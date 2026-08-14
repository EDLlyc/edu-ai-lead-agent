from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.content_slots import (
    ClaimedContentSlotJob,
    GovernedSlotLineage,
)
from app.core.errors import ConflictError, NotFoundError
from app.domain.content_slots import (
    ContentSlot,
    ContentSlotDecision,
    ContentSlotSchedule,
    ContentSlotScore,
    SlotRankingPolicy,
)
from app.domain.topic_selection import TopicCandidate, TopicScoringConfig
from app.infrastructure.db.models import (
    AcquisitionRunModel,
    ContentSlotJobModel,
    ContentSlotRunModel,
    ContentSlotScoreModel,
    ContentSlotSelectionModel,
    DailyTopicSelectionModel,
    EventClusterVersionModel,
    GovernanceJobModel,
    GovernanceRunModel,
)
from app.infrastructure.db.topic_selection import (
    ensure_topic_scoring_config,
    load_governed_topic_candidates,
    topic_scoring_config_fingerprint,
)

_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_TERMINAL_ACQUISITION_STATUSES = ("succeeded", "partially_succeeded")
_TERMINAL_GOVERNANCE_RUN_STATUSES = ("succeeded", "partially_succeeded")
_NON_TERMINAL_GOVERNANCE_JOB_STATUSES = ("queued", "running", "retry_scheduled")
_MAX_DAILY_SLOT_SELECTIONS = 9


@dataclass(frozen=True, slots=True)
class ContentSlotScoreProjection:
    score: ContentSlotScoreModel
    event_title: str
    event_time: datetime | None


@dataclass(frozen=True, slots=True)
class ContentSlotSelectionProjection:
    selection: ContentSlotSelectionModel
    title: str
    event_time: datetime | None


@dataclass(frozen=True, slots=True)
class ContentSlotRunProjection:
    run: ContentSlotRunModel
    selections: tuple[ContentSlotSelectionProjection, ...]


async def _lock_business_date(session: AsyncSession, business_date: date, timezone: str) -> None:
    lock_key = f"content-slot:{business_date.isoformat()}:{timezone}"
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(lock_key))))


async def get_ready_slot_lineage(
    session: AsyncSession,
    *,
    business_date: date,
    timezone: str,
    slot: ContentSlot,
    now: datetime,
) -> GovernedSlotLineage | None:
    if now.tzinfo is None:
        raise ValueError("content slot readiness time must be timezone-aware")
    acquisition = await session.scalar(
        select(AcquisitionRunModel)
        .where(
            AcquisitionRunModel.trigger == "scheduled",
            AcquisitionRunModel.business_date == business_date,
            AcquisitionRunModel.timezone == timezone,
            AcquisitionRunModel.content_slot == slot.value,
            AcquisitionRunModel.status.in_(_TERMINAL_ACQUISITION_STATUSES),
        )
        .order_by(AcquisitionRunModel.completed_at.desc(), AcquisitionRunModel.id.desc())
        .limit(1)
    )
    if acquisition is None:
        return None
    governance = await session.scalar(
        select(GovernanceRunModel)
        .where(
            GovernanceRunModel.acquisition_run_id == acquisition.id,
            GovernanceRunModel.status.in_(_TERMINAL_GOVERNANCE_RUN_STATUSES),
        )
        .order_by(GovernanceRunModel.completed_at.desc(), GovernanceRunModel.id.desc())
        .limit(1)
    )
    if governance is None or governance.completed_at is None:
        return None
    pending_job = await session.scalar(
        select(GovernanceJobModel.id)
        .where(
            GovernanceJobModel.run_id == governance.id,
            GovernanceJobModel.status.in_(_NON_TERMINAL_GOVERNANCE_JOB_STATUSES),
        )
        .limit(1)
    )
    if pending_job is not None:
        return None
    cutoff = min(now.astimezone(UTC), governance.completed_at.astimezone(UTC))
    return GovernedSlotLineage(
        acquisition_run_id=acquisition.id,
        governance_run_id=governance.id,
        governed_event_cutoff=cutoff,
    )


