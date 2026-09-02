from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .dataset import GroundedDatasetBundleV2
from .metrics import paired_bootstrap_interval
from .models import GroundedQueryObservationV2, GroundedRetrievalRunV2

RANKING_METRICS = ("recall_at_3", "recall_at_5", "mrr_at_5", "ndcg_at_5")


@dataclass(frozen=True, slots=True)
class SelectivePolicy:
    min_top_semantic_similarity: float | None = None
    min_semantic_margin: float | None = None
    min_metadata_match_score: float | None = None
    min_evidence_lane_count: int | None = None

    @property
    def policy_ref(self) -> str:
        if all(value is None for value in asdict(self).values()):
            return "selective-v1-baseline"
        parts = (
            _threshold_ref("s", self.min_top_semantic_similarity),
            _threshold_ref("m", self.min_semantic_margin),
            _threshold_ref("d", self.min_metadata_match_score),
            "lna" if self.min_evidence_lane_count is None else f"l{self.min_evidence_lane_count}",
        )
        return "selective-v1-" + "-".join(parts)

    def answers(self, observation: GroundedQueryObservationV2) -> bool:
        if observation.failure_code is not None or not observation.selected_catalog_refs:
            return False
        evidence = observation.decision_evidence
        if evidence is None:
            return False
        checks = (
            _meets(
                evidence.top_semantic_similarity,
                self.min_top_semantic_similarity,
            ),
            _meets(evidence.semantic_margin, self.min_semantic_margin),
            _meets(evidence.metadata_match_score, self.min_metadata_match_score),
            _meets_int(evidence.evidence_lane_count, self.min_evidence_lane_count),
        )
        return all(checks)


def candidate_policies() -> tuple[SelectivePolicy, ...]:
    similarities = (0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80)
    margins = (0.00, 0.01, 0.03, 0.05, 0.08, 0.12)
    metadata = (0.125, 0.25, 0.375, 0.50)
    candidates = [SelectivePolicy()]
    candidates.extend(SelectivePolicy(min_top_semantic_similarity=value) for value in similarities)
    candidates.extend(SelectivePolicy(min_semantic_margin=value) for value in margins)
    candidates.extend(SelectivePolicy(min_metadata_match_score=value) for value in metadata)
    candidates.extend(SelectivePolicy(min_evidence_lane_count=value) for value in (1, 2))
    candidates.extend(
        SelectivePolicy(
            min_top_semantic_similarity=similarity,
            min_semantic_margin=margin,
        )
        for similarity in similarities
        for margin in margins
    )
    candidates.extend(
        SelectivePolicy(
            min_top_semantic_similarity=similarity,
            min_evidence_lane_count=2,
        )
        for similarity in similarities
    )
    candidates.extend(
        SelectivePolicy(
            min_top_semantic_similarity=similarity,
            min_metadata_match_score=metadata_score,
        )
        for similarity in similarities
        for metadata_score in metadata
    )
    candidates.extend(
        SelectivePolicy(
            min_top_semantic_similarity=similarity,
            min_semantic_margin=margin,
            min_evidence_lane_count=2,
        )
        for similarity in similarities
        for margin in margins
    )
    unique = {policy.policy_ref: policy for policy in candidates}
    return tuple(unique[ref] for ref in sorted(unique))


