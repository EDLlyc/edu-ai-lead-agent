from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]

from app.application.services.enqueue_runs import (
    reconcile_content_slot_run,
    reconcile_daily_run,
)
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.db.repositories import PostgresAcquisitionRepository
from app.infrastructure.db.session import create_engine, create_session_factory

logger = structlog.get_logger()


async def run_scheduler() -> None:
    settings = get_settings()
    configure_logging(json_output=settings.app_env != "development")
    engine = create_engine(settings)
    repository = PostgresAcquisitionRepository(create_session_factory(engine))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)

    async def reconcile_legacy() -> None:
        result = await reconcile_daily_run(repository, settings, now=datetime.now(UTC))
        if result is not None:
            run_id, created = result
            logger.info("scheduled_run_reconciled", run_id=str(run_id), created=created)

    async def reconcile_slot(schedule_index: int) -> None:
        schedule = settings.content_slot_schedules()[schedule_index]
        result = await reconcile_content_slot_run(
            repository,
            settings,
            schedule=schedule,
            now=datetime.now(UTC),
        )
        if result is not None:
            run_id, created = result
            logger.info(
                "scheduled_slot_acquisition_reconciled",
                run_id=str(run_id),
                content_slot=schedule.slot.value,
                created=created,
            )

    scheduler = AsyncIOScheduler(timezone=settings.business_timezone)
    if settings.content_slot_mode_enabled:
        for index, schedule in enumerate(settings.content_slot_schedules()):
            if not schedule.enabled:
                continue
            preparation_minutes = (
                schedule.target_hour * 60 + schedule.target_minute - schedule.prepare_lead_minutes
            ) % (24 * 60)
            scheduler.add_job(
                reconcile_slot,
                CronTrigger(
                    hour=preparation_minutes // 60,
                    minute=preparation_minutes % 60,
                    timezone=settings.business_timezone,
                ),
                args=(index,),
                id=f"content-slot-{schedule.slot.value}-acquisition",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
            await reconcile_slot(index)
    else:
        scheduler.add_job(
            reconcile_legacy,
            CronTrigger(
                hour=settings.acquisition_schedule_hour,
                minute=settings.acquisition_schedule_minute,
                timezone=settings.business_timezone,
            ),
            id="daily-authoritative-source-acquisition",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        await reconcile_legacy()
    scheduler.start()
    logger.info(
        "scheduler_started",
        content_slot_mode_enabled=settings.content_slot_mode_enabled,
        enabled_slots=[
            schedule.slot.value
            for schedule in settings.content_slot_schedules()
            if schedule.enabled
        ],
        timezone=settings.business_timezone,
    )
    try:
        await stop.wait()
    finally:
        scheduler.shutdown(wait=False)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_scheduler())