async def enqueue_content_slot_run(
    session: AsyncSession,
    *,
    business_date: date,
    timezone: str,
    schedule: ContentSlotSchedule,
    config: TopicScoringConfig,
    policy: SlotRankingPolicy,
    lineage: GovernedSlotLineage,
    trigger: str,
) -> tuple[ContentSlotRunModel, bool]:
    if trigger not in {"manual", "scheduled"}:
        raise ValueError("content slot trigger must be manual or scheduled")
    if lineage.governed_event_cutoff.tzinfo is None:
        raise ValueError("content slot governed cutoff must be timezone-aware")
    if not timezone.strip() or len(timezone) > 80:
        raise ValueError("content slot timezone must be non-blank and bounded")
    await _lock_business_date(session, business_date, timezone)
    stored_config = await ensure_topic_scoring_config(session, config)
    instants = schedule.instants(business_date, timezone)
    existing = await session.scalar(
        select(ContentSlotRunModel)
        .where(
            ContentSlotRunModel.business_date == business_date,
            ContentSlotRunModel.timezone == timezone,
            ContentSlotRunModel.content_slot == schedule.slot.value,
            ContentSlotRunModel.scoring_profile == config.profile,
            ContentSlotRunModel.slot_policy_fingerprint == policy.fingerprint,
        )
        .with_for_update()
    )
    if existing is not None:
        if (
            existing.acquisition_run_id != lineage.acquisition_run_id
            or existing.governance_run_id != lineage.governance_run_id
            or existing.governed_event_cutoff != lineage.governed_event_cutoff
            or existing.config_fingerprint != stored_config.fingerprint
            or existing.config_snapshot != config.as_metadata()
            or existing.slot_policy_snapshot != policy.as_metadata()
            or existing.item_limit != schedule.max_items
        ):
            await session.rollback()
            raise ConflictError("content slot run identity is immutable")
        await session.commit()
        return existing, False

    run_id = uuid4()
    run = ContentSlotRunModel(
        id=run_id,
        trigger=trigger,
        business_date=business_date,
        timezone=timezone,
        content_slot=schedule.slot.value,
        scoring_profile=config.profile,
        acquisition_run_id=lineage.acquisition_run_id,
        governance_run_id=lineage.governance_run_id,
        governed_event_cutoff=lineage.governed_event_cutoff,
        config_id=stored_config.id,
        config_fingerprint=stored_config.fingerprint,
        config_snapshot=config.as_metadata(),
        slot_policy_version=policy.version,
        slot_policy_fingerprint=policy.fingerprint,
        slot_policy_snapshot=policy.as_metadata(),
        preparation_at=instants.preparation_at,
        target_at=instants.target_at,
        expires_at=instants.expires_at,
        item_limit=schedule.max_items,
        status="queued",
        unfilled_count=schedule.max_items,
    )
    session.add(run)
    # These tables intentionally have no ORM relationship; persist the parent
    # before adding the durable job child so SQLAlchemy cannot reorder inserts.
    await session.flush()
    session.add(ContentSlotJobModel(id=uuid4(), run_id=run_id, status="queued"))
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        duplicate = await session.scalar(
            select(ContentSlotRunModel).where(
                ContentSlotRunModel.business_date == business_date,
                ContentSlotRunModel.timezone == timezone,
                ContentSlotRunModel.content_slot == schedule.slot.value,
                ContentSlotRunModel.scoring_profile == config.profile,
                ContentSlotRunModel.slot_policy_fingerprint == policy.fingerprint,
            )
        )
        if duplicate is None:
            raise
        return duplicate, False
    await session.refresh(run)
    return run, True


