from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from .dataset import GroundedDatasetBundle, GroundedDatasetBundleV2
from .metrics import aggregate_scores, run_identity, score_run
from .models import GroundedRetrievalRun


def build_seed_report(bundle: GroundedDatasetBundle) -> dict[str, Any]:
    grade_counts: Counter[int] = Counter()
    relevant_counts: list[int] = []
    category_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    category_relevant: dict[str, list[int]] = defaultdict(list)
    query_by_ref = {query.query_ref: query for query in bundle.queries}
    for matrix in bundle.seed:
        query = query_by_ref[matrix.query_ref]
        counts = Counter(item.grade for item in matrix.grades)
        grade_counts.update(counts)
        relevant = sum(item.grade >= 2 for item in matrix.grades)
        relevant_counts.append(relevant)
        category_counts[query.category.value] += 1
        split_counts[query.split] += 1
        category_relevant[query.category.value].append(relevant)
    answer_kinds = Counter(query.expected_answer_kind for query in bundle.queries)
    return {
        "schema_version": "ip-asset-grounded-seed-report-v1",
        "maturity": "seed",
        "label_source": "codex_seed",
        "truthfulness": {
            "human_gold": False,
            "human_agreement_available": False,
            "live_retrieval_measured": False,
        },
        "dataset": {
            "asset_count": len(bundle.assets.assets),
            "query_count": len(bundle.queries),
            "judgment_count": sum(len(matrix.grades) for matrix in bundle.seed),
            "asset_set_fingerprint": bundle.assets.asset_set_fingerprint,
            "assets_sha256": bundle.assets_sha256,
            "queries_sha256": bundle.queries_sha256,
            "seed_sha256": bundle.seed_sha256,
        },
        "distribution": {
            "categories": dict(sorted(category_counts.items())),
            "splits": dict(sorted(split_counts.items())),
            "answer_kinds": dict(sorted(answer_kinds.items())),
            "grades": {str(grade): grade_counts[grade] for grade in range(4)},
            "relevant_per_answerable_query": {
                "minimum": min(
                    count
                    for query, count in zip(bundle.queries, relevant_counts, strict=True)
                    if query.expected_answer_kind == "has_relevant"
                ),
                "maximum": max(relevant_counts),
            },
            "category_mean_relevant": {
                category: round(sum(counts) / len(counts), 3)
                for category, counts in sorted(category_relevant.items())
            },
        },
    }


def build_seed_v2_report(bundle: GroundedDatasetBundleV2) -> dict[str, Any]:
    grade_counts: Counter[int] = Counter(
        grade.grade for matrix in bundle.seed for grade in matrix.grades
    )
    category_counts = Counter(query.category.value for query in bundle.queries)
    split_counts = Counter(query.split for query in bundle.queries)
    answer_kinds = Counter(query.expected_answer_kind for query in bundle.queries)
    challenge_kinds = Counter(
        query.challenge_kind.value for query in bundle.queries if query.challenge_kind is not None
    )
    robustness_relations = Counter(pair.relation.value for pair in bundle.robustness_pairs)
    return {
        "schema_version": "ip-asset-grounded-seed-report-v2",
        "maturity": "seed",
        "label_source": "codex_seed_v2",
        "truthfulness": {
            "human_gold": False,
            "human_agreement_available": False,
            "independent_review_available": False,
            "live_retrieval_measured": False,
        },
        "dataset": {
            "asset_count": len(bundle.assets.assets),
            "query_count": len(bundle.queries),
            "judgment_count": sum(len(matrix.grades) for matrix in bundle.seed),
            "no_answer_count": sum(
                query.expected_answer_kind == "no_answer" for query in bundle.queries
            ),
            "asset_set_fingerprint": bundle.assets.asset_set_fingerprint,
            "assets_sha256": bundle.assets_sha256,
            "queries_sha256": bundle.queries_sha256,
            "seed_sha256": bundle.seed_sha256,
            "review_sha256": bundle.review_sha256,
            "robustness_sha256": bundle.robustness_sha256,
            "source_v1_queries_sha256": bundle.source_v1_queries_sha256,
            "source_v1_seed_sha256": bundle.source_v1_seed_sha256,
        },
        "distribution": {
            "categories": dict(sorted(category_counts.items())),
            "splits": dict(sorted(split_counts.items())),
            "answer_kinds": dict(sorted(answer_kinds.items())),
            "challenge_kinds": dict(sorted(challenge_kinds.items())),
            "grades": {str(grade): grade_counts[grade] for grade in range(4)},
            "robustness_relations": dict(sorted(robustness_relations.items())),
        },
        "review": {
            "review_pass_id": bundle.review.review_pass_id,
            "reviewed_asset_count": bundle.review.reviewed_asset_count,
            "reviewed_scopes": bundle.review.reviewed_scopes,
            "changed_grade_count": len(bundle.review.changes),
            "rank_or_score_observations_opened": (bundle.review.rank_or_score_observations_opened),
            "independent_human_review": bundle.review.independent_human_review,
        },
    }


