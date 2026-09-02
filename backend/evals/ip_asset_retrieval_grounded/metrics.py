from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .dataset import GroundedDatasetBundle
from .models import GroundedQuery, GroundedQueryObservation, GroundedRetrievalRun

MetricName = Literal["recall_at_3", "recall_at_5", "mrr_at_5", "ndcg_at_5"]
_METRIC_NAMES: tuple[MetricName, ...] = (
    "recall_at_3",
    "recall_at_5",
    "mrr_at_5",
    "ndcg_at_5",
)


@dataclass(frozen=True, slots=True)
class GroundedQueryScore:
    query_ref: str
    category: str
    split: str
    expected_answer_kind: str
    failed: bool
    failure_code: str | None
    mode: str | None
    degraded_reason: str | None
    returned_count: int
    zero_result: bool | None
    relevant_count: int
    recall_at_3: float | None
    recall_at_5: float | None
    mrr_at_5: float | None
    ndcg_at_5: float | None
    correct_abstention: bool | None
    false_positive: bool | None


def score_run(
    bundle: GroundedDatasetBundle, run: GroundedRetrievalRun
) -> tuple[GroundedQueryScore, ...]:
    _validate_run_identity(bundle, run)
    grades_by_query = {
        matrix.query_ref: {grade.catalog_ref: grade.grade for grade in matrix.grades}
        for matrix in bundle.seed
    }
    query_by_ref = {query.query_ref: query for query in bundle.queries}
    return tuple(
        _score_observation(
            query=query_by_ref[observation.query_ref],
            grades=grades_by_query[observation.query_ref],
            observation=observation,
        )
        for observation in run.observations
    )


def aggregate_scores(scores: tuple[GroundedQueryScore, ...]) -> dict[str, Any]:
    return {
        "overall": _aggregate_bucket(scores),
        "categories": {
            key: _aggregate_bucket(tuple(items))
            for key, items in _group(scores, "category").items()
        },
        "splits": {
            key: _aggregate_bucket(tuple(items)) for key, items in _group(scores, "split").items()
        },
        "modes": {
            key: _aggregate_bucket(tuple(items))
            for key, items in _group(
                tuple(score for score in scores if score.mode is not None), "mode"
            ).items()
        },
    }


def compare_runs(
    bundle: GroundedDatasetBundle,
    baseline: GroundedRetrievalRun,
    candidate: GroundedRetrievalRun,
    *,
    bootstrap_samples: int = 10_000,
    bootstrap_seed: int = 20_260_902,
) -> dict[str, Any]:
    if baseline.search_version == candidate.search_version:
        raise ValueError("paired grounded comparison needs two different search versions")
    if _embedding_identity(baseline) != _embedding_identity(candidate):
        raise ValueError("paired grounded comparison needs one embedding identity")
    left = score_run(bundle, baseline)
    right = score_run(bundle, candidate)
    left_by_ref = {score.query_ref: score for score in left}
    right_by_ref = {score.query_ref: score for score in right}
    if left_by_ref.keys() != right_by_ref.keys():
        raise ValueError("paired grounded runs do not cover the same query set")
    intervals: dict[str, dict[str, float | int]] = {}
    for metric in _METRIC_NAMES:
        pairs = tuple(
            (getattr(left_by_ref[ref], metric), getattr(right_by_ref[ref], metric))
            for ref in sorted(left_by_ref)
        )
        usable = tuple(
            (float(left_value), float(right_value))
            for left_value, right_value in pairs
            if left_value is not None and right_value is not None
        )
        intervals[metric] = paired_bootstrap_interval(
            usable,
            samples=bootstrap_samples,
            seed=bootstrap_seed,
        )
    return {
        "schema_version": "ip-asset-grounded-comparison-v1",
        "maturity": "seed",
        "baseline_search_version": baseline.search_version,
        "candidate_search_version": candidate.search_version,
        "baseline_run": run_identity(baseline),
        "candidate_run": run_identity(candidate),
        "baseline": aggregate_scores(left),
        "candidate": aggregate_scores(right),
        "paired_bootstrap": {
            "direction": "candidate_minus_baseline",
            "samples": bootstrap_samples,
            "seed": bootstrap_seed,
            "metrics": intervals,
        },
    }