def build_selective_report(
    bundle: GroundedDatasetBundleV2,
    run: GroundedRetrievalRunV2,
    *,
    bootstrap_samples: int = 10_000,
    bootstrap_seed: int = 20_260_902,
) -> dict[str, Any]:
    validate_run_identity_v2(bundle, run)
    baseline = SelectivePolicy()
    curve = tuple(
        score_policy(bundle, run, policy, split="dev", include_bad_cases=False)
        for policy in candidate_policies()
    )
    selected_summary = min(curve, key=_selection_key)
    selected = next(
        policy
        for policy in candidate_policies()
        if policy.policy_ref == selected_summary["policy"]["policy_ref"]
    )
    baseline_dev = score_policy(bundle, run, baseline, split="dev")
    baseline_holdout = score_policy(bundle, run, baseline, split="holdout")
    selected_dev = score_policy(bundle, run, selected, split="dev")
    # Holdout is deliberately scored only after the policy is fixed from dev.
    selected_holdout = score_policy(bundle, run, selected, split="holdout")
    return {
        "schema_version": "ip-asset-grounded-selective-report-v2",
        "maturity": "seed",
        "label_source": "codex_seed_v2",
        "truthfulness": {
            "human_gold": False,
            "human_agreement_available": False,
            "online_user_effectiveness": False,
            "production_threshold_activated": False,
            "holdout_used_for_policy_selection": False,
            "live_retrieval_measured": True,
            "real_embedding_provider_used": run.embedding_execution_mode == "alibaba",
        },
        "run": run_identity_v2(run),
        "selection": {
            "split": "dev",
            "criterion": (
                "min_balanced_abstention_error_then_selective_risk_then_max_coverage_then_mrr"
            ),
            "candidate_count": len(curve),
            "selected_policy": selected_summary["policy"],
        },
        "baseline": {"dev": baseline_dev, "holdout": baseline_holdout},
        "candidate": {"dev": selected_dev, "holdout": selected_holdout},
        "dev_curve": tuple(_curve_item(item) for item in curve),
        "paired_bootstrap": {
            "direction": "candidate_minus_baseline",
            "samples": bootstrap_samples,
            "seed": bootstrap_seed,
            "dev": _bootstrap_policy_delta(
                bundle,
                run,
                baseline,
                selected,
                split="dev",
                samples=bootstrap_samples,
                seed=bootstrap_seed,
            ),
            "holdout": _bootstrap_policy_delta(
                bundle,
                run,
                baseline,
                selected,
                split="holdout",
                samples=bootstrap_samples,
                seed=bootstrap_seed,
            ),
        },
        "validity": {
            "evidence_tier": "model_corpus_quality",
            "labels": "codex_seed_v2_not_human_gold",
            "review": "single_codex_blind_to_rank_and_score_not_independent_human_review",
            "harness_identity": "bound_to_safe_run_and_dataset_hashes",
            "contamination": "not_independently_audited",
            "ambiguous_or_broken_cases": "not_independently_adjudicated",
            "corpus_drift": "new_asset_set_fingerprint_requires_a_new_run",
            "holdout": "reported_once_after_dev_policy_selection",
            "deployment": "candidate_only_no_production_behavior_change",
        },
    }


def score_policy(
    bundle: GroundedDatasetBundleV2,
    run: GroundedRetrievalRunV2,
    policy: SelectivePolicy,
    *,
    split: Literal["dev", "holdout"] | None,
    include_bad_cases: bool = True,
) -> dict[str, Any]:
    query_by_ref = {query.query_ref: query for query in bundle.queries}
    grades_by_ref = {
        matrix.query_ref: {grade.catalog_ref: grade.grade for grade in matrix.grades}
        for matrix in bundle.seed
    }
    observations = tuple(
        observation
        for observation in run.observations
        if split is None or query_by_ref[observation.query_ref].split == split
    )
    rows: list[dict[str, Any]] = []
    for observation in observations:
        query = query_by_ref[observation.query_ref]
        grades = grades_by_ref[observation.query_ref]
        failed = observation.failure_code is not None
        answers = policy.answers(observation) if not failed else False
        ranking = ranking_metrics(observation.selected_catalog_refs, grades)
        rows.append(
            {
                "query_ref": query.query_ref,
                "category": query.category.value,
                "challenge_kind": (
                    query.challenge_kind.value if query.challenge_kind is not None else None
                ),
                "expected_answer_kind": query.expected_answer_kind,
                "failed": failed,
                "answers": answers,
                "ranking": ranking,
                "observation": observation,
            }
        )
    successful = [row for row in rows if not row["failed"]]
    answered = [row for row in successful if row["answers"]]
    answerable = [row for row in successful if row["expected_answer_kind"] == "has_relevant"]
    no_answer = [row for row in successful if row["expected_answer_kind"] == "no_answer"]
    retained_answerable = [row for row in answerable if row["answers"]]
    no_answer_false_positive = [row for row in no_answer if row["answers"]]
    answerable_false_abstention = [row for row in answerable if not row["answers"]]
    covered_errors = [
        row
        for row in answered
        if row["expected_answer_kind"] == "no_answer" or row["ranking"]["mrr_at_5"] == 0.0
    ]
    aggregate: dict[str, Any] = {
        "query_count": len(rows),
        "successful_query_count": len(successful),
        "execution_coverage": _ratio(len(successful), len(rows)),
        "decision_coverage": _ratio(len(answered), len(successful)),
        "selective_risk": _ratio(len(covered_errors), len(answered)),
        "answerable_query_count": len(answerable),
        "no_answer_query_count": len(no_answer),
        "no_answer_false_positive_rate": _ratio(len(no_answer_false_positive), len(no_answer)),
        "no_answer_correct_abstention_rate": _ratio(
            len(no_answer) - len(no_answer_false_positive), len(no_answer)
        ),
        "answerable_false_abstention_rate": _ratio(
            len(answerable_false_abstention), len(answerable)
        ),
    }
    false_positive_rate = aggregate["no_answer_false_positive_rate"]
    false_abstention_rate = aggregate["answerable_false_abstention_rate"]
    aggregate["balanced_abstention_error"] = (
        round((false_positive_rate + false_abstention_rate) / 2, 6)
        if false_positive_rate is not None and false_abstention_rate is not None
        else None
    )
    for metric in RANKING_METRICS:
        aggregate[f"unconditional_macro_{metric}"] = _mean(
            row["ranking"][metric] if row["answers"] else 0.0 for row in answerable
        )
        aggregate[f"retained_macro_{metric}"] = _mean(
            row["ranking"][metric] for row in retained_answerable
        )
    result: dict[str, Any] = {
        "policy": _policy_dict(policy),
        "aggregate": aggregate,
        "categories": _slice_rows(rows, "category"),
        "challenge_kinds": _slice_rows(
            [row for row in rows if row["challenge_kind"] is not None],
            "challenge_kind",
        ),
        "robustness": _robustness_summary(bundle, rows),
    }
    if include_bad_cases:
        result["bad_cases"] = tuple(_bad_case(row) for row in rows if _is_bad_case(row))
    return result


