from __future__ import annotations

import asyncio
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog

from app.application.ports.content_slots import (
    ClaimedContentSlotJob,
    ContentSlotRepository,
)
from app.application.services.topic_selection import build_topic_scoring_config
from app.core.config import Settings
from app.core.errors import ConflictError, ContentSlotLeaseLostError
from app.domain.content_slots import (
    ContentSlot,
    ContentSlotSchedule,
    SlotRankingPolicy,
    due_content_slot_business_date,
    select_slot_topics,
)

logger = structlog.get_logger()


def _schedule_for_slot(settings: Settings, slot: ContentSlot) -> ContentSlotSchedule:
    return next(schedule for schedule in settings.content_slot_schedules() if schedule.slot is slot)


async def enqueue_manual_content_slot(
    repository: ContentSlotRepository,
    settings: Settings,
    *,
    business_date: date | None,
    slot: ContentSlot,
    now: datetime,
) -> UUID:
    if now.tzinfo is None:
        raise ValueError("content slot enqueue time must be timezone-aware")
    schedule = _schedule_for_slot(settings, slot)
    if (
        not settings.content_enabled
        or not settings.content_slot_mode_enabled
        or not schedule.enabled
    ):
        raise ConflictError("content slot is disabled")
    resolved_date = business_date or now.astimezone(ZoneInfo(settings.business_timezone)).date()
    lineage = await repository.ready_lineage(
        business_date=resolved_date,
        timezone=settings.business_timezone,
        slot=slot,
        now=now,
    )
    if lineage is None:
        raise ConflictError("exact acquisition and governance lineage is not ready")
    return await repository.enqueue(
        business_date=resolved_date,
        timezone=settings.business_timezone,
        schedule=schedule,
        config=build_topic_scoring_config(settings),
        policy=SlotRankingPolicy(version=settings.content_slot_ranking_version),
        lineage=lineage,
        trigger="manual",
    )


async def reconcile_content_slot_selection(
    repository: ContentSlotRepository,
    settings: Settings,
    *,
    schedule: ContentSlotSchedule,
    now: datetime,
) -> UUID | None:
    if (
        not settings.content_enabled
        or not settings.content_slot_mode_enabled
        or not schedule.enabled
    ):
        return None
    business_date = due_content_slot_business_date(
        now,
        timezone=settings.business_timezone,
        schedule=schedule,
        catchup_hours=settings.content_catchup_hours,
    )
    if business_date is None:
        return None
    lineage = await repository.ready_lineage(
        business_date=business_date,
        timezone=settings.business_timezone,
        slot=schedule.slot,
        now=now,
    )
    if lineage is None:
        return None
    return await repository.enqueue(
        business_date=business_date,
        timezone=settings.business_timezone,
        schedule=schedule,
        config=build_topic_scoring_config(settings),
        policy=SlotRankingPolicy(version=settings.content_slot_ranking_version),
        lineage=lineage,
        trigger="scheduled",
    )


class ContentSlotExecutor:
    def __init__(self, repository: ContentSlotRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

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
            policy = await self._repository.load_policy(claimed.run_id)
            candidates = await self._repository.load_candidates(claimed.run_id)
            for conflict_attempt in range(3):
                self._ensure_lease(lease_lost)
                same_day_ids = await self._repository.same_day_selected_event_ids(claimed.run_id)
                decision = select_slot_topics(
                    candidates,
                    as_of=claimed.cutoff_at,
                    config=config,
                    slot=claimed.slot,
                    policy=policy,
                    max_items=claimed.item_limit,
                    same_day_selected_event_ids=same_day_ids,
                )
                try:
                    persisted = await self._repository.persist_decision(
                        claimed=claimed,
                        config=config,
                        policy=policy,
                        decision=decision,
                    )
                except ConflictError:
                    if conflict_attempt == 2:
                        raise
                    continue
                if not persisted:
                    raise ContentSlotLeaseLostError()
                break
            if not await self._repository.complete(claimed=claimed):
                raise ContentSlotLeaseLostError()
            logger.info(
                "content_slot_job_succeeded",
                content_slot_run_id=str(claimed.run_id),
                job_id=str(claimed.job_id),
                business_date=claimed.business_date.isoformat(),
                content_slot=claimed.slot.value,
                considered_count=len(decision.scores),
                selected_count=len(decision.selected_event_ids),
                unfilled_count=decision.unfilled_count,
                scoring_version=config.version,
                slot_policy_version=policy.version,
            )
        except ContentSlotLeaseLostError:
            logger.warning(
                "content_slot_job_lease_lost",
                content_slot_run_id=str(claimed.run_id),
                job_id=str(claimed.job_id),
            )
        except (ConflictError, ValueError):
            await self._repository.fail(
                claimed=claimed,
                error_code="content_slot_decision_conflict",
            )
            logger.warning(
                "content_slot_job_invalid",
                content_slot_run_id=str(claimed.run_id),
                job_id=str(claimed.job_id),
                error_code="content_slot_decision_conflict",
            )
        except Exception:
            await self._repository.fail(claimed=claimed, error_code="internal_worker_error")
            logger.exception(
                "content_slot_job_internal_failure",
                content_slot_run_id=str(claimed.run_id),
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
            raise ContentSlotLeaseLostError()

    async def _heartbeat_loop(
        self,
        claimed: ClaimedContentSlotJob,
        stop: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=self._settings.content_heartbeat_seconds
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
                        "content_slot_heartbeat_failed",
                        content_slot_run_id=str(claimed.run_id),
                        job_id=str(claimed.job_id),
                        error_code="heartbeat_dependency_failure",
                    )
                    return
                if not renewed:
                    lease_lost.set()
                    return
