"""Case-clustered metrics and paired bootstrap inference for the live A/B."""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable

from .harness import build_schedule, canary_attempt_passed
from .models import (
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    CANARY_ATTEMPTS,
    REPORT_SCHEMA_VERSION,
    ArmSummary,
    AttemptObservation,
    CapabilityCounts,
    CapabilityLimits,
    ExperimentArm,
    LiveAbCase,
    MetricEstimate,
    PairedReport,
)

_ScoreGetter = Callable[[AttemptObservation], float]


def build_paired_report(
    *,
    run_ref: str,
    manifest_sha256: str,
    cases: tuple[LiveAbCase, ...],
    attempts: tuple[AttemptObservation, ...],
    capability_counts: CapabilityCounts,
    authorization_sha256: str | None = None,
    started_attempt_count: int = 0,
    circuit_breaker_reason: str | None = None,
) -> PairedReport:
    _require_attempt_identities(
        cases,
        attempts,
        manifest_sha256=manifest_sha256,
        authorization_sha256=authorization_sha256,
    )
    _require_compatibility_boundary(
        cases,
        attempts,
        started_attempt_count=started_attempt_count,
    )
    _require_capability_count_consistency(
        attempts,
        capability_counts=capability_counts,
        started_attempt_count=started_attempt_count,
    )
    expected_identities = {
        (case.case_id, repetition, arm)
        for case in cases
        for repetition in range(1, 4)
        for arm in ExperimentArm
    }
    observed_identities = {(item.case_id, item.repetition, item.arm) for item in attempts}
    if observed_identities == expected_identities and started_attempt_count == 0:
        raise ValueError("v3 compatibility reports cannot contain a complete 72-cell matrix")
    complete = False
    canary_attempts = tuple(
        sorted(
            (item for item in attempts if item.canary),
            key=lambda item: item.schedule_ordinal,
        )
    )
    canary_passed = len(canary_attempts) == 2 and all(
        canary_attempt_passed(item) for item in canary_attempts
    )
    retrieval_ids = tuple(item.case_id for item in cases if item.retrieval_sensitive)
    negative_ids = tuple(item.case_id for item in cases if not item.retrieval_sensitive)
    retrieval_metrics: dict[str, _ScoreGetter] = {
        "hit_at_3": lambda item: item.score.hit_at_3 or 0.0,
        "recall_at_3": lambda item: item.score.recall_at_3 or 0.0,
        "mrr_at_3": lambda item: item.score.mrr_at_3 or 0.0,
        "ndcg_at_3": lambda item: item.score.ndcg_at_3 or 0.0,
        "target_citation_coverage": lambda item: item.score.target_citation_coverage or 0.0,
    }
    all_metrics: dict[str, _ScoreGetter] = {
        "task_success": lambda item: float(item.score.task_success),
        "terminal_accuracy": lambda item: float(item.score.terminal_match),
        "tool_precision": lambda item: item.score.tool_precision,
        "tool_recall": lambda item: item.score.tool_recall,
        "argument_valid_rate": lambda item: item.score.argument_valid_rate,
        "citation_precision": lambda item: item.score.citation_precision,
        "citation_coverage": lambda item: item.score.citation_coverage,
        "refusal_accuracy": lambda item: float(item.score.refusal_correct),
    }
    retrieval_estimates = {
        name: _paired_estimate(
            attempts,
            case_ids=retrieval_ids,
            getter=getter,
            complete=complete,
            seed=BOOTSTRAP_SEED + index,
        )
        for index, (name, getter) in enumerate(retrieval_metrics.items())
    }
    all_case_estimates = {
        name: _paired_estimate(
            attempts,
            case_ids=tuple(item.case_id for item in cases),
            getter=getter,
            complete=complete,
            seed=BOOTSTRAP_SEED + 100 + index,
        )
        for index, (name, getter) in enumerate(all_metrics.items())
    }
    negative_control_estimates = {
        name: _paired_estimate(
            attempts,
            case_ids=negative_ids,
            getter=getter,
            complete=complete,
            seed=BOOTSTRAP_SEED + 200 + index,
        )
        for index, (name, getter) in enumerate(
            {
                "task_success": all_metrics["task_success"],
                "terminal_accuracy": all_metrics["terminal_accuracy"],
                "tool_precision": all_metrics["tool_precision"],
                "tool_recall": all_metrics["tool_recall"],
                "refusal_accuracy": all_metrics["refusal_accuracy"],
            }.items()
        )
    }
    failures = Counter(code for attempt in attempts for code in attempt.score.failure_codes)
    failures.update(
        f"terminal:{attempt.error_code}" for attempt in attempts if attempt.error_code is not None
    )
    for attempt in attempts:
        for capability, count in attempt.capability_failure_counts.items():
            failures[f"capability:{capability}_failed"] += count
    provider_failure_count = sum(
        bool(attempt.error_code and attempt.error_code.startswith("agent_model_"))
        for attempt in attempts
    )
    bounded_run_failure_count = sum(
        attempt.terminal_status in {"budget_exhausted", "cancelled"} for attempt in attempts
    )
    executor_failure_count = sum(attempt.execution_status.value == "failed" for attempt in attempts)
    terminal_failure_counts_by_arm = {
        arm.value: dict(
            sorted(
                Counter(
                    attempt.error_code or attempt.terminal_status
                    for attempt in attempts
                    if attempt.arm is arm
                    and (
                        attempt.error_code is not None
                        or attempt.terminal_status not in {"completed", "refused"}
                    )
                ).items()
            )
        )
        for arm in ExperimentArm
    }
    bad_case_ids = tuple(
        sorted({attempt.case_id for attempt in attempts if not attempt.score.task_success})
    )
    conclusion = _conclusion(
        complete=False,
        canary_passed=canary_passed,
        circuit_breaker_reason=circuit_breaker_reason,
        provider_failure_count=provider_failure_count,
        bounded_run_failure_count=bounded_run_failure_count,
        executor_failure_count=executor_failure_count,
        retrieval_estimates=retrieval_estimates,
        negative_control_estimates=negative_control_estimates,
    )
    return PairedReport(
        schema_version=REPORT_SCHEMA_VERSION,
        run_ref=run_ref,
        manifest_sha256=manifest_sha256,
        completed_attempts=len(attempts),
        complete=False,
        canary_passed=canary_passed,
        circuit_breaker_reason=circuit_breaker_reason,
        arms=(
            _arm_summary(ExperimentArm.RAW, attempts),
            _arm_summary(ExperimentArm.ENHANCED, attempts),
        ),
        retrieval_estimates=retrieval_estimates,
        all_case_estimates=all_case_estimates,
        negative_control_estimates=negative_control_estimates,
        capability_counts=capability_counts,
        capability_counts_complete=started_attempt_count == 0,
        started_attempt_count=started_attempt_count,
        provider_failure_count=provider_failure_count,
        bounded_run_failure_count=bounded_run_failure_count,
        executor_failure_count=executor_failure_count,
        terminal_failure_counts_by_arm=terminal_failure_counts_by_arm,
        fallback_or_failure_codes=dict(sorted(failures.items())),
        bad_case_ids=bad_case_ids,
        conclusion=conclusion,
        validity_notes=(
            "This is a local, small-sample exploratory result over 12 Codex-Seed cases.",
            "The labels are not human Gold and do not establish production or "
            "user-conversion uplift.",
            "The statistical unit is the case; three repeated attempts are averaged "
            "before bootstrap.",
            "Provider latency and behavior may vary over time; raw and warm-cache "
            "latency are not interchangeable.",
            "Unknown provider usage or price is retained as unknown rather than "
            "estimated from response text.",
        ),
    )


