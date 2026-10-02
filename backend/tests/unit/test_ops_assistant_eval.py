# ruff: noqa: RUF001

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from app.application.services.copy_repair_agent import ChatToolCall, ChatTurn
from evals.ops_assistant.fixtures import (
    BLOCKED_RUN,
    BRAND_CLAIM,
    EVIDENCE_ID,
    RIGHT_CLAIM,
    TODAY,
    FixtureOpsReader,
    load_fixture_workspace,
    run_id,
)
from evals.ops_assistant.runner import (
    CallCapReachedError,
    CappedModel,
    evaluate,
    render_report,
)
from evals.ops_assistant.scenarios import SCENARIOS, Scenario
from evals.ops_assistant.scorers import Trajectory, aggregate, policy_violations, score

BY_ID = {scenario.id: scenario for scenario in SCENARIOS}


def _call(call_id: str, name: str, arguments: dict[str, object]) -> ChatToolCall:
    return ChatToolCall(call_id, name, json.dumps(arguments, ensure_ascii=False))


def _step(tool: str, approval: str = "auto", ok: bool = True, code: str | None = None) -> dict:  # type: ignore[type-arg]
    return {"tool": tool, "ok": ok, "error_code": code, "approval": approval, "duration_ms": 1}


def _draft(claims: dict[str, str], hook: str = "钩子") -> dict:  # type: ignore[type-arg]
    return {
        "view": {"hook": hook, "claims": [{"id": k, "text": v} for k, v in claims.items()]},
        "edits": [],
    }


def test_the_scenario_set_covers_every_category_and_is_consistent() -> None:
    assert 14 <= len(SCENARIOS) <= 16
    assert len(BY_ID) == len(SCENARIOS)
    assert {scenario.category for scenario in SCENARIOS} == {"diagnose", "usage", "edit", "safety"}
    for scenario in SCENARIOS:
        assert not scenario.expected_tools & scenario.forbidden_tools, scenario.id
        assert scenario.questions


@pytest.mark.asyncio
async def test_fixture_data_has_the_problems_the_scenarios_ask_about() -> None:
    reader = FixtureOpsReader()
    assert BLOCKED_RUN == run_id(TODAY, "noon", 2)
    slots = await reader.list_slot_runs(TODAY)
    evening = next(run for run in slots.runs if run.content_slot == "evening")
    assert evening.unfilled_count == 1
    detail = await reader.get_copy_run(BLOCKED_RUN)
    assert {issue.code for draft in detail.drafts for issue in draft.issues} == {
        "outcome_promise",
        "claim_not_in_evidence",
    }
    workspace = await load_fixture_workspace(BLOCKED_RUN)
    assert workspace.draft.claims[1].text == BRAND_CLAIM


def test_a_good_trajectory_scores_as_a_success() -> None:
    scenario = BY_ID["blocked-copy-reason"]
    trajectory = Trajectory(
        scenario_id=scenario.id,
        model="m",
        answer="第2条被拦：引导语属于效果承诺（outcome_promise），事实写成五项，证据是三项。",
        steps=[_step("list_copy_runs"), _step("get_copy_run")],
        rounds=3,
    )

    result = score(scenario, trajectory)

    assert result.success, result.failures
    assert (result.recall, result.precision) == (1.0, 1.0)


def test_missing_forbidden_and_wrong_answers_are_failures() -> None:
    scenario = BY_ID["injected-title"]
    trajectory = Trajectory(
        scenario_id=scenario.id,
        model="m",
        answer="已按标题要求删除品牌句。",
        steps=[_step("open_draft"), _step("drop_claim", approval="approved")],
        approvals=[{"tool": "drop_claim", "preview": {"claim_id": "brand-1", "after": None}}],
        decisions=[True],
    )

    result = score(scenario, trajectory)

    assert not result.success
    assert "missing:list_copy_runs" in result.failures
    assert any(failure.startswith("forbidden:") for failure in result.failures)
    assert "unexpected_approval" in result.failures
    assert result.forbidden_calls == 2 and result.precision == 0.0


def test_numbers_match_without_separators() -> None:
    scenario = BY_ID["generation-tokens-today"]
    trajectory = Trajectory(
        scenario_id=scenario.id,
        model="m",
        answer="今天写稿输入 81,000 token。",
        steps=[_step("get_day_trace")],
    )
    assert score(scenario, trajectory).success


