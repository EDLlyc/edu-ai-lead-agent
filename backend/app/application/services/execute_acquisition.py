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
from app.domain.freshness import FreshnessDecision, evaluate_publication_freshness
from app.domain.science_relevance import (
    SCIENCE_CONTENT_CHARACTER_LIMIT,
    SCIENCE_RELEVANCE_RULE_VERSION,
    ScienceRelevanceResult,
    evaluate_moe_science_relevance,
)
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
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._fetcher = fetcher
        self._snapshot_store = snapshot_store
        self._settings = settings
        self._sleep = sleep
        self._jitter = jitter
        self._clock = clock

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
        freshness_filtered_count = 0
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
            await self._wait_for_source_request(claimed, lease_lost)
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
                accepted_items: list[
                    tuple[DiscoveredItem, TitleRelevanceResult | ScienceRelevanceResult | None]
                ]
                accepted_items = []
                freshness_evaluated_at = self._clock()
                if claimed.profile.relevance_rule_version is None:
                    relevant_count = scanned_count
                    deferred_relevant_count = max(0, relevant_count - accepted_limit)
                    accepted_items.extend((item, None) for item in scanned_items[:accepted_limit])
                elif claimed.profile.relevance_rule_version == TITLE_RELEVANCE_RULE_VERSION:
                    title_evaluated_items = [
                        (item, evaluate_title_relevance(item.title)) for item in scanned_items
                    ]
                    relevant_items = [
                        (item, relevance)
                        for item, relevance in title_evaluated_items
                        if relevance.is_relevant
                    ]
                    relevant_count = len(relevant_items)
                    title_filtered_count = scanned_count - relevant_count
                    fresh_relevant_items: list[tuple[DiscoveredItem, TitleRelevanceResult]] = []
                    for item, relevance in relevant_items:
                        freshness = evaluate_publication_freshness(
                            item.published_at,
                            evaluated_at=freshness_evaluated_at,
                            max_age_days=self._settings.acquisition_freshness_window_days,
                        )
                        if freshness.status == "stale":
                            freshness_filtered_count += 1
                            filtered_count += 1
                            await self._repository.observe(
                                claimed=claimed,
                                source_item_id=item.source_item_id,
                                outcome=ObservationOutcome.STALE,
                                metadata=_freshness_metadata(freshness),
                            )
                            continue
                        fresh_relevant_items.append((item, relevance))
                    filtered_count += title_filtered_count
                    accepted_items.extend(fresh_relevant_items[:accepted_limit])
                    deferred_relevant_count = len(fresh_relevant_items) - len(accepted_items)
                    if relevant_count == 0:
                        job_outcome = ObservationOutcome.NO_RELEVANT_ITEMS.value
                elif claimed.profile.relevance_rule_version == SCIENCE_RELEVANCE_RULE_VERSION:
                    science_evaluated_items: list[tuple[DiscoveredItem, ScienceRelevanceResult]] = [
                        (item, evaluate_moe_science_relevance(item.title, None))
                        for item in scanned_items
                    ]
                    title_matches = [
                        (item, relevance)
                        for item, relevance in science_evaluated_items
                        if relevance.matched_title_terms
                    ]
                    title_neutral = [
                        (item, relevance)
                        for item, relevance in science_evaluated_items
                        if not relevance.matched_title_terms
                    ]
                    ordered_items = [*title_matches, *title_neutral]
                    accepted_items.extend(ordered_items[:accepted_limit])
                    accepted_title_match_count = sum(
                        bool(relevance.matched_title_terms)
                        for _, relevance in accepted_items
                        if isinstance(relevance, ScienceRelevanceResult)
                    )
                    deferred_relevant_count = max(
                        0, len(title_matches) - accepted_title_match_count
                    )
                else:
                    raise ParseError("relevance rule version is not installed")

                # Discovery dates are authoritative enough to skip stale detail requests. An
                # unknown date is retained for the bounded detail fetch so the connector can try
                # to resolve it; unknown remains excluded if the detail page also has no date.
                prechecked_items: list[
                    tuple[DiscoveredItem, TitleRelevanceResult | ScienceRelevanceResult | None]
                ] = []
                for item, relevance_value in accepted_items:
                    freshness = evaluate_publication_freshness(
                        item.published_at,
                        evaluated_at=freshness_evaluated_at,
                        max_age_days=self._settings.acquisition_freshness_window_days,
                    )
                    if freshness.status == "stale":
                        if claimed.profile.relevance_rule_version in {
                            None,
                            SCIENCE_RELEVANCE_RULE_VERSION,
                        }:
                            freshness_filtered_count += 1
                            filtered_count += 1
                            metadata = _freshness_metadata(freshness)
                            if isinstance(relevance_value, ScienceRelevanceResult):
                                metadata = {
                                    **_science_relevance_metadata(relevance_value),
                                    **metadata,
                                }
                            await self._repository.observe(
                                claimed=claimed,
                                source_item_id=item.source_item_id,
                                outcome=ObservationOutcome.STALE,
                                metadata=metadata,
                            )
                        continue
                    prechecked_items.append((item, relevance_value))
                accepted_items = prechecked_items

                for item, relevance_value in accepted_items:
                    await self._wait_for_source_request(claimed, lease_lost)
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
                    freshness = evaluate_publication_freshness(
                        document.published_at,
                        evaluated_at=freshness_evaluated_at,
                        max_age_days=self._settings.acquisition_freshness_window_days,
                    )
                    relevance_metadata: dict[str, object] = {}
                    science_relevance: ScienceRelevanceResult | None = None
                    if claimed.profile.relevance_rule_version == SCIENCE_RELEVANCE_RULE_VERSION:
                        science_relevance = evaluate_moe_science_relevance(
                            document.title, document.clean_text
                        )
                        relevance_metadata = _science_relevance_metadata(science_relevance)
                    elif isinstance(relevance_value, TitleRelevanceResult):
                        relevance_metadata = {
                            "relevance_rule_version": relevance_value.rule_version,
                            "matched_title_terms": list(relevance_value.matched_terms),
                        }
                    elif isinstance(relevance_value, ScienceRelevanceResult):
                        relevance_metadata = _science_relevance_metadata(relevance_value)
                    if relevance_metadata:
                        document = replace(
                            document,
                            extraction_metadata={
                                **document.extraction_metadata,
                                **relevance_metadata,
                            },
                        )
                    if freshness.status != "fresh":
                        freshness_filtered_count += 1
                        filtered_count += 1
                        await self._repository.observe(
                            claimed=claimed,
                            source_item_id=item.source_item_id,
                            outcome=(
                                ObservationOutcome.STALE
                                if freshness.status == "stale"
                                else ObservationOutcome.FRESHNESS_UNKNOWN
                            ),
                            snapshot_id=snapshot_id,
                            http_status=detail_response.status_code,
                            metadata={**relevance_metadata, **_freshness_metadata(freshness)},
                        )
                        continue
                    if science_relevance is not None and not science_relevance.is_relevant:
                        filtered_count += 1
                        await self._repository.observe(
                            claimed=claimed,
                            source_item_id=item.source_item_id,
                            outcome=ObservationOutcome.FILTERED,
                            snapshot_id=snapshot_id,
                            http_status=detail_response.status_code,
                            metadata=relevance_metadata,
                        )
                        continue
                    if science_relevance is not None:
                        relevant_count += 1
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
                    if claimed.profile.relevance_rule_version == SCIENCE_RELEVANCE_RULE_VERSION:
                        filter_metadata.update(
                            {
                                "title_match_count": sum(
                                    isinstance(relevance, ScienceRelevanceResult)
                                    and bool(relevance.matched_title_terms)
                                    for _, relevance in accepted_items
                                ),
                                "detail_probe_limit": accepted_limit,
                                "deferred_detail_count": max(
                                    0, len(scanned_items) - accepted_limit
                                ),
                                "content_character_limit": SCIENCE_CONTENT_CHARACTER_LIMIT,
                            }
                        )
                        if relevant_count == 0:
                            job_outcome = ObservationOutcome.NO_RELEVANT_ITEMS.value
                    if freshness_filtered_count:
                        filter_metadata.update(
                            {
                                "freshness_filtered_count": freshness_filtered_count,
                                "freshness_window_days": (
                                    self._settings.acquisition_freshness_window_days
                                ),
                            }
                        )
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
                delay = (
                    error.retry_after_seconds if isinstance(error, TransientFetchError) else None
                )
                if delay is None:
                    delay = min(300.0, 2 ** (claimed.attempt_number - 1) + self._jitter())
                else:
                    delay = min(self._settings.acquisition_max_retry_after_seconds, delay)
                retry_at = self._clock() + timedelta(seconds=delay)
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

    async def _wait_for_source_request(
        self, claimed: ClaimedJob, lease_lost: asyncio.Event
    ) -> None:
        delay = await self._repository.reserve_source_request_slot(
            claimed=claimed,
            minimum_interval_seconds=claimed.profile.rate_limit_seconds,
        )
        if delay > 0:
            await self._sleep(delay)
        self._ensure_lease(lease_lost)

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


def _freshness_metadata(decision: FreshnessDecision) -> dict[str, object]:
    # Keep the persisted audit projection small and content-free.
    return {
        "freshness_rule_version": decision.rule_version,
        "freshness_reason": decision.reason_code,
        "cutoff_at": decision.cutoff_at.isoformat(),
        "published_at": decision.published_at.isoformat() if decision.published_at else None,
    }


def _science_relevance_metadata(result: ScienceRelevanceResult) -> dict[str, object]:
    return {
        "relevance_rule_version": result.rule_version,
        "matched_title_terms": list(result.matched_title_terms),
        "matched_content_terms": list(result.matched_content_terms),
        "matched_terms": list(result.matched_terms),
        "content_characters_considered": result.content_characters_considered,
        "content_truncated": result.content_truncated,
    }
