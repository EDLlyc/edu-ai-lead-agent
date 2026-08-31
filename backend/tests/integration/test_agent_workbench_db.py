from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from app.application.services.agent_tools import build_agent_tool_registry
from app.application.services.governance_analysis import FactualAnalysisCoordinator
from app.application.services.governance_graph import build_governance_graph
from app.application.services.governance_runtime import build_governance_version_bundle
from app.application.services.governance_worker import SystemClock, execute_claimed_governance_job
from app.domain.event_assignment import EventAssignmentPolicy
from app.domain.governance_semantic import SemanticDuplicatePolicy
from app.infrastructure.ai.brand import GovernanceEmbeddingBrandAdapter
from app.infrastructure.ai.fake import (
    DeterministicFakeEmbeddingModel,
    DeterministicFakeFactualAnalysisModel,
)
from app.infrastructure.db.agent_workbench import (
    PostgresAgentKnowledgeReader,
    _mark_transaction_read_only,
)
from app.infrastructure.db.governance_artifacts import PostgresGovernanceArtifactRepository
from app.infrastructure.db.governance_checkpointer import PostgresGovernanceCheckpointer
from app.infrastructure.db.governance_queries import get_event_detail
from app.infrastructure.db.governance_repositories import PostgresGovernanceRepository
from app.infrastructure.db.models import (
    ArticleOccurrenceModel,
    BrandDocumentModel,
    CopyGenerationRunModel,
    EventClusterModel,
    EventClusterVersionModel,
    EventMembershipModel,
    EvidenceBindingModel,
    EvidenceCandidateModel,
    NormalizedArticleModel,
)
from app.schemas.agent_workbench import GetEventResult, SearchEvidenceResult
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from .conftest import IntegrationContext
from .test_governance_repositories import _create_acquisition_fixture


