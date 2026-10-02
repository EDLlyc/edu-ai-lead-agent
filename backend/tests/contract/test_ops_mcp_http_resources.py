"""Ops MCP server: resources, prompts, Streamable HTTP behind a bearer token, loopback guard."""

from __future__ import annotations

import json
from datetime import date

import httpx2
import pytest
from app.application.services.ops_tools import (
    CopyRunDetail,
    CopyRunsResult,
    DayTraceResult,
    DeliveriesResult,
    SlotRunsResult,
)
from app.core.errors import NotFoundError
from app.mcp_http import (
    MIN_TOKEN_LENGTH,
    StaticTokenVerifier,
    bearer_token_from_environment,
    check_bind_host,
    static_token_auth,
)
from app.ops_mcp_main import build_ops_mcp_server, main
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

TOKEN = "s3cret-operator-token-for-tests-0123456789"
BASE_URL = "http://127.0.0.1:8765"


class Reader:
    def __init__(self) -> None:
        self.trace_dates: list[date] = []

    async def list_slot_runs(self, business_date: date) -> SlotRunsResult:
        return SlotRunsResult(runs=())

    async def list_copy_runs(self, business_date: date, limit: int) -> CopyRunsResult:
        return CopyRunsResult(runs=())

    async def get_copy_run(self, run_id: object) -> CopyRunDetail:
        raise NotFoundError("copy generation run")

    async def list_deliveries(self, business_date: date) -> DeliveriesResult:
        return DeliveriesResult(deliveries=())

    async def get_day_trace(self, business_date: date) -> DayTraceResult:
        self.trace_dates.append(business_date)
        return DayTraceResult(business_date=business_date, posts=(), usage=())


async def test_day_trace_resource_template_and_server_info() -> None:
    reader = Reader()
    server = build_ops_mcp_server(reader, call_logger=None)

    async with Client(server) as client:
        templates = await client.list_resource_templates()
        resources = await client.list_resources()
        trace = await client.read_resource("ops://trace/2026-09-30")
        info = await client.read_resource("ops://server/info")
        with pytest.raises(MCPError):
            await client.read_resource("ops://trace/yesterday")

    assert [t.uri_template for t in templates.resource_templates] == ["ops://trace/{business_date}"]
    assert [str(r.uri) for r in resources.resources] == ["ops://server/info"]
    trace_json = json.loads(trace.contents[0].text)  # type: ignore[union-attr]
    assert trace_json["business_date"] == "2026-09-30"
    assert reader.trace_dates == [date(2026, 9, 30)]
    info_json = json.loads(info.contents[0].text)  # type: ignore[union-attr]
    assert {tool["name"] for tool in info_json["tools"]} == {
        "get_copy_run",
        "get_day_trace",
        "list_copy_runs",
        "list_deliveries",
        "list_slot_runs",
    }
    assert all(tool["read_only"] for tool in info_json["tools"])
    # Resource reads go through the registry: counted against the budget like a tool call.
    assert server.calls_used == 2


async def test_prompts_route_the_client_model_through_the_tools() -> None:
    server = build_ops_mcp_server(Reader(), call_logger=None)

    async with Client(server) as client:
        listed = await client.list_prompts()
        slot = await client.get_prompt(
            "diagnose_slot", {"business_date": "2026-10-02", "slot": "noon"}
        )
        blocked = await client.get_prompt(
            "explain_blocked_copy", {"run_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}
        )
        with pytest.raises(MCPError):
            await client.get_prompt("diagnose_slot", {"business_date": "2026-10-02", "slot": "x"})

    assert {prompt.name for prompt in listed.prompts} == {
        "daily_usage",
        "diagnose_slot",
        "explain_blocked_copy",
    }
    text = slot.messages[0].content.text  # type: ignore[union-attr]
    for tool in ("list_slot_runs", "list_copy_runs", "get_copy_run", "list_deliveries"):
        assert tool in text
    assert "2026-10-02" in text and "午间" in text and "需人工批准" in text
    assert "get_copy_run(run_id=aaaaaaaa" in blocked.messages[0].content.text  # type: ignore[union-attr]


async def test_http_requires_the_bearer_token() -> None:
    auth, verifier = static_token_auth(TOKEN, host="127.0.0.1", port=8765, client_id="ops")
    server = build_ops_mcp_server(Reader(), call_logger=None, auth=auth, token_verifier=verifier)
    app = server.streamable_http_app(streamable_http_path="/mcp", host="127.0.0.1")
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    headers = {"accept": "application/json, text/event-stream"}

    async with server.session_manager.run():
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url=BASE_URL) as raw:
            missing = await raw.post("/mcp", json=request, headers=headers)
            wrong = await raw.post(
                "/mcp", json=request, headers={**headers, "authorization": "Bearer wrong"}
            )
            metadata = await raw.get("/.well-known/oauth-protected-resource")
        authorized = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url=BASE_URL,
            headers={"authorization": f"Bearer {TOKEN}"},
        )
        async with Client(
            streamable_http_client(f"{BASE_URL}/mcp", http_client=authorized)
        ) as client:
            tools = await client.list_tools()
            runs = await client.call_tool("list_copy_runs", {"business_date": "2026-10-02"})

    assert missing.status_code == 401 and wrong.status_code == 401
    assert missing.headers["www-authenticate"].startswith("Bearer ")
    # No OAuth discovery is offered: the token is a static operator secret.
    assert "resource_metadata" not in missing.headers["www-authenticate"]
    assert metadata.status_code == 404
    assert TOKEN not in missing.text and TOKEN not in wrong.text
    assert len(tools.tools) == 5
    assert runs.structured_content == {"runs": []}


async def test_static_token_verifier_compares_and_never_returns_the_secret() -> None:
    verifier = StaticTokenVerifier(TOKEN, client_id="ops")

    assert await verifier.verify_token("nope") is None
    granted = await verifier.verify_token(TOKEN)
    assert granted is not None and granted.client_id == "ops"
    assert TOKEN not in granted.model_dump_json()
    with pytest.raises(ValueError, match="too short"):
        StaticTokenVerifier("short", client_id="ops")


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]", "127.0.0.2"])
def test_loopback_hosts_are_allowed(host: str) -> None:
    check_bind_host(host, allow_remote=False)


@pytest.mark.parametrize("host", ["0.0.0.0", "10.0.0.5", "example.org"])
def test_non_loopback_hosts_need_allow_remote(host: str) -> None:
    with pytest.raises(RuntimeError, match="refusing to listen"):
        check_bind_host(host, allow_remote=False)
    check_bind_host(host, allow_remote=True)


def test_token_must_be_set_and_long_enough() -> None:
    with pytest.raises(RuntimeError, match="required"):
        bearer_token_from_environment({}, "OPS_MCP_TOKEN")
    with pytest.raises(RuntimeError, match=str(MIN_TOKEN_LENGTH)):
        bearer_token_from_environment({"OPS_MCP_TOKEN": "short"}, "OPS_MCP_TOKEN")
    assert bearer_token_from_environment({"OPS_MCP_TOKEN": f" {TOKEN} "}, "OPS_MCP_TOKEN") == TOKEN


def test_http_main_refuses_before_touching_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPS_DATABASE_URL", raising=False)
    monkeypatch.delenv("OPS_MCP_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="refusing to listen"):
        main(["--transport", "http", "--host", "0.0.0.0"])
    with pytest.raises(RuntimeError, match="OPS_MCP_TOKEN"):
        main(["--transport", "http"])
