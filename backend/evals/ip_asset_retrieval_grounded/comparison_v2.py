from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from app.domain.ip_assets import IP_ASSET_SEARCH_V2_VERSION, IP_ASSET_SEARCH_V3_VERSION

from .dataset import GroundedDatasetBundleV2
from .metrics import paired_bootstrap_interval
from .models import EXPECTED_V2_QUERY_COUNT, GroundedRetrievalRunV2
from .selective import (
    RANKING_METRICS,
    SelectivePolicy,
    ranking_metrics,
    run_identity_v2,
    score_policy,
    validate_run_identity_v2,
)

ComparisonSplit = Literal["overall", "dev", "holdout"]
_COMPARISON_SPLITS: tuple[ComparisonSplit, ...] = ("overall", "dev", "holdout")


def compare_runs_v2(
    bundle: GroundedDatasetBundleV2,
    baseline: GroundedRetrievalRunV2,
    candidate: GroundedRetrievalRunV2,
    *,
    bootstrap_samples: int = 10_000,
    bootstrap_seed: int = 20_260_902,
) -> dict[str, Any]:
    """Compare real Seed V2 runs without treating no-answer rows as ranking wins."""
    _validate_pair(bundle, baseline, candidate)
    baseline_by_ref = {item.query_ref: item for item in baseline.observations}
    candidate_by_ref = {item.query_ref: item for item in candidate.observations}
    query_by_ref = {query.query_ref: query for query in bundle.queries}
    grades_by_ref = {
        matrix.query_ref: {grade.catalog_ref: grade.grade for grade in matrix.grades}
        for matrix in bundle.seed
    }
    paired_bootstrap: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, dict[str, int]]] = {}
    for split in _COMPARISON_SPLITS:
        pairs = _metric_pairs(
            query_by_ref=query_by_ref,
            grades_by_ref=grades_by_ref,
            baseline_by_ref=baseline_by_ref,
            candidate_by_ref=candidate_by_ref,
            split=split,
        )
        paired_bootstrap[split] = {
            metric: paired_bootstrap_interval(
                values,
                samples=bootstrap_samples,
                seed=bootstrap_seed,
            )
            for metric, values in pairs.items()
        }
        outcomes[split] = {metric: _outcomes(values) for metric, values in pairs.items()}
    return {
        "schema_version": "ip-asset-grounded-comparison-v2",
        "maturity": "seed",
        "label_source": "codex_seed_v2",
        "truthfulness": {
            "human_gold": False,
            "human_agreement_available": False,
            "online_user_effectiveness": False,
            "production_threshold_activated": False,
            "live_retrieval_measured": True,
            "real_embedding_provider_used": True,
            "same_embedding_bytes_proven": False,
        },
        "baseline_search_version": baseline.search_version,
        "candidate_search_version": candidate.search_version,
        "baseline_run": run_identity_v2(baseline),
        "candidate_run": run_identity_v2(candidate),
        "baseline": _run_scores(bundle, baseline),
        "candidate": _run_scores(bundle, candidate),
        "diagnostics": {
            "baseline": _run_diagnostics(bundle, baseline),
            "candidate": _run_diagnostics(bundle, candidate),
        },
        "paired_bootstrap": {
            "direction": "candidate_minus_baseline",
            "samples": bootstrap_samples,
            "seed": bootstrap_seed,
            **paired_bootstrap,
        },
        "paired_outcomes": outcomes,
        "validity": {
            "evidence_tier": "model_corpus_quality",
            "labels": "codex_seed_v2_not_human_gold",
            "provider_execution": "two_separate_real_embedding_runs",
            "embedding_bytes": "not_captured_or_proven_identical_between_runs",
            "online_effectiveness": "not_measured",
            "deployment": "comparison_only_no_production_behavior_change",
        },
    }


