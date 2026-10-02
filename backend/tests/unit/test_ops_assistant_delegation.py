# ruff: noqa: RUF001
"""The ops assistant hands a draft to the copy repair sub-agent; its change set needs approval."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from app.application.services.agent_tracing import OPERATION, JsonlTraceRecorder
from app.application.services.copy_repair_agent import ChatTurn
from app.application.services.ops_assistant import OpsAssistant
from app.application.services.ops_tools import CopyIssueItem, CopyRunDetail, DraftItem
from langgraph.checkpoint.memory import InMemorySaver
from tests.unit.test_copy_repair_tools import EVIDENCE_A, _call
from tests.unit.test_ops_assistant import NEW_HOOK, RIGHT, WRONG, _Loader, _open, _Scripted
from tests.unit.test_ops_tools import RUN_ID, _FakeReader


class _IssueReader(_FakeReader):
    """The run's newest draft (version 2) was blocked for the number and the hook."""

    def __init__(self, *, issues: bool = True) -> None:
        super().__init__()
        self.issues = issues

    async def get_copy_run(self, run_id: UUID) -> CopyRunDetail:
        assert run_id == RUN_ID
        blocked = (
            CopyIssueItem(
                stage="validation",
                code="claim_not_in_evidence",
                severity="error",
                claim_key="fact-1",
                message="“五项测试”在证据里找不到。",
            ),
            CopyIssueItem(
                stage="audit",
                code="outcome_promise",
                severity="error",
                claim_key=None,
                message="引导语承诺学习效果。",
            ),
            CopyIssueItem(
                stage="audit",
                code="tone",
                severity="warning",
                claim_key=None,
                message="语气可以更轻松。",
            ),
        )
        return CopyRunDetail(
            run_id=run_id,
            title="机器人世界模型取得新进展",
            status="review_required",
            error_code="repair_exhausted",
            repair_count=1,
            job_status="succeeded",
            job_attempts=1,
            job_error_code=None,
            drafts=tuple(
                DraftItem(
                    version=version,
                    created_at=datetime(2026, 10, 1, 4, tzinfo=UTC),
                    hook="引导语",
                    claim_count=2,
                    audit_accepted=False,
                    audit_prompt_version="moments-auditor-v22-enumerated-codes",
                    issues=blocked if self.issues and version == 2 else (),
                )
                for version in (1, 2)
            ),
        )


class _SubAgentModel:
    """The repair sub-agent's model: only ever sees the repair tools."""

    def __init__(self, turns: list[ChatTurn]) -> None:
        self.turns = turns
        self.calls: list[list[dict[str, object]]] = []

    async def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        names = {tool["function"]["name"] for tool in tools}
        assert "open_draft" not in names and "delegate_repair" not in names
        self.calls.append([dict(m) for m in messages])
        return self.turns.pop(0)


def _fix_both() -> list[ChatTurn]:
    replace: dict[str, object] = {
        "claim_id": "fact-1",
        "text": RIGHT,
        "evidence_ids": [str(EVIDENCE_A)],
    }
    return [
        ChatTurn(
            None,
            (
                _call("s1", "replace_claim", replace),
                _call("s2", "rewrite_hook", {"text": NEW_HOOK}),
                _call("s3", "check_draft", {}),
            ),
            700,
            60,
        )
    ]


def _delegate(call_id: str = "2", **arguments: object) -> ChatTurn:
    return ChatTurn(None, (_call(call_id, "delegate_repair", arguments),), 100, 5)


def _assistant(
    turns: list[ChatTurn],
    sub_turns: list[ChatTurn],
    *,
    reader: _FakeReader | None = None,
    checkpointer: InMemorySaver | None = None,
    thread_id: str | None = None,
    loader: _Loader | None = None,
    tracer: JsonlTraceRecorder | None = None,
    max_tool_calls: int = 16,
) -> tuple[OpsAssistant, _Scripted, _SubAgentModel]:
    model, sub_model = _Scripted(turns), _SubAgentModel(sub_turns)
    assistant = OpsAssistant(
        model,
        reader or _IssueReader(),
        loader or _Loader(),
        today=date(2026, 10, 1),
        checkpointer=checkpointer,
        thread_id=thread_id,
        tracer=tracer,
        model_name="glm-test",
        repair_model=sub_model,
        max_tool_calls=max_tool_calls,
    )
    return assistant, model, sub_model


def _last_tool_result(model: _Scripted) -> dict[str, Any]:
    tool_messages = [m for m in model.calls[-1] if m["role"] == "tool"]
    result: dict[str, Any] = json.loads(str(tool_messages[-1]["content"]))
    return result