def _arm_summary(
    arm: ExperimentArm,
    attempts: tuple[AttemptObservation, ...],
) -> ArmSummary:
    values = tuple(item for item in attempts if item.arm is arm)
    grouped: dict[str, list[AttemptObservation]] = defaultdict(list)
    for item in values:
        grouped[item.case_id].append(item)
    latencies = tuple(float(item.duration_ms) for item in values)
    return ArmSummary(
        arm=arm,
        attempt_count=len(values),
        task_success_rate=_mean(float(item.score.task_success) for item in values),
        all_three_pass_rate=_mean(
            float(len(rows) == 3 and all(row.score.task_success for row in rows))
            for rows in grouped.values()
        ),
        terminal_accuracy=_mean(float(item.score.terminal_match) for item in values),
        tool_precision=_mean(item.score.tool_precision for item in values),
        tool_recall=_mean(item.score.tool_recall for item in values),
        citation_precision=_mean(item.score.citation_precision for item in values),
        citation_coverage=_mean(item.score.citation_coverage for item in values),
        unsupported_claim_rate=_mean(item.score.unsupported_claim_rate for item in values),
        refusal_accuracy=_mean(float(item.score.refusal_correct) for item in values),
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        prompt_tokens=sum(item.prompt_tokens for item in values),
        completion_tokens=sum(item.completion_tokens for item in values),
        reasoning_tokens=sum(item.reasoning_tokens for item in values),
    )


