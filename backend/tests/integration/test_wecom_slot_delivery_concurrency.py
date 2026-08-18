from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from app.application.services.copy_generation import build_copy_version_bundle
from app.application.services.wecom_delivery import WeComDeliveryExecutor
from app.domain.content_slots import SlotRankingPolicy
from app.domain.topic_rerank import TopicRerankConfig
from app.domain.topic_selection import TopicScoringConfig, TopicVetoCode, score_topic_candidate
from app.infrastructure.db.copy_generation import PostgresCopyGenerationRepository
from app.infrastructure.db.models import (
    AcquisitionRunModel,
    ContentSlotRunModel,
    ContentSlotScoreModel,
    ContentSlotSelectionModel,
    CopyDraftVersionModel,
    CopyGenerationCheckpointModel,
    CopyGenerationJobModel,
    CopyGenerationRunModel,
    DailyTopicSelectionModel,
    EventClusterModel,
    EventClusterVersionModel,
    EvidenceCandidateModel,
    GovernanceRunModel,
    ImageArtifactModel,
    MaterialPackageModel,
    NormalizedArticleModel,
    TopicSelectionRunModel,
    WeComDeliveryAttemptModel,
    WeComDeliveryJobModel,
    WeComDeliveryWindowModel,
)
from app.infrastructure.db.topic_selection import (
    ensure_topic_scoring_config,
    load_governed_topic_candidates,
    topic_scoring_config_fingerprint,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .conftest import IntegrationContext
from .test_governance_repositories import _create_acquisition_fixture


async def _seed_slot_delivery_lane(
    context: IntegrationContext,
    *,
    target_at: datetime,
) -> tuple[UUID, tuple[UUID, UUID, UUID], date, str]:
    business_date = target_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
    acquisition_id, candidate_ids = await _create_acquisition_fixture(
        context,
        candidate_count=3,
    )
    governance_id = uuid4()
    policy = SlotRankingPolicy()
    rerank_config = TopicRerankConfig()
    config = TopicScoringConfig(
        profile=f"slot-delivery-{uuid4().hex[:10]}",
        version="scoring-v1-preview.6-tiered-science-tech-priority",
    )
    run_id = uuid4()
    window_id = uuid4()
    expires_at = target_at + timedelta(hours=1)
    job_ids: list[UUID] = []

    async with context.session_factory() as session:
        await session.execute(
            update(WeComDeliveryJobModel)
            .where(WeComDeliveryJobModel.status.in_(("queued", "running")))
            .values(
                status="cancelled",
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                completed_at=target_at,
            )
        )
        acquisition = await session.get(AcquisitionRunModel, acquisition_id)
        assert acquisition is not None
        acquisition.trigger = "scheduled"
        acquisition.business_date = business_date
        acquisition.content_slot = "morning"
        acquisition.manual_idempotency_key = None
        session.add(
            GovernanceRunModel(
                id=governance_id,
                trigger="acquisition",
                acquisition_run_id=acquisition_id,
                timezone="Asia/Shanghai",
                profile_fingerprint=uuid4().hex + uuid4().hex,
                version_bundle={},
                status="succeeded",
                completed_at=target_at - timedelta(minutes=1),
            )
        )
        # The fixture models intentionally declare no ORM relationships, so
        # make the exact governance lineage durable before its slot aggregate.
        await session.flush()
        stored_config = await ensure_topic_scoring_config(session, config)
        session.add(
            ContentSlotRunModel(
                id=run_id,
                trigger="scheduled",
                business_date=business_date,
                timezone="Asia/Shanghai",
                content_slot="morning",
                scoring_profile=config.profile,
                acquisition_run_id=acquisition_id,
                governance_run_id=governance_id,
                governed_event_cutoff=target_at - timedelta(minutes=1),
                config_id=stored_config.id,
                config_fingerprint=topic_scoring_config_fingerprint(config),
                config_snapshot=config.as_metadata(),
                rerank_config_fingerprint=rerank_config.fingerprint,
                rerank_config_snapshot=rerank_config.as_metadata(),
                slot_policy_version=policy.version,
                slot_policy_fingerprint=policy.fingerprint,
                slot_policy_snapshot=policy.as_metadata(),
                preparation_at=target_at - timedelta(minutes=90),
                target_at=target_at,
                expires_at=expires_at,
                item_limit=3,
                status="succeeded",
                total_scores=3,
                eligible_scores=3,
                selected_count=3,
                unfilled_count=0,
                unfilled_reason_codes=[],
                completed_at=target_at - timedelta(seconds=1),
            )
        )
        await session.flush()
        session.add(
            WeComDeliveryWindowModel(
                id=window_id,
                business_date=business_date,
                timezone="Asia/Shanghai",
                content_slot="morning",
                recipient_id="default",
                provider="self_built_app",
                mode="formal",
                target_at=target_at,
                expires_at=expires_at,
                package_gap_seconds=60,
                next_allowed_at=target_at,
            )
        )
        await session.flush()

        for index, candidate_id in enumerate(candidate_ids, start=1):
            candidate = await session.get(EvidenceCandidateModel, candidate_id)
            assert candidate is not None
            normalized_id = uuid4()
            event_id = uuid4()
            event_version_id = uuid4()
            score_id = uuid4()
            selection_id = uuid4()
            copy_run_id = uuid4()
            draft_id = uuid4()
            image_id = uuid4()
            package_id = uuid4()
            digest = f"{index + 10:064x}"
            draft_fingerprint = uuid4().hex + uuid4().hex
            image_fingerprint = uuid4().hex + uuid4().hex
            package_fingerprint = uuid4().hex + uuid4().hex
            delivery_fingerprint = uuid4().hex + uuid4().hex

            session.add(
                NormalizedArticleModel(
                    id=normalized_id,
                    candidate_id=candidate.id,
                    input_content_hash=candidate.content_hash,
                    normalization_version="slot-delivery-fixture-v1",
                    normalized_hash=digest,
                    simhash_hex=f"{index:016x}",
                    normalized_text=candidate.clean_text,
                    language="zh-CN",
                )
            )
            session.add(EventClusterModel(id=event_id, status="active"))
            await session.flush()
            session.add(
                EventClusterVersionModel(
                    id=event_version_id,
                    event_id=event_id,
                    version=1,
                    representative_article_id=normalized_id,
                    representative_title=f"Slot delivery fixture {index}",
                    summary_projection={},
                    event_time_start=target_at - timedelta(hours=1),
                    event_time_end=None,
                    event_time_precision="exact",
                    member_set_hash=digest,
                    source_diversity=1,
                    category_projection=[],
                    entity_projection=[],
                    clustering_policy_version="slot-delivery-fixture-v1",
                    version_bundle_fingerprint=digest,
                    created_by_run_id=governance_id,
                )
            )
            await session.flush()
            event = await session.get(EventClusterModel, event_id)
            assert event is not None
            event.current_version_id = event_version_id
            session.add(
                ContentSlotScoreModel(
                    id=score_id,
                    run_id=run_id,
                    event_id=event_id,
                    event_version_id=event_version_id,
                    raw_features={},
                    normalized_features={},
                    weights={},
                    penalty_weights={},
                    positive_components={},
                    penalty_components={},
                    total=0.9,
                    threshold=0.6,
                    passes_threshold=True,
                    eligible=True,
                    veto_codes=[],
                    explanation={},
                    slot_affinity=0.0,
                    slot_affinity_reasons=[],
                    same_day_excluded=False,
                    same_day_exclusion_reason=None,
                    final_ordering_value=0.9,
                    final_ordering_key=f"slot-delivery-{index}",
                    deterministic_rank=index,
                    rank=index,
                    selected_ordinal=index,
                )
            )
            await session.flush()
            session.add(
                ContentSlotSelectionModel(
                    id=selection_id,
                    run_id=run_id,
                    score_id=score_id,
                    business_date=business_date,
                    timezone="Asia/Shanghai",
                    content_slot="morning",
                    ordinal=index,
                    selected_event_id=event_id,
                    selected_event_version_id=event_version_id,
                )
            )
            await session.flush()
            copy_run = CopyGenerationRunModel(
                id=copy_run_id,
                daily_topic_selection_id=None,
                content_slot_selection_id=selection_id,
                topic_selection_run_id=None,
                business_date=business_date,
                timezone="Asia/Shanghai",
                scoring_profile=config.profile,
                decision_kind="selected",
                selected_event_id=event_id,
                selected_event_version_id=event_version_id,
                no_topic_code=None,
                status="accepted",
                pipeline_version="slot-delivery-fixture-v1",
                version_fingerprint=digest,
                version_bundle={},
                active_draft_version_id=None,
                repair_count=0,
                completed_at=target_at - timedelta(seconds=1),
            )
            session.add(copy_run)
            await session.flush()
            session.add(
                CopyDraftVersionModel(
                    id=draft_id,
                    run_id=copy_run_id,
                    version=1,
                    repair_of_version_id=None,
                    copywriting="fixture copy",
                    parent_takeaway="fixture takeaway",
                    interaction="fixture interaction",
                    source_note="fixture source",
                    image_prompt="fixture image",
                    provider="fake",
                    model="fake",
                    request_fingerprint=draft_fingerprint,
                    provider_request_id=None,
                    prompt_version="fixture-v1",
                    schema_version="fixture-v1",
                    rule_version="fixture-v1",
                    validation_passed=True,
                    audit_accepted=True,
                )
            )
            await session.flush()
            copy_run.active_draft_version_id = draft_id
            session.add(
                ImageArtifactModel(
                    id=image_id,
                    run_id=copy_run_id,
                    draft_version_id=draft_id,
                    request_fingerprint=image_fingerprint,
                    provider="fake",
                    model="fake",
                    prompt_version="fixture-v1",
                    pipeline_version="fixture-v1",
                    status="succeeded",
                    validation_snapshot={"configured": True, "passed": True},
                    audit_snapshot={"configured": False, "passed": None},
                    media_type="image/png",
                    width=1024,
                    height=1024,
                    byte_size=1024,
                    sha256=f"{index + 30:064x}",
                    bucket="fixture",
                    object_key=f"fixture/{image_id}.png",
                    storage_metadata={
                        "access": "private",
                        "immutable": True,
                        "content_addressed": True,
                    },
                    completed_at=target_at - timedelta(seconds=1),
                )
            )
            await session.flush()
            session.add(
                MaterialPackageModel(
                    id=package_id,
                    run_id=copy_run_id,
                    draft_version_id=draft_id,
                    image_artifact_id=image_id,
                    package_version=1,
                    request_fingerprint=package_fingerprint,
                    status="completed",
                    topic_snapshot={},
                    copy_snapshot={},
                    source_snapshot=[],
                    brand_snapshot=[],
                    validation_snapshot={"passed": True},
                    audit_snapshot={"accepted": True},
                    version_snapshot={},
                    review_status="approved",
                )
            )
            await session.flush()
            job_id = uuid4()
            job_ids.append(job_id)
            session.add(
                WeComDeliveryJobModel(
                    id=job_id,
                    material_package_id=package_id,
                    delivery_window_id=window_id,
                    content_slot_selection_id=selection_id,
                    sequence_ordinal=index,
                    not_before=target_at,
                    expires_at=expires_at,
                    recipient_id="default",
                    mode="formal",
                    package_version=1,
                    content_fingerprint=package_fingerprint,
                    request_fingerprint=delivery_fingerprint,
                    include_copy=True,
                    include_image=True,
                    status="queued",
                    text_status="pending",
                    image_status="pending",
                    attempt_count=0,
                    next_attempt_at=target_at,
                )
            )

        await session.commit()

    return window_id, (job_ids[0], job_ids[1], job_ids[2]), business_date, config.profile


async def _add_delivery_variant(
    session: AsyncSession,
    *,
    source_job_id: UUID,
    package_version: int,
    mode: str,
    status: str,
    completed_at: datetime | None = None,
) -> UUID:
    source_job = await session.get(WeComDeliveryJobModel, source_job_id)
    assert source_job is not None
    source_package = await session.get(MaterialPackageModel, source_job.material_package_id)
    assert source_package is not None
    package_id = uuid4()
    package_fingerprint = uuid4().hex + uuid4().hex
    session.add(
        MaterialPackageModel(
            id=package_id,
            run_id=source_package.run_id,
            draft_version_id=source_package.draft_version_id,
            image_artifact_id=source_package.image_artifact_id,
            package_version=package_version,
            request_fingerprint=package_fingerprint,
            status=source_package.status,
            topic_snapshot=source_package.topic_snapshot,
            copy_snapshot=source_package.copy_snapshot,
            source_snapshot=source_package.source_snapshot,
            brand_snapshot=source_package.brand_snapshot,
            validation_snapshot=source_package.validation_snapshot,
            audit_snapshot=source_package.audit_snapshot,
            version_snapshot=source_package.version_snapshot,
            review_status=source_package.review_status,
        )
    )
    await session.flush()
    delivered_child_status = "delivered" if status == "delivered" else "pending"
    is_slot_job = mode == "formal" and source_job.content_slot_selection_id is not None
    job_id = uuid4()
    session.add(
        WeComDeliveryJobModel(
            id=job_id,
            material_package_id=package_id,
            delivery_window_id=source_job.delivery_window_id if is_slot_job else None,
            content_slot_selection_id=(
                source_job.content_slot_selection_id if is_slot_job else None
            ),
            sequence_ordinal=source_job.sequence_ordinal if is_slot_job else None,
            not_before=source_job.not_before if is_slot_job else None,
            expires_at=source_job.expires_at if is_slot_job else None,
            recipient_id=source_job.recipient_id,
            mode=mode,
            package_version=package_version,
            content_fingerprint=package_fingerprint,
            request_fingerprint=uuid4().hex + uuid4().hex,
            include_copy=True,
            include_image=True,
            status=status,
            text_status=delivered_child_status,
            image_status=delivered_child_status,
            attempt_count=1 if status != "queued" else 0,
            next_attempt_at=source_job.next_attempt_at,
            completed_at=completed_at,
        )
    )
    await session.flush()
    return job_id


async def _seed_daily_delivery_origin(
    session: AsyncSession,
    *,
    slot_selection: ContentSlotSelectionModel,
    business_date: date,
    scoring_profile: str,
    completed_at: datetime,
    delivery_mode: str | None,
) -> tuple[UUID, UUID | None]:
    slot_run = await session.get(ContentSlotRunModel, slot_selection.run_id)
    assert slot_run is not None
    topic_run_id = uuid4()
    selection_id = uuid4()
    copy_run_id = uuid4()
    draft_id = uuid4()
    image_id = uuid4()
    package_id = uuid4()
    config_fingerprint = slot_run.config_fingerprint
    version_fingerprint = uuid4().hex + uuid4().hex
    package_fingerprint = uuid4().hex + uuid4().hex

    session.add(
        TopicSelectionRunModel(
            id=topic_run_id,
            trigger="manual",
            business_date=business_date,
            timezone=slot_selection.timezone,
            scoring_profile=scoring_profile,
            config_id=slot_run.config_id,
            config_fingerprint=config_fingerprint,
            config_snapshot=slot_run.config_snapshot,
            rerank_config_fingerprint=slot_run.rerank_config_fingerprint,
            rerank_config_snapshot=slot_run.rerank_config_snapshot,
            governed_event_cutoff=completed_at,
            status="succeeded",
            selected_event_id=slot_selection.selected_event_id,
            selected_event_version_id=slot_selection.selected_event_version_id,
            no_topic_code=None,
            total_scores=1,
            eligible_scores=1,
            completed_at=completed_at,
        )
    )
    await session.flush()
    session.add(
        DailyTopicSelectionModel(
            id=selection_id,
            business_date=business_date,
            timezone=slot_selection.timezone,
            scoring_profile=scoring_profile,
            run_id=topic_run_id,
            config_id=slot_run.config_id,
            config_fingerprint=config_fingerprint,
            decision_kind="selected",
            selected_event_id=slot_selection.selected_event_id,
            selected_event_version_id=slot_selection.selected_event_version_id,
            no_topic_code=None,
        )
    )
    await session.flush()
    copy_run = CopyGenerationRunModel(
        id=copy_run_id,
        daily_topic_selection_id=selection_id,
        content_slot_selection_id=None,
        topic_selection_run_id=topic_run_id,
        business_date=business_date,
        timezone=slot_selection.timezone,
        scoring_profile=scoring_profile,
        decision_kind="selected",
        selected_event_id=slot_selection.selected_event_id,
        selected_event_version_id=slot_selection.selected_event_version_id,
        no_topic_code=None,
        status="accepted",
        pipeline_version="daily-delivery-fixture-v1",
        version_fingerprint=version_fingerprint,
        version_bundle={},
        active_draft_version_id=None,
        repair_count=0,
        completed_at=completed_at,
    )
    session.add(copy_run)
    await session.flush()
    session.add(
        CopyDraftVersionModel(
            id=draft_id,
            run_id=copy_run_id,
            version=1,
            repair_of_version_id=None,
            copywriting="daily fixture copy",
            parent_takeaway="daily fixture takeaway",
            interaction="daily fixture interaction",
            source_note="daily fixture source",
            image_prompt="daily fixture image",
            provider="fake",
            model="fake",
            request_fingerprint=uuid4().hex + uuid4().hex,
            provider_request_id=None,
            prompt_version="fixture-v1",
            schema_version="fixture-v1",
            rule_version="fixture-v1",
            validation_passed=True,
            audit_accepted=True,
        )
    )
    await session.flush()
    copy_run.active_draft_version_id = draft_id
    session.add(
        ImageArtifactModel(
            id=image_id,
            run_id=copy_run_id,
            draft_version_id=draft_id,
            request_fingerprint=uuid4().hex + uuid4().hex,
            provider="fake",
            model="fake",
            prompt_version="fixture-v1",
            pipeline_version="fixture-v1",
            status="succeeded",
            validation_snapshot={"configured": True, "passed": True},
            audit_snapshot={"configured": False, "passed": None},
            media_type="image/png",
            width=1024,
            height=1024,
            byte_size=1024,
            sha256=uuid4().hex + uuid4().hex,
            bucket="fixture",
            object_key=f"fixture/{image_id}.png",
            storage_metadata={
                "access": "private",
                "immutable": True,
                "content_addressed": True,
            },
            completed_at=completed_at,
        )
    )
    await session.flush()
    session.add(
        MaterialPackageModel(
            id=package_id,
            run_id=copy_run_id,
            draft_version_id=draft_id,
            image_artifact_id=image_id,
            package_version=1,
            request_fingerprint=package_fingerprint,
            status="completed",
            topic_snapshot={},
            copy_snapshot={},
            source_snapshot=[],
            brand_snapshot=[],
            validation_snapshot={"passed": True},
            audit_snapshot={"accepted": True},
            version_snapshot={},
            review_status="approved",
        )
    )
    await session.flush()
    if delivery_mode is None:
        return slot_selection.selected_event_id, None

    job_id = uuid4()
    session.add(
        WeComDeliveryJobModel(
            id=job_id,
            material_package_id=package_id,
            delivery_window_id=None,
            content_slot_selection_id=None,
            sequence_ordinal=None,
            not_before=None,
            expires_at=None,
            recipient_id="default",
            mode=delivery_mode,
            package_version=1,
            content_fingerprint=package_fingerprint,
            request_fingerprint=uuid4().hex + uuid4().hex,
            include_copy=True,
            include_image=True,
            status="delivered",
            text_status="delivered",
            image_status="delivered",
            attempt_count=1,
            next_attempt_at=completed_at,
            completed_at=completed_at,
        )
    )
    await session.flush()
    return slot_selection.selected_event_id, job_id


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_slot_candidate_history_merges_prior_slots_without_changing_legacy_projection(
    integration_context: IntegrationContext,
) -> None:
    target_at = datetime(2095, 8, 16, 23, 30, tzinfo=UTC)
    _window_id, _job_ids, prior_business_date, profile = await _seed_slot_delivery_lane(
        integration_context,
        target_at=target_at,
    )
    business_date = prior_business_date + timedelta(days=1)
    config = TopicScoringConfig(
        profile=profile,
        version="scoring-v1-preview.6-tiered-science-tech-priority",
    )

    async with integration_context.session_factory() as session:
        selected_event_ids = set(
            (
                await session.scalars(
                    select(ContentSlotSelectionModel.selected_event_id)
                    .join(
                        ContentSlotRunModel,
                        ContentSlotRunModel.id == ContentSlotSelectionModel.run_id,
                    )
                    .where(
                        ContentSlotSelectionModel.business_date == prior_business_date,
                        ContentSlotRunModel.scoring_profile == profile,
                    )
                )
            ).all()
        )
        slot_candidates = await load_governed_topic_candidates(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            governed_event_cutoff=target_at + timedelta(days=1),
            config_snapshot=config.as_metadata(),
            include_content_slot_history=True,
        )
        legacy_candidates = await load_governed_topic_candidates(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            governed_event_cutoff=target_at + timedelta(days=1),
            config_snapshot=config.as_metadata(),
        )

    relevant_slot_candidates = tuple(
        candidate for candidate in slot_candidates if candidate.event_id in selected_event_ids
    )
    relevant_legacy_candidates = tuple(
        candidate for candidate in legacy_candidates if candidate.event_id in selected_event_ids
    )
    assert len(relevant_slot_candidates) == 3
    assert len(relevant_legacy_candidates) == 3
    assert all(candidate.days_since_last_selection == 1 for candidate in relevant_slot_candidates)
    assert all(
        candidate.days_since_last_selection is None for candidate in relevant_legacy_candidates
    )
    assert all(
        TopicVetoCode.REPEATED_WITHIN_WINDOW
        in score_topic_candidate(candidate, as_of=target_at, config=config).veto_codes
        for candidate in relevant_slot_candidates
    )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_delivered_repeat_history_filters_slot_job_matrix_and_preserves_theme(
    integration_context: IntegrationContext,
) -> None:
    target_at = datetime(2095, 8, 25, 23, 30, tzinfo=UTC)
    _window_id, job_ids, prior_business_date, profile = await _seed_slot_delivery_lane(
        integration_context,
        target_at=target_at,
    )
    config = TopicScoringConfig(profile=profile)
    business_date = prior_business_date + timedelta(days=1)

    async with integration_context.session_factory() as session:
        selections = tuple(
            (
                await session.scalars(
                    select(ContentSlotSelectionModel)
                    .join(
                        ContentSlotRunModel,
                        ContentSlotRunModel.id == ContentSlotSelectionModel.run_id,
                    )
                    .where(
                        ContentSlotSelectionModel.business_date == prior_business_date,
                        ContentSlotRunModel.scoring_profile == profile,
                    )
                    .order_by(ContentSlotSelectionModel.ordinal)
                )
            ).all()
        )
        assert len(selections) == 3
        await session.execute(
            update(EventClusterVersionModel)
            .where(
                EventClusterVersionModel.id.in_(
                    tuple(selection.selected_event_version_id for selection in selections)
                )
            )
            .values(category_projection=["ai_education_policy"])
        )
        await session.execute(
            update(WeComDeliveryJobModel)
            .where(WeComDeliveryJobModel.id == job_ids[0])
            .values(
                status="delivered",
                text_status="delivered",
                image_status="delivered",
                attempt_count=1,
                completed_at=target_at,
            )
        )
        await session.execute(
            update(WeComDeliveryJobModel)
            .where(WeComDeliveryJobModel.id == job_ids[1])
            .values(status="failed", attempt_count=1, completed_at=target_at)
        )
        await session.execute(
            update(WeComDeliveryJobModel)
            .where(WeComDeliveryJobModel.id == job_ids[2])
            .values(status="failed", attempt_count=1, completed_at=target_at)
        )
        await _add_delivery_variant(
            session,
            source_job_id=job_ids[0],
            package_version=2,
            mode="formal",
            status="delivered",
            completed_at=target_at,
        )
        for package_version, status in enumerate(
            (
                "partial",
                "delivery_unknown",
                "cancelled",
                "delivery_window_expired",
                "queued",
                "running",
            ),
            start=2,
        ):
            await _add_delivery_variant(
                session,
                source_job_id=job_ids[2],
                package_version=package_version,
                mode="formal",
                status=status,
                completed_at=(None if status in {"queued", "running"} else target_at),
            )
        await session.commit()

        candidates = await load_governed_topic_candidates(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            governed_event_cutoff=target_at + timedelta(days=1),
            config_snapshot=config.as_metadata(),
            include_content_slot_history=True,
        )

    candidates_by_event = {candidate.event_id: candidate for candidate in candidates}
    delivered = candidates_by_event[selections[0].selected_event_id]
    failed = candidates_by_event[selections[1].selected_event_id]
    non_delivered = candidates_by_event[selections[2].selected_event_id]
    assert delivered.days_since_last_selection == 1
    assert failed.days_since_last_selection is None
    assert non_delivered.days_since_last_selection is None
    fixture_candidates = tuple(
        candidates_by_event[selection.selected_event_id] for selection in selections
    )
    assert all(candidate.theme_repetition == pytest.approx(1.0) for candidate in fixture_candidates)
    assert (
        TopicVetoCode.REPEATED_WITHIN_WINDOW
        in score_topic_candidate(
            delivered,
            as_of=target_at + timedelta(days=1),
            config=config,
        ).veto_codes
    )
    assert (
        TopicVetoCode.REPEATED_WITHIN_WINDOW
        not in score_topic_candidate(
            non_delivered,
            as_of=target_at + timedelta(days=1),
            config=config,
        ).veto_codes
    )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_delivered_repeat_history_uses_daily_origin_without_newer_failed_or_test_masking(
    integration_context: IntegrationContext,
) -> None:
    target_at = datetime(2095, 8, 23, 23, 30, tzinfo=UTC)
    _window_id, job_ids, slot_business_date, profile = await _seed_slot_delivery_lane(
        integration_context,
        target_at=target_at,
    )
    config = TopicScoringConfig(profile=profile)
    historical_config = TopicScoringConfig(
        profile=profile,
        version="scoring-v1-preview.6-tiered-science-tech-priority",
    )
    business_date = slot_business_date + timedelta(days=1)

    async with integration_context.session_factory() as session:
        selections = tuple(
            (
                await session.scalars(
                    select(ContentSlotSelectionModel)
                    .join(
                        ContentSlotRunModel,
                        ContentSlotRunModel.id == ContentSlotSelectionModel.run_id,
                    )
                    .where(
                        ContentSlotSelectionModel.business_date == slot_business_date,
                        ContentSlotRunModel.scoring_profile == profile,
                    )
                    .order_by(ContentSlotSelectionModel.ordinal)
                )
            ).all()
        )
        assert len(selections) == 3
        delivered_event_id, daily_job_id = await _seed_daily_delivery_origin(
            session,
            slot_selection=selections[0],
            business_date=slot_business_date - timedelta(days=3),
            scoring_profile=profile,
            completed_at=target_at - timedelta(days=3),
            delivery_mode="formal",
        )
        test_only_event_id, test_job_id = await _seed_daily_delivery_origin(
            session,
            slot_selection=selections[1],
            business_date=slot_business_date - timedelta(days=2),
            scoring_profile=profile,
            completed_at=target_at - timedelta(days=2),
            delivery_mode="test",
        )
        absent_event_id, absent_job_id = await _seed_daily_delivery_origin(
            session,
            slot_selection=selections[2],
            business_date=slot_business_date - timedelta(days=1),
            scoring_profile=profile,
            completed_at=target_at - timedelta(days=1),
            delivery_mode=None,
        )
        assert daily_job_id is not None
        assert test_job_id is not None
        assert absent_job_id is None
        await _add_delivery_variant(
            session,
            source_job_id=daily_job_id,
            package_version=2,
            mode="formal",
            status="delivered",
            completed_at=target_at - timedelta(days=3),
        )
        await _add_delivery_variant(
            session,
            source_job_id=daily_job_id,
            package_version=3,
            mode="test",
            status="delivered",
            completed_at=target_at,
        )
        await _add_delivery_variant(
            session,
            source_job_id=daily_job_id,
            package_version=4,
            mode="formal",
            status="failed",
            completed_at=target_at,
        )
        await session.execute(
            update(WeComDeliveryJobModel)
            .where(WeComDeliveryJobModel.id == job_ids[0])
            .values(status="failed", attempt_count=1, completed_at=target_at)
        )
        await session.commit()

        daily_candidates = await load_governed_topic_candidates(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            governed_event_cutoff=target_at + timedelta(days=1),
            config_snapshot=config.as_metadata(),
        )
        slot_candidates = await load_governed_topic_candidates(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            governed_event_cutoff=target_at + timedelta(days=1),
            config_snapshot=config.as_metadata(),
            include_content_slot_history=True,
        )
        historical_candidates = await load_governed_topic_candidates(
            session,
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            governed_event_cutoff=target_at + timedelta(days=1),
            config_snapshot=historical_config.as_metadata(),
        )
        day_six_candidates = await load_governed_topic_candidates(
            session,
            business_date=slot_business_date + timedelta(days=3),
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            governed_event_cutoff=target_at + timedelta(days=3),
            config_snapshot=config.as_metadata(),
            include_content_slot_history=True,
        )
        day_seven_candidates = await load_governed_topic_candidates(
            session,
            business_date=slot_business_date + timedelta(days=4),
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            governed_event_cutoff=target_at + timedelta(days=4),
            config_snapshot=config.as_metadata(),
            include_content_slot_history=True,
        )

    daily_by_event = {candidate.event_id: candidate for candidate in daily_candidates}
    slot_by_event = {candidate.event_id: candidate for candidate in slot_candidates}
    historical_by_event = {candidate.event_id: candidate for candidate in historical_candidates}
    day_six_by_event = {candidate.event_id: candidate for candidate in day_six_candidates}
    day_seven_by_event = {candidate.event_id: candidate for candidate in day_seven_candidates}
    assert daily_by_event[delivered_event_id].days_since_last_selection == 4
    assert slot_by_event[delivered_event_id].days_since_last_selection == 4
    assert daily_by_event[test_only_event_id].days_since_last_selection is None
    assert slot_by_event[test_only_event_id].days_since_last_selection is None
    assert daily_by_event[absent_event_id].days_since_last_selection is None
    assert slot_by_event[absent_event_id].days_since_last_selection is None
    assert historical_by_event[delivered_event_id].days_since_last_selection == 4
    assert historical_by_event[test_only_event_id].days_since_last_selection == 3
    assert historical_by_event[absent_event_id].days_since_last_selection == 2
    day_six = day_six_by_event[delivered_event_id]
    day_seven = day_seven_by_event[delivered_event_id]
    assert day_six.days_since_last_selection == 6
    assert day_seven.days_since_last_selection == 7
    assert (
        TopicVetoCode.REPEATED_WITHIN_WINDOW
        in score_topic_candidate(
            day_six,
            as_of=target_at + timedelta(days=3),
            config=config,
        ).veto_codes
    )
    assert (
        TopicVetoCode.REPEATED_WITHIN_WINDOW
        not in score_topic_candidate(
            day_seven,
            as_of=target_at + timedelta(days=4),
            config=config,
        ).veto_codes
    )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_postgres_slot_lineage_and_delivery_identity_reject_cross_wiring(
    integration_context: IntegrationContext,
) -> None:
    target_at = datetime(2095, 8, 18, 23, 30, tzinfo=UTC)
    _window_id, job_ids, business_date, profile = await _seed_slot_delivery_lane(
        integration_context,
        target_at=target_at,
    )
    unrelated_acquisition_id, _candidate_ids = await _create_acquisition_fixture(
        integration_context,
        candidate_count=1,
    )
    async with integration_context.session_factory() as session:
        run_id = await session.scalar(
            select(ContentSlotRunModel.id).where(
                ContentSlotRunModel.business_date == business_date,
                ContentSlotRunModel.scoring_profile == profile,
            )
        )
        selections = tuple(
            (
                await session.scalars(
                    select(ContentSlotSelectionModel)
                    .where(ContentSlotSelectionModel.run_id == run_id)
                    .order_by(ContentSlotSelectionModel.ordinal)
                )
            ).all()
        )
        first_copy_id = await session.scalar(
            select(CopyGenerationRunModel.id).where(
                CopyGenerationRunModel.content_slot_selection_id == selections[0].id
            )
        )
    assert run_id is not None
    assert len(selections) == 3
    assert first_copy_id is not None

    async with integration_context.session_factory() as session:
        with pytest.raises(
            IntegrityError,
            match=r"fk_content_slot_runs_(acquisition_identity|governance_lineage)",
        ):
            await session.execute(
                update(ContentSlotRunModel)
                .where(ContentSlotRunModel.id == run_id)
                .values(acquisition_run_id=unrelated_acquisition_id)
            )
            await session.commit()

    async with integration_context.session_factory() as session:
        with pytest.raises(
            IntegrityError,
            match="fk_copy_generation_runs_slot_origin_identity",
        ):
            await session.execute(
                update(CopyGenerationRunModel)
                .where(CopyGenerationRunModel.id == first_copy_id)
                .values(
                    selected_event_id=selections[1].selected_event_id,
                    selected_event_version_id=selections[1].selected_event_version_id,
                )
            )
            await session.commit()

    async with integration_context.session_factory() as session:
        with pytest.raises(IntegrityError, match="fk_wecom_delivery_jobs_slot_ordinal"):
            await session.execute(
                update(WeComDeliveryJobModel)
                .where(WeComDeliveryJobModel.id == job_ids[0])
                .values(sequence_ordinal=2)
            )
            await session.commit()

    async with integration_context.session_factory() as session:
        with pytest.raises(IntegrityError, match="fk_wecom_delivery_jobs_window_identity"):
            await session.execute(
                update(WeComDeliveryJobModel)
                .where(WeComDeliveryJobModel.id == job_ids[0])
                .values(not_before=target_at + timedelta(seconds=1))
            )
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_postgres_slot_lane_serializes_dispatchers_and_persists_gap_and_expiry(
    integration_context: IntegrationContext,
) -> None:
    target_at = datetime(2095, 8, 13, 23, 30, tzinfo=UTC)
    window_id, job_ids, _business_date, _profile = await _seed_slot_delivery_lane(
        integration_context,
        target_at=target_at,
    )
    clock = [target_at - timedelta(seconds=1)]
    settings = integration_context.settings.model_copy(
        update={"wecom_lease_seconds": 120, "wecom_max_attempts": 3}
    )

    def now() -> datetime:
        return clock[0]

    first_executor = WeComDeliveryExecutor(
        session_factory=integration_context.session_factory,
        client=object(),  # type: ignore[arg-type]
        image_store=object(),  # type: ignore[arg-type]
        settings=settings,
        clock=now,
    )
    second_executor = WeComDeliveryExecutor(
        session_factory=integration_context.session_factory,
        client=object(),  # type: ignore[arg-type]
        image_store=object(),  # type: ignore[arg-type]
        settings=settings,
        clock=now,
    )

    assert await first_executor._claim("too-early") is None

    clock[0] = target_at
    contenders = await asyncio.gather(
        first_executor._claim("dispatcher-one"),
        second_executor._claim("dispatcher-two"),
    )
    claims = [claim for claim in contenders if claim is not None]
    assert len(claims) == 1
    assert claims[0].job_id == job_ids[0]

    async with integration_context.session_factory() as session:
        window = await session.get(WeComDeliveryWindowModel, window_id)
        jobs = tuple(
            (
                await session.scalars(
                    select(WeComDeliveryJobModel)
                    .where(WeComDeliveryJobModel.id.in_(job_ids))
                    .order_by(WeComDeliveryJobModel.sequence_ordinal)
                )
            ).all()
        )
    assert window is not None
    assert window.next_allowed_at == target_at + timedelta(seconds=60)
    assert [job.status for job in jobs] == ["running", "queued", "queued"]

    clock[0] = target_at + timedelta(seconds=59)
    assert await second_executor._claim("still-throttled") is None

    clock[0] = target_at + timedelta(seconds=60)
    second_claim = await second_executor._claim("after-gap")
    assert second_claim is not None
    assert second_claim.job_id == job_ids[1]

    clock[0] = target_at + timedelta(hours=1)
    assert await first_executor._claim("at-expiry") is None
    async with integration_context.session_factory() as session:
        final_jobs = tuple(
            (
                await session.scalars(
                    select(WeComDeliveryJobModel)
                    .where(WeComDeliveryJobModel.id.in_(job_ids))
                    .order_by(WeComDeliveryJobModel.sequence_ordinal)
                )
            ).all()
        )
    assert [job.status for job in final_jobs] == [
        "delivery_unknown",
        "delivery_unknown",
        "delivery_window_expired",
    ]
    assert final_jobs[2].attempt_count == 0
    assert final_jobs[2].last_error_code == "delivery_window_expired"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_slot_stale_running_becomes_unknown_without_blocking_next_ready_ordinal(
    integration_context: IntegrationContext,
) -> None:
    target_at = datetime(2095, 8, 20, 23, 30, tzinfo=UTC)
    _window_id, job_ids, _business_date, _profile = await _seed_slot_delivery_lane(
        integration_context,
        target_at=target_at,
    )
    clock = [target_at]
    settings = integration_context.settings.model_copy(
        update={"wecom_lease_seconds": 30, "wecom_max_attempts": 3}
    )
    executor = WeComDeliveryExecutor(
        session_factory=integration_context.session_factory,
        client=object(),  # type: ignore[arg-type]
        image_store=object(),  # type: ignore[arg-type]
        settings=settings,
        clock=lambda: clock[0],
    )

    first = await executor._claim("first-dispatcher")
    assert first is not None
    assert first.job_id == job_ids[0]

    clock[0] = target_at + timedelta(seconds=60)
    second = await executor._claim("replacement-dispatcher")
    assert second is not None
    assert second.job_id == job_ids[1]

    async with integration_context.session_factory() as session:
        first_job = await session.get(WeComDeliveryJobModel, job_ids[0])
        unknown_attempt_count = await session.scalar(
            select(func.count())
            .select_from(WeComDeliveryAttemptModel)
            .where(
                WeComDeliveryAttemptModel.job_id == job_ids[0],
                WeComDeliveryAttemptModel.result_state == "unknown",
            )
        )
    assert first_job is not None
    assert first_job.status == "delivery_unknown"
    assert first_job.text_status == "unknown"
    assert first_job.attempt_count == 1
    assert first_job.last_error_code == "delivery_lease_expired_after_start"
    assert unknown_attempt_count == 1


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_slot_copy_reconciliation_creates_one_independent_run_per_selection(
    integration_context: IntegrationContext,
) -> None:
    target_at = datetime(2095, 8, 14, 23, 30, tzinfo=UTC)
    window_id, job_ids, business_date, profile = await _seed_slot_delivery_lane(
        integration_context,
        target_at=target_at,
    )
    async with integration_context.session_factory() as session:
        selection_ids = tuple(
            (
                await session.scalars(
                    select(ContentSlotSelectionModel.id).where(
                        ContentSlotSelectionModel.business_date == business_date,
                        ContentSlotSelectionModel.content_slot == "morning",
                    )
                )
            ).all()
        )
        copy_run_ids = tuple(
            (
                await session.scalars(
                    select(CopyGenerationRunModel.id).where(
                        CopyGenerationRunModel.content_slot_selection_id.in_(selection_ids)
                    )
                )
            ).all()
        )
        await session.execute(
            delete(WeComDeliveryJobModel).where(WeComDeliveryJobModel.id.in_(job_ids))
        )
        await session.execute(
            delete(WeComDeliveryWindowModel).where(WeComDeliveryWindowModel.id == window_id)
        )
        await session.execute(
            delete(MaterialPackageModel).where(MaterialPackageModel.run_id.in_(copy_run_ids))
        )
        await session.execute(
            delete(ImageArtifactModel).where(ImageArtifactModel.run_id.in_(copy_run_ids))
        )
        await session.execute(
            update(CopyGenerationRunModel)
            .where(CopyGenerationRunModel.id.in_(copy_run_ids))
            .values(active_draft_version_id=None)
        )
        await session.execute(
            delete(CopyDraftVersionModel).where(CopyDraftVersionModel.run_id.in_(copy_run_ids))
        )
        await session.execute(
            delete(CopyGenerationRunModel).where(CopyGenerationRunModel.id.in_(copy_run_ids))
        )
        await session.commit()

    settings = integration_context.settings.model_copy(
        update={"content_enabled": True, "content_slot_mode_enabled": True}
    )
    repository = PostgresCopyGenerationRepository(integration_context.session_factory)
    bundle = build_copy_version_bundle(settings)

    assert (
        await repository.reconcile_ready_slot_topics(
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            version_bundle=bundle,
        )
        == 3
    )
    assert (
        await repository.reconcile_ready_slot_topics(
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            version_bundle=bundle,
        )
        == 0
    )
    async with integration_context.session_factory() as session:
        rows = tuple(
            (
                await session.scalars(
                    select(CopyGenerationRunModel).where(
                        CopyGenerationRunModel.content_slot_selection_id.in_(selection_ids),
                        CopyGenerationRunModel.version_fingerprint == bundle.fingerprint,
                    )
                )
            ).all()
        )
        job_count = await session.scalar(
            select(func.count())
            .select_from(CopyGenerationJobModel)
            .where(CopyGenerationJobModel.run_id.in_(tuple(row.id for row in rows)))
        )
        checkpoint_count = await session.scalar(
            select(func.count())
            .select_from(CopyGenerationCheckpointModel)
            .where(CopyGenerationCheckpointModel.run_id.in_(tuple(row.id for row in rows)))
        )

    assert len(rows) == 3
    assert {row.content_slot_selection_id for row in rows} == set(selection_ids)
    assert all(row.daily_topic_selection_id is None for row in rows)
    assert all(row.topic_selection_run_id is None for row in rows)
    assert job_count == 3
    assert checkpoint_count == 3
