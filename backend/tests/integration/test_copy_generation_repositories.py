from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from app.api_main import app
from app.application.services.copy_generation import (
    CopyGenerationExecutor,
    build_copy_version_bundle,
)
from app.core.errors import ProviderValidationIssue
from app.domain.topic_selection import TopicScoringConfig, select_daily_topic
from app.infrastructure.db.copy_generation import (
    PostgresCopyGenerationRepository,
    get_copy_generation_projection,
)
from app.infrastructure.db.models import CopyGenerationAttemptModel
from app.infrastructure.db.topic_selection import (
    claim_topic_selection_job,
    complete_topic_selection_job,
    enqueue_topic_selection_run,
    load_topic_candidates,
    persist_topic_selection_decision,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_no_topic_copy_run_is_idempotent_and_never_calls_a_model(
    integration_context: IntegrationContext,
) -> None:
    suffix = uuid4().hex[:12]
    profile = f"copy-no-topic-{suffix}"
    business_date = date(2097, 7, 30)
    cutoff = datetime(2000, 1, 1, tzinfo=UTC)
    config = TopicScoringConfig(
        version=f"copy-no-topic-scoring-{suffix}",
        profile=profile,
    )
    async with integration_context.session_factory() as session:
        topic_run, _ = await enqueue_topic_selection_run(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            config=config,
            governed_event_cutoff=cutoff,
        )
        claimed_topic = await claim_topic_selection_job(
            session,
            run_id=topic_run.id,
            worker_id="copy-no-topic-selection",
            lease_seconds=60,
            max_attempts=3,
        )
        assert claimed_topic is not None
        candidates = await load_topic_candidates(session, topic_run.id)
        decision = select_daily_topic(candidates, as_of=cutoff, config=config)
        assert decision.is_no_topic
        assert await persist_topic_selection_decision(
            session,
            claimed=claimed_topic,
            config=config,
            decision=decision,
        )
        assert await complete_topic_selection_job(session, claimed=claimed_topic)

    settings = integration_context.settings.model_copy(
        update={
            "content_enabled": True,
            "ai_provider_mode": "disabled",
            "content_scoring_profile": profile,
        }
    )
    repository = PostgresCopyGenerationRepository(integration_context.session_factory)
    bundle = build_copy_version_bundle(settings)
    diagnostic_settings = settings.model_copy(
        update={"copy_pipeline_version": f"copy-provider-diagnostic-{suffix}"}
    )
    diagnostic_run_id = await repository.enqueue_for_daily_topic(
        business_date=business_date,
        timezone="Asia/Shanghai",
        scoring_profile=profile,
        version_bundle=build_copy_version_bundle(diagnostic_settings),
    )
    diagnostic_claim = await repository.claim(
        worker_id="copy-provider-diagnostic-worker",
        lease_seconds=60,
        max_attempts=1,
    )
    assert diagnostic_claim is not None
    assert diagnostic_claim.run_id == diagnostic_run_id
    assert await repository.fail_job(
        claimed=diagnostic_claim,
        error_code="invalid_provider_output",
        retry_at=None,
        capability="copy_generation",
        provider_validation_issues=(
            ProviderValidationIssue(
                loc=("claims", 0, "evidence_ids", 0),
                type="uuid_parsing",
            ),
        ),
    )
    async with integration_context.session_factory() as session:
        diagnostic_attempt = await session.scalar(
            select(CopyGenerationAttemptModel).where(
                CopyGenerationAttemptModel.job_id == diagnostic_claim.job_id
            )
        )
    assert diagnostic_attempt is not None
    assert diagnostic_attempt.safe_metadata == {
        "retry_scheduled": False,
        "provider_validation_issues": [
            {
                "loc": ["claims", 0, "evidence_ids", 0],
                "type": "uuid_parsing",
            }
        ],
    }
    run_id = await repository.enqueue_for_daily_topic(
        business_date=business_date,
        timezone="Asia/Shanghai",
        scoring_profile=profile,
        version_bundle=bundle,
    )
    replay_id = await repository.enqueue_for_daily_topic(
        business_date=business_date,
        timezone="Asia/Shanghai",
        scoring_profile=profile,
        version_bundle=bundle,
    )
    assert replay_id == run_id
    executor = CopyGenerationExecutor(
        repository=repository,
        brand_retriever=None,
        generator=None,
        auditor=None,
        settings=settings,
    )

    assert await executor.execute_next("copy-no-topic-worker")
    assert not await executor.execute_next("copy-no-topic-worker-replay")

    async with integration_context.session_factory() as session:
        projection = await get_copy_generation_projection(session, run_id)
    assert projection.run.status == "no_topic"
    assert projection.run.error_code == "no_candidates"
    assert projection.run.repair_count == 0
    assert projection.run.active_draft_version_id is None
    assert projection.drafts == ()

    previous_settings = app.state.settings
    previous_factory = app.state.session_factory
    app.state.settings = settings
    app.state.session_factory = integration_context.session_factory
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            diagnostic_response = await client.get(
                f"/api/v1/copy-generation-runs/{diagnostic_run_id}"
            )
            status_response = await client.get(f"/api/v1/copy-generation-runs/{run_id}")
            detail_response = await client.get(f"/api/v1/copy-generation-runs/{run_id}/detail")
        assert diagnostic_response.status_code == 200
        assert diagnostic_response.json()["error_code"] == "invalid_provider_output"
        assert "provider_validation_issues" not in diagnostic_response.json()
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "no_topic"
        assert detail_response.status_code == 200
        assert detail_response.json()["drafts"] == []
    finally:
        app.state.settings = previous_settings
        app.state.session_factory = previous_factory
