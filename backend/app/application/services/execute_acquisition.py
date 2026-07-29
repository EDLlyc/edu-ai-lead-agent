from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import structlog

from app.application.ports.acquisition import (
    AcquisitionRepository,
    ClaimedJob,
    Fetcher,
    SnapshotStore,
)
from app.core.config import Settings
from app.core.errors import (
    AppError,
    LeaseLostError,
    ParseError,
    PermanentFetchError,
    PolicyRejectedError,
    ResponseLimitError,
    TransientFetchError,
    UnsupportedContentError,
)
from app.domain.entities import DiscoveredItem
from app.domain.enums import JobStatus, ObservationOutcome
from app.domain.title_relevance import (
    TITLE_RELEVANCE_RULE_VERSION,
    TitleRelevanceResult,
    evaluate_title_relevance,
)
from app.infrastructure.ingestion.connectors import get_connector

logger = structlog.get_logger()


class AcquisitionExecutor:
    def __init__(
        self,
        repository: AcquisitionRepository,
        fetcher: Fetcher,
        snapshot_store: SnapshotStore,
        settings: Settings,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._repository = repository
        self._fetcher = fetcher
        self._snapshot_store = snapshot_store
        self._settings = settings
        self._sleep = sleep
        self._jitter = jitter

    async def execute_next(self, worker_id: str) -> bool:
        claimed = await self._repository.claim(
            worker_id=worker_id, lease_seconds=self._settings.acquisition_lease_seconds
        )
        if claimed is None:
            return False
        attempt_id = await self._repository.create_attempt(claimed)
        byte_count = 0
        item_count = 0
        new_count = 0
        unchanged_count = 0
        duplicate_count = 0
        filtered_count = 0
        scanned_count = 0
        relevant_count = 0
        deferred_relevant_count = 0
        job_outcome = "succeeded"
        heartbeat_stop = asyncio.Event()
        lease_lost = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(claimed, heartbeat_stop, lease_lost)
        )
        source_lease = False
        try:
            source_lease = await self._repository.acquire_source_lease(
                claimed=claimed,
                owner=worker_id,
                lease_seconds=self._settings.acquisition_lease_seconds,
            )
            if not source_lease:
                raise TransientFetchError("source_busy", "source already has an active fetch")
            self._ensure_lease(lease_lost)
            cursor = await self._repository.cursor(claimed.profile.source_version_id)
            list_response = await self._fetcher.fetch(
                claimed.profile.entry_url,
                claimed.profile,
                etag=cursor.etag,
                last_modified=cursor.last_modified,
            )
            self._ensure_lease(lease_lost)
            if list_response.status_code == 304:
                await self._repository.observe(
                    claimed=claimed,
                    source_item_id=None,
                    outcome=ObservationOutcome.NOT_MODIFIED,
                    http_status=304,
                )
                unchanged_count = 1
            else:
                byte_count += len(list_response.body)
                stored_list = await self._snapshot_store.put_immutable(
                    list_response.body, list_response.media_type or "application/octet-stream"
                )
                self._ensure_lease(lease_lost)
                await self._repository.save_snapshot(
                    claimed=claimed,
                    profile=claimed.profile,
                    kind="list",
                    response=list_response,
                    stored=stored_list,
                )
                connector = get_connector(claimed.profile.connector_key)
                accepted_limit = (
                    self._settings.acquisition_first_run_item_limit
                    if cursor.last_item_id is None
                    else self._settings.acquisition_daily_item_limit
                )
                scan_limit = (
                    self._settings.acquisition_first_run_scan_limit
                    if cursor.last_item_id is None
                    else self._settings.acquisition_daily_scan_limit
                )
                scanned_items = connector.discover(list_response, claimed.profile, limit=scan_limit)
                scanned_count = len(scanned_items)
                accepted_items: list[tuple[DiscoveredItem, TitleRelevanceResult | None]]
                accepted_items = []
                if claimed.profile.relevance_rule_version is None:
                    relevant_count = scanned_count
                    deferred_relevant_count = max(0, relevant_count - accepted_limit)
                    accepted_items.extend((item, None) for item in scanned_items[:accepted_limit])
                else:
                    if claimed.profile.relevance_rule_version != TITLE_RELEVANCE_RULE_VERSION:
                        raise ParseError("title relevance rule version is not installed")
                    evaluated_items = [
                        (item, evaluate_title_relevance(item.title)) for item in scanned_items
                    ]
                    relevant_items = [
                        (item, relevance)
                        for item, relevance in evaluated_items
                        if relevance.is_relevant
                    ]
                    relevant_count = len(relevant_items)
                    filtered_count = scanned_count - relevant_count
                    accepted_items.extend(relevant_items[:accepted_limit])
                    deferred_relevant_count = relevant_count - len(accepted_items)
                    if relevant_count == 0:
                        job_outcome = ObservationOutcome.NO_RELEVANT_ITEMS.value

                for item, relevance in accepted_items:
                    # The list request is also a source request, so the first
                    # detail fetch must respect the same inter-request rate.
                    if claimed.profile.rate_limit_seconds > 0:
                        await self._sleep(claimed.profile.rate_limit_seconds)
                    self._ensure_lease(lease_lost)
                    detail_response = await self._fetcher.fetch(item.url, claimed.profile)
                    self._ensure_lease(lease_lost)
                    byte_count += len(detail_response.body)
                    stored_detail = await self._snapshot_store.put_immutable(
                        detail_response.body,
                        detail_response.media_type or "application/octet-stream",
                    )
                    self._ensure_lease(lease_lost)
                    snapshot_id = await self._repository.save_snapshot(
                        claimed=claimed,
                        profile=claimed.profile,
                        kind="detail",
                        response=detail_response,
                        stored=stored_detail,
                    )
                    document = connector.extract(detail_response, item, claimed.profile)
                    relevance_metadata: dict[str, object] = {}
                    if relevance is not None:
                        relevance_metadata = {
                            "relevance_rule_version": relevance.rule_version,
                            "matched_title_terms": list(relevance.matched_terms),
                        }
                        document = replace(
                            document,
                            extraction_metadata={
                                **document.extraction_metadata,
                                **relevance_metadata,
                            },
                        )
                    persisted = await self._repository.save_candidate(
                        claimed=claimed,
                        profile=claimed.profile,
                        document=document,
                        snapshot_id=snapshot_id,
                        fetched_at=detail_response.fetched_at,
                    )
                    await self._repository.observe(
                        claimed=claimed,
                        source_item_id=item.source_item_id,
                        outcome=persisted.outcome,
                        snapshot_id=snapshot_id,
                        candidate_id=persisted.candidate_id,
                        http_status=detail_response.status_code,
                        metadata=relevance_metadata,
                    )
                    item_count += 1
                    if persisted.outcome is ObservationOutcome.NEW:
                        new_count += 1
                    elif persisted.outcome is ObservationOutcome.EXACT_DUPLICATE:
                        duplicate_count += 1
                    else:
                        unchanged_count += 1
                if claimed.profile.relevance_rule_version is not None:
                    filter_metadata = {
                        "scanned_count": scanned_count,
                        "relevant_count": relevant_count,
                        "accepted_count": len(accepted_items),
                        "filtered_count": filtered_count,
                        "deferred_relevant_count": deferred_relevant_count,
                        "relevance_rule_version": claimed.profile.relevance_rule_version,
                    }
                    if relevant_count == 0:
                        await self._repository.observe(
                            claimed=claimed,
                            source_item_id=None,
                            outcome=ObservationOutcome.NO_RELEVANT_ITEMS,
                            metadata=filter_metadata,
                        )
                    elif filtered_count > 0 or deferred_relevant_count > 0:
                        await self._repository.observe(
                            claimed=claimed,
                            source_item_id=None,
                            outcome=ObservationOutcome.FILTERED,
                            metadata=filter_metadata,
                        )
                last_item = scanned_items[0] if scanned_items else None
                await self._repository.save_cursor(
                    claimed=claimed,
                    source_version_id=claimed.profile.source_version_id,
                    etag=list_response.headers.get("etag"),
                    last_modified=list_response.headers.get("last-modified"),
                    last_item_id=last_item.source_item_id if last_item else cursor.last_item_id,
                    last_published_at=(
                        last_item.published_at if last_item else cursor.last_published_at
                    ),
                )
            await self._repository.complete_attempt(
                claimed=claimed,
                attempt_id=attempt_id,
                result="succeeded",
                error_code=None,
                byte_count=byte_count,
                item_count=item_count,
            )
            completed = await self._repository.complete_job(
                claimed=claimed,
                status=JobStatus.SUCCEEDED,
                outcome=job_outcome,
                error_code=None,
                new_count=new_count,
                unchanged_count=unchanged_count,
                duplicate_count=duplicate_count,
                filtered_count=filtered_count,
                byte_count=byte_count,
            )
            if not completed:
                raise LeaseLostError()
            logger.info(
                "acquisition_job_succeeded",
                acquisition_run_id=str(claimed.run_id),
                job_id=str(claimed.job_id),
                source_id=str(claimed.profile.source_id),
                connector_version=claimed.profile.connector_version,
                parser_version=claimed.profile.parser_version,
                byte_count=byte_count,
                item_count=item_count,
                scanned_count=scanned_count,
                relevant_count=relevant_count,
                filtered_count=filtered_count,
                deferred_relevant_count=deferred_relevant_count,
            )
        except LeaseLostError:
            logger.warning(
                "acquisition_job_lease_lost",
                acquisition_run_id=str(claimed.run_id),
                job_id=str(claimed.job_id),
                source_id=str(claimed.profile.source_id),
            )
        except AppError as error:
            outcome = _outcome_for_error(error)
            await self._repository.observe(
                claimed=claimed,
                source_item_id=None,
                outcome=outcome,
                error_code=error.code,
            )
            await self._repository.complete_attempt(
                claimed=claimed,
                attempt_id=attempt_id,
                result=outcome.value,
                error_code=error.code,
                byte_count=byte_count,
                item_count=item_count,
            )
            should_retry = (
                error.retryable and claimed.attempt_number < self._settings.acquisition_max_attempts
            )
            retry_at = None
            status = JobStatus.FAILED
            if should_retry:
                delay = min(300.0, 2 ** (claimed.attempt_number - 1) + self._jitter())
                retry_at = datetime.now(UTC) + timedelta(seconds=delay)
                status = JobStatus.RETRY_SCHEDULED
            completed = await self._repository.complete_job(
                claimed=claimed,
                status=status,
                outcome=outcome.value,
                error_code=error.code,
                new_count=new_count,
                unchanged_count=unchanged_count,
                duplicate_count=duplicate_count,
                filtered_count=filtered_count,
                byte_count=byte_count,
                retry_at=retry_at,
            )
            if not completed:
                logger.warning(
                    "acquisition_job_lease_lost",
                    acquisition_run_id=str(claimed.run_id),
                    job_id=str(claimed.job_id),
                    source_id=str(claimed.profile.source_id),
                )
            logger.warning(
                "acquisition_job_failed",
                acquisition_run_id=str(claimed.run_id),
                job_id=str(claimed.job_id),
                source_id=str(claimed.profile.source_id),
                error_code=error.code,
                retryable=should_retry,
            )
        except Exception:
            internal_error = AppError(
                "internal_worker_error", "acquisition worker failed unexpectedly"
            )
            await self._repository.observe(
                claimed=claimed,
                source_item_id=None,
                outcome=ObservationOutcome.PERMANENT_FETCH_FAILURE,
                error_code=internal_error.code,
            )
            await self._repository.complete_attempt(
                claimed=claimed,
                attempt_id=attempt_id,
                result="failed",
                error_code=internal_error.code,
                byte_count=byte_count,
                item_count=item_count,
            )
            completed = await self._repository.complete_job(
                claimed=claimed,
                status=JobStatus.FAILED,
                outcome=ObservationOutcome.PERMANENT_FETCH_FAILURE.value,
                error_code=internal_error.code,
                new_count=new_count,
                unchanged_count=unchanged_count,
                duplicate_count=duplicate_count,
                filtered_count=filtered_count,
                byte_count=byte_count,
            )
            if not completed:
                logger.warning(
                    "acquisition_job_lease_lost",
                    acquisition_run_id=str(claimed.run_id),
                    job_id=str(claimed.job_id),
                    source_id=str(claimed.profile.source_id),
                )
            logger.error(
                "acquisition_job_internal_failure",
                acquisition_run_id=str(claimed.run_id),
                job_id=str(claimed.job_id),
                source_id=str(claimed.profile.source_id),
            )
        finally:
            heartbeat_stop.set()
            await heartbeat_task
            if source_lease:
                await self._repository.release_source_lease(claimed)
        return True

    @staticmethod
    def _ensure_lease(lease_lost: asyncio.Event) -> None:
        if lease_lost.is_set():
            raise LeaseLostError()

    async def _heartbeat_loop(
        self, claimed: ClaimedJob, stop: asyncio.Event, lease_lost: asyncio.Event
    ) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=self._settings.acquisition_heartbeat_seconds
                )
                return
            except TimeoutError:
                try:
                    renewed = await self._repository.heartbeat(
                        claimed=claimed,
                        lease_seconds=self._settings.acquisition_lease_seconds,
                    )
                except Exception:
                    lease_lost.set()
                    logger.error(
                        "acquisition_heartbeat_failed",
                        job_id=str(claimed.job_id),
                        source_id=str(claimed.profile.source_id),
                        error_code="heartbeat_dependency_failure",
                    )
                    return
                if not renewed:
                    lease_lost.set()
                    return


def _outcome_for_error(error: AppError) -> ObservationOutcome:
    if isinstance(error, ResponseLimitError):
        return ObservationOutcome.RESPONSE_LIMIT_REJECTION
    if isinstance(error, UnsupportedContentError):
        return ObservationOutcome.UNSUPPORTED_CONTENT
    if isinstance(error, PolicyRejectedError):
        return ObservationOutcome.POLICY_REJECTION
    if isinstance(error, ParseError):
        return ObservationOutcome.PARSE_FAILURE
    if isinstance(error, TransientFetchError):
        return ObservationOutcome.TRANSIENT_FETCH_FAILURE
    if isinstance(error, PermanentFetchError):
        return ObservationOutcome.PERMANENT_FETCH_FAILURE
    return ObservationOutcome.PERMANENT_FETCH_FAILURE
