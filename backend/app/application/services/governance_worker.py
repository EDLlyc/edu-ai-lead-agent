from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from langchain_core.runnables import RunnableConfig

from app.application.ports.governance import GovernanceCheckpointer, GovernanceRepository
from app.application.services.governance_graph import (
    CompiledGovernanceGraph,
    governance_graph_input,
    governance_graph_resume_claim,
    governance_thread_id,
)
from app.core.config import Settings
from app.core.errors import (
    AppError,
    FactualAnalysisValidationError,
    GovernanceLeaseLostError,
    InvalidProviderOutputError,
    ProviderDimensionMismatchError,
    ProviderInputLimitError,
    ProviderRejectedError,
)
from app.domain.governance_entities import ClaimedGovernanceJob, GovernanceJobCompletion
from app.domain.governance_enums import (
    EventAssignmentOutcome,
    GovernanceAttemptResult,
    GovernanceJobStatus,
)

logger = structlog.get_logger()

_REVIEWABLE_ERRORS = (
    FactualAnalysisValidationError,
    InvalidProviderOutputError,
    ProviderDimensionMismatchError,
    ProviderInputLimitError,
    ProviderRejectedError,
)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


async def execute_claimed_governance_job(
    *,
    claimed: ClaimedGovernanceJob,
    repository: GovernanceRepository,
    checkpointer: GovernanceCheckpointer,
    graph: CompiledGovernanceGraph,
    settings: Settings,
) -> None:
    try:
        attempt_id = await repository.create_attempt(claimed, stage="langgraph")
    except GovernanceLeaseLostError:
        _log_lease_lost(claimed)
        return
    heartbeat_stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(
            claimed=claimed,
            repository=repository,
            settings=settings,
            stop=heartbeat_stop,
        )
    )
    try:
        thread_id = governance_thread_id(claimed.job_id)
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        resume = await checkpointer.checkpoint_exists(thread_id=thread_id)
        if resume:
            await graph.aupdate_state(config, governance_graph_resume_claim(claimed))
        state = await graph.ainvoke(
            None if resume else governance_graph_input(claimed),
            config,
        )
        assignment_outcome = state.get("assignment_outcome")
        review_required = (
            assignment_outcome == EventAssignmentOutcome.REVIEW_REQUIRED.value
            or state.get("stage") == "review-required-quarantine"
        )
        attempt_result = (
            GovernanceAttemptResult.REVIEW_REQUIRED
            if review_required
            else GovernanceAttemptResult.SUCCEEDED
        )
        job_status = (
            GovernanceJobStatus.REVIEW_REQUIRED
            if review_required
            else GovernanceJobStatus.SUCCEEDED
        )
        await repository.complete_attempt(
            claimed=claimed,
            attempt_id=attempt_id,
            result=attempt_result,
            stage=str(state.get("stage", "terminal")),
            safe_metadata=_safe_state_metadata(state),
        )
        completed = await repository.complete_job(
            claimed=claimed,
            completion=GovernanceJobCompletion(
                status=job_status,
                outcome=(
                    "review_required" if review_required else str(assignment_outcome or "governed")
                ),
                safe_metadata=_safe_state_metadata(state),
            ),
        )
        if not completed:
            _log_lease_lost(claimed)
            return
        logger.info(
            "governance_job_completed",
            governance_job_id=str(claimed.job_id),
            governance_run_id=str(claimed.run_id),
            candidate_id=str(claimed.candidate_id),
            result=job_status.value,
        )
    except GovernanceLeaseLostError:
        _log_lease_lost(claimed)
    except AppError as error:
        try:
            await _complete_failed_job(
                claimed=claimed,
                attempt_id=attempt_id,
                error=error,
                repository=repository,
                settings=settings,
            )
        except GovernanceLeaseLostError:
            _log_lease_lost(claimed)
    except Exception:
        try:
            await _complete_internal_failure(
                claimed=claimed,
                attempt_id=attempt_id,
                repository=repository,
                settings=settings,
            )
        except GovernanceLeaseLostError:
            _log_lease_lost(claimed)
    finally:
        heartbeat_stop.set()
        await _finish_heartbeat_task(heartbeat_task, claimed=claimed)