@pytest.mark.asyncio
async def test_a_delegated_change_set_waits_for_one_approval_then_applies_every_edit() -> None:
    assistant, model, sub_model = _assistant(
        [_open(), _delegate(), ChatTurn("两处都改好了，请到审核页提交。", (), 100, 5)],
        _fix_both(),
    )

    paused = await assistant.send("第2条被拦了，把问题都修好")

    assert paused.kind == "approval" and paused.approval is not None
    assert paused.approval.tool == "delegate_repair"
    preview = paused.approval.preview
    assert preview["edits"] == [
        {"tool": "replace_claim", "claim_id": "fact-1", "before": WRONG, "after": RIGHT},
        {
            "tool": "rewrite_hook",
            "claim_id": None,
            "before": preview["edits"][1]["before"],
            "after": NEW_HOOK,
        },
    ]
    assert preview["edits"][1]["before"] != NEW_HOOK
    # newest draft's errors only (the warning is not a blocking issue)
    assert preview["issues"] == ["claim_not_in_evidence", "outcome_promise"]
    assert preview["sub_agent"] == {"stopped": "checked", "rounds": 1, "tool_calls": 3}
    assert paused.draft is not None and paused.draft["edits"] == []  # nothing applied yet
    assert (paused.prompt_tokens, paused.completion_tokens) == (100 + 100 + 700, 5 + 5 + 60)
    sub_prompt = json.loads(str(sub_model.calls[0][1]["content"]))
    assert [issue["code"] for issue in sub_prompt["blocking_issues"]] == [
        "claim_not_in_evidence",
        "outcome_promise",
    ]

    done = await assistant.decide(approve=True)

    assert done.kind == "answer" and done.text == "两处都改好了，请到审核页提交。"
    assert done.draft is not None
    assert done.draft["edits"] == ["replace_claim:fact-1", "rewrite_hook"]
    assert done.draft["view"]["claims"][0]["text"] == RIGHT
    assert done.draft["view"]["hook"] == NEW_HOOK
    assert [(s.tool, s.ok, s.approval, s.delegated) for s in done.steps] == [
        ("delegate_repair", True, "approved", ["replace_claim", "rewrite_hook"])
    ]
    result = _last_tool_result(model)
    assert result["ok"] is True and result["applied"] == 2
    assert result["sub_agent_stopped"] == "checked"
    assert len(sub_model.calls) == 1  # the approval did not run the sub-agent again
    assert [(a["tool"], a["approved"]) for a in await assistant.approvals()] == [
        ("delegate_repair", True)
    ]


@pytest.mark.asyncio
async def test_a_denied_change_set_leaves_the_sandbox_unchanged() -> None:
    assistant, model, _ = _assistant(
        [_open(), _delegate(), ChatTurn("好的，草稿保持原样。", (), 100, 5)], _fix_both()
    )

    await assistant.send("把问题都修好")
    done = await assistant.decide(approve=False)

    assert done.kind == "answer"
    assert done.draft is not None and done.draft["edits"] == []
    assert done.draft["view"]["claims"][0]["text"] == WRONG
    assert [(s.tool, s.error_code, s.approval) for s in done.steps] == [
        ("delegate_repair", "denied_by_operator", "denied")
    ]
    assert _last_tool_result(model)["error_code"] == "denied_by_operator"


@pytest.mark.asyncio
async def test_a_sub_agent_that_gives_up_is_reported_without_an_approval() -> None:
    assistant, model, sub_model = _assistant(
        [_open(), _delegate(), ChatTurn("修复助手没能修好，需要人工处理。", (), 100, 5)],
        [ChatTurn("放弃", (), 300, 3)],
    )

    reply = await assistant.send("把问题都修好")

    assert reply.kind == "answer" and reply.approval is None
    result = _last_tool_result(model)
    assert result["error_code"] == "no_change" and "gave_up" in str(result["hint"])
    assert [(s.tool, s.ok, s.approval, s.delegated) for s in reply.steps][-1] == (
        "delegate_repair",
        False,
        "auto",
        [],
    )
    assert len(sub_model.calls) == 1
    assert reply.draft is not None and reply.draft["edits"] == []


@pytest.mark.asyncio
async def test_nothing_to_repair_and_unknown_claims_never_start_the_sub_agent() -> None:
    assistant, model, sub_model = _assistant(
        [
            _open(),
            _delegate(),
            _delegate(
                "3", issues=[{"code": "claim_not_in_evidence", "message": "x", "claim_id": "no"}]
            ),
            ChatTurn("没有需要修的问题。", (), 100, 5),
        ],
        [],
        reader=_IssueReader(issues=False),
    )

    reply = await assistant.send("修一下")

    results = [json.loads(str(m["content"])) for m in model.calls[-1] if m["role"] == "tool"][-2:]
    assert [result["error_code"] for result in results] == ["nothing_to_repair", "claim_not_found"]
    assert sub_model.calls == []
    assert reply.kind == "answer"


