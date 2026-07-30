from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.application.services.governance_analysis import FactualAnalysisCoordinator
from app.application.services.governance_graph import build_governance_graph
from app.application.services.governance_runtime import build_governance_version_bundle
from app.application.services.governance_worker import (
    SystemClock,
    execute_claimed_governance_job,
)
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.domain.event_assignment import EventAssignmentPolicy
from app.domain.governance_semantic import SemanticDuplicatePolicy
from app.domain.value_objects import stable_key
from app.infrastructure.ai.factory import governance_models
from app.infrastructure.db.governance_artifacts import PostgresGovernanceArtifactRepository
from app.infrastructure.db.governance_checkpointer import PostgresGovernanceCheckpointer
from app.infrastructure.db.governance_queries import get_governance_run_with_usage
from app.infrastructure.db.governance_repositories import PostgresGovernanceRepository
from app.infrastructure.db.models import (
    AnalysisFactModel,
    ArticleOccurrenceModel,
    CandidateAnalysisModel,
    EventAssignmentDecisionModel,
    GovernanceJobModel,
    ModelInvocationModel,
    NormalizedPassageModel,
)
from app.infrastructure.db.session import create_engine, create_session_factory


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one explicit stored candidate through the Zhipu governance workflow."
    )
    parser.add_argument("--candidate-id", required=True, type=UUID)
    return parser.parse_args()


def _validate_live_settings(settings: Settings) -> None:
    if settings.ai_provider_mode != "zhipu":
        raise SystemExit("Governance live smoke requires AI_PROVIDER_MODE=zhipu")
    if (
        settings.ai_platform_api_key is None
        or not settings.ai_platform_api_key.get_secret_value().strip()
    ):
        raise SystemExit("Governance live smoke requires AI_PLATFORM_API_KEY in local secrets")
    if not settings.governance_enabled:
        raise SystemExit("Governance live smoke requires GOVERNANCE_ENABLED=true")


async def run_live_smoke(candidate_id: UUID, settings: Settings) -> dict[str, Any]:
    _validate_live_settings(settings)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    repository = PostgresGovernanceRepository(session_factory)
    artifact_repository = PostgresGovernanceArtifactRepository(session_factory)
    checkpointer = PostgresGovernanceCheckpointer(settings.governance_checkpoint_database_url)
    bundle = build_governance_version_bundle(settings)
    idempotency_key = stable_key("governance-live-smoke", candidate_id, bundle.fingerprint)
    try:
        run_id = await repository.create_manual_run(
            candidate_ids=(candidate_id,),
            idempotency_key=idempotency_key,
            bundle=bundle,
            timezone=settings.business_timezone,
        )
        claimed = await repository.claim_for_run(
            run_id=run_id,
            worker_id="governance-live-smoke",
            lease_seconds=settings.governance_lease_seconds,
        )
        if claimed is not None:
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
                    await execute_claimed_governance_job(
                        claimed=claimed,
                        repository=repository,
                        checkpointer=checkpointer,
                        graph=graph,
                        settings=settings,
                    )
        async with session_factory() as session:
            run, usage = await get_governance_run_with_usage(session, run_id)
            job = await session.scalar(
                select(GovernanceJobModel).where(GovernanceJobModel.run_id == run_id)
            )
            if job is None:
                raise RuntimeError("live smoke run has no job")
            invocation_rows = tuple(
                (
                    await session.execute(
                        select(
                            ModelInvocationModel.capability,
                            ModelInvocationModel.provider,
                            ModelInvocationModel.model,
                            ModelInvocationModel.status,
                            ModelInvocationModel.prompt_tokens,
                            ModelInvocationModel.completion_tokens,
                            ModelInvocationModel.reasoning_tokens,
                            ModelInvocationModel.latency_ms,
                        )
                        .where(ModelInvocationModel.governance_job_id == job.id)
                        .order_by(ModelInvocationModel.capability, ModelInvocationModel.id)
                    )
                ).tuples()
            )
            decision = await session.scalar(
                select(EventAssignmentDecisionModel)
                .where(EventAssignmentDecisionModel.governance_run_id == run_id)
                .order_by(EventAssignmentDecisionModel.created_at.desc())
                .limit(1)
            )
            analysis_count = await session.scalar(
                select(func.count(CandidateAnalysisModel.id)).where(
                    CandidateAnalysisModel.candidate_id == candidate_id
                )
            )
            fact_count = await session.scalar(
                select(func.count(AnalysisFactModel.id))
                .join(
                    CandidateAnalysisModel,
                    CandidateAnalysisModel.id == AnalysisFactModel.analysis_id,
                )
                .where(CandidateAnalysisModel.candidate_id == candidate_id)
            )
            passage_count = await session.scalar(
                select(func.count(NormalizedPassageModel.id)).where(
                    NormalizedPassageModel.candidate_id == candidate_id
                )
            )
            occurrence_count = await session.scalar(
                select(func.count(ArticleOccurrenceModel.id)).where(
                    ArticleOccurrenceModel.candidate_id == candidate_id
                )
            )
        return {
            "run_id": str(run_id),
            "job_id": str(job.id),
            "candidate_id": str(candidate_id),
            "run_status": run.status,
            "job_status": job.status,
            "job_outcome": job.outcome,
            "error_code": job.error_code,
            "pipeline_version": bundle.pipeline_version,
            "version_bundle_fingerprint": bundle.fingerprint,
            "chat_model": settings.ai_chat_model,
            "embedding_model": settings.ai_embedding_model,
            "embedding_dimensions": settings.ai_embedding_dimensions,
            "analysis_count": int(analysis_count or 0),
            "fact_count": int(fact_count or 0),
            "passage_count": int(passage_count or 0),
            "source_occurrence_count": int(occurrence_count or 0),
            "event_assignment_outcome": decision.outcome if decision is not None else None,
            "event_id": str(decision.selected_event_id)
            if decision and decision.selected_event_id
            else None,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
            "latency_ms": usage.latency_ms,
            "invocations": [
                {
                    "capability": capability,
                    "provider": provider,
                    "model": model,
                    "status": status,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "reasoning_tokens": reasoning_tokens,
                    "latency_ms": latency_ms,
                }
                for (
                    capability,
                    provider,
                    model,
                    status,
                    prompt_tokens,
                    completion_tokens,
                    reasoning_tokens,
                    latency_ms,
                ) in invocation_rows
            ],
        }
    finally:
        await engine.dispose()


async def _main() -> None:
    args = _parse_args()
    try:
        settings = get_settings()
        configure_logging(json_output=settings.app_env != "development")
        result = await run_live_smoke(args.candidate_id, settings)
    except AppError as error:
        raise SystemExit(f"Governance live smoke failed: {error.code}") from None
    except SystemExit:
        raise
    except Exception:
        raise SystemExit("Governance live smoke failed: internal_error") from None
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["job_status"] not in {"succeeded", "review_required"}:
        raise SystemExit("Governance live smoke did not reach an accepted terminal state")


if __name__ == "__main__":
    asyncio.run(_main())
