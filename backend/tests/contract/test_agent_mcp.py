from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from app.agent_mcp_main import (
    build_agent_mcp_server,
    validate_agent_mcp_environment,
)
from app.application.services.agent_tools import TypedToolRegistry, build_agent_tool_registry
from app.infrastructure.agent_workbench_fixture import (
    FIXTURE_BRAND_CHUNK_ID,
    FIXTURE_COPY_RUN_ID,
    FIXTURE_EVENT_ID,
    build_fixture_material_draft,
    build_fixture_reader,
)
from mcp import Client, StdioServerParameters, stdio_client
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS

BACKEND_ROOT = Path(__file__).resolve().parents[2]


async def test_official_client_lists_exact_canonical_registry_contract() -> None:
    registry = build_agent_tool_registry(build_fixture_reader())
    server = build_agent_mcp_server(registry)

    async with Client(server) as client:
        listed = await client.list_tools()

    assert [tool.name for tool in listed.tools] == [
        "get_event",
        "retrieve_brand_context",
        "search_evidence",
        "validate_copy",
    ]
    by_name = {tool.name: tool for tool in listed.tools}
    for definition in registry.definitions:
        tool = by_name[definition.name]
        assert tool.description == definition.description
        assert tool.input_schema == definition.input_schema()
        assert tool.output_schema == definition.output_schema()
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.annotations.open_world_hint is False


async def test_official_client_calls_all_four_tools_with_structured_results() -> None:
    server = build_agent_mcp_server()
    draft = build_fixture_material_draft()

    async with Client(server) as client:
        event = await client.call_tool("get_event", {"event_id": str(FIXTURE_EVENT_ID)})
        evidence = await client.call_tool(
            "search_evidence", {"query": "人工智能教育安全证据", "limit": 1}
        )
        brand = await client.call_tool(
            "retrieve_brand_context",
            {
                "query": "如何向家长克制地表达",
                "valid_on": date(2026, 8, 16).isoformat(),
                "audience": "parents",
                "document_kinds": ["tone"],
                "limit": 1,
            },
        )
        validation = await client.call_tool(
            "validate_copy",
            {
                "copy_run_id": str(FIXTURE_COPY_RUN_ID),
                "draft": draft.model_dump(mode="json"),
                "brand_chunk_ids": [str(FIXTURE_BRAND_CHUNK_ID)],
            },
        )

    assert event.is_error is False
    assert event.structured_content is not None
    assert event.structured_content["event_id"] == str(FIXTURE_EVENT_ID)
    assert evidence.is_error is False
    assert evidence.structured_content is not None
    assert evidence.structured_content["items"][0]["evidence_eligible"] is True
    assert brand.is_error is False
    assert brand.structured_content is not None
    assert brand.structured_content["items"][0]["evidence_eligible"] is False
    assert validation.is_error is False
    assert validation.structured_content is not None
    assert validation.structured_content["copy_run_id"] == str(FIXTURE_COPY_RUN_ID)


async def test_mcp_projects_invalid_unknown_and_timeout_errors_without_raw_input() -> None:
    registry = build_agent_tool_registry(build_fixture_reader())
    invalid_server = build_agent_mcp_server(registry)

    async with Client(invalid_server) as client:
        invalid = await client.call_tool(
            "get_event", {"event_id": "private-invalid-value", "unexpected": "do-not-echo"}
        )
        # An unknown tool is a JSON-RPC protocol error, not a tool result.
        with pytest.raises(MCPError) as unknown:
            await client.call_tool("shell", {"command": "do-not-echo"})

    invalid_text = " ".join(getattr(block, "text", "") for block in invalid.content)
    assert invalid.is_error is True
    assert invalid_text == "agent_tool_invalid_arguments: tool arguments failed validation"
    assert invalid.structured_content == {
        "ok": False,
        "error_code": "agent_tool_invalid_arguments",
        "retryable": True,
        "hint": "fix the listed fields to match the input schema",
        "fields": ["event_id:uuid_parsing", "unexpected_field"],
    }
    serialized = json.dumps(invalid.structured_content) + invalid_text
    for private in ("private-invalid-value", "do-not-echo", 'unexpected"'):
        assert private not in serialized
    assert unknown.value.code == INVALID_PARAMS
    assert str(unknown.value) == "agent_tool_unknown: tool is not registered"
    assert "shell" not in str(unknown.value)
    assert "do-not-echo" not in str(unknown.value)

    async def slow_handler(raw):
        del raw
        import asyncio

        await asyncio.sleep(0.05)
        raise AssertionError("timeout should cancel the handler")

    definitions = tuple(
        replace(
            definition,
            handler=slow_handler,
            timeout_seconds=0.001,
        )
        if definition.name == "get_event"
        else definition
        for definition in registry.definitions
    )
    timeout_server = build_agent_mcp_server(TypedToolRegistry(definitions))
    async with Client(timeout_server) as client:
        timeout = await client.call_tool("get_event", {"event_id": str(FIXTURE_EVENT_ID)})

    timeout_text = " ".join(getattr(block, "text", "") for block in timeout.content)
    assert timeout.is_error is True
    assert timeout_text == "agent_tool_timeout: tool execution timed out"
    assert timeout.structured_content is not None
    assert timeout.structured_content["retryable"] is True
    assert "AssertionError" not in timeout_text


