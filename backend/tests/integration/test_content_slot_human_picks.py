from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.application.services.copy_generation import build_copy_version_bundle
from app.application.services.wecom_delivery import _ensure_slot_delivery_window
from app.infrastructure.db.content_slot_human_picks import (
    HUMAN_PICK_DELIVERY_WINDOW,
    HumanPickRejectedError,
    create_human_pick,
)
from app.infrastructure.db.content_slots import (
    _count_same_day_scheduled_selections,
    list_content_slot_runs_for_date,
)
from app.infrastructure.db.copy_generation import PostgresCopyGenerationRepository
from app.infrastructure.db.models import (
    ContentSlotRunModel,
    ContentSlotScoreModel,
    ContentSlotSelectionModel,
    CopyGenerationCheckpointModel,
    CopyGenerationJobModel,
    CopyGenerationRunModel,
    EventClusterModel,
    EventClusterVersionModel,
    WeComDeliveryJobModel,
    WeComDeliveryWindowModel,
)
from sqlalchemy import delete, select, update

from .conftest import IntegrationContext
from .test_wecom_slot_delivery_concurrency import _seed_slot_delivery_lane


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _purge_human_picks(integration_context: IntegrationContext) -> AsyncIterator[None]:
    """Later migration tests downgrade the shared database; 0051 refuses while picks exist."""
    yield
    async with integration_context.session_factory() as session:
        human_runs = select(ContentSlotRunModel.id).where(ContentSlotRunModel.trigger == "human")
        selections = select(ContentSlotSelectionModel.id).where(
            ContentSlotSelectionModel.run_id.in_(human_runs)
        )
        copy_runs = select(CopyGenerationRunModel.id).where(
            CopyGenerationRunModel.content_slot_selection_id.in_(selections)
        )
        await session.execute(
            delete(CopyGenerationCheckpointModel).where(
                CopyGenerationCheckpointModel.run_id.in_(copy_runs)
            )
        )
        await session.execute(
            delete(CopyGenerationJobModel).where(CopyGenerationJobModel.run_id.in_(copy_runs))
        )
        await session.execute(
            delete(CopyGenerationRunModel).where(CopyGenerationRunModel.id.in_(copy_runs))
        )
        await session.execute(
            delete(WeComDeliveryWindowModel).where(WeComDeliveryWindowModel.lane_key != "slot")
        )
        await session.execute(
            delete(ContentSlotSelectionModel).where(ContentSlotSelectionModel.id.in_(selections))
        )
        await session.execute(
            delete(ContentSlotScoreModel).where(ContentSlotScoreModel.run_id.in_(human_runs))
        )
        await session.execute(
            delete(ContentSlotRunModel).where(ContentSlotRunModel.trigger == "human")
        )
        await session.commit()


async def _add_rejected_candidate(
    context: IntegrationContext, *, run_id: UUID, rank: int, veto: bool
) -> UUID:
    """Add a scored but unselected event (optionally vetoed) to an existing AI slot run."""
    async with context.session_factory() as session:
        run = await session.get(ContentSlotRunModel, run_id)
        assert run is not None
        template = await session.scalar(
            select(EventClusterVersionModel)
            .join(
                ContentSlotScoreModel,
                ContentSlotScoreModel.event_version_id == EventClusterVersionModel.id,
            )
            .where(ContentSlotScoreModel.run_id == run_id)
            .limit(1)
        )
        assert template is not None
        event_id = uuid4()
        version_id = uuid4()
        session.add(EventClusterModel(id=event_id, status="active"))
        await session.flush()
        session.add(
            EventClusterVersionModel(
                id=version_id,
                event_id=event_id,
                version=1,
                representative_article_id=template.representative_article_id,
                representative_title=f"Rejected fixture {rank}",
                summary_projection={},
                event_time_start=template.event_time_start,
                event_time_end=None,
                event_time_precision="exact",
                member_set_hash=f"{rank + 90:064x}",
                source_diversity=1,
                category_projection=[],
                entity_projection=[],
                clustering_policy_version="human-pick-fixture-v1",
                version_bundle_fingerprint=f"{rank + 90:064x}",
                created_by_run_id=template.created_by_run_id,
            )
        )
        await session.flush()
        session.add(
            ContentSlotScoreModel(
                id=uuid4(),
                run_id=run_id,
                event_id=event_id,
                event_version_id=version_id,
                raw_features={},
                normalized_features={},
                weights={},
                penalty_weights={},
                positive_components={},
                penalty_components={},
                total=0.4,
                threshold=0.6,
                passes_threshold=False,
                eligible=not veto,
                veto_codes=["negative_incident"] if veto else [],
                explanation={"scoring_version": "fixture", "scoring_profile": run.scoring_profile},
                slot_affinity=0.0,
                slot_affinity_reasons=[],
                same_day_excluded=False,
                same_day_exclusion_reason=None,
                final_ordering_value=0.4,
                final_ordering_key=f"rejected-{rank}",
                deterministic_rank=rank,
                rank=rank,
                selected_ordinal=None,
            )
        )
        await session.commit()
    return event_id


