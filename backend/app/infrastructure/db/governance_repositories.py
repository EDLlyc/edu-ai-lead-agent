from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.governance import GovernanceRepository
from app.core.errors import ConflictError, GovernanceLeaseLostError, NotFoundError
from app.domain.enums import SourceTier
from app.domain.governance_entities import (
    ClaimedGovernanceJob,
    GovernanceJobCompletion,
    GovernanceSourceOccurrence,
    GovernanceVersionBundle,
)
from app.domain.governance_enums import (
    GovernanceAttemptResult,
    GovernanceJobStatus,
    GovernanceRunStatus,
    GovernanceRunTrigger,
)
from app.domain.governance_value_objects import (
    event_assignment_advisory_key,
    governance_job_idempotency_key,
    source_occurrence_key,
)
from app.infrastructure.db.models import (
    AcquisitionRunModel,
    ArticleOccurrenceModel,
    EvidenceCandidateModel,
    GovernanceAttemptModel,
    GovernanceJobModel,
    GovernanceRunModel,
    SourceModel,
    SourceObservationModel,
    SourceSnapshotModel,
    SourceVersionModel,
)

_TERMINAL_ACQUISITION_STATUSES = ("succeeded", "partially_succeeded")
_TERMINAL_GOVERNANCE_JOB_STATUSES = {
    GovernanceJobStatus.SUCCEEDED.value,
    GovernanceJobStatus.REVIEW_REQUIRED.value,
    GovernanceJobStatus.FAILED.value,
    GovernanceJobStatus.CANCELLED.value,
}
_UNSAFE_METADATA_KEYS = {
    "api_key",
    "authorization",
    "body",
    "content",
    "database_url",
    "prompt",
    "raw",
    "reasoning_content",
    "response",
    "secret",
    "source_text",
}
_UNSAFE_METADATA_TOKENS = {
    "authorization",
    "blob",
    "body",
    "checkpoint",
    "content",
    "credential",
    "exception",
    "output",
    "password",
    "payload",
    "prompt",
    "raw",
    "reasoning",
    "response",
    "secret",
    "text",
    "traceback",
}
_SAFE_NUMERIC_METADATA_SUFFIXES = {
    "bytes",
    "count",
    "duration",
    "length",
    "ms",
    "size",
    "tokens",
}
_SAFE_STRING_METADATA_SUFFIXES = {"code", "hash", "id", "status", "type", "version"}
_METADATA_TOKEN_ALIASES = {
    "blobs": "blob",
    "bodies": "body",
    "checkpoints": "checkpoint",
    "contents": "content",
    "credentials": "credential",
    "keys": "key",
    "outputs": "output",
    "payloads": "payload",
    "prompts": "prompt",
    "responses": "response",
    "secrets": "secret",
    "texts": "text",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _validated_safe_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    metadata = value or {}

    def key_tokens(key: object) -> tuple[str, ...]:
        snake_case = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", str(key))
        snake_case = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", snake_case)
        return tuple(
            _METADATA_TOKEN_ALIASES.get(token, token)
            for token in re.split(r"[^a-z0-9]+", snake_case.casefold())
            if token
        )

    def is_safe_projection(tokens: tuple[str, ...], node: Any) -> bool:
        if not tokens:
            return False
        suffix = tokens[-1]
        if suffix in _SAFE_NUMERIC_METADATA_SUFFIXES:
            return isinstance(node, (int, float)) and not isinstance(node, bool)
        if suffix in _SAFE_STRING_METADATA_SUFFIXES:
            return isinstance(node, str)
        return False

    def validate_node(node: Any, *, parent_key: object | None = None) -> None:
        if parent_key is not None:
            tokens = key_tokens(parent_key)
            normalized_key = "_".join(tokens)
            forbidden_pair = (
                {"api", "key"}.issubset(tokens)
                or {"database", "url"}.issubset(tokens)
                or {"error", "message"}.issubset(tokens)
                or {"error", "detail"}.issubset(tokens)
            )
            if not is_safe_projection(tokens, node) and (
                normalized_key in _UNSAFE_METADATA_KEYS
                or forbidden_pair
                or bool(set(tokens) & _UNSAFE_METADATA_TOKENS)
            ):
                raise ValueError("safe metadata contains a forbidden content or credential field")
        if isinstance(node, dict):
            for key, nested in node.items():
                validate_node(nested, parent_key=key)
            return
        if isinstance(node, (list, tuple)):
            for nested in node:
                validate_node(nested)
            return
        if node is not None and not isinstance(node, (str, int, float, bool)):
            raise ValueError("safe metadata must contain only JSON-compatible scalar values")
        if isinstance(node, str) and len(node) > 2_000:
            raise ValueError("safe metadata string exceeds the bounded audit size")

    validate_node(metadata)
    if len(json.dumps(metadata, ensure_ascii=False, default=str)) > 16_384:
        raise ValueError("safe metadata exceeds the bounded audit size")
    return metadata


async def create_governance_run_for_acquisition(
    session: AsyncSession,
    *,
    acquisition_run_id: UUID,
    bundle: GovernanceVersionBundle,
    timezone: str,
) -> tuple[GovernanceRunModel, bool]:
    acquisition_run = await session.get(AcquisitionRunModel, acquisition_run_id)
    if acquisition_run is None:
        raise NotFoundError("acquisition run")
    if acquisition_run.status not in _TERMINAL_ACQUISITION_STATUSES:
        raise ConflictError("acquisition run must be terminal before governance enqueue")
    candidate_rows = list(
        (
            await session.execute(
                select(EvidenceCandidateModel.id, EvidenceCandidateModel.content_hash)
                .join(
                    SourceObservationModel,
                    SourceObservationModel.candidate_id == EvidenceCandidateModel.id,
                )
                .where(
                    SourceObservationModel.run_id == acquisition_run_id,
                    SourceObservationModel.candidate_id.is_not(None),
                )
                .distinct()
                .order_by(EvidenceCandidateModel.id)
            )
        ).tuples()
    )
    run_id = uuid4()
    initial_status = (
        GovernanceRunStatus.QUEUED.value if candidate_rows else GovernanceRunStatus.SUCCEEDED.value
    )
    inserted_id = await session.scalar(
        insert(GovernanceRunModel)
        .values(
            id=run_id,
            trigger=GovernanceRunTrigger.ACQUISITION.value,
            acquisition_run_id=acquisition_run_id,
            timezone=timezone,
            profile_fingerprint=bundle.fingerprint,
            version_bundle=bundle.as_metadata(),
            status=initial_status,
            total_jobs=len(candidate_rows),
            completed_at=None if candidate_rows else _utcnow(),
        )
        .on_conflict_do_nothing()
        .returning(GovernanceRunModel.id)
    )
    if inserted_id is None:
        await session.rollback()
        existing = await session.scalar(
            select(GovernanceRunModel).where(
                GovernanceRunModel.acquisition_run_id == acquisition_run_id,
                GovernanceRunModel.profile_fingerprint == bundle.fingerprint,
            )
        )
        if existing is None:
            raise RuntimeError("governance run conflict could not be resolved")
        return existing, False

    for candidate_id, content_hash in candidate_rows:
        session.add(
            GovernanceJobModel(
                id=uuid4(),
                run_id=run_id,
                candidate_id=candidate_id,
                input_content_hash=content_hash,
                idempotency_key=governance_job_idempotency_key(candidate_id, content_hash, bundle),
                status=GovernanceJobStatus.QUEUED.value,
            )
        )
    await session.commit()
    run = await session.get(GovernanceRunModel, run_id)
    if run is None:
        raise RuntimeError("created governance run could not be loaded")
    return run, True


async def create_manual_governance_run(
    session: AsyncSession,
    *,
    candidate_ids: tuple[UUID, ...],
    idempotency_key: str,
    bundle: GovernanceVersionBundle,
    timezone: str,
) -> tuple[GovernanceRunModel, bool]:
    unique_candidate_ids = tuple(sorted(set(candidate_ids), key=lambda value: value.int))
    if not unique_candidate_ids or len(unique_candidate_ids) > 100:
        raise ValueError("manual governance runs require 1 to 100 unique candidates")
    if not idempotency_key.strip() or len(idempotency_key) > 128:
        raise ValueError("manual governance idempotency key must be non-blank and bounded")
    candidate_rows = list(
        (
            await session.execute(
                select(EvidenceCandidateModel.id, EvidenceCandidateModel.content_hash)
                .where(EvidenceCandidateModel.id.in_(unique_candidate_ids))
                .order_by(EvidenceCandidateModel.id)
            )
        ).tuples()
    )
    if len(candidate_rows) != len(unique_candidate_ids):
        raise NotFoundError("evidence candidate")
    run_id = uuid4()
    inserted_id = await session.scalar(
        insert(GovernanceRunModel)
        .values(
            id=run_id,
            trigger=GovernanceRunTrigger.MANUAL.value,
            acquisition_run_id=None,
            manual_idempotency_key=idempotency_key.strip(),
            timezone=timezone,
            profile_fingerprint=bundle.fingerprint,
            version_bundle=bundle.as_metadata(),
            status=GovernanceRunStatus.QUEUED.value,
            total_jobs=len(candidate_rows),
        )
        .on_conflict_do_nothing()
        .returning(GovernanceRunModel.id)
    )
    if inserted_id is None:
        await session.rollback()
        existing = await session.scalar(
            select(GovernanceRunModel).where(
                GovernanceRunModel.manual_idempotency_key == idempotency_key.strip()
            )
        )
        if existing is None:
            raise RuntimeError("manual governance run conflict could not be resolved")
        return existing, False
    for candidate_id, content_hash in candidate_rows:
        session.add(
            GovernanceJobModel(
                id=uuid4(),
                run_id=run_id,
                candidate_id=candidate_id,
                input_content_hash=content_hash,
                idempotency_key=governance_job_idempotency_key(candidate_id, content_hash, bundle),
                status=GovernanceJobStatus.QUEUED.value,
            )
        )
    await session.commit()
    run = await session.get(GovernanceRunModel, run_id)
    if run is None:
        raise RuntimeError("created manual governance run could not be loaded")
    return run, True


async def reconcile_terminal_acquisition_runs(
    session: AsyncSession,
    *,
    bundle: GovernanceVersionBundle,
    timezone: str,
    limit: int = 20,
) -> int:
    acquisition_runs = list(
        (
            await session.scalars(
                select(AcquisitionRunModel)
                .where(
                    AcquisitionRunModel.status.in_(_TERMINAL_ACQUISITION_STATUSES),
                    ~select(GovernanceRunModel.id)
                    .where(
                        GovernanceRunModel.acquisition_run_id == AcquisitionRunModel.id,
                        GovernanceRunModel.profile_fingerprint == bundle.fingerprint,
                    )
                    .exists(),
                )
                .order_by(AcquisitionRunModel.completed_at, AcquisitionRunModel.id)
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        ).all()
    )
    created = 0
    for acquisition_run in acquisition_runs:
        _, was_created = await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=acquisition_run.id,
            bundle=bundle,
            timezone=timezone,
        )
        created += int(was_created)
    return created


async def claim_governance_job(
    session: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: int,
    run_id: UUID | None = None,
    now: datetime | None = None,
) -> ClaimedGovernanceJob | None:
    current = now or _utcnow()
    claimable = or_(
        and_(
            GovernanceJobModel.status.in_(
                [
                    GovernanceJobStatus.QUEUED.value,
                    GovernanceJobStatus.RETRY_SCHEDULED.value,
                ]
            ),
            GovernanceJobModel.available_at <= current,
        ),
        and_(
            GovernanceJobModel.status == GovernanceJobStatus.RUNNING.value,
            GovernanceJobModel.lease_expires_at < current,
        ),
    )
    statement = select(GovernanceJobModel).where(claimable)
    if run_id is not None:
        statement = statement.where(GovernanceJobModel.run_id == run_id)
    job = await session.scalar(
        statement.order_by(GovernanceJobModel.available_at, GovernanceJobModel.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        await session.rollback()
        return None
    run = await session.get(GovernanceRunModel, job.run_id)
    if run is None:
        raise RuntimeError("governance job references a missing run")
    token = uuid4()
    job.status = GovernanceJobStatus.RUNNING.value
    job.attempt_count += 1
    job.lease_owner = worker_id
    job.lease_token = token
    job.lease_expires_at = current + timedelta(seconds=lease_seconds)
    job.heartbeat_at = current
    job.started_at = job.started_at or current
    if run.status == GovernanceRunStatus.QUEUED.value:
        run.status = GovernanceRunStatus.RUNNING.value
        run.started_at = current
    await session.commit()
    return ClaimedGovernanceJob(
        job_id=job.id,
        run_id=job.run_id,
        candidate_id=job.candidate_id,
        attempt_number=job.attempt_count,
        lease_token=token,
        input_content_hash=job.input_content_hash,
        idempotency_key=job.idempotency_key,
        version_bundle=GovernanceVersionBundle.from_metadata(run.version_bundle),
    )


async def assert_active_governance_lease(
    session: AsyncSession,
    claimed: ClaimedGovernanceJob,
    *,
    for_update: bool = False,
) -> None:
    statement = select(GovernanceJobModel.id).where(
        GovernanceJobModel.id == claimed.job_id,
        GovernanceJobModel.lease_token == claimed.lease_token,
        GovernanceJobModel.status == GovernanceJobStatus.RUNNING.value,
        GovernanceJobModel.lease_expires_at >= _utcnow(),
    )
    if for_update:
        statement = statement.with_for_update()
    active = await session.scalar(statement)
    if active is None:
        raise GovernanceLeaseLostError()


async def heartbeat_governance_job(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    lease_seconds: int,
) -> bool:
    now = _utcnow()
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(GovernanceJobModel)
            .where(
                GovernanceJobModel.id == claimed.job_id,
                GovernanceJobModel.lease_token == claimed.lease_token,
                GovernanceJobModel.status == GovernanceJobStatus.RUNNING.value,
                GovernanceJobModel.lease_expires_at >= now,
            )
            .values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=lease_seconds))
        ),
    )
    if not result.rowcount:
        await session.rollback()
        return False
    await session.commit()
    return True