async def _durable_counts(context: IntegrationContext) -> tuple[int, ...]:
    models = (
        EvidenceCandidateModel,
        EvidenceBindingModel,
        EventClusterModel,
        EventClusterVersionModel,
        EventMembershipModel,
        BrandDocumentModel,
        CopyGenerationRunModel,
    )
    async with context.session_factory() as session:
        counts: list[int] = []
        for model in models:
            count = await session.scalar(select(func.count()).select_from(model))
            counts.append(int(count or 0))
        return tuple(counts)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_postgres_workbench_reader_is_governed_read_only_and_session_bounded(
    integration_context: IntegrationContext,
) -> None:
    acquisition_run_id, candidate_ids = await _create_acquisition_fixture(
        integration_context,
        candidate_count=1,
    )
    async with integration_context.session_factory() as session:
        candidate = await session.get(EvidenceCandidateModel, candidate_ids[0])
        assert candidate is not None
        historical_time = datetime(2000, 1, 1, tzinfo=UTC)
        candidate.title = "Artificial intelligence governance evidence"
        candidate.clean_text = (
            "Artificial intelligence governance evidence is stored for offline verification."
        )
        candidate.original_url = "https://example.edu.cn/agent-workbench/source"
        candidate.canonical_url = "https://example.edu.cn/agent-workbench/source"
        candidate.published_at = historical_time
        candidate.first_fetched_at = historical_time
        await session.commit()

    settings = integration_context.settings.model_copy(
        update={
            "governance_enabled": True,
            "ai_provider_mode": "fake",
            "ai_embedding_model": "agent-workbench-integration-embedding-v1",
        }
    )
    governance_repository = PostgresGovernanceRepository(integration_context.session_factory)
    run_id = await governance_repository.create_run_for_acquisition(
        acquisition_run_id=acquisition_run_id,
        bundle=build_governance_version_bundle(settings),
        timezone=settings.business_timezone,
    )
    analysis_model = DeterministicFakeFactualAnalysisModel(model=settings.ai_chat_model)
    embedding_model = DeterministicFakeEmbeddingModel(
        model=settings.ai_embedding_model,
        dimensions=settings.ai_embedding_dimensions,
    )
    psycopg_url = make_url(settings.database_url.get_secret_value()).set(drivername="postgresql")
    checkpointer = PostgresGovernanceCheckpointer(
        SecretStr(psycopg_url.render_as_string(hide_password=False))
    )
    async with checkpointer.saver() as saver:
        graph = build_governance_graph(
            governance_repository=governance_repository,
            artifact_repository=PostgresGovernanceArtifactRepository(
                integration_context.session_factory
            ),
            analysis_coordinator=FactualAnalysisCoordinator(
                analysis_model,
                max_validation_corrections=0,
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
        claimed = await governance_repository.claim_for_run(
            run_id=run_id,
            worker_id="agent-workbench-integration",
            lease_seconds=settings.governance_lease_seconds,
        )
        assert claimed is not None
        await execute_claimed_governance_job(
            claimed=claimed,
            repository=governance_repository,
            checkpointer=checkpointer,
            graph=graph,
            settings=settings,
        )

    async with integration_context.session_factory() as session:
        current_membership = await session.scalar(
            select(EventMembershipModel)
            .join(
                NormalizedArticleModel,
                NormalizedArticleModel.id == EventMembershipModel.normalized_article_id,
            )
            .where(NormalizedArticleModel.candidate_id == candidate_ids[0])
        )
        assert current_membership is not None
        occurrences = tuple(
            (
                await session.scalars(
                    select(ArticleOccurrenceModel).where(
                        ArticleOccurrenceModel.candidate_id == candidate_ids[0]
                    )
                )
            ).all()
        )
        assert occurrences
        for occurrence in occurrences:
            occurrence.final_url = f"https://example.edu.cn/agent-workbench/{occurrence.id}"
        session.add(
            EventMembershipModel(
                id=uuid4(),
                event_id=current_membership.event_id,
                normalized_article_id=current_membership.normalized_article_id,
                assignment_decision_id=current_membership.assignment_decision_id,
                policy_version="agent-workbench-wrong-membership-policy-v1",
                active=True,
                superseded_at=None,
                created_at=current_membership.created_at,
            )
        )
        await session.commit()
        shared_detail = await get_event_detail(
            session,
            current_membership.event_id,
            include_history=False,
            include_member_content=False,
        )

    # The shared event projection retains every active membership represented by the current
    # event aggregate, regardless of the policy version that originally attached it. The
    # workbench adapter below locally de-duplicates the same candidate for its bounded overview.
    assert len(shared_detail.members) == 2

    before_counts = await _durable_counts(integration_context)
    before_checked_out = integration_context.engine.sync_engine.pool.checkedout()
    reader = PostgresAgentKnowledgeReader(
        integration_context.session_factory,
        brand_embeddings=GovernanceEmbeddingBrandAdapter(embedding_model),
        brand_retrieval_version="brand-hybrid-rrf-v3-parent-diverse",
    )
    raw_evidence = await reader.search_evidence(
        query="artificial intelligence governance",
        limit=3,
        candidate_id=None,
    )
    assert raw_evidence
    assert len({record.evidence.evidence_id for record in raw_evidence}) == len(raw_evidence)
    registry = build_agent_tool_registry(reader)
    evidence = cast(
        SearchEvidenceResult,
        await registry.invoke(
            "search_evidence",
            {
                "query": "artificial intelligence governance",
                "limit": 3,
                "candidate_id": None,
            },
        ),
    )
    assert evidence.items
    assert all(item.source_tier in {"A", "B"} for item in evidence.items)
    assert all(item.evidence_eligible for item in evidence.items)

    event = cast(
        GetEventResult,
        await registry.invoke(
            "get_event",
            {"event_id": str(evidence.items[0].event_id)},
        ),
    )
    assert event.event_id == evidence.items[0].event_id
    assert len(event.members) == 1
    assert sum(len(member.source_ids) for member in event.members) <= 8

    async with integration_context.session_factory() as session:
        await _mark_transaction_read_only(session)
        assert await session.scalar(select(func.current_setting("transaction_read_only"))) == "on"
        with pytest.raises(DBAPIError):
            await session.execute(
                update(EventClusterModel)
                .where(EventClusterModel.id == event.event_id)
                .values(updated_at=EventClusterModel.updated_at)
            )
        await session.rollback()

    assert await _durable_counts(integration_context) == before_counts
    assert integration_context.engine.sync_engine.pool.checkedout() == before_checked_out
