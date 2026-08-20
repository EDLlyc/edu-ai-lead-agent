from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.application.services.governance_graph import governance_graph_input
from app.application.services.governance_runtime import build_governance_version_bundle
from app.core.errors import ConflictError
from app.domain.editorial_relevance import ScienceTechContentSignal
from app.domain.governance_enums import FactualCategory
from app.domain.ministry_education_priority import MINISTRY_EDUCATION_PRIORITY_RULE_VERSION
from app.domain.topic_rerank import TopicRerankConfig
from app.domain.topic_selection import (
    MOE_SCIENCE_TOP1_PRIORITY_POLICY,
    SOURCE_PRIORITY_RULE_VERSION,
    THRESHOLD_059_TOPIC_SCORING_VERSION,
    NoTopicCode,
    TopicScoringConfig,
    select_daily_topic,
)
from app.infrastructure.db.governance_repositories import create_governance_run_for_acquisition
from app.infrastructure.db.models import (
    AcquisitionJobModel,
    EvidenceCandidateModel,
    SourceObservationModel,
    SourceSnapshotModel,
    TopicSelectionJobModel,
)
from app.infrastructure.db.topic_selection import (
    claim_topic_selection_job,
    complete_topic_selection_job,
    enqueue_topic_selection_run,
    get_daily_topic_result,
    get_topic_rerank_record,
    get_topic_selection_run,
    heartbeat_topic_selection_job,
    list_topic_score_rows,
    load_governed_topic_candidates,
    load_topic_candidates,
    persist_topic_selection_decision,
)
from app.infrastructure.ingestion.source_profiles import SOURCE_SEEDS

