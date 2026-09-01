"""PostgreSQL durability for automated WeChat Official Account draft jobs."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.wechat_official_account_draft_jobs import (
    WeChatOfficialAccountDraftJobRepository,
)
from app.domain.official_account_weekly_edition import WEEKLY_EDITION_ROLE_ORDER, WeeklyArticleRole
from app.domain.wechat_official_account_draft_jobs import (
    WECHAT_DRAFT_JOB_POLICY_VERSION,
    WeChatDraftAttemptStatus,
    WeChatDraftItemSnapshot,
    WeChatDraftItemStatus,
    WeChatDraftJobClaim,
    WeChatDraftJobEnqueue,
    WeChatDraftJobErrorCode,
    WeChatDraftJobFailure,
    WeChatDraftJobSnapshot,
    WeChatDraftJobStatus,
    WeChatDraftStatusProjection,
    validate_endpoint,
    validate_error_code,
)
from app.infrastructure.db.models import (
    WeChatOfficialAccountDraftAttemptModel,
    WeChatOfficialAccountDraftItemModel,
    WeChatOfficialAccountDraftJobModel,
)

_SAFE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CLAIMABLE = (
    WeChatDraftJobStatus.QUEUED.value,
    WeChatDraftJobStatus.RETRYABLE_FAILED.value,
)
_INCOMPLETE_ITEMS = (
    WeChatDraftItemStatus.PENDING.value,
    WeChatDraftItemStatus.RETRYABLE_FAILED.value,
)


class PostgresWeChatOfficialAccountDraftJobRepository(WeChatOfficialAccountDraftJobRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def enqueue(
        self,
        command: WeChatDraftJobEnqueue,
        *,
        now: datetime,
    ) -> tuple[WeChatDraftStatusProjection, bool]:
        _validate_aware(now)
        async with self._session_factory() as session, session.begin():
            created_id = await session.scalar(
                insert(WeChatOfficialAccountDraftJobModel)
                .values(
                    id=command.job_id,
                    request_fingerprint=command.request_fingerprint,
                    account_fingerprint=command.account_fingerprint,
                    aggregate_fingerprint=command.aggregate_fingerprint,
                    batch_fingerprint=command.batch_fingerprint,
                    policy_version=WECHAT_DRAFT_JOB_POLICY_VERSION,
                    status=WeChatDraftJobStatus.QUEUED.value,
                    attempt_count=0,
                    max_attempts=command.max_attempts,
                    available_at=now,
                    fencing_token=0,
                    created_at=now,
                    updated_at=now,
                )
                # The deterministic job UUID and request fingerprint identify the
                # same logical request. Under concurrency PostgreSQL may detect
                # either unique constraint first, so ignore both here and verify
                # the complete stored identity under the row lock below.
                .on_conflict_do_nothing()
                .returning(WeChatOfficialAccountDraftJobModel.id)
            )
            created = created_id is not None
            job = await session.scalar(
                select(WeChatOfficialAccountDraftJobModel)
                .where(
                    WeChatOfficialAccountDraftJobModel.request_fingerprint
                    == command.request_fingerprint
                )
                .with_for_update()
            )
            if job is None or not _job_identity_matches(job, command):
                raise WeChatDraftJobFailure(
                    WeChatDraftJobErrorCode.ARTIFACT_CONFLICT.value,
                    retryable=False,
                )
            if created:
                session.add_all(
                    [
                        WeChatOfficialAccountDraftItemModel(
                            job_id=job.id,
                            ordinal=item.ordinal,
                            role=item.role.value,
                            source_ref=item.source_ref,
                            source_fingerprint=item.source_fingerprint,
                            article_fingerprint=item.article_fingerprint,
                            content_fingerprint=item.content_fingerprint,
                            policy_fingerprint=item.policy_fingerprint,
                            status=WeChatDraftItemStatus.PENDING.value,
                            attempt_count=0,
                            uploaded_image_count=0,
                            created_at=now,
                            updated_at=now,
                        )
                        for item in command.items
                    ]
                )
                await session.flush()
            status = await _load_status(session, job.id, lock_items=True)
            if not created and not _items_identity_matches(status, command):
                raise WeChatDraftJobFailure(
                    WeChatDraftJobErrorCode.ARTIFACT_CONFLICT.value,
                    retryable=False,
                )
            return status, created

    async def get_status(self, job_id: UUID) -> WeChatDraftStatusProjection:
        async with self._session_factory() as session:
            return await _load_status(session, job_id)

    async def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> WeChatDraftJobClaim | None:
        _validate_ref(worker_id, "worker ID")
        _validate_aware(now)
        _validate_lease_seconds(lease_seconds)
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        async with self._session_factory() as session, session.begin():
            while True:
                job = await session.scalar(
                    select(WeChatOfficialAccountDraftJobModel)
                    .where(
                        or_(
                            and_(
                                WeChatOfficialAccountDraftJobModel.status.in_(_CLAIMABLE),
                                WeChatOfficialAccountDraftJobModel.available_at <= now,
                            ),
                            and_(
                                WeChatOfficialAccountDraftJobModel.status
                                == WeChatDraftJobStatus.RUNNING.value,
                                WeChatOfficialAccountDraftJobModel.lease_expires_at < now,
                            ),
                        )
                    )
                    .order_by(
                        WeChatOfficialAccountDraftJobModel.available_at,
                        WeChatOfficialAccountDraftJobModel.created_at,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if job is None:
                    return None
                items = await _load_item_models(session, job.id, lock=True)
                if job.status == WeChatDraftJobStatus.RUNNING.value:
                    if not await _recover_expired_job(session, job=job, items=items, now=now):
                        continue
                item = next((row for row in items if row.status in _INCOMPLETE_ITEMS), None)
                if item is None:
                    if all(row.status == WeChatDraftItemStatus.SUCCEEDED.value for row in items):
                        _finish_job_ready(job, now=now)
                    else:
                        _terminalize_invalid(job, items=items, now=now)
                    await session.flush()
                    continue
                if item.attempt_count >= job.max_attempts:
                    _terminalize_exhausted(job, item=item, now=now)
                    await session.flush()
                    continue

                job.status = WeChatDraftJobStatus.RUNNING.value
                job.attempt_count += 1
                job.fencing_token += 1
                job.lease_owner = worker_id
                job.lease_expires_at = lease_expires_at
                job.heartbeat_at = now
                job.error_code = None
                job.completed_at = None
                job.updated_at = now

                item.status = WeChatDraftItemStatus.RUNNING.value
                item.attempt_count += 1
                item.side_effect_started_at = None
                item.endpoint = None
                item.uploaded_image_count = 0
                item.draft_media_fingerprint = None
                item.error_code = None
                item.started_at = item.started_at or now
                item.completed_at = None
                item.updated_at = now

                session.add(
                    WeChatOfficialAccountDraftAttemptModel(
                        job_id=job.id,
                        item_ordinal=item.ordinal,
                        attempt_no=item.attempt_count,
                        fencing_token=job.fencing_token,
                        worker_id=worker_id,
                        status=WeChatDraftAttemptStatus.RUNNING.value,
                        uploaded_image_count=0,
                        lease_expires_at=lease_expires_at,
                        started_at=now,
                        heartbeat_at=now,
                    )
                )
                await session.flush()
                return WeChatDraftJobClaim(
                    job=_job_snapshot(job),
                    item=_item_snapshot(item),
                    worker_id=worker_id,
                    lease_expires_at=lease_expires_at,
                )

    async def heartbeat(
        self,
        claim: WeChatDraftJobClaim,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        _validate_aware(now)
        _validate_lease_seconds(lease_seconds)
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        async with self._session_factory() as session, session.begin():
            owned = await _load_owned(session, claim=claim, now=now, allow_expired=False)
            if owned is None:
                return False
            job, _item, attempt = owned
            job.heartbeat_at = now
            job.lease_expires_at = lease_expires_at
            job.updated_at = now
            attempt.heartbeat_at = now
            attempt.lease_expires_at = lease_expires_at
            await session.flush()
            return True

    async def mark_side_effect_started(
        self,
        claim: WeChatDraftJobClaim,
        *,
        endpoint: str,
        now: datetime,
    ) -> bool:
        validate_endpoint(endpoint)
        _validate_aware(now)
        async with self._session_factory() as session, session.begin():
            owned = await _load_owned(session, claim=claim, now=now, allow_expired=False)
            if owned is None:
                return False
            _job, item, attempt = owned
            if item.side_effect_started_at is not None:
                return item.endpoint == endpoint and attempt.endpoint == endpoint
            item.side_effect_started_at = now
            item.endpoint = endpoint
            item.updated_at = now
            attempt.side_effect_started_at = now
            attempt.endpoint = endpoint
            await session.flush()
            return True

    async def succeed(
        self,
        claim: WeChatDraftJobClaim,
        *,
        endpoint: str,
        uploaded_image_count: int,
        draft_media_fingerprint: str,
        now: datetime,
    ) -> WeChatDraftStatusProjection:
        validate_endpoint(endpoint)
        _validate_count(uploaded_image_count)
        _validate_sha256(draft_media_fingerprint, "draft media fingerprint")
        _validate_aware(now)
        async with self._session_factory() as session, session.begin():
            owned = await _require_owned(session, claim=claim, now=now)
            job, item, attempt = owned
            if item.side_effect_started_at is None or attempt.side_effect_started_at is None:
                raise WeChatDraftJobFailure(
                    WeChatDraftJobErrorCode.INVALID_CHECKPOINT.value,
                    retryable=False,
                )
            item.status = WeChatDraftItemStatus.SUCCEEDED.value
            item.endpoint = endpoint
            item.uploaded_image_count = uploaded_image_count
            item.draft_media_fingerprint = draft_media_fingerprint
            item.error_code = None
            item.completed_at = now
            item.updated_at = now
            attempt.status = WeChatDraftAttemptStatus.SUCCEEDED.value
            attempt.endpoint = endpoint
            attempt.uploaded_image_count = uploaded_image_count
            attempt.draft_media_fingerprint = draft_media_fingerprint
            attempt.error_code = None
            attempt.completed_at = now
            remaining = tuple(
                await session.scalars(
                    select(WeChatOfficialAccountDraftItemModel)
                    .where(WeChatOfficialAccountDraftItemModel.job_id == job.id)
                    .order_by(WeChatOfficialAccountDraftItemModel.ordinal)
                    .with_for_update()
                )
            )
            _clear_job_lease(job)
            if all(row.status == WeChatDraftItemStatus.SUCCEEDED.value for row in remaining):
                _finish_job_ready(job, now=now)
            else:
                job.status = WeChatDraftJobStatus.QUEUED.value
                job.available_at = now
                job.error_code = None
                job.completed_at = None
                job.updated_at = now
            await session.flush()
            return await _load_status(session, job.id)

    async def fail_known(
        self,
        claim: WeChatDraftJobClaim,
        *,
        error_code: str,
        endpoint: str | None,
        retryable: bool,
        uploaded_image_count: int,
        available_at: datetime,
        now: datetime,
    ) -> WeChatDraftStatusProjection:
        validate_error_code(error_code)
        if endpoint is not None:
            validate_endpoint(endpoint)
        _validate_count(uploaded_image_count)
        _validate_aware(now)
        _validate_aware(available_at)
        async with self._session_factory() as session, session.begin():
            job, item, attempt = await _require_owned(session, claim=claim, now=now)
            exhausted = item.attempt_count >= job.max_attempts
            resolved_error = (
                WeChatDraftJobErrorCode.ATTEMPTS_EXHAUSTED.value
                if retryable and exhausted
                else error_code
            )
            retry = retryable and not exhausted
            item.status = (
                WeChatDraftItemStatus.RETRYABLE_FAILED.value
                if retry
                else WeChatDraftItemStatus.TERMINAL_FAILED.value
            )
            item.endpoint = endpoint or item.endpoint
            item.uploaded_image_count = uploaded_image_count
            item.error_code = resolved_error
            item.completed_at = now
            item.updated_at = now
            attempt.status = (
                WeChatDraftAttemptStatus.RETRYABLE_FAILED.value
                if retry
                else WeChatDraftAttemptStatus.TERMINAL_FAILED.value
            )
            attempt.endpoint = endpoint or attempt.endpoint
            attempt.uploaded_image_count = uploaded_image_count
            attempt.error_code = resolved_error
            attempt.completed_at = now
            _clear_job_lease(job)
            job.status = (
                WeChatDraftJobStatus.RETRYABLE_FAILED.value
                if retry
                else WeChatDraftJobStatus.TERMINAL_FAILED.value
            )
            job.available_at = available_at
            job.error_code = resolved_error
            job.completed_at = None if retry else now
            job.updated_at = now
            await session.flush()
            return await _load_status(session, job.id)

    async def mark_outcome_unknown(
        self,
        claim: WeChatDraftJobClaim,
        *,
        error_code: str,
        endpoint: str | None,
        uploaded_image_count: int,
        now: datetime,
    ) -> WeChatDraftStatusProjection:
        validate_error_code(error_code)
        if endpoint is not None:
            validate_endpoint(endpoint)
        _validate_count(uploaded_image_count)
        _validate_aware(now)
        async with self._session_factory() as session, session.begin():
            job, item, attempt = await _require_owned(
                session,
                claim=claim,
                now=now,
                allow_expired=True,
            )
            if item.side_effect_started_at is None or attempt.side_effect_started_at is None:
                raise WeChatDraftJobFailure(
                    WeChatDraftJobErrorCode.INVALID_CHECKPOINT.value,
                    retryable=False,
                )
            item.status = WeChatDraftItemStatus.OUTCOME_UNKNOWN.value
            item.endpoint = endpoint or item.endpoint
            item.uploaded_image_count = uploaded_image_count
            item.error_code = error_code
            item.completed_at = now
            item.updated_at = now
            attempt.status = WeChatDraftAttemptStatus.OUTCOME_UNKNOWN.value
            attempt.endpoint = endpoint or attempt.endpoint
            attempt.uploaded_image_count = uploaded_image_count
            attempt.error_code = error_code
            attempt.completed_at = now
            _clear_job_lease(job)
            job.status = WeChatDraftJobStatus.OUTCOME_UNKNOWN.value
            job.error_code = error_code
            job.completed_at = now
            job.updated_at = now
            await session.flush()
            return await _load_status(session, job.id)


async def _load_status(
    session: AsyncSession,
    job_id: UUID,
    *,
    lock_items: bool = False,
) -> WeChatDraftStatusProjection:
    job = await session.get(WeChatOfficialAccountDraftJobModel, job_id)
    if job is None:
        raise LookupError("WeChat draft job does not exist")
    items = await _load_item_models(session, job_id, lock=lock_items)
    return WeChatDraftStatusProjection(
        job=_job_snapshot(job),
        items=tuple(_item_snapshot(item) for item in items),
    )


async def _load_item_models(
    session: AsyncSession,
    job_id: UUID,
    *,
    lock: bool,
) -> tuple[WeChatOfficialAccountDraftItemModel, ...]:
    statement = (
        select(WeChatOfficialAccountDraftItemModel)
        .where(WeChatOfficialAccountDraftItemModel.job_id == job_id)
        .order_by(WeChatOfficialAccountDraftItemModel.ordinal)
    )
    if lock:
        statement = statement.with_for_update()
    items = tuple(await session.scalars(statement))
    if len(items) != 3 or tuple(item.ordinal for item in items) != (1, 2, 3):
        raise WeChatDraftJobFailure(
            WeChatDraftJobErrorCode.INVALID_CHECKPOINT.value,
            retryable=False,
        )
    return items


async def _load_owned(
    session: AsyncSession,
    *,
    claim: WeChatDraftJobClaim,
    now: datetime,
    allow_expired: bool,
) -> (
    tuple[
        WeChatOfficialAccountDraftJobModel,
        WeChatOfficialAccountDraftItemModel,
        WeChatOfficialAccountDraftAttemptModel,
    ]
    | None
):
    job = await session.scalar(
        select(WeChatOfficialAccountDraftJobModel)
        .where(
            WeChatOfficialAccountDraftJobModel.id == claim.job.job_id,
            WeChatOfficialAccountDraftJobModel.status == WeChatDraftJobStatus.RUNNING.value,
            WeChatOfficialAccountDraftJobModel.lease_owner == claim.worker_id,
            WeChatOfficialAccountDraftJobModel.fencing_token == claim.job.fencing_token,
            WeChatOfficialAccountDraftJobModel.attempt_count == claim.job.attempt_count,
        )
        .with_for_update()
    )
    if job is None or job.lease_expires_at is None:
        return None
    if not allow_expired and job.lease_expires_at < now:
        return None
    item = await session.scalar(
        select(WeChatOfficialAccountDraftItemModel)
        .where(
            WeChatOfficialAccountDraftItemModel.job_id == job.id,
            WeChatOfficialAccountDraftItemModel.ordinal == claim.item.ordinal,
            WeChatOfficialAccountDraftItemModel.status == WeChatDraftItemStatus.RUNNING.value,
            WeChatOfficialAccountDraftItemModel.attempt_count == claim.item.attempt_count,
        )
        .with_for_update()
    )
    attempt = await session.scalar(
        select(WeChatOfficialAccountDraftAttemptModel)
        .where(
            WeChatOfficialAccountDraftAttemptModel.job_id == job.id,
            WeChatOfficialAccountDraftAttemptModel.item_ordinal == claim.item.ordinal,
            WeChatOfficialAccountDraftAttemptModel.attempt_no == claim.item.attempt_count,
            WeChatOfficialAccountDraftAttemptModel.fencing_token == claim.job.fencing_token,
            WeChatOfficialAccountDraftAttemptModel.worker_id == claim.worker_id,
            WeChatOfficialAccountDraftAttemptModel.status == WeChatDraftAttemptStatus.RUNNING.value,
        )
        .with_for_update()
    )
    if item is None or attempt is None:
        return None
    return job, item, attempt


async def _require_owned(
    session: AsyncSession,
    *,
    claim: WeChatDraftJobClaim,
    now: datetime,
    allow_expired: bool = False,
) -> tuple[
    WeChatOfficialAccountDraftJobModel,
    WeChatOfficialAccountDraftItemModel,
    WeChatOfficialAccountDraftAttemptModel,
]:
    owned = await _load_owned(session, claim=claim, now=now, allow_expired=allow_expired)
    if owned is None:
        raise WeChatDraftJobFailure(
            WeChatDraftJobErrorCode.LEASE_LOST.value,
            retryable=False,
        )
    return owned


async def _recover_expired_job(
    session: AsyncSession,
    *,
    job: WeChatOfficialAccountDraftJobModel,
    items: tuple[WeChatOfficialAccountDraftItemModel, ...],
    now: datetime,
) -> bool:
    running = tuple(item for item in items if item.status == WeChatDraftItemStatus.RUNNING.value)
    if len(running) != 1:
        _terminalize_invalid(job, items=items, now=now)
        await session.flush()
        return False
    item = running[0]
    attempt = await session.scalar(
        select(WeChatOfficialAccountDraftAttemptModel)
        .where(
            WeChatOfficialAccountDraftAttemptModel.job_id == job.id,
            WeChatOfficialAccountDraftAttemptModel.item_ordinal == item.ordinal,
            WeChatOfficialAccountDraftAttemptModel.attempt_no == item.attempt_count,
            WeChatOfficialAccountDraftAttemptModel.fencing_token == job.fencing_token,
            WeChatOfficialAccountDraftAttemptModel.status == WeChatDraftAttemptStatus.RUNNING.value,
        )
        .with_for_update()
    )
    if attempt is None:
        _terminalize_invalid(job, items=items, now=now)
        await session.flush()
        return False
    _clear_job_lease(job)
    if item.side_effect_started_at is not None or attempt.side_effect_started_at is not None:
        error = WeChatDraftJobErrorCode.LEASE_LOST_AFTER_SIDE_EFFECT.value
        item.status = WeChatDraftItemStatus.OUTCOME_UNKNOWN.value
        item.error_code = error
        item.completed_at = now
        item.updated_at = now
        attempt.status = WeChatDraftAttemptStatus.OUTCOME_UNKNOWN.value
        attempt.error_code = error
        attempt.completed_at = now
        job.status = WeChatDraftJobStatus.OUTCOME_UNKNOWN.value
        job.error_code = error
        job.completed_at = now
        job.updated_at = now
        await session.flush()
        return False
    attempt.status = WeChatDraftAttemptStatus.LEASE_EXPIRED.value
    attempt.error_code = WeChatDraftJobErrorCode.LEASE_LOST.value
    attempt.completed_at = now
    if item.attempt_count >= job.max_attempts:
        _terminalize_exhausted(job, item=item, now=now)
        await session.flush()
        return False
    item.status = WeChatDraftItemStatus.RETRYABLE_FAILED.value
    item.error_code = WeChatDraftJobErrorCode.LEASE_LOST.value
    item.completed_at = now
    item.updated_at = now
    job.status = WeChatDraftJobStatus.RETRYABLE_FAILED.value
    job.available_at = now
    job.error_code = WeChatDraftJobErrorCode.LEASE_LOST.value
    job.completed_at = None
    job.updated_at = now
    await session.flush()
    return True


def _clear_job_lease(job: WeChatOfficialAccountDraftJobModel) -> None:
    job.lease_owner = None
    job.lease_expires_at = None
    job.heartbeat_at = None


def _finish_job_ready(job: WeChatOfficialAccountDraftJobModel, *, now: datetime) -> None:
    job.status = WeChatDraftJobStatus.READY.value
    job.error_code = None
    job.completed_at = now
    job.updated_at = now
    job.lease_owner = None
    job.lease_expires_at = None
    job.heartbeat_at = None


def _terminalize_exhausted(
    job: WeChatOfficialAccountDraftJobModel,
    *,
    item: WeChatOfficialAccountDraftItemModel,
    now: datetime,
) -> None:
    error = WeChatDraftJobErrorCode.ATTEMPTS_EXHAUSTED.value
    item.status = WeChatDraftItemStatus.TERMINAL_FAILED.value
    item.error_code = error
    item.completed_at = now
    item.updated_at = now
    job.status = WeChatDraftJobStatus.TERMINAL_FAILED.value
    job.error_code = error
    job.completed_at = now
    job.updated_at = now
    job.lease_owner = None
    job.lease_expires_at = None
    job.heartbeat_at = None


def _terminalize_invalid(
    job: WeChatOfficialAccountDraftJobModel,
    *,
    items: tuple[WeChatOfficialAccountDraftItemModel, ...],
    now: datetime,
) -> None:
    error = WeChatDraftJobErrorCode.INVALID_CHECKPOINT.value
    for item in items:
        if item.status == WeChatDraftItemStatus.RUNNING.value:
            item.status = WeChatDraftItemStatus.TERMINAL_FAILED.value
            item.error_code = error
            item.completed_at = now
            item.updated_at = now
    job.status = WeChatDraftJobStatus.TERMINAL_FAILED.value
    job.error_code = error
    job.completed_at = now
    job.updated_at = now
    job.lease_owner = None
    job.lease_expires_at = None
    job.heartbeat_at = None


def _job_identity_matches(
    model: WeChatOfficialAccountDraftJobModel,
    command: WeChatDraftJobEnqueue,
) -> bool:
    return (
        model.id == command.job_id
        and model.request_fingerprint == command.request_fingerprint
        and model.account_fingerprint == command.account_fingerprint
        and model.aggregate_fingerprint == command.aggregate_fingerprint
        and model.batch_fingerprint == command.batch_fingerprint
        and model.policy_version == WECHAT_DRAFT_JOB_POLICY_VERSION
    )


def _items_identity_matches(
    status: WeChatDraftStatusProjection,
    command: WeChatDraftJobEnqueue,
) -> bool:
    return all(
        (
            snapshot.role == expected.role
            and snapshot.ordinal == expected.ordinal
            and snapshot.source_ref == expected.source_ref
            and snapshot.source_fingerprint == expected.source_fingerprint
            and snapshot.article_fingerprint == expected.article_fingerprint
            and snapshot.content_fingerprint == expected.content_fingerprint
            and snapshot.policy_fingerprint == expected.policy_fingerprint
        )
        for snapshot, expected in zip(status.items, command.items, strict=True)
    )


def _job_snapshot(model: WeChatOfficialAccountDraftJobModel) -> WeChatDraftJobSnapshot:
    return WeChatDraftJobSnapshot(
        job_id=model.id,
        request_fingerprint=model.request_fingerprint,
        account_fingerprint=model.account_fingerprint,
        aggregate_fingerprint=model.aggregate_fingerprint,
        batch_fingerprint=model.batch_fingerprint,
        policy_version=model.policy_version,
        status=WeChatDraftJobStatus(model.status),
        attempt_count=model.attempt_count,
        max_attempts=model.max_attempts,
        fencing_token=model.fencing_token,
        available_at=model.available_at,
        error_code=model.error_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )


def _item_snapshot(model: WeChatOfficialAccountDraftItemModel) -> WeChatDraftItemSnapshot:
    expected_role = (
        WEEKLY_EDITION_ROLE_ORDER[model.ordinal - 1] if 1 <= model.ordinal <= 3 else None
    )
    if expected_role != model.role:
        raise WeChatDraftJobFailure(
            WeChatDraftJobErrorCode.INVALID_CHECKPOINT.value,
            retryable=False,
        )
    return WeChatDraftItemSnapshot(
        job_id=model.job_id,
        role=WeeklyArticleRole(model.role),
        ordinal=model.ordinal,
        source_ref=model.source_ref,
        source_fingerprint=model.source_fingerprint,
        article_fingerprint=model.article_fingerprint,
        content_fingerprint=model.content_fingerprint,
        policy_fingerprint=model.policy_fingerprint,
        status=WeChatDraftItemStatus(model.status),
        attempt_count=model.attempt_count,
        side_effect_started_at=model.side_effect_started_at,
        endpoint=model.endpoint,
        uploaded_image_count=model.uploaded_image_count,
        draft_media_fingerprint=model.draft_media_fingerprint,
        error_code=model.error_code,
        started_at=model.started_at,
        completed_at=model.completed_at,
    )


def _validate_ref(value: str, label: str) -> None:
    if _SAFE_REF.fullmatch(value) is None:
        raise ValueError(f"WeChat draft {label} is invalid")


def _validate_sha256(value: str, label: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"WeChat draft {label} must be lowercase SHA-256")


def _validate_aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise ValueError("WeChat draft repository timestamps must be timezone-aware")


def _validate_lease_seconds(value: int) -> None:
    if not 3 <= value <= 3600:
        raise ValueError("WeChat draft lease must be between 3 and 3600 seconds")


def _validate_count(value: int) -> None:
    if not 0 <= value <= 1000:
        raise ValueError("WeChat draft uploaded image count is invalid")