def _validate_pair(
    bundle: GroundedDatasetBundleV2,
    baseline: GroundedRetrievalRunV2,
    candidate: GroundedRetrievalRunV2,
) -> None:
    validate_run_identity_v2(bundle, baseline)
    validate_run_identity_v2(bundle, candidate)
    if baseline.search_version != IP_ASSET_SEARCH_V2_VERSION:
        raise ValueError("grounded Seed V2 baseline must use ip-asset-hybrid-v2")
    if candidate.search_version != IP_ASSET_SEARCH_V3_VERSION:
        raise ValueError("grounded Seed V2 candidate must use ip-asset-hybrid-v3-rrf")
    if baseline.run_ref == candidate.run_ref:
        raise ValueError("grounded Seed V2 paired runs need distinct run refs")
    if baseline.embedding_execution_mode != "alibaba" or (
        candidate.embedding_execution_mode != "alibaba"
    ):
        raise ValueError("grounded Seed V2 paired comparison requires real Alibaba runs")
    if baseline.provider_request_count != EXPECTED_V2_QUERY_COUNT or (
        candidate.provider_request_count != EXPECTED_V2_QUERY_COUNT
    ):
        raise ValueError("grounded Seed V2 paired runs need complete provider request counts")
    if _embedding_identity(baseline) != _embedding_identity(candidate):
        raise ValueError("grounded Seed V2 paired runs need one embedding identity")


def _run_scores(
    bundle: GroundedDatasetBundleV2,
    run: GroundedRetrievalRunV2,
) -> dict[str, dict[str, Any]]:
    policy = SelectivePolicy()
    return {
        "overall": score_policy(bundle, run, policy, split=None),
        "dev": score_policy(bundle, run, policy, split="dev"),
        "holdout": score_policy(bundle, run, policy, split="holdout"),
    }


def _run_diagnostics(
    bundle: GroundedDatasetBundleV2,
    run: GroundedRetrievalRunV2,
) -> dict[str, dict[str, Any]]:
    query_by_ref = {query.query_ref: query for query in bundle.queries}
    result: dict[str, dict[str, Any]] = {}
    for split in _COMPARISON_SPLITS:
        observations = tuple(
            item
            for item in run.observations
            if split == "overall" or query_by_ref[item.query_ref].split == split
        )
        successful = tuple(item for item in observations if item.failure_code is None)
        result[split] = {
            "query_count": len(observations),
            "successful_query_count": len(successful),
            "execution_coverage": _ratio(len(successful), len(observations)),
            "modes": dict(sorted(Counter(item.mode for item in successful).items())),
            "degraded_reasons": dict(
                sorted(
                    Counter(
                        item.degraded_reason
                        for item in successful
                        if item.degraded_reason is not None
                    ).items()
                )
            ),
            "failure_codes": dict(
                sorted(
                    Counter(
                        item.failure_code for item in observations if item.failure_code is not None
                    ).items()
                )
            ),
        }
    return result


def _metric_pairs(
    *,
    query_by_ref: dict[str, Any],
    grades_by_ref: dict[str, dict[str, int]],
    baseline_by_ref: dict[str, Any],
    candidate_by_ref: dict[str, Any],
    split: ComparisonSplit,
) -> dict[str, tuple[tuple[float, float], ...]]:
    pairs: dict[str, list[tuple[float, float]]] = {metric: [] for metric in RANKING_METRICS}
    for query_ref in sorted(query_by_ref):
        query = query_by_ref[query_ref]
        if query.expected_answer_kind == "no_answer" or (
            split != "overall" and query.split != split
        ):
            continue
        baseline = baseline_by_ref[query_ref]
        candidate = candidate_by_ref[query_ref]
        if baseline.failure_code is not None or candidate.failure_code is not None:
            continue
        baseline_metrics = ranking_metrics(
            baseline.selected_catalog_refs,
            grades_by_ref[query_ref],
        )
        candidate_metrics = ranking_metrics(
            candidate.selected_catalog_refs,
            grades_by_ref[query_ref],
        )
        for metric in RANKING_METRICS:
            pairs[metric].append((baseline_metrics[metric], candidate_metrics[metric]))
    return {metric: tuple(values) for metric, values in pairs.items()}


def _outcomes(values: tuple[tuple[float, float], ...]) -> dict[str, int]:
    wins = sum(candidate > baseline for baseline, candidate in values)
    losses = sum(candidate < baseline for baseline, candidate in values)
    return {"wins": wins, "ties": len(values) - wins - losses, "losses": losses}


def _embedding_identity(run: GroundedRetrievalRunV2) -> tuple[object, ...]:
    return (
        run.embedding_execution_mode,
        run.embedding_provider,
        run.embedding_model,
        run.embedding_dimensions,
        run.embedding_input_policy_version,
        run.asset_set_fingerprint,
        run.query_dataset_sha256,
        run.seed_dataset_sha256,
        run.robustness_dataset_sha256,
        run.review_ledger_sha256,
    )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0