from .conftest import IntegrationContext
from .governance_graph_support import FakeEmbeddingModel, FakeFactualAnalysisModel
from .test_event_organization import _build_graph, _claim
from .test_governance_repositories import _create_acquisition_fixture


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_topic_selection_no_topic_flow_is_idempotent_and_durable(
    integration_context: IntegrationContext,
) -> None:
    suffix = uuid4().hex[:12]
    config = TopicScoringConfig(
        version=f"scoring-v1-preview-{suffix}",
        profile=f"preview-{suffix}",
        selection_priority_rule_version=SOURCE_PRIORITY_RULE_VERSION,
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
        assert replay.config_snapshot["selection_priority_rule_version"] == "source-priority-v1"
        assert replay.rerank_config_snapshot == TopicRerankConfig().as_metadata()
        assert replay.rerank_config_fingerprint == TopicRerankConfig().fingerprint
        run_id = run.id

        with pytest.raises(ConflictError):
            await enqueue_topic_selection_run(
                session,
                business_date=business_date,
                timezone="Asia/Shanghai",
                config=config,
                rerank_config=TopicRerankConfig(
                    enabled=True,
                    provider="fake",
                    model="fake-rerank-v1",
                ),
                governed_event_cutoff=cutoff,
            )

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
        assert not await persist_topic_selection_decision(
            session,
            claimed=claimed,
            config=config,
            decision=decision,
        )

        stored_run = await get_topic_selection_run(session, run_id)
        scores = await list_topic_score_rows(session, run_id)
        daily = await get_daily_topic_result(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=config.profile,
        )
        rerank_record = await get_topic_rerank_record(
            session,
            topic_selection_run_id=run_id,
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
    assert rerank_record is not None
    assert rerank_record.outcome == "skipped"
    assert rerank_record.provider == "disabled"
    assert rerank_record.candidate_count == 0
    assert rerank_record.base_order == []
    assert rerank_record.final_order == []
    assert rerank_record.reasons == {}


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_provisional_no_topic_can_be_superseded_once(
    integration_context: IntegrationContext,
) -> None:
    suffix = uuid4().hex[:12]
    config = TopicScoringConfig(
        version=f"scoring-v1-preview-recovery-{suffix}",
        profile=f"preview-recovery-{suffix}",
    )
    business_date = date(2098, 8, 2)
    old_cutoff = datetime(2026, 8, 3, 1, 0, tzinfo=UTC)
    new_cutoff = datetime(2026, 8, 3, 2, 0, tzinfo=UTC)
    async with integration_context.session_factory() as session:
        first, created = await enqueue_topic_selection_run(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            config=config,
            governed_event_cutoff=old_cutoff,
            trigger="scheduled",
        )
        assert created is True
        claimed = await claim_topic_selection_job(
            session,
            run_id=first.id,
            worker_id="topic-recovery-worker",
            lease_seconds=60,
            max_attempts=3,
        )
        assert claimed is not None
        decision = select_daily_topic((), as_of=old_cutoff, config=config)
        assert await persist_topic_selection_decision(
            session,
            claimed=claimed,
            config=config,
            decision=decision,
        )
        assert await complete_topic_selection_job(session, claimed=claimed)

        second, recovery_created = await enqueue_topic_selection_run(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            config=config,
            governed_event_cutoff=new_cutoff,
            trigger="scheduled",
        )
        replay, replay_created = await enqueue_topic_selection_run(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            config=config,
            governed_event_cutoff=new_cutoff,
            trigger="scheduled",
        )
        old = await get_topic_selection_run(session, first.id)

    assert recovery_created is True
    assert second.id != first.id
    assert second.revision == first.revision + 1
    assert replay_created is False
    assert replay.id == second.id
    assert old.superseded_at is not None
    assert old.superseded_by_run_id == second.id


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


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_ministry_policy_authenticates_from_source_version_and_round_trips_explanation(
    integration_context: IntegrationContext,
) -> None:
    acquisition_run_id, candidate_ids = await _create_acquisition_fixture(
        integration_context,
        candidate_count=1,
    )
    candidate_id = candidate_ids[0]
    ministry_seed = next(seed for seed in SOURCE_SEEDS if seed.slug == "moe-science-news")
    now = datetime.now(UTC)
    ministry_job_id = uuid4()
    ministry_snapshot_id = uuid4()
    ministry_observation_id = uuid4()
    async with integration_context.session_factory() as session:
        candidate = await session.get(EvidenceCandidateModel, candidate_id)
        assert candidate is not None
        candidate.title = "教育部报道人工智能教育课程实践成果"
        candidate.clean_text = "教育部报道学校人工智能课程实践取得新成果。"
        candidate.published_at = now
        candidate.first_fetched_at = now
        session.add(
            AcquisitionJobModel(
                id=ministry_job_id,
                run_id=acquisition_run_id,
                source_id=ministry_seed.source_id,
                source_version_id=ministry_seed.source_version_id,
                status="succeeded",
                outcome="completed",
                completed_at=now,
            )
        )
        session.add(
            SourceSnapshotModel(
                id=ministry_snapshot_id,
                provenance_key=uuid4().hex + uuid4().hex,
                source_version_id=ministry_seed.source_version_id,
                kind="detail",
                original_url="https://www.moe.gov.cn/jyb_xwfb/ministry-priority-fixture.html",
                final_url="https://www.moe.gov.cn/jyb_xwfb/ministry-priority-fixture.html",
                bucket="fixture",
                object_key=f"fixture/{ministry_snapshot_id}",
                media_type="text/html",
                byte_size=100,
                sha256="e" * 64,
                response_metadata={},
                fetched_at=now,
                connector_version=ministry_seed.connector_version,
                parser_version=ministry_seed.parser_version,
            )
        )
        await session.flush()
        session.add(
            SourceObservationModel(
                id=ministry_observation_id,
                idempotency_key=uuid4().hex + uuid4().hex,
                run_id=acquisition_run_id,
                job_id=ministry_job_id,
                source_version_id=ministry_seed.source_version_id,
                source_item_id="ministry-priority-fixture",
                outcome="exact_duplicate",
                snapshot_id=ministry_snapshot_id,
                candidate_id=candidate_id,
                observed_at=now,
                observation_metadata={},
            )
        )
        await session.commit()

    bundle = build_governance_version_bundle(integration_context.settings)
    async with integration_context.session_factory() as session:
        await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=acquisition_run_id,
            bundle=bundle,
            timezone="Asia/Shanghai",
        )
    claimed_governance = await _claim(
        integration_context,
        worker_id="topic-ministry-source-policy",
    )
    graph = _build_graph(
        integration_context,
        bundle=bundle,
        analysis_model=FakeFactualAnalysisModel(
            category=FactualCategory.AI_EDUCATION_POLICY,
            entity_name="教育部",
        ),
        embedding_model=FakeEmbeddingModel(),
        now=now,
    )
    graph_result = await graph.ainvoke(governance_graph_input(claimed_governance))
    event_id = graph_result["event_id"]
    assert isinstance(event_id, UUID)

    suffix = uuid4().hex[:12]
    config = TopicScoringConfig(
        profile=f"ministry-auth-{suffix}",
        threshold=0.99,
        selection_priority_rule_version=MINISTRY_EDUCATION_PRIORITY_RULE_VERSION,
    )
    cutoff = now + timedelta(minutes=1)
    async with integration_context.session_factory() as session:
        topic_run, _ = await enqueue_topic_selection_run(
            session,
            business_date=now.date(),
            timezone="Asia/Shanghai",
            config=config,
            governed_event_cutoff=cutoff,
        )
        candidates = await load_topic_candidates(session, topic_run.id)
        target = next(candidate for candidate in candidates if candidate.event_id == event_id)
        assert target.topic_priority_policy == MOE_SCIENCE_TOP1_PRIORITY_POLICY
        assert target.science_tech_content_signals == (ScienceTechContentSignal.GENERAL_HARD_TECH,)
        historical_config = TopicScoringConfig(
            version=THRESHOLD_059_TOPIC_SCORING_VERSION,
            profile=f"historical-v2-{suffix}",
            threshold=0.59,
            selection_priority_rule_version=MINISTRY_EDUCATION_PRIORITY_RULE_VERSION,
        )
        historical_candidates = await load_governed_topic_candidates(
            session,
            business_date=now.date(),
            timezone="Asia/Shanghai",
            scoring_profile=historical_config.profile,
            governed_event_cutoff=cutoff,
            config_snapshot=historical_config.as_metadata(),
        )
        historical_target = next(
            candidate for candidate in historical_candidates if candidate.event_id == event_id
        )
        assert historical_target.science_tech_editorial_cohort == (
            target.science_tech_editorial_cohort
        )
        assert historical_target.science_tech_content_signals == ()
        claimed_topic = await claim_topic_selection_job(
            session,
            run_id=topic_run.id,
            worker_id="topic-ministry-source-policy",
            lease_seconds=60,
            max_attempts=3,
        )
        assert claimed_topic is not None
        decision = select_daily_topic((target,), as_of=cutoff, config=config)
        assert decision.scores[0].passes_threshold is False
        assert decision.scores[0].eligible is True
        assert decision.scores[0].priority_applied is True
        assert decision.scores[0].threshold_bypass_applied is True
        assert await persist_topic_selection_decision(
            session,
            claimed=claimed_topic,
            config=config,
            decision=decision,
        )
        score_rows = await list_topic_score_rows(session, topic_run.id)

    assert len(score_rows) == 1
    stored = score_rows[0].score
    assert stored.passes_threshold is False
    assert stored.eligible is True
    assert stored.explanation["topic_priority_policy"] == MOE_SCIENCE_TOP1_PRIORITY_POLICY
    assert stored.explanation["priority_applied"] is True
    assert stored.explanation["threshold_bypass_applied"] is True