async def test_stdio_entrypoint_supports_official_client_without_network() -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.agent_mcp_main"],
        env={"APP_ENV": "development", "AI_PROVIDER_MODE": "fake"},
        cwd=BACKEND_ROOT,
    )

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr:
        async with Client(stdio_client(parameters, errlog=stderr)) as client:
            listed = await client.list_tools()
            result = await client.call_tool("get_event", {"event_id": str(FIXTURE_EVENT_ID)})
        stderr.seek(0)
        stderr_text = stderr.read()

    assert [tool.name for tool in listed.tools] == [
        "get_event",
        "retrieve_brand_context",
        "search_evidence",
        "validate_copy",
    ]
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["event_id"] == str(FIXTURE_EVENT_ID)
    assert "Traceback" not in stderr_text


@pytest.mark.parametrize(
    ("environment", "message"),
    (
        ({"APP_ENV": "production", "AI_PROVIDER_MODE": "fake"}, "local-only"),
        ({"APP_ENV": "development", "AI_PROVIDER_MODE": "zhipu"}, "offline"),
    ),
)
def test_mcp_environment_guard_rejects_production_and_live_provider(
    environment: dict[str, str], message: str
) -> None:
    validate_agent_mcp_environment({})
    validate_agent_mcp_environment({"APP_ENV": "development", "AI_PROVIDER_MODE": "fake"})

    with pytest.raises(RuntimeError, match=message):
        validate_agent_mcp_environment(environment)


async def test_server_states_routing_rules_logs_each_call_and_enforces_a_call_budget() -> None:
    records: list[dict[str, object]] = []
    server = build_agent_mcp_server(
        call_budget=2, call_logger=lambda record: records.append(dict(record))
    )

    async with Client(server) as client:
        first = await client.call_tool("get_event", {"event_id": str(FIXTURE_EVENT_ID)})
        second = await client.call_tool("get_event", {"event_id": "not-a-uuid"})
        third = await client.call_tool("get_event", {"event_id": str(FIXTURE_EVENT_ID)})
        instructions = client.instructions

    assert (
        instructions is not None and "search_evidence before stating any news fact" in instructions
    )
    assert (first.is_error, second.is_error, third.is_error) == (False, True, True)
    assert third.structured_content is not None
    assert third.structured_content["error_code"] == "mcp_call_budget_exhausted"
    assert third.structured_content["retryable"] is False
    assert [(r["tool"], r["ok"], r["error_code"], r["call"]) for r in records] == [
        ("get_event", True, None, 1),
        ("get_event", False, "agent_tool_invalid_arguments", 2),
        ("get_event", False, "mcp_call_budget_exhausted", 3),
    ]
    assert all("not-a-uuid" not in json.dumps(record) for record in records)


def test_workbench_tool_arguments_all_have_descriptions() -> None:
    registry = build_agent_tool_registry(build_fixture_reader())

    for definition in registry.definitions:
        for name, field in definition.input_schema()["properties"].items():  # type: ignore[union-attr]
            assert field.get("description"), (definition.name, name)
