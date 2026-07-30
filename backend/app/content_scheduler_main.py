from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]

from app.application.services.topic_selection import reconcile_daily_topic_selection
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.topic_selection import PostgresTopicSelectionRepository

logger = structlog.get_logger()


async def run_content_scheduler() -> None:
    settings = get_settings()
    configure_logging(json_output=settings.app_env != "development")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    if not settings.content_enabled or not settings.content_scheduler_enabled:
        logger.info("content_scheduler_disabled")
        await stop.wait()
        return

    engine = create_engine(settings)
    repository = PostgresTopicSelectionRepository(create_session_factory(engine))

    async def reconcile() -> None:
        run_id = await reconcile_daily_topic_selection(
            repository,
            settings,
            now=datetime.now(UTC),
        )
        if run_id is not None:
            logger.info("topic_selection_run_reconciled", run_id=str(run_id))

    scheduler = AsyncIOScheduler(timezone=settings.business_timezone)
    scheduler.add_job(
        reconcile,
        CronTrigger(
            hour=settings.content_schedule_hour,
            minute=settings.content_schedule_minute,
            timezone=settings.business_timezone,
        ),
        id="daily-topic-selection",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    try:
        await reconcile()
        scheduler.start()
        logger.info(
            "content_scheduler_started",
            hour=settings.content_schedule_hour,
            minute=settings.content_schedule_minute,
            timezone=settings.business_timezone,
            scoring_version=settings.content_scoring_version,
        )
        await stop.wait()
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await engine.dispose()
        logger.info("content_scheduler_stopped")


if __name__ == "__main__":
    asyncio.run(run_content_scheduler())