async def update_governance_job_stage(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    stage: str,
) -> None:
    normalized_stage = stage.strip()
    if not normalized_stage or len(normalized_stage) > 80:
        raise ValueError("governance stage must be non-blank and at most 80 characters")
    await assert_active_governance_lease(session, claimed, for_update=True)
    job = await session.get(GovernanceJobModel, claimed.job_id)
    if job is None:
        raise NotFoundError("governance job")
    job.current_stage = normalized_stage
    await assert_active_governance_lease(session, claimed, for_update=True)
    await session.commit()


async def create_governance_attempt(
    session: AsyncSession,
    claimed: ClaimedGovernanceJob,
    *,
    stage: str,
) -> UUID:
    await assert_active_governance_lease(session, claimed)
    job = await session.get(GovernanceJobModel, claimed.job_id)
    if job is None:
        raise NotFoundError("governance job")
    job.current_stage = stage
    attempt_id = uuid4()
    inserted_id = await session.scalar(
        insert(GovernanceAttemptModel)
        .values(
            id=attempt_id,
            job_id=claimed.job_id,
            attempt_number=claimed.attempt_number,
            stage=stage,
            started_at=_utcnow(),
        )
        .on_conflict_do_nothing(constraint="uq_governance_attempts_job_number")
        .returning(GovernanceAttemptModel.id)
    )
    await session.commit()
    if inserted_id is not None:
        return inserted_id
    existing_id = await session.scalar(
        select(GovernanceAttemptModel.id).where(
            GovernanceAttemptModel.job_id == claimed.job_id,
            GovernanceAttemptModel.attempt_number == claimed.attempt_number,
        )
    )
    if existing_id is None:
        raise RuntimeError("governance attempt conflict could not be resolved")
    return existing_id


