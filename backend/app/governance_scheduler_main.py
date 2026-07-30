from __future__ import annotations

import asyncio
import signal

import structlog

from app.application.services.governance_runtime import build_governance_version_bundle
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.db.governance_repositories import PostgresGovernanceRepository
from app.infrastructure.db.session import create_engine, create_session_factory

logger = structlog.get_logger()


async def run_governance_scheduler() -> None:
    settings = get_settings()
    configure_logging(json_output=settings.app_env != "development")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    if not settings.governance_enabled or not settings.governance_scheduler_enabled:
        logger.info("governance_scheduler_disabled")
        await stop.wait()
        return

    engine = create_engine(settings)
    repository = PostgresGovernanceRepository(create_session_factory(engine))
    bundle = build_governance_version_bundle(settings)
    logger.info(
        "governance_scheduler_started",
        pipeline_version=bundle.pipeline_version,
        poll_seconds=settings.governance_poll_seconds,
    )
    try:
        while not stop.is_set():
            created = await repository.reconcile_terminal_acquisition_runs(
                bundle=bundle,
                timezone=settings.business_timezone,
            )
            if created:
                logger.info(
                    "governance_runs_reconciled",
                    created_count=created,
                    pipeline_version=bundle.pipeline_version,
                )
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.governance_poll_seconds)
            except TimeoutError:
                pass
    finally:
        await engine.dispose()
        logger.info("governance_scheduler_stopped")


if __name__ == "__main__":
    asyncio.run(run_governance_scheduler())
