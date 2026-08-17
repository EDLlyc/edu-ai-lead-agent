from __future__ import annotations

import httpx
import pytest
from app.agent_workbench_api_main import create_agent_workbench_app
from app.core.agent_workbench_config import AgentWorkbenchSettings
from pydantic import ValidationError


def _settings(*, enabled: bool) -> AgentWorkbenchSettings:
    return AgentWorkbenchSettings(
        _env_file=None,
        app_env="test",
        agent_workbench_enabled=enabled,
    )


def _transport(
    *,
    enabled: bool,
    peer: str = "127.0.0.1",
) -> httpx.ASGITransport:
    return httpx.ASGITransport(
        app=create_agent_workbench_app(settings=_settings(enabled=enabled)),
        client=(peer, 42000),
    )


@pytest.mark.asyncio
async def test_local_api_disabled_and_enabled_contract() -> None:
    async with httpx.AsyncClient(
        transport=_transport(enabled=False),
        base_url="http://127.0.0.1:8010",
    ) as client:
        disabled = await client.post(
            "/api/v1/agent-workbench/runs",
            json={"query": "可靠证据"},
        )
    assert disabled.status_code == 404
    assert disabled.json()["error"]["code"] == "agent_workbench_disabled"

    async with httpx.AsyncClient(
        transport=_transport(enabled=True),
        base_url="http://127.0.0.1:8010",
    ) as client:
        response = await client.post(
            "/api/v1/agent-workbench/runs",
            json={"query": "这条人工智能教育事件有哪些可靠证据?", "scenario_id": "evidence"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["metrics"]["tool_calls"] == 1
    assert payload["claims"][0]["citation_ids"] == [payload["citations"][0]["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ("/healthz", "/docs", "/openapi.json"))
async def test_entire_independent_app_rejects_non_loopback_peer(path: str) -> None:
    async with httpx.AsyncClient(
        transport=_transport(enabled=True, peer="192.0.2.25"),
        base_url="http://127.0.0.1:8010",
    ) as client:
        response = await client.get(path)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "agent_workbench_loopback_required"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header",
    (
        {"Forwarded": "for=127.0.0.1"},
        {"X-Forwarded-For": "127.0.0.1"},
        {"X-Forwarded-Host": "127.0.0.1"},
    ),
)
async def test_forwarding_headers_are_rejected_even_from_loopback(
    header: dict[str, str],
) -> None:
    async with httpx.AsyncClient(
        transport=_transport(enabled=True),
        base_url="http://127.0.0.1:8010",
    ) as client:
        response = await client.post(
            "/api/v1/agent-workbench/runs",
            headers=header,
            json={"query": "可靠证据"},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "agent_workbench_loopback_required"


@pytest.mark.asyncio
async def test_cors_allows_only_exact_local_vite_origin_after_peer_gate() -> None:
    preflight_headers = {
        "Origin": "http://127.0.0.1:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-request-id",
    }
    async with httpx.AsyncClient(
        transport=_transport(enabled=True),
        base_url="http://127.0.0.1:8010",
    ) as client:
        allowed = await client.options(
            "/api/v1/agent-workbench/runs",
            headers=preflight_headers,
        )
        denied = await client.options(
            "/api/v1/agent-workbench/runs",
            headers={**preflight_headers, "Origin": "http://localhost:5173"},
        )
        allowed_post = await client.post(
            "/api/v1/agent-workbench/runs",
            headers={"Origin": "http://127.0.0.1:5173"},
            json={"query": "可靠证据"},
        )
        denied_post = await client.post(
            "/api/v1/agent-workbench/runs",
            headers={"Origin": "http://localhost:5173"},
            json={"query": "可靠证据"},
        )
        forwarded_preflight = await client.options(
            "/api/v1/agent-workbench/runs",
            headers={**preflight_headers, "X-Forwarded-For": "127.0.0.1"},
        )
    async with httpx.AsyncClient(
        transport=_transport(enabled=True, peer="192.0.2.25"),
        base_url="http://127.0.0.1:8010",
    ) as remote_client:
        remote_preflight = await remote_client.options(
            "/api/v1/agent-workbench/runs",
            headers=preflight_headers,
        )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "access-control-allow-credentials" not in allowed.headers
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "agent_workbench_origin_rejected"
    assert "access-control-allow-origin" not in denied.headers
    assert allowed_post.status_code == 200
    assert allowed_post.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "access-control-allow-credentials" not in allowed_post.headers
    assert denied_post.status_code == 403
    assert denied_post.json()["error"]["code"] == "agent_workbench_origin_rejected"
    assert "access-control-allow-origin" not in denied_post.headers
    assert forwarded_preflight.status_code == 403
    assert forwarded_preflight.json()["error"]["code"] == "agent_workbench_loopback_required"
    assert remote_preflight.status_code == 403
    assert remote_preflight.json()["error"]["code"] == "agent_workbench_loopback_required"


@pytest.mark.asyncio
async def test_request_validation_and_request_id_projection_are_bounded() -> None:
    async with httpx.AsyncClient(
        transport=_transport(enabled=True),
        base_url="http://127.0.0.1:8010",
    ) as client:
        response = await client.post(
            "/api/v1/agent-workbench/runs",
            headers={"X-Request-ID": "x" * 500},
            json={"query": "x" * 501},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert response.headers["x-request-id"] != "x" * 500
    assert len(response.headers["x-request-id"]) <= 128


def test_workbench_cannot_be_enabled_in_production() -> None:
    with pytest.raises(ValidationError, match="cannot be enabled in production"):
        AgentWorkbenchSettings(
            _env_file=None,
            app_env="production",
            agent_workbench_enabled=True,
        )


def test_production_api_does_not_register_workbench_route() -> None:
    from app.api_main import app as production_app

    assert "/api/v1/agent-workbench/runs" not in production_app.openapi()["paths"]