def canonical_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_run_report(bundle: GroundedDatasetBundle, run: GroundedRetrievalRun) -> dict[str, Any]:
    return {
        "schema_version": "ip-asset-grounded-run-report-v1",
        "maturity": "seed",
        "label_source": "codex_seed",
        "truthfulness": {
            "human_gold": False,
            "human_agreement_available": False,
            "online_user_effectiveness": False,
            "business_impact_measured": False,
            "live_retrieval_measured": True,
            "real_embedding_provider_used": run.embedding_execution_mode == "alibaba",
        },
        "run": run_identity(run),
        "metrics": aggregate_scores(score_run(bundle, run)),
    }


def render_run_markdown(report: dict[str, Any]) -> str:
    run = report["run"]
    overall = report["metrics"]["overall"]
    lines = [
        "# IP asset grounded retrieval run",
        "",
        "> Results use a Codex relevance seed, not human Gold, online user effectiveness, "
        "or business impact evidence.",
        "",
        f"- Run: `{run['run_ref']}` at `{run['created_at']}`",
        f"- Search: `{run['search_version']}`",
        f"- Embedding execution: `{run['embedding_execution_mode']}` / "
        f"`{run['embedding_provider']}` / `{run['embedding_model']}`",
        f"- Embedding dimensions/policy: {run['embedding_dimensions']} / "
        f"`{run['embedding_input_policy_version']}`",
        f"- Coverage: {_rate(overall['coverage'])}",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for metric in ("recall_at_3", "recall_at_5", "mrr_at_5", "ndcg_at_5"):
        lines.append(f"| {metric} | {_rate(overall[f'macro_{metric}'])} |")
    lines.extend(
        [
            f"| zero_result_rate | {_rate(overall['zero_result_rate'])} |",
            f"| no_answer_correct_abstention_rate | {_rate(overall['correct_abstention_rate'])} |",
            f"| no_answer_false_positive_rate | {_rate(overall['false_positive_rate'])} |",
            "",
            "## Category aggregates",
            "",
            "| Category | Queries | Recall@5 | MRR@5 | nDCG@5 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for category, bucket in report["metrics"]["categories"].items():
        lines.append(
            f"| `{category}` | {bucket['query_count']} | "
            f"{_rate(bucket['macro_recall_at_5'])} | "
            f"{_rate(bucket['macro_mrr_at_5'])} | "
            f"{_rate(bucket['macro_ndcg_at_5'])} |"
        )
    lines.extend(
        [
            "",
            f"Dataset identity: asset `{run['asset_set_fingerprint']}`, query "
            f"`{run['query_dataset_sha256']}`, seed `{run['seed_dataset_sha256']}`.",
            "",
        ]
    )
    return "\n".join(lines)


def _rate(value: object) -> str:
    if value is None:
        return "n/a"
    if not isinstance(value, (int, float)):
        raise TypeError("grounded report rate must be numeric")
    return f"{float(value):.4f}"


def render_seed_markdown(report: dict[str, Any]) -> str:
    dataset = report["dataset"]
    distribution = report["distribution"]
    lines = [
        "# IP asset grounded retrieval Codex seed",
        "",
        "> This report validates a Codex-authored 0-3 relevance seed over the real approved "
        "41-image corpus. It is not human Gold, human agreement, a live-provider result, "
        "online user effectiveness, or business impact evidence.",
        "",
        f"- Maturity: `{report['maturity']}`",
        f"- Assets: {dataset['asset_count']}",
        f"- Queries: {dataset['query_count']} (80 dev / 20 holdout)",
        f"- Judgments: {dataset['judgment_count']}",
        f"- Asset-set fingerprint: `{dataset['asset_set_fingerprint']}`",
        f"- Query dataset SHA-256: `{dataset['queries_sha256']}`",
        f"- Seed dataset SHA-256: `{dataset['seed_sha256']}`",
        "",
        "## Query distribution",
        "",
        "| Category | Queries | Mean usable assets (grade >= 2) |",
        "| --- | ---: | ---: |",
    ]
    for category, count in distribution["categories"].items():
        lines.append(
            f"| `{category}` | {count} | {distribution['category_mean_relevant'][category]:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Grade distribution",
            "",
            "| Grade | Meaning | Judgments |",
            "| ---: | --- | ---: |",
        ]
    )
    meanings = {
        "0": "irrelevant or conflicting",
        "1": "weak/local relevance",
        "2": "usable but incomplete",
        "3": "highly relevant / preferred",
    }
    for grade in ("0", "1", "2", "3"):
        lines.append(f"| {grade} | {meanings[grade]} | {distribution['grades'][grade]} |")
    lines.extend(
        [
            "",
            "The fixed query set includes `小赛和赛先生在空间站`. "
            "No-answer cases are retained for abstention/false-positive measurement and do not "
            "receive artificial perfect Recall/MRR values.",
            "",
        ]
    )
    return "\n".join(lines)


def render_seed_v2_markdown(report: dict[str, Any]) -> str:
    dataset = report["dataset"]
    distribution = report["distribution"]
    review = report["review"]
    lines = [
        "# IP asset grounded retrieval Codex Seed V2",
        "",
        "> This additive dataset was authored and risk-reviewed by Codex after re-viewing the "
        "approved 41-image corpus. It remains Seed evidence, not human Gold, independent review, "
        "human agreement, live-provider quality, or online-effectiveness evidence.",
        "",
        f"- Assets: {dataset['asset_count']}",
        f"- Queries: {dataset['query_count']} (98 dev / 26 holdout)",
        f"- No-answer challenges: {dataset['no_answer_count']}",
        f"- Judgments: {dataset['judgment_count']}",
        f"- Blind risk-review grade changes: {review['changed_grade_count']}",
        f"- Blind risk-review scopes: {', '.join(review['reviewed_scopes'])}",
        f"- Source V1 query hash: `{dataset['source_v1_queries_sha256']}`",
        f"- Source V1 seed hash: `{dataset['source_v1_seed_sha256']}`",
        f"- V2 query hash: `{dataset['queries_sha256']}`",
        f"- V2 seed hash: `{dataset['seed_sha256']}`",
        f"- Review ledger hash: `{dataset['review_sha256']}`",
        f"- Robustness metadata hash: `{dataset['robustness_sha256']}`",
        "",
        "## Challenge distribution",
        "",
        "| Challenge | Queries |",
        "| --- | ---: |",
    ]
    for challenge, count in distribution["challenge_kinds"].items():
        lines.append(f"| `{challenge}` | {count} |")
    lines.extend(
        [
            "",
            "## Grade distribution",
            "",
            "| Grade | Judgments |",
            "| ---: | ---: |",
        ]
    )
    for grade in ("0", "1", "2", "3"):
        lines.append(f"| {grade} | {distribution['grades'][grade]} |")
    lines.extend(
        [
            "",
            "The 24 additive challenges contain no grade >= 2 by construction and are paired "
            "with answerable anchors for paraphrase/noise or filter-monotonicity diagnostics. "
            "The review pass did not open per-query rank or score observations; because the same "
            "AI authored and reviewed the labels, it does not establish independent agreement.",
            "",
        ]
    )
    return "\n".join(lines)


def render_selective_markdown(report: dict[str, Any]) -> str:
    policy = report["selection"]["selected_policy"]
    baseline_dev = report["baseline"]["dev"]["aggregate"]
    candidate_dev = report["candidate"]["dev"]["aggregate"]
    baseline_holdout = report["baseline"]["holdout"]["aggregate"]
    candidate_holdout = report["candidate"]["holdout"]["aggregate"]
    lines = [
        "# IP asset selective-retrieval Seed V2 report",
        "",
        "> Candidate evidence uses Codex Seed V2, not human Gold or online effectiveness. The "
        "selected policy is diagnostic only and is not active in production.",
        "",
        f"- Run: `{report['run']['run_ref']}`",
        f"- Search: `{report['run']['search_version']}`",
        f"- Selected on: `dev` only ({report['selection']['candidate_count']} candidates)",
        f"- Candidate policy: `{policy['policy_ref']}`",
        f"- Provider mode: `{report['run']['embedding_execution_mode']}`",
        "",
        "| Split / metric | Baseline | Candidate |",
        "| --- | ---: | ---: |",
    ]
    for split, baseline, candidate in (
        ("dev", baseline_dev, candidate_dev),
        ("holdout", baseline_holdout, candidate_holdout),
    ):
        for metric in (
            "decision_coverage",
            "selective_risk",
            "no_answer_false_positive_rate",
            "answerable_false_abstention_rate",
            "unconditional_macro_recall_at_5",
            "unconditional_macro_mrr_at_5",
            "unconditional_macro_ndcg_at_5",
        ):
            lines.append(
                f"| {split} / {metric} | {_rate(baseline[metric])} | {_rate(candidate[metric])} |"
            )
    lines.extend(
        [
            "",
            "Holdout was evaluated after the dev-selected policy was fixed. Bad cases contain "
            "only safe query refs and bounded evidence, never query text, image paths, vectors, "
            "provider bodies, or user identity.",
            "",
        ]
    )
    return "\n".join(lines)


def render_comparison_markdown(report: dict[str, Any]) -> str:
    baseline = report["baseline"]["overall"]
    candidate = report["candidate"]["overall"]
    intervals = report["paired_bootstrap"]["metrics"]
    lines = [
        "# IP asset grounded retrieval paired comparison",
        "",
        "> Results use a Codex relevance seed, not human Gold or online effectiveness data.",
        "",
        f"- Baseline: `{report['baseline_search_version']}`",
        f"- Candidate: `{report['candidate_search_version']}`",
        f"- Bootstrap samples: {report['paired_bootstrap']['samples']}",
        "",
        "| Metric | Baseline | Candidate | Delta | 95% CI | Queries |",
        "| --- | ---: | ---: | ---: | --- | ---: |",
    ]
    for metric in ("recall_at_3", "recall_at_5", "mrr_at_5", "ndcg_at_5"):
        interval = intervals[metric]
        lines.append(
            f"| {metric} | {baseline[f'macro_{metric}']:.4f} | "
            f"{candidate[f'macro_{metric}']:.4f} | {interval['delta']:+.4f} | "
            f"[{interval['ci95_low']:+.4f}, {interval['ci95_high']:+.4f}] | "
            f"{interval['query_count']} |"
        )
    lines.extend(
        [
            "",
            "No-answer queries are reported separately: baseline false-positive rate "
            f"{baseline['false_positive_rate']!s}; candidate "
            f"{candidate['false_positive_rate']!s}.",
            "",
        ]
    )
    return "\n".join(lines)
