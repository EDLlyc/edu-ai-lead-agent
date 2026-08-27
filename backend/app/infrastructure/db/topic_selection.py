from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import and_, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.topic_selection import ClaimedTopicSelectionJob
from app.application.services.topic_reranking import topic_rerank_outcome_metadata
from app.core.errors import ConflictError, NotFoundError
from app.domain.editorial_relevance import (
    SCIENCE_TECH_EDITORIAL_V2_RULE_VERSION,
    evaluate_product_matrix_fit,
    evaluate_product_matrix_fit_v2,
    evaluate_science_ai_education_relevance,
    evaluate_science_tech_editorial_relevance,
)
from app.domain.topic_rerank import (
    TopicRerankConfig,
    TopicRerankOutcome,
    skipped_topic_rerank_outcome,
)
from app.domain.topic_selection import (
    DELIVERED_CONTENT_VETO_RULE_VERSION,
    GOV_CN_YAOWEN_PRIORITY_POLICY,
    MOE_SCIENCE_TOP1_PRIORITY_POLICY,
    DailyTopicDecision,
    TopicCandidate,
    TopicScoringConfig,
)
from app.infrastructure.db.models import (
    AcquisitionRunModel,
    ArticleOccurrenceModel,
    ContentSlotRunModel,
    ContentSlotSelectionModel,
    CopyGenerationRunModel,
    DailyTopicSelectionModel,
    EventAssignmentDecisionModel,
    EventClusterModel,
    EventClusterVersionModel,
    EventMembershipModel,
    EvidenceBindingModel,
    EvidenceCandidateModel,
    GovernanceJobModel,
    GovernanceRunModel,
    MaterialPackageModel,
    NormalizedArticleModel,
    SourceVersionModel,
    TopicRerankRecordModel,
    TopicScoreModel,
    TopicScoringConfigModel,
    TopicSelectionJobModel,
    TopicSelectionRunModel,
    WeComDeliveryJobModel,
)

_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_PARENT_RELEVANCE = {
    "ai_education_policy": 1.0,
    "youth_science_education": 1.0,
    "robotics_embodied_intelligence": 0.78,
    "large_generative_models": 0.72,
    "ai_governance_safety": 0.68,
    "ai_industry_application": 0.58,
    "ai_compute_chips": 0.45,
}
_CONTROVERSY_TERMS = ("争议", "质疑", "风险", "安全事故", "失控", "替代教师", "裁员")
_UNVERIFIED_TERMS = ("网传", "传言", "未经证实", "据说", "疑似")
_NEGATIVE_INCIDENT_TERMS = ("伤亡", "诈骗", "自杀", "暴力", "事故", "犯罪", "失踪")
_PRIVACY_SAFETY_TERMS = ("隐私泄露", "个人信息泄露", "未成年人数据", "人脸泄露")
_PROHIBITED_MARKETING_TERMS = ("保过", "包会", "稳赚", "零风险", "百分百提升")
_SOURCE_TRUST_WEIGHTS = {"A": 1.0, "B": 0.75, "C": 0.0}
_EDITORIAL_CATEGORY_TEXT = {
    "ai_education_policy": "人工智能教育 政策 课程 教师 学生",
    "youth_science_education": "青少年 科学教育 科学探究",
    "robotics_embodied_intelligence": "机器人 具身智能",
    "large_generative_models": "大模型 生成式人工智能",
    "ai_governance_safety": "人工智能 安全 治理",
    "ai_industry_application": "人工智能 产业应用",
    "ai_compute_chips": "人工智能 算力 芯片",
}
_TERMINAL_ACQUISITION_STATUSES = ("succeeded", "partially_succeeded")
_TERMINAL_GOVERNANCE_RUN_STATUSES = ("succeeded", "partially_succeeded")
_NON_TERMINAL_GOVERNANCE_JOB_STATUSES = ("queued", "running", "retry_scheduled")


@dataclass(frozen=True, slots=True)
class TopicScoreProjection:
    score: TopicScoreModel
    event_title: str
    event_time: datetime | None


@dataclass(frozen=True, slots=True)
class DailyTopicResultProjection:
    selection: DailyTopicSelectionModel
    run: TopicSelectionRunModel
    config: TopicScoringConfigModel
    selected_title: str | None
    selected_event_time: datetime | None


