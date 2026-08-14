from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.acquisition import ClaimedJob, CursorState, PersistedCandidate
from app.core.errors import ConflictError, LeaseLostError, NotFoundError
from app.domain.content_slots import ContentSlot
from app.domain.entities import (
    ExtractedDocument,
    FetchedResponse,
    SnapshotDescriptor,
    SourceProfile,
)
from app.domain.enums import JobStatus, ObservationOutcome, RunStatus, RunTrigger, SourceTier
from app.domain.value_objects import sha256_bytes, stable_key
from app.infrastructure.db.models import (
    AcquisitionAttemptModel,
    AcquisitionJobModel,
    AcquisitionRunModel,
    EvidenceCandidateModel,
    SourceCursorModel,
    SourceFetchLeaseModel,
    SourceModel,
    SourceObservationModel,
    SourceSnapshotModel,
    SourceVersionModel,
)
from app.infrastructure.ingestion.source_profiles import (
    PENDING_SOURCE_SEEDS,
    SOURCE_SEEDS,
    TERMS_REVIEWED_AT,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def seed_sources(session: AsyncSession) -> int:
    seeded = 0
    pending_source_ids = [seed.source_id for seed in PENDING_SOURCE_SEEDS]
    if pending_source_ids:
        await session.execute(
            update(SourceModel)
            .where(SourceModel.id.in_(pending_source_ids))
            .values(enabled=False, active_version_id=None, updated_at=_utcnow())
        )
    for seed in SOURCE_SEEDS:
        source = await session.get(SourceModel, seed.source_id)
        if source is None:
            source = SourceModel(
                id=seed.source_id,
                slug=seed.slug,
                display_name=seed.display_name,
                organization_type=seed.organization_type,
                enabled=True,
                owner=seed.owner,
            )
            session.add(source)
            await session.flush()
            seeded += 1
        else:
            source.display_name = seed.display_name
            source.organization_type = seed.organization_type
            source.enabled = True
            source.owner = seed.owner
            source.updated_at = _utcnow()

        version = await session.scalar(
            select(SourceVersionModel).where(
                SourceVersionModel.source_id == seed.source_id,
                SourceVersionModel.config_fingerprint == seed.config_fingerprint,
            )
        )
        if version is None:
            current_version = await session.scalar(
                select(func.max(SourceVersionModel.version)).where(
                    SourceVersionModel.source_id == seed.source_id
                )
            )
            version = SourceVersionModel(
                id=seed.source_version_id,
                source_id=seed.source_id,
                version=(current_version or 0) + 1,
                trust_tier=seed.tier.value,
                connector_key=seed.connector_key,
                entry_url=seed.entry_url,
                allowed_hosts=list(seed.allowed_hosts),
                allowed_path_prefixes=list(seed.allowed_path_prefixes),
                cadence=seed.cadence,
                timezone=seed.timezone,
                language=seed.language,
                robots_status=seed.robots_status,
                terms_reviewed_at=TERMS_REVIEWED_AT,
                rate_limit_seconds=seed.rate_limit_seconds,
                connector_version=seed.connector_version,
                parser_version=seed.parser_version,
                relevance_rule_version=seed.relevance_rule_version,
                allow_http_fallback=seed.allow_http_fallback,
                topic_priority_policy=seed.topic_priority_policy,
                config_fingerprint=seed.config_fingerprint,
            )
            session.add(version)
            await session.flush()
        source.active_version_id = version.id
    await session.commit()
    return seeded


async def create_run(
    session: AsyncSession,
    *,
    trigger: RunTrigger,
    timezone: str,
    acquisition_version: str,
    business_date: date | None = None,
    content_slot: ContentSlot | None = None,
    manual_idempotency_key: str | None = None,
    source_ids: list[UUID] | None = None,
) -> tuple[AcquisitionRunModel, bool]:
    if trigger is RunTrigger.SCHEDULED and business_date is None:
        raise ValueError("scheduled runs require a business date")
    slot_value = content_slot.value if content_slot is not None else None

    if trigger is RunTrigger.SCHEDULED:
        existing = await session.scalar(
            select(AcquisitionRunModel).where(
                AcquisitionRunModel.trigger == trigger.value,
                AcquisitionRunModel.business_date == business_date,
                AcquisitionRunModel.timezone == timezone,
                AcquisitionRunModel.acquisition_version == acquisition_version,
                AcquisitionRunModel.content_slot == slot_value,
            )
        )
    elif manual_idempotency_key:
        existing = await session.scalar(
            select(AcquisitionRunModel).where(
                AcquisitionRunModel.manual_idempotency_key == manual_idempotency_key
            )
        )
    else:
        existing = None
    if existing is not None:
        return existing, False

    version_query: Select[tuple[SourceModel, SourceVersionModel]] = (
        select(SourceModel, SourceVersionModel)
        .join(SourceVersionModel, SourceVersionModel.id == SourceModel.active_version_id)
        .where(SourceModel.enabled.is_(True))
        .order_by(SourceModel.slug)
    )
    if source_ids:
        version_query = version_query.where(SourceModel.id.in_(source_ids))
    rows = list((await session.execute(version_query)).tuples())
    if source_ids and len(rows) != len(set(source_ids)):
        raise ConflictError("one or more selected sources are disabled or unknown")
    if not rows:
        raise ConflictError("no enabled sources are available")

    run = AcquisitionRunModel(
        id=uuid4(),
        trigger=trigger.value,
        business_date=business_date,
        timezone=timezone,
        acquisition_version=acquisition_version,
        content_slot=slot_value,
        manual_idempotency_key=manual_idempotency_key,
        status=RunStatus.QUEUED.value,
        total_jobs=len(rows),
    )
    session.add(run)
    await session.flush()
    for source, version in rows:
        session.add(
            AcquisitionJobModel(
                id=uuid4(),
                run_id=run.id,
                source_id=source.id,
                source_version_id=version.id,
                status=JobStatus.QUEUED.value,
            )
        )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        if trigger is RunTrigger.SCHEDULED:
            duplicate = await session.scalar(
                select(AcquisitionRunModel).where(
                    AcquisitionRunModel.trigger == trigger.value,
                    AcquisitionRunModel.business_date == business_date,
                    AcquisitionRunModel.timezone == timezone,
                    AcquisitionRunModel.acquisition_version == acquisition_version,
                    AcquisitionRunModel.content_slot == slot_value,
                )
            )
        elif manual_idempotency_key:
            duplicate = await session.scalar(
                select(AcquisitionRunModel).where(
                    AcquisitionRunModel.manual_idempotency_key == manual_idempotency_key
                )
            )
        else:
            raise
        if duplicate is None:
            raise
        return duplicate, False
    await session.refresh(run)
    return run, True


async def claim_job(
    session: AsyncSession, *, worker_id: str, lease_seconds: int, now: datetime | None = None
) -> ClaimedJob | None:
    current = now or _utcnow()
    claimable = or_(
        and_(
            AcquisitionJobModel.status.in_(
                [JobStatus.QUEUED.value, JobStatus.RETRY_SCHEDULED.value]
            ),
            AcquisitionJobModel.available_at <= current,
        ),
        and_(
            AcquisitionJobModel.status == JobStatus.RUNNING.value,
            AcquisitionJobModel.lease_expires_at < current,
        ),
    )
    job = await session.scalar(
        select(AcquisitionJobModel)
        .where(claimable)
        .order_by(AcquisitionJobModel.available_at, AcquisitionJobModel.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        await session.rollback()
        return None
    source = await session.get(SourceModel, job.source_id)
    version = await session.get(SourceVersionModel, job.source_version_id)
    if source is None or version is None:
        raise RuntimeError("claimed job references missing source configuration")

    token = uuid4()
    job.status = JobStatus.RUNNING.value
    job.attempt_count += 1
    job.lease_owner = worker_id
    job.lease_token = token
    job.lease_expires_at = current + timedelta(seconds=lease_seconds)
    job.heartbeat_at = current
    job.started_at = job.started_at or current
    run = await session.get(AcquisitionRunModel, job.run_id)
    if run is not None and run.status == RunStatus.QUEUED.value:
        run.status = RunStatus.RUNNING.value
        run.started_at = current
    await session.commit()
    return ClaimedJob(
        job_id=job.id,
        run_id=job.run_id,
        attempt_number=job.attempt_count,
        lease_token=token,
        profile=SourceProfile(
            source_id=source.id,
            source_version_id=version.id,
            slug=source.slug,
            display_name=source.display_name,
            organization_type=source.organization_type,
            tier=SourceTier(version.trust_tier),
            connector_key=version.connector_key,
            entry_url=version.entry_url,
            allowed_hosts=tuple(version.allowed_hosts),
            allowed_path_prefixes=tuple(version.allowed_path_prefixes),
            connector_version=version.connector_version,
            parser_version=version.parser_version,
            relevance_rule_version=version.relevance_rule_version,
            allow_http_fallback=version.allow_http_fallback,
            topic_priority_policy=version.topic_priority_policy,
            language=version.language,
            timezone=version.timezone,
            rate_limit_seconds=version.rate_limit_seconds,
            robots_status=version.robots_status,
            terms_reviewed_at=version.terms_reviewed_at,
        ),
    )


async def create_attempt(session: AsyncSession, claimed: ClaimedJob) -> UUID:
    attempt_id = uuid4()
    session.add(
        AcquisitionAttemptModel(
            id=attempt_id,
            job_id=claimed.job_id,
            attempt_number=claimed.attempt_number,
            started_at=_utcnow(),
        )
    )
    await session.commit()
    return attempt_id


async def heartbeat_job(session: AsyncSession, *, claimed: ClaimedJob, lease_seconds: int) -> bool:
    now = _utcnow()
    job_result = cast(
        CursorResult[Any],
        await session.execute(
            update(AcquisitionJobModel)
            .where(
                AcquisitionJobModel.id == claimed.job_id,
                AcquisitionJobModel.lease_token == claimed.lease_token,
                AcquisitionJobModel.status == JobStatus.RUNNING.value,
                AcquisitionJobModel.lease_expires_at >= now,
            )
            .values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=lease_seconds))
        ),
    )
    if not job_result.rowcount:
        await session.rollback()
        return False
    source_result = cast(
        CursorResult[Any],
        await session.execute(
            update(SourceFetchLeaseModel)
            .where(
                SourceFetchLeaseModel.source_id == claimed.profile.source_id,
                SourceFetchLeaseModel.lease_token == claimed.lease_token,
                SourceFetchLeaseModel.expires_at >= now,
            )
            .values(expires_at=now + timedelta(seconds=lease_seconds), updated_at=now)
        ),
    )
    if not source_result.rowcount:
        await session.rollback()
        return False
    await session.commit()
    return True


async def assert_active_lease(
    session: AsyncSession, *, claimed: ClaimedJob, require_source_lease: bool
) -> None:
    now = _utcnow()
    active_job = await session.scalar(
        select(AcquisitionJobModel.id).where(
            AcquisitionJobModel.id == claimed.job_id,
            AcquisitionJobModel.lease_token == claimed.lease_token,
            AcquisitionJobModel.status == JobStatus.RUNNING.value,
            AcquisitionJobModel.lease_expires_at >= now,
        )
    )
    if active_job is None:
        raise LeaseLostError
    if require_source_lease:
        active_source = await session.scalar(
            select(SourceFetchLeaseModel.source_id).where(
                SourceFetchLeaseModel.source_id == claimed.profile.source_id,
                SourceFetchLeaseModel.lease_token == claimed.lease_token,
                SourceFetchLeaseModel.expires_at >= now,
            )
        )
        if active_source is None:
            raise LeaseLostError


async def acquire_source_fetch_lease(
    session: AsyncSession,
    *,
    source_id: UUID,
    owner: str,
    lease_token: UUID,
    lease_seconds: int,
) -> bool:
    now = _utcnow()
    await session.execute(
        insert(SourceFetchLeaseModel)
        .values(
            source_id=source_id,
            lease_owner=owner,
            lease_token=lease_token,
            expires_at=now + timedelta(seconds=lease_seconds),
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=[SourceFetchLeaseModel.source_id],
            set_={
                "lease_owner": owner,
                "lease_token": lease_token,
                "expires_at": now + timedelta(seconds=lease_seconds),
                "updated_at": now,
            },
            where=SourceFetchLeaseModel.expires_at < now,
        )
    )
    await session.commit()
    lease = await session.get(SourceFetchLeaseModel, source_id)
    return lease is not None and lease.lease_token == lease_token


async def reserve_source_request_slot(
    session: AsyncSession,
    *,
    claimed: ClaimedJob,
    minimum_interval_seconds: float,
) -> float:
    """Reserve the next source request without holding a database transaction open."""
    now = _utcnow()
    lease = await session.scalar(
        select(SourceFetchLeaseModel)
        .where(
            SourceFetchLeaseModel.source_id == claimed.profile.source_id,
            SourceFetchLeaseModel.lease_token == claimed.lease_token,
            SourceFetchLeaseModel.expires_at >= now,
        )
        .with_for_update()
    )
    if lease is None:
        await session.rollback()
        raise LeaseLostError()
    scheduled_at = max(now, lease.next_request_at or now)
    lease.next_request_at = scheduled_at + timedelta(seconds=max(0.0, minimum_interval_seconds))
    lease.updated_at = now
    await session.commit()
    return max(0.0, (scheduled_at - now).total_seconds())


async def release_source_fetch_lease(
    session: AsyncSession, *, source_id: UUID, lease_token: UUID
) -> None:
    lease = await session.get(SourceFetchLeaseModel, source_id)
    if lease is not None and lease.lease_token == lease_token:
        # Keep the pacing watermark after ownership is released.
        lease.expires_at = _utcnow()
        lease.updated_at = _utcnow()
        await session.commit()


async def get_cursor(session: AsyncSession, source_version_id: UUID) -> CursorState:
    cursor = await session.get(SourceCursorModel, source_version_id)
    if cursor is None:
        return CursorState(None, None, None, None)
    return CursorState(
        cursor.etag, cursor.last_modified, cursor.last_item_id, cursor.last_published_at
    )


async def update_cursor(
    session: AsyncSession,
    *,
    claimed: ClaimedJob,
    source_version_id: UUID,
    etag: str | None,
    last_modified: str | None,
    last_item_id: str | None,
    last_published_at: datetime | None,
) -> None:
    await assert_active_lease(session, claimed=claimed, require_source_lease=True)
    await session.execute(
        insert(SourceCursorModel)
        .values(
            source_version_id=source_version_id,
            etag=etag,
            last_modified=last_modified,
            last_item_id=last_item_id,
            last_published_at=last_published_at,
            cursor_data={},
            lock_version=1,
            updated_at=_utcnow(),
        )
        .on_conflict_do_update(
            index_elements=[SourceCursorModel.source_version_id],
            set_={
                "etag": etag,
                "last_modified": last_modified,
                "last_item_id": last_item_id,
                "last_published_at": last_published_at,
                "lock_version": SourceCursorModel.lock_version + 1,
                "updated_at": _utcnow(),
            },
        )
    )
    await session.commit()


async def persist_snapshot(
    session: AsyncSession,
    *,
    claimed: ClaimedJob,
    profile: SourceProfile,
    kind: str,
    response: FetchedResponse,
    stored: SnapshotDescriptor,
) -> SourceSnapshotModel:
    await assert_active_lease(session, claimed=claimed, require_source_lease=True)
    provenance_key = stable_key(
        profile.source_version_id,
        kind,
        response.requested_url,
        response.final_url,
        stored.sha256,
    )
    snapshot_id = uuid4()
    inserted_id = await session.scalar(
        insert(SourceSnapshotModel)
        .values(
            id=snapshot_id,
            provenance_key=provenance_key,
            source_version_id=profile.source_version_id,
            kind=kind,
            original_url=response.requested_url,
            final_url=response.final_url,
            bucket=stored.bucket,
            object_key=stored.object_key,
            media_type=stored.media_type,
            byte_size=stored.byte_size,
            sha256=stored.sha256,
            response_metadata=response.headers,
            fetched_at=response.fetched_at,
            connector_version=profile.connector_version,
            parser_version=profile.parser_version,
        )
        .on_conflict_do_nothing(constraint="uq_source_snapshots_provenance_key")
        .returning(SourceSnapshotModel.id)
    )
    await session.commit()
    snapshot = await session.get(SourceSnapshotModel, inserted_id or snapshot_id)
    if snapshot is None:
        snapshot = await session.scalar(
            select(SourceSnapshotModel).where(SourceSnapshotModel.provenance_key == provenance_key)
        )
    if snapshot is None:
        raise ConflictError("snapshot provenance could not be persisted idempotently")
    if snapshot.sha256 != stored.sha256 or snapshot.byte_size != stored.byte_size:
        raise ConflictError("snapshot object identity does not match immutable content")
    return snapshot


async def persist_candidate(
    session: AsyncSession,
    *,
    claimed: ClaimedJob,
    profile: SourceProfile,
    document: ExtractedDocument,
    snapshot_id: UUID,
    fetched_at: datetime,
) -> tuple[EvidenceCandidateModel, ObservationOutcome]:
    await assert_active_lease(session, claimed=claimed, require_source_lease=True)
    content_hash = sha256_bytes(document.clean_text.encode())
    existing = await session.scalar(
        select(EvidenceCandidateModel).where(
            EvidenceCandidateModel.source_version_id == profile.source_version_id,
            EvidenceCandidateModel.source_item_id == document.source_item_id,
            EvidenceCandidateModel.content_hash == content_hash,
        )
    )
    if existing is not None:
        return existing, ObservationOutcome.UNCHANGED
    duplicate = await session.scalar(
        select(EvidenceCandidateModel).where(
            EvidenceCandidateModel.content_hash == content_hash,
            or_(
                EvidenceCandidateModel.source_id != profile.source_id,
                EvidenceCandidateModel.source_item_id != document.source_item_id,
            ),
        )
    )
    if duplicate is not None:
        return duplicate, ObservationOutcome.EXACT_DUPLICATE
    candidate_id = uuid4()
    inserted_id = await session.scalar(
        insert(EvidenceCandidateModel)
        .values(
            id=candidate_id,
            source_id=profile.source_id,
            source_version_id=profile.source_version_id,
            source_item_id=document.source_item_id,
            original_url=document.original_url,
            canonical_url=document.canonical_url,
            trust_tier=profile.tier.value,
            title=document.title,
            clean_text=document.clean_text,
            published_at=document.published_at,
            first_fetched_at=fetched_at,
            language=document.language,
            content_hash=content_hash,
            parser_version=document.parser_version,
            relevance_rule_version=profile.relevance_rule_version,
            extraction_metadata=document.extraction_metadata,
            primary_snapshot_id=snapshot_id,
        )
        .on_conflict_do_nothing(constraint="uq_evidence_candidates_item_content")
        .returning(EvidenceCandidateModel.id)
    )
    await session.commit()
    if inserted_id is not None:
        candidate = await session.get(EvidenceCandidateModel, inserted_id)
        if candidate is None:
            raise ConflictError("evidence candidate insert could not be loaded")
        return candidate, ObservationOutcome.NEW
    candidate = await session.scalar(
        select(EvidenceCandidateModel).where(
            EvidenceCandidateModel.source_version_id == profile.source_version_id,
            EvidenceCandidateModel.source_item_id == document.source_item_id,
            EvidenceCandidateModel.content_hash == content_hash,
        )
    )
    if candidate is None:
        raise ConflictError("evidence candidate could not be persisted idempotently")
    return candidate, ObservationOutcome.UNCHANGED


async def add_observation(
    session: AsyncSession,
    *,
    claimed: ClaimedJob,
    run_id: UUID,
    job_id: UUID,
    source_version_id: UUID,
    source_item_id: str | None,
    outcome: ObservationOutcome,
    snapshot_id: UUID | None = None,
    candidate_id: UUID | None = None,
    http_status: int | None = None,
    error_code: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SourceObservationModel:
    await assert_active_lease(session, claimed=claimed, require_source_lease=False)
    key = stable_key(job_id, source_item_id or "list", outcome.value, snapshot_id, candidate_id)
    existing = await session.scalar(
        select(SourceObservationModel).where(SourceObservationModel.idempotency_key == key)
    )
    if existing is not None:
        return existing
    observation = SourceObservationModel(
        id=uuid4(),
        idempotency_key=key,
        run_id=run_id,
        job_id=job_id,
        source_version_id=source_version_id,
        source_item_id=source_item_id,
        outcome=outcome.value,
        http_status=http_status,
        error_code=error_code,
        snapshot_id=snapshot_id,
        candidate_id=candidate_id,
        observed_at=_utcnow(),
        observation_metadata=metadata or {},
    )
    session.add(observation)
    await session.commit()
    await session.refresh(observation)
    return observation


async def finish_attempt(
    session: AsyncSession,
    *,
    claimed: ClaimedJob,
    attempt_id: UUID,
    result: str,
    error_code: str | None,
    byte_count: int,
    item_count: int,
) -> None:
    await assert_active_lease(session, claimed=claimed, require_source_lease=False)
    attempt = await session.get(AcquisitionAttemptModel, attempt_id)
    if attempt is None:
        raise NotFoundError("acquisition attempt")
    attempt.completed_at = _utcnow()
    attempt.result = result
    attempt.error_code = error_code
    attempt.byte_count = byte_count
    attempt.item_count = item_count
    await session.commit()


async def finish_job(
    session: AsyncSession,
    *,
    claimed: ClaimedJob,
    status: JobStatus,
    outcome: str,
    error_code: str | None,
    new_count: int = 0,
    unchanged_count: int = 0,
    duplicate_count: int = 0,
    filtered_count: int = 0,
    byte_count: int = 0,
    retry_at: datetime | None = None,
) -> bool:
    try:
        await assert_active_lease(session, claimed=claimed, require_source_lease=False)
    except LeaseLostError:
        return False
    job = await session.get(AcquisitionJobModel, claimed.job_id)
    if job is None or job.lease_token != claimed.lease_token:
        return False
    now = _utcnow()
    job.status = status.value
    job.outcome = outcome
    job.error_code = error_code
    job.new_count += new_count
    job.unchanged_count += unchanged_count
    job.duplicate_count += duplicate_count
    # Filtering is a property of the terminal scan, not an attempt counter.
    # Retry-scheduled attempts may scan the same list again, so accumulating
    # here would double-count unrelated titles in the job/run projection.
    if status is not JobStatus.RETRY_SCHEDULED:
        job.filtered_count = filtered_count
    job.byte_count += byte_count
    job.available_at = retry_at or now
    if status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
        job.completed_at = now
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    await session.commit()
    if status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
        await complete_run_if_terminal(session, claimed.run_id)
    return True


async def complete_run_if_terminal(session: AsyncSession, run_id: UUID) -> None:
    jobs = list(
        (
            await session.scalars(
                select(AcquisitionJobModel).where(AcquisitionJobModel.run_id == run_id)
            )
        ).all()
    )
    terminal = {JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}
    if not jobs or any(job.status not in terminal for job in jobs):
        return
    succeeded = sum(job.status == JobStatus.SUCCEEDED.value for job in jobs)
    failed = sum(job.status == JobStatus.FAILED.value for job in jobs)
    cancelled = sum(job.status == JobStatus.CANCELLED.value for job in jobs)
    run = await session.get(AcquisitionRunModel, run_id)
    if run is None:
        return
    run.succeeded_jobs = succeeded
    run.failed_jobs = failed
    run.new_count = sum(job.new_count for job in jobs)
    run.unchanged_count = sum(job.unchanged_count for job in jobs)
    run.duplicate_count = sum(job.duplicate_count for job in jobs)
    run.filtered_count = sum(job.filtered_count for job in jobs)
    if cancelled == len(jobs):
        run.status = RunStatus.CANCELLED.value
    elif succeeded == len(jobs):
        run.status = RunStatus.SUCCEEDED.value
    elif succeeded > 0:
        run.status = RunStatus.PARTIALLY_SUCCEEDED.value
    else:
        run.status = RunStatus.FAILED.value
    run.completed_at = _utcnow()
    await session.commit()


async def list_sources(session: AsyncSession) -> list[dict[str, Any]]:
    latest_job = (
        select(
            AcquisitionJobModel.source_id,
            AcquisitionJobModel.completed_at.label("latest_completed_at"),
            AcquisitionJobModel.filtered_count.label("latest_filtered_count"),
            func.row_number()
            .over(
                partition_by=AcquisitionJobModel.source_id,
                order_by=AcquisitionJobModel.completed_at.desc(),
            )
            .label("row_number"),
        )
        .where(AcquisitionJobModel.status == JobStatus.SUCCEEDED.value)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                SourceModel,
                SourceVersionModel,
                latest_job.c.latest_completed_at,
                latest_job.c.latest_filtered_count,
            )
            .join(SourceVersionModel, SourceVersionModel.id == SourceModel.active_version_id)
            .outerjoin(
                latest_job,
                and_(latest_job.c.source_id == SourceModel.id, latest_job.c.row_number == 1),
            )
            .order_by(SourceVersionModel.trust_tier, SourceModel.slug)
        )
    ).all()
    return [
        {
            "id": source.id,
            "slug": source.slug,
            "display_name": source.display_name,
            "organization_type": source.organization_type,
            "enabled": source.enabled,
            "owner": source.owner,
            "tier": version.trust_tier,
            "entry_url": version.entry_url,
            "connector_key": version.connector_key,
            "version": version.version,
            "connector_version": version.connector_version,
            "parser_version": version.parser_version,
            "relevance_rule_version": version.relevance_rule_version,
            "allow_http_fallback": version.allow_http_fallback,
            "topic_priority_policy": version.topic_priority_policy,
            "cadence": version.cadence,
            "timezone": version.timezone,
            "latest_success_at": latest_success,
            "latest_filtered_count": latest_filtered_count,
        }
        for source, version, latest_success, latest_filtered_count in rows
    ]