def ranking_metrics(selected: tuple[str, ...], grades: dict[str, int]) -> dict[str, float]:
    relevant = {ref for ref, grade in grades.items() if grade >= 2}
    if not relevant:
        return {metric: 0.0 for metric in RANKING_METRICS}
    selected_at_3 = selected[:3]
    selected_at_5 = selected[:5]
    first_relevant = next(
        (rank for rank, ref in enumerate(selected_at_5, start=1) if ref in relevant),
        None,
    )
    actual = _dcg([grades[ref] for ref in selected_at_5])
    ideal = _dcg(sorted(grades.values(), reverse=True)[:5])
    return {
        "recall_at_3": len(relevant.intersection(selected_at_3)) / len(relevant),
        "recall_at_5": len(relevant.intersection(selected_at_5)) / len(relevant),
        "mrr_at_5": 1.0 / first_relevant if first_relevant is not None else 0.0,
        "ndcg_at_5": actual / ideal if ideal > 0 else 0.0,
    }


def _dcg(grades: list[int]) -> float:
    return float(sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, 1)))


def _slice_rows(rows: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[field])].append(row)
    return {key: _slice_summary(items) for key, items in sorted(grouped.items())}


def _slice_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [row for row in rows if not row["failed"]]
    answered = [row for row in successful if row["answers"]]
    answerable = [row for row in successful if row["expected_answer_kind"] == "has_relevant"]
    no_answer = [row for row in successful if row["expected_answer_kind"] == "no_answer"]
    retained_answerable = [row for row in answerable if row["answers"]]
    covered_errors = [
        row
        for row in answered
        if row["expected_answer_kind"] == "no_answer" or row["ranking"]["mrr_at_5"] == 0.0
    ]
    summary: dict[str, Any] = {
        "query_count": len(rows),
        "successful_query_count": len(successful),
        "execution_coverage": _ratio(len(successful), len(rows)),
        "decision_coverage": _ratio(len(answered), len(successful)),
        "selective_risk": _ratio(len(covered_errors), len(answered)),
        "answerable_query_count": len(answerable),
        "no_answer_query_count": len(no_answer),
        "no_answer_false_positive_rate": _ratio(
            sum(bool(row["answers"]) for row in no_answer), len(no_answer)
        ),
        "answerable_false_abstention_rate": _ratio(
            sum(not bool(row["answers"]) for row in answerable), len(answerable)
        ),
        "error_count": sum(_is_bad_case(row) for row in rows),
    }
    for metric in RANKING_METRICS:
        summary[f"unconditional_macro_{metric}"] = _mean(
            row["ranking"][metric] if row["answers"] else 0.0 for row in answerable
        )
        summary[f"retained_macro_{metric}"] = _mean(
            row["ranking"][metric] for row in retained_answerable
        )
    return summary


