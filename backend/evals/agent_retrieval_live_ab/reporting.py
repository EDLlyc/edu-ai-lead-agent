"""Render an aggregate-only report without queries, UUIDs, prompts, or provider bodies."""

from __future__ import annotations

from .models import CANARY_ATTEMPTS, MetricEstimate, PairedReport, canonical_json_bytes
from .privacy import require_aggregate_safe


def safe_report_json(report: PairedReport) -> str:
    rendered = canonical_json_bytes(report).decode("utf-8") + "\n"
    require_aggregate_safe(rendered)
    return rendered


def render_markdown(report: PairedReport) -> str:
    raw, enhanced = report.arms
    lines = [
        "# Agent retrieval paired live A/B",
        "",
        "> Local exploratory evidence over Codex-Seed labels; not human Gold and not "
        "production uplift.",
        "",
        "## Integrity",
        "",
        f"- Completed authorized compatibility attempts: "
        f"{report.completed_attempts}/{CANARY_ATTEMPTS}",
        f"- Full paired-matrix coverage: {report.completed_attempts}/{report.expected_attempts}",
        f"- Non-terminal started journals: {report.started_attempt_count}",
        f"- Complete paired matrix: `{str(report.complete).lower()}`",
        f"- Mandatory first-pair canary passed: `{str(report.canary_passed).lower()}`",
        f"- Circuit breaker: `{report.circuit_breaker_reason or 'none'}`",
        f"- Retrieval-sensitive cases: {report.retrieval_case_count}",
        f"- Negative-control cases: {report.negative_control_case_count}",
        f"- Provider failures: {report.provider_failure_count}",
        f"- Bounded/cancelled runs: {report.bounded_run_failure_count}",
        f"- Executor failures: {report.executor_failure_count}",
        "",
        "## Agent outcomes",
        "",
        "| Arm | Task success | All-three pass | Tool P/R | Citation P/R | "
        "Unsupported claims | P95 latency |",
        "|---|---:|---:|---:|---:|---:|---:|",
        _arm_row(raw),
        _arm_row(enhanced),
        "",
        "## Retrieval-sensitive paired estimates",
        "",
        "| Metric | Raw | Enhanced | Delta | 95% paired CI | Paired cases | Uplift supported |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        _estimate_row(name, estimate) for name, estimate in report.retrieval_estimates.items()
    )
    lines.extend(
        [
            "",
            "## Negative-control non-regression",
            "",
            "| Metric | Raw | Enhanced | Delta | 95% paired CI | Paired cases |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    lines.extend(
        _estimate_row(name, estimate, include_support=False)
        for name, estimate in report.negative_control_estimates.items()
    )
    lines.extend(
        [
            "",
            "## Provider observations",
            "",
            f"- Agent decisions: {report.capability_counts.agent}",
            f"- Query planner requests: {report.capability_counts.planner}",
            f"- Reranker requests: {report.capability_counts.reranker}",
            f"- Alibaba embedding requests: {report.capability_counts.embedding}",
            "- Capability counts cover all started work: "
            f"`{str(report.capability_counts_complete).lower()}`",
            "- Prompt/completion/reasoning tokens (raw): "
            f"{raw.prompt_tokens}/{raw.completion_tokens}/{raw.reasoning_tokens}",
            "- Prompt/completion/reasoning tokens (enhanced): "
            f"{enhanced.prompt_tokens}/{enhanced.completion_tokens}/"
            f"{enhanced.reasoning_tokens}",
            "- Monetary cost: unknown unless a separately frozen provider price sheet is supplied.",
            "",
            "## Terminal failures by arm",
            "",
        ]
    )
    for arm, failures in report.terminal_failure_counts_by_arm.items():
        if failures:
            lines.extend(f"- `{arm}` / `{code}`: {count}" for code, count in failures.items())
        else:
            lines.append(f"- `{arm}`: none")
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            report.conclusion,
            "",
            "## Validity limits",
            "",
        ]
    )
    lines.extend(f"- {note}" for note in report.validity_notes)
    if report.fallback_or_failure_codes:
        lines.extend(["", "## Failure taxonomy", ""])
        lines.extend(
            f"- `{code}`: {count}" for code, count in report.fallback_or_failure_codes.items()
        )
    if report.bad_case_ids:
        lines.extend(
            [
                "",
                "## Bad-case aliases",
                "",
                ", ".join(report.bad_case_ids),
            ]
        )
    rendered = "\n".join(lines) + "\n"
    require_aggregate_safe(rendered)
    return rendered


def _arm_row(summary: object) -> str:
    from .models import ArmSummary

    item = summary
    if not isinstance(item, ArmSummary):
        raise TypeError("arm report row requires ArmSummary")
    return (
        f"| {item.arm.value} | {_pct(item.task_success_rate)} | "
        f"{_pct(item.all_three_pass_rate)} | {_pct(item.tool_precision)} / "
        f"{_pct(item.tool_recall)} | "
        f"{_pct(item.citation_precision)} / {_pct(item.citation_coverage)} | "
        f"{_pct(item.unsupported_claim_rate)} | {item.p95_latency_ms:.0f} ms |"
    )


def _estimate_row(
    name: str,
    estimate: MetricEstimate,
    *,
    include_support: bool = True,
) -> str:
    if not estimate.paired_matrix_complete:
        row = (
            f"| {name} | N/A | N/A | N/A | N/A | "
            f"{estimate.paired_case_count}/{estimate.expected_case_count}"
        )
    else:
        assert estimate.raw is not None
        assert estimate.enhanced is not None
        assert estimate.delta is not None
        assert estimate.ci_low is not None
        assert estimate.ci_high is not None
        row = (
            f"| {name} | {_pct(estimate.raw)} | {_pct(estimate.enhanced)} | "
            f"{estimate.delta:+.4f} | [{estimate.ci_low:+.4f}, {estimate.ci_high:+.4f}] | "
            f"{estimate.paired_case_count}/{estimate.expected_case_count}"
        )
    if include_support:
        return f"{row} | `{str(estimate.supports_uplift_claim).lower()}` |"
    return f"{row} |"


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"
