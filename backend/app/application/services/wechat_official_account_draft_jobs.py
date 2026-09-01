"""Durable enqueue, reconciliation, and execution for WeChat draft-only jobs."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

import structlog

from app.application.ports.wechat_official_account import (
    WeChatDraftArticleRequest,
    WeChatDraftCreated,
    WeChatInlineImage,
    WeChatMpEndpoint,
    WeChatOfficialAccountDraftClient,
    WeChatOfficialAccountError,
    WeChatThumbMedia,
)
from app.application.ports.wechat_official_account_draft_artifacts import (
    WeChatDraftArtifactBatch,
    WeChatDraftArtifactStore,
)
from app.application.ports.wechat_official_account_draft_jobs import (
    WeChatOfficialAccountDraftJobRepository,
)
from app.application.services.official_account_weekly_edition import (
    FinalizedWeeklyEdition,
    load_finalized_weekly_edition,
)
from app.application.services.wechat_official_account_draft import (
    WeChatDraftLocalSource,
    WeChatOfficialAccountDraftOnlyService,
    WeChatOfficialAccountDraftPreparer,
    WeChatPreparedDraft,
)
from app.domain.official_account_weekly_edition import WeeklyArticleRole
from app.domain.wechat_official_account_draft_jobs import (
    WeChatDraftJobClaim,
    WeChatDraftJobEnqueue,
    WeChatDraftJobFailure,
    WeChatDraftJobItemInput,
    WeChatDraftStatusProjection,
    draft_media_fingerprint,
    wechat_draft_policy_fingerprint,
)

logger = structlog.get_logger()

_PREPARATION_ERROR = "wechat_mp_draft_preparation_invalid"
_INTERNAL_ERROR = "wechat_mp_draft_internal"
_LEASE_LOST_AFTER_SIDE_EFFECT = "lease_lost_after_side_effect"
_OUTCOME_UNKNOWN = "wechat_mp_outcome_unknown"
_FINAL_ENDPOINT: WeChatMpEndpoint = "draft_add"


class WeChatDraftPreparer(Protocol):
    def prepare_weekly(
        self,
        sources: tuple[
            WeChatDraftLocalSource,
            WeChatDraftLocalSource,
            WeChatDraftLocalSource,
        ],
    ) -> tuple[WeChatPreparedDraft, WeChatPreparedDraft, WeChatPreparedDraft]: ...


@dataclass(frozen=True, slots=True)
class WeChatDraftEnqueueResult:
    status: WeChatDraftStatusProjection
    created: bool

    def as_dict(self) -> dict[str, object]:
        return {**self.status.as_dict(), "created": self.created}


@dataclass(frozen=True, slots=True)
class WeChatDraftReconcileResult:
    discovered: int
    enqueued: int
    existing: int
    skipped_by_code: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "discovered": self.discovered,
            "enqueued": self.enqueued,
            "existing": self.existing,
            "skipped_by_code": dict(sorted(self.skipped_by_code.items())),
        }


class WeChatOfficialAccountDraftJobService:
    """Strictly stage and idempotently enqueue live weekly draft batches."""

    def __init__(
        self,
        *,
        repository: WeChatOfficialAccountDraftJobRepository,
        artifact_store: WeChatDraftArtifactStore,
        account_fingerprint: str,
        max_attempts: int,
        max_image_bytes: int,
        clock: Callable[[], datetime] | None = None,
        preparer: WeChatDraftPreparer | None = None,
        weekly_loader: Callable[[Path], FinalizedWeeklyEdition] = load_finalized_weekly_edition,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store
        self._account_fingerprint = account_fingerprint
        self._max_attempts = max_attempts
        self._clock = clock or (lambda: datetime.now(UTC))
        self._preparer = preparer or WeChatOfficialAccountDraftPreparer(
            max_image_bytes=max_image_bytes
        )
        self._weekly_loader = weekly_loader

    async def enqueue_weekly(self, source_directory: Path) -> WeChatDraftEnqueueResult:
        """Preflight the source, stage it immutably, and enqueue the canonical batch."""

        edition = self._weekly_loader(source_directory)
        self._prepare_original(edition)
        batch = self._artifact_store.stage_weekly(source_directory)
        return await self.enqueue_staged(batch)

    async def enqueue_staged(
        self,
        batch: WeChatDraftArtifactBatch,
    ) -> WeChatDraftEnqueueResult:
        prepared = self._resolve_and_prepare(batch)
        items: list[WeChatDraftJobItemInput] = []
        for source, draft in zip(batch.sources, prepared, strict=True):
            if (
                source.role != draft.role
                or source.article_fingerprint != draft.article_fingerprint
                or source.content_fingerprint != draft.content_fingerprint
            ):
                raise ValueError("staged WeChat draft preparation identity changed")
            items.append(
                WeChatDraftJobItemInput(
                    role=WeeklyArticleRole(source.role),
                    ordinal=source.ordinal,
                    source_ref=source.source_ref,
                    source_fingerprint=source.source_fingerprint,
                    article_fingerprint=source.article_fingerprint,
                    content_fingerprint=source.content_fingerprint,
                    policy_fingerprint=wechat_draft_policy_fingerprint(
                        content_source_url=None,
                        need_open_comment=False,
                        only_fans_can_comment=False,
                    ),
                )
            )
        command = WeChatDraftJobEnqueue(
            account_fingerprint=self._account_fingerprint,
            aggregate_fingerprint=batch.aggregate_fingerprint,
            batch_fingerprint=batch.batch_fingerprint,
            items=cast(
                tuple[
                    WeChatDraftJobItemInput,
                    WeChatDraftJobItemInput,
                    WeChatDraftJobItemInput,
                ],
                tuple(items),
            ),
            max_attempts=self._max_attempts,
        )
        status, created = await self._repository.enqueue(command, now=self._now())
        logger.info(
            "wechat_mp_draft_job_enqueued",
            job_id=str(status.job.job_id),
            created=created,
            status=status.job.status.value,
        )
        return WeChatDraftEnqueueResult(status=status, created=created)

    async def reconcile(self, *, maximum: int = 100) -> WeChatDraftReconcileResult:
        discovery = self._artifact_store.discover_weekly(maximum=maximum)
        skipped = Counter(discovery.skipped_by_code)
        enqueued = 0
        existing = 0
        for batch in discovery.batches:
            try:
                result = await self.enqueue_staged(batch)
            except WeChatDraftJobFailure as exc:
                skipped[exc.error_code] += 1
                continue
            except ValueError:
                skipped[_PREPARATION_ERROR] += 1
                continue
            if result.created:
                enqueued += 1
            else:
                existing += 1
        outcome = WeChatDraftReconcileResult(
            discovered=len(discovery.batches),
            enqueued=enqueued,
            existing=existing,
            skipped_by_code=dict(skipped),
        )
        logger.info("wechat_mp_draft_reconciled", **outcome.as_dict())
        return outcome

    def _prepare_original(self, edition: FinalizedWeeklyEdition) -> None:
        sources = tuple(
            WeChatDraftLocalSource(
                directory=(
                    edition.directory / f"articles/{child.role.ordinal:02d}-{child.role.value}"
                ),
                role=child.role.value,
            )
            for child in edition.children
        )
        prepared = self._preparer.prepare_weekly(
            cast(
                tuple[
                    WeChatDraftLocalSource,
                    WeChatDraftLocalSource,
                    WeChatDraftLocalSource,
                ],
                sources,
            )
        )
        for child, draft in zip(edition.children, prepared, strict=True):
            if (
                child.role.value != draft.role
                or child.article_fingerprint != draft.article_fingerprint
                or child.content_fingerprint != draft.content_fingerprint
            ):
                raise ValueError("weekly WeChat draft preparation identity changed")

    def _resolve_and_prepare(
        self,
        batch: WeChatDraftArtifactBatch,
    ) -> tuple[WeChatPreparedDraft, WeChatPreparedDraft, WeChatPreparedDraft]:
        local_sources: list[WeChatDraftLocalSource] = []
        for source in batch.sources:
            resolved = self._artifact_store.resolve(source.source_ref)
            if (
                resolved.source != source
                or resolved.batch_fingerprint != batch.batch_fingerprint
                or resolved.aggregate_fingerprint != batch.aggregate_fingerprint
            ):
                raise ValueError("resolved WeChat draft artifact identity changed")
            local_sources.append(
                WeChatDraftLocalSource(directory=resolved.directory, role=source.role)
            )
        return self._preparer.prepare_weekly(
            cast(
                tuple[
                    WeChatDraftLocalSource,
                    WeChatDraftLocalSource,
                    WeChatDraftLocalSource,
                ],
                tuple(local_sources),
            )
        )

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("WeChat draft clock must be timezone-aware")
        return now


class WeChatOfficialAccountDraftJobExecutor:
    """Execute one fenced child while conservatively classifying external writes."""

    def __init__(
        self,
        *,
        repository: WeChatOfficialAccountDraftJobRepository,
        artifact_store: WeChatDraftArtifactStore,
        client: WeChatOfficialAccountDraftClient,
        lease_seconds: int,
        heartbeat_seconds: int,
        retry_base_seconds: int,
        max_image_bytes: int,
        clock: Callable[[], datetime] | None = None,
        preparer: WeChatDraftPreparer | None = None,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store
        self._client = client
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._retry_base_seconds = retry_base_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._preparer = preparer or WeChatOfficialAccountDraftPreparer(
            max_image_bytes=max_image_bytes
        )

    async def execute_next(self, worker_id: str) -> WeChatDraftStatusProjection | None:
        claim = await self._repository.claim_next(
            worker_id=worker_id,
            now=self._now(),
            lease_seconds=self._lease_seconds,
        )
        if claim is None:
            return None
        heartbeat_stop = asyncio.Event()
        lease_lost = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat_loop(
                claim=claim,
                stop=heartbeat_stop,
                lease_lost=lease_lost,
            )
        )
        side_effect_started = False
        observed = _ObservedWeChatDraftClient(self._client)
        try:
            prepared = await self._preflight_claim(claim)
            if lease_lost.is_set():
                return await self._safe_current_status(claim)
            first_endpoint: WeChatMpEndpoint = (
                "media_uploadimg" if prepared.body_media else "material_add_thumb"
            )
            side_effect_started = await self._repository.mark_side_effect_started(
                claim,
                endpoint=first_endpoint,
                now=self._now(),
            )
            if not side_effect_started:
                return await self._safe_current_status(claim)
            if lease_lost.is_set():
                return await self._outcome_unknown(
                    claim,
                    endpoint=first_endpoint,
                    uploaded_image_count=0,
                    error_code=_LEASE_LOST_AFTER_SIDE_EFFECT,
                )
            service = WeChatOfficialAccountDraftOnlyService(
                client=observed,
                clock=self._clock,
            )
            receipt = await service.create_prepared(prepared)
            if lease_lost.is_set():
                return await self._outcome_unknown(
                    claim,
                    endpoint=observed.endpoint,
                    uploaded_image_count=observed.uploaded_image_count,
                    error_code=_LEASE_LOST_AFTER_SIDE_EFFECT,
                )
            try:
                status = await self._repository.succeed(
                    claim,
                    endpoint=_FINAL_ENDPOINT,
                    uploaded_image_count=receipt.uploaded_image_count,
                    draft_media_fingerprint=draft_media_fingerprint(receipt.draft_media_id),
                    now=self._now(),
                )
            except WeChatDraftJobFailure:
                return await self._outcome_unknown(
                    claim,
                    endpoint=_FINAL_ENDPOINT,
                    uploaded_image_count=receipt.uploaded_image_count,
                    error_code=_LEASE_LOST_AFTER_SIDE_EFFECT,
                )
            logger.info(
                "wechat_mp_draft_item_succeeded",
                job_id=str(claim.job.job_id),
                role=claim.item.role.value,
                uploaded_image_count=receipt.uploaded_image_count,
                status=status.job.status.value,
            )
            return status
        except asyncio.CancelledError:
            if side_effect_started:
                await self._shield_outcome_unknown(
                    claim,
                    endpoint=observed.endpoint,
                    uploaded_image_count=observed.uploaded_image_count,
                    error_code=_OUTCOME_UNKNOWN,
                )
            raise
        except WeChatOfficialAccountError as exc:
            if side_effect_started and (lease_lost.is_set() or exc.unknown):
                return await self._outcome_unknown(
                    claim,
                    endpoint=exc.endpoint or observed.endpoint,
                    uploaded_image_count=observed.uploaded_image_count,
                    error_code=exc.code,
                )
            return await self._known_failure_or_lease_loss(
                claim,
                error_code=exc.code,
                endpoint=exc.endpoint or observed.endpoint,
                retryable=exc.retryable,
                uploaded_image_count=observed.uploaded_image_count,
                side_effect_started=side_effect_started,
            )
        except (OSError, ValueError) as exc:
            del exc
            if side_effect_started:
                return await self._outcome_unknown(
                    claim,
                    endpoint=observed.endpoint,
                    uploaded_image_count=observed.uploaded_image_count,
                    error_code=_OUTCOME_UNKNOWN,
                )
            return await self._known_failure_or_lease_loss(
                claim,
                error_code=_PREPARATION_ERROR,
                endpoint=None,
                retryable=False,
                uploaded_image_count=0,
                side_effect_started=False,
            )
        except Exception:
            if side_effect_started:
                return await self._outcome_unknown(
                    claim,
                    endpoint=observed.endpoint,
                    uploaded_image_count=observed.uploaded_image_count,
                    error_code=_OUTCOME_UNKNOWN,
                )
            return await self._known_failure_or_lease_loss(
                claim,
                error_code=_INTERNAL_ERROR,
                endpoint=None,
                retryable=False,
                uploaded_image_count=0,
                side_effect_started=False,
            )
        finally:
            heartbeat_stop.set()
            await heartbeat

    async def _preflight_claim(self, claim: WeChatDraftJobClaim) -> WeChatPreparedDraft:
        status = await self._repository.get_status(claim.job.job_id)
        local_sources: list[WeChatDraftLocalSource] = []
        for item in status.items:
            resolved = self._artifact_store.resolve(item.source_ref)
            source = resolved.source
            if (
                source.role != item.role.value
                or source.ordinal != item.ordinal
                or source.source_fingerprint != item.source_fingerprint
                or source.article_fingerprint != item.article_fingerprint
                or source.content_fingerprint != item.content_fingerprint
                or resolved.aggregate_fingerprint != status.job.aggregate_fingerprint
                or resolved.batch_fingerprint != status.job.batch_fingerprint
            ):
                raise ValueError("claimed WeChat draft artifact identity changed")
            local_sources.append(
                WeChatDraftLocalSource(directory=resolved.directory, role=source.role)
            )
        prepared = self._preparer.prepare_weekly(
            cast(
                tuple[
                    WeChatDraftLocalSource,
                    WeChatDraftLocalSource,
                    WeChatDraftLocalSource,
                ],
                tuple(local_sources),
            )
        )
        for item, draft in zip(status.items, prepared, strict=True):
            if (
                item.role.value != draft.role
                or item.article_fingerprint != draft.article_fingerprint
                or item.content_fingerprint != draft.content_fingerprint
                or item.policy_fingerprint
                != wechat_draft_policy_fingerprint(
                    content_source_url=draft.content_source_url,
                    need_open_comment=draft.need_open_comment,
                    only_fans_can_comment=draft.only_fans_can_comment,
                )
            ):
                raise ValueError("claimed WeChat draft preparation identity changed")
        return prepared[claim.item.ordinal - 1]

    async def _heartbeat_loop(
        self,
        *,
        claim: WeChatDraftJobClaim,
        stop: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._heartbeat_seconds)
            except TimeoutError:
                try:
                    owned = await self._repository.heartbeat(
                        claim,
                        now=self._now(),
                        lease_seconds=self._lease_seconds,
                    )
                except Exception:
                    lease_lost.set()
                    return
                if not owned:
                    lease_lost.set()
                    return

    async def _known_failure(
        self,
        claim: WeChatDraftJobClaim,
        *,
        error_code: str,
        endpoint: WeChatMpEndpoint | None,
        retryable: bool,
        uploaded_image_count: int,
    ) -> WeChatDraftStatusProjection:
        now = self._now()
        delay = self._retry_base_seconds * (2 ** min(claim.item.attempt_count - 1, 8))
        status = await self._repository.fail_known(
            claim,
            error_code=error_code,
            endpoint=endpoint,
            retryable=retryable,
            uploaded_image_count=uploaded_image_count,
            available_at=now + timedelta(seconds=min(delay, 86_400)),
            now=now,
        )
        logger.warning(
            "wechat_mp_draft_item_failed",
            job_id=str(claim.job.job_id),
            role=claim.item.role.value,
            retryable=retryable,
            error_code=status.job.error_code,
            status=status.job.status.value,
        )
        return status

    async def _known_failure_or_lease_loss(
        self,
        claim: WeChatDraftJobClaim,
        *,
        error_code: str,
        endpoint: WeChatMpEndpoint | None,
        retryable: bool,
        uploaded_image_count: int,
        side_effect_started: bool,
    ) -> WeChatDraftStatusProjection:
        try:
            return await self._known_failure(
                claim,
                error_code=error_code,
                endpoint=endpoint,
                retryable=retryable,
                uploaded_image_count=uploaded_image_count,
            )
        except WeChatDraftJobFailure:
            if side_effect_started:
                return await self._outcome_unknown(
                    claim,
                    endpoint=endpoint,
                    uploaded_image_count=uploaded_image_count,
                    error_code=_LEASE_LOST_AFTER_SIDE_EFFECT,
                )
            return await self._safe_current_status(claim)

    async def _outcome_unknown(
        self,
        claim: WeChatDraftJobClaim,
        *,
        endpoint: WeChatMpEndpoint | None,
        uploaded_image_count: int,
        error_code: str,
    ) -> WeChatDraftStatusProjection:
        try:
            status = await self._repository.mark_outcome_unknown(
                claim,
                error_code=error_code,
                endpoint=endpoint,
                uploaded_image_count=uploaded_image_count,
                now=self._now(),
            )
        except WeChatDraftJobFailure:
            status = await self._safe_current_status(claim)
            logger.warning(
                "wechat_mp_draft_unknown_fence_rejected",
                job_id=str(claim.job.job_id),
                role=claim.item.role.value,
                status=status.job.status.value,
            )
            return status
        logger.error(
            "wechat_mp_draft_item_outcome_unknown",
            job_id=str(claim.job.job_id),
            role=claim.item.role.value,
            error_code=error_code,
            status=status.job.status.value,
        )
        return status

    async def _shield_outcome_unknown(
        self,
        claim: WeChatDraftJobClaim,
        *,
        endpoint: WeChatMpEndpoint | None,
        uploaded_image_count: int,
        error_code: str,
    ) -> None:
        try:
            await asyncio.shield(
                self._outcome_unknown(
                    claim,
                    endpoint=endpoint,
                    uploaded_image_count=uploaded_image_count,
                    error_code=error_code,
                )
            )
        except (Exception, asyncio.CancelledError):
            return

    async def _safe_current_status(
        self,
        claim: WeChatDraftJobClaim,
    ) -> WeChatDraftStatusProjection:
        return await self._repository.get_status(claim.job.job_id)

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("WeChat draft clock must be timezone-aware")
        return now


class _ObservedWeChatDraftClient:
    """Track only safe progress metadata for one provider attempt."""

    def __init__(self, delegate: WeChatOfficialAccountDraftClient) -> None:
        self._delegate = delegate
        self.endpoint: WeChatMpEndpoint | None = None
        self.uploaded_image_count = 0

    async def upload_inline_image(
        self,
        image_bytes: bytes,
        media_type: str,
        filename: str,
    ) -> WeChatInlineImage:
        self.endpoint = "media_uploadimg"
        result = await self._delegate.upload_inline_image(image_bytes, media_type, filename)
        self.uploaded_image_count += 1
        return result

    async def upload_thumb(
        self,
        image_bytes: bytes,
        media_type: str,
        filename: str,
    ) -> WeChatThumbMedia:
        self.endpoint = "material_add_thumb"
        return await self._delegate.upload_thumb(image_bytes, media_type, filename)

    async def add_draft(self, article: WeChatDraftArticleRequest) -> WeChatDraftCreated:
        self.endpoint = "draft_add"
        return await self._delegate.add_draft(article)


__all__ = [
    "WeChatDraftEnqueueResult",
    "WeChatDraftReconcileResult",
    "WeChatOfficialAccountDraftJobExecutor",
    "WeChatOfficialAccountDraftJobService",
]
