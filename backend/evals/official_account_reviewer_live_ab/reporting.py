"""Stable report, worksheet, and human-confirmed calibration projections."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from hashlib import sha256

from pydantic import BaseModel

from .metrics import LiveAbReport
from .models import (
    REPORT_CONFIRMATION_ACKNOWLEDGEMENT,
    CalibrationCandidate,
    WorksheetRow,
    evidence_sha256,
)
from .privacy import require_privacy_safe


def canonical_json(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def canonical_jsonl(values: tuple[object, ...]) -> str:
    return "".join(
        json.dumps(
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
        for item in values
    )


def report_sha256(report: LiveAbReport) -> str:
    return sha256(canonical_json(report).encode()).hexdigest()


def render_worksheet_csv(rows: tuple[WorksheetRow, ...]) -> str:
    """Render the human sheet without arm, system decision, provider, or model fields."""

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "blind_ref",
            "pair_ref",
            "candidate",
            "artifact_ref",
            "artifact_commitment_sha256",
            "annotator_ref",
            "editorial_pass",
            "critical_defect_present",
            "defect_codes",
        )
    )
    for row in rows:
        writer.writerow(
            (
                row.blind_ref,
                row.pair_ref,
                row.candidate,
                row.artifact_ref,
                row.artifact_commitment_sha256,
                "",
                "",
                "",
                "",
            )
        )
    return output.getvalue()


def render_markdown(report: LiveAbReport) -> str:
    lines = [
        "# Governed Reviewer paired live A/B evidence",
        "",
        f"> {report.disclaimer}",
        "",
        "## Evidence identity",
        "",
        f"- Manifest SHA-256: `{report.manifest_sha256}`",
        f"- Local authorization SHA-256: `{report.authorization_sha256}`",
        f"- Attempt ledger SHA-256: `{report.evidence_artifact_hashes.attempts_sha256}`",
        f"- Blinded worksheet SHA-256: `{report.evidence_artifact_hashes.worksheet_sha256}`",
        f"- Blind-map SHA-256: `{report.evidence_artifact_hashes.blind_map_sha256}`",
        f"- Human judgments/adjudications SHA-256: "
        f"`{report.evidence_artifact_hashes.judgments_sha256}` / "
        f"`{report.evidence_artifact_hashes.adjudications_sha256}`",
        f"- Dataset: `{report.dataset_version}` / `{report.dataset_sha256}`",
        f"- Provider/model: `{report.provider}` / `{report.model}`",
        f"- Scope: `{report.sample_count}` cases x `{report.repetitions}` repetitions",
        f"- Imported live model calls: `{report.live_model_calls}`",
        f"- Human gold: `{str(report.human_gold).lower()}`",
        f"- LLM judge used: `{str(report.llm_judge_used).lower()}`",
        f"- Conclusion eligible: `{str(report.conclusion_eligible).lower()}`",
        "",
        "## Quality, latency, and cost",
        "",
        "False-accept rates use human-gold negatives as the denominator; false-reject rates use "
        "human-gold positives. A missing gold class is reported as `unknown`, never as zero.",
        "",
        "| Arm | Pass@1 | Pass@2 | Critical recall | False accept | False reject | "
        "Manual review | P50/P95 ms | Calls | Tokens in/out | Estimated cost |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm in report.arms:
        tokens = (
            f"{arm.input_tokens}/{arm.output_tokens}"
            if arm.input_tokens is not None and arm.output_tokens is not None
            else f"unknown ({arm.unknown_usage_call_count} calls)"
        )
        cost = (
            f"${arm.estimated_cost_usd:.6f}"
            if arm.estimated_cost_usd is not None
            else f"unknown (known lower bound ${arm.known_cost_lower_bound_usd:.6f})"
        )
        lines.append(
            f"| `{arm.arm.value}` | {_pct(arm.editorial_pass_at_1)} | "
            f"{_pct(arm.editorial_pass_at_2)} | {_pct(arm.critical_defect_recall)} | "
            f"{_rate(arm.false_accept_rate, arm.false_accept_count, arm.gold_negative_count)} | "
            f"{_rate(arm.false_reject_rate, arm.false_reject_count, arm.gold_positive_count)} | "
            f"{_pct(arm.manual_review_rate)} | {_number(arm.p50_latency_ms)}/"
            f"{_number(arm.p95_latency_ms)} | {arm.provider_call_count} | {tokens} | {cost} |"
        )
    incremental_cost = (
        f"${report.incremental.estimated_cost_usd:.6f}"
        if report.incremental.estimated_cost_usd is not None
        else (
            "unknown (known lower-bound delta "
            f"${report.incremental.known_cost_lower_bound_usd:.6f})"
        )
    )
    lines.extend(
        [
            "",
            "## Incremental treatment cost",
            "",
            f"- Provider-call delta: `{report.incremental.provider_call_count}`",
            f"- P50/P95 latency delta: `{_number(report.incremental.p50_latency_ms)}` / "
            f"`{_number(report.incremental.p95_latency_ms)}` ms",
            f"- Estimated cost delta: `{incremental_cost}`",
            "",
            "## Paired estimates",
            "",
        ]
    )
    if report.paired_estimates:
        lines.extend(
            [
                "| Metric | Baseline | Treatment | Delta | 95% bootstrap CI | Repeat variance |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for item in report.paired_estimates:
            lines.append(
                f"| `{item.metric}` | {_pct(item.baseline_mean)} | "
                f"{_pct(item.treatment_mean)} | {_pct(item.treatment_minus_baseline)} | "
                f"[{_pct(item.ci_lower)}, {_pct(item.ci_upper)}] | "
                f"{_number(item.repetition_delta_variance)} |"
            )
    else:
        lines.append("No uplift estimate is emitted because the evidence gate did not pass.")
    lines.extend(["", "## Evidence gate", ""])
    blockers = ", ".join(f"`{item}`" for item in report.evidence_blockers) or "—"
    lines.extend(
        [
            f"- Integrity passed: `{str(report.integrity_passed).lower()}`",
            f"- Complete pairs: `{report.complete_pair_count}`",
            f"- Double-annotated calibration pairs: "
            f"`{report.human_agreement.double_annotated_pair_count}`",
            f"- Editorial/critical pairwise agreement: "
            f"`{_pct(report.human_agreement.editorial_pairwise_agreement)}` / "
            f"`{_pct(report.human_agreement.critical_pairwise_agreement)}`",
            f"- Blockers: {blockers}",
            "",
            "## Failure taxonomy and bad cases",
            "",
        ]
    )
    if report.failure_taxonomy:
        for code, count in report.failure_taxonomy.items():
            lines.append(f"- `{code}`: `{count}`")
    else:
        lines.append("- No execution failures in the imported attempt ledger.")
    if report.bad_cases:
        lines.extend(["", "| Pair | Arm | Reasons |", "| --- | --- | --- |"])
        for bad_case in report.bad_cases:
            reasons = ", ".join(f"`{code}`" for code in bad_case.reason_codes)
            lines.append(f"| `{bad_case.pair_ref}` | `{bad_case.arm.value}` | {reasons} |")
    else:
        lines.append("- No false accept, false reject, or treatment-regression cases.")
    lines.extend(
        [
            "",
            "Resume claims are absent unless all integrity, human calibration, minimum-sample, "
            "provider-status, and cost-usage gates pass. Production mode is never modified by "
            "this report.",
            "",
        ]
    )
    return "\n".join(lines)


def build_calibration_candidate(
    *,
    report: LiveAbReport,
    confirmed_at: datetime,
    confirmed_by_ref: str,
    confirmation: str,
    expected_report_sha256: str,
) -> CalibrationCandidate:
    """Create a non-activating candidate only from an eligible, explicitly confirmed report."""

    require_privacy_safe(report)
    if not report.conclusion_eligible or report.evidence_blockers or not report.resume_claims:
        raise ValueError("ineligible live A/B report cannot become a calibration candidate")
    if report.live_model_calls <= 0:
        raise ValueError("calibration candidate requires retained live-call evidence")
    if confirmation != REPORT_CONFIRMATION_ACKNOWLEDGEMENT:
        raise ValueError("calibration report requires the exact human confirmation")
    report_sha = report_sha256(report)
    if expected_report_sha256 != report_sha:
        raise ValueError("calibration confirmation does not bind the canonical report SHA-256")
    if report.dataset_version != "official-account-review-live-ab-dataset-v1":
        raise ValueError("calibration report dataset version is unsupported")
    candidate = CalibrationCandidate.model_construct(
        schema_version="official-account-review-live-ab-calibration-candidate-v1",
        report_sha256=report_sha,
        manifest_sha256=report.manifest_sha256,
        authorization_sha256=report.authorization_sha256,
        dataset_version="official-account-review-live-ab-dataset-v1",
        dataset_sha256=report.dataset_sha256,
        sample_count=report.sample_count,
        repetitions=report.repetitions,
        confirmed_at=confirmed_at,
        confirmed_by_ref=confirmed_by_ref,
        confirmation="I_CONFIRM_REVIEWER_LIVE_AB_REPORT_V1",
        production_mode_changed=False,
        candidate_sha256="0" * 64,
    )
    hash_payload = candidate.model_dump(mode="json", exclude={"candidate_sha256"})
    result = CalibrationCandidate.model_validate(
        {**hash_payload, "candidate_sha256": evidence_sha256(hash_payload)}
    )
    require_privacy_safe(result)
    return result


def _pct(value: float | None) -> str:
    return "unknown" if value is None else f"{value * 100:.2f}%"


def _number(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.4f}"


def _rate(value: float | None, numerator: int, denominator: int) -> str:
    if value is None:
        return f"unknown ({numerator}/{denominator})"
    return f"{_pct(value)} ({numerator}/{denominator})"
