"""Stable JSON and Markdown output for digital-IP fixture evaluation."""

from __future__ import annotations

import json

from .metrics import DigitalIpEvalReport


def canonical_json(report: DigitalIpEvalReport) -> str:
    return (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def render_markdown(report: DigitalIpEvalReport) -> str:
    aggregate = report.aggregate
    lines = [
        "# Digital IP fixture contract conformance",
        "",
        f"> {report.disclaimer}",
        "",
        f"- Dataset: `{report.dataset_version}`",
        f"- Cases passed: {aggregate.passed_count}/{aggregate.case_count}",
        f"- Expected document-type coverage: {_percentage(aggregate.expected_type_coverage)}",
        f"- Expected tag/character coverage: {_percentage(aggregate.expected_tag_coverage)}",
        f"- Prohibited-rule hit rate: {_percentage(aggregate.prohibited_rule_hit_rate)}",
        f"- Brand-as-fact violations: {aggregate.brand_as_fact_count}",
        "",
        "| Case | Category | Pass | Type coverage | Tag coverage | Prohibited | Fact violations |",
        "| --- | --- | --- | ---: | ---: | --- | ---: |",
    ]
    for case in report.cases:
        prohibited_result = (
            ("hit" if case.prohibited_rule_hit else "miss")
            if case.prohibited_rule_required
            else "n/a"
        )
        lines.append(
            f"| `{case.case_id}` | `{case.category.value}` | "
            f"{'yes' if case.passed else 'no'} | "
            f"{case.matched_type_count}/{case.expected_type_count} | "
            f"{case.matched_tag_count}/{case.expected_tag_count} | "
            f"{prohibited_result} | "
            f"{case.brand_as_fact_count} |"
        )
    lines.extend(
        [
            "",
            "This checked artifact is a provider-free fixture baseline. It makes no claim about "
            "real embedding recall, live model consistency, or production effectiveness.",
            "",
        ]
    )
    return "\n".join(lines)


def _percentage(value: float) -> str:
    return f"{value * 100:.2f}%"
