from __future__ import annotations

from uuid import uuid4

import pytest
from app.api_main import app
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
        assert sources.json()["count"] == 8
        assert {item["relevance_rule_version"] for item in sources.json()["items"]} == {
            "ai-title-v1"
        }
        assert all("latest_filtered_count" in item for item in sources.json()["items"])

        created = await client.post(
            "/api/v1/acquisition-runs",
            headers={"Idempotency-Key": f"api-{uuid4()}"},
            json={"source_ids": [str(SOURCE_SEEDS[0].source_id)]},
        )
        assert created.status_code == 202
        assert created.headers["location"] == created.json()["status_url"]
        assert created.json()["status"] == "queued"
        assert created.json()["filtered_count"] == 0

        run = await client.get(created.json()["status_url"])
        jobs = await client.get(f"{created.json()['status_url']}/jobs")
        assert run.status_code == 200
        assert jobs.status_code == 200
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
    assert response.json() == {
        "error": {"code": "not_found", "message": "acquisition run was not found", "details": None}
    }
