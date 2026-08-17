"""Stable JSON/Markdown rendering for the checked Agent Workbench baseline."""

from __future__ import annotations

import json
from hashlib import sha256

from pydantic import BaseModel

from .metrics import CanonicalEvalReport, RuntimeDiagnostics


def canonical_json(model: BaseModel) -> str:
    """Serialize a report with stable key order, UTF-8 text, and one final newline."""

    return (
        json.dumps(
            model.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def report_sha256(report: CanonicalEvalReport) -> str:
    return sha256(canonical_json(report).encode("utf-8")).hexdigest()


def render_markdown(report: CanonicalEvalReport) -> str:
    """Render the deterministic report without volatile timing or token values."""

    aggregate = report.aggregate
    lines = [
        "# Agent Workbench deterministic baseline",
        "",
        f"> {report.disclaimer}",
        "",
        f"- Dataset: `{report.dataset_version}` ({aggregate.case_count} cases)",
        f"- Registry schema SHA-256: `{report.registry_schema_hash}`",
        "- Volatile wall-clock latency and token diagnostics are intentionally excluded here.",
        "",
        "## Aggregate contract metrics",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Task success | {_percentage(aggregate.task_success_rate)} |",
        f"| Terminal-state accuracy | {_percentage(aggregate.terminal_accuracy)} |",
        f"| Exact tool-set rate | {_percentage(aggregate.tool_set_exact_rate)} |",
        f"| Tool-selection precision | {_percentage(aggregate.tool_selection_precision)} |",
        f"| Tool-selection recall | {_percentage(aggregate.tool_selection_recall)} |",
        f"| Valid argument rate | {_percentage(aggregate.argument_valid_rate)} |",
        f"| Citation precision | {_percentage(aggregate.citation_precision)} |",
        f"| Citation coverage | {_percentage(aggregate.citation_coverage)} |",
        f"| Unsupported-claim rate | {_percentage(aggregate.unsupported_claim_rate)} |",
        f"| Refusal precision | {_percentage(aggregate.refusal_precision)} |",
        f"| Refusal recall | {_percentage(aggregate.refusal_recall)} |",
        f"| Refusal accuracy | {_percentage(aggregate.refusal_accuracy)} |",
        f"| Mean model steps | {aggregate.mean_model_steps:.2f} |",
        f"| P50 / P95 model steps | {aggregate.p50_model_steps:.2f} / "
        f"{aggregate.p95_model_steps:.2f} |",
        f"| Unknown tool calls | {aggregate.unknown_tool_count} |",
        "",
        "## Category results",
        "",
        "| Category | Passed | Success | Failed case IDs |",
        "| --- | ---: | ---: | --- |",
    ]
    for category in report.categories:
        failures = ", ".join(f"`{case_id}`" for case_id in category.failed_case_ids) or "—"
        lines.append(
            f"| `{category.category.value}` | {category.passed_count}/{category.case_count} | "
            f"{_percentage(category.task_success_rate)} | {failures} |"
        )
    lines.extend(
        [
            "",
            "## Case-level deterministic checks",
            "",
            "| Case | Category | Pass | Tools P/R | Citations P/C | "
            "Unsupported claims | Failures |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for case in report.cases:
        failures = ", ".join(f"`{code}`" for code in case.failure_codes) or "—"
        lines.append(
            f"| `{case.case_id}` | `{case.category.value}` | "
            f"{'yes' if case.passed else 'no'} | "
            f"{_percentage(case.tool_selection_precision)} / "
            f"{_percentage(case.tool_selection_recall)} | "
            f"{_percentage(case.citation_precision)} / "
            f"{_percentage(case.citation_coverage)} | "
            f"{_percentage(case.unsupported_claim_rate)} | {failures} |"
        )
    lines.extend(
        [
            "",
            "The baseline policy reads only the query, successful trace, and canonical registry. "
            "Eval oracle fields are held by the evaluator and are never supplied to the policy.",
            "",
        ]
    )
    return "\n".join(lines)


def runtime_json(diagnostics: RuntimeDiagnostics) -> str:
    return canonical_json(diagnostics)


def _percentage(value: float) -> str:
    return f"{value * 100:.2f}%"