async def _finish_heartbeat_task(
    task: asyncio.Task[None], *, claimed: ClaimedGovernanceJob
) -> None:
    try:
        await task
    except Exception:
        logger.error(
            "governance_heartbeat_task_failed",
            governance_job_id=str(claimed.job_id),
            governance_run_id=str(claimed.run_id),
            error_code="governance_heartbeat_failed",
        )


async def _heartbeat_loop(
    *,
    claimed: ClaimedGovernanceJob,
    repository: GovernanceRepository,
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.governance_heartbeat_seconds)
        except TimeoutError:
            if not await repository.heartbeat(
                claimed=claimed,
                lease_seconds=settings.governance_lease_seconds,
            ):
                logger.warning(
                    "governance_heartbeat_lost",
                    governance_job_id=str(claimed.job_id),
                )
                return


async def _complete_failed_job(
    *,
    claimed: ClaimedGovernanceJob,
    attempt_id: UUID,
    error: AppError,
    repository: GovernanceRepository,
    settings: Settings,
) -> None:
    if isinstance(error, _REVIEWABLE_ERRORS):
        attempt_result = GovernanceAttemptResult.REVIEW_REQUIRED
        status = GovernanceJobStatus.REVIEW_REQUIRED
        retry_at = None
    elif error.retryable and claimed.attempt_number < settings.governance_max_attempts:
        attempt_result = GovernanceAttemptResult.RETRY_SCHEDULED
        status = GovernanceJobStatus.RETRY_SCHEDULED
        retry_at = _retry_at(claimed.attempt_number, settings)
    else:
        attempt_result = GovernanceAttemptResult.FAILED
        status = GovernanceJobStatus.FAILED
        retry_at = None
    await repository.complete_attempt(
        claimed=claimed,
        attempt_id=attempt_id,
        result=attempt_result,
        stage="failed",
        error_code=error.code,
        safe_metadata={"error_code": error.code},
    )
    completed = await repository.complete_job(
        claimed=claimed,
        completion=GovernanceJobCompletion(
            status=status,
            outcome=status.value,
            error_code=error.code,
            retry_at=retry_at,
            safe_metadata={"error_code": error.code},
        ),
    )
    if not completed:
        _log_lease_lost(claimed)
        return
    logger.warning(
        "governance_job_failed",
        governance_job_id=str(claimed.job_id),
        governance_run_id=str(claimed.run_id),
        candidate_id=str(claimed.candidate_id),
        error_code=error.code,
        retryable=status is GovernanceJobStatus.RETRY_SCHEDULED,
    )


def _log_lease_lost(claimed: ClaimedGovernanceJob) -> None:
    logger.warning(
        "governance_job_lease_lost",
        governance_job_id=str(claimed.job_id),
        governance_run_id=str(claimed.run_id),
        candidate_id=str(claimed.candidate_id),
    )


async def _complete_internal_failure(
    *,
    claimed: ClaimedGovernanceJob,
    attempt_id: UUID,
    repository: GovernanceRepository,
    settings: Settings,
) -> None:
    from app.core.errors import AppError

    await _complete_failed_job(
        claimed=claimed,
        attempt_id=attempt_id,
        error=AppError(
            code="governance_internal_error",
            message="governance processing failed",
            status_code=500,
            retryable=claimed.attempt_number < settings.governance_max_attempts,
        ),
        repository=repository,
        settings=settings,
    )


def _retry_at(attempt_number: int, settings: Settings) -> datetime:
    delay = min(
        settings.governance_retry_base_seconds * (2 ** max(0, attempt_number - 1)),
        3_600,
    )
    return datetime.now(UTC) + timedelta(seconds=delay)


def _safe_state_metadata(state: Mapping[str, object]) -> dict[str, object]:
    source_diversity = state.get("source_diversity", 0)
    safe: dict[str, object] = {
        "graph_stage": str(state.get("stage", "terminal")),
        "source_count": source_diversity if isinstance(source_diversity, int) else 0,
    }
    for state_key, metadata_key in (
        ("event_id", "event_id"),
        ("event_version_id", "event_version_id"),
        ("assignment_decision_id", "assignment_decision_id"),
        ("assignment_outcome", "assignment_status"),
    ):
        value = state.get(state_key)
        if value is not None:
            safe[metadata_key] = str(value)
    return safe
