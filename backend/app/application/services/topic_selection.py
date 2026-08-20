from __future__ import annotations

import asyncio
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog

from app.application.ports.topic_rerank import TopicReranker
from app.application.ports.topic_selection import (
    ClaimedTopicSelectionJob,
    TopicSelectionRepository,
)
from app.application.services.topic_reranking import execute_topic_rerank
from app.core.config import Settings
from app.core.errors import ConflictError, TopicSelectionLeaseLostError
from app.domain.ministry_education_priority import (
    MINISTRY_EDUCATION_PRIORITY_RULE_VERSION,
    MINISTRY_EDUCATION_PRIORITY_V4_RULE_VERSION,
)
from app.domain.science_policy_priority import SCIENCE_POLICY_PRIORITY_RULE_VERSION
from app.domain.topic_rerank import (
    TopicRerankConfig,
    TopicRerankRequest,
    build_daily_rerank_pool,
    finalize_daily_topic_rerank,
)
from app.domain.topic_selection import (
    DEFAULT_TOPIC_SCORING_THRESHOLD,
    HISTORICAL_TOPIC_SCORING_THRESHOLD,
    LOWER_THRESHOLD_TOPIC_SCORING_VERSIONS,
    SCIENCE_EDUCATION_TOPIC_SCORING_VERSION,
    SUBSTANTIVE_SCIENCE_EDUCATION_TOPIC_SCORING_VERSION,
    TIERED_SCIENCE_TECH_TOPIC_SCORING_VERSIONS,
    TopicScoringConfig,
    select_daily_topic,
)
from app.domain.value_objects import due_business_date

logger = structlog.get_logger()


def build_topic_scoring_config(settings: Settings) -> TopicScoringConfig:
    if settings.content_scoring_version == SUBSTANTIVE_SCIENCE_EDUCATION_TOPIC_SCORING_VERSION:
        priority_rule_version = (
            settings.content_selection_priority_rule_version
            or MINISTRY_EDUCATION_PRIORITY_V4_RULE_VERSION
        )
    elif settings.content_scoring_version in TIERED_SCIENCE_TECH_TOPIC_SCORING_VERSIONS:
        priority_rule_version = (
            settings.content_selection_priority_rule_version
            or MINISTRY_EDUCATION_PRIORITY_RULE_VERSION
        )
    elif settings.content_scoring_version == SCIENCE_EDUCATION_TOPIC_SCORING_VERSION:
        priority_rule_version = None
    elif settings.content_scoring_version == "scoring-v1-preview.4-science-policy-priority":
        priority_rule_version = SCIENCE_POLICY_PRIORITY_RULE_VERSION
    else:
        priority_rule_version = settings.content_selection_priority_rule_version or None
    return TopicScoringConfig(
        version=settings.content_scoring_version,
        profile=settings.content_scoring_profile,
        selection_priority_rule_version=priority_rule_version,
        threshold=(
            DEFAULT_TOPIC_SCORING_THRESHOLD
            if settings.content_scoring_version in LOWER_THRESHOLD_TOPIC_SCORING_VERSIONS
            else HISTORICAL_TOPIC_SCORING_THRESHOLD
        ),
        freshness_window_days=float(settings.content_freshness_window_days),
    )


def build_topic_rerank_config(settings: Settings) -> TopicRerankConfig:
    enabled = settings.content_enabled and settings.content_llm_rerank_enabled
    return TopicRerankConfig(
        enabled=enabled,
        policy_version=settings.content_llm_rerank_policy_version,
        candidate_limit=settings.content_llm_rerank_candidate_limit,
        provider=(settings.ai_provider_mode if enabled else "disabled"),
        model=(settings.ai_chat_model if enabled else "none"),
        max_output_tokens=settings.content_llm_rerank_max_output_tokens,
    )


async def enqueue_manual_topic_selection(
    repository: TopicSelectionRepository,
    settings: Settings,
    *,
    business_date: date | None,
    now: datetime,
) -> UUID:
    if now.tzinfo is None:
        raise ValueError("topic selection enqueue time must be timezone-aware")
    resolved_date = business_date or now.astimezone(ZoneInfo(settings.business_timezone)).date()
    governed_event_cutoff = await repository.governed_event_cutoff(
        business_date=resolved_date,
        timezone=settings.business_timezone,
        now=now,
    )
    if governed_event_cutoff is None:
        raise ConflictError("governance is not ready for topic selection")
    return await repository.enqueue(
        business_date=resolved_date,
        timezone=settings.business_timezone,
        config=build_topic_scoring_config(settings),
        rerank_config=build_topic_rerank_config(settings),
        governed_event_cutoff=governed_event_cutoff,
        trigger="manual",
    )


