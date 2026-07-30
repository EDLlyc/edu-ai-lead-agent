import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.application.services.governance_analysis import FactualAnalysisCoordinator
from app.application.services.governance_graph import (
    CompiledGovernanceGraph,
    build_governance_graph,
    governance_graph_input,
)
from app.application.services.governance_runtime import build_governance_version_bundle
from app.domain.event_assignment import EventAssignmentPolicy
from app.domain.governance_entities import ClaimedGovernanceJob, GovernanceVersionBundle
from app.domain.governance_enums import EventAssignmentOutcome, FactualCategory
from app.domain.governance_semantic import SemanticDuplicatePolicy
from app.infrastructure.db.governance_artifacts import PostgresGovernanceArtifactRepository
from app.infrastructure.db.governance_repositories import (
    PostgresGovernanceRepository,
    claim_governance_job,
    create_governance_run_for_acquisition,
)
from app.infrastructure.db.models import (
    ArticleEmbeddingModel,
    CandidateAnalysisModel,
    DuplicateRelationModel,
    EventAssignmentDecisionModel,
    EventClusterModel,
    EventClusterVersionModel,
    EventMembershipModel,
    EvidenceCandidateModel,
    GovernanceJobModel,
    NormalizedArticleModel,
)
from sqlalchemy import func, select, update

from .conftest import IntegrationContext
from .governance_graph_support import (
    FakeEmbeddingModel,
    FakeFactualAnalysisModel,
    FixedClock,
)
from .test_governance_repositories import _create_acquisition_fixture


def _build_graph(
    context: IntegrationContext,
    *,
    bundle: GovernanceVersionBundle,
    analysis_model: FakeFactualAnalysisModel,
    embedding_model: FakeEmbeddingModel,
    now: datetime,
) -> CompiledGovernanceGraph:
    return build_governance_graph(
        governance_repository=PostgresGovernanceRepository(context.session_factory),
        artifact_repository=PostgresGovernanceArtifactRepository(context.session_factory),
        analysis_coordinator=FactualAnalysisCoordinator(
            analysis_model, max_validation_corrections=0
        ),
        embedding_model=embedding_model,
        clock=FixedClock(now),
        semantic_policy=SemanticDuplicatePolicy(version="semantic-v1"),
        event_policy=EventAssignmentPolicy(version=bundle.event_assignment_version),
        analysis_max_output_tokens=1024,
    )


async def _claim(context: IntegrationContext, *, worker_id: str) -> ClaimedGovernanceJob:
    async with context.session_factory() as session:
        claimed = await claim_governance_job(
            session,
            worker_id=worker_id,
            lease_seconds=300,
        )
    assert claimed is not None
    return claimed