def topic_scoring_config_fingerprint(config: TopicScoringConfig) -> str:
    payload = json.dumps(
        config.as_metadata(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def source_trust_projection(tiers_by_source: dict[UUID, set[str]]) -> tuple[float, bool, bool]:
    """Return average trust, Tier-C-only state, and eligible-evidence availability.

    Unknown persisted tier values are deliberately worth zero and cannot make evidence eligible.
    The current acquisition schema accepts only A/B, while this defensive projection preserves the
    downstream Tier-C boundary if discovery-only sources are introduced later.
    """
    if not tiers_by_source:
        return 0.0, False, False
    all_tiers = {tier for tiers in tiers_by_source.values() for tier in tiers}
    eligible_evidence = any(tier in {"A", "B"} for tier in all_tiers)
    tier_c_only = bool(all_tiers) and all(tier == "C" for tier in all_tiers)
    per_source_trust = [
        max((_SOURCE_TRUST_WEIGHTS.get(tier, 0.0) for tier in tiers), default=0.0)
        for tiers in tiers_by_source.values()
    ]
    return sum(per_source_trust) / len(per_source_trust), tier_c_only, eligible_evidence


async def ensure_topic_scoring_config(
    session: AsyncSession,
    config: TopicScoringConfig,
) -> TopicScoringConfigModel:
    snapshot = config.as_metadata()
    fingerprint = topic_scoring_config_fingerprint(config)
    config_id = uuid4()
    inserted_config_id = await session.scalar(
        insert(TopicScoringConfigModel)
        .values(
            id=config_id,
            version=config.version,
            profile=config.profile,
            fingerprint=fingerprint,
            config_snapshot=snapshot,
        )
        .on_conflict_do_nothing(constraint="uq_topic_scoring_configs_profile_version")
        .returning(TopicScoringConfigModel.id)
    )
    if inserted_config_id is None:
        stored_config = await session.scalar(
            select(TopicScoringConfigModel).where(
                TopicScoringConfigModel.profile == config.profile,
                TopicScoringConfigModel.version == config.version,
            )
        )
        if stored_config is None:
            raise RuntimeError("topic scoring config conflict could not be resolved")
        if stored_config.fingerprint != fingerprint or stored_config.config_snapshot != snapshot:
            await session.rollback()
            raise ConflictError("topic scoring config version is immutable")
        return stored_config
    stored_config = await session.get(TopicScoringConfigModel, config_id)
    if stored_config is None:
        raise RuntimeError("created topic scoring config could not be loaded")
    return stored_config


async def enqueue_topic_selection_run(
    session: AsyncSession,
    *,
    business_date: date,
    timezone: str,
    config: TopicScoringConfig,
    governed_event_cutoff: datetime,
    trigger: str = "manual",
    rerank_config: TopicRerankConfig | None = None,
) -> tuple[TopicSelectionRunModel, bool]:
    if governed_event_cutoff.tzinfo is None:
        raise ValueError("governed event cutoff must be timezone-aware")
    if not timezone.strip() or len(timezone) > 80:
        raise ValueError("topic selection timezone must be non-blank and bounded")
    if trigger not in {"manual", "scheduled"}:
        raise ValueError("topic selection trigger must be manual or scheduled")
    stored_config = await ensure_topic_scoring_config(session, config)
    snapshot = config.as_metadata()
    fingerprint = stored_config.fingerprint
    config_id = stored_config.id
    resolved_rerank_config = rerank_config or TopicRerankConfig()
    rerank_snapshot = resolved_rerank_config.as_metadata()
    rerank_fingerprint = resolved_rerank_config.fingerprint

    current = await session.scalar(
        select(TopicSelectionRunModel)
        .where(
            TopicSelectionRunModel.business_date == business_date,
            TopicSelectionRunModel.timezone == timezone.strip(),
            TopicSelectionRunModel.scoring_profile == config.profile,
            TopicSelectionRunModel.superseded_at.is_(None),
        )
        .order_by(TopicSelectionRunModel.revision.desc())
        .with_for_update()
    )
    if current is not None:
        can_recover = (
            current.status == "succeeded"
            and current.selected_event_id is None
            and current.no_topic_code in {"no_candidates", "all_vetoed"}
            and governed_event_cutoff > current.governed_event_cutoff
        )
        if not can_recover:
            if (
                current.config_fingerprint != fingerprint
                or current.config_snapshot != snapshot
                or current.rerank_config_fingerprint != rerank_fingerprint
                or current.rerank_config_snapshot != rerank_snapshot
            ):
                await session.rollback()
                raise ConflictError(
                    "a different scoring config already owns this date and scoring profile"
                )
            await session.commit()
            return current, False

    revision = current.revision + 1 if current is not None else 1
    run_id = uuid4()
    inserted_run_id = await session.scalar(
        insert(TopicSelectionRunModel)
        .values(
            id=run_id,
            trigger=trigger,
            business_date=business_date,
            timezone=timezone.strip(),
            scoring_profile=config.profile,
            revision=revision,
            config_id=config_id,
            config_fingerprint=fingerprint,
            config_snapshot=snapshot,
            rerank_config_fingerprint=rerank_fingerprint,
            rerank_config_snapshot=rerank_snapshot,
            governed_event_cutoff=governed_event_cutoff,
            status="queued",
        )
        .on_conflict_do_nothing(constraint="uq_topic_selection_runs_business_revision")
        .returning(TopicSelectionRunModel.id)
    )
    if inserted_run_id is None:
        existing = await session.scalar(
            select(TopicSelectionRunModel)
            .where(
                TopicSelectionRunModel.business_date == business_date,
                TopicSelectionRunModel.timezone == timezone.strip(),
                TopicSelectionRunModel.scoring_profile == config.profile,
            )
            .order_by(TopicSelectionRunModel.revision.desc())
        )
        if existing is None:
            raise RuntimeError("topic selection run conflict could not be resolved")
        if (
            existing.config_fingerprint != fingerprint
            or existing.config_snapshot != snapshot
            or existing.rerank_config_fingerprint != rerank_fingerprint
            or existing.rerank_config_snapshot != rerank_snapshot
        ):
            await session.rollback()
            raise ConflictError(
                "a different scoring config already owns this date and scoring profile"
            )
        await session.commit()
        return existing, False

    if current is not None:
        now = datetime.now(UTC)
        current.superseded_at = now
        current.superseded_by_run_id = run_id
        old_selection = await session.scalar(
            select(DailyTopicSelectionModel).where(
                DailyTopicSelectionModel.run_id == current.id,
                DailyTopicSelectionModel.superseded_at.is_(None),
            )
        )
        if old_selection is not None:
            old_selection.superseded_at = now
            old_selection.superseded_by_run_id = run_id

    session.add(
        TopicSelectionJobModel(
            id=uuid4(),
            run_id=run_id,
            status="queued",
        )
    )
    await session.commit()
    run = await session.get(TopicSelectionRunModel, run_id)
    if run is None:
        raise RuntimeError("created topic selection run could not be loaded")
    return run, True


async def claim_topic_selection_job(
    session: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: int,
    max_attempts: int,
    run_id: UUID | None = None,
) -> ClaimedTopicSelectionJob | None:
    normalized_worker_id = worker_id.strip()
    if not normalized_worker_id or len(normalized_worker_id) > 200:
        raise ValueError("topic selection worker id must be non-blank and bounded")
    if lease_seconds < 1:
        raise ValueError("topic selection lease must be positive")
    if max_attempts < 1:
        raise ValueError("topic selection max attempts must be positive")
    now = datetime.now(UTC)
    exhausted_statement = (
        select(TopicSelectionJobModel)
        .where(
            TopicSelectionJobModel.status == "running",
            TopicSelectionJobModel.lease_expires_at < now,
            TopicSelectionJobModel.attempt_count >= max_attempts,
        )
        .order_by(TopicSelectionJobModel.available_at, TopicSelectionJobModel.created_at)
        .with_for_update(skip_locked=True)
        .limit(100)
    )
    if run_id is not None:
        exhausted_statement = exhausted_statement.where(TopicSelectionJobModel.run_id == run_id)
    exhausted_jobs = tuple((await session.scalars(exhausted_statement)).all())
    for exhausted_job in exhausted_jobs:
        exhausted_run = await session.get(TopicSelectionRunModel, exhausted_job.run_id)
        decision_persisted = exhausted_run is not None and exhausted_run.status == "succeeded"
        exhausted_job.status = "succeeded" if decision_persisted else "failed"
        exhausted_job.lease_owner = None
        exhausted_job.lease_token = None
        exhausted_job.lease_expires_at = None
        exhausted_job.heartbeat_at = now
        exhausted_job.error_code = None if decision_persisted else "max_attempts_exhausted"
        exhausted_job.completed_at = now
        if exhausted_run is not None and not decision_persisted:
            exhausted_run.status = "failed"
            exhausted_run.completed_at = now
    statement = (
        select(TopicSelectionJobModel)
        .where(
            TopicSelectionJobModel.available_at <= now,
            or_(
                TopicSelectionJobModel.status == "queued",
                and_(
                    TopicSelectionJobModel.status == "running",
                    TopicSelectionJobModel.lease_expires_at < now,
                    TopicSelectionJobModel.attempt_count < max_attempts,
                ),
            ),
        )
        .order_by(TopicSelectionJobModel.available_at, TopicSelectionJobModel.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if run_id is not None:
        statement = statement.where(TopicSelectionJobModel.run_id == run_id)
    job = await session.scalar(statement)
    if job is None:
        if exhausted_jobs:
            await session.commit()
        else:
            await session.rollback()
        return None
    run = await session.get(TopicSelectionRunModel, job.run_id)
    if run is None:
        raise RuntimeError("topic selection job has no run")
    lease_token = uuid4()
    job.status = "running"
    job.attempt_count += 1
    job.lease_owner = normalized_worker_id
    job.lease_token = lease_token
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.heartbeat_at = now
    job.started_at = job.started_at or now
    job.completed_at = None
    job.error_code = None
    run.status = "running"
    run.started_at = run.started_at or now
    await session.commit()
    return ClaimedTopicSelectionJob(
        job_id=job.id,
        run_id=run.id,
        attempt_number=job.attempt_count,
        lease_token=lease_token,
        business_date=run.business_date,
        timezone=run.timezone,
        cutoff_at=run.governed_event_cutoff,
    )


async def heartbeat_topic_selection_job(
    session: AsyncSession,
    *,
    claimed: ClaimedTopicSelectionJob,
    lease_seconds: int,
) -> bool:
    if lease_seconds < 1:
        raise ValueError("topic selection lease must be positive")
    now = datetime.now(UTC)
    result = cast(
        CursorResult[object],
        await session.execute(
            update(TopicSelectionJobModel)
            .where(
                TopicSelectionJobModel.id == claimed.job_id,
                TopicSelectionJobModel.run_id == claimed.run_id,
                TopicSelectionJobModel.lease_token == claimed.lease_token,
                TopicSelectionJobModel.status == "running",
                TopicSelectionJobModel.lease_expires_at >= now,
            )
            .values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=lease_seconds))
        ),
    )
    if not result.rowcount:
        await session.rollback()
        return False
    await session.commit()
    return True


async def load_topic_candidates(
    session: AsyncSession,
    run_id: UUID,
) -> tuple[TopicCandidate, ...]:
    run = await session.get(TopicSelectionRunModel, run_id)
    if run is None:
        raise NotFoundError("topic selection run")
    return await load_governed_topic_candidates(
        session,
        business_date=run.business_date,
        timezone=run.timezone,
        scoring_profile=run.scoring_profile,
        governed_event_cutoff=run.governed_event_cutoff,
        config_snapshot=run.config_snapshot,
    )


async def load_governed_topic_candidates(
    session: AsyncSession,
    *,
    business_date: date,
    timezone: str,
    scoring_profile: str,
    governed_event_cutoff: datetime,
    config_snapshot: dict[str, object],
    include_content_slot_history: bool = False,
) -> tuple[TopicCandidate, ...]:
    """Project immutable governed candidates without reinterpreting legacy history.

    Legacy daily runs intentionally keep their historical daily-only repetition projection.
    Content-slot runs additionally merge prior slot selections. The delivered-history veto rule
    changes only the hard-repeat date projection; selected versions continue to own the theme
    repetition projection for every policy.
    """

    recent_days_value = config_snapshot.get("recent_selection_window_days", 7)
    recent_days = int(recent_days_value) if isinstance(recent_days_value, int) else 7
    history_start = business_date - timedelta(days=max(recent_days, 30))
    uses_delivered_repeat_history = (
        config_snapshot.get("veto_rule_version") == DELIVERED_CONTENT_VETO_RULE_VERSION
    )
    scoring_config = TopicScoringConfig.from_metadata(config_snapshot)
    science_tech_editorial_rule_version = (
        scoring_config.effective_science_tech_editorial_rule_version
        or SCIENCE_TECH_EDITORIAL_V2_RULE_VERSION
    )

    latest_version_id = (
        select(EventClusterVersionModel.id)
        .where(
            EventClusterVersionModel.event_id == EventClusterModel.id,
            EventClusterVersionModel.created_at <= governed_event_cutoff,
        )
        .order_by(EventClusterVersionModel.version.desc(), EventClusterVersionModel.id.desc())
        .limit(1)
        .correlate(EventClusterModel)
        .scalar_subquery()
    )
    version_rows = tuple(
        (
            await session.execute(
                select(
                    EventClusterVersionModel,
                    EvidenceCandidateModel.published_at,
                    EvidenceCandidateModel.first_fetched_at,
                )
                .select_from(EventClusterModel)
                .join(EventClusterVersionModel, EventClusterVersionModel.id == latest_version_id)
                .join(
                    NormalizedArticleModel,
                    NormalizedArticleModel.id == EventClusterVersionModel.representative_article_id,
                )
                .join(
                    EvidenceCandidateModel,
                    EvidenceCandidateModel.id == NormalizedArticleModel.candidate_id,
                )
                .where(EventClusterModel.status == "active")
                .order_by(EventClusterModel.id)
                .limit(500)
            )
        ).tuples()
    )
    if not version_rows:
        return ()
    versions = {version.event_id: version for version, _, _ in version_rows}
    event_ids = tuple(versions)
    event_version_ids = tuple(version.id for version in versions.values())

    source_priority_policy = getattr(SourceVersionModel, "topic_priority_policy", None)
    priority_policy_column = (
        source_priority_policy if source_priority_policy is not None else literal(None)
    ).label("topic_priority_policy")
    occurrence_rows = tuple(
        (
            await session.execute(
                select(
                    EventMembershipModel.event_id,
                    ArticleOccurrenceModel.source_id,
                    ArticleOccurrenceModel.trust_tier,
                    priority_policy_column,
                )
                .join(
                    EventClusterVersionModel,
                    and_(
                        EventClusterVersionModel.event_id == EventMembershipModel.event_id,
                        EventClusterVersionModel.id.in_(event_version_ids),
                    ),
                )
                .join(
                    NormalizedArticleModel,
                    NormalizedArticleModel.id == EventMembershipModel.normalized_article_id,
                )
                .join(
                    ArticleOccurrenceModel,
                    ArticleOccurrenceModel.candidate_id == NormalizedArticleModel.candidate_id,
                )
                .join(
                    SourceVersionModel,
                    SourceVersionModel.id == ArticleOccurrenceModel.source_version_id,
                )
                .where(
                    EventMembershipModel.event_id.in_(event_ids),
                    EventMembershipModel.created_at <= EventClusterVersionModel.created_at,
                    or_(
                        EventMembershipModel.active.is_(True),
                        EventMembershipModel.superseded_at > EventClusterVersionModel.created_at,
                    ),
                    ArticleOccurrenceModel.created_at <= EventClusterVersionModel.created_at,
                )
                .distinct()
            )
        ).tuples()
    )
    trust_by_event: dict[UUID, dict[UUID, set[str]]] = {event_id: {} for event_id in event_ids}
    priority_policies_by_event: dict[UUID, set[str]] = {event_id: set() for event_id in event_ids}
    for event_id, source_id, trust_tier, topic_priority_policy in occurrence_rows:
        trust_by_event[event_id].setdefault(source_id, set()).add(trust_tier)
        if isinstance(topic_priority_policy, str) and topic_priority_policy.strip():
            priority_policies_by_event[event_id].add(topic_priority_policy.strip())

    analysis_ids: dict[UUID, UUID] = {}
    for event_id, version in versions.items():
        raw_analysis_id = version.summary_projection.get("analysis_id")
        if isinstance(raw_analysis_id, str):
            try:
                analysis_ids[event_id] = UUID(raw_analysis_id)
            except ValueError:
                continue
    bound_analysis_ids = set(
        (
            await session.scalars(
                select(EvidenceBindingModel.analysis_id)
                .where(
                    EvidenceBindingModel.analysis_id.in_(tuple(analysis_ids.values())),
                    EvidenceBindingModel.validated.is_(True),
                )
                .distinct()
            )
        ).all()
    )
    unresolved_events = set(
        (
            await session.scalars(
                select(EventAssignmentDecisionModel.selected_event_id)
                .where(
                    EventAssignmentDecisionModel.selected_event_id.in_(event_ids),
                    EventAssignmentDecisionModel.outcome == "review_required",
                    EventAssignmentDecisionModel.created_at <= governed_event_cutoff,
                )
                .distinct()
            )
        ).all()
    )
    daily_prior_rows = tuple(
        (
            await session.execute(
                select(
                    DailyTopicSelectionModel.selected_event_id,
                    DailyTopicSelectionModel.selected_event_version_id,
                    DailyTopicSelectionModel.business_date,
                ).where(
                    DailyTopicSelectionModel.decision_kind == "selected",
                    DailyTopicSelectionModel.business_date < business_date,
                    DailyTopicSelectionModel.business_date >= history_start,
                    DailyTopicSelectionModel.timezone == timezone,
                    DailyTopicSelectionModel.scoring_profile == scoring_profile,
                )
            )
        ).tuples()
    )
    slot_prior_rows: tuple[tuple[UUID, UUID, date], ...] = ()
    if include_content_slot_history:
        slot_prior_rows = tuple(
            (
                await session.execute(
                    select(
                        ContentSlotSelectionModel.selected_event_id,
                        ContentSlotSelectionModel.selected_event_version_id,
                        ContentSlotSelectionModel.business_date,
                    )
                    .join(
                        ContentSlotRunModel,
                        ContentSlotRunModel.id == ContentSlotSelectionModel.run_id,
                    )
                    .where(
                        ContentSlotSelectionModel.business_date < business_date,
                        ContentSlotSelectionModel.business_date >= history_start,
                        ContentSlotSelectionModel.timezone == timezone,
                        ContentSlotRunModel.scoring_profile == scoring_profile,
                    )
                )
            ).tuples()
        )
    prior_version_ids: list[UUID] = []
    for _selected_event_id, selected_version_id, _selected_business_date in (
        *daily_prior_rows,
        *slot_prior_rows,
    ):
        if selected_version_id is not None:
            prior_version_ids.append(selected_version_id)

    repeat_history_rows = (*daily_prior_rows, *slot_prior_rows)
    if uses_delivered_repeat_history:
        daily_delivered_rows = tuple(
            (
                await session.execute(
                    select(
                        DailyTopicSelectionModel.selected_event_id,
                        DailyTopicSelectionModel.selected_event_version_id,
                        DailyTopicSelectionModel.business_date,
                    )
                    .select_from(DailyTopicSelectionModel)
                    .join(
                        CopyGenerationRunModel,
                        and_(
                            CopyGenerationRunModel.daily_topic_selection_id
                            == DailyTopicSelectionModel.id,
                            CopyGenerationRunModel.topic_selection_run_id
                            == DailyTopicSelectionModel.run_id,
                            CopyGenerationRunModel.business_date
                            == DailyTopicSelectionModel.business_date,
                            CopyGenerationRunModel.timezone == DailyTopicSelectionModel.timezone,
                            CopyGenerationRunModel.scoring_profile
                            == DailyTopicSelectionModel.scoring_profile,
                            CopyGenerationRunModel.decision_kind == "selected",
                            CopyGenerationRunModel.selected_event_id
                            == DailyTopicSelectionModel.selected_event_id,
                            CopyGenerationRunModel.selected_event_version_id
                            == DailyTopicSelectionModel.selected_event_version_id,
                        ),
                    )
                    .join(
                        MaterialPackageModel,
                        MaterialPackageModel.run_id == CopyGenerationRunModel.id,
                    )
                    .join(
                        WeComDeliveryJobModel,
                        WeComDeliveryJobModel.material_package_id == MaterialPackageModel.id,
                    )
                    .where(
                        DailyTopicSelectionModel.decision_kind == "selected",
                        DailyTopicSelectionModel.business_date < business_date,
                        DailyTopicSelectionModel.business_date >= history_start,
                        DailyTopicSelectionModel.timezone == timezone,
                        DailyTopicSelectionModel.scoring_profile == scoring_profile,
                        WeComDeliveryJobModel.content_slot_selection_id.is_(None),
                        WeComDeliveryJobModel.mode == "formal",
                        WeComDeliveryJobModel.status == "delivered",
                    )
                    .distinct()
                )
            ).tuples()
        )
        slot_delivered_rows: tuple[tuple[UUID, UUID, date], ...] = ()
        if include_content_slot_history:
            slot_delivered_rows = tuple(
                (
                    await session.execute(
                        select(
                            ContentSlotSelectionModel.selected_event_id,
                            ContentSlotSelectionModel.selected_event_version_id,
                            ContentSlotSelectionModel.business_date,
                        )
                        .select_from(ContentSlotSelectionModel)
                        .join(
                            ContentSlotRunModel,
                            ContentSlotRunModel.id == ContentSlotSelectionModel.run_id,
                        )
                        .join(
                            CopyGenerationRunModel,
                            and_(
                                CopyGenerationRunModel.content_slot_selection_id
                                == ContentSlotSelectionModel.id,
                                CopyGenerationRunModel.business_date
                                == ContentSlotSelectionModel.business_date,
                                CopyGenerationRunModel.timezone
                                == ContentSlotSelectionModel.timezone,
                                CopyGenerationRunModel.scoring_profile
                                == ContentSlotRunModel.scoring_profile,
                                CopyGenerationRunModel.decision_kind == "selected",
                                CopyGenerationRunModel.selected_event_id
                                == ContentSlotSelectionModel.selected_event_id,
                                CopyGenerationRunModel.selected_event_version_id
                                == ContentSlotSelectionModel.selected_event_version_id,
                            ),
                        )
                        .join(
                            MaterialPackageModel,
                            MaterialPackageModel.run_id == CopyGenerationRunModel.id,
                        )
                        .join(
                            WeComDeliveryJobModel,
                            WeComDeliveryJobModel.material_package_id == MaterialPackageModel.id,
                        )
                        .where(
                            ContentSlotSelectionModel.business_date < business_date,
                            ContentSlotSelectionModel.business_date >= history_start,
                            ContentSlotSelectionModel.timezone == timezone,
                            ContentSlotRunModel.scoring_profile == scoring_profile,
                            WeComDeliveryJobModel.content_slot_selection_id
                            == ContentSlotSelectionModel.id,
                            WeComDeliveryJobModel.mode == "formal",
                            WeComDeliveryJobModel.status == "delivered",
                        )
                        .distinct()
                    )
                ).tuples()
            )
        repeat_history_rows = (*daily_delivered_rows, *slot_delivered_rows)

    last_selected: dict[UUID, date] = {}
    for selected_event_id, _selected_version_id, selected_business_date in repeat_history_rows:
        if selected_event_id is not None:
            previous = last_selected.get(selected_event_id)
            if previous is None or selected_business_date > previous:
                last_selected[selected_event_id] = selected_business_date
    prior_categories = tuple(
        (
            await session.scalars(
                select(EventClusterVersionModel.category_projection).where(
                    EventClusterVersionModel.id.in_(prior_version_ids)
                )
            )
        ).all()
    )

    candidates: list[TopicCandidate] = []
    for version, published_at, first_fetched_at in version_rows:
        event_time = (
            version.event_time_start or version.event_time_end or published_at or first_fetched_at
        )
        tiers = trust_by_event[version.event_id]
        source_trust, tier_c_only, has_eligible_source_tier = source_trust_projection(tiers)
        priority_policies = priority_policies_by_event[version.event_id]
        topic_priority_policy = (
            GOV_CN_YAOWEN_PRIORITY_POLICY
            if (
                scoring_config.has_qualified_authoritative_priority
                and GOV_CN_YAOWEN_PRIORITY_POLICY in priority_policies
            )
            else MOE_SCIENCE_TOP1_PRIORITY_POLICY
            if MOE_SCIENCE_TOP1_PRIORITY_POLICY in priority_policies
            else min(priority_policies)
            if priority_policies
            else None
        )
        categories = tuple(
            category for category in version.category_projection if isinstance(category, str)
        )
        parent_relevance = max(
            (_PARENT_RELEVANCE.get(value, 0.4) for value in categories), default=0.0
        )
        facts_value = version.summary_projection.get("facts", [])
        fact_count = len(facts_value) if isinstance(facts_value, list) else 0
        communication_potential = min(
            1.0,
            0.35
            + min(version.source_diversity, 4) * 0.12
            + min(fact_count, 4) * 0.06
            + min(len(version.entity_projection), 5) * 0.03,
        )
        category_set = set(categories)
        theme_repetition = 0.0
        if category_set:
            for previous_categories in prior_categories:
                if not isinstance(previous_categories, list):
                    continue
                previous_set = {value for value in previous_categories if isinstance(value, str)}
                union = category_set | previous_set
                if union:
                    theme_repetition = max(
                        theme_repetition, len(category_set & previous_set) / len(union)
                    )
        summary_value = version.summary_projection.get("summary")
        summary = summary_value if isinstance(summary_value, str) else ""
        governed_facts = " ".join(fact for fact in facts_value if isinstance(fact, str))
        searchable_text = f"{version.representative_title}\n{summary}"
        category_editorial_text = " ".join(
            _EDITORIAL_CATEGORY_TEXT.get(category, category) for category in categories
        )
        editorial_body = f"{summary}\n{governed_facts}\n{category_editorial_text}"
        science_education = evaluate_science_ai_education_relevance(
            version.representative_title,
            editorial_body,
        )
        product_fit = evaluate_product_matrix_fit(
            version.representative_title,
            editorial_body,
        )
        science_tech_editorial = evaluate_science_tech_editorial_relevance(
            version.representative_title,
            editorial_body,
            rule_version=science_tech_editorial_rule_version,
        )
        product_fit_v2 = evaluate_product_matrix_fit_v2(
            version.representative_title,
            editorial_body,
        )
        controversy_hits = sum(term in searchable_text for term in _CONTROVERSY_TERMS)
        marketing_hits = sum(term in searchable_text for term in _PROHIBITED_MARKETING_TERMS)
        analysis_id = analysis_ids.get(version.event_id)
        candidates.append(
            TopicCandidate(
                event_id=version.event_id,
                event_version_id=version.id,
                event_time=event_time,
                source_trust=source_trust,
                source_diversity=version.source_diversity,
                ai_relevance=1.0 if categories else 0.0,
                parent_relevance=parent_relevance,
                communication_potential=communication_potential,
                science_education_relevance=science_education.score,
                science_ai_education_eligible=science_education.is_eligible,
                science_ai_education_reason_codes=science_education.reason_codes,
                product_matrix_fit=product_fit.score,
                product_matrix_direction_ids=product_fit.direction_ids,
                editorial_priority=science_tech_editorial.editorial_priority_score,
                science_tech_editorial_cohort=science_tech_editorial.cohort,
                science_tech_education_relevance=(science_tech_editorial.education_relevance_score),
                frontier_significance=science_tech_editorial.frontier_significance_score,
                science_tech_editorial_reason_codes=science_tech_editorial.reason_codes,
                science_tech_content_signals=science_tech_editorial.content_signals,
                product_matrix_fit_v2=product_fit_v2.score,
                product_matrix_v2_direction_ids=product_fit_v2.direction_ids,
                topic_priority_policy=topic_priority_policy,
                priority_title=version.representative_title,
                priority_summary=summary,
                theme_repetition=theme_repetition,
                controversy_risk=min(controversy_hits * 0.25, 1.0),
                marketing_risk=min(marketing_hits * 0.5, 1.0),
                governance_resolved=version.event_id not in unresolved_events,
                has_eligible_evidence=(
                    has_eligible_source_tier
                    and analysis_id is not None
                    and analysis_id in bound_analysis_ids
                ),
                tier_c_only=tier_c_only,
                unverified=any(term in searchable_text for term in _UNVERIFIED_TERMS),
                unsuitable_negative_incident=(
                    any(term in searchable_text for term in _NEGATIVE_INCIDENT_TERMS)
                    and parent_relevance < 0.6
                ),
                privacy_legal_safety_uncertain=any(
                    term in searchable_text for term in _PRIVACY_SAFETY_TERMS
                ),
                prohibited_marketing_risk=marketing_hits > 0,
                days_since_last_selection=(
                    (business_date - last_selected[version.event_id]).days
                    if version.event_id in last_selected
                    else None
                ),
            )
        )
    return tuple(candidates)


async def load_topic_scoring_config(session: AsyncSession, run_id: UUID) -> TopicScoringConfig:
    run = await session.get(TopicSelectionRunModel, run_id)
    if run is None:
        raise NotFoundError("topic selection run")
    return TopicScoringConfig.from_metadata(run.config_snapshot)


async def load_topic_rerank_config(session: AsyncSession, run_id: UUID) -> TopicRerankConfig:
    run = await session.get(TopicSelectionRunModel, run_id)
    if run is None:
        raise NotFoundError("topic selection run")
    return TopicRerankConfig.from_metadata(run.rerank_config_snapshot)


async def persist_topic_selection_decision(
    session: AsyncSession,
    *,
    claimed: ClaimedTopicSelectionJob,
    config: TopicScoringConfig,
    decision: DailyTopicDecision,
    rerank_outcome: TopicRerankOutcome | None = None,
) -> bool:
    now = datetime.now(UTC)
    job = await session.scalar(
        select(TopicSelectionJobModel)
        .where(
            TopicSelectionJobModel.id == claimed.job_id,
            TopicSelectionJobModel.run_id == claimed.run_id,
            TopicSelectionJobModel.lease_token == claimed.lease_token,
            TopicSelectionJobModel.status == "running",
            TopicSelectionJobModel.lease_expires_at >= now,
        )
        .with_for_update()
    )
    if job is None:
        await session.rollback()
        return False
    run = await session.scalar(
        select(TopicSelectionRunModel)
        .where(TopicSelectionRunModel.id == claimed.run_id)
        .with_for_update()
    )
    if run is None:
        raise RuntimeError("claimed topic selection run is missing")
    stored_rerank_config = TopicRerankConfig.from_metadata(run.rerank_config_snapshot)
    if rerank_outcome is None:
        if stored_rerank_config.enabled:
            raise ValueError("enabled topic rerank requires a persisted outcome")
        rerank_outcome = skipped_topic_rerank_outcome(
            stored_rerank_config,
            tuple(score.event_id for score in decision.scores if score.eligible)[:8],
        )
    fingerprint = topic_scoring_config_fingerprint(config)
    if (
        run.config_fingerprint != fingerprint
        or run.config_snapshot != config.as_metadata()
        or run.rerank_config_fingerprint != stored_rerank_config.fingerprint
        or rerank_outcome.policy_version != run.rerank_config_snapshot.get("policy_version")
        or rerank_outcome.provider != run.rerank_config_snapshot.get("provider")
        or rerank_outcome.model != run.rerank_config_snapshot.get("model")
        or decision.scoring_version != config.version
        or decision.scoring_profile != config.profile
    ):
        raise ValueError("topic selection decision does not match its immutable config")
    if any(score.rank is None for score in decision.scores):
        raise ValueError("persisted topic scores require stable ranks")
    selected_score = next(
        (score for score in decision.scores if score.event_id == decision.selected_event_id), None
    )
    if decision.selected_event_id is not None and (
        selected_score is None
        or not selected_score.eligible
        or selected_score.event_version_id != decision.selected_event_version_id
    ):
        raise ValueError("selected topic must reference the eligible ranked score")
    if decision.selected_event_id is None and decision.no_topic_code is None:
        raise ValueError("no-topic decision requires a reason code")

    existing_selection = await session.scalar(
        select(DailyTopicSelectionModel).where(
            DailyTopicSelectionModel.business_date == run.business_date,
            DailyTopicSelectionModel.timezone == run.timezone,
            DailyTopicSelectionModel.scoring_profile == run.scoring_profile,
            DailyTopicSelectionModel.superseded_at.is_(None),
        )
    )
    if existing_selection is not None and existing_selection.run_id != run.id:
        await session.rollback()
        raise ConflictError("daily topic is already locked for this date and profile")

    for score in decision.scores:
        rank = cast(int, score.rank)
        await session.execute(
            insert(TopicScoreModel)
            .values(
                id=uuid4(),
                run_id=run.id,
                event_id=score.event_id,
                event_version_id=score.event_version_id,
                raw_features=dict(score.raw_features),
                normalized_features=dict(score.normalized_features),
                weights=dict(score.weights),
                penalty_weights=dict(score.penalty_weights),
                positive_components=dict(score.positive_components),
                penalty_components=dict(score.penalty_components),
                total=score.total,
                threshold=score.threshold,
                passes_threshold=score.passes_threshold,
                eligible=score.eligible,
                veto_codes=[code.value for code in score.veto_codes],
                rank=rank,
                deterministic_rank=(score.deterministic_rank or rank),
                explanation={
                    "formula": "sum(positive_components)-sum(penalty_components)",
                    "scoring_version": score.scoring_version,
                    "scoring_profile": score.scoring_profile,
                    "veto_codes": [code.value for code in score.veto_codes],
                    "selection_priority_rule_version": score.selection_priority_rule_version,
                    "topic_priority_policy": score.topic_priority_policy,
                    "priority_applied": score.priority_applied,
                    "priority_reason": score.priority_reason,
                    "threshold_bypass_applied": score.threshold_bypass_applied,
                    "threshold_bypass_reason": score.threshold_bypass_reason,
                    "hard_tech_pool_policy_version": score.hard_tech_pool_policy_version,
                    "science_ai_education_rule_version": (score.science_ai_education_rule_version),
                    "science_tech_editorial_rule_version": (
                        score.science_tech_editorial_rule_version
                    ),
                    "product_matrix_fit_rule_version": (score.product_matrix_fit_rule_version),
                    "science_ai_education_reason_codes": list(
                        score.science_ai_education_reason_codes
                    ),
                    "product_matrix_direction_ids": list(score.product_matrix_direction_ids),
                    "science_tech_editorial_cohort": (
                        score.science_tech_editorial_cohort.value
                        if score.science_tech_editorial_cohort is not None
                        else None
                    ),
                    "science_tech_education_relevance": (score.science_tech_education_relevance),
                    "frontier_significance": score.frontier_significance,
                    "science_tech_editorial_reason_codes": list(
                        score.science_tech_editorial_reason_codes
                    ),
                    "science_tech_content_signals": [
                        signal.value for signal in score.science_tech_content_signals
                    ],
                    "deterministic_rank": score.deterministic_rank or rank,
                    "final_rank": rank,
                    "rerank_reason_codes": list(score.rerank_reason_codes),
                    "rerank_explanation": score.rerank_explanation,
                },
            )
            .on_conflict_do_nothing(constraint="uq_topic_scores_run_event")
        )
    rerank_metadata = topic_rerank_outcome_metadata(rerank_outcome)
    await session.execute(
        insert(TopicRerankRecordModel)
        .values(
            id=uuid4(),
            topic_selection_run_id=run.id,
            content_slot_run_id=None,
            policy_version=rerank_outcome.policy_version,
            provider=rerank_outcome.provider,
            model=rerank_outcome.model,
            outcome=rerank_outcome.kind.value,
            failure_code=(
                rerank_outcome.failure_code.value if rerank_outcome.failure_code else None
            ),
            candidate_count=rerank_outcome.candidate_count,
            base_order=rerank_metadata["base_order"],
            final_order=rerank_metadata["final_order"],
            reasons=rerank_metadata["reasons"],
            request_fingerprint=rerank_outcome.request_fingerprint,
            prompt_fingerprint=rerank_outcome.prompt_fingerprint,
            prompt_tokens=rerank_outcome.prompt_tokens,
            completion_tokens=rerank_outcome.completion_tokens,
            reasoning_tokens=rerank_outcome.reasoning_tokens,
            latency_ms=rerank_outcome.latency_ms,
        )
        .on_conflict_do_nothing()
    )
    selection_id = uuid4()
    inserted_selection_id = await session.scalar(
        insert(DailyTopicSelectionModel)
        .values(
            id=selection_id,
            business_date=run.business_date,
            timezone=run.timezone,
            scoring_profile=run.scoring_profile,
            revision=run.revision,
            run_id=run.id,
            config_id=run.config_id,
            config_fingerprint=run.config_fingerprint,
            decision_kind=("selected" if decision.selected_event_id is not None else "no_topic"),
            selected_event_id=decision.selected_event_id,
            selected_event_version_id=decision.selected_event_version_id,
            no_topic_code=(decision.no_topic_code.value if decision.no_topic_code else None),
        )
        .on_conflict_do_nothing(
            index_elements=[
                DailyTopicSelectionModel.business_date,
                DailyTopicSelectionModel.timezone,
                DailyTopicSelectionModel.scoring_profile,
            ],
            index_where=DailyTopicSelectionModel.superseded_at.is_(None),
        )
        .returning(DailyTopicSelectionModel.id)
    )
    if inserted_selection_id is None and existing_selection is None:
        existing_selection = await session.scalar(
            select(DailyTopicSelectionModel).where(
                DailyTopicSelectionModel.business_date == run.business_date,
                DailyTopicSelectionModel.timezone == run.timezone,
                DailyTopicSelectionModel.scoring_profile == run.scoring_profile,
                DailyTopicSelectionModel.superseded_at.is_(None),
            )
        )
    if existing_selection is not None and (
        existing_selection.run_id != run.id
        or existing_selection.selected_event_id != decision.selected_event_id
        or existing_selection.selected_event_version_id != decision.selected_event_version_id
        or existing_selection.no_topic_code
        != (decision.no_topic_code.value if decision.no_topic_code else None)
    ):
        await session.rollback()
        raise ConflictError("daily topic lock conflicts with this decision")
    run.status = "succeeded"
    run.selected_event_id = decision.selected_event_id
    run.selected_event_version_id = decision.selected_event_version_id
    run.no_topic_code = decision.no_topic_code.value if decision.no_topic_code else None
    run.total_scores = len(decision.scores)
    run.eligible_scores = sum(score.eligible for score in decision.scores)
    run.completed_at = now
    await session.commit()
    return True


async def complete_topic_selection_job(
    session: AsyncSession,
    *,
    claimed: ClaimedTopicSelectionJob,
) -> bool:
    now = datetime.now(UTC)
    result = cast(
        CursorResult[object],
        await session.execute(
            update(TopicSelectionJobModel)
            .where(
                TopicSelectionJobModel.id == claimed.job_id,
                TopicSelectionJobModel.run_id == claimed.run_id,
                TopicSelectionJobModel.lease_token == claimed.lease_token,
                TopicSelectionJobModel.status == "running",
                TopicSelectionJobModel.lease_expires_at >= now,
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
    run = await session.get(TopicSelectionRunModel, claimed.run_id)
    if run is None or run.status != "succeeded":
        await session.rollback()
        raise ConflictError("topic selection decision must be persisted before job completion")
    await session.commit()
    return True


async def fail_topic_selection_job(
    session: AsyncSession,
    *,
    claimed: ClaimedTopicSelectionJob,
    error_code: str,
) -> bool:
    normalized_error_code = error_code.strip()
    if not _SAFE_ERROR_CODE.fullmatch(normalized_error_code):
        raise ValueError("topic selection error code must be safe snake_case")
    now = datetime.now(UTC)
    result = cast(
        CursorResult[object],
        await session.execute(
            update(TopicSelectionJobModel)
            .where(
                TopicSelectionJobModel.id == claimed.job_id,
                TopicSelectionJobModel.run_id == claimed.run_id,
                TopicSelectionJobModel.lease_token == claimed.lease_token,
                TopicSelectionJobModel.status == "running",
                TopicSelectionJobModel.lease_expires_at >= now,
            )
            .values(
                status="failed",
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                heartbeat_at=now,
                error_code=normalized_error_code,
                completed_at=now,
            )
        ),
    )
    if not result.rowcount:
        await session.rollback()
        return False
    run = await session.get(TopicSelectionRunModel, claimed.run_id)
    if run is not None and run.status != "succeeded":
        run.status = "failed"
        run.completed_at = now
    await session.commit()
    return True


async def get_topic_selection_run(session: AsyncSession, run_id: UUID) -> TopicSelectionRunModel:
    run = await session.get(TopicSelectionRunModel, run_id)
    if run is None:
        raise NotFoundError("topic selection run")
    return run


async def get_topic_rerank_record(
    session: AsyncSession,
    *,
    topic_selection_run_id: UUID | None = None,
    content_slot_run_id: UUID | None = None,
) -> TopicRerankRecordModel | None:
    if (topic_selection_run_id is None) == (content_slot_run_id is None):
        raise ValueError("exactly one topic rerank origin is required")
    statement = select(TopicRerankRecordModel)
    if topic_selection_run_id is not None:
        statement = statement.where(
            TopicRerankRecordModel.topic_selection_run_id == topic_selection_run_id
        )
    else:
        statement = statement.where(
            TopicRerankRecordModel.content_slot_run_id == content_slot_run_id
        )
    return cast(TopicRerankRecordModel | None, await session.scalar(statement))


async def get_governed_event_cutoff(
    session: AsyncSession,
    *,
    business_date: date,
    timezone: str,
    now: datetime,
) -> datetime | None:
    """Return a fresh immutable cutoff only after acquisition and governance are terminal."""
    if now.tzinfo is None:
        raise ValueError("governance readiness time must be timezone-aware")
    acquisition = await session.scalar(
        select(AcquisitionRunModel)
        .where(
            AcquisitionRunModel.business_date == business_date,
            AcquisitionRunModel.timezone == timezone,
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
    if governance is None:
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
    return now.astimezone(UTC)


async def list_topic_score_rows(
    session: AsyncSession, run_id: UUID
) -> tuple[TopicScoreProjection, ...]:
    if await session.get(TopicSelectionRunModel, run_id) is None:
        raise NotFoundError("topic selection run")
    rows = tuple(
        (
            await session.execute(
                select(TopicScoreModel, EventClusterVersionModel)
                .join(
                    EventClusterVersionModel,
                    EventClusterVersionModel.id == TopicScoreModel.event_version_id,
                )
                .where(TopicScoreModel.run_id == run_id)
                .order_by(TopicScoreModel.rank)
            )
        ).tuples()
    )
    return tuple(
        TopicScoreProjection(
            score=score,
            event_title=version.representative_title,
            event_time=version.event_time_start or version.event_time_end,
        )
        for score, version in rows
    )


async def get_daily_topic_result(
    session: AsyncSession,
    *,
    business_date: date,
    timezone: str,
    scoring_profile: str,
) -> DailyTopicResultProjection | None:
    row = (
        await session.execute(
            select(
                DailyTopicSelectionModel,
                TopicSelectionRunModel,
                TopicScoringConfigModel,
                EventClusterVersionModel,
            )
            .join(
                TopicSelectionRunModel,
                TopicSelectionRunModel.id == DailyTopicSelectionModel.run_id,
            )
            .join(
                TopicScoringConfigModel,
                TopicScoringConfigModel.id == DailyTopicSelectionModel.config_id,
            )
            .outerjoin(
                EventClusterVersionModel,
                EventClusterVersionModel.id == DailyTopicSelectionModel.selected_event_version_id,
            )
            .where(
                DailyTopicSelectionModel.business_date == business_date,
                DailyTopicSelectionModel.timezone == timezone,
                DailyTopicSelectionModel.scoring_profile == scoring_profile,
                DailyTopicSelectionModel.superseded_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    selection, run, config, version = row
    return DailyTopicResultProjection(
        selection=selection,
        run=run,
        config=config,
        selected_title=version.representative_title if version is not None else None,
        selected_event_time=(
            version.event_time_start or version.event_time_end if version is not None else None
        ),
    )


class PostgresTopicSelectionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def governed_event_cutoff(
        self, *, business_date: date, timezone: str, now: datetime
    ) -> datetime | None:
        async with self._session_factory() as session:
            return await get_governed_event_cutoff(
                session,
                business_date=business_date,
                timezone=timezone,
                now=now,
            )

    async def enqueue(
        self,
        *,
        business_date: date,
        timezone: str,
        config: TopicScoringConfig,
        rerank_config: TopicRerankConfig,
        governed_event_cutoff: datetime,
        trigger: str = "manual",
    ) -> UUID:
        async with self._session_factory() as session:
            run, _ = await enqueue_topic_selection_run(
                session,
                business_date=business_date,
                timezone=timezone,
                config=config,
                rerank_config=rerank_config,
                governed_event_cutoff=governed_event_cutoff,
                trigger=trigger,
            )
        return run.id

    async def claim(
        self, *, worker_id: str, lease_seconds: int, max_attempts: int
    ) -> ClaimedTopicSelectionJob | None:
        async with self._session_factory() as session:
            return await claim_topic_selection_job(
                session,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
            )

    async def claim_for_run(
        self, *, run_id: UUID, worker_id: str, lease_seconds: int, max_attempts: int = 3
    ) -> ClaimedTopicSelectionJob | None:
        async with self._session_factory() as session:
            return await claim_topic_selection_job(
                session,
                run_id=run_id,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
            )

    async def heartbeat(self, *, claimed: ClaimedTopicSelectionJob, lease_seconds: int) -> bool:
        async with self._session_factory() as session:
            return await heartbeat_topic_selection_job(
                session, claimed=claimed, lease_seconds=lease_seconds
            )

    async def load_candidates(self, run_id: UUID) -> tuple[TopicCandidate, ...]:
        async with self._session_factory() as session:
            return await load_topic_candidates(session, run_id)

    async def load_config(self, run_id: UUID) -> TopicScoringConfig:
        async with self._session_factory() as session:
            return await load_topic_scoring_config(session, run_id)

    async def load_rerank_config(self, run_id: UUID) -> TopicRerankConfig:
        async with self._session_factory() as session:
            return await load_topic_rerank_config(session, run_id)

    async def persist_decision(
        self,
        *,
        claimed: ClaimedTopicSelectionJob,
        config: TopicScoringConfig,
        decision: DailyTopicDecision,
        rerank_outcome: TopicRerankOutcome | None = None,
    ) -> bool:
        async with self._session_factory() as session:
            return await persist_topic_selection_decision(
                session,
                claimed=claimed,
                config=config,
                decision=decision,
                rerank_outcome=rerank_outcome,
            )

    async def complete(self, *, claimed: ClaimedTopicSelectionJob) -> bool:
        async with self._session_factory() as session:
            return await complete_topic_selection_job(session, claimed=claimed)

    async def fail(self, *, claimed: ClaimedTopicSelectionJob, error_code: str) -> bool:
        async with self._session_factory() as session:
            return await fail_topic_selection_job(session, claimed=claimed, error_code=error_code)