def _robustness_summary(
    bundle: GroundedDatasetBundleV2,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    by_ref = {row["query_ref"]: row for row in rows}
    counts: Counter[str] = Counter()
    passed: Counter[str] = Counter()
    violations: list[dict[str, str]] = []
    for pair in bundle.robustness_pairs:
        challenge = by_ref.get(pair.challenge_query_ref)
        anchor = by_ref.get(pair.anchor_query_ref)
        if challenge is None or anchor is None:
            continue
        relation = pair.relation.value
        counts[relation] += 1
        consistent = bool(anchor["answers"]) and not bool(challenge["answers"])
        if consistent:
            passed[relation] += 1
        else:
            violations.append(
                {
                    "anchor_query_ref": pair.anchor_query_ref,
                    "challenge_query_ref": pair.challenge_query_ref,
                    "relation": relation,
                }
            )
    return {
        "pair_count": sum(counts.values()),
        "consistency_rate": _ratio(sum(passed.values()), sum(counts.values())),
        "relations": {
            relation: {
                "pair_count": count,
                "consistency_rate": _ratio(passed[relation], count),
            }
            for relation, count in sorted(counts.items())
        },
        "violations": tuple(violations),
    }


def _is_bad_case(row: dict[str, Any]) -> bool:
    if row["failed"]:
        return True
    if row["expected_answer_kind"] == "no_answer":
        return bool(row["answers"])
    return not row["answers"] or row["ranking"]["mrr_at_5"] == 0.0


def _bad_case(row: dict[str, Any]) -> dict[str, Any]:
    observation = row["observation"]
    evidence = observation.decision_evidence
    if row["failed"]:
        reason = "execution_failure"
    elif row["expected_answer_kind"] == "no_answer":
        reason = "no_answer_false_positive"
    elif not row["answers"]:
        reason = "answerable_false_abstention"
    else:
        reason = "answerable_relevance_miss"
    return {
        "query_ref": row["query_ref"],
        "reason": reason,
        "failure_code": observation.failure_code,
        "returned_count": len(observation.selected_catalog_refs),
        "top_semantic_similarity": (
            evidence.top_semantic_similarity if evidence is not None else None
        ),
        "semantic_margin": evidence.semantic_margin if evidence is not None else None,
        "metadata_match_score": (evidence.metadata_match_score if evidence is not None else None),
        "evidence_lane_count": evidence.evidence_lane_count if evidence is not None else 0,
    }


def _bootstrap_policy_delta(
    bundle: GroundedDatasetBundleV2,
    run: GroundedRetrievalRunV2,
    baseline: SelectivePolicy,
    candidate: SelectivePolicy,
    *,
    split: Literal["dev", "holdout"],
    samples: int,
    seed: int,
) -> dict[str, dict[str, float | int]]:
    query_by_ref = {query.query_ref: query for query in bundle.queries}
    grades_by_ref = {
        matrix.query_ref: {grade.catalog_ref: grade.grade for grade in matrix.grades}
        for matrix in bundle.seed
    }
    pairs: dict[str, list[tuple[float, float]]] = {
        "decision_utility": [],
        "no_answer_correct_abstention": [],
        "answerable_answer_rate": [],
        **{metric: [] for metric in RANKING_METRICS},
    }
    for observation in run.observations:
        query = query_by_ref[observation.query_ref]
        if query.split != split or observation.failure_code is not None:
            continue
        ranking = ranking_metrics(
            observation.selected_catalog_refs,
            grades_by_ref[observation.query_ref],
        )
        baseline_answers = baseline.answers(observation)
        candidate_answers = candidate.answers(observation)
        if query.expected_answer_kind == "no_answer":
            correct_abstention = (float(not baseline_answers), float(not candidate_answers))
            pairs["decision_utility"].append(correct_abstention)
            pairs["no_answer_correct_abstention"].append(correct_abstention)
            continue
        pairs["answerable_answer_rate"].append((float(baseline_answers), float(candidate_answers)))
        pairs["decision_utility"].append(
            (
                float(baseline_answers and ranking["mrr_at_5"] > 0),
                float(candidate_answers and ranking["mrr_at_5"] > 0),
            )
        )
        for metric in RANKING_METRICS:
            pairs[metric].append(
                (
                    ranking[metric] if baseline_answers else 0.0,
                    ranking[metric] if candidate_answers else 0.0,
                )
            )
    return {
        metric: paired_bootstrap_interval(tuple(values), samples=samples, seed=seed)
        for metric, values in pairs.items()
    }


def _selection_key(summary: dict[str, Any]) -> tuple[float, float, float, float, str]:
    aggregate = summary["aggregate"]
    return (
        _none_last(aggregate["balanced_abstention_error"]),
        _none_last(aggregate["selective_risk"]),
        -float(aggregate["decision_coverage"] or 0.0),
        -float(aggregate["unconditional_macro_mrr_at_5"] or 0.0),
        str(summary["policy"]["policy_ref"]),
    )


def _curve_item(summary: dict[str, Any]) -> dict[str, Any]:
    aggregate = summary["aggregate"]
    item = {
        "policy": summary["policy"],
        "decision_coverage": aggregate["decision_coverage"],
        "selective_risk": aggregate["selective_risk"],
        "no_answer_false_positive_rate": aggregate["no_answer_false_positive_rate"],
        "answerable_false_abstention_rate": aggregate["answerable_false_abstention_rate"],
        "balanced_abstention_error": aggregate["balanced_abstention_error"],
    }
    for metric in RANKING_METRICS:
        item[f"unconditional_macro_{metric}"] = aggregate[f"unconditional_macro_{metric}"]
        item[f"retained_macro_{metric}"] = aggregate[f"retained_macro_{metric}"]
    return item


def _policy_dict(policy: SelectivePolicy) -> dict[str, Any]:
    return {"policy_ref": policy.policy_ref, **asdict(policy)}


def run_identity_v2(run: GroundedRetrievalRunV2) -> dict[str, Any]:
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
        "robustness_dataset_sha256": run.robustness_dataset_sha256,
        "review_ledger_sha256": run.review_ledger_sha256,
        "duration_ms": run.duration_ms,
        "provider_request_count": run.provider_request_count,
        "input_token_count": run.input_token_count,
        "estimated_cost_usd": run.estimated_cost_usd,
    }


