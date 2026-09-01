"""Stable JSON and Markdown rendering for image-quality policy evaluation."""

from __future__ import annotations

import json

from pydantic import BaseModel

from .metrics import ImageQualityEvalReport


def canonical_json(model: BaseModel) -> str:
    return (
        json.dumps(
            model.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def render_markdown(report: ImageQualityEvalReport) -> str:
    aggregate = report.aggregate
    lines = [
        "# Image quality provider-free policy baseline",
        "",
        f"> {report.disclaimer}",
        "",
        f"- Dataset: `{report.dataset_version}` ({aggregate.case_count} cases)",
        f"- Dataset SHA-256: `{report.dataset_sha256}`",
        f"- Rubric: `{report.rubric_version}` (`{report.rubric_sha256}`)",
        f"- Decision policy: `{report.decision_policy_version}`",
        f"- Contract cases passed: {aggregate.passed_count}/{aggregate.case_count}",
        "",
        "## Fixture distribution",
        "",
        "| Fixture kind | Cases |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| `{item.fixture_kind.value}` | {item.case_count} |"
        for item in report.fixture_distribution
    )
    lines.extend(
        [
            "",
            "## Critical-defect policy metrics",
            "",
            "| Metric | Result |",
            "| --- | ---: |",
            f"| Critical precision | {_pct(aggregate.critical_precision)} |",
            f"| Critical recall | {_pct(aggregate.critical_recall)} |",
            f"| Critical F1 | {_pct(aggregate.critical_f1)} |",
            f"| False-pass rate | {_pct(aggregate.false_pass_rate)} "
            f"({aggregate.false_pass_count}/{aggregate.critical_gold_case_count}) |",
            f"| Manual-review rate | {_pct(aggregate.manual_review_rate)} "
            f"({aggregate.manual_review_count}/{aggregate.case_count}) |",
            f"| Unavailable rate | {_pct(aggregate.unavailable_rate)} "
            f"({aggregate.unavailable_count}/{aggregate.case_count}) |",
            "",
            "No aggregate image-quality score is produced: an aesthetic signal cannot offset a "
            "critical semantic, identity, text, crop, or duplicate failure.",
            "",
            "## Per-dimension coverage and defect metrics",
            "",
            "| Dimension | Cases | Coverage | Defect P/R/F1 | False pass | Manual review |",
            "| --- | ---: | ---: | --- | ---: | ---: |",
        ]
    )
    for item in report.dimensions:
        lines.append(
            f"| `{item.dimension.value}` | {item.case_count} | "
            f"{_pct(item.observation_coverage)} | "
            f"{_pct(item.defect_precision)} / {_pct(item.defect_recall)} / "
            f"{_pct(item.defect_f1)} | {_pct(item.false_pass_rate)} | "
            f"{_pct(item.manual_review_rate)} |"
        )
    lines.extend(
        [
            "",
            "## Case diagnostics",
            "",
            "| Case | Dimension | Fixture | Expected | Actual | Pass | Diagnostic |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for case in report.cases:
        diagnostics = "; ".join(case.failure_codes) or "—"
        lines.append(
            f"| `{case.case_id}` | `{case.dimension.value}` | `{case.fixture_kind.value}` | "
            f"`{case.expected_decision.value}` | `{case.actual_decision.value}` | "
            f"{'yes' if case.passed else 'no'} | {diagnostics} |"
        )
    lines.extend(
        [
            "",
            "The frozen observations are hand-authored regression inputs. Their perfect agreement "
            "with fixture labels proves only that the typed aggregation and decision policy replay "
            "deterministically; it is not judge-human agreement or a live-model benchmark.",
            "",
        ]
    )
    return "\n".join(lines)


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"