async def claim_content_slot_job(
    session: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: int,
    max_attempts: int,
) -> ClaimedContentSlotJob | None:
    normalized_worker_id = worker_id.strip()
    if not normalized_worker_id or len(normalized_worker_id) > 200:
        raise ValueError("content slot worker ID must be non-blank and bounded")
    if lease_seconds < 1 or max_attempts < 1:
        raise ValueError("content slot lease and attempts must be positive")
    now = datetime.now(UTC)
    exhausted = tuple(
        (
            await session.scalars(
                select(ContentSlotJobModel)
                .where(
                    ContentSlotJobModel.status == "running",
                    ContentSlotJobModel.lease_expires_at < now,
                    ContentSlotJobModel.attempt_count >= max_attempts,
                )
                .with_for_update(skip_locked=True)
                .limit(100)
            )
        ).all()
    )
    for exhausted_job in exhausted:
        exhausted_job.status = "failed"
        exhausted_job.error_code = "max_attempts_exhausted"
        exhausted_job.completed_at = now
        exhausted_job.lease_owner = None
        exhausted_job.lease_token = None
        exhausted_job.lease_expires_at = None
        run = await session.get(ContentSlotRunModel, exhausted_job.run_id)
        if run is not None and run.status != "succeeded":
            run.status = "failed"
            run.error_code = "max_attempts_exhausted"
            run.completed_at = now
    claimed_job = await session.scalar(
        select(ContentSlotJobModel)
        .where(
            ContentSlotJobModel.available_at <= now,
            or_(
                ContentSlotJobModel.status == "queued",
                and_(
                    ContentSlotJobModel.status == "running",
                    ContentSlotJobModel.lease_expires_at < now,
                    ContentSlotJobModel.attempt_count < max_attempts,
                ),
            ),
        )
        .order_by(ContentSlotJobModel.available_at, ContentSlotJobModel.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if claimed_job is None:
        if exhausted:
            await session.commit()
        else:
            await session.rollback()
        return None
    run = await session.get(ContentSlotRunModel, claimed_job.run_id)
    if run is None:
        raise RuntimeError("content slot job has no run")
    lease_token = uuid4()
    claimed_job.status = "running"
    claimed_job.attempt_count += 1
    claimed_job.lease_owner = normalized_worker_id
    claimed_job.lease_token = lease_token
    claimed_job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    claimed_job.heartbeat_at = now
    claimed_job.started_at = claimed_job.started_at or now
    claimed_job.error_code = None
    claimed_job.completed_at = None
    run.status = "running"
    run.started_at = run.started_at or now
    await session.commit()
    return ClaimedContentSlotJob(
        job_id=claimed_job.id,
        run_id=run.id,
        attempt_number=claimed_job.attempt_count,
        lease_token=lease_token,
        business_date=run.business_date,
        timezone=run.timezone,
        slot=ContentSlot(run.content_slot),
        cutoff_at=run.governed_event_cutoff,
        item_limit=run.item_limit,
    )


async def heartbeat_content_slot_job(
    session: AsyncSession,
    *,
    claimed: ClaimedContentSlotJob,
    lease_seconds: int,
) -> bool:
    now = datetime.now(UTC)
    result = cast(
        CursorResult[object],
        await session.execute(
            update(ContentSlotJobModel)
            .where(
                ContentSlotJobModel.id == claimed.job_id,
                ContentSlotJobModel.run_id == claimed.run_id,
                ContentSlotJobModel.lease_token == claimed.lease_token,
                ContentSlotJobModel.status == "running",
                ContentSlotJobModel.lease_expires_at >= now,
            )
            .values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=lease_seconds))
        ),
    )
    if not result.rowcount:
        await session.rollback()
        return False
    await session.commit()
    return True


async def load_content_slot_candidates(
    session: AsyncSession, run_id: UUID
) -> tuple[TopicCandidate, ...]:
    run = await session.get(ContentSlotRunModel, run_id)
    if run is None:
        raise NotFoundError("content slot run")
    return await load_governed_topic_candidates(
        session,
        business_date=run.business_date,
        timezone=run.timezone,
        scoring_profile=run.scoring_profile,
        governed_event_cutoff=run.governed_event_cutoff,
        config_snapshot=run.config_snapshot,
        include_content_slot_history=True,
    )


async def load_content_slot_config(session: AsyncSession, run_id: UUID) -> TopicScoringConfig:
    run = await session.get(ContentSlotRunModel, run_id)
    if run is None:
        raise NotFoundError("content slot run")
    return TopicScoringConfig.from_metadata(run.config_snapshot)


