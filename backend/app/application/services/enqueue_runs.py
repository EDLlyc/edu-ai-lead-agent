from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from app.application.ports.acquisition import AcquisitionRepository
from app.core.config import Settings
from app.domain.content_slots import ContentSlotSchedule, due_content_slot_business_date
from app.domain.enums import RunTrigger
from app.domain.value_objects import due_business_date


async def enqueue_manual_run(
    repository: AcquisitionRepository,
    settings: Settings,
    *,
    source_ids: list[UUID] | None,
    idempotency_key: str | None,
    business_date: date | None = None,
) -> tuple[UUID, bool]:
    return await repository.enqueue(
        trigger=RunTrigger.MANUAL,
        timezone=settings.business_timezone,
        acquisition_version=settings.acquisition_version,
        business_date=business_date,
        manual_idempotency_key=idempotency_key,
        source_ids=source_ids,
    )


async def reconcile_daily_run(
    repository: AcquisitionRepository, settings: Settings, *, now: datetime
) -> tuple[UUID, bool] | None:
    business_date: date | None = due_business_date(
        now,
        timezone=settings.business_timezone,
        hour=settings.acquisition_schedule_hour,
        minute=settings.acquisition_schedule_minute,
        catchup_hours=settings.acquisition_catchup_hours,
    )
    if business_date is None:
        return None
    return await repository.enqueue(
        trigger=RunTrigger.SCHEDULED,
        timezone=settings.business_timezone,
        acquisition_version=settings.acquisition_version,
        business_date=business_date,
    )


async def reconcile_content_slot_run(
    repository: AcquisitionRepository,
    settings: Settings,
    *,
    schedule: ContentSlotSchedule,
    now: datetime,
) -> tuple[UUID, bool] | None:
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
        catchup_hours=settings.acquisition_catchup_hours,
    )
    if business_date is None:
        return None
    return await repository.enqueue(
        trigger=RunTrigger.SCHEDULED,
        timezone=settings.business_timezone,
        acquisition_version=settings.acquisition_version,
        business_date=business_date,
        content_slot=schedule.slot,
    )
