# ruff: noqa: RUF001
"""The read-only diagnosis agent behind the delivery watchdog."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pytest
from app.application.services.agent_tracing import JsonlTraceRecorder
from app.application.services.copy_repair_agent import ChatToolCall, ChatTurn
from app.application.services.ops_diagnosis import (
    DiagnosisAgent,
    DiagnosisOutcome,
    DiagnosisReport,
    format_diagnosis,
)
from app.core.errors import InvalidProviderOutputError
from app.delivery_watchdog_main import SlotCheck, alert_text
from evals.ops_assistant.fixtures import BLOCKED_RUN, TODAY, FixtureOpsReader

PROBLEMS = (
    "第 2 条文案 review_required（repair_exhausted）：研究团队发布用于机器人学习的世界模型",
)


def _call(call_id: str, name: str, arguments: Mapping[str, object]) -> ChatToolCall:
    return ChatToolCall(call_id, name, json.dumps(arguments, ensure_ascii=False))


def _turn(*calls: ChatToolCall, content: str | None = None) -> ChatTurn:
    return ChatTurn(content, calls, 500, 40)


class Scripted:
    def __init__(self, turns: Sequence[ChatTurn | Exception]) -> None:
        self.turns = list(turns)
        self.tool_names: list[str] = []

    async def complete(self, messages: object, tools: Sequence[Mapping[str, object]]) -> ChatTurn:
        self.tool_names = [str(tool["function"]["name"]) for tool in tools]  # type: ignore[index]
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn


REPORT = {
    "stage": "copy",
    "cause": "第 2 条文案修复后审查仍拦下（outcome_promise），任务停在 review_required。",
    "run_ids": [str(BLOCKED_RUN)],
    "action": "manual_review",
}


@pytest.mark.asyncio
async def test_agent_investigates_with_read_tools_and_ends_with_a_structured_report() -> None:
    model = Scripted(
        [
            _turn(_call("1", "list_copy_runs", {"business_date": TODAY.isoformat()})),
            _turn(_call("2", "get_copy_run", {"run_id": str(BLOCKED_RUN)})),
            _turn(_call("3", "report_diagnosis", REPORT)),
        ]
    )
    reader = FixtureOpsReader()
    recorder = JsonlTraceRecorder()

    outcome = await DiagnosisAgent(model, reader, tracer=recorder, model_name="glm-test").diagnose(
        TODAY, "noon", PROBLEMS
    )

    assert outcome.stopped == "reported"
    assert outcome.report is not None and outcome.report.stage == "copy"
    assert outcome.report.needs_approval is False
    assert outcome.tools_called == ["list_copy_runs", "get_copy_run", "report_diagnosis"]
    assert reader.calls == ["list_copy_runs", "get_copy_run"]
    assert (outcome.rounds, outcome.prompt_tokens) == (3, 1_500)
    # Only read tools and the report are offered: the agent cannot change anything.
    assert set(model.tool_names) == {
        "get_copy_run",
        "get_day_trace",
        "list_copy_runs",
        "list_deliveries",
        "list_slot_runs",
        "report_diagnosis",
    }
    operations = [record["attributes"]["gen_ai.operation.name"] for record in recorder.records()]
    assert operations.count("chat") == 3 and operations.count("execute_tool") == 3
    assert operations[-1] == "invoke_agent"
    text = format_diagnosis(outcome.report)
    assert "出问题的环节：文案" in text and "人工检查" in text and str(BLOCKED_RUN)[:8] in text


def test_a_suggested_rerun_is_marked_as_needing_approval() -> None:
    report = DiagnosisReport.model_validate(
        {**REPORT, "stage": "delivery", "action": "rerun_delivery"}
    )

    assert report.needs_approval
    assert "需运营批准，系统不会自动执行" in format_diagnosis(report)


@pytest.mark.asyncio
async def test_an_invalid_report_is_returned_as_a_structured_error_and_can_be_corrected() -> None:
    model = Scripted(
        [
            _turn(_call("1", "report_diagnosis", {**REPORT, "action": "delete_drafts"})),
            _turn(_call("2", "report_diagnosis", REPORT)),
        ]
    )

    outcome = await DiagnosisAgent(model, FixtureOpsReader()).diagnose(TODAY, "noon", PROBLEMS)

    assert outcome.stopped == "reported" and outcome.tool_calls == 2


@pytest.mark.asyncio
async def test_an_answer_without_the_report_gets_one_reminder_then_stops() -> None:
    model = Scripted([_turn(content="文案被拦了。"), _turn(content="就是文案被拦了。")])

    outcome = await DiagnosisAgent(model, FixtureOpsReader()).diagnose(TODAY, "noon", PROBLEMS)

    assert (outcome.stopped, outcome.report, outcome.rounds) == ("no_report", None, 2)


@pytest.mark.asyncio
async def test_a_model_failure_leaves_no_report() -> None:
    model = Scripted([InvalidProviderOutputError(("invalid_schema",))])

    outcome = await DiagnosisAgent(model, FixtureOpsReader()).diagnose(TODAY, "noon", PROBLEMS)

    assert outcome.stopped == "model_error" and outcome.report is None
    assert outcome.error_code is not None


@pytest.mark.asyncio
async def test_tool_calls_are_bounded() -> None:
    looping = [
        _turn(
            *(
                _call(f"{n}-{k}", "list_slot_runs", {"business_date": TODAY.isoformat()})
                for k in range(4)
            )
        )
        for n in range(4)
    ]

    outcome = await DiagnosisAgent(
        Scripted(looping), FixtureOpsReader(), max_tool_calls=5
    ).diagnose(TODAY, "noon", PROBLEMS)

    assert outcome.stopped == "call_limit" and outcome.tool_calls == 5


def test_the_alert_carries_the_diagnosis_and_the_log_record_stays_bodiless() -> None:
    check = SlotCheck(TODAY, "noon", problems=list(PROBLEMS))
    report = DiagnosisReport.model_validate(REPORT)
    diagnosis = DiagnosisOutcome(report=report, stopped="reported", rounds=3, tool_calls=3)

    text = alert_text(check, diagnosis)
    plain = alert_text(check, DiagnosisOutcome(report=None, stopped="model_error"))

    assert text.startswith(check.message()) and "【自动诊断】" in text
    assert plain == check.message()
    record = diagnosis.record()
    assert record["stage"] == "copy" and record["needs_approval"] is False
    assert json.dumps(record, ensure_ascii=False)