def paired_bootstrap_interval(
    pairs: tuple[tuple[float, float], ...],
    *,
    samples: int,
    seed: int,
) -> dict[str, float | int]:
    if not pairs:
        raise ValueError("paired bootstrap needs at least one comparable query")
    if samples < 1_000:
        raise ValueError("paired bootstrap needs at least 1,000 samples")
    observed = sum(right - left for left, right in pairs) / len(pairs)
    rng = random.Random(seed)
    deltas = sorted(
        sum(
            pairs[index][1] - pairs[index][0]
            for index in (rng.randrange(len(pairs)) for _ in pairs)
        )
        / len(pairs)
        for _ in range(samples)
    )
    return {
        "query_count": len(pairs),
        "delta": round(observed, 6),
        "ci95_low": round(_percentile(deltas, 0.025), 6),
        "ci95_high": round(_percentile(deltas, 0.975), 6),
    }


def _score_observation(
    *,
    query: GroundedQuery,
    grades: dict[str, int],
    observation: GroundedQueryObservation,
) -> GroundedQueryScore:
    relevant = {ref for ref, grade in grades.items() if grade >= 2}
    if observation.failure_code is not None:
        return GroundedQueryScore(
            query_ref=query.query_ref,
            category=query.category.value,
            split=query.split,
            expected_answer_kind=query.expected_answer_kind,
            failed=True,
            failure_code=observation.failure_code,
            mode=None,
            degraded_reason=None,
            returned_count=0,
            zero_result=None,
            relevant_count=len(relevant),
            recall_at_3=None,
            recall_at_5=None,
            mrr_at_5=None,
            ndcg_at_5=None,
            correct_abstention=None,
            false_positive=None,
        )
    selected = observation.selected_catalog_refs
    if query.expected_answer_kind == "no_answer":
        returned = bool(selected)
        return GroundedQueryScore(
            query_ref=query.query_ref,
            category=query.category.value,
            split=query.split,
            expected_answer_kind=query.expected_answer_kind,
            failed=False,
            failure_code=None,
            mode=observation.mode,
            degraded_reason=observation.degraded_reason,
            returned_count=len(selected),
            zero_result=not returned,
            relevant_count=0,
            recall_at_3=None,
            recall_at_5=None,
            mrr_at_5=None,
            ndcg_at_5=None,
            correct_abstention=not returned,
            false_positive=returned,
        )
    selected_at_3 = selected[:3]
    selected_at_5 = selected[:5]
    first_relevant = next(
        (rank for rank, ref in enumerate(selected_at_5, start=1) if ref in relevant),
        None,
    )
    return GroundedQueryScore(
        query_ref=query.query_ref,
        category=query.category.value,
        split=query.split,
        expected_answer_kind=query.expected_answer_kind,
        failed=False,
        failure_code=None,
        mode=observation.mode,
        degraded_reason=observation.degraded_reason,
        returned_count=len(selected),
        zero_result=not selected,
        relevant_count=len(relevant),
        recall_at_3=len(relevant.intersection(selected_at_3)) / len(relevant),
        recall_at_5=len(relevant.intersection(selected_at_5)) / len(relevant),
        mrr_at_5=1.0 / first_relevant if first_relevant is not None else 0.0,
        ndcg_at_5=_ndcg(selected_at_5, grades),
        correct_abstention=None,
        false_positive=None,
    )


def _ndcg(selected: tuple[str, ...], grades: dict[str, int]) -> float:
    actual = _dcg([grades[ref] for ref in selected])
    ideal = _dcg(sorted(grades.values(), reverse=True)[:5])
    if ideal <= 0:
        raise ValueError("answerable grounded query has no graded relevance gain")
    return actual / ideal


def _dcg(grades: list[int]) -> float:
    return float(sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, 1)))


