# ruff: noqa: RUF001

from __future__ import annotations

import json
from datetime import date
from uuid import UUID

import pytest
from app.application.services.agent_tracing import (
    INPUT_TOKENS,
    OPERATION,
    TOOL_NAME,
    JsonlTraceRecorder,
)
from app.application.services.copy_repair_agent import ChatTurn
from app.application.services.ops_assistant import OpsAssistant
from langgraph.checkpoint.memory import InMemorySaver
from tests.unit.test_copy_repair_tools import EVIDENCE_A, _call, _workspace
from tests.unit.test_ops_tools import RUN_ID, _FakeReader

WRONG = "该模型在五项测试中表现领先。"
RIGHT = "该模型在三项测试中表现领先。"
NEW_HOOK = "机器人在学着观察世界，和孩子聊聊吧🔍"


class _Scripted:
    def __init__(self, turns: list[ChatTurn]) -> None:
        self.turns = turns
        self.calls: list[list[dict[str, object]]] = []

    async def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls.append([dict(m) for m in messages])
        assert {tool["function"]["name"] for tool in tools} >= {
            "open_draft",
            "list_copy_runs",
            "rewrite_hook",
        }
        return self.turns.pop(0)


class _Loader:
    def __init__(self) -> None:
        self.loads = 0

    async def __call__(self, run_id: UUID):  # type: ignore[no-untyped-def]
        assert run_id == RUN_ID
        self.loads += 1
        return _workspace(claim_text=WRONG)


def _assistant(
    turns: list[ChatTurn],
    *,
    checkpointer: InMemorySaver | None = None,
    thread_id: str | None = None,
    loader: _Loader | None = None,
    tracer: JsonlTraceRecorder | None = None,
    **limits: int,
) -> tuple[OpsAssistant, _Scripted]:
    model = _Scripted(turns)
    assistant = OpsAssistant(
        model,
        _FakeReader(),
        loader or _Loader(),
        today=date(2026, 10, 1),
        checkpointer=checkpointer,
        thread_id=thread_id,
        tracer=tracer,
        model_name="glm-test",
        **limits,
    )
    return assistant, model


def _tool_results(model: _Scripted) -> list[dict[str, object]]:
    return [json.loads(m["content"]) for m in model.calls[-1] if m["role"] == "tool"]  # type: ignore[arg-type]


def _open() -> ChatTurn:
    return ChatTurn(None, (_call("1", "open_draft", {"run_id": str(RUN_ID)}),), 100, 5)


def _replace(call_id: str = "2") -> ChatTurn:
    arguments = {"claim_id": "fact-1", "text": RIGHT, "evidence_ids": [str(EVIDENCE_A)]}
    return ChatTurn(None, (_call(call_id, "replace_claim", arguments),), 100, 5)


@pytest.mark.asyncio
async def test_reads_run_at_once_and_the_answer_cites_them() -> None:
    assistant, model = _assistant(
        [
            ChatTurn(
                None, (_call("1", "list_copy_runs", {"business_date": "2026-09-30"}),), 900, 20
            ),
            ChatTurn("中午 1 号任务已通过。", (), 1200, 15),
        ]
    )

    reply = await assistant.send("昨天中午的文案怎么样？")

    assert reply.kind == "answer" and reply.text == "中午 1 号任务已通过。"
    assert [(s.tool, s.ok, s.approval) for s in reply.steps] == [("list_copy_runs", True, "auto")]
    assert _tool_results(model)[0]["runs"][0]["content_slot"] == "noon"  # type: ignore[index]
    assert (reply.prompt_tokens, reply.completion_tokens) == (2100, 35)
    assert await assistant.pending() is None


@pytest.mark.asyncio
async def test_edits_pause_at_an_interrupt_and_run_only_when_approved() -> None:
    assistant, _ = _assistant(
        [_open(), _replace(), ChatTurn("已在沙盒里改好，请到审核页提交。", (), 100, 5)]
    )

    paused = await assistant.send("把这条的错误数字改掉")

    assert paused.kind == "approval" and paused.approval is not None
    assert paused.approval.tool == "replace_claim"
    assert paused.approval.preview == {"claim_id": "fact-1", "before": WRONG, "after": RIGHT}
    assert paused.draft is not None and paused.draft["edits"] == []  # nothing ran yet
    assert (await assistant.pending()) == paused.approval
    with pytest.raises(RuntimeError, match="pending approval"):
        await assistant.send("再问一句")

    done = await assistant.decide(approve=True)

    assert done.kind == "answer"
    assert done.draft is not None and done.draft["edits"] == ["replace_claim:fact-1"]
    assert done.draft["view"]["claims"][0]["text"] == RIGHT
    assert [(s.tool, s.approval) for s in done.steps] == [("replace_claim", "approved")]
    assert [(a["tool"], a["approved"]) for a in await assistant.approvals()] == [
        ("replace_claim", True)
    ]


@pytest.mark.asyncio
async def test_a_denied_edit_goes_back_to_the_model_and_changes_nothing() -> None:
    assistant, model = _assistant(
        [
            _open(),
            ChatTurn(None, (_call("2", "rewrite_hook", {"text": NEW_HOOK}),), 100, 5),
            ChatTurn("好的，引导语保持不变。", (), 100, 5),
        ]
    )

    paused = await assistant.send("改一下引导语")
    done = await assistant.decide(approve=False)

    assert paused.kind == "approval" and paused.approval is not None
    assert paused.approval.preview["after"] == NEW_HOOK
    assert done.kind == "answer"
    assert done.draft is not None and done.draft["edits"] == []
    assert done.draft["view"]["hook"] == paused.draft["view"]["hook"]  # type: ignore[index]
    assert _tool_results(model)[-1]["error_code"] == "denied_by_operator"
    assert [(s.tool, s.approval) for s in done.steps] == [("rewrite_hook", "denied")]