async def _scheduled_run_id(context: IntegrationContext, business_date: object) -> UUID:
    async with context.session_factory() as session:
        run_id = await session.scalar(
            select(ContentSlotRunModel.id).where(
                ContentSlotRunModel.business_date == business_date,
                ContentSlotRunModel.trigger == "scheduled",
            )
        )
    assert run_id is not None
    return run_id


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_human_pick_creates_extra_one_item_run_with_own_lane(
    integration_context: IntegrationContext,
) -> None:
    # 00:30 UTC = 08:30 Asia/Shanghai; the scheduled morning slot already succeeded.
    target_at = datetime(2096, 3, 2, 23, 30, tzinfo=UTC)
    slot_window_id, _, business_date, profile = await _seed_slot_delivery_lane(
        integration_context, target_at=target_at
    )
    base_run_id = await _scheduled_run_id(integration_context, business_date)
    event_id = await _add_rejected_candidate(
        integration_context, run_id=base_run_id, rank=4, veto=True
    )
    now = target_at + timedelta(hours=1)

    async with integration_context.session_factory() as session:
        result = await create_human_pick(
            session,
            source_run_id=base_run_id,
            event_id=event_id,
            note="运营认为值得推",
            now=now,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
        )
    assert result.created
    run_id = result.run.id

    async with integration_context.session_factory() as session:
        run = await session.get(ContentSlotRunModel, run_id)
        assert run is not None
        base = await session.get(ContentSlotRunModel, base_run_id)
        assert base is not None
        assert run.trigger == "human"
        assert run.status == "succeeded"
        assert run.scoring_profile == profile
        assert run.content_slot == base.content_slot
        assert run.acquisition_run_id == base.acquisition_run_id
        assert run.governance_run_id == base.governance_run_id
        assert (run.item_limit, run.selected_count, run.unfilled_count) == (1, 1, 0)
        assert run.target_at == now
        assert run.expires_at == now + HUMAN_PICK_DELIVERY_WINDOW
        assert run.slot_policy_version == "human-pick-v1"
        assert run.slot_policy_snapshot["note"] == "运营认为值得推"
        assert run.slot_policy_snapshot["ai_verdict"]["eligible"] is False
        assert run.slot_policy_snapshot["ai_verdict"]["veto_codes"] == ["negative_incident"]
        score = await session.scalar(
            select(ContentSlotScoreModel).where(ContentSlotScoreModel.run_id == run_id)
        )
        assert score is not None
        assert (score.rank, score.selected_ordinal, score.eligible, score.veto_codes) == (
            1,
            1,
            True,
            [],
        )
        assert score.total == pytest.approx(0.4)
        selection = await session.scalar(
            select(ContentSlotSelectionModel).where(ContentSlotSelectionModel.run_id == run_id)
        )
        assert selection is not None
        assert (selection.ordinal, selection.selected_event_id) == (1, event_id)

        # Own delivery lane with the pick's own times; the scheduled lane is untouched.
        window = await _ensure_slot_delivery_window(
            session, run=run, recipient_id="default", provider="self_built_app", gap_seconds=60
        )
        assert window.id != slot_window_id
        assert window.lane_key == f"human-{run_id.hex}"
        assert (window.target_at, window.expires_at) == (run.target_at, run.expires_at)
        scheduled = await _ensure_slot_delivery_window(
            session, run=base, recipient_id="default", provider="self_built_app", gap_seconds=60
        )
        assert scheduled.id == slot_window_id
        assert scheduled.lane_key == "slot"
        await session.commit()

        # Human picks are extra: a later scheduled slot still sees only the 3 AI picks.
        later = ContentSlotRunModel(
            id=uuid4(), business_date=business_date, timezone="Asia/Shanghai"
        )
        assert await _count_same_day_scheduled_selections(session, later) == 3
        editions = await list_content_slot_runs_for_date(
            session, business_date=business_date, timezone="Asia/Shanghai", scoring_profile=profile
        )
        assert [projection.run.id for projection in editions] == [base_run_id]

    # Repeat press returns the same pick instead of a second push.
    async with integration_context.session_factory() as session:
        again = await create_human_pick(
            session,
            source_run_id=base_run_id,
            event_id=event_id,
            note=None,
            now=now + timedelta(minutes=1),
            timezone="Asia/Shanghai",
            scoring_profile=profile,
        )
    assert not again.created
    assert again.run.id == run_id

    # The existing copy reconciler picks the human selection up like any AI selection.
    settings = integration_context.settings.model_copy(
        update={"content_enabled": True, "content_slot_mode_enabled": True}
    )
    repository = PostgresCopyGenerationRepository(integration_context.session_factory)
    created = await repository.reconcile_ready_slot_topics(
        business_date=business_date,
        timezone="Asia/Shanghai",
        scoring_profile=profile,
        version_bundle=build_copy_version_bundle(settings),
    )
    assert created == 1
    async with integration_context.session_factory() as session:
        copy_run = await session.scalar(
            select(CopyGenerationRunModel).where(
                CopyGenerationRunModel.content_slot_selection_id == selection.id
            )
        )
        assert copy_run is not None
        assert copy_run.selected_event_id == event_id
        lanes = (
            await session.scalars(
                select(WeComDeliveryWindowModel.lane_key).where(
                    WeComDeliveryWindowModel.business_date == business_date
                )
            )
        ).all()
        assert sorted(lanes) == sorted(["slot", f"human-{run_id.hex}"])


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_human_pick_refuses_duplicates_busy_slots_and_late_or_unknown_items(
    integration_context: IntegrationContext,
) -> None:
    target_at = datetime(2096, 3, 9, 23, 30, tzinfo=UTC)
    _, _, business_date, profile = await _seed_slot_delivery_lane(
        integration_context, target_at=target_at
    )
    base_run_id = await _scheduled_run_id(integration_context, business_date)
    event_id = await _add_rejected_candidate(
        integration_context, run_id=base_run_id, rank=4, veto=False
    )
    now = target_at + timedelta(hours=1)

    async def pick(target: UUID, *, at: datetime = now, run: UUID = base_run_id) -> None:
        async with integration_context.session_factory() as session:
            await create_human_pick(
                session,
                source_run_id=run,
                event_id=target,
                note=None,
                now=at,
                timezone="Asia/Shanghai",
                scoring_profile=profile,
            )

    async with integration_context.session_factory() as session:
        selected_event_id = await session.scalar(
            select(ContentSlotSelectionModel.selected_event_id).where(
                ContentSlotSelectionModel.run_id == base_run_id
            )
        )
    assert selected_event_id is not None
    with pytest.raises(HumanPickRejectedError) as already:
        await pick(selected_event_id)
    assert already.value.code == "human_pick_already_selected"

    with pytest.raises(Exception) as unknown:
        await pick(uuid4())
    assert getattr(unknown.value, "status_code", None) == 404

    # 23:10 business time: downstream would roll over to the next business date.
    late = datetime(2096, 3, 10, 15, 10, tzinfo=UTC)
    with pytest.raises(HumanPickRejectedError) as too_late:
        await pick(event_id, at=late)
    assert too_late.value.code == "human_pick_too_late"

    async with integration_context.session_factory() as session:
        base = await session.get(ContentSlotRunModel, base_run_id)
        assert base is not None
        base.status = "running"
        await session.commit()
    try:
        with pytest.raises(HumanPickRejectedError) as busy:
            await pick(event_id)
        assert busy.value.code == "human_pick_slot_busy"
    finally:
        async with integration_context.session_factory() as session:
            base = await session.get(ContentSlotRunModel, base_run_id)
            assert base is not None
            base.status = "succeeded"
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_human_pick_refuses_story_with_prior_formal_delivery(
    integration_context: IntegrationContext,
) -> None:
    # Seed yesterday's AI slot whose three items have queued formal deliveries, then try to
    # human-pick one of them today.
    yesterday = datetime(2096, 3, 15, 23, 30, tzinfo=UTC)
    _, _, old_date, profile = await _seed_slot_delivery_lane(
        integration_context, target_at=yesterday
    )
    old_run_id = await _scheduled_run_id(integration_context, old_date)
    async with integration_context.session_factory() as session:
        delivered_event_id = await session.scalar(
            select(ContentSlotSelectionModel.selected_event_id).where(
                ContentSlotSelectionModel.run_id == old_run_id
            )
        )
    assert delivered_event_id is not None
    today = yesterday + timedelta(days=1)
    await _seed_slot_delivery_lane(integration_context, target_at=today)
    async with integration_context.session_factory() as session:
        # The fixture cancels older queued jobs; make yesterday's send a real delivery.
        await session.execute(
            update(WeComDeliveryJobModel)
            .where(
                WeComDeliveryJobModel.content_slot_selection_id.in_(
                    select(ContentSlotSelectionModel.id).where(
                        ContentSlotSelectionModel.run_id == old_run_id
                    )
                )
            )
            .values(status="delivered", text_status="delivered", image_status="delivered")
        )
        await session.commit()

    async with integration_context.session_factory() as session:
        with pytest.raises(HumanPickRejectedError) as delivered:
            await create_human_pick(
                session,
                source_run_id=old_run_id,
                event_id=delivered_event_id,
                note=None,
                now=today + timedelta(hours=1),
                timezone="Asia/Shanghai",
                scoring_profile=profile,
            )
    assert delivered.value.code == "human_pick_already_delivered"