async def get_run(session: AsyncSession, run_id: UUID) -> AcquisitionRunModel:
    run = await session.get(AcquisitionRunModel, run_id)
    if run is None:
        raise NotFoundError("acquisition run")
    return run


async def list_run_jobs(session: AsyncSession, run_id: UUID) -> list[dict[str, Any]]:
    if await session.get(AcquisitionRunModel, run_id) is None:
        raise NotFoundError("acquisition run")
    rows = (
        await session.execute(
            select(AcquisitionJobModel, SourceModel)
            .join(SourceModel, SourceModel.id == AcquisitionJobModel.source_id)
            .where(AcquisitionJobModel.run_id == run_id)
            .order_by(SourceModel.slug)
        )
    ).all()
    return [
        {
            "id": job.id,
            "source_id": source.id,
            "source_slug": source.slug,
            "status": job.status,
            "outcome": job.outcome,
            "error_code": job.error_code,
            "attempt_count": job.attempt_count,
            "new_count": job.new_count,
            "unchanged_count": job.unchanged_count,
            "duplicate_count": job.duplicate_count,
            "filtered_count": job.filtered_count,
            "byte_count": job.byte_count,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
        }
        for job, source in rows
    ]


async def list_candidates(
    session: AsyncSession,
    *,
    limit: int,
    after: UUID | None = None,
    source_id: UUID | None = None,
    relevance_rule_version: str | None = None,
) -> list[dict[str, Any]]:
    query = (
        select(EvidenceCandidateModel, SourceModel.slug, SourceModel.display_name)
        .join(SourceModel, SourceModel.id == EvidenceCandidateModel.source_id)
        .order_by(EvidenceCandidateModel.created_at.desc(), EvidenceCandidateModel.id.desc())
    )
    if after is not None:
        anchor = await session.get(EvidenceCandidateModel, after)
        if anchor is None:
            raise NotFoundError("candidate cursor")
        query = query.where(
            or_(
                EvidenceCandidateModel.created_at < anchor.created_at,
                and_(
                    EvidenceCandidateModel.created_at == anchor.created_at,
                    EvidenceCandidateModel.id < anchor.id,
                ),
            )
        )
    if source_id is not None:
        query = query.where(EvidenceCandidateModel.source_id == source_id)
    if relevance_rule_version is not None:
        query = query.where(EvidenceCandidateModel.relevance_rule_version == relevance_rule_version)
    rows = (await session.execute(query.limit(limit))).all()
    return [
        {
            "id": candidate.id,
            "source_id": candidate.source_id,
            "source_slug": source_slug,
            "source_display_name": source_display_name,
            "source_item_id": candidate.source_item_id,
            "original_url": candidate.original_url,
            "canonical_url": candidate.canonical_url,
            "trust_tier": candidate.trust_tier,
            "title": candidate.title,
            "published_at": candidate.published_at,
            "first_fetched_at": candidate.first_fetched_at,
            "language": candidate.language,
            "content_hash": candidate.content_hash,
            "parser_version": candidate.parser_version,
            "relevance_rule_version": candidate.relevance_rule_version,
            "created_at": candidate.created_at,
        }
        for candidate, source_slug, source_display_name in rows
    ]


