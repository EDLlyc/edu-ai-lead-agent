from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from app.api_main import app
from app.domain.topic_selection import select_daily_topic
from app.infrastructure.db.models import (
    AcquisitionRunModel,
    GovernanceRunModel,
    TopicSelectionRunModel,
)
from app.infrastructure.db.topic_selection import PostgresTopicSelectionRepository
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_topic_selection_api_enqueues_and_exposes_durable_no_topic(
    integration_context: IntegrationContext,
) -> None:
    scoring_profile = f"api-no-topic-{uuid4().hex[:8]}"
    settings = integration_context.settings.model_copy(
        update={
            "content_enabled": True,
            "content_worker_enabled": True,
            "content_scoring_profile": scoring_profile,
        }
    )
    app.state.settings = settings
    app.state.session_factory = integration_context.session_factory
    transport = ASGITransport(app=app)
    business_date = date(2098, 8, 1)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        not_ready = await client.post(
            "/api/v1/topic-selection-runs",
            json={"business_date": business_date.isoformat()},
        )
        assert not_ready.status_code == 409
        assert not_ready.json()["error"]["code"] == "conflict"

    ready_at = datetime.now(UTC)
    acquisition_run_id = uuid4()
    async with integration_context.session_factory() as session:
        session.add(
            AcquisitionRunModel(
                id=acquisition_run_id,
                trigger="manual",
                business_date=business_date,
                timezone="Asia/Shanghai",
                acquisition_version="acquisition-test",
                manual_idempotency_key=f"topic-api-acquisition-{uuid4().hex}",
                status="succeeded",
                completed_at=ready_at,
            )
        )
        session.add(
            GovernanceRunModel(
                id=uuid4(),
                trigger="acquisition",
                acquisition_run_id=acquisition_run_id,
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
            "/api/v1/topic-selection-runs",
            json={"business_date": business_date.isoformat()},
        )
        assert created.status_code == 202
        run_id = UUID(created.json()["id"])
        assert created.json()["status"] == "queued"
        assert created.json()["scoring_version"] == "scoring-v1-preview.4-science-policy-priority"
        assert created.headers["location"] == f"/api/v1/topic-selection-runs/{run_id}"

    async with integration_context.session_factory() as session:
        await session.execute(
            update(TopicSelectionRunModel)
            .where(TopicSelectionRunModel.id == run_id)
            .values(governed_event_cutoff=datetime(1970, 1, 1, tzinfo=UTC))
        )
        await session.commit()

    repository = PostgresTopicSelectionRepository(integration_context.session_factory)
    claimed = await repository.claim_for_run(
        run_id=run_id,
        worker_id="topic-api-e2e",
        lease_seconds=settings.content_lease_seconds,
    )
    assert claimed is not None
    config = await repository.load_config(run_id)
    candidates = await repository.load_candidates(run_id)
    decision = select_daily_topic(candidates, as_of=claimed.cutoff_at, config=config)
    assert await repository.persist_decision(
        claimed=claimed,
        config=config,
        decision=decision,
    )
    assert await repository.complete(claimed=claimed)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        run = await client.get(f"/api/v1/topic-selection-runs/{run_id}")
        scores = await client.get(f"/api/v1/topic-selection-runs/{run_id}/scores")
        daily = await client.get(
            f"/api/v1/daily-topics/{business_date.isoformat()}",
            params={"profile": scoring_profile},
        )
        replay = await client.post(
            "/api/v1/topic-selection-runs",
            json={"business_date": business_date.isoformat()},
        )

    assert run.status_code == 200
    assert run.json()["status"] == "succeeded"
    assert run.json()["no_topic_code"] == "no_candidates"
    assert run.json()["considered_count"] == 0
    assert scores.status_code == 200
    assert scores.json() == {"items": [], "count": 0}
    assert daily.status_code == 200
    assert daily.json()["decision"] == "no_topic"
    assert daily.json()["no_topic_code"] == "no_candidates"
    assert daily.json()["selected_score"] is None
    assert replay.status_code == 202
    assert replay.json()["id"] != str(run_id)
    assert replay.json()["revision"] == 2
    assert replay.json()["is_current"] is True
