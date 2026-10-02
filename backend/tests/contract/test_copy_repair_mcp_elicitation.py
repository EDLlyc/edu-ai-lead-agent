# ruff: noqa: RUF001
"""Operator confirmation of repair edits through MCP form elicitation, on both protocol eras."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from app.application.services.copy_repair_tools import RepairWorkspace
from app.copy_repair_mcp_main import build_copy_repair_mcp_server, load_fixture_workspace
from app.mcp_registry_server import CONFIRMATION_META_KEY
from mcp import Client, types

# "auto" negotiates 2026-07-28 in process (InputRequiredResult round trip); "legacy" uses the
# initialize handshake (mid-call elicitation/create request).
MODES = ["auto", "legacy"]


class Operator:
    def __init__(self, action: str = "accept", *, apply: bool = True) -> None:
        self.action = action
        self.apply = apply
        self.messages: list[str] = []

    async def __call__(self, context: Any, params: types.ElicitRequestParams) -> types.ElicitResult:
        self.messages.append(params.message)
        if self.action == "accept":
            return types.ElicitResult(action="accept", content={"apply": self.apply})
        return types.ElicitResult(action=self.action)


def _last_claim(workspace: RepairWorkspace) -> tuple[str, str]:
    assert len(workspace.draft.claims) >= 2
    claim = workspace.draft.claims[-1]
    return claim.id, claim.text


@pytest.mark.parametrize("mode", MODES)
async def test_accepted_edit_runs_once_shows_the_change_and_is_marked(mode: str) -> None:
    workspace = await load_fixture_workspace()
    claim_id, claim_text = _last_claim(workspace)
    records: list[Mapping[str, object]] = []
    server = build_copy_repair_mcp_server(workspace, call_logger=records.append)
    operator = Operator()
    rounds: list[str] = []
    call_tool = server.call_tool

    async def counted(name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        result = await call_tool(name, arguments, context)
        rounds.append(type(result).__name__)
        return result

    server.call_tool = counted  # type: ignore[method-assign]

    async with Client(server, mode=mode, elicitation_callback=operator) as client:
        result = await client.call_tool("drop_claim", {"claim_id": claim_id})

    # 2026-07-28: an InputRequiredResult round, then the retry with the answer; handshake era:
    # one call with the elicitation/create request in between.
    expected = ["CallToolResult"] if mode == "legacy" else ["InputRequiredResult", "CallToolResult"]
    assert rounds == expected

    assert result.is_error is False
    assert result.structured_content is not None and result.structured_content["ok"] is True
    assert result.meta is not None and result.meta[CONFIRMATION_META_KEY] == "accepted"
    assert claim_id not in {claim.id for claim in workspace.draft.claims}
    (message,) = operator.messages
    assert f"删除 claim {claim_id}" in message and claim_text[:20] in message
    # The confirmation round is not a second call.
    assert server.calls_used == 1
    assert [record["confirmation"] for record in records] == ["accepted"]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("operator", "confirmation"),
    [
        (Operator("decline"), "declined"),
        (Operator("cancel"), "cancelled"),
        (Operator("accept", apply=False), "declined"),
    ],
)
async def test_declined_or_cancelled_edit_is_refused_and_leaves_the_draft(
    mode: str, operator: Operator, confirmation: str
) -> None:
    workspace = await load_fixture_workspace()
    original = workspace.draft
    claim_id, _ = _last_claim(workspace)
    server = build_copy_repair_mcp_server(workspace, call_logger=None)
    operator.messages.clear()

    async with Client(server, mode=mode, elicitation_callback=operator) as client:
        result = await client.call_tool("drop_claim", {"claim_id": claim_id})

    assert result.is_error is True
    assert result.structured_content is not None
    assert result.structured_content["error_code"] == "operator_declined"
    assert result.structured_content["retryable"] is False
    assert result.structured_content["confirmation"] == confirmation
    assert workspace.draft == original
    assert len(operator.messages) == 1


@pytest.mark.parametrize("mode", MODES)
async def test_rewrite_hook_shows_the_rendered_hook_before_and_after(mode: str) -> None:
    workspace = await load_fixture_workspace()
    before = workspace.view().hook
    server = build_copy_repair_mcp_server(workspace, call_logger=None)
    operator = Operator()
    hook = "人工智能走进课堂，正好和孩子聊聊怎样分辨一条消息的出处🔍"

    async with Client(server, mode=mode, elicitation_callback=operator) as client:
        result = await client.call_tool("rewrite_hook", {"text": hook})

    assert result.structured_content is not None and result.structured_content["ok"] is True
    (message,) = operator.messages
    assert f"改前：{before}" in message
    assert f"改后：{workspace.view().hook}" in message


async def test_an_edit_the_tool_refuses_is_not_asked_about() -> None:
    workspace = await load_fixture_workspace()
    claim = workspace.draft.claims[0]
    server = build_copy_repair_mcp_server(workspace, call_logger=None)
    operator = Operator()

    async with Client(server, elicitation_callback=operator) as client:
        refused = await client.call_tool(
            "replace_claim",
            {
                "claim_id": claim.id,
                "text": "编造的新事实。",
                "evidence_ids": list(map(str, claim.evidence_ids)),
            },
        )
        invalid = await client.call_tool("drop_claim", {"claim_id": ""})

    assert operator.messages == []
    assert refused.structured_content is not None and refused.structured_content["ok"] is False
    assert refused.meta is None or CONFIRMATION_META_KEY not in refused.meta
    assert invalid.is_error is True


@pytest.mark.parametrize("mode", MODES)
async def test_client_without_elicitation_keeps_todays_behaviour_marked(mode: str) -> None:
    workspace = await load_fixture_workspace()
    claim_id, _ = _last_claim(workspace)
    server = build_copy_repair_mcp_server(workspace, call_logger=None)

    async with Client(server, mode=mode) as client:
        result = await client.call_tool("drop_claim", {"claim_id": claim_id})

    assert result.structured_content is not None and result.structured_content["ok"] is True
    assert result.meta is not None and result.meta[CONFIRMATION_META_KEY] == "not_supported"
    assert claim_id not in {claim.id for claim in workspace.draft.claims}


async def test_require_confirmation_refuses_a_client_that_cannot_ask() -> None:
    workspace = await load_fixture_workspace()
    original = workspace.draft
    claim_id, _ = _last_claim(workspace)
    server = build_copy_repair_mcp_server(workspace, call_logger=None, require_confirmation=True)

    async with Client(server) as client:
        result = await client.call_tool("drop_claim", {"claim_id": claim_id})
        checked = await client.call_tool("check_draft", {})

    assert result.is_error is True
    assert result.structured_content is not None
    assert result.structured_content["error_code"] == "confirmation_unavailable"
    assert workspace.draft == original
    # Read-only tools are never gated.
    assert checked.is_error is False


def test_only_writing_tools_can_ask_for_confirmation() -> None:
    from app.application.services.copy_repair_tools import build_repair_tool_registry
    from app.mcp_registry_server import RegistryMCPServer

    async def message(_arguments: Mapping[str, Any]) -> str | None:
        return "确认？"

    with pytest.raises(ValueError, match="writing tool"):
        RegistryMCPServer(
            build_repair_tool_registry(_workspace_stub()),
            name="t",
            title="t",
            description="t",
            instructions="t",
            version="t",
            call_logger=None,
            confirmations={"check_draft": message},
        )


def _workspace_stub() -> RepairWorkspace:
    import asyncio

    return asyncio.run(load_fixture_workspace())