@pytest.mark.asyncio
async def test_model_named_issues_are_used_and_delegation_needs_an_open_draft() -> None:
    issues = [{"code": "outcome_promise", "message": "引导语承诺学习效果。"}]
    hook_only = [
        ChatTurn(
            None,
            (
                _call("s1", "rewrite_hook", {"text": NEW_HOOK}),
                _call("s2", "check_draft", {}),
            ),
            500,
            40,
        )
    ]
    assistant, model, sub_model = _assistant(
        [
            _delegate("0"),
            _open(),
            _delegate(issues=issues),
            ChatTurn("引导语改好了。", (), 100, 5),
        ],
        hook_only,
        reader=_IssueReader(issues=False),
    )

    paused = await assistant.send("引导语有效果承诺，交给修复助手改")
    done = await assistant.decide(approve=True)

    first = json.loads(str(model.calls[1][-1]["content"]))
    assert first["error_code"] == "no_draft_open"
    assert paused.approval is not None
    assert [edit["tool"] for edit in paused.approval.preview["edits"]] == ["rewrite_hook"]
    sub_prompt = json.loads(str(sub_model.calls[0][1]["content"]))
    assert [issue["code"] for issue in sub_prompt["blocking_issues"]] == ["outcome_promise"]
    assert done.draft is not None and done.draft["edits"] == ["rewrite_hook"]


@pytest.mark.asyncio
async def test_delegation_counts_against_the_turn_call_limit() -> None:
    assistant, model, sub_model = _assistant(
        [_open(), _delegate(), ChatTurn("步骤用完了。", (), 100, 5)],
        _fix_both(),
        max_tool_calls=1,
    )

    reply = await assistant.send("修好")

    assert _last_tool_result(model)["error_code"] == "call_limit"
    assert sub_model.calls == []
    assert reply.kind == "answer"


@pytest.mark.asyncio
async def test_a_delegated_approval_survives_a_restart_and_its_edits_replay_later() -> None:
    checkpointer = InMemorySaver()
    first, _, _ = _assistant(
        [_open(), _delegate()], _fix_both(), checkpointer=checkpointer, thread_id="t:delegate"
    )
    await first.send("把问题都修好")

    # Restart: a new assistant whose sub-agent model has no turns (it must not run again).
    loader = _Loader()
    restarted, _, sub_model = _assistant(
        [ChatTurn("改好了。", (), 100, 5)],
        [],
        checkpointer=checkpointer,
        thread_id="t:delegate",
        loader=loader,
    )
    pending = await restarted.pending()
    assert pending is not None and pending.tool == "delegate_repair"
    done = await restarted.decide(approve=True)
    assert done.draft is not None
    assert done.draft["edits"] == ["replace_claim:fact-1", "rewrite_hook"]
    assert sub_model.calls == [] and loader.loads == 1

    # Another restart: the sandbox is rebuilt from the recorded edits of the change set.
    replay_loader = _Loader()
    later, _, _ = _assistant(
        [ChatTurn("草稿还在。", (), 10, 1)],
        [],
        checkpointer=checkpointer,
        thread_id="t:delegate",
        loader=replay_loader,
    )
    reply = await later.send("现在草稿是什么样？")
    assert reply.draft is not None
    assert reply.draft["edits"] == ["replace_claim:fact-1", "rewrite_hook"]
    assert reply.draft["view"]["claims"][0]["text"] == RIGHT
    assert reply.draft["view"]["hook"] == NEW_HOOK
    assert replay_loader.loads == 1


@pytest.mark.asyncio
async def test_sub_agent_steps_are_a_nested_invoke_agent_span() -> None:
    tracer = JsonlTraceRecorder()
    assistant, _, _ = _assistant(
        [_open(), _delegate(), ChatTurn("好了。", (), 10, 1)], _fix_both(), tracer=tracer
    )

    await assistant.send("把问题都修好")
    await assistant.decide(approve=True)

    spans = tracer.records()
    by_id = {span["span_id"]: span for span in spans}
    sub = next(span for span in spans if span["name"] == "invoke_agent copy_repair")
    propose = by_id[sub["parent_span_id"]]
    assert propose["name"] == "execute_tool delegate_repair"
    assert propose["attributes"]["ops_assistant.phase"] == "propose"
    assert by_id[propose["parent_span_id"]]["name"] == "invoke_agent ops_assistant"
    children = [span for span in spans if span["parent_span_id"] == sub["span_id"]]
    assert [span["attributes"][OPERATION] for span in children] == [
        "chat",
        "execute_tool",
        "execute_tool",
        "execute_tool",
    ]
    assert sub["attributes"]["copy_repair.stopped"] == "checked"
    assert sub["attributes"]["gen_ai.agent.name"] == "copy_repair"
    applied = [
        span
        for span in spans
        if span["name"] == "execute_tool delegate_repair"
        and span["attributes"].get("ops_assistant.phase") == "apply"
    ]
    assert applied and applied[0]["attributes"]["ops_assistant.change_set.applied"] == 2
