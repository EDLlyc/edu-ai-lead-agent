"""Production Monday scheduler for the durable three-article official-account DAG."""

from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime
from pathlib import Path

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]

from app.application.ports.official_account_weekly_dag import (
    WeeklyDagNodeFailure,
    WeeklyDagNodeResult,
)
from app.application.services.official_account_weekly_dag import (
    OfficialAccountWeeklyDagService,
    StaticWeeklyDagHandlerRegistry,
)
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.domain.official_account_weekly_dag import (
    WEEKLY_DAG_NODES,
    WeeklyDagClaim,
    weekly_dag_run_id,
)
from app.domain.official_account_weekly_edition import (
    WeeklyEditionSchedule,
    due_weekly_edition_week_start,
)
from app.infrastructure.db.execution_governance import (
    PostgresExecutionGovernanceRepository,
)
from app.infrastructure.db.official_account_weekly_dag import (
    PostgresOfficialAccountWeeklyDagRepository,
)
from app.infrastructure.db.official_account_weekly_production import (
    PostgresWeeklyProductionInputPlanner,
)
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.official_account_weekly_dag_governance import (
    PostgresOfficialAccountWeeklyDagGovernance,
)
from app.infrastructure.official_account_weekly_production import (
    LocalWeeklyProductionArtifactOwner,
)

logger = structlog.get_logger()


async def _scheduler_handler_rejected(claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
    del claim
    raise RuntimeError("the weekly scheduler cannot execute DAG nodes")


async def run_weekly_scheduler() -> None:
    settings = get_settings()
    configure_logging(json_output=settings.app_env != "development")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    if (
        not settings.official_account_weekly_production_enabled
        or not settings.official_account_weekly_scheduler_enabled
    ):
        logger.info("official_account_weekly_scheduler_disabled")
        await stop.wait()
        return
    _require_scheduler_dependencies(settings)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    repository = PostgresOfficialAccountWeeklyDagRepository(session_factory)
    governance = PostgresOfficialAccountWeeklyDagGovernance(
        repository=PostgresExecutionGovernanceRepository(session_factory),
        session_factory=session_factory,
    )
    registry = StaticWeeklyDagHandlerRegistry(
        {definition.key: _scheduler_handler_rejected for definition in WEEKLY_DAG_NODES}
    )
    service = OfficialAccountWeeklyDagService(
        repository=repository,
        governance=governance,
        handlers=registry,
    )
    planner = PostgresWeeklyProductionInputPlanner(session_factory)
    checkpoints = LocalWeeklyProductionArtifactOwner(
        Path(settings.official_account_weekly_artifact_root)
    )
    schedule = WeeklyEditionSchedule()

    async def reconcile() -> None:
        now = datetime.now(UTC)
        completed = await repository.completed_week_starts()
        week_start = due_weekly_edition_week_start(
            now,
            schedule=schedule,
            completed_week_starts=completed,
        )
        if week_start is None:
            logger.info("official_account_weekly_reconciled", due=False)
            return
        minimum = settings.official_account_weekly_min_week_start
        if minimum is None or week_start < minimum:
            logger.info(
                "official_account_weekly_reconciled",
                due=False,
                reason="before_activation_week",
            )
            return
        run_id = weekly_dag_run_id(week_start)
        try:
            existing = await service.status(run_id)
        except LookupError:
            existing = None
        if existing is not None:
            logger.info(
                "official_account_weekly_reconciled",
                due=True,
                created=False,
                run_id=str(run_id),
                status=existing.run.status.value,
            )
            return
        try:
            planned = await planner.plan(week_start=week_start, cutoff=now)
            checkpoint = checkpoints.put_json(planned.as_dict())
            if checkpoint.fingerprint != planned.fingerprint:
                raise ValueError("weekly production input serialization changed")
            run, created = await service.enqueue(
                week_start=week_start,
                input_fingerprint=planned.fingerprint,
                now=now,
            )
        except (ValueError, WeeklyDagNodeFailure) as error:
            logger.warning(
                "official_account_weekly_reconcile_deferred",
                week_start=week_start.isoformat(),
                error_code=(
                    error.error_code
                    if isinstance(error, WeeklyDagNodeFailure)
                    else "weekly_input_unavailable"
                ),
            )
            return
        logger.info(
            "official_account_weekly_reconciled",
            due=True,
            created=created,
            run_id=str(run.run_id),
            status=run.status.value,
        )

    scheduler = AsyncIOScheduler(timezone=schedule.timezone)
    scheduler.add_job(
        reconcile,
        CronTrigger(
            day_of_week="mon",
            hour=schedule.target_time.hour,
            minute=schedule.target_time.minute,
            timezone=schedule.timezone,
        ),
        id="official-account-weekly-due",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        reconcile,
        IntervalTrigger(seconds=settings.official_account_weekly_reconcile_seconds),
        id="official-account-weekly-catchup",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    try:
        await reconcile()
        scheduler.start()
        logger.info(
            "official_account_weekly_scheduler_started",
            timezone=schedule.timezone,
            weekday=schedule.weekday,
            target_time=schedule.target_time.isoformat(timespec="minutes"),
            catchup_hours=schedule.catchup_hours,
            minimum_week_start=settings.official_account_weekly_min_week_start.isoformat()
            if settings.official_account_weekly_min_week_start
            else None,
        )
        await stop.wait()
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await engine.dispose()
        logger.info("official_account_weekly_scheduler_stopped")


def _require_scheduler_dependencies(settings: Settings) -> None:
    if (
        not settings.official_account_local_enabled
        or not settings.official_account_local_worker_enabled
        or settings.ai_provider_mode != "zhipu"
    ):
        raise RuntimeError("weekly scheduler requires the persisted Zhipu article worker")


if __name__ == "__main__":
    asyncio.run(run_weekly_scheduler())
