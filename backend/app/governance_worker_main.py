from __future__ import annotations

import asyncio
import signal

import structlog

from app.application.services.governance_analysis import FactualAnalysisCoordinator
from app.application.services.governance_graph import (
    CompiledGovernanceGraph,
    build_governance_graph,
)
from app.application.services.governance_worker import (
    SystemClock,
    execute_claimed_governance_job,
)
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.domain.event_assignment import EventAssignmentPolicy
from app.domain.governance_semantic import SemanticDuplicatePolicy
from app.infrastructure.ai.factory import governance_models
from app.infrastructure.db.governance_artifacts import PostgresGovernanceArtifactRepository
from app.infrastructure.db.governance_checkpointer import PostgresGovernanceCheckpointer
from app.infrastructure.db.governance_repositories import PostgresGovernanceRepository
from app.infrastructure.db.session import create_engine, create_session_factory

logger = structlog.get_logger()


async def run_governance_worker() -> None:
    settings = get_settings()
    configure_logging(json_output=settings.app_env != "development")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    if not settings.governance_enabled or not settings.governance_worker_enabled:
        logger.info("governance_worker_disabled")
        await stop.wait()
        return
    if settings.ai_provider_mode == "disabled":
        logger.warning("governance_worker_provider_disabled")
        await stop.wait()
        return

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    repository = PostgresGovernanceRepository(session_factory)
    artifact_repository = PostgresGovernanceArtifactRepository(session_factory)
    checkpointer = PostgresGovernanceCheckpointer(settings.governance_checkpoint_database_url)
    logger.info(
        "governance_worker_started",
        provider=settings.ai_provider_mode,
        concurrency=settings.governance_worker_concurrency,
    )
    try:
        async with governance_models(settings) as (analysis_model, embedding_model):
            async with checkpointer.saver() as saver:
                graph = build_governance_graph(
                    governance_repository=repository,
                    artifact_repository=artifact_repository,
                    analysis_coordinator=FactualAnalysisCoordinator(
                        analysis_model,
                        max_validation_corrections=settings.ai_max_validation_corrections,
                    ),
                    embedding_model=embedding_model,
                    clock=SystemClock(),
                    semantic_policy=SemanticDuplicatePolicy(
                        version=settings.governance_similarity_rule_version
                    ),
                    event_policy=EventAssignmentPolicy(
                        version=settings.governance_event_assignment_version
                    ),
                    analysis_max_output_tokens=settings.ai_max_output_tokens,
                    checkpointer=saver,
                )
                workers = [
                    asyncio.create_task(
                        _worker_loop(
                            worker_id=f"governance-worker-{index + 1}",
                            stop=stop,
                            repository=repository,
                            checkpointer=checkpointer,
                            graph=graph,
                            settings=settings,
                        )
                    )
                    for index in range(settings.governance_worker_concurrency)
                ]
                await stop.wait()
                await asyncio.gather(*workers)
    finally:
        await engine.dispose()
        logger.info("governance_worker_stopped")


async def _worker_loop(
    *,
    worker_id: str,
    stop: asyncio.Event,
    repository: PostgresGovernanceRepository,
    checkpointer: PostgresGovernanceCheckpointer,
    graph: CompiledGovernanceGraph,
    settings: Settings,
) -> None:
    while not stop.is_set():
        claimed = await repository.claim(
            worker_id=worker_id,
            lease_seconds=settings.governance_lease_seconds,
        )
        if claimed is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.governance_poll_seconds)
            except TimeoutError:
                pass
            continue
        await execute_claimed_governance_job(
            claimed=claimed,
            repository=repository,
            checkpointer=checkpointer,
            graph=graph,
            settings=settings,
        )


if __name__ == "__main__":
    asyncio.run(run_governance_worker())