async def get_candidate_detail(session: AsyncSession, candidate_id: UUID) -> dict[str, Any]:
    candidate = await session.get(EvidenceCandidateModel, candidate_id)
    if candidate is None:
        raise NotFoundError("evidence candidate")
    snapshot = await session.get(SourceSnapshotModel, candidate.primary_snapshot_id)
    source = await session.get(SourceModel, candidate.source_id)
    observations = list(
        (
            await session.scalars(
                select(SourceObservationModel)
                .where(SourceObservationModel.candidate_id == candidate_id)
                .order_by(SourceObservationModel.observed_at.desc())
                .limit(100)
            )
        ).all()
    )
    return {
        "candidate": candidate,
        "snapshot": snapshot,
        "source": source,
        "observations": observations,
    }


class PostgresAcquisitionRepository:
    """Short-transaction adapter used by scheduler and worker processes."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def enqueue(
        self,
        *,
        trigger: RunTrigger,
        timezone: str,
        acquisition_version: str,
        business_date: date | None = None,
        content_slot: ContentSlot | None = None,
        manual_idempotency_key: str | None = None,
        source_ids: list[UUID] | None = None,
    ) -> tuple[UUID, bool]:
        async with self._factory() as session:
            run, created = await create_run(
                session,
                trigger=trigger,
                timezone=timezone,
                acquisition_version=acquisition_version,
                business_date=business_date,
                content_slot=content_slot,
                manual_idempotency_key=manual_idempotency_key,
                source_ids=source_ids,
            )
            return run.id, created

    async def claim(self, *, worker_id: str, lease_seconds: int) -> ClaimedJob | None:
        async with self._factory() as session:
            return await claim_job(session, worker_id=worker_id, lease_seconds=lease_seconds)

    async def create_attempt(self, claimed: ClaimedJob) -> UUID:
        async with self._factory() as session:
            return await create_attempt(session, claimed)

    async def heartbeat(self, *, claimed: ClaimedJob, lease_seconds: int) -> bool:
        async with self._factory() as session:
            return await heartbeat_job(
                session,
                claimed=claimed,
                lease_seconds=lease_seconds,
            )

    async def acquire_source_lease(
        self, *, claimed: ClaimedJob, owner: str, lease_seconds: int
    ) -> bool:
        async with self._factory() as session:
            return await acquire_source_fetch_lease(
                session,
                source_id=claimed.profile.source_id,
                owner=owner,
                lease_token=claimed.lease_token,
                lease_seconds=lease_seconds,
            )

    async def reserve_source_request_slot(
        self, *, claimed: ClaimedJob, minimum_interval_seconds: float
    ) -> float:
        async with self._factory() as session:
            return await reserve_source_request_slot(
                session,
                claimed=claimed,
                minimum_interval_seconds=minimum_interval_seconds,
            )

    async def release_source_lease(self, claimed: ClaimedJob) -> None:
        async with self._factory() as session:
            await release_source_fetch_lease(
                session,
                source_id=claimed.profile.source_id,
                lease_token=claimed.lease_token,
            )

    async def cursor(self, source_version_id: UUID) -> CursorState:
        async with self._factory() as session:
            return await get_cursor(session, source_version_id)

    async def save_cursor(
        self,
        *,
        claimed: ClaimedJob,
        source_version_id: UUID,
        etag: str | None,
        last_modified: str | None,
        last_item_id: str | None,
        last_published_at: datetime | None,
    ) -> None:
        async with self._factory() as session:
            await update_cursor(
                session,
                claimed=claimed,
                source_version_id=source_version_id,
                etag=etag,
                last_modified=last_modified,
                last_item_id=last_item_id,
                last_published_at=last_published_at,
            )

    async def save_snapshot(
        self,
        *,
        claimed: ClaimedJob,
        profile: SourceProfile,
        kind: str,
        response: FetchedResponse,
        stored: SnapshotDescriptor,
    ) -> UUID:
        async with self._factory() as session:
            snapshot = await persist_snapshot(
                session,
                claimed=claimed,
                profile=profile,
                kind=kind,
                response=response,
                stored=stored,
            )
            return snapshot.id

    async def save_candidate(
        self,
        *,
        claimed: ClaimedJob,
        profile: SourceProfile,
        document: ExtractedDocument,
        snapshot_id: UUID,
        fetched_at: datetime,
    ) -> PersistedCandidate:
        async with self._factory() as session:
            candidate, outcome = await persist_candidate(
                session,
                claimed=claimed,
                profile=profile,
                document=document,
                snapshot_id=snapshot_id,
                fetched_at=fetched_at,
            )
            return PersistedCandidate(candidate.id, outcome)

    async def observe(
        self,
        *,
        claimed: ClaimedJob,
        source_item_id: str | None,
        outcome: ObservationOutcome,
        snapshot_id: UUID | None = None,
        candidate_id: UUID | None = None,
        http_status: int | None = None,
        error_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with self._factory() as session:
            await add_observation(
                session,
                claimed=claimed,
                run_id=claimed.run_id,
                job_id=claimed.job_id,
                source_version_id=claimed.profile.source_version_id,
                source_item_id=source_item_id,
                outcome=outcome,
                snapshot_id=snapshot_id,
                candidate_id=candidate_id,
                http_status=http_status,
                error_code=error_code,
                metadata=metadata,
            )

    async def complete_attempt(
        self,
        *,
        claimed: ClaimedJob,
        attempt_id: UUID,
        result: str,
        error_code: str | None,
        byte_count: int,
        item_count: int,
    ) -> None:
        async with self._factory() as session:
            await finish_attempt(
                session,
                claimed=claimed,
                attempt_id=attempt_id,
                result=result,
                error_code=error_code,
                byte_count=byte_count,
                item_count=item_count,
            )

    async def complete_job(
        self,
        *,
        claimed: ClaimedJob,
        status: JobStatus,
        outcome: str,
        error_code: str | None,
        new_count: int = 0,
        unchanged_count: int = 0,
        duplicate_count: int = 0,
        filtered_count: int = 0,
        byte_count: int = 0,
        retry_at: datetime | None = None,
    ) -> bool:
        async with self._factory() as session:
            return await finish_job(
                session,
                claimed=claimed,
                status=status,
                outcome=outcome,
                error_code=error_code,
                new_count=new_count,
                unchanged_count=unchanged_count,
                duplicate_count=duplicate_count,
                filtered_count=filtered_count,
                byte_count=byte_count,
                retry_at=retry_at,
            )
