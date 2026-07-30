from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.api_main import app
from app.application.services.governance_analysis import FactualAnalysisCoordinator
from app.application.services.governance_graph import build_governance_graph
from app.application.services.governance_worker import (
    SystemClock,
    execute_claimed_governance_job,
)
from app.domain.event_assignment import EventAssignmentPolicy
from app.domain.governance_semantic import SemanticDuplicatePolicy
from app.infrastructure.ai.fake import (
    DeterministicFakeEmbeddingModel,
    DeterministicFakeFactualAnalysisModel,
)
from app.infrastructure.db.governance_artifacts import PostgresGovernanceArtifactRepository
from app.infrastructure.db.governance_checkpointer import PostgresGovernanceCheckpointer
from app.infrastructure.db.governance_repositories import PostgresGovernanceRepository
from app.infrastructure.db.models import EvidenceCandidateModel
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from .conftest import IntegrationContext
from .test_governance_repositories import _create_acquisition_fixture


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_terminal_acquisition_to_governance_event_api_is_resumable_and_idempotent(
    integration_context: IntegrationContext,
) -> None:
    acquisition_run_id, candidate_ids = await _create_acquisition_fixture(
        integration_context, candidate_count=2
    )
    now = datetime.now(UTC)
    ordered_candidate_ids = sorted(candidate_ids, key=lambda value: value.int)
    async with integration_context.session_factory() as session:
        candidates: dict[UUID, EvidenceCandidateModel] = {}
        for candidate_id in candidate_ids:
            candidate = await session.get(EvidenceCandidateModel, candidate_id)
            assert candidate is not None
            candidates[candidate_id] = candidate
        for index, candidate_id in enumerate(ordered_candidate_ids):
            candidate = candidates[candidate_id]
            candidate.title = "人工智能治理平台发布权威进展"
            candidate.clean_text = "人工智能治理平台发布权威进展, 并公布可核验的实施安排。"
            candidate.published_at = now
            candidate.first_fetched_at = now + timedelta(seconds=index)
        await session.commit()

    psycopg_url = make_url(integration_context.settings.database_url.get_secret_value()).set(
        drivername="postgresql"
    )
    settings = integration_context.settings.model_copy(
        update={
            "governance_enabled": True,
            "ai_provider_mode": "fake",
            "governance_checkpoint_database_url": SecretStr(
                psycopg_url.render_as_string(hide_password=False)
            ),
        }
    )
    app.state.settings = settings
    app.state.session_factory = integration_context.session_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/governance-runs",
            json={"acquisition_run_id": str(acquisition_run_id)},
        )
        assert created.status_code == 202
        run_id = UUID(created.json()["id"])
        assert created.headers["location"] == f"/api/v1/governance-runs/{run_id}"

        jobs_page = await client.get(f"/api/v1/governance-runs/{run_id}/jobs", params={"limit": 1})
        assert jobs_page.status_code == 200
        assert len(jobs_page.json()["items"]) == 1
        assert jobs_page.json()["next_cursor"] is not None
        next_jobs_page = await client.get(
            f"/api/v1/governance-runs/{run_id}/jobs",
            params={"limit": 1, "cursor": jobs_page.json()["next_cursor"]},
        )
        assert len(next_jobs_page.json()["items"]) == 1

    repository = PostgresGovernanceRepository(integration_context.session_factory)
    artifact_repository = PostgresGovernanceArtifactRepository(integration_context.session_factory)
    checkpointer = PostgresGovernanceCheckpointer(settings.governance_checkpoint_database_url)
    analysis_model = DeterministicFakeFactualAnalysisModel(model=settings.ai_chat_model)
    embedding_model = DeterministicFakeEmbeddingModel(model=settings.ai_embedding_model)
    async with checkpointer.saver() as saver:
        graph = build_governance_graph(
            governance_repository=repository,
            artifact_repository=artifact_repository,
            analysis_coordinator=FactualAnalysisCoordinator(
                analysis_model, max_validation_corrections=0
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
        for index in range(2):
            claimed = await repository.claim_for_run(
                run_id=run_id,
                worker_id=f"governance-api-e2e-{index}",
                lease_seconds=settings.governance_lease_seconds,
            )
            assert claimed is not None and claimed.run_id == run_id
            await execute_claimed_governance_job(
                claimed=claimed,
                repository=repository,
                checkpointer=checkpointer,
                graph=graph,
                settings=settings,
            )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        run = await client.get(f"/api/v1/governance-runs/{run_id}")
        assert run.status_code == 200
        assert run.json()["status"] == "succeeded"
        assert run.json()["succeeded_jobs"] == 2

        replay = await client.post(
            "/api/v1/governance-runs",
            json={"acquisition_run_id": str(acquisition_run_id)},
        )
        assert replay.status_code == 202
        assert replay.json()["id"] == str(run_id)

        analyses = await client.get("/api/v1/candidate-analyses", params={"limit": 100})
        assert analyses.status_code == 200
        test_candidate_ids = {str(candidate_id) for candidate_id in candidate_ids}
        test_analyses = [
            item for item in analyses.json()["items"] if item["candidate_id"] in test_candidate_ids
        ]
        assert len(test_analyses) == 1

        candidate_detail = await client.get(f"/api/v1/candidate-analyses/{candidate_ids[0]}")
        assert candidate_detail.status_code == 200
        candidate_payload = candidate_detail.json()
        assert candidate_payload["facts"]
        assert candidate_payload["passages"]
        assert len(candidate_payload["source_occurrences"]) >= 2
        assert {binding["occurrence_id"] for binding in candidate_payload["evidence_bindings"]} <= {
            occurrence["id"] for occurrence in candidate_payload["source_occurrences"]
        }
        assert len(candidate_payload["duplicate_relations"]) == 1
        assert candidate_payload["active_event_id"] is not None
        assert candidate_payload["assignment"]["review_required"] is False

        reused_detail = await client.get(f"/api/v1/candidate-analyses/{ordered_candidate_ids[1]}")
        assert reused_detail.status_code == 200
        reused_payload = reused_detail.json()
        assert reused_payload["requested_candidate_id"] == str(ordered_candidate_ids[1])
        assert reused_payload["analysis_candidate_id"] == str(ordered_candidate_ids[0])
        assert reused_payload["analysis_reused"] is True
        occurrence_ids = {occurrence["id"] for occurrence in reused_payload["source_occurrences"]}
        assert len(occurrence_ids) == 3
        assert {
            binding["occurrence_id"] for binding in reused_payload["evidence_bindings"]
        } <= occurrence_ids
        assert {binding["candidate_id"] for binding in reused_payload["evidence_bindings"]} == {
            str(ordered_candidate_ids[0])
        }

        events = await client.get("/api/v1/events", params={"limit": 100})
        assert events.status_code == 200
        event_item = next(
            item
            for item in events.json()["items"]
            if item["id"] == candidate_payload["active_event_id"]
        )
        assert event_item["member_count"] == 2
        assert event_item["source_diversity"] == 3

        event = await client.get(f"/api/v1/events/{event_item['id']}")
        assert event.status_code == 200
        event_payload = event.json()
        assert len(event_payload["members"]) == 2
        assert len(event_payload["versions"]) == 2
        assert all(member["source_occurrences"] for member in event_payload["members"])
        rendered = event.text.casefold()
        assert "lease_token" not in rendered
        assert '"vector"' not in rendered
        assert "api_key" not in rendered
        assert "provider_request_id" not in rendered

        manual_key = f"manual-api-{uuid4()}"
        manual = await client.post(
            "/api/v1/governance-runs",
            headers={"Idempotency-Key": manual_key},
            json={"candidate_ids": [str(candidate_ids[0])]},
        )
        repeated_manual = await client.post(
            "/api/v1/governance-runs",
            headers={"Idempotency-Key": manual_key},
            json={"candidate_ids": [str(candidate_ids[0])]},
        )
        assert manual.status_code == repeated_manual.status_code == 202
        assert manual.json()["id"] == repeated_manual.json()["id"]


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_manual_governance_api_requires_bounded_selection_and_idempotency(
    integration_context: IntegrationContext,
) -> None:
    app.state.settings = integration_context.settings
    app.state.session_factory = integration_context.session_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing_key = await client.post(
            "/api/v1/governance-runs",
            json={"candidate_ids": [str(uuid4())]},
        )
        excessive = await client.post(
            "/api/v1/governance-runs",
            headers={"Idempotency-Key": "bounded-selection"},
            json={"candidate_ids": [str(uuid4()) for _ in range(101)]},
        )

    assert missing_key.status_code == 422
    assert missing_key.json()["error"]["code"] == "missing_idempotency_key"
    assert missing_key.json()["error"]["request_id"] == missing_key.headers["x-request-id"]
    assert excessive.status_code == 422
    assert excessive.json()["error"]["code"] == "invalid_request"
    assert excessive.json()["error"]["request_id"] == excessive.headers["x-request-id"]
