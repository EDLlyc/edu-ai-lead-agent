"""Run the provider-free IP asset V2/V3 retrieval evaluation."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.domain.ip_assets import (
    IP_ASSET_SEARCH_V2_VERSION,
    IP_ASSET_SEARCH_V3_VERSION,
    IpAssetRankCandidate,
    rank_ip_asset_candidates,
)

from .dataset import DEFAULT_CASES_PATH, IpAssetRetrievalEvalDatasetError, load_eval_cases
from .metrics import RetrievalMetrics, score_ranking
from .models import CASE_SCHEMA_VERSION, IpAssetRetrievalEvalCase
from .reporting import canonical_json, render_markdown

FEATURE_ROOT = Path(__file__).resolve().parent
CANONICAL_JSON_PATH = FEATURE_ROOT / "canonical-report.json"
CANONICAL_MARKDOWN_PATH = FEATURE_ROOT / "canonical-report.md"


def evaluate_path(path: Path = DEFAULT_CASES_PATH) -> dict[str, Any]:
    cases = load_eval_cases(path)
    try:
        dataset_hash = sha256(path.read_bytes()).hexdigest()[:16]
    except OSError as exc:
        raise IpAssetRetrievalEvalDatasetError("dataset could not be hashed") from exc
    scored = tuple(_score_case(case) for case in cases)
    categories: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in scored:
        categories[item["category"]].append(item)
    return {
        "dataset_version": f"{CASE_SCHEMA_VERSION}:{dataset_hash}",
        "aggregate": _aggregate(scored),
        "categories": {
            category: _aggregate(tuple(items)) for category, items in categories.items()
        },
        "cases": scored,
    }


def _score_case(case: IpAssetRetrievalEvalCase) -> dict[str, Any]:
    observed = tuple(
        IpAssetRankCandidate(
            asset_ref=candidate.candidate_id,
            created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
            stable_id=f"{index:04d}",
            metadata_rank=candidate.metadata_rank,
            semantic_rank=candidate.semantic_rank,
            metadata_score=candidate.metadata_score,
            semantic_similarity=candidate.semantic_similarity,
        )
        for index, candidate in enumerate(case.candidates, start=1)
    )
    v2_ids = rank_ip_asset_candidates(observed, version=IP_ASSET_SEARCH_V2_VERSION, limit=5)
    v3_ids = rank_ip_asset_candidates(observed, version=IP_ASSET_SEARCH_V3_VERSION, limit=5)
    relevance = {candidate.candidate_id: candidate.relevance_grade for candidate in case.candidates}
    v2 = score_ranking(selected_ids=v2_ids, relevance_by_id=relevance)
    v3 = score_ranking(selected_ids=v3_ids, relevance_by_id=relevance)
    exact_priority_passed = (
        not case.exact_metadata_priority
        or not case.candidates
        or (
            v3_ids
            and v3_ids[0]
            == min(
                (item for item in case.candidates if item.metadata_rank is not None),
                key=lambda item: item.metadata_rank or 1_000,
            ).candidate_id
        )
    )
    return {
        "case_id": case.case_id,
        "category": case.category,
        "exact_metadata_priority_passed": exact_priority_passed,
        "v2": _track(v2, v2_ids, IP_ASSET_SEARCH_V2_VERSION),
        "v3": _track(v3, v3_ids, IP_ASSET_SEARCH_V3_VERSION),
    }


def _track(
    metrics: RetrievalMetrics, selected_ids: tuple[str, ...], version: str
) -> dict[str, Any]:
    return {
        "retrieval_version": version,
        "selected_candidate_ids": list(selected_ids),
        "recall_at_5": round(metrics.recall_at_5, 6),
        "mrr_at_5": round(metrics.mrr_at_5, 6),
        "ndcg_at_5": round(metrics.ndcg_at_5, 6),
        "zero_result": metrics.zero_result,
    }


def _aggregate(items: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    def track(name: str, version: str) -> dict[str, Any]:
        count = len(items)
        return {
            "retrieval_version": version,
            "macro_recall_at_5": round(sum(item[name]["recall_at_5"] for item in items) / count, 6),
            "macro_mrr_at_5": round(sum(item[name]["mrr_at_5"] for item in items) / count, 6),
            "macro_ndcg_at_5": round(sum(item[name]["ndcg_at_5"] for item in items) / count, 6),
            "zero_result_rate": round(
                sum(bool(item[name]["zero_result"]) for item in items) / count, 6
            ),
        }

    return {
        "case_count": len(items),
        "exact_metadata_priority_passed": all(
            item["exact_metadata_priority_passed"] for item in items
        ),
        "v2": track("v2", IP_ASSET_SEARCH_V2_VERSION),
        "v3": track("v3", IP_ASSET_SEARCH_V3_VERSION),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write-canonical", action="store_true")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    args = parser.parse_args(argv)
    try:
        report = evaluate_path(args.cases)
    except (IpAssetRetrievalEvalDatasetError, RuntimeError, ValueError) as exc:
        print(f"IP asset retrieval eval failed: {exc}", file=sys.stderr)
        return 1
    aggregate = report["aggregate"]
    failed = bool(
        aggregate["v3"]["macro_recall_at_5"] < aggregate["v2"]["macro_recall_at_5"]
        or aggregate["v3"]["macro_mrr_at_5"] < aggregate["v2"]["macro_mrr_at_5"]
        or aggregate["v3"]["macro_ndcg_at_5"] < aggregate["v2"]["macro_ndcg_at_5"]
        or not aggregate["exact_metadata_priority_passed"]
    )
    if failed:
        print("IP asset retrieval eval gates failed", file=sys.stderr)
        return 1
    rendered_json = canonical_json(report)
    rendered_markdown = render_markdown(report)
    if args.write_canonical:
        CANONICAL_JSON_PATH.write_text(rendered_json, encoding="utf-8")
        CANONICAL_MARKDOWN_PATH.write_text(rendered_markdown, encoding="utf-8")
    elif args.check and not _artifacts_match(rendered_json, rendered_markdown):
        print("IP asset retrieval canonical report drifted", file=sys.stderr)
        return 1
    print(
        "IP asset retrieval eval passed: "
        f"{aggregate['case_count']} cases; "
        f"v3 recall@5={aggregate['v3']['macro_recall_at_5']:.6f}; "
        f"v3 ndcg@5={aggregate['v3']['macro_ndcg_at_5']:.6f}"
    )
    return 0


def _artifacts_match(rendered_json: str, rendered_markdown: str) -> bool:
    try:
        return (
            CANONICAL_JSON_PATH.read_text(encoding="utf-8") == rendered_json
            and CANONICAL_MARKDOWN_PATH.read_text(encoding="utf-8") == rendered_markdown
        )
    except OSError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
