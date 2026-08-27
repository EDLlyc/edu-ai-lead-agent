from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from app.api_main import app
from app.domain.editorial_relevance import SCIENCE_TECH_EDITORIAL_RULE_VERSION
from app.infrastructure.db.repositories import seed_sources
from app.infrastructure.ingestion.source_profiles import SOURCE_SEEDS
from httpx import ASGITransport, AsyncClient

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_internal_api_lists_sources_and_enqueues_without_fetching(
    integration_context: IntegrationContext,
) -> None:
    async with integration_context.session_factory() as session:
        await seed_sources(session)
    app.state.settings = integration_context.settings
    app.state.session_factory = integration_context.session_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        sources = await client.get("/api/v1/sources")
        assert sources.status_code == 200
        assert sources.json()["count"] == 11
        assert {item["relevance_rule_version"] for item in sources.json()["items"]} == {
            SCIENCE_TECH_EDITORIAL_RULE_VERSION,
        }
        assert all("latest_filtered_count" in item for item in sources.json()["items"])

        created = await client.post(
            "/api/v1/acquisition-runs",
            headers={"Idempotency-Key": f"api-{uuid4()}"},
            json={
                "source_ids": [str(SOURCE_SEEDS[0].source_id)],
                "business_date": "2031-01-02",
            },
        )
        assert created.status_code == 202
        assert created.headers["location"] == created.json()["status_url"]
        assert created.json()["status"] == "queued"
        assert created.json()["filtered_count"] == 0
        assert created.json()["business_date"] == date(2031, 1, 2).isoformat()

        run = await client.get(created.json()["status_url"])
        jobs = await client.get(f"{created.json()['status_url']}/jobs")
        assert run.status_code == 200
        assert jobs.status_code == 200
        assert run.json()["business_date"] == date(2031, 1, 2).isoformat()
        assert jobs.json()["count"] == 1
        assert jobs.json()["items"][0]["filtered_count"] == 0


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_api_returns_stable_not_found_envelope(
    integration_context: IntegrationContext,
) -> None:
    app.state.settings = integration_context.settings
    app.state.session_factory = integration_context.session_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/acquisition-runs/{uuid4()}")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["message"] == "acquisition run was not found"
    assert error["details"] is None
    assert error["request_id"] == response.headers["x-request-id"]