async def complete_governance_attempt(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    attempt_id: UUID,
    result: GovernanceAttemptResult,
    stage: str,
    error_code: str | None = None,
    safe_metadata: dict[str, Any] | None = None,
) -> None:
    await assert_active_governance_lease(session, claimed)
    attempt = await session.get(GovernanceAttemptModel, attempt_id)
    if attempt is None or attempt.job_id != claimed.job_id:
        raise NotFoundError("governance attempt")
    attempt.stage = stage
    attempt.result = result.value
    attempt.error_code = error_code
    attempt.safe_metadata = _validated_safe_metadata(safe_metadata)
    attempt.completed_at = _utcnow()
    job = await session.get(GovernanceJobModel, claimed.job_id)
    if job is not None:
        job.current_stage = stage
    await session.commit()


async def synchronize_source_occurrences(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
) -> list[GovernanceSourceOccurrence]:
    await assert_active_governance_lease(session, claimed)
    candidate_id = claimed.candidate_id
    rows = list(
        (
            await session.execute(
                select(
                    SourceObservationModel,
                    SourceSnapshotModel,
                    SourceVersionModel,
                    SourceModel,
                    EvidenceCandidateModel,
                )
                .join(
                    SourceSnapshotModel,
                    SourceSnapshotModel.id == SourceObservationModel.snapshot_id,
                )
                .join(
                    SourceVersionModel,
                    SourceVersionModel.id == SourceObservationModel.source_version_id,
                )
                .join(SourceModel, SourceModel.id == SourceVersionModel.source_id)
                .join(
                    EvidenceCandidateModel,
                    EvidenceCandidateModel.id == SourceObservationModel.candidate_id,
                )
                .where(
                    SourceObservationModel.candidate_id == candidate_id,
                    SourceObservationModel.snapshot_id.is_not(None),
                    SourceObservationModel.source_item_id.is_not(None),
                )
                .order_by(SourceObservationModel.observed_at, SourceObservationModel.id)
            )
        ).tuples()
    )
    for observation, snapshot, version, source, candidate in rows:
        item_id = cast(str, observation.source_item_id)
        key = source_occurrence_key(candidate_id, observation.id, snapshot.id, item_id)
        await session.execute(
            insert(ArticleOccurrenceModel)
            .values(
                id=uuid4(),
                occurrence_key=key,
                candidate_id=candidate_id,
                observation_id=observation.id,
                snapshot_id=snapshot.id,
                source_id=source.id,
                source_version_id=version.id,
                source_item_id=item_id,
                source_slug=source.slug,
                source_display_name=source.display_name,
                trust_tier=version.trust_tier,
                original_url=snapshot.original_url,
                final_url=snapshot.final_url,
                # Acquisition can reuse a candidate for an exact duplicate from another
                # source. Its publication time belongs only to the retained candidate's own
                # source item; historical observations do not contain a second source's time.
                published_at=(
                    candidate.published_at
                    if candidate.source_version_id == version.id
                    and candidate.source_item_id == item_id
                    else None
                ),
                fetched_at=snapshot.fetched_at,
                parser_version=snapshot.parser_version,
                relevance_rule_version=version.relevance_rule_version,
            )
            .on_conflict_do_nothing(constraint="uq_article_occurrences_occurrence_key")
        )
    await assert_active_governance_lease(session, claimed)
    await session.commit()
    await assert_active_governance_lease(session, claimed)
    occurrences = list(
        (
            await session.scalars(
                select(ArticleOccurrenceModel)
                .where(ArticleOccurrenceModel.candidate_id == candidate_id)
                .order_by(ArticleOccurrenceModel.fetched_at, ArticleOccurrenceModel.id)
            )
        ).all()
    )
    return [
        GovernanceSourceOccurrence(
            occurrence_id=occurrence.id,
            candidate_id=occurrence.candidate_id,
            observation_id=occurrence.observation_id,
            snapshot_id=occurrence.snapshot_id,
            source_id=occurrence.source_id,
            source_version_id=occurrence.source_version_id,
            source_item_id=occurrence.source_item_id,
            source_slug=occurrence.source_slug,
            source_display_name=occurrence.source_display_name,
            trust_tier=SourceTier(occurrence.trust_tier),
            original_url=occurrence.original_url,
            final_url=occurrence.final_url,
            published_at=occurrence.published_at,
            fetched_at=occurrence.fetched_at,
            parser_version=occurrence.parser_version,
            relevance_rule_version=occurrence.relevance_rule_version,
        )
        for occurrence in occurrences
    ]


