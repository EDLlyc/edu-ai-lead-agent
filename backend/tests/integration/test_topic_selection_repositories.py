from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.application.ports.content_slots import GovernedSlotLineage
from app.application.services.governance_graph import governance_graph_input
from app.application.services.governance_runtime import build_governance_version_bundle
from app.application.services.topic_reranking import execute_topic_rerank
from app.core.errors import ConflictError
from app.domain.content_slots import (
    ContentSlot,
    ContentSlotSchedule,
    SlotRankingPolicy,
    select_slot_topics,
)
from app.domain.editorial_relevance import ScienceTechContentSignal
from app.domain.governance_enums import FactualCategory
from app.domain.ministry_education_priority import (
    MINISTRY_EDUCATION_PRIORITY_RULE_VERSION,
)
from app.domain.topic_rerank import (
    TopicRerankConfig,
    TopicRerankFailureCode,
    TopicRerankOutcomeKind,
    TopicRerankRequest,
    build_daily_rerank_pool,
    build_slot_rerank_pool,
    finalize_content_slot_rerank,
    finalize_daily_topic_rerank,
)
from app.domain.topic_selection import (
    BROAD_HARD_TECH_TOPIC_SCORING_VERSION,
    MOE_SCIENCE_TOP1_PRIORITY_POLICY,
    SOURCE_PRIORITY_RULE_VERSION,
    THRESHOLD_059_TOPIC_SCORING_VERSION,
    NoTopicCode,
    TopicScoringConfig,
    select_daily_topic,
)
from app.infrastructure.ai.topic_rerank import DeterministicFakeTopicReranker
from app.infrastructure.db.content_slots import (
    claim_content_slot_job,
    complete_content_slot_job,
    enqueue_content_slot_run,
    persist_content_slot_decision,
)
from app.infrastructure.db.governance_repositories import create_governance_run_for_acquisition
from app.infrastructure.db.models import (
    AcquisitionJobModel,
    AcquisitionRunModel,
    EventClusterModel,
    EventClusterVersionModel,
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
        version=BROAD_HARD_TECH_TOPIC_SCORING_VERSION,
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


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_v4_rerank_applied_and_finalization_fallback_are_atomic(
    integration_context: IntegrationContext,
) -> None:
    """Persist both v4 paths against real event/version foreign keys."""

    acquisition_run_id, candidate_ids = await _create_acquisition_fixture(
        integration_context,
        candidate_count=1,
    )
    now = datetime.now(UTC)
    async with integration_context.session_factory() as session:
        candidate = await session.get(EvidenceCandidateModel, candidate_ids[0])
        assert candidate is not None
        candidate.title = "人工智能教育与硬科技融合取得新进展"
        candidate.clean_text = "人工智能教育与硬科技融合取得可核验的新进展。"
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
    claimed_governance = await _claim(
        integration_context,
        worker_id="topic-rerank-v3-atomic",
    )
    graph = _build_graph(
        integration_context,
        bundle=bundle,
        analysis_model=FakeFactualAnalysisModel(
            category=FactualCategory.AI_INDUSTRY_APPLICATION,
            entity_name="硬科技教育项目",
        ),
        embedding_model=FakeEmbeddingModel(),
        now=now,
    )
    graph_result = await graph.ainvoke(governance_graph_input(claimed_governance))
    event_id = graph_result["event_id"]
    assert isinstance(event_id, UUID)

    suffix = uuid4().hex[:12]
    scoring_config = TopicScoringConfig(profile=f"rerank-v3-atomic-{suffix}")
    rerank_config = TopicRerankConfig(
        enabled=True,
        provider="fake",
        model="fake-rerank-v1",
    )
    cutoff = now + timedelta(minutes=1)
    async with integration_context.session_factory() as session:
        seed_run, _ = await enqueue_topic_selection_run(
            session,
            business_date=now.date(),
            timezone="Asia/Shanghai",
            config=scoring_config,
            rerank_config=rerank_config,
            governed_event_cutoff=cutoff,
        )
        loaded = await load_topic_candidates(session, seed_run.id)
        first = next(candidate for candidate in loaded if candidate.event_id == event_id)
        original_version = await session.get(EventClusterVersionModel, first.event_version_id)
        assert original_version is not None
        clone_event_id = uuid4()
        clone_version_id = uuid4()
        clone_event = EventClusterModel(
            id=clone_event_id,
            status="active",
            current_version_id=None,
        )
        session.add(clone_event)
        await session.flush()
        session.add(
            EventClusterVersionModel(
                id=clone_version_id,
                event_id=clone_event_id,
                version=1,
                representative_article_id=original_version.representative_article_id,
                representative_title="硬科技教育项目的另一项可核验进展",
                summary_projection=dict(original_version.summary_projection),
                event_time_start=original_version.event_time_start,
                event_time_end=original_version.event_time_end,
                event_time_precision=original_version.event_time_precision,
                member_set_hash=uuid4().hex + uuid4().hex,
                source_diversity=original_version.source_diversity,
                category_projection=list(original_version.category_projection),
                entity_projection=list(original_version.entity_projection),
                clustering_policy_version=original_version.clustering_policy_version,
                version_bundle_fingerprint=original_version.version_bundle_fingerprint,
                created_by_run_id=original_version.created_by_run_id,
            )
        )
        await session.flush()
        clone_event.current_version_id = clone_version_id
        second = replace(
            first,
            event_id=clone_event_id,
            event_version_id=clone_version_id,
            priority_title="硬科技教育项目的另一项可核验进展",
            communication_potential=max(0.0, first.communication_potential - 0.1),
        )

        claimed_applied = await claim_topic_selection_job(
            session,
            run_id=seed_run.id,
            worker_id="topic-rerank-v3-applied",
            lease_seconds=60,
            max_attempts=3,
        )
        assert claimed_applied is not None
        applied_decision = select_daily_topic((first, second), as_of=cutoff, config=scoring_config)
        applied_pool = build_daily_rerank_pool(applied_decision, (first, second), limit=8)
        applied_request = TopicRerankRequest(
            run_id=seed_run.id,
            cutoff_at=cutoff,
            context="daily",
            policy_version=rerank_config.policy_version,
            max_output_tokens=rerank_config.max_output_tokens,
            candidates=applied_pool,
        )
        applied_outcome = await execute_topic_rerank(
            config=rerank_config,
            reranker=DeterministicFakeTopicReranker(model=rerank_config.model),
            request=applied_request,
        )
        applied_decision, applied_outcome = finalize_daily_topic_rerank(
            applied_decision,
            applied_pool,
            applied_outcome,
            request=applied_request,
            candidate_limit=rerank_config.candidate_limit,
        )
        assert applied_outcome.kind is TopicRerankOutcomeKind.APPLIED
        assert await persist_topic_selection_decision(
            session,
            claimed=claimed_applied,
            config=scoring_config,
            decision=applied_decision,
            rerank_outcome=applied_outcome,
        )
        assert await complete_topic_selection_job(session, claimed=claimed_applied)

        fallback_run, _ = await enqueue_topic_selection_run(
            session,
            business_date=now.date() + timedelta(days=1),
            timezone="Asia/Shanghai",
            config=scoring_config,
            rerank_config=rerank_config,
            governed_event_cutoff=cutoff,
        )
        claimed_fallback = await claim_topic_selection_job(
            session,
            run_id=fallback_run.id,
            worker_id="topic-rerank-v3-fallback",
            lease_seconds=60,
            max_attempts=3,
        )
        assert claimed_fallback is not None
        fallback_decision = select_daily_topic((first, second), as_of=cutoff, config=scoring_config)
        fallback_pool = build_daily_rerank_pool(fallback_decision, (first, second), limit=8)
        fallback_request = replace(
            applied_request,
            run_id=fallback_run.id,
            candidates=fallback_pool,
        )
        fallback_decision, fallback_outcome = finalize_daily_topic_rerank(
            fallback_decision,
            fallback_pool,
            applied_outcome,
            request=fallback_request,
            candidate_limit=rerank_config.candidate_limit,
        )
        assert fallback_outcome.kind is TopicRerankOutcomeKind.FALLBACK
        assert fallback_outcome.failure_code is TopicRerankFailureCode.FINALIZATION_REQUEST_MISMATCH
        assert await persist_topic_selection_decision(
            session,
            claimed=claimed_fallback,
            config=scoring_config,
            decision=fallback_decision,
            rerank_outcome=fallback_outcome,
        )
        assert await complete_topic_selection_job(session, claimed=claimed_fallback)

        applied_record = await get_topic_rerank_record(
            session,
            topic_selection_run_id=seed_run.id,
        )
        fallback_record = await get_topic_rerank_record(
            session,
            topic_selection_run_id=fallback_run.id,
        )
        applied_scores = await list_topic_score_rows(session, seed_run.id)
        fallback_scores = await list_topic_score_rows(session, fallback_run.id)

        slot_schedule = ContentSlotSchedule(
            slot=ContentSlot.MORNING,
            enabled=True,
            target_hour=7,
            target_minute=30,
            max_items=2,
        )
        slot_policy = SlotRankingPolicy()
        slot_business_date = now.date() + timedelta(days=2)
        acquisition_run = await session.get(AcquisitionRunModel, acquisition_run_id)
        assert acquisition_run is not None
        acquisition_run.business_date = slot_business_date
        acquisition_run.content_slot = ContentSlot.MORNING.value
        await session.flush()
        slot_run, _ = await enqueue_content_slot_run(
            session,
            business_date=slot_business_date,
            timezone="Asia/Shanghai",
            schedule=slot_schedule,
            config=scoring_config,
            policy=slot_policy,
            lineage=GovernedSlotLineage(
                acquisition_run_id=acquisition_run_id,
                governance_run_id=claimed_governance.run_id,
                governed_event_cutoff=cutoff,
            ),
            trigger="manual",
            rerank_config=rerank_config,
        )
        claimed_slot = await claim_content_slot_job(
            session,
            worker_id="topic-rerank-v3-slot",
            lease_seconds=60,
            max_attempts=3,
        )
        assert claimed_slot is not None
        slot_decision = select_slot_topics(
            (first, second),
            as_of=cutoff,
            config=scoring_config,
            slot=ContentSlot.MORNING,
            policy=slot_policy,
            max_items=2,
        )
        slot_pool = build_slot_rerank_pool(slot_decision, (first, second), limit=8)
        slot_request = TopicRerankRequest(
            run_id=slot_run.id,
            cutoff_at=cutoff,
            context="morning",
            policy_version=rerank_config.policy_version,
            max_output_tokens=rerank_config.max_output_tokens,
            candidates=slot_pool,
        )
        slot_outcome = await execute_topic_rerank(
            config=rerank_config,
            reranker=DeterministicFakeTopicReranker(model=rerank_config.model),
            request=slot_request,
        )
        slot_decision, slot_outcome = finalize_content_slot_rerank(
            slot_decision,
            slot_pool,
            slot_outcome,
            request=slot_request,
            candidate_limit=rerank_config.candidate_limit,
            max_items=2,
        )
        assert await persist_content_slot_decision(
            session,
            claimed=claimed_slot,
            config=scoring_config,
            policy=slot_policy,
            decision=slot_decision,
            rerank_outcome=slot_outcome,
        )
        assert await complete_content_slot_job(session, claimed=claimed_slot)
        slot_record = await get_topic_rerank_record(
            session,
            content_slot_run_id=slot_run.id,
        )

    assert applied_record is not None
    assert applied_record.outcome == "applied"
    assert applied_record.policy_version == rerank_config.policy_version
    assert applied_record.failure_code is None
    assert len(applied_record.reasons) == 2
    assert sorted(score.score.rank for score in applied_scores) == [1, 2]
    assert sorted(score.score.deterministic_rank for score in applied_scores) == [1, 2]
    assert fallback_record is not None
    assert fallback_record.outcome == "fallback"
    assert fallback_record.policy_version == rerank_config.policy_version
    assert fallback_record.failure_code == "finalization_request_mismatch"
    assert fallback_record.base_order == fallback_record.final_order
    assert all(score.score.rank == score.score.deterministic_rank for score in fallback_scores)
    assert slot_record is not None
    assert slot_record.outcome == "applied"
    assert slot_record.policy_version == rerank_config.policy_version
    assert slot_record.failure_code is None
    assert len(slot_record.reasons) == 2
