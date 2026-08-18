from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from app.application.ports.content_slots import (
    ClaimedContentSlotJob,
    GovernedSlotLineage,
)
from app.application.services.content_slots import (
    ContentSlotExecutor,
    enqueue_manual_content_slot,
    reconcile_content_slot_selection,
)
from app.application.services.enqueue_runs import reconcile_content_slot_run
from app.core.config import Settings
from app.core.errors import ConflictError
from app.domain.content_slots import ContentSlot, ContentSlotSchedule, SlotRankingPolicy
from app.domain.enums import RunTrigger
from app.domain.topic_rerank import TopicRerankConfig
from app.domain.topic_selection import TopicScoringConfig

NOW = datetime(2026, 8, 14, 3, 0, tzinfo=UTC)


class _SlotRepository:
    def __init__(self, *, ready: bool = True, conflict_count: int = 0) -> None:
        self.lineage = (
            GovernedSlotLineage(
                acquisition_run_id=uuid4(),
                governance_run_id=uuid4(),
                governed_event_cutoff=NOW,
            )
            if ready
            else None
        )
        self.run_id = uuid4()
        self.job_id = uuid4()
        self.lease_token = uuid4()
        self.conflict_count = conflict_count
        self.ready_calls: list[tuple[date, ContentSlot]] = []
        self.enqueue_triggers: list[str] = []
        self.same_day_reads = 0
        self.completed = False
        self.failed: list[str] = []
        self.claimed = False

    async def ready_lineage(
        self,
        *,
        business_date: date,
        timezone: str,
        slot: ContentSlot,
        now: datetime,
    ) -> GovernedSlotLineage | None:
        assert timezone == "Asia/Shanghai"
        assert now == NOW
        self.ready_calls.append((business_date, slot))
        return self.lineage

    async def enqueue(self, **values: object):
        self.enqueue_triggers.append(str(values["trigger"]))
        return self.run_id

    async def claim(self, **_values: object):
        if self.claimed:
            return None
        self.claimed = True
        return ClaimedContentSlotJob(
            job_id=self.job_id,
            run_id=self.run_id,
            attempt_number=1,
            lease_token=self.lease_token,
            business_date=date(2026, 8, 14),
            timezone="Asia/Shanghai",
            slot=ContentSlot.NOON,
            cutoff_at=NOW,
            item_limit=3,
        )

    async def heartbeat(self, **_values: object) -> bool:
        return True

    async def load_config(self, _run_id: object) -> TopicScoringConfig:
        return TopicScoringConfig()

    async def load_policy(self, _run_id: object) -> SlotRankingPolicy:
        return SlotRankingPolicy()

    async def load_rerank_config(self, _run_id: object) -> TopicRerankConfig:
        return TopicRerankConfig()

    async def load_candidates(self, _run_id: object):
        return ()

    async def same_day_selected_event_ids(self, _run_id: object):
        self.same_day_reads += 1
        return frozenset()

    async def persist_decision(self, **_values: object) -> bool:
        if self.conflict_count:
            self.conflict_count -= 1
            raise ConflictError("simulated concurrent earlier-slot selection")
        return True

    async def complete(self, **_values: object) -> bool:
        self.completed = True
        return True

    async def fail(self, *, error_code: str, **_values: object) -> bool:
        self.failed.append(error_code)
        return True


class _AcquisitionRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.run_id = uuid4()

    async def enqueue(self, **values: object):
        self.calls.append(values)
        return self.run_id, True


def _enabled_settings() -> Settings:
    return Settings(
        _env_file=None,
        content_enabled=True,
        content_slot_mode_enabled=True,
        content_noon_enabled=True,
    )


@pytest.mark.asyncio
async def test_manual_slot_requires_global_content_enable_and_exact_ready_lineage() -> None:
    repository = _SlotRepository()
    globally_disabled = _enabled_settings().model_copy(update={"content_enabled": False})

    with pytest.raises(ConflictError, match="disabled"):
        await enqueue_manual_content_slot(
            repository,  # type: ignore[arg-type]
            globally_disabled,
            business_date=date(2026, 8, 14),
            slot=ContentSlot.NOON,
            now=NOW,
        )
    assert repository.ready_calls == []

    not_ready = _SlotRepository(ready=False)
    with pytest.raises(ConflictError, match="exact acquisition and governance"):
        await enqueue_manual_content_slot(
            not_ready,  # type: ignore[arg-type]
            _enabled_settings(),
            business_date=date(2026, 8, 14),
            slot=ContentSlot.NOON,
            now=NOW,
        )
    assert not_ready.ready_calls == [(date(2026, 8, 14), ContentSlot.NOON)]


@pytest.mark.asyncio
async def test_slot_acquisition_and_selection_reconciliation_share_due_business_date() -> None:
    settings = _enabled_settings()
    schedule = next(
        item for item in settings.content_slot_schedules() if item.slot is ContentSlot.NOON
    )
    acquisition = _AcquisitionRepository()
    selection = _SlotRepository()

    acquisition_result = await reconcile_content_slot_run(
        acquisition,  # type: ignore[arg-type]
        settings,
        schedule=schedule,
        now=NOW,
    )
    selection_result = await reconcile_content_slot_selection(
        selection,  # type: ignore[arg-type]
        settings,
        schedule=schedule,
        now=NOW,
    )

    assert acquisition_result == (acquisition.run_id, True)
    assert acquisition.calls == [
        {
            "trigger": RunTrigger.SCHEDULED,
            "timezone": "Asia/Shanghai",
            "acquisition_version": settings.acquisition_version,
            "business_date": date(2026, 8, 14),
            "content_slot": ContentSlot.NOON,
        }
    ]
    assert selection_result == selection.run_id
    assert selection.ready_calls == [(date(2026, 8, 14), ContentSlot.NOON)]
    assert selection.enqueue_triggers == ["scheduled"]


@pytest.mark.asyncio
async def test_slot_executor_does_not_loop_after_a_persistence_conflict() -> None:
    repository = _SlotRepository(conflict_count=2)
    executor = ContentSlotExecutor(repository, _enabled_settings())  # type: ignore[arg-type]

    assert await executor.execute_next("slot-worker") is True

    assert repository.same_day_reads == 1
    assert repository.completed is False
    assert repository.failed == ["content_slot_decision_conflict"]


@pytest.mark.asyncio
async def test_reconciliation_skips_disabled_schedule_before_readiness() -> None:
    repository = _SlotRepository()
    acquisition = _AcquisitionRepository()
    schedule = ContentSlotSchedule(
        slot=ContentSlot.EVENING,
        enabled=False,
        target_hour=18,
        target_minute=30,
    )

    assert (
        await reconcile_content_slot_selection(
            repository,  # type: ignore[arg-type]
            _enabled_settings(),
            schedule=schedule,
            now=NOW,
        )
        is None
    )
    assert repository.ready_calls == []

    globally_disabled = _enabled_settings().model_copy(update={"content_enabled": False})
    enabled_schedule = ContentSlotSchedule(
        slot=ContentSlot.NOON,
        enabled=True,
        target_hour=12,
        target_minute=30,
    )
    assert (
        await reconcile_content_slot_run(
            acquisition,  # type: ignore[arg-type]
            globally_disabled,
            schedule=enabled_schedule,
            now=NOW,
        )
        is None
    )
    assert acquisition.calls == []