async def acquire_event_assignment_lock(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    normalized_article_id: UUID,
    policy_version: str,
    wait: bool = True,
) -> bool:
    """Acquire a transaction-scoped lock for the final mutable assignment decision."""

    await assert_active_governance_lease(session, claimed)
    lock_key = event_assignment_advisory_key(normalized_article_id, policy_version)
    statement = (
        text("SELECT pg_advisory_xact_lock(:lock_key)")
        if wait
        else text("SELECT pg_try_advisory_xact_lock(:lock_key)")
    )
    result = await session.scalar(statement, {"lock_key": lock_key})
    return True if wait else bool(result)


async def complete_governance_run_if_terminal(session: AsyncSession, run_id: UUID) -> None:
    jobs = list(
        (
            await session.scalars(
                select(GovernanceJobModel).where(GovernanceJobModel.run_id == run_id)
            )
        ).all()
    )
    if not jobs or any(job.status not in _TERMINAL_GOVERNANCE_JOB_STATUSES for job in jobs):
        return
    run = await session.get(GovernanceRunModel, run_id)
    if run is None:
        return
    succeeded = sum(job.status == GovernanceJobStatus.SUCCEEDED.value for job in jobs)
    review = sum(job.status == GovernanceJobStatus.REVIEW_REQUIRED.value for job in jobs)
    failed = sum(job.status == GovernanceJobStatus.FAILED.value for job in jobs)
    cancelled = sum(job.status == GovernanceJobStatus.CANCELLED.value for job in jobs)
    run.succeeded_jobs = succeeded
    run.review_jobs = review
    run.failed_jobs = failed
    if cancelled == len(jobs):
        run.status = GovernanceRunStatus.CANCELLED.value
    elif failed == len(jobs):
        run.status = GovernanceRunStatus.FAILED.value
    elif failed or review or cancelled:
        run.status = GovernanceRunStatus.PARTIALLY_SUCCEEDED.value
    else:
        run.status = GovernanceRunStatus.SUCCEEDED.value
    run.completed_at = _utcnow()
    await session.commit()


