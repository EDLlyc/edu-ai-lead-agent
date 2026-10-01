# ruff: noqa: RUF001

from __future__ import annotations

import json
from datetime import date
from uuid import UUID

import pytest
from app.application.services.copy_repair_agent import ChatTurn
from app.application.services.ops_assistant import (
    AssistantSession,
    OpsAssistant,
    build_assistant_registry,
)
from tests.unit.test_copy_repair_tools import EVIDENCE_A, _call, _workspace
from tests.unit.test_ops_tools import RUN_ID, _FakeReader


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


def _assistant(turns: list[ChatTurn]) -> tuple[OpsAssistant, _Scripted, AssistantSession]:
    session = AssistantSession()

    async def load(run_id: UUID):  # type: ignore[no-untyped-def]
        assert run_id == RUN_ID
        return _workspace(claim_text="该模型在五项测试中表现领先。")

    registry = build_assistant_registry(_FakeReader(), session, load)
    model = _Scripted(turns)
    return OpsAssistant(model, registry, session, today=date(2026, 10, 1)), model, session


def _tool_results(model: _Scripted) -> list[dict[str, object]]:
    return [json.loads(m["content"]) for m in model.calls[-1] if m["role"] == "tool"]  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_reads_run_at_once_and_the_answer_cites_them() -> None:
    assistant, model, _ = _assistant(
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


@pytest.mark.asyncio
async def test_edits_pause_for_approval_and_run_only_when_approved() -> None:
    new_claim = {
        "claim_id": "fact-1",
        "text": "该模型在三项测试中表现领先。",
        "evidence_ids": [str(EVIDENCE_A)],
    }
    assistant, _, session = _assistant(
        [
            ChatTurn(None, (_call("1", "open_draft", {"run_id": str(RUN_ID)}),), 100, 5),
            ChatTurn(None, (_call("2", "replace_claim", new_claim),), 100, 5),
            ChatTurn("已在沙盒里改好，请到审核页提交。", (), 100, 5),
        ]
    )

    paused = await assistant.send("把这条的错误数字改掉")

    assert paused.kind == "approval" and paused.approval is not None
    assert paused.approval.tool == "replace_claim"
    assert paused.approval.preview == {
        "claim_id": "fact-1",
        "before": "该模型在五项测试中表现领先。",
        "after": "该模型在三项测试中表现领先。",
    }
    assert session.workspace is not None and session.workspace.edits == []  # nothing ran yet

    done = await assistant.decide(approve=True)

    assert done.kind == "answer"
    assert session.workspace.draft.claims[0].text == "该模型在三项测试中表现领先。"
    assert [(s.tool, s.approval) for s in done.steps] == [("replace_claim", "approved")]
    assert done.draft is not None and done.draft["edits"] == ["replace_claim:fact-1"]


@pytest.mark.asyncio
async def test_a_denied_edit_goes_back_to_the_model_and_changes_nothing() -> None:
    assistant, model, session = _assistant(
        [
            ChatTurn(None, (_call("1", "open_draft", {"run_id": str(RUN_ID)}),), 100, 5),
            ChatTurn(
                None,
                (_call("2", "rewrite_hook", {"text": "机器人在学着观察世界，和孩子聊聊吧🔍"}),),
                100,
                5,
            ),
            ChatTurn("好的，引导语保持不变。", (), 100, 5),
        ]
    )

    paused = await assistant.send("改一下引导语")
    before = session.workspace.draft if session.workspace else None
    done = await assistant.decide(approve=False)

    assert paused.kind == "approval" and paused.approval is not None
    assert paused.approval.preview["after"] == "机器人在学着观察世界，和孩子聊聊吧🔍"
    assert done.kind == "answer"
    assert session.workspace is not None and session.workspace.draft == before
    assert _tool_results(model)[-1]["error_code"] == "denied_by_operator"
    assert [(s.tool, s.approval) for s in done.steps] == [("rewrite_hook", "denied")]


@pytest.mark.asyncio
async def test_draft_tools_without_an_open_draft_get_a_hint_not_a_crash() -> None:
    assistant, model, _ = _assistant(
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
    session = AssistantSession()

    async def load(run_id: UUID):  # type: ignore[no-untyped-def]
        raise AssertionError

    assistant = OpsAssistant(
        _Scripted(loop),
        build_assistant_registry(_FakeReader(), session, load),
        session,
        today=date(2026, 10, 1),
        max_rounds=2,
    )

    reply = await assistant.send("一直查")

    assert reply.kind == "limit"
    assert len(reply.steps) == 2
