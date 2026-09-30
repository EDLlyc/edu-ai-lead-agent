from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
from app.application.services.copy_repair_agent import REPAIR_SYSTEM_PROMPT
from app.application.services.copy_repair_tools import (
    REPAIR_TOOL_RULES,
    build_repair_tool_registry,
)
from app.copy_repair_mcp_main import build_copy_repair_mcp_server, load_fixture_workspace
from mcp import Client, StdioServerParameters, stdio_client

BACKEND_ROOT = Path(__file__).resolve().parents[2]


async def test_mcp_lists_the_agents_exact_repair_registry_and_shares_its_rules() -> None:
    workspace = await load_fixture_workspace()
    registry = build_repair_tool_registry(workspace)
    server = build_copy_repair_mcp_server(workspace, call_logger=None)

    async with Client(server) as client:
        listed = await client.list_tools()
        instructions = client.instructions

    assert [tool.name for tool in listed.tools] == [d.name for d in registry.definitions]
    function_calling = {
        schema["function"]["name"]: schema["function"]  # type: ignore[index]
        for schema in registry.model_tool_schemas()
    }
    for tool in listed.tools:
        definition = function_calling[tool.name]
        assert tool.description == definition["description"]
        assert tool.input_schema == definition["parameters"]
        assert tool.annotations is not None
        writes = tool.name in {"drop_claim", "replace_claim", "rewrite_hook"}
        assert tool.annotations.read_only_hint is not writes
        assert tool.annotations.open_world_hint is False
    assert instructions is not None and REPAIR_TOOL_RULES in instructions
    assert REPAIR_TOOL_RULES in REPAIR_SYSTEM_PROMPT


async def test_mcp_edits_only_the_in_memory_workspace_and_returns_structured_refusals() -> None:
    workspace = await load_fixture_workspace()
    original = workspace.draft
    server = build_copy_repair_mcp_server(workspace, call_logger=None)
    claim = original.claims[0]

    async with Client(server) as client:
        refused = await client.call_tool(
            "replace_claim",
            {
                "claim_id": claim.id,
                "text": "编造的新事实。",
                "evidence_ids": list(map(str, claim.evidence_ids)),
            },
        )
        invalid = await client.call_tool("rewrite_hook", {"text": "短"})
        checked = await client.call_tool("check_draft", {})

    assert refused.is_error is False
    assert refused.structured_content is not None
    assert refused.structured_content["ok"] is False
    assert refused.structured_content["error_code"] in {
        "claim_not_in_evidence",
        "claim_not_in_brand",
    }
    assert invalid.is_error is True
    assert invalid.structured_content is not None
    assert invalid.structured_content["fields"] == ["text:string_too_short"]
    assert checked.structured_content is not None and "passed" in checked.structured_content
    assert workspace.draft == original


@pytest.mark.parametrize("budget", ["0", "abc"])
def test_call_budget_environment_is_validated(budget: str) -> None:
    from app.mcp_registry_server import call_budget_from_environment

    with pytest.raises(RuntimeError):
        call_budget_from_environment({"AGENT_MCP_MAX_CALLS": budget})
    assert call_budget_from_environment({}) == 200


async def test_stdio_repair_server_runs_offline_and_logs_to_stderr_only() -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.copy_repair_mcp_main"],
        env={"APP_ENV": "development", "AI_PROVIDER_MODE": "fake", "AGENT_MCP_MAX_CALLS": "5"},
        cwd=BACKEND_ROOT,
    )

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr:
        async with Client(stdio_client(parameters, errlog=stderr)) as client:
            listed = await client.list_tools()
            result = await client.call_tool("check_draft", {})
        stderr.seek(0)
        stderr_text = stderr.read()

    assert len(listed.tools) == 5
    assert result.is_error is False
    assert '"event":"mcp_tool_call"' in stderr_text
    assert '"tool":"check_draft"' in stderr_text
    assert "Traceback" not in stderr_text