def _paired_estimate(
    attempts: tuple[AttemptObservation, ...],
    *,
    case_ids: tuple[str, ...],
    getter: _ScoreGetter,
    complete: bool,
    seed: int,
) -> MetricEstimate:
    by_cell: dict[tuple[str, ExperimentArm], list[float]] = defaultdict(list)
    for item in attempts:
        if item.case_id in case_ids:
            by_cell[(item.case_id, item.arm)].append(getter(item))
    paired_case_ids = tuple(
        case_id
        for case_id in case_ids
        if all(len(by_cell[(case_id, arm)]) == 3 for arm in ExperimentArm)
    )
    paired_matrix_complete = len(paired_case_ids) == len(case_ids)
    if not paired_matrix_complete:
        return MetricEstimate(
            raw=None,
            enhanced=None,
            delta=None,
            ci_low=None,
            ci_high=None,
            paired_case_count=len(paired_case_ids),
            expected_case_count=len(case_ids),
            paired_matrix_complete=False,
            supports_uplift_claim=False,
        )
    raw_by_case = {
        case_id: _mean(by_cell[(case_id, ExperimentArm.RAW)]) for case_id in paired_case_ids
    }
    enhanced_by_case = {
        case_id: _mean(by_cell[(case_id, ExperimentArm.ENHANCED)]) for case_id in paired_case_ids
    }
    raw = _mean(raw_by_case.values())
    enhanced = _mean(enhanced_by_case.values())
    delta = enhanced - raw
    rng = random.Random(seed)
    bootstrap: list[float] = []
    if paired_case_ids:
        for _ in range(BOOTSTRAP_SAMPLES):
            sample = tuple(rng.choice(paired_case_ids) for _ in paired_case_ids)
            bootstrap.append(_mean(enhanced_by_case[item] - raw_by_case[item] for item in sample))
    ci_low = _percentile(tuple(bootstrap), 0.025)
    ci_high = _percentile(tuple(bootstrap), 0.975)
    return MetricEstimate(
        raw=raw,
        enhanced=enhanced,
        delta=delta,
        ci_low=ci_low,
        ci_high=ci_high,
        paired_case_count=len(paired_case_ids),
        expected_case_count=len(case_ids),
        paired_matrix_complete=True,
        supports_uplift_claim=complete and ci_low > 0,
    )


def _require_attempt_identities(
    cases: tuple[LiveAbCase, ...],
    attempts: tuple[AttemptObservation, ...],
    *,
    manifest_sha256: str,
    authorization_sha256: str | None,
) -> None:
    if len(cases) != 12 or len({item.case_id for item in cases}) != 12:
        raise ValueError("paired report requires twelve unique cases")
    if sum(item.retrieval_sensitive for item in cases) != 8:
        raise ValueError("paired report requires eight retrieval-sensitive cases")
    case_ids = {item.case_id for item in cases}
    identities = {(item.case_id, item.repetition, item.arm) for item in attempts}
    if len(identities) != len(attempts):
        raise ValueError("attempt ledger contains duplicate A/B cells")
    if any(item.case_id not in case_ids for item in attempts):
        raise ValueError("attempt ledger contains an unknown case")
    if any(item.manifest_sha256 != manifest_sha256 for item in attempts):
        raise ValueError("attempt ledger is not bound to one manifest")
    if authorization_sha256 is not None and any(
        item.authorization_sha256 != authorization_sha256 for item in attempts
    ):
        raise ValueError("attempt ledger is not bound to the run authorization")
    schedule = {
        (item.case_id, item.repetition, item.arm): (item.ordinal, item.canary)
        for item in build_schedule(tuple(case.case_id for case in cases))
    }
    if any(
        schedule[(item.case_id, item.repetition, item.arm)] != (item.schedule_ordinal, item.canary)
        for item in attempts
    ):
        raise ValueError("attempt ledger differs from the manifest-bound schedule")


