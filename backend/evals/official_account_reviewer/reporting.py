"""Stable JSON and Markdown projections for Reviewer fixture results."""

from __future__ import annotations

import json

from .metrics import OfficialAccountReviewEvalReport


def canonical_json(report: OfficialAccountReviewEvalReport) -> str:
    return (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def render_markdown(report: OfficialAccountReviewEvalReport) -> str:
    aggregate = report.aggregate
    lines = [
        "# Official-account Reviewer provider-free contract report",
        "",
        f"> {report.disclaimer}",
        "",
        "## Evidence identity",
        "",
        f"- Provider-free: `{str(report.provider_free).lower()}`",
        f"- Live model calls: `{report.live_model_calls}`",
        f"- Dataset: `{report.dataset_version}` / `{report.cases_sha256}`",
        f"- Oracle SHA-256: `{report.oracle_sha256}`",
        f"- Rubric: `{report.rubric_version}` / `{report.rubric_sha256}`",
        f"- Fixture policy: `{report.fixture_policy_version}` / `{report.policy_sha256}`",
        f"- Evaluator bundle SHA-256: `{report.runner_sha256}`",
        "",
        "## Aggregate contract metrics",
        "",
        f"- Passing cases: `{aggregate.passed_count}/{aggregate.case_count}`",
        f"- Hard-gate critical contract precision / recall / F1: "
        f"`{_pct(aggregate.critical_precision)}` / "
        f"`{_pct(aggregate.critical_recall)}` / `{_pct(aggregate.critical_f1)}`",
        f"- False accept count / rate: `{aggregate.false_accept_count}` / "
        f"`{_pct(aggregate.false_accept_rate)}`",
        f"- False reject count / rate: `{aggregate.false_reject_count}` / "
        f"`{_pct(aggregate.false_reject_rate)}`",
        f"- Manual review rate: `{_pct(aggregate.manual_review_rate)}`",
        f"- Unavailable rate: `{_pct(aggregate.unavailable_rate)}`",
        f"- Repairability accuracy: `{_pct(aggregate.repairability_accuracy)}`",
        f"- Exact issue-location accuracy: `{_pct(aggregate.location_accuracy)}`",
        f"- Hard-gate override violations: `{aggregate.hard_gate_override_violation_count}`",
        "",
        "## Dimension coverage",
        "",
        "| Dimension | Cases | Defect-case P/R/F1 | Failed cases |",
        "| --- | ---: | ---: | --- |",
    ]
    for dimension_score in report.dimensions:
        failed = ", ".join(f"`{case_id}`" for case_id in dimension_score.failed_case_ids) or "—"
        lines.append(
            f"| `{dimension_score.dimension.value}` | {dimension_score.case_count} | "
            f"{_pct(dimension_score.defect_precision)} / "
            f"{_pct(dimension_score.defect_recall)} / "
            f"{_pct(dimension_score.defect_f1)} | {failed} |"
        )
    lines.extend(
        [
            "",
            "## Failure cases",
            "",
            "| Case | Expected / actual | Failure codes |",
            "| --- | --- | --- |",
        ]
    )
    failed_scores = tuple(item for item in report.cases if not item.passed)
    if not failed_scores:
        lines.append("| — | All fixture contracts matched | — |")
    else:
        for case_score in failed_scores:
            failures = ", ".join(f"`{code}`" for code in case_score.failure_codes)
            lines.append(
                f"| `{case_score.case_id}` | `{case_score.expected_decision.value}` / "
                f"`{case_score.actual_decision.value}` | {failures} |"
            )
    lines.extend(
        [
            "",
            "Case inputs and evaluator oracle labels are stored in separate files. The frozen "
            "policy receives only case-side typed observations and never receives expected labels.",
            "",
        ]
    )
    return "\n".join(lines)


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"