async def finish_governance_job(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    completion: GovernanceJobCompletion,
) -> bool:
    allowed_completion_statuses = {
        GovernanceJobStatus.RETRY_SCHEDULED,
        GovernanceJobStatus.SUCCEEDED,
        GovernanceJobStatus.REVIEW_REQUIRED,
        GovernanceJobStatus.FAILED,
        GovernanceJobStatus.CANCELLED,
    }
    if completion.status not in allowed_completion_statuses:
        raise ValueError("governance completion must be retryable or terminal")
    if completion.status is GovernanceJobStatus.RETRY_SCHEDULED and completion.retry_at is None:
        raise ValueError("retry-scheduled governance completion requires retry_at")
    try:
        await assert_active_governance_lease(session, claimed)
    except GovernanceLeaseLostError:
        return False
    job = await session.get(GovernanceJobModel, claimed.job_id)
    if job is None or job.lease_token != claimed.lease_token:
        return False
    now = _utcnow()
    job.status = completion.status.value
    job.outcome = completion.outcome
    job.error_code = completion.error_code
    job.safe_metadata = _validated_safe_metadata(completion.safe_metadata)
    job.available_at = completion.retry_at or now
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    if completion.status.value in _TERMINAL_GOVERNANCE_JOB_STATUSES:
        job.completed_at = now
    await session.commit()
    if completion.status.value in _TERMINAL_GOVERNANCE_JOB_STATUSES:
        await complete_governance_run_if_terminal(session, claimed.run_id)
    return True