def _require_compatibility_boundary(
    cases: tuple[LiveAbCase, ...],
    attempts: tuple[AttemptObservation, ...],
    *,
    started_attempt_count: int,
) -> None:
    if started_attempt_count < 0 or len(attempts) + started_attempt_count > CANARY_ATTEMPTS:
        raise ValueError("v3 report exceeds the two-cell compatibility authorization")
    authorized = {
        (item.case_id, item.repetition, item.arm)
        for item in build_schedule(tuple(case.case_id for case in cases))[:CANARY_ATTEMPTS]
    }
    if any(
        (item.case_id, item.repetition, item.arm) not in authorized or not item.canary
        for item in attempts
    ):
        raise ValueError("v3 report contains a cell outside the compatibility canary")


def _require_capability_count_consistency(
    attempts: tuple[AttemptObservation, ...],
    *,
    capability_counts: CapabilityCounts,
    started_attempt_count: int,
) -> None:
    limits = CapabilityLimits()
    limit_by_name = {
        "agent": limits.agent_decisions,
        "planner": limits.planner_requests,
        "reranker": limits.rerank_requests,
        "embedding": limits.embedding_requests,
    }
    aggregate = capability_counts.model_dump()
    if any(aggregate[name] > limit for name, limit in limit_by_name.items()):
        raise ValueError("v3 report capability counts exceed the authorization")

    completed = {
        name: sum(getattr(item.capability_counts, name) for item in attempts)
        for name in limit_by_name
    }
    if started_attempt_count == 0 and aggregate != completed:
        raise ValueError("report capability counts differ from the terminal attempt ledger")
    if started_attempt_count and any(aggregate[name] < completed[name] for name in limit_by_name):
        raise ValueError("report capability counts omit terminal attempt usage")
    for attempt in attempts:
        used = attempt.capability_counts.model_dump()
        failures = attempt.capability_failure_counts
        if any(failures.get(name, 0) > used[name] for name in limit_by_name):
            raise ValueError("attempt capability failures exceed recorded requests")


def _conclusion(
    *,
    complete: bool,
    canary_passed: bool,
    circuit_breaker_reason: str | None,
    provider_failure_count: int,
    bounded_run_failure_count: int,
    executor_failure_count: int,
    retrieval_estimates: dict[str, MetricEstimate],
    negative_control_estimates: dict[str, MetricEstimate],
) -> str:
    if not canary_passed:
        return (
            "The mandatory first A/B canary pair did not pass all terminal, task, tool, "
            "retrieval, citation, and provider gates; the remaining cells were not executed "
            "and no uplift conclusion is permitted."
        )
    if circuit_breaker_reason == "compatibility_canary_complete":
        return (
            "The authorized two-cell compatibility canary passed and stopped at its hard boundary; "
            "the remaining matrix was intentionally not executed and no retrieval-uplift "
            "conclusion is permitted."
        )
    if not complete:
        reason = circuit_breaker_reason or "incomplete_matrix"
        return (
            f"The 72-cell paired matrix stopped at the {reason} circuit gate; "
            "no retrieval-uplift conclusion is permitted."
        )
    if provider_failure_count or bounded_run_failure_count or executor_failure_count:
        return "Provider or bounded-run failures occurred; observed deltas are diagnostic only."
    recall = retrieval_estimates["recall_at_3"]
    ndcg = retrieval_estimates["ndcg_at_3"]
    controls = negative_control_estimates["task_success"]
    if (
        recall.ci_low is not None
        and ndcg.ci_low is not None
        and controls.ci_low is not None
        and recall.ci_low > 0
        and ndcg.ci_low > 0
        and controls.ci_low >= -0.05
    ):
        return (
            "On this local Codex-Seed dataset, the enhanced reader improved both Recall@3 and "
            "nDCG@3 without an observed material negative-control regression. This remains "
            "exploratory evidence, not a production uplift claim."
        )
    return (
        "Observed A/B differences are reported, but the small-sample paired intervals or "
        "negative controls do not support a robust uplift statement."
    )


def _mean(values: Iterable[float]) -> float:
    materialized: tuple[float, ...] = tuple(values)
    return sum(materialized) / len(materialized) if materialized else 0.0


def _percentile(values: tuple[float, ...], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction
