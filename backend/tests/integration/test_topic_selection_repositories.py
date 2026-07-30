from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from app.core.errors import ConflictError
from app.domain.topic_selection import NoTopicCode, TopicScoringConfig, select_daily_topic
from app.infrastructure.db.models import TopicSelectionJobModel
from app.infrastructure.db.topic_selection import (
    claim_topic_selection_job,
    complete_topic_selection_job,
    enqueue_topic_selection_run,
    get_daily_topic_result,
    get_topic_selection_run,
    heartbeat_topic_selection_job,
    list_topic_score_rows,
    load_topic_candidates,
    persist_topic_selection_decision,
)

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_topic_selection_no_topic_flow_is_idempotent_and_durable(
    integration_context: IntegrationContext,
) -> None:
    suffix = uuid4().hex[:12]
    config = TopicScoringConfig(
        version=f"scoring-v1-preview-{suffix}",
        profile=f"preview-{suffix}",
    )
    business_date = date(2098, 7, 30)
    cutoff = datetime(2000, 1, 1, tzinfo=UTC)
    async with integration_context.session_factory() as session:
        run, created = await enqueue_topic_selection_run(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            config=config,
            governed_event_cutoff=cutoff,
        )
        replay, replay_created = await enqueue_topic_selection_run(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            config=config,
            governed_event_cutoff=cutoff,
        )
        assert created is True
        assert replay_created is False
        assert replay.id == run.id
        assert replay.config_snapshot == config.as_metadata()
        run_id = run.id

        different_config = TopicScoringConfig(
            version=f"scoring-v1-preview-{suffix}-next",
            profile=config.profile,
            threshold=0.63,
        )
        with pytest.raises(ConflictError):
            await enqueue_topic_selection_run(
                session,
                business_date=business_date,
                timezone="Asia/Shanghai",
                config=different_config,
                governed_event_cutoff=cutoff,
            )

        claimed = await claim_topic_selection_job(
            session,
            run_id=run_id,
            worker_id="topic-test-worker",
            lease_seconds=60,
            max_attempts=3,
        )
        assert claimed is not None
        assert await heartbeat_topic_selection_job(session, claimed=claimed, lease_seconds=60)

        candidates = await load_topic_candidates(session, run_id)
        assert candidates == ()
        decision = select_daily_topic(candidates, as_of=cutoff, config=config)
        assert decision.no_topic_code is NoTopicCode.NO_CANDIDATES
        assert await persist_topic_selection_decision(
            session,
            claimed=claimed,
            config=config,
            decision=decision,
        )
        assert await persist_topic_selection_decision(
            session,
            claimed=claimed,
            config=config,
            decision=decision,
        )
        assert await complete_topic_selection_job(session, claimed=claimed)

        stored_run = await get_topic_selection_run(session, run_id)
        scores = await list_topic_score_rows(session, run_id)
        daily = await get_daily_topic_result(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=config.profile,
        )

    assert stored_run.status == "succeeded"
    assert stored_run.trigger == "manual"
    assert stored_run.no_topic_code == "no_candidates"
    assert stored_run.total_scores == 0
    assert stored_run.eligible_scores == 0
    assert scores == ()
    assert daily is not None
    assert daily.selection.decision_kind == "no_topic"
    assert daily.selection.no_topic_code == "no_candidates"
    assert daily.selected_title is None


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_expired_topic_job_stops_after_the_configured_attempt_limit(
    integration_context: IntegrationContext,
) -> None:
    suffix = uuid4().hex[:12]
    config = TopicScoringConfig(
        version=f"scoring-v1-preview-attempt-{suffix}",
        profile=f"preview-attempt-{suffix}",
    )
    async with integration_context.session_factory() as session:
        run, _ = await enqueue_topic_selection_run(
            session,
            business_date=date(2098, 7, 31),
            timezone="Asia/Shanghai",
            config=config,
            governed_event_cutoff=datetime(2000, 1, 1, tzinfo=UTC),
        )
        claimed = await claim_topic_selection_job(
            session,
            run_id=run.id,
            worker_id="topic-attempt-limit",
            lease_seconds=60,
            max_attempts=1,
        )
        assert claimed is not None
        job = await session.get(TopicSelectionJobModel, claimed.job_id)
        assert job is not None
        job.lease_expires_at = datetime(1999, 1, 1, tzinfo=UTC)
        await session.commit()

        assert (
            await claim_topic_selection_job(
                session,
                run_id=run.id,
                worker_id="topic-attempt-limit-retry",
                lease_seconds=60,
                max_attempts=1,
            )
            is None
        )
        await session.refresh(job)
        stored_run = await get_topic_selection_run(session, run.id)

    assert job.status == "failed"
    assert job.error_code == "max_attempts_exhausted"
    assert stored_run.status == "failed"
