from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from app import content_scheduler_main
from app.application.ports.content_slots import ContentSlotRepository
from app.core.config import Settings
from app.core.errors import ConflictError
from app.domain.content_slots import ContentSlot, ContentSlotSchedule

NOW = datetime(2026, 8, 27, 4, 40, tzinfo=UTC)
SCHEDULE = ContentSlotSchedule(
    slot=ContentSlot.NOON,
    enabled=True,
    target_hour=12,
    target_minute=30,
)


@pytest.mark.asyncio
async def test_scheduled_reconcile_skips_immutable_history_conflict(monkeypatch) -> None:
    async def conflict(*args, **kwargs):
        raise ConflictError("content slot run identity is immutable")

    monkeypatch.setattr(content_scheduler_main, "reconcile_content_slot_selection", conflict)

    result = await content_scheduler_main._reconcile_scheduled_content_slot(
        cast(ContentSlotRepository, object()),
        cast(Settings, object()),
        schedule=SCHEDULE,
        now=NOW,
    )

    assert result is None


@pytest.mark.asyncio
async def test_scheduled_reconcile_returns_new_run(monkeypatch) -> None:
    expected = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

    async def created(*args, **kwargs):
        return expected

    monkeypatch.setattr(content_scheduler_main, "reconcile_content_slot_selection", created)

    result = await content_scheduler_main._reconcile_scheduled_content_slot(
        cast(ContentSlotRepository, object()),
        cast(Settings, object()),
        schedule=SCHEDULE,
        now=NOW,
    )

    assert result == expected