async def _prioritize_jobs(
    context: IntegrationContext,
    *,
    first_candidate_id: UUID,
    second_candidate_id: UUID,
    now: datetime,
) -> None:
    async with context.session_factory() as session:
        first_job = await session.scalar(
            select(GovernanceJobModel).where(
                GovernanceJobModel.candidate_id == first_candidate_id,
                GovernanceJobModel.status == "queued",
            )
        )
        second_job = await session.scalar(
            select(GovernanceJobModel).where(
                GovernanceJobModel.candidate_id == second_candidate_id,
                GovernanceJobModel.status == "queued",
            )
        )
        assert first_job is not None and second_job is not None
        first_job.available_at = now - timedelta(seconds=2)
        second_job.available_at = now - timedelta(seconds=1)
        await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_exact_copy_reuses_analysis_and_event_with_immutable_source_versions(
    integration_context: IntegrationContext,
) -> None:
    acquisition_run_id, candidate_ids = await _create_acquisition_fixture(
        integration_context, candidate_count=2
    )
    first_candidate_id, second_candidate_id = candidate_ids
    now = datetime.now(UTC)
    exact_text = "教育部发布人工智能课程建设指南, 明确课程目标、教师培训和安全规范。"
    async with integration_context.session_factory() as session:
        first = await session.get(EvidenceCandidateModel, first_candidate_id)
        second = await session.get(EvidenceCandidateModel, second_candidate_id)
        assert first is not None and second is not None
        first.title = second.title = "教育部发布人工智能课程建设指南"
        first.clean_text = second.clean_text = exact_text
        first.published_at = second.published_at = now
        first.first_fetched_at = now
        second.first_fetched_at = now + timedelta(seconds=1)
        await session.commit()

    bundle = build_governance_version_bundle(integration_context.settings)
    async with integration_context.session_factory() as session:
        await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=acquisition_run_id,
            bundle=bundle,
            timezone="Asia/Shanghai",
        )
    await _prioritize_jobs(
        integration_context,
        first_candidate_id=first_candidate_id,
        second_candidate_id=second_candidate_id,
        now=now,
    )

    analysis_model = FakeFactualAnalysisModel(
        category=FactualCategory.LARGE_GENERATIVE_MODELS,
        entity_name="教育部",
    )
    embedding_model = FakeEmbeddingModel()
    graph = _build_graph(
        integration_context,
        bundle=bundle,
        analysis_model=analysis_model,
        embedding_model=embedding_model,
        now=now,
    )
    first_claim = await _claim(integration_context, worker_id="exact-copy-first")
    assert first_claim.candidate_id == first_candidate_id
    second_claim = await _claim(integration_context, worker_id="exact-copy-second")
    assert second_claim.candidate_id == second_candidate_id
    first_result = await graph.ainvoke(governance_graph_input(first_claim))
    second_result = await graph.ainvoke(governance_graph_input(second_claim))
    replay_result = await graph.ainvoke(governance_graph_input(second_claim))

    assert first_result["assignment_outcome"] == EventAssignmentOutcome.CREATED_NEW.value
    assert first_result["source_diversity"] == 2
    assert second_result["stage"] == "terminal"
    assert second_result["assignment_outcome"] == (EventAssignmentOutcome.ASSIGNED_EXISTING.value)
    assert replay_result["event_id"] == second_result["event_id"]
    assert len(analysis_model.calls) == 1
    assert len(embedding_model.calls) == 2

    async with integration_context.session_factory() as session:
        article_ids = tuple(
            (
                await session.scalars(
                    select(NormalizedArticleModel.id).where(
                        NormalizedArticleModel.candidate_id.in_(candidate_ids)
                    )
                )
            ).all()
        )
        event_ids = tuple(
            (
                await session.scalars(
                    select(EventMembershipModel.event_id)
                    .where(EventMembershipModel.normalized_article_id.in_(article_ids))
                    .distinct()
                )
            ).all()
        )
        versions = tuple(
            (
                await session.scalars(
                    select(EventClusterVersionModel)
                    .where(EventClusterVersionModel.event_id.in_(event_ids))
                    .order_by(EventClusterVersionModel.version)
                )
            ).all()
        )
        analysis_count = await session.scalar(
            select(func.count())
            .select_from(CandidateAnalysisModel)
            .where(CandidateAnalysisModel.normalized_article_id.in_(article_ids))
        )
        embedding_count = await session.scalar(
            select(func.count())
            .select_from(ArticleEmbeddingModel)
            .where(ArticleEmbeddingModel.normalized_article_id.in_(article_ids))
        )
        relation_count = await session.scalar(
            select(func.count())
            .select_from(DuplicateRelationModel)
            .where(
                DuplicateRelationModel.left_article_id.in_(article_ids),
                DuplicateRelationModel.right_article_id.in_(article_ids),
            )
        )
        membership_count = await session.scalar(
            select(func.count())
            .select_from(EventMembershipModel)
            .where(EventMembershipModel.normalized_article_id.in_(article_ids))
        )

    assert len(article_ids) == 2
    assert len(event_ids) == 1
    assert analysis_count == 1
    assert embedding_count == 2
    assert relation_count == 1
    assert membership_count == 2
    assert [version.version for version in versions] == [1, 2]
    assert [version.source_diversity for version in versions] == [2, 3]
    assert versions[0].member_set_hash != versions[1].member_set_hash
    assert {version.representative_article_id for version in versions} == {
        versions[0].representative_article_id
    }


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_changed_analysis_and_embedding_versions_create_new_derivations(
    integration_context: IntegrationContext,
) -> None:
    acquisition_run_id, candidate_ids = await _create_acquisition_fixture(
        integration_context, candidate_count=1
    )
    now = datetime.now(UTC)
    candidate_id = candidate_ids[0]
    async with integration_context.session_factory() as session:
        candidate = await session.get(EvidenceCandidateModel, candidate_id)
        assert candidate is not None
        candidate.title = "教育部发布人工智能课程指南"
        candidate.clean_text = "教育部发布人工智能课程指南, 并明确教师培训要求。"
        candidate.published_at = now
        candidate.first_fetched_at = now
        await session.commit()

    base_bundle = build_governance_version_bundle(integration_context.settings)
    base_analysis = FakeFactualAnalysisModel(
        category=FactualCategory.AI_EDUCATION_POLICY,
        entity_name="教育部",
    )
    base_embedding = FakeEmbeddingModel()
    async with integration_context.session_factory() as session:
        await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=acquisition_run_id,
            bundle=base_bundle,
            timezone="Asia/Shanghai",
        )
    base_claim = await _claim(integration_context, worker_id="version-base")
    await _build_graph(
        integration_context,
        bundle=base_bundle,
        analysis_model=base_analysis,
        embedding_model=base_embedding,
        now=now,
    ).ainvoke(governance_graph_input(base_claim))
    assert len(base_analysis.calls) == 1
    assert len(base_embedding.calls) == 2

    prompt_bundle = replace(base_bundle, prompt_version="factual-analysis-v2")
    prompt_analysis = FakeFactualAnalysisModel(
        category=FactualCategory.AI_EDUCATION_POLICY,
        entity_name="教育部",
    )
    prompt_embedding = FakeEmbeddingModel()
    async with integration_context.session_factory() as session:
        await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=acquisition_run_id,
            bundle=prompt_bundle,
            timezone="Asia/Shanghai",
        )
    prompt_claim = await _claim(integration_context, worker_id="version-prompt")
    await _build_graph(
        integration_context,
        bundle=prompt_bundle,
        analysis_model=prompt_analysis,
        embedding_model=prompt_embedding,
        now=now,
    ).ainvoke(governance_graph_input(prompt_claim))
    assert len(prompt_analysis.calls) == 1
    assert prompt_embedding.calls == []

    embedding_bundle = replace(prompt_bundle, embedding_model="embedding-3-v2")
    changed_embedding = FakeEmbeddingModel(model="embedding-3-v2")
    embedding_analysis = FakeFactualAnalysisModel(
        category=FactualCategory.AI_EDUCATION_POLICY,
        entity_name="教育部",
    )
    async with integration_context.session_factory() as session:
        await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=acquisition_run_id,
            bundle=embedding_bundle,
            timezone="Asia/Shanghai",
        )
    embedding_claim = await _claim(integration_context, worker_id="version-embedding")
    await _build_graph(
        integration_context,
        bundle=embedding_bundle,
        analysis_model=embedding_analysis,
        embedding_model=changed_embedding,
        now=now,
    ).ainvoke(governance_graph_input(embedding_claim))
    assert embedding_analysis.calls == []
    assert len(changed_embedding.calls) == 2

    async with integration_context.session_factory() as session:
        article_id = await session.scalar(
            select(NormalizedArticleModel.id).where(
                NormalizedArticleModel.candidate_id == candidate_id
            )
        )
        assert article_id is not None
        analyses = await session.scalar(
            select(func.count())
            .select_from(CandidateAnalysisModel)
            .where(CandidateAnalysisModel.normalized_article_id == article_id)
        )
        embeddings = await session.scalar(
            select(func.count())
            .select_from(ArticleEmbeddingModel)
            .where(ArticleEmbeddingModel.normalized_article_id == article_id)
        )

    assert analyses == 2
    assert embeddings == 4


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_workers_create_one_event_and_serialize_final_assignment(
    integration_context: IntegrationContext,
) -> None:
    acquisition_run_id, candidate_ids = await _create_acquisition_fixture(
        integration_context, candidate_count=2
    )
    now = datetime.now(UTC)
    async with integration_context.session_factory() as session:
        candidates = tuple(
            (
                await session.scalars(
                    select(EvidenceCandidateModel).where(
                        EvidenceCandidateModel.id.in_(candidate_ids)
                    )
                )
            ).all()
        )
        assert len(candidates) == 2
        for index, candidate in enumerate(candidates):
            candidate.title = "某芯片企业发布人工智能算力平台"
            candidate.clean_text = (
                f"某芯片企业发布人工智能算力平台, 公布统一的产品能力和时间表。编号{index}。"
            )
            candidate.published_at = now
            candidate.first_fetched_at = now
        await session.commit()

    bundle = build_governance_version_bundle(integration_context.settings)
    async with integration_context.session_factory() as session:
        await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=acquisition_run_id,
            bundle=bundle,
            timezone="Asia/Shanghai",
        )
    first_claim = await _claim(integration_context, worker_id="concurrent-event-one")
    second_claim = await _claim(integration_context, worker_id="concurrent-event-two")
    assert {first_claim.candidate_id, second_claim.candidate_id} == set(candidate_ids)

    analysis_model = FakeFactualAnalysisModel(
        category=FactualCategory.AI_COMPUTE_CHIPS,
        entity_name="某芯片企业",
    )
    embedding_model = FakeEmbeddingModel()
    graph = _build_graph(
        integration_context,
        bundle=bundle,
        analysis_model=analysis_model,
        embedding_model=embedding_model,
        now=now,
    )
    first_result, second_result = await asyncio.gather(
        graph.ainvoke(governance_graph_input(first_claim)),
        graph.ainvoke(governance_graph_input(second_claim)),
    )

    assert {first_result["assignment_outcome"], second_result["assignment_outcome"]} == {
        EventAssignmentOutcome.CREATED_NEW.value,
        EventAssignmentOutcome.ASSIGNED_EXISTING.value,
    }
    assert first_result["event_id"] == second_result["event_id"]
    assert len(analysis_model.calls) == 2
    assert len(embedding_model.calls) == 4

    async with integration_context.session_factory() as session:
        article_ids = tuple(
            (
                await session.scalars(
                    select(NormalizedArticleModel.id).where(
                        NormalizedArticleModel.candidate_id.in_(candidate_ids)
                    )
                )
            ).all()
        )
        event_ids = tuple(
            (
                await session.scalars(
                    select(EventMembershipModel.event_id)
                    .where(EventMembershipModel.normalized_article_id.in_(article_ids))
                    .distinct()
                )
            ).all()
        )
        membership_count = await session.scalar(
            select(func.count())
            .select_from(EventMembershipModel)
            .where(EventMembershipModel.normalized_article_id.in_(article_ids))
        )
        decision_outcomes = tuple(
            (
                await session.scalars(
                    select(EventAssignmentDecisionModel.outcome).where(
                        EventAssignmentDecisionModel.normalized_article_id.in_(article_ids)
                    )
                )
            ).all()
        )
        version_count = await session.scalar(
            select(func.count())
            .select_from(EventClusterVersionModel)
            .where(EventClusterVersionModel.event_id.in_(event_ids))
        )
        cluster_count = await session.scalar(
            select(func.count())
            .select_from(EventClusterModel)
            .where(EventClusterModel.id.in_(event_ids))
        )

    assert len(article_ids) == 2
    assert len(event_ids) == 1
    assert membership_count == 2
    assert cluster_count == 1
    assert version_count == 2
    assert set(decision_outcomes) == {
        EventAssignmentOutcome.CREATED_NEW.value,
        EventAssignmentOutcome.ASSIGNED_EXISTING.value,
    }

    async with integration_context.session_factory() as session:
        versions = tuple(
            (
                await session.scalars(
                    select(EventClusterVersionModel)
                    .where(EventClusterVersionModel.event_id == event_ids[0])
                    .order_by(EventClusterVersionModel.version)
                )
            ).all()
        )
        assert len(versions) == 2
        representative_id = versions[-1].representative_article_id
        assert {version.representative_article_id for version in versions} == {representative_id}
        orthogonal_vector = [0.0, 1.0] + [0.0] * 2046
        representative_vector = [1.0, 0.0] + [0.0] * 2046
        await session.execute(
            update(ArticleEmbeddingModel)
            .where(
                ArticleEmbeddingModel.normalized_article_id == representative_id,
                ArticleEmbeddingModel.purpose == "event_assignment",
            )
            .values(vector=representative_vector)
        )
        await session.execute(
            update(ArticleEmbeddingModel)
            .where(
                ArticleEmbeddingModel.normalized_article_id.in_(
                    tuple(
                        article_id for article_id in article_ids if article_id != representative_id
                    )
                ),
                ArticleEmbeddingModel.purpose == "event_assignment",
            )
            .values(vector=orthogonal_vector)
        )
        await session.commit()

    third_acquisition_run_id, third_candidate_ids = await _create_acquisition_fixture(
        integration_context, candidate_count=1
    )
    third_candidate_id = third_candidate_ids[0]
    async with integration_context.session_factory() as session:
        third_candidate = await session.get(EvidenceCandidateModel, third_candidate_id)
        assert third_candidate is not None
        third_candidate.title = "某芯片企业发布人工智能算力平台"
        third_candidate.clean_text = "某芯片企业发布同一人工智能算力平台的新进展。"
        third_candidate.published_at = now
        third_candidate.first_fetched_at = now
        await session.commit()
        await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=third_acquisition_run_id,
            bundle=bundle,
            timezone="Asia/Shanghai",
        )
    third_claim = await _claim(integration_context, worker_id="stable-representative-third")
    third_result = await _build_graph(
        integration_context,
        bundle=bundle,
        analysis_model=FakeFactualAnalysisModel(
            category=FactualCategory.AI_COMPUTE_CHIPS,
            entity_name="某芯片企业",
        ),
        embedding_model=FakeEmbeddingModel(vector=tuple(orthogonal_vector)),
        now=now,
    ).ainvoke(governance_graph_input(third_claim))

    assert third_result["assignment_outcome"] == EventAssignmentOutcome.CREATED_NEW.value
    assert third_result["event_id"] != event_ids[0]
