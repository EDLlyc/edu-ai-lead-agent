"""Stable JSON and Markdown rendering for brand retrieval evaluation."""

from __future__ import annotations

import json

from pydantic import BaseModel

from .metrics import BrandRetrievalEvalReport, BrandRetrievalTrackScore


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


def render_markdown(report: BrandRetrievalEvalReport) -> str:
    aggregate = report.aggregate
    lines = [
        "# Brand text retrieval deterministic baseline",
        "",
        f"> {report.disclaimer}",
        "",
        f"- Dataset: `{report.dataset_version}` ({aggregate.case_count} cases)",
        f"- Top K: {report.top_k}",
        f"- Passed: {aggregate.passed_count}/{aggregate.case_count}",
        "",
        "## Retrieval-policy comparison",
        "",
        "| Metric | Legacy v2 | Structured v3 |",
        "| --- | ---: | ---: |",
        f"| Recall@5 | {_pct(aggregate.legacy_v2.macro_recall_at_5)} | "
        f"{_pct(aggregate.structured_v3.macro_recall_at_5)} |",
        f"| MRR@5 | {_pct(aggregate.legacy_v2.macro_mrr_at_5)} | "
        f"{_pct(aggregate.structured_v3.macro_mrr_at_5)} |",
        f"| nDCG@5 | {_pct(aggregate.legacy_v2.macro_ndcg_at_5)} | "
        f"{_pct(aggregate.structured_v3.macro_ndcg_at_5)} |",
        f"| Parent diversity@5 | "
        f"{_pct(aggregate.legacy_v2.macro_parent_diversity_at_5)} | "
        f"{_pct(aggregate.structured_v3.macro_parent_diversity_at_5)} |",
        f"| External-claim verification | "
        f"{_pct(aggregate.legacy_v2.verification_coverage)} | "
        f"{_pct(aggregate.structured_v3.verification_coverage)} |",
        f"| Brand-as-fact violations | "
        f"{aggregate.legacy_v2.brand_as_fact_violation_count} | "
        f"{aggregate.structured_v3.brand_as_fact_violation_count} |",
        "",
        f"Parent-diversity delta: `{aggregate.parent_diversity_delta:+.6f}`.",
        "",
        "## Case results",
        "",
        "| Case | Category | Pass | v2 R/M/N/D | v3 R/M/N/D | Failures |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case in report.cases:
        failures = ", ".join(f"`{code}`" for code in case.failure_codes) or "—"
        lines.append(
            f"| `{case.case_id}` | `{case.category.value}` | "
            f"{'yes' if case.passed else 'no'} | {_compact(case.legacy_v2)} | "
            f"{_compact(case.structured_v3)} | {failures} |"
        )
    lines.extend(
        [
            "",
            "The evaluator ranks only from fixture FTS/vector observations. Graded relevance is "
            "held by the scorer and never supplied to RRF fusion or the production selector.",
            "",
        ]
    )
    return "\n".join(lines)


def _compact(score: BrandRetrievalTrackScore) -> str:
    return "/".join(
        (
            f"{score.recall_at_5:.3f}",
            f"{score.mrr_at_5:.3f}",
            f"{score.ndcg_at_5:.3f}",
            f"{score.parent_diversity_at_5:.3f}",
        )
    )


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"
