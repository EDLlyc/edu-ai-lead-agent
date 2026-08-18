from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from app.api_main import app
from app.application.services.content_slots import ContentSlotExecutor
from app.infrastructure.db.content_slots import PostgresContentSlotRepository
from app.infrastructure.db.models import (
    AcquisitionRunModel,
    ContentSlotRunModel,
    GovernanceRunModel,
    WeComDeliveryJobModel,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from .conftest import IntegrationContext
from .test_wecom_slot_delivery_concurrency import _seed_slot_delivery_lane


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_content_slot_api_projects_disabled_missing_and_durable_empty_slot(
    integration_context: IntegrationContext,
) -> None:
    suffix = uuid4().hex[:10]
    business_date = date(2096, 8, 14)
    profile = f"slot-api-{suffix}"
    base_settings = integration_context.settings.model_copy(
        update={
            "content_enabled": True,
            "content_scoring_profile": profile,
            "content_slot_mode_enabled": False,
            "content_morning_enabled": False,
            "content_noon_enabled": False,
            "content_evening_enabled": False,
        }
    )
    previous_settings = app.state.settings
    previous_factory = app.state.session_factory
    app.state.settings = base_settings
    app.state.session_factory = integration_context.session_factory
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            disabled = await client.get(
                f"/api/v1/content-editions/{business_date.isoformat()}",
                params={"profile": profile},
            )
            rejected = await client.post(
                "/api/v1/content-slot-runs",
                json={"business_date": business_date.isoformat(), "content_slot": "morning"},
            )
        assert disabled.status_code == 200
        assert disabled.json()["slot_mode_enabled"] is False
        assert [item["state"] for item in disabled.json()["slots"]] == [
            "disabled",
            "disabled",
            "disabled",
        ]
        assert rejected.status_code == 409

        enabled_settings = base_settings.model_copy(
            update={
                "content_slot_mode_enabled": True,
                "content_morning_enabled": True,
            }
        )
        app.state.settings = enabled_settings
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            missing = await client.get(
                f"/api/v1/content-editions/{business_date.isoformat()}",
                params={"profile": profile},
            )
            not_ready = await client.post(
                "/api/v1/content-slot-runs",
                json={"business_date": business_date.isoformat(), "content_slot": "morning"},
            )
        assert missing.json()["slots"][0]["state"] == "missing"
        assert not_ready.status_code == 409

        ready_at = datetime.now(UTC)
        acquisition_id = uuid4()
        governance_id = uuid4()
        async with integration_context.session_factory() as session:
            session.add(
                AcquisitionRunModel(
                    id=acquisition_id,
                    trigger="scheduled",
                    business_date=business_date,
                    timezone="Asia/Shanghai",
                    content_slot="morning",
                    acquisition_version=f"slot-api-acquisition-{suffix}",
                    manual_idempotency_key=None,
                    status="succeeded",
                    completed_at=ready_at,
                )
            )
            session.add(
                GovernanceRunModel(
                    id=governance_id,
                    trigger="acquisition",
                    acquisition_run_id=acquisition_id,
                    timezone="Asia/Shanghai",
                    profile_fingerprint=uuid4().hex + uuid4().hex,
                    version_bundle={},
                    status="succeeded",
                    completed_at=ready_at,
                )
            )
            await session.commit()

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/v1/content-slot-runs",
                json={"business_date": business_date.isoformat(), "content_slot": "morning"},
            )
        assert created.status_code == 202
        run_id = UUID(created.json()["id"])
        assert created.json()["content_slot"] == "morning"
        assert created.json()["selected_count"] == 0
        assert created.json()["rerank_config"]["enabled"] is False
        assert created.json()["rerank"]["outcome"] == "not_applied"

        async with integration_context.session_factory() as session:
            await session.execute(
                update(ContentSlotRunModel)
                .where(ContentSlotRunModel.id == run_id)
                .values(governed_event_cutoff=datetime(1970, 1, 1, tzinfo=UTC))
            )
            await session.commit()
        repository = PostgresContentSlotRepository(integration_context.session_factory)
        executor = ContentSlotExecutor(repository, enabled_settings)
        assert await executor.execute_next("slot-api-worker")

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            run = await client.get(f"/api/v1/content-slot-runs/{run_id}")
            scores = await client.get(f"/api/v1/content-slot-runs/{run_id}/scores")
            edition = await client.get(
                f"/api/v1/content-editions/{business_date.isoformat()}",
                params={"profile": profile},
            )
        assert run.status_code == 200
        assert run.json()["status"] == "succeeded"
        assert run.json()["selected_count"] == 0
        assert run.json()["unfilled_count"] == 3
        assert run.json()["unfilled_reason_codes"] == ["no_candidates"]
        assert run.json()["rerank"]["outcome"] == "skipped"
        assert run.json()["rerank"]["provider"] == "disabled"
        assert scores.json() == {"items": [], "count": 0}
        morning = edition.json()["slots"][0]
        assert morning["state"] == "ready"
        assert morning["selections"] == []
        assert morning["unfilled_count"] == 3
        assert [item["content_slot"] for item in edition.json()["slots"]] == [
            "morning",
            "noon",
            "evening",
        ]

        async with integration_context.session_factory() as state_session:
            await state_session.execute(
                update(ContentSlotRunModel)
                .where(ContentSlotRunModel.id == run_id)
                .values(status="queued")
            )
            await state_session.commit()
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            preparing = await client.get(
                f"/api/v1/content-editions/{business_date.isoformat()}",
                params={"profile": profile},
            )
        assert preparing.json()["slots"][0]["state"] == "preparing"

        async with integration_context.session_factory() as state_session:
            await state_session.execute(
                update(ContentSlotRunModel)
                .where(ContentSlotRunModel.id == run_id)
                .values(status="failed", error_code="fixture_failure")
            )
            await state_session.commit()
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            failed = await client.get(
                f"/api/v1/content-editions/{business_date.isoformat()}",
                params={"profile": profile},
            )
            expired = await client.get(
                "/api/v1/content-editions/2000-01-01",
                params={"profile": profile},
            )
        assert failed.json()["slots"][0]["state"] == "failed"
        assert failed.json()["slots"][0]["error_code"] == "fixture_failure"
        assert expired.json()["slots"][0]["state"] == "expired"
    finally:
        app.state.settings = previous_settings
        app.state.session_factory = previous_factory


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_content_edition_keeps_three_sibling_delivery_states_independent(
    integration_context: IntegrationContext,
) -> None:
    target_at = datetime(2094, 8, 13, 23, 30, tzinfo=UTC)
    _window_id, job_ids, business_date, profile = await _seed_slot_delivery_lane(
        integration_context,
        target_at=target_at,
    )
    async with integration_context.session_factory() as session:
        await session.execute(
            update(WeComDeliveryJobModel)
            .where(WeComDeliveryJobModel.id == job_ids[0])
            .values(status="delivered", text_status="delivered", image_status="delivered")
        )
        await session.execute(
            update(WeComDeliveryJobModel)
            .where(WeComDeliveryJobModel.id == job_ids[1])
            .values(status="failed", last_error_code="fixture_failure")
        )
        await session.execute(
            update(WeComDeliveryJobModel)
            .where(WeComDeliveryJobModel.id == job_ids[2])
            .values(
                status="delivery_window_expired",
                last_error_code="delivery_window_expired",
            )
        )
        await session.commit()

    previous_settings = app.state.settings
    previous_factory = app.state.session_factory
    app.state.settings = integration_context.settings.model_copy(
        update={
            "content_enabled": True,
            "content_slot_mode_enabled": True,
            "content_morning_enabled": True,
            "content_noon_enabled": True,
            "content_evening_enabled": True,
            "content_scoring_profile": profile,
        }
    )
    app.state.session_factory = integration_context.session_factory
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/content-editions/{business_date.isoformat()}",
                params={"profile": profile},
            )
        assert response.status_code == 200
        morning = response.json()["slots"][0]
        assert morning["state"] == "ready"
        assert morning["selected_count"] == 3
        assert [item["ordinal"] for item in morning["selections"]] == [1, 2, 3]
        assert [item["state"] for item in morning["selections"]] == [
            "delivered",
            "failed",
            "expired",
        ]
        assert all(item["source_links"] == [] for item in morning["selections"])
        assert [item["state"] for item in response.json()["slots"][1:]] == [
            "missing",
            "missing",
        ]

        async with integration_context.session_factory() as session:
            await session.execute(
                update(WeComDeliveryJobModel)
                .where(WeComDeliveryJobModel.id.in_(job_ids))
                .values(
                    status="delivered",
                    text_status="delivered",
                    image_status="delivered",
                    last_error_code=None,
                )
            )
            await session.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            complete = await client.get(
                f"/api/v1/content-editions/{business_date.isoformat()}",
                params={"profile": profile},
            )
        assert [item["state"] for item in complete.json()["slots"][0]["selections"]] == [
            "delivered",
            "delivered",
            "delivered",
        ]
    finally:
        app.state.settings = previous_settings
        app.state.session_factory = previous_factory