async def load_content_slot_policy(session: AsyncSession, run_id: UUID) -> SlotRankingPolicy:
    run = await session.get(ContentSlotRunModel, run_id)
    if run is None:
        raise NotFoundError("content slot run")
    maximum_affinity = run.slot_policy_snapshot.get("maximum_affinity")
    if isinstance(maximum_affinity, bool) or not isinstance(maximum_affinity, (int, float)):
        raise ValueError("stored content slot ranking policy is invalid")
    return SlotRankingPolicy(
        version=run.slot_policy_version,
        maximum_affinity=float(maximum_affinity),
    )


async def get_same_day_selected_event_ids(session: AsyncSession, run_id: UUID) -> frozenset[UUID]:
    run = await session.get(ContentSlotRunModel, run_id)
    if run is None:
        raise NotFoundError("content slot run")
    slot_ids = set(
        (
            await session.scalars(
                select(ContentSlotSelectionModel.selected_event_id).where(
                    ContentSlotSelectionModel.business_date == run.business_date,
                    ContentSlotSelectionModel.timezone == run.timezone,
                    ContentSlotSelectionModel.run_id != run.id,
                )
            )
        ).all()
    )
    legacy_ids = set(
        (
            await session.scalars(
                select(DailyTopicSelectionModel.selected_event_id).where(
                    DailyTopicSelectionModel.business_date == run.business_date,
                    DailyTopicSelectionModel.timezone == run.timezone,
                    DailyTopicSelectionModel.decision_kind == "selected",
                    DailyTopicSelectionModel.selected_event_id.is_not(None),
                )
            )
        ).all()
    )
    return frozenset(value for value in (*slot_ids, *legacy_ids) if value is not None)


def _validate_content_slot_decision(
    decision: ContentSlotDecision,
    *,
    item_limit: int,
) -> tuple[ContentSlotScore, ...]:
    if len(decision.scores) != len({score.base.event_id for score in decision.scores}):
        raise ValueError("content slot scores must have unique event IDs")
    if tuple(score.rank for score in decision.scores) != tuple(range(1, len(decision.scores) + 1)):
        raise ValueError("content slot scores require consecutive stable ranks")

    selected_scores = tuple(
        sorted(
            (score for score in decision.scores if score.selected_ordinal is not None),
            key=lambda score: cast(int, score.selected_ordinal),
        )
    )
    if len(selected_scores) > item_limit:
        raise ValueError("content slot decision exceeds its item limit")
    if tuple(score.selected_ordinal for score in selected_scores) != tuple(
        range(1, len(selected_scores) + 1)
    ):
        raise ValueError("content slot selection ordinals must be consecutive")
    if any(not score.base.eligible or score.same_day_excluded for score in selected_scores):
        raise ValueError("content slot selections must remain eligible and non-excluded")
    if decision.selected_event_ids != tuple(score.base.event_id for score in selected_scores):
        raise ValueError("content slot selected event IDs do not match ranked scores")
    if decision.selected_event_version_ids != tuple(
        score.base.event_version_id for score in selected_scores
    ):
        raise ValueError("content slot selected event versions do not match ranked scores")
    if decision.unfilled_count != item_limit - len(selected_scores):
        raise ValueError("content slot unfilled count does not match its item limit")
    return selected_scores


