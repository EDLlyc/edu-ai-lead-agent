from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.application.services.governance_analysis import FactualAnalysisCoordinator
from app.application.services.governance_graph import (
    build_governance_graph,
    governance_graph_input,
    governance_graph_resume_claim,
    governance_thread_id,
)
from app.application.services.governance_runtime import build_governance_version_bundle
from app.core.errors import GovernanceLeaseLostError
from app.domain.event_assignment import EventAssignmentPolicy
from app.domain.governance_enums import EmbeddingPurpose, FactualCategory
from app.domain.governance_normalization import normalize_and_segment
from app.domain.governance_semantic import SemanticDuplicatePolicy
from app.infrastructure.db import governance_artifacts
from app.infrastructure.db.governance_artifacts import PostgresGovernanceArtifactRepository
from app.infrastructure.db.governance_checkpointer import PostgresGovernanceCheckpointer
from app.infrastructure.db.governance_repositories import (
    PostgresGovernanceRepository,
    claim_governance_job,
    create_governance_run_for_acquisition,
)
from app.infrastructure.db.models import (
    ArticleEmbeddingModel,
    CandidateAnalysisModel,
    EventAssignmentDecisionModel,
    EventClusterVersionModel,
    EventMembershipModel,
    EvidenceCandidateModel,
    GovernanceJobModel,
    ModelInvocationModel,
    NormalizedArticleModel,
)
from langchain_core.runnables import RunnableConfig
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from .conftest import IntegrationContext
from .governance_graph_support import (
    FakeEmbeddingModel,
    FakeFactualAnalysisModel,
    FixedClock,
)
from .test_governance_repositories import _create_acquisition_fixture


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_postgres_checkpoint_resume_and_replay_do_not_repeat_provider_work(
    integration_context: IntegrationContext,
) -> None:
    acquisition_run_id, candidate_ids = await _create_acquisition_fixture(
        integration_context, candidate_count=1
    )
    bundle = build_governance_version_bundle(integration_context.settings)
    async with integration_context.session_factory() as session:
        await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=acquisition_run_id,
            bundle=bundle,
            timezone="Asia/Shanghai",
        )
    async with integration_context.session_factory() as session:
        claimed = await claim_governance_job(
            session, worker_id="governance-graph-resume", lease_seconds=300
        )
    assert claimed is not None

    analysis_model = FakeFactualAnalysisModel(
        category=FactualCategory.AI_EDUCATION_POLICY,
        entity_name="教育部",
    )
    embedding_model = FakeEmbeddingModel()
    governance_repository = PostgresGovernanceRepository(integration_context.session_factory)
    artifact_repository = PostgresGovernanceArtifactRepository(integration_context.session_factory)
    psycopg_url = make_url(integration_context.settings.database_url.get_secret_value()).set(
        drivername="postgresql"
    )
    checkpointer = PostgresGovernanceCheckpointer(
        SecretStr(psycopg_url.render_as_string(hide_password=False))
    )
    thread_id = governance_thread_id(claimed.job_id)
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    async with checkpointer.saver() as saver:
        graph = build_governance_graph(
            governance_repository=governance_repository,
            artifact_repository=artifact_repository,
            analysis_coordinator=FactualAnalysisCoordinator(
                analysis_model, max_validation_corrections=0
            ),
            embedding_model=embedding_model,
            clock=FixedClock(datetime.now(UTC)),
            semantic_policy=SemanticDuplicatePolicy(version="semantic-v1"),
            event_policy=EventAssignmentPolicy(version=bundle.event_assignment_version),
            analysis_max_output_tokens=1024,
            checkpointer=saver,
            interrupt_after=["structured_factual_analysis"],
        )
        interrupted = await graph.ainvoke(governance_graph_input(claimed), config)
        snapshot = await graph.aget_state(config)

        assert interrupted["stage"] == "analysis-persisted"
        assert len(analysis_model.calls) == 1
        assert embedding_model.calls == []
        assert "vector" not in snapshot.values
        async with integration_context.session_factory() as session:
            candidate_text = await session.scalar(
                select(EvidenceCandidateModel.clean_text).where(
                    EvidenceCandidateModel.id == candidate_ids[0]
                )
            )
            interrupted_stage = await session.scalar(
                select(GovernanceJobModel.current_stage).where(
                    GovernanceJobModel.id == claimed.job_id
                )
            )
        assert candidate_text is not None
        assert candidate_text not in repr(snapshot.values)
        assert interrupted_stage == "structured_factual_analysis"

        async with integration_context.session_factory() as session:
            job = await session.get(GovernanceJobModel, claimed.job_id)
            assert job is not None
            job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        async with integration_context.session_factory() as session:
            reclaimed = await claim_governance_job(
                session,
                worker_id="governance-graph-recovery",
                lease_seconds=300,
            )
        assert reclaimed is not None
        assert reclaimed.job_id == claimed.job_id
        assert reclaimed.lease_token != claimed.lease_token
        assert reclaimed.attempt_number == claimed.attempt_number + 1

        await graph.aupdate_state(config, governance_graph_resume_claim(reclaimed))
        resumed = await graph.ainvoke(None, config)
        assert resumed["stage"] == "terminal"
        assert resumed["lease_token"] == reclaimed.lease_token
        assert resumed["attempt_number"] == reclaimed.attempt_number
        assert len(analysis_model.calls) == 1
        assert [request.purpose for request in embedding_model.calls] == [
            EmbeddingPurpose.NEAR_DUPLICATE,
            EmbeddingPurpose.EVENT_ASSIGNMENT,
        ]

        replay_config: RunnableConfig = {"configurable": {"thread_id": f"{thread_id}:replay"}}
        replay_interrupted = await graph.ainvoke(governance_graph_input(reclaimed), replay_config)
        replayed = await graph.ainvoke(None, replay_config)
        assert replay_interrupted["stage"] == "analysis-persisted"
        assert replayed["stage"] == "terminal"

        async with integration_context.session_factory() as session:
            terminal_stage = await session.scalar(
                select(GovernanceJobModel.current_stage).where(
                    GovernanceJobModel.id == claimed.job_id
                )
            )
        assert terminal_stage == "persist_terminal_projection"

    assert await checkpointer.checkpoint_exists(thread_id=thread_id) is True
    assert len(analysis_model.calls) == 1
    assert len(embedding_model.calls) == 2

    async with integration_context.engine.connect() as connection:
        checkpoint_rows = (
            await connection.execute(
                text(
                    "SELECT checkpoint::text, metadata::text FROM checkpoints "
                    "WHERE thread_id IN (:thread_id, :replay_thread_id)"
                ),
                {"thread_id": thread_id, "replay_thread_id": f"{thread_id}:replay"},
            )
        ).all()
        blob_rows = (
            await connection.execute(
                text(
                    "SELECT blob FROM checkpoint_blobs "
                    "WHERE thread_id IN (:thread_id, :replay_thread_id) AND blob IS NOT NULL "
                    "UNION ALL "
                    "SELECT blob FROM checkpoint_writes "
                    "WHERE thread_id IN (:thread_id, :replay_thread_id)"
                ),
                {"thread_id": thread_id, "replay_thread_id": f"{thread_id}:replay"},
            )
        ).scalars()
        serialized_checkpoint_bytes = (
            b"".join(value if isinstance(value, bytes) else bytes(value) for value in blob_rows)
            + "".join(value for row in checkpoint_rows for value in row).encode()
        )

    assert checkpoint_rows
    assert candidate_text.encode() not in serialized_checkpoint_bytes
    assert b"local-contract-secret" not in serialized_checkpoint_bytes

    async with integration_context.session_factory() as session:
        article_ids = tuple(
            (
                await session.scalars(
                    select(NormalizedArticleModel.id).where(
                        NormalizedArticleModel.candidate_id == candidate_ids[0]
                    )
                )
            ).all()
        )
        event_ids = tuple(
            (
                await session.scalars(
                    select(EventMembershipModel.event_id).where(
                        EventMembershipModel.normalized_article_id.in_(article_ids)
                    )
                )
            ).all()
        )
        counts = {
            "analyses": await session.scalar(
                select(func.count())
                .select_from(CandidateAnalysisModel)
                .where(CandidateAnalysisModel.normalized_article_id.in_(article_ids))
            ),
            "embeddings": await session.scalar(
                select(func.count())
                .select_from(ArticleEmbeddingModel)
                .where(ArticleEmbeddingModel.normalized_article_id.in_(article_ids))
            ),
            "invocations": await session.scalar(
                select(func.count())
                .select_from(ModelInvocationModel)
                .where(ModelInvocationModel.governance_job_id == claimed.job_id)
            ),
            "decisions": await session.scalar(
                select(func.count())
                .select_from(EventAssignmentDecisionModel)
                .where(EventAssignmentDecisionModel.normalized_article_id.in_(article_ids))
            ),
            "memberships": await session.scalar(
                select(func.count())
                .select_from(EventMembershipModel)
                .where(EventMembershipModel.normalized_article_id.in_(article_ids))
            ),
            "versions": await session.scalar(
                select(func.count())
                .select_from(EventClusterVersionModel)
                .where(EventClusterVersionModel.event_id.in_(event_ids))
            ),
        }

    assert counts == {
        "analyses": 1,
        "embeddings": 2,
        "invocations": 3,
        "decisions": 1,
        "memberships": 1,
        "versions": 1,
    }


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_stale_artifact_worker_is_fenced_before_commit(
    integration_context: IntegrationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acquisition_run_id, candidate_ids = await _create_acquisition_fixture(
        integration_context, candidate_count=1
    )
    bundle = build_governance_version_bundle(integration_context.settings)
    async with integration_context.session_factory() as session:
        await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=acquisition_run_id,
            bundle=bundle,
            timezone="Asia/Shanghai",
        )
    async with integration_context.session_factory() as session:
        claimed = await claim_governance_job(
            session, worker_id="stale-artifact-worker", lease_seconds=300
        )
        candidate = await session.get(EvidenceCandidateModel, candidate_ids[0])
    assert claimed is not None and candidate is not None
    document = normalize_and_segment(
        candidate_id=candidate.id,
        source_text=candidate.clean_text,
        normalization_version=bundle.normalization_version,
        passage_schema_version=bundle.passage_schema_version,
        input_content_hash=candidate.content_hash,
    )
    original_assert = governance_artifacts.assert_active_governance_lease
    assertion_count = 0

    async def expire_before_commit(  # type: ignore[no-untyped-def]
        session, current_claim, *, for_update=False
    ):
        nonlocal assertion_count
        assertion_count += 1
        if assertion_count == 1:
            return
        if assertion_count == 2:
            async with integration_context.session_factory() as fencing_session:
                job = await fencing_session.get(GovernanceJobModel, current_claim.job_id)
                assert job is not None
                job.lease_token = uuid4()
                await fencing_session.commit()
        await original_assert(session, current_claim, for_update=for_update)

    monkeypatch.setattr(
        governance_artifacts,
        "assert_active_governance_lease",
        expire_before_commit,
    )
    repository = PostgresGovernanceArtifactRepository(integration_context.session_factory)
    with pytest.raises(GovernanceLeaseLostError):
        await repository.persist_normalized(
            claimed=claimed,
            document=document,
            language=candidate.language,
        )

    async with integration_context.session_factory() as session:
        artifact_count = await session.scalar(
            select(func.count())
            .select_from(NormalizedArticleModel)
            .where(NormalizedArticleModel.candidate_id == candidate.id)
        )

    assert assertion_count == 2
    assert artifact_count == 0
