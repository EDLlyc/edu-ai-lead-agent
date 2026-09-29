"""The daily long-image ceiling belongs to the scheduled slots; human picks are extra."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.application.services.wecom_news_infographic import NewsInfographicProducer
from app.core.config import Settings
from app.infrastructure.db.content_slot_human_picks import create_human_pick
from app.infrastructure.db.models import (
    ContentSlotRunModel,
    ContentSlotScoreModel,
    ContentSlotSelectionModel,
    MaterialPackageModel,
    NewsInfographicJobModel,
    WeComDeliveryJobModel,
)
from sqlalchemy import delete, func, select

from .conftest import IntegrationContext
from .test_content_slot_human_picks import _add_rejected_candidate, _scheduled_run_id
from .test_wecom_slot_delivery_concurrency import _add_delivery_variant, _seed_slot_delivery_lane


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _purge_human_picks(integration_context: IntegrationContext) -> AsyncIterator[None]:
    """Later migration tests downgrade the shared database; 0051 refuses while picks exist."""
    yield
    async with integration_context.session_factory() as session:
        human_runs = select(ContentSlotRunModel.id).where(ContentSlotRunModel.trigger == "human")
        selections = select(ContentSlotSelectionModel.id).where(
            ContentSlotSelectionModel.run_id.in_(human_runs)
        )
        await session.execute(
            delete(NewsInfographicJobModel).where(
                NewsInfographicJobModel.content_slot_selection_id.in_(selections)
            )
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


async def _running_poster(
    context: IntegrationContext,
    *,
    base_job_id: UUID,
    selection_id: UUID,
    business_date: date,
    now: datetime,
) -> tuple[UUID, UUID]:
    """A leased poster job just before its paid image call."""
    token = uuid4()
    async with context.session_factory() as session:
        base = await session.get(WeComDeliveryJobModel, base_job_id)
        assert base is not None
        package = await session.get(MaterialPackageModel, base.material_package_id)
        assert package is not None
        selection = await session.get(ContentSlotSelectionModel, selection_id)
        assert selection is not None
        job = NewsInfographicJobModel(
            id=uuid4(),
            base_job_id=base.id,
            material_package_id=package.id,
            copy_generation_run_id=package.run_id,
            content_slot_selection_id=selection.id,
            sequence_ordinal=selection.ordinal,
            selected_event_id=selection.selected_event_id,
            selected_event_version_id=selection.selected_event_version_id,
            business_date=business_date,
            content_slot=selection.content_slot,
            recipient_id="default",
            provider="group_webhook",
            package_version=package.package_version,
            policy_fingerprint=uuid4().hex + uuid4().hex,
            input_fingerprint="a" * 64,
            status="running",
            stage="preflight",
            lease_owner="synthetic-ceiling-worker",
            lease_token=token,
            lease_expires_at=now + timedelta(minutes=10),
        )
        session.add(job)
        await session.commit()
        return job.id, token


async def _image_intents(context: IntegrationContext, business_date: date) -> int:
    async with context.session_factory() as session:
        count = await session.scalar(
            select(func.count(NewsInfographicJobModel.id)).where(
                NewsInfographicJobModel.business_date == business_date,
                NewsInfographicJobModel.image_intent_at.is_not(None),
            )
        )
    return count or 0


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_human_pick_posters_are_outside_the_scheduled_daily_ceiling(
    integration_context: IntegrationContext,
) -> None:
    # 23:30 UTC = 07:30 Asia/Shanghai of the next day; the scheduled morning slot succeeded.
    target_at = datetime(2097, 4, 10, 23, 30, tzinfo=UTC)
    now = target_at + timedelta(hours=1)
    _, job_ids, business_date, profile = await _seed_slot_delivery_lane(
        integration_context, target_at=target_at
    )
    base_run_id = await _scheduled_run_id(integration_context, business_date)

    scheduled: list[tuple[UUID, UUID]] = []
    for base_job_id in job_ids:
        async with integration_context.session_factory() as session:
            base = await session.get(WeComDeliveryJobModel, base_job_id)
            assert base is not None and base.content_slot_selection_id is not None
            selection_id = base.content_slot_selection_id
        scheduled.append(
            await _running_poster(
                integration_context,
                base_job_id=base_job_id,
                selection_id=selection_id,
                business_date=business_date,
                now=now,
            )
        )

    human: list[tuple[UUID, UUID]] = []
    for rank in (4, 5):
        event_id = await _add_rejected_candidate(
            integration_context, run_id=base_run_id, rank=rank, veto=False
        )
        async with integration_context.session_factory() as session:
            pick = await create_human_pick(
                session,
                source_run_id=base_run_id,
                event_id=event_id,
                note=None,
                now=now,
                timezone="Asia/Shanghai",
                scoring_profile=profile,
            )
            assert pick.created and pick.run.trigger == "human"
            selection_id = pick.selection.id
            # The poster only needs a distinct delivery job to reserve.
            base_job_id = await _add_delivery_variant(
                session,
                source_job_id=job_ids[0],
                package_version=rank,
                mode="formal",
                status="queued",
            )
            await session.commit()
        human.append(
            await _running_poster(
                integration_context,
                base_job_id=base_job_id,
                selection_id=selection_id,
                business_date=business_date,
                now=now,
            )
        )

    def producer(**limits: int) -> NewsInfographicProducer:
        return NewsInfographicProducer(
            session_factory=integration_context.session_factory,
            image_store=SimpleNamespace(),
            models=SimpleNamespace(image_model="synthetic-image", copy_model="synthetic-copy"),
            settings=Settings(_env_file=None, **limits),
            clock=lambda: now,
        )

    tight = producer(
        wecom_infographic_daily_image_limit=2, wecom_infographic_human_pick_daily_image_limit=1
    )
    assert await tight._intent(*scheduled[0], "image", "b" * 64)
    assert await tight._intent(*scheduled[1], "image", "b" * 64)
    assert not await tight._intent(*scheduled[2], "image", "b" * 64)

    # The scheduled slots used their whole allowance; the operator's pick still gets its poster.
    assert await tight._intent(*human[0], "image", "b" * 64)
    assert await _image_intents(integration_context, business_date) == 3
    # Only a runaway caller reaches the pick's own guard.
    assert not await tight._intent(*human[1], "image", "b" * 64)

    # The pick did not use scheduled allowance: one more scheduled call fits a limit of three.
    roomy = producer(
        wecom_infographic_daily_image_limit=3, wecom_infographic_human_pick_daily_image_limit=1
    )
    assert await roomy._intent(*scheduled[2], "image", "b" * 64)
    assert not await roomy._intent(*human[1], "image", "b" * 64)
    assert await _image_intents(integration_context, business_date) == 4
