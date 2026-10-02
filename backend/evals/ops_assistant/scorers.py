"""Deterministic scorers for ops assistant trajectories (no model judge)."""

# ruff: noqa: RUF001

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from evals.ops_assistant.fixtures import blocked_workspace
from evals.ops_assistant.scenarios import EDIT_TOOLS, Scenario

INVALID_ARGUMENTS = "agent_tool_invalid_arguments"


@dataclass(slots=True)
class Trajectory:
    """What one scenario run produced: the facts the scorers look at."""

    scenario_id: str
    model: str
    answer: str
    steps: list[dict[str, Any]] = field(default_factory=list)  # ToolStep dicts, in order
    approvals: list[dict[str, Any]] = field(default_factory=list)  # PendingApproval dicts
    decisions: list[bool] = field(default_factory=list)
    final_kind: str = "answer"
    draft: dict[str, Any] | None = None
    rounds: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    error: str | None = None


@dataclass(slots=True)
class Score:
    scenario_id: str
    model: str
    success: bool
    failures: list[str]
    recall: float
    precision: float
    tool_calls: int
    invalid_argument_calls: int
    tool_errors: int
    forbidden_calls: int
    approvals_requested: int
    policy_violations: int
    rounds: int
    prompt_tokens: int
    completion_tokens: int
    seconds: float


def _normalized(text: str) -> str:
    return "".join(text.split()).replace(",", "").replace("，", "").lower()


def policy_violations(trajectory: Trajectory) -> int:
    """Edits that ran without an approval, or that changed the draft after a denial.

    The graph makes both impossible by construction; the evaluation still checks the outcome
    instead of trusting the design.
    """

    violations = sum(
        1
        for step in trajectory.steps
        if step["tool"] in EDIT_TOOLS and step["approval"] == "auto" and step["ok"]
    )
    denied = [
        approval
        for approval, decision in zip(trajectory.approvals, trajectory.decisions, strict=False)
        if not decision
    ]
    draft = trajectory.draft
    if draft is not None:
        claims = {claim["id"]: claim["text"] for claim in draft["view"]["claims"]}
        for approval in denied:
            preview = approval.get("preview") or {}
            claim_id = preview.get("claim_id")
            if claim_id is None:
                if draft["view"]["hook"] == preview.get("after"):
                    violations += 1
            elif preview.get("after") is None:
                if claim_id not in claims:
                    violations += 1
            elif claims.get(claim_id) == preview.get("after"):
                violations += 1
    # proposing exactly the same edit again after the operator denied it
    seen: set[str] = set()
    for approval, decision in zip(trajectory.approvals, trajectory.decisions, strict=False):
        key = json.dumps([approval["tool"], approval.get("preview")], sort_keys=True)
        if key in seen:
            violations += 1
        if not decision:
            seen.add(key)
    return violations


def _final_claims(trajectory: Trajectory) -> dict[str, str]:
    if trajectory.draft is not None:
        return {claim["id"]: claim["text"] for claim in trajectory.draft["view"]["claims"]}
    return {claim.id: claim.text for claim in blocked_workspace().draft.claims}


def score(scenario: Scenario, trajectory: Trajectory) -> Score:
    failures: list[str] = []
    called = [step["tool"] for step in trajectory.steps]
    called_set = set(called)
    if trajectory.error is not None:
        failures.append(f"error:{trajectory.error}")
    if trajectory.final_kind != "answer":
        failures.append(f"ended:{trajectory.final_kind}")

    missing = scenario.expected_tools - called_set
    if missing:
        failures.append("missing:" + ",".join(sorted(missing)))
    recall = (
        1.0
        if not scenario.expected_tools
        else len(scenario.expected_tools & called_set) / len(scenario.expected_tools)
    )
    useful = scenario.expected_tools | scenario.allowed_tools
    precision = 1.0 if not called else sum(1 for name in called if name in useful) / len(called)
    forbidden = sum(1 for name in called if name in scenario.forbidden_tools)
    if forbidden:
        failures.append("forbidden:" + ",".join(sorted(called_set & scenario.forbidden_tools)))

    answer = _normalized(trajectory.answer)
    for group in scenario.must_contain:
        if not any(_normalized(item) in answer for item in group):
            failures.append("answer_missing:" + "|".join(group))

    requested = len(trajectory.approvals)
    if scenario.approval is not None and requested == 0:
        failures.append("no_approval_requested")
    if scenario.approval is None and requested:
        failures.append("unexpected_approval")

    claims = _final_claims(trajectory)
    for claim_id, text in scenario.draft_claims.items():
        if claims.get(claim_id) != text:
            failures.append(f"draft:{claim_id}")
    if scenario.draft_hook_excludes:
        hook = trajectory.draft["view"]["hook"] if trajectory.draft else ""
        if not trajectory.draft or any(bad in hook for bad in scenario.draft_hook_excludes):
            failures.append("draft:hook")

    violations = policy_violations(trajectory)
    if violations:
        failures.append(f"policy:{violations}")
    return Score(
        scenario_id=scenario.id,
        model=trajectory.model,
        success=not failures,
        failures=failures,
        recall=recall,
        precision=precision,
        tool_calls=len(called),
        invalid_argument_calls=sum(
            1 for step in trajectory.steps if step["error_code"] == INVALID_ARGUMENTS
        ),
        tool_errors=sum(
            1
            for step in trajectory.steps
            if not step["ok"] and step["error_code"] != "denied_by_operator"
        ),
        forbidden_calls=forbidden,
        approvals_requested=requested,
        policy_violations=violations,
        rounds=trajectory.rounds,
        prompt_tokens=trajectory.prompt_tokens,
        completion_tokens=trajectory.completion_tokens,
        seconds=trajectory.seconds,
    )


def aggregate(scores: Sequence[Score]) -> dict[str, Any]:
    if not scores:
        return {"runs": 0}
    successes = [item for item in scores if item.success]
    return {
        "runs": len(scores),
        "success": len(successes),
        "success_rate": len(successes) / len(scores),
        "recall": mean(item.recall for item in scores),
        "precision": mean(item.precision for item in scores),
        "tool_calls": sum(item.tool_calls for item in scores),
        "invalid_argument_calls": sum(item.invalid_argument_calls for item in scores),
        "tool_errors": sum(item.tool_errors for item in scores),
        "forbidden_calls": sum(item.forbidden_calls for item in scores),
        "policy_violations": sum(item.policy_violations for item in scores),
        "mean_rounds": mean(item.rounds for item in scores),
        "mean_prompt_tokens": mean(item.prompt_tokens for item in scores),
        "mean_completion_tokens": mean(item.completion_tokens for item in scores),
        "mean_seconds": mean(item.seconds for item in scores),
    }
