"""A bounded tool-calling agent that repairs a blocked Moments draft.

The agent sees the blocking issues and a summary of the draft, then works through the repair
tool registry (find_evidence, replace_claim, drop_claim, rewrite_hook, check_draft). It stops
when the model answers without a tool call, or at the round or call cap. The caller must run the
normal rules and auditor on the returned draft; the agent's own check_draft is only a hint.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.application.services.agent_tools import AgentToolFailure
from app.application.services.agent_tracing import (
    ERROR_TYPE,
    INPUT_TOKENS,
    OUTPUT_TOKENS,
    REQUEST_MODEL,
    TOOL_CALL_ID,
    TOOL_NAME,
    TOOL_TYPE,
    AgentTracer,
    NoopTracer,
)
from app.application.services.copy_repair_tools import (
    REPAIR_TOOL_RULES,
    CheckDraftResult,
    RepairWorkspace,
    build_repair_tool_registry,
)
from app.schemas.copy_generation import CopyIssue, MaterialDraft

REPAIR_AGENT_VERSION = "copy-repair-agent-v4-keep-brand"

REPAIR_SYSTEM_PROMPT = (
    "你是赛先生朋友圈文案的修复节点。审查拦下了这份草稿，你只能通过工具修改工作稿，"
    "只修复列出的问题，其余内容保持不变。规则：\n"
    + REPAIR_TOOL_RULES
    + "\n每个问题附有 fix_with（建议的工具）。确认没有 error 后不再调用工具，直接回复“完成”；"
    "无法修复时回复“放弃”。"
)


@dataclass(frozen=True, slots=True)
class ChatToolCall:
    call_id: str
    name: str
    arguments_json: str


@dataclass(frozen=True, slots=True)
class ChatTurn:
    content: str | None
    tool_calls: tuple[ChatToolCall, ...]
    prompt_tokens: int
    completion_tokens: int


class RepairChatModel(Protocol):
    async def complete(
        self, messages: Sequence[Mapping[str, object]], tools: Sequence[Mapping[str, object]]
    ) -> ChatTurn: ...


# checked: stopped by the loop because check_draft passed after every flagged target
# was edited.
Stopped = Literal["finished", "checked", "gave_up", "round_limit", "call_limit"]


@dataclass(slots=True)
class RepairOutcome:
    draft: MaterialDraft
    stopped: Stopped
    rounds: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    edits: tuple[str, ...] = ()
    trace: list[dict[str, object]] = field(default_factory=list)


def _fix_with(issue: CopyIssue, draft: MaterialDraft) -> str:
    if issue.claim_id is None:
        return "rewrite_hook"
    claim = next((item for item in draft.claims if item.id == issue.claim_id), None)
    if claim is not None and claim.kind == "brand_statement":
        return "replace_claim（原样复制所引品牌资料里的句子）或 drop_claim"
    if claim is not None and claim.kind == "opinion":
        return "replace_claim"
    return "find_evidence 后 replace_claim（原样复制证据句子），找不到就 drop_claim"


def _blocking(issues: Sequence[CopyIssue]) -> list[CopyIssue]:
    return [issue for issue in issues if issue.severity == "error"][:12]


def _issue_payload(
    issues: Sequence[CopyIssue], draft: MaterialDraft
) -> list[dict[str, str | None]]:
    return [
        {
            "code": issue.code,
            "message": issue.message,
            "claim_id": issue.claim_id,
            "fix_with": _fix_with(issue, draft),
        }
        for issue in issues
    ]


class CopyRepairAgent:
    def __init__(
        self,
        model: RepairChatModel,
        *,
        max_rounds: int = 6,
        max_tool_calls: int = 12,
        tracer: AgentTracer | None = None,
        model_name: str | None = None,
    ):
        if not 1 <= max_rounds <= 6 or not 1 <= max_tool_calls <= 20:
            raise ValueError("repair agent limits are out of range")
        self._model = model
        self._max_rounds = max_rounds
        self._max_tool_calls = max_tool_calls
        # Optional step traces (chat and execute_tool spans); the caller owns invoke_agent.
        self._tracer: AgentTracer = tracer or NoopTracer()
        self._model_name = model_name

    async def repair(
        self, workspace: RepairWorkspace, issues: Sequence[CopyIssue]
    ) -> RepairOutcome:
        blocking = _blocking(issues)
        workspace.scope_to([(issue.claim_id, issue.code) for issue in blocking])
        registry = build_repair_tool_registry(workspace)
        tools = registry.model_tool_schemas()
        messages: list[Mapping[str, object]] = [
            {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "title": workspace.topic.title,
                        "summary": workspace.topic.summary,
                        "blocking_issues": _issue_payload(blocking, workspace.draft),
                        "draft": workspace.view().model_dump(),
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        outcome = RepairOutcome(draft=workspace.draft, stopped="round_limit")
        chat_attributes = {REQUEST_MODEL: self._model_name} if self._model_name else {}
        for _ in range(self._max_rounds):
            with self._tracer.span(
                "chat", f"chat {self._model_name or 'model'}", chat_attributes
            ) as span:
                turn = await self._model.complete(messages, tools)
                span.set_attribute(INPUT_TOKENS, turn.prompt_tokens)
                span.set_attribute(OUTPUT_TOKENS, turn.completion_tokens)
            outcome.rounds += 1
            outcome.prompt_tokens += turn.prompt_tokens
            outcome.completion_tokens += turn.completion_tokens
            if not turn.tool_calls:
                outcome.stopped = (
                    "gave_up" if turn.content and "放弃" in turn.content else "finished"
                )
                break
            checked_clean = False
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call.call_id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": call.arguments_json},
                        }
                        for call in turn.tool_calls
                    ],
                }
            )
            for call in turn.tool_calls:
                if outcome.tool_calls >= self._max_tool_calls:
                    content = json.dumps(
                        {
                            "ok": False,
                            "error_code": "call_limit",
                            "retryable": False,
                            "hint": "tool call limit reached; stop and reply",
                        }
                    )
                    outcome.stopped = "call_limit"
                else:
                    outcome.tool_calls += 1
                    tool_attributes = {
                        TOOL_NAME: call.name,
                        TOOL_CALL_ID: call.call_id,
                        TOOL_TYPE: "function",
                    }
                    with self._tracer.span(
                        "execute_tool", f"execute_tool {call.name}", tool_attributes
                    ) as span:
                        try:
                            result = await registry.invoke(call.name, call.arguments_json)
                            content = result.model_dump_json()
                            if isinstance(result, CheckDraftResult):
                                checked_clean = (
                                    result.passed
                                    and bool(workspace.edits)
                                    and workspace.flagged_targets_edited()
                                )
                            ok = bool(getattr(result, "ok", True))
                            code = getattr(result, "error_code", None)
                        except AgentToolFailure as failure:
                            # The same structured error an MCP client receives.
                            content = json.dumps(failure.payload(), ensure_ascii=False)
                            ok, code = False, failure.code.value
                        if code:
                            span.set_attribute(ERROR_TYPE, str(code))
                    outcome.trace.append({"tool": call.name, "ok": ok, "error_code": code})
                messages.append({"role": "tool", "tool_call_id": call.call_id, "content": content})
            if outcome.stopped == "call_limit":
                break
            if checked_clean:
                # The deterministic rules pass after an edit: stop without another model round.
                # The caller still runs the full gate, auditor included.
                outcome.stopped = "checked"
                break
        outcome.draft = workspace.draft
        outcome.edits = tuple(workspace.edits)
        return outcome