async def persist_content_slot_decision(
    session: AsyncSession,
    *,
    claimed: ClaimedContentSlotJob,
    config: TopicScoringConfig,
    policy: SlotRankingPolicy,
    decision: ContentSlotDecision,
) -> bool:
    now = datetime.now(UTC)
    job = await session.scalar(
        select(ContentSlotJobModel)
        .where(
            ContentSlotJobModel.id == claimed.job_id,
            ContentSlotJobModel.run_id == claimed.run_id,
            ContentSlotJobModel.lease_token == claimed.lease_token,
            ContentSlotJobModel.status == "running",
            ContentSlotJobModel.lease_expires_at >= now,
        )
        .with_for_update()
    )
    if job is None:
        await session.rollback()
        return False
    run = await session.scalar(
        select(ContentSlotRunModel)
        .where(ContentSlotRunModel.id == claimed.run_id)
        .with_for_update()
    )
    if run is None:
        raise RuntimeError("claimed content slot run is missing")
    await _lock_business_date(session, run.business_date, run.timezone)
    if (
        run.config_fingerprint != topic_scoring_config_fingerprint(config)
        or run.config_snapshot != config.as_metadata()
        or run.slot_policy_fingerprint != policy.fingerprint
        or run.slot_policy_snapshot != policy.as_metadata()
        or decision.slot.value != run.content_slot
        or decision.scoring_version != config.version
        or decision.scoring_profile != config.profile
        or decision.ranking_policy_version != policy.version
    ):
        raise ValueError("content slot decision does not match immutable run snapshots")
    selected_scores = _validate_content_slot_decision(decision, item_limit=run.item_limit)
    current_same_day = await get_same_day_selected_event_ids(session, run.id)
    overlap = current_same_day.intersection(decision.selected_event_ids)
    if overlap:
        await session.rollback()
        raise ConflictError("content slot decision contains a newly selected same-day event")
    if len(current_same_day) + len(selected_scores) > _MAX_DAILY_SLOT_SELECTIONS:
        await session.rollback()
        raise ConflictError("content slot decision exceeds the nine-item daily limit")

    score_ids: dict[UUID, UUID] = {}
    for score in decision.scores:
        score_id = uuid4()
        base = score.base
        inserted_id = await session.scalar(
            insert(ContentSlotScoreModel)
            .values(
                id=score_id,
                run_id=run.id,
                event_id=base.event_id,
                event_version_id=base.event_version_id,
                raw_features=dict(base.raw_features),
                normalized_features=dict(base.normalized_features),
                weights=dict(base.weights),
                penalty_weights=dict(base.penalty_weights),
                positive_components=dict(base.positive_components),
                penalty_components=dict(base.penalty_components),
                total=base.total,
                threshold=base.threshold,
                passes_threshold=base.passes_threshold,
                eligible=base.eligible,
                veto_codes=[code.value for code in base.veto_codes],
                explanation={
                    **base.as_metadata(),
                    "base_scoring_version": base.scoring_version,
                    "slot_policy_version": policy.version,
                    "slot_affinity": score.affinity,
                    "slot_affinity_reasons": list(score.affinity_reasons),
                    "same_day_excluded": score.same_day_excluded,
                    "same_day_exclusion_reason": score.same_day_exclusion_reason,
                    "final_ordering_key": score.final_ordering_key,
                },
                slot_affinity=score.affinity,
                slot_affinity_reasons=list(score.affinity_reasons),
                same_day_excluded=score.same_day_excluded,
                same_day_exclusion_reason=score.same_day_exclusion_reason,
                final_ordering_value=score.ordering_value,
                final_ordering_key=score.final_ordering_key,
                rank=score.rank,
                selected_ordinal=score.selected_ordinal,
            )
            .on_conflict_do_nothing(constraint="uq_content_slot_scores_run_event")
            .returning(ContentSlotScoreModel.id)
        )
        if inserted_id is None:
            existing_score = await session.scalar(
                select(ContentSlotScoreModel).where(
                    ContentSlotScoreModel.run_id == run.id,
                    ContentSlotScoreModel.event_id == base.event_id,
                )
            )
            if existing_score is None:
                raise RuntimeError("content slot score conflict could not be resolved")
            score_id = existing_score.id
        score_ids[base.event_id] = score_id

    for score in selected_scores:
        await session.execute(
            insert(ContentSlotSelectionModel)
            .values(
                id=uuid4(),
                run_id=run.id,
                score_id=score_ids[score.base.event_id],
                business_date=run.business_date,
                timezone=run.timezone,
                content_slot=run.content_slot,
                ordinal=score.selected_ordinal,
                selected_event_id=score.base.event_id,
                selected_event_version_id=score.base.event_version_id,
            )
            .on_conflict_do_nothing(constraint="uq_content_slot_selections_run_event")
        )
    run.status = "succeeded"
    run.total_scores = len(decision.scores)
    run.eligible_scores = sum(score.base.eligible for score in decision.scores)
    run.selected_count = len(selected_scores)
    run.unfilled_count = decision.unfilled_count
    run.unfilled_reason_codes = [code.value for code in decision.unfilled_reason_codes]
    run.error_code = None
    run.completed_at = now
    await session.commit()
    return True