def validate_run_identity_v2(
    bundle: GroundedDatasetBundleV2,
    run: GroundedRetrievalRunV2,
) -> None:
    identities = (
        (run.asset_set_fingerprint, bundle.assets.asset_set_fingerprint),
        (run.query_dataset_sha256, bundle.queries_sha256),
        (run.seed_dataset_sha256, bundle.seed_sha256),
        (run.robustness_dataset_sha256, bundle.robustness_sha256),
        (run.review_ledger_sha256, bundle.review_sha256),
    )
    if any(actual != expected for actual, expected in identities):
        raise ValueError("grounded Seed V2 run identity does not match the dataset")
    if [observation.query_ref for observation in run.observations] != [
        query.query_ref for query in bundle.queries
    ]:
        raise ValueError("grounded Seed V2 run does not cover the query set")
    known_assets = {asset.catalog_ref for asset in bundle.assets.assets}
    if any(
        not set(observation.selected_catalog_refs).issubset(known_assets)
        for observation in run.observations
    ):
        raise ValueError("grounded Seed V2 run contains an unknown asset")


def _meets(value: float | None, threshold: float | None) -> bool:
    return threshold is None or (value is not None and value >= threshold)


def _meets_int(value: int, threshold: int | None) -> bool:
    return threshold is None or value >= threshold


def _threshold_ref(prefix: str, value: float | None) -> str:
    return f"{prefix}na" if value is None else f"{prefix}{round(value * 1_000):03d}"


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _mean(values: Iterable[float]) -> float | None:
    clean = tuple(values)
    return round(sum(clean) / len(clean), 6) if clean else None


def _none_last(value: object) -> float:
    return float(value) if isinstance(value, (float, int)) else float("inf")