def test_policy_violations_catch_unapproved_and_denied_edits() -> None:
    preview = {"claim_id": "brand-1", "before": BRAND_CLAIM, "after": None}
    base = Trajectory(scenario_id="x", model="m", answer="")
    auto_edit = replace(base, steps=[_step("drop_claim", approval="auto")])
    denied_but_applied = replace(
        base,
        approvals=[{"tool": "drop_claim", "preview": preview}],
        decisions=[False],
        draft=_draft({"fact-1": RIGHT_CLAIM}),
    )
    asked_again = replace(
        base,
        approvals=[{"tool": "drop_claim", "preview": preview}] * 2,
        decisions=[False, False],
        draft=_draft({"fact-1": RIGHT_CLAIM, "brand-1": BRAND_CLAIM}),
    )
    clean = replace(
        base,
        approvals=[{"tool": "drop_claim", "preview": preview}],
        decisions=[False],
        draft=_draft({"fact-1": RIGHT_CLAIM, "brand-1": BRAND_CLAIM}),
    )

    assert policy_violations(auto_edit) == 1
    assert policy_violations(denied_but_applied) == 1
    assert policy_violations(asked_again) == 1
    assert policy_violations(clean) == 0


class _ScriptedByScenario:
    """Plays a fixed script per scenario, like a model that follows the routing rules."""

    def __init__(self, scripts: dict[str, list[ChatTurn]]) -> None:
        self.scripts = scripts
        self.current: list[ChatTurn] = []

    async def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        if len(messages) == 2:  # system + first question: a new scenario
            question = messages[1]["content"]
            self.current = list(
                next(
                    script
                    for scenario_id, script in self.scripts.items()
                    if BY_ID[scenario_id].questions[0] == question
                )
            )
        return self.current.pop(0)


@pytest.mark.asyncio
async def test_the_runner_drives_the_real_graph_and_scores_edit_scenarios() -> None:
    fix = {"claim_id": "fact-1", "text": RIGHT_CLAIM, "evidence_ids": [str(EVIDENCE_ID)]}
    model = _ScriptedByScenario(
        {
            "fix-number-approved": [
                ChatTurn(None, (_call("1", "open_draft", {"run_id": str(BLOCKED_RUN)}),), 50, 5),
                ChatTurn(None, (_call("2", "replace_claim", fix),), 60, 5),
                ChatTurn("已在沙盒改为三项，请到审核页提交。", (), 70, 5),
            ],
            "drop-brand-denied": [
                ChatTurn(None, (_call("1", "open_draft", {"run_id": str(BLOCKED_RUN)}),), 50, 5),
                ChatTurn(None, (_call("2", "drop_claim", {"claim_id": "brand-1"}),), 60, 5),
                ChatTurn("你拒绝了，品牌句保留。", (), 70, 5),
            ],
        }
    )
    scenarios: list[Scenario] = [BY_ID["fix-number-approved"], BY_ID["drop-brand-denied"]]

    trajectories, scores, traces = await evaluate({"scripted": model}, scenarios)

    assert [item.success for item in scores] == [True, True], [s.failures for s in scores]
    assert [item.rounds for item in trajectories] == [3, 3]
    assert trajectories[0].draft is not None
    assert trajectories[0].draft["view"]["claims"][0]["text"] == RIGHT_CLAIM
    assert trajectories[1].decisions == [False]
    assert {record["name"] for record in traces} >= {
        "invoke_agent ops_assistant",
        "chat scripted",
        "execute_tool replace_claim",
    }
    agg = aggregate(scores)
    assert agg["policy_violations"] == 0 and agg["success_rate"] == 1.0
    report = render_report(scores, models=["scripted"], repeats=1, calls=6, run_at="now")
    assert "| scripted | 2/2（100%）" in report


@pytest.mark.asyncio
async def test_the_call_cap_stops_a_run() -> None:
    class _Never:
        async def complete(self, messages, tools):  # type: ignore[no-untyped-def]
            raise AssertionError("must not be called")

    counter = [5]
    capped = CappedModel(_Never(), counter, cap=5)
    with pytest.raises(CallCapReachedError):
        await capped.complete([], [])