@pytest.mark.asyncio
async def test_a_pending_approval_survives_a_restart_and_the_sandbox_is_replayed() -> None:
    checkpointer = InMemorySaver()
    first, _ = _assistant(
        [
            _open(),
            _replace(),
            ChatTurn(None, (_call("3", "rewrite_hook", {"text": NEW_HOOK}),), 100, 5),
        ],
        checkpointer=checkpointer,
        thread_id="ops-assistant:test",
    )
    paused = await first.send("改数字，再改引导语")
    second_pause = await first.decide(approve=True)  # the number edit runs, the hook edit waits
    assert second_pause.kind == "approval" and second_pause.approval is not None
    assert second_pause.approval.tool == "rewrite_hook"
    assert paused.approval is not None and paused.approval.tool == "replace_claim"

    # "Restart": a new assistant, model and loader; only the checkpointer and thread id remain.
    loader = _Loader()
    restarted, model = _assistant(
        [ChatTurn("两处都改好了。", (), 100, 5)],
        checkpointer=checkpointer,
        thread_id="ops-assistant:test",
        loader=loader,
    )
    pending = await restarted.pending()
    assert pending is not None and pending.tool == "rewrite_hook"

    done = await restarted.decide(approve=True)

    assert done.kind == "answer" and done.text == "两处都改好了。"
    assert done.draft is not None
    assert done.draft["edits"] == ["replace_claim:fact-1", "rewrite_hook"]
    assert done.draft["view"]["claims"][0]["text"] == RIGHT
    assert done.draft["view"]["hook"] == NEW_HOOK
    assert loader.loads == 1  # draft reloaded once, the recorded edit replayed
    # the model saw the whole conversation from the checkpoint, including the first approval
    assert [m["role"] for m in model.calls[0]][:2] == ["system", "user"]
    assert [(a["tool"], a["approved"]) for a in await restarted.approvals()] == [
        ("replace_claim", True),
        ("rewrite_hook", True),
    ]


@pytest.mark.asyncio
async def test_the_conversation_continues_on_the_same_thread() -> None:
    assistant, model = _assistant(
        [
            ChatTurn("第一个回答", (), 10, 1),
            ChatTurn("第二个回答", (), 10, 1),
        ]
    )

    await assistant.send("第一个问题")
    reply = await assistant.send("第二个问题")

    assert reply.text == "第二个回答"
    roles = [m["role"] for m in model.calls[-1]]
    assert roles == ["system", "user", "assistant", "user"]


@pytest.mark.asyncio
async def test_draft_tools_without_an_open_draft_get_a_hint_not_a_crash() -> None:
    assistant, model = _assistant(
        [
            ChatTurn(None, (_call("1", "check_draft", {}),), 100, 5),
            ChatTurn("请先告诉我是哪条任务。", (), 100, 5),
        ]
    )

    reply = await assistant.send("检查一下草稿")

    assert reply.kind == "answer"
    assert _tool_results(model)[0]["error_code"] == "no_draft_open"


@pytest.mark.asyncio
async def test_a_turn_stops_at_the_round_limit() -> None:
    loop = [
        ChatTurn(None, (_call(str(i), "list_slot_runs", {"business_date": "2026-10-01"}),), 10, 1)
        for i in range(3)
    ]
    assistant, _ = _assistant(loop, max_rounds=2)

    reply = await assistant.send("一直查")

    assert reply.kind == "limit"
    assert len(reply.steps) == 2


@pytest.mark.asyncio
async def test_calls_over_the_limit_are_refused_without_running() -> None:
    calls = tuple(
        _call(str(i), "list_slot_runs", {"business_date": "2026-10-01"}) for i in range(3)
    )
    assistant, model = _assistant(
        [ChatTurn(None, calls, 10, 1), ChatTurn("查不完了。", (), 10, 1)], max_tool_calls=2
    )

    reply = await assistant.send("查三次")

    assert reply.kind == "answer"
    assert len(reply.steps) == 2
    assert _tool_results(model)[-1]["error_code"] == "call_limit"


@pytest.mark.asyncio
async def test_steps_are_traced_with_genai_semantic_convention_names() -> None:
    tracer = JsonlTraceRecorder()
    assistant, _ = _assistant(
        [
            ChatTurn(
                None, (_call("1", "list_copy_runs", {"business_date": "2026-09-30"}),), 900, 20
            ),
            ChatTurn("好的", (), 1200, 15),
        ],
        tracer=tracer,
    )

    await assistant.send("昨天怎么样？")

    records = tracer.records()
    names = [record["name"] for record in records]
    assert names == [
        "chat glm-test",
        "execute_tool list_copy_runs",
        "chat glm-test",
        "invoke_agent ops_assistant",
    ]
    agent = records[-1]
    assert agent["attributes"][OPERATION] == "invoke_agent"
    assert agent["attributes"][INPUT_TOKENS] == 2100
    assert agent["attributes"]["gen_ai.conversation.id"] == assistant.thread_id
    assert {record["trace_id"] for record in records} == {agent["trace_id"]}
    assert all(r["parent_span_id"] == agent["span_id"] for r in records[:-1])
    assert records[1]["attributes"][TOOL_NAME] == "list_copy_runs"
    assert records[1]["attributes"]["gen_ai.tool.call.id"] == "1"
    assert "content" not in json.dumps(records)  # no message bodies in traces