async def complete_content_slot_job(
    session: AsyncSession, *, claimed: ClaimedContentSlotJob
) -> bool:
    now = datetime.now(UTC)
    result = cast(
        CursorResult[object],
        await session.execute(
            update(ContentSlotJobModel)
            .where(
                ContentSlotJobModel.id == claimed.job_id,
                ContentSlotJobModel.run_id == claimed.run_id,
                ContentSlotJobModel.lease_token == claimed.lease_token,
                ContentSlotJobModel.status == "running",
                ContentSlotJobModel.lease_expires_at >= now,
            )
            .values(
                status="succeeded",
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                heartbeat_at=now,
                error_code=None,
                completed_at=now,
            )
        ),
    )
    if not result.rowcount:
        await session.rollback()
        return False
    run = await session.get(ContentSlotRunModel, claimed.run_id)
    if run is None or run.status != "succeeded":
        await session.rollback()
        raise ConflictError("content slot decision must precede job completion")
    await session.commit()
    return True


async def fail_content_slot_job(
    session: AsyncSession,
    *,
    claimed: ClaimedContentSlotJob,
    error_code: str,
) -> bool:
    normalized = error_code.strip()
    if not _SAFE_ERROR_CODE.fullmatch(normalized):
        raise ValueError("content slot error code must be safe snake_case")
    now = datetime.now(UTC)
    result = cast(
        CursorResult[object],
        await session.execute(
            update(ContentSlotJobModel)
            .where(
                ContentSlotJobModel.id == claimed.job_id,
                ContentSlotJobModel.run_id == claimed.run_id,
                ContentSlotJobModel.lease_token == claimed.lease_token,
                ContentSlotJobModel.status == "running",
                ContentSlotJobModel.lease_expires_at >= now,
            )
            .values(
                status="failed",
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                heartbeat_at=now,
                error_code=normalized,
                completed_at=now,
            )
        ),
    )
    if not result.rowcount:
        await session.rollback()
        return False
    run = await session.get(ContentSlotRunModel, claimed.run_id)
    if run is not None and run.status != "succeeded":
        run.status = "failed"
        run.error_code = normalized
        run.completed_at = now
    await session.commit()
    return True


async def get_content_slot_run(session: AsyncSession, run_id: UUID) -> ContentSlotRunModel:
    run = await session.get(ContentSlotRunModel, run_id)
    if run is None:
        raise NotFoundError("content slot run")
    return run


async def list_content_slot_scores(
    session: AsyncSession, run_id: UUID
) -> tuple[ContentSlotScoreProjection, ...]:
    if await session.get(ContentSlotRunModel, run_id) is None:
        raise NotFoundError("content slot run")
    rows = tuple(
        (
            await session.execute(
                select(ContentSlotScoreModel, EventClusterVersionModel)
                .join(
                    EventClusterVersionModel,
                    EventClusterVersionModel.id == ContentSlotScoreModel.event_version_id,
                )
                .where(ContentSlotScoreModel.run_id == run_id)
                .order_by(ContentSlotScoreModel.rank)
            )
        ).tuples()
    )
    return tuple(
        ContentSlotScoreProjection(
            score=score,
            event_title=version.representative_title,
            event_time=version.event_time_start or version.event_time_end,
        )
        for score, version in rows
    )