def _aggregate_bucket(scores: tuple[GroundedQueryScore, ...]) -> dict[str, Any]:
    successful = tuple(score for score in scores if not score.failed)
    answerable = tuple(
        score for score in successful if score.expected_answer_kind == "has_relevant"
    )
    no_answer = tuple(score for score in successful if score.expected_answer_kind == "no_answer")
    failures = Counter(score.failure_code for score in scores if score.failure_code is not None)
    degraded = Counter(
        score.degraded_reason for score in scores if score.degraded_reason is not None
    )
    result: dict[str, Any] = {
        "query_count": len(scores),
        "successful_query_count": len(successful),
        "coverage": round(len(successful) / len(scores), 6) if scores else 0.0,
        "failure_codes": dict(sorted(failures.items())),
        "degraded_reasons": dict(sorted(degraded.items())),
        "answerable_query_count": len(answerable),
        "no_answer_query_count": len(no_answer),
        "zero_result_rate": _mean_bool(score.zero_result for score in successful),
        "correct_abstention_rate": _mean_bool(score.correct_abstention for score in no_answer),
        "false_positive_rate": _mean_bool(score.false_positive for score in no_answer),
    }
    for metric in _METRIC_NAMES:
        values = [getattr(score, metric) for score in answerable]
        clean = [float(value) for value in values if value is not None]
        result[f"macro_{metric}"] = round(sum(clean) / len(clean), 6) if clean else None
    return result


def _mean_bool(values: Iterable[bool | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return round(sum(clean) / len(clean), 6) if clean else None


def _group(
    scores: tuple[GroundedQueryScore, ...], field: Literal["category", "split", "mode"]
) -> dict[str, list[GroundedQueryScore]]:
    grouped: dict[str, list[GroundedQueryScore]] = defaultdict(list)
    for score in scores:
        value = getattr(score, field)
        if value is not None:
            grouped[str(value)].append(score)
    return dict(sorted(grouped.items()))


def _validate_run_identity(bundle: GroundedDatasetBundle, run: GroundedRetrievalRun) -> None:
    if run.asset_set_fingerprint != bundle.assets.asset_set_fingerprint:
        raise ValueError("grounded run asset fingerprint does not match the seed")
    if run.query_dataset_sha256 != bundle.queries_sha256:
        raise ValueError("grounded run query dataset does not match the seed")
    if run.seed_dataset_sha256 != bundle.seed_sha256:
        raise ValueError("grounded run seed dataset does not match")
    query_refs = [query.query_ref for query in bundle.queries]
    if [observation.query_ref for observation in run.observations] != query_refs:
        raise ValueError("grounded run query identity/order does not match the seed")
    known_assets = {asset.catalog_ref for asset in bundle.assets.assets}
    for observation in run.observations:
        if not set(observation.selected_catalog_refs).issubset(known_assets):
            raise ValueError("grounded run contains an unknown selected asset")


def _percentile(values: list[float], proportion: float) -> float:
    if not values:
        raise ValueError("percentile needs values")
    position = (len(values) - 1) * proportion
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction


def score_as_dict(score: GroundedQueryScore) -> dict[str, Any]:
    return asdict(score)


def run_identity(run: GroundedRetrievalRun) -> dict[str, Any]:
    return {
        "run_ref": run.run_ref,
        "created_at": run.created_at,
        "search_version": run.search_version,
        "embedding_execution_mode": run.embedding_execution_mode,
        "embedding_provider": run.embedding_provider,
        "embedding_model": run.embedding_model,
        "embedding_dimensions": run.embedding_dimensions,
        "embedding_input_policy_version": run.embedding_input_policy_version,
        "asset_set_fingerprint": run.asset_set_fingerprint,
        "query_dataset_sha256": run.query_dataset_sha256,
        "seed_dataset_sha256": run.seed_dataset_sha256,
    }


def _embedding_identity(run: GroundedRetrievalRun) -> tuple[object, ...]:
    return (
        run.embedding_execution_mode,
        run.embedding_provider,
        run.embedding_model,
        run.embedding_dimensions,
        run.embedding_input_policy_version,
    )
