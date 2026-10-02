from __future__ import annotations

import asyncio
from dataclasses import replace
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
from app.infrastructure.db.models import CopyGenerationAttemptModel, CopyGenerationRunModel
from app.infrastructure.db.repair_metrics import load_repair_stats
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
    assert (
        await repository.claim(
            worker_id="copy-provider-other-business-date-worker",
            business_date=date(2097, 7, 31),
            lease_seconds=60,
            max_attempts=1,
        )
        is None
    )
    diagnostic_claim = await repository.claim(
        worker_id="copy-provider-diagnostic-worker",
        business_date=business_date,
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
    # A failed old run must not be replayed automatically merely because a
    # deployment changes the copy bundle. Explicit enqueue below still may
    # create a run for another version.
    assert (
        await repository.reconcile_ready_topics(
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            version_bundle=bundle,
        )
        == 0
    )
    review_cases = (
        ("provider_request_rejected", (), []),
        (
            "invalid_provider_output",
            (
                ProviderValidationIssue(
                    loc=("claims", 0, "evidence_ids", 0),
                    type="uuid_parsing",
                ),
            ),
            [
                {
                    "loc": ["claims", 0, "evidence_ids", 0],
                    "type": "uuid_parsing",
                }
            ],
        ),
    )
    for index, (error_code, validation_issues, expected_metadata) in enumerate(review_cases):
        review_settings = settings.model_copy(
            update={"copy_pipeline_version": f"copy-provider-review-{index}-{suffix}"}
        )
        review_run_id = await repository.enqueue_for_daily_topic(
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            version_bundle=build_copy_version_bundle(review_settings),
        )
        review_claim = await repository.claim(
            worker_id=f"copy-provider-review-worker-{index}",
            business_date=business_date,
            lease_seconds=60,
            max_attempts=1,
        )
        assert review_claim is not None
        assert review_claim.run_id == review_run_id
        assert await repository.finish(
            claimed=review_claim,
            status="review_required",
            active_draft_version_id=None,
            repair_count=1,
            error_code=error_code,
            provider_validation_issues=validation_issues,
        )
        async with integration_context.session_factory() as session:
            review_attempt = await session.scalar(
                select(CopyGenerationAttemptModel).where(
                    CopyGenerationAttemptModel.job_id == review_claim.job_id
                )
            )
            review_projection = await get_copy_generation_projection(session, review_run_id)
        assert review_attempt is not None
        assert review_attempt.draft_version_id is None
        assert review_attempt.safe_metadata == {"provider_validation_issues": expected_metadata}
        assert review_projection.run.status == "review_required"
        assert review_projection.run.active_draft_version_id is None
        assert review_projection.run.repair_count == 1
        assert review_projection.run.error_code == error_code

    run_id = await repository.enqueue_for_daily_topic(
        business_date=business_date,
        timezone="Asia/Shanghai",
        scoring_profile=profile,
        version_bundle=bundle,
    )
    assert run_id != diagnostic_run_id
    replay_id = await repository.enqueue_for_daily_topic(
        business_date=business_date,
        timezone="Asia/Shanghai",
        scoring_profile=profile,
        version_bundle=bundle,
    )
    assert replay_id == run_id
    assert (
        await repository.reconcile_ready_topics(
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            version_bundle=bundle,
        )
        == 0
    )
    executor = CopyGenerationExecutor(
        repository=repository,
        brand_retriever=None,
        generator=None,
        auditor=None,
        settings=settings,
    )

    assert await executor.execute_next(
        "copy-no-topic-worker", now=datetime(2097, 7, 30, tzinfo=UTC)
    )
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


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_daily_copy_reconciliation_serializes_versions_but_preserves_explicit_enqueue(
    integration_context: IntegrationContext,
) -> None:
    suffix = uuid4().hex[:12]
    profile = f"copy-reconcile-{suffix}"
    business_date = date(2097, 8, 1)
    cutoff = datetime(2000, 1, 1, tzinfo=UTC)
    config = TopicScoringConfig(version=f"copy-reconcile-{suffix}", profile=profile)
    async with integration_context.session_factory() as session:
        topic_run, _ = await enqueue_topic_selection_run(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            config=config,
            governed_event_cutoff=cutoff,
        )
        claimed = await claim_topic_selection_job(
            session,
            run_id=topic_run.id,
            worker_id="copy-reconcile-topic-selection",
            lease_seconds=60,
            max_attempts=3,
        )
        assert claimed is not None
        decision = select_daily_topic(
            await load_topic_candidates(session, topic_run.id),
            as_of=cutoff,
            config=config,
        )
        assert decision.is_no_topic
        assert await persist_topic_selection_decision(
            session, claimed=claimed, config=config, decision=decision
        )
        assert await complete_topic_selection_job(session, claimed=claimed)

    settings = integration_context.settings.model_copy(update={"content_enabled": True})
    first_bundle = build_copy_version_bundle(settings)
    second_bundle = build_copy_version_bundle(
        settings.model_copy(update={"copy_pipeline_version": f"copy-reconcile-v2-{suffix}"})
    )
    repository = PostgresCopyGenerationRepository(integration_context.session_factory)
    created = await asyncio.gather(
        *(
            repository.reconcile_ready_topics(
                business_date=business_date,
                timezone="Asia/Shanghai",
                scoring_profile=profile,
                version_bundle=bundle,
            )
            for bundle in (first_bundle, first_bundle, second_bundle)
        )
    )
    assert sum(created) == 1
    async with integration_context.session_factory() as session:
        automatic_runs = tuple(
            (
                await session.scalars(
                    select(CopyGenerationRunModel).where(
                        CopyGenerationRunModel.topic_selection_run_id == topic_run.id
                    )
                )
            ).all()
        )
    assert len(automatic_runs) == 1
    assert (
        await repository.reconcile_ready_topics(
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            version_bundle=second_bundle,
        )
        == 0
    )

    # An explicit request is still allowed to create a different version.
    explicit_bundle = (
        second_bundle
        if automatic_runs[0].version_fingerprint == first_bundle.fingerprint
        else first_bundle
    )
    explicit_run_id = await repository.enqueue_for_daily_topic(
        business_date=business_date,
        timezone="Asia/Shanghai",
        scoring_profile=profile,
        version_bundle=explicit_bundle,
    )
    assert explicit_run_id != automatic_runs[0].id


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_repair_agent_attempt_is_recorded_once_and_fenced_by_the_lease(
    integration_context: IntegrationContext,
) -> None:
    suffix = uuid4().hex[:12]
    profile = f"copy-agent-attempt-{suffix}"
    business_date = date(2097, 8, 2)
    cutoff = datetime(2000, 1, 1, tzinfo=UTC)
    config = TopicScoringConfig(version=f"copy-agent-attempt-scoring-{suffix}", profile=profile)
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
            worker_id="copy-agent-attempt-selection",
            lease_seconds=60,
            max_attempts=3,
        )
        assert claimed_topic is not None
        candidates = await load_topic_candidates(session, topic_run.id)
        decision = select_daily_topic(candidates, as_of=cutoff, config=config)
        assert await persist_topic_selection_decision(
            session, claimed=claimed_topic, config=config, decision=decision
        )
        assert await complete_topic_selection_job(session, claimed=claimed_topic)
    settings = integration_context.settings.model_copy(
        update={"content_enabled": True, "content_scoring_profile": profile}
    )
    repository = PostgresCopyGenerationRepository(integration_context.session_factory)
    await repository.enqueue_for_daily_topic(
        business_date=business_date,
        timezone="Asia/Shanghai",
        scoring_profile=profile,
        version_bundle=build_copy_version_bundle(settings),
    )
    claimed = await repository.claim(
        worker_id="copy-agent-attempt-worker",
        business_date=business_date,
        lease_seconds=60,
        max_attempts=1,
    )
    assert claimed is not None
    record = {
        "error_code": "repair_agent_audit_blocked",
        "prompt_tokens": 1_300,
        "completion_tokens": 70,
        "latency_ms": 2_000,
        "safe_metadata": {"stopped": "checked", "issue_codes": ["evidence_mismatch"]},
    }

    assert await repository.record_repair_agent_attempt(claimed=claimed, **record)
    assert await repository.record_repair_agent_attempt(claimed=claimed, **record)
    stale = replace(claimed, lease_token=uuid4())
    assert not await repository.record_repair_agent_attempt(
        claimed=stale, **{**record, "error_code": "repair_agent_timeout"}
    )

    async with integration_context.session_factory() as session:
        attempts = (
            await session.scalars(
                select(CopyGenerationAttemptModel).where(
                    CopyGenerationAttemptModel.job_id == claimed.job_id
                )
            )
        ).all()
    (attempt,) = attempts
    assert (attempt.capability, attempt.status, attempt.draft_version_id) == (
        "workflow",
        "failed",
        None,
    )
    assert attempt.error_code == "repair_agent_audit_blocked"
    assert (attempt.prompt_tokens, attempt.completion_tokens) == (1_300, 70)
    assert attempt.safe_metadata == {
        "stopped": "checked",
        "issue_codes": ["evidence_mismatch"],
        "repair_method": "agent",
    }

    # The online statistics read the same rows through plain SELECTs.
    async with integration_context.session_factory() as session:
        stats = await load_repair_stats(
            session, start=business_date, end=business_date, timezone="Asia/Shanghai"
        )
    assert (stats.repaired_runs, stats.agent_attempted, stats.agent_accepted) == (1, 1, 0)
    assert dict(stats.fallbacks) == {"repair_agent_audit_blocked": 1}
    assert dict(stats.stop_reasons) == {"checked": 1}