async def list_content_slot_runs_for_date(
    session: AsyncSession,
    *,
    business_date: date,
    timezone: str,
    scoring_profile: str,
) -> tuple[ContentSlotRunProjection, ...]:
    runs = tuple(
        (
            await session.scalars(
                select(ContentSlotRunModel)
                .where(
                    ContentSlotRunModel.business_date == business_date,
                    ContentSlotRunModel.timezone == timezone,
                    ContentSlotRunModel.scoring_profile == scoring_profile,
                )
                .order_by(ContentSlotRunModel.target_at)
            )
        ).all()
    )
    if not runs:
        return ()
    rows = tuple(
        (
            await session.execute(
                select(ContentSlotSelectionModel, EventClusterVersionModel)
                .join(
                    EventClusterVersionModel,
                    EventClusterVersionModel.id
                    == ContentSlotSelectionModel.selected_event_version_id,
                )
                .where(ContentSlotSelectionModel.run_id.in_(tuple(run.id for run in runs)))
                .order_by(ContentSlotSelectionModel.run_id, ContentSlotSelectionModel.ordinal)
            )
        ).tuples()
    )
    selections_by_run: dict[UUID, list[ContentSlotSelectionProjection]] = {
        run.id: [] for run in runs
    }
    for selection, version in rows:
        selections_by_run[selection.run_id].append(
            ContentSlotSelectionProjection(
                selection=selection,
                title=version.representative_title,
                event_time=version.event_time_start or version.event_time_end,
            )
        )
    return tuple(
        ContentSlotRunProjection(run=run, selections=tuple(selections_by_run[run.id]))
        for run in runs
    )


class PostgresContentSlotRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ready_lineage(
        self,
        *,
        business_date: date,
        timezone: str,
        slot: ContentSlot,
        now: datetime,
    ) -> GovernedSlotLineage | None:
        async with self._session_factory() as session:
            return await get_ready_slot_lineage(
                session,
                business_date=business_date,
                timezone=timezone,
                slot=slot,
                now=now,
            )

    async def enqueue(
        self,
        *,
        business_date: date,
        timezone: str,
        schedule: ContentSlotSchedule,
        config: TopicScoringConfig,
        policy: SlotRankingPolicy,
        lineage: GovernedSlotLineage,
        trigger: str,
    ) -> UUID:
        async with self._session_factory() as session:
            run, _ = await enqueue_content_slot_run(
                session,
                business_date=business_date,
                timezone=timezone,
                schedule=schedule,
                config=config,
                policy=policy,
                lineage=lineage,
                trigger=trigger,
            )
            return run.id

    async def claim(
        self, *, worker_id: str, lease_seconds: int, max_attempts: int
    ) -> ClaimedContentSlotJob | None:
        async with self._session_factory() as session:
            return await claim_content_slot_job(
                session,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
            )

    async def heartbeat(self, *, claimed: ClaimedContentSlotJob, lease_seconds: int) -> bool:
        async with self._session_factory() as session:
            return await heartbeat_content_slot_job(
                session, claimed=claimed, lease_seconds=lease_seconds
            )

    async def load_config(self, run_id: UUID) -> TopicScoringConfig:
        async with self._session_factory() as session:
            return await load_content_slot_config(session, run_id)

    async def load_policy(self, run_id: UUID) -> SlotRankingPolicy:
        async with self._session_factory() as session:
            return await load_content_slot_policy(session, run_id)

    async def load_candidates(self, run_id: UUID) -> tuple[TopicCandidate, ...]:
        async with self._session_factory() as session:
            return await load_content_slot_candidates(session, run_id)

    async def same_day_selected_event_ids(self, run_id: UUID) -> frozenset[UUID]:
        async with self._session_factory() as session:
            return await get_same_day_selected_event_ids(session, run_id)

    async def persist_decision(
        self,
        *,
        claimed: ClaimedContentSlotJob,
        config: TopicScoringConfig,
        policy: SlotRankingPolicy,
        decision: ContentSlotDecision,
    ) -> bool:
        async with self._session_factory() as session:
            return await persist_content_slot_decision(
                session,
                claimed=claimed,
                config=config,
                policy=policy,
                decision=decision,
            )

    async def complete(self, *, claimed: ClaimedContentSlotJob) -> bool:
        async with self._session_factory() as session:
            return await complete_content_slot_job(session, claimed=claimed)

    async def fail(self, *, claimed: ClaimedContentSlotJob, error_code: str) -> bool:
        async with self._session_factory() as session:
            return await fail_content_slot_job(session, claimed=claimed, error_code=error_code)
