from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]

from app.application.services.enqueue_runs import reconcile_daily_run
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

    async def reconcile() -> None:
        result = await reconcile_daily_run(repository, settings, now=datetime.now(UTC))
        if result is not None:
            run_id, created = result
            logger.info("scheduled_run_reconciled", run_id=str(run_id), created=created)

    scheduler = AsyncIOScheduler(timezone=settings.business_timezone)
    scheduler.add_job(
        reconcile,
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
    await reconcile()
    scheduler.start()
    logger.info(
        "scheduler_started",
        hour=settings.acquisition_schedule_hour,
        minute=settings.acquisition_schedule_minute,
        timezone=settings.business_timezone,
    )
    try:
        await stop.wait()
    finally:
        scheduler.shutdown(wait=False)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_scheduler())