class PostgresGovernanceRepository(GovernanceRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_run_for_acquisition(
        self,
        *,
        acquisition_run_id: UUID,
        bundle: GovernanceVersionBundle,
        timezone: str,
    ) -> UUID:
        async with self._session_factory() as session:
            run, _ = await create_governance_run_for_acquisition(
                session,
                acquisition_run_id=acquisition_run_id,
                bundle=bundle,
                timezone=timezone,
            )
        return run.id

    async def create_manual_run(
        self,
        *,
        candidate_ids: tuple[UUID, ...],
        idempotency_key: str,
        bundle: GovernanceVersionBundle,
        timezone: str,
    ) -> UUID:
        async with self._session_factory() as session:
            run, _ = await create_manual_governance_run(
                session,
                candidate_ids=candidate_ids,
                idempotency_key=idempotency_key,
                bundle=bundle,
                timezone=timezone,
            )
        return run.id

    async def reconcile_terminal_acquisition_runs(
        self, *, bundle: GovernanceVersionBundle, timezone: str, limit: int = 20
    ) -> int:
        async with self._session_factory() as session:
            return await reconcile_terminal_acquisition_runs(
                session, bundle=bundle, timezone=timezone, limit=limit
            )

    async def claim(self, *, worker_id: str, lease_seconds: int) -> ClaimedGovernanceJob | None:
        async with self._session_factory() as session:
            return await claim_governance_job(
                session, worker_id=worker_id, lease_seconds=lease_seconds
            )

    async def claim_for_run(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        lease_seconds: int,
    ) -> ClaimedGovernanceJob | None:
        async with self._session_factory() as session:
            return await claim_governance_job(
                session,
                run_id=run_id,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )

    async def heartbeat(self, *, claimed: ClaimedGovernanceJob, lease_seconds: int) -> bool:
        async with self._session_factory() as session:
            return await heartbeat_governance_job(
                session, claimed=claimed, lease_seconds=lease_seconds
            )

    async def update_stage(self, claimed: ClaimedGovernanceJob, *, stage: str) -> None:
        async with self._session_factory() as session:
            await update_governance_job_stage(session, claimed=claimed, stage=stage)

    async def create_attempt(self, claimed: ClaimedGovernanceJob, *, stage: str) -> UUID:
        async with self._session_factory() as session:
            return await create_governance_attempt(session, claimed, stage=stage)

    async def complete_attempt(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        attempt_id: UUID,
        result: GovernanceAttemptResult,
        stage: str,
        error_code: str | None = None,
        safe_metadata: dict[str, Any] | None = None,
    ) -> None:
        async with self._session_factory() as session:
            await complete_governance_attempt(
                session,
                claimed=claimed,
                attempt_id=attempt_id,
                result=result,
                stage=stage,
                error_code=error_code,
                safe_metadata=safe_metadata,
            )

    async def synchronize_occurrences(
        self, claimed: ClaimedGovernanceJob
    ) -> list[GovernanceSourceOccurrence]:
        async with self._session_factory() as session:
            return await synchronize_source_occurrences(session, claimed=claimed)

    async def complete_job(
        self, *, claimed: ClaimedGovernanceJob, completion: GovernanceJobCompletion
    ) -> bool:
        async with self._session_factory() as session:
            return await finish_governance_job(session, claimed=claimed, completion=completion)