async def reconcile_daily_topic_selection(
    repository: TopicSelectionRepository,
    settings: Settings,
    *,
    now: datetime,
) -> UUID | None:
    business_date = due_business_date(
        now,
        timezone=settings.business_timezone,
        hour=settings.content_schedule_hour,
        minute=settings.content_schedule_minute,
        catchup_hours=settings.content_catchup_hours,
    )
    if business_date is None:
        return None
    governed_event_cutoff = await repository.governed_event_cutoff(
        business_date=business_date,
        timezone=settings.business_timezone,
        now=now,
    )
    if governed_event_cutoff is None:
        return None
    try:
        return await repository.enqueue(
            business_date=business_date,
            timezone=settings.business_timezone,
            config=build_topic_scoring_config(settings),
            rerank_config=build_topic_rerank_config(settings),
            governed_event_cutoff=governed_event_cutoff,
            trigger="scheduled",
        )
    except ConflictError:
        # A locked selected run must remain immutable; the scheduler can still reconcile
        # downstream copy jobs for that current run instead of exiting its process.
        logger.info(
            "topic_selection_reconcile_skipped",
            business_date=business_date.isoformat(),
            timezone=settings.business_timezone,
            scoring_profile=settings.content_scoring_profile,
            reason="current_daily_run_locked",
        )
        return None


class TopicSelectionExecutor:
    def __init__(
        self,
        repository: TopicSelectionRepository,
        settings: Settings,
        reranker: TopicReranker | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._reranker = reranker

    async def execute_next(self, worker_id: str) -> bool:
        claimed = await self._repository.claim(
            worker_id=worker_id,
            lease_seconds=self._settings.content_lease_seconds,
            max_attempts=self._settings.content_max_attempts,
        )
        if claimed is None:
            return False
        heartbeat_stop = asyncio.Event()
        lease_lost = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(claimed, heartbeat_stop, lease_lost)
        )
        try:
            config = await self._repository.load_config(claimed.run_id)
            rerank_config = await self._repository.load_rerank_config(claimed.run_id)
            candidates = await self._repository.load_candidates(claimed.run_id)
            self._ensure_lease(lease_lost)
            decision = select_daily_topic(
                candidates,
                as_of=claimed.cutoff_at,
                config=config,
            )
            pool = build_daily_rerank_pool(
                decision,
                candidates,
                limit=rerank_config.candidate_limit,
            )
            request = (
                TopicRerankRequest(
                    run_id=claimed.run_id,
                    cutoff_at=claimed.cutoff_at,
                    context="daily",
                    policy_version=rerank_config.policy_version,
                    max_output_tokens=rerank_config.max_output_tokens,
                    candidates=pool,
                )
                if pool
                else None
            )
            rerank_outcome = await execute_topic_rerank(
                config=rerank_config,
                reranker=self._reranker,
                request=request,
            )
            self._ensure_lease(lease_lost)
            decision, rerank_outcome = finalize_daily_topic_rerank(
                decision,
                pool,
                rerank_outcome,
                request=request,
                candidate_limit=rerank_config.candidate_limit,
            )
            if not await self._repository.persist_decision(
                claimed=claimed,
                config=config,
                decision=decision,
                rerank_outcome=rerank_outcome,
            ):
                raise TopicSelectionLeaseLostError()
            if not await self._repository.complete(claimed=claimed):
                raise TopicSelectionLeaseLostError()
            logger.info(
                "topic_selection_job_succeeded",
                topic_selection_run_id=str(claimed.run_id),
                job_id=str(claimed.job_id),
                business_date=claimed.business_date.isoformat(),
                considered_count=len(decision.scores),
                eligible_count=sum(score.eligible for score in decision.scores),
                selected_event_id=(
                    str(decision.selected_event_id) if decision.selected_event_id else None
                ),
                no_topic_code=(decision.no_topic_code.value if decision.no_topic_code else None),
                scoring_version=config.version,
                rerank_outcome=rerank_outcome.kind.value,
                rerank_failure_code=(
                    rerank_outcome.failure_code.value if rerank_outcome.failure_code else None
                ),
            )
        except TopicSelectionLeaseLostError:
            logger.warning(
                "topic_selection_job_lease_lost",
                topic_selection_run_id=str(claimed.run_id),
                job_id=str(claimed.job_id),
            )
        except ValueError:
            await self._repository.fail(
                claimed=claimed,
                error_code="invalid_topic_selection_input",
            )
            logger.warning(
                "topic_selection_job_invalid_input",
                topic_selection_run_id=str(claimed.run_id),
                job_id=str(claimed.job_id),
                error_code="invalid_topic_selection_input",
            )
        except Exception:
            await self._repository.fail(
                claimed=claimed,
                error_code="internal_worker_error",
            )
            logger.exception(
                "topic_selection_job_internal_failure",
                topic_selection_run_id=str(claimed.run_id),
                job_id=str(claimed.job_id),
                error_code="internal_worker_error",
            )
        finally:
            heartbeat_stop.set()
            await heartbeat_task
        return True

    @staticmethod
    def _ensure_lease(lease_lost: asyncio.Event) -> None:
        if lease_lost.is_set():
            raise TopicSelectionLeaseLostError()

    async def _heartbeat_loop(
        self,
        claimed: ClaimedTopicSelectionJob,
        stop: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=self._settings.content_heartbeat_seconds,
                )
                return
            except TimeoutError:
                try:
                    renewed = await self._repository.heartbeat(
                        claimed=claimed,
                        lease_seconds=self._settings.content_lease_seconds,
                    )
                except Exception:
                    lease_lost.set()
                    logger.error(
                        "topic_selection_heartbeat_failed",
                        topic_selection_run_id=str(claimed.run_id),
                        job_id=str(claimed.job_id),
                        error_code="heartbeat_dependency_failure",
                    )
                    return
                if not renewed:
                    lease_lost.set()
                    return
