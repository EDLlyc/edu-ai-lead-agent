from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.domain.ip_assets import (
    IP_ASSET_SEARCH_V2_VERSION,
    IP_ASSET_SEARCH_V3_VERSION,
    IpAssetRankCandidate,
    rank_ip_asset_candidates,
)
from evals.ip_asset_retrieval.dataset import (
    IpAssetRetrievalEvalDatasetError,
    load_eval_cases,
)
from evals.ip_asset_retrieval.reporting import canonical_json, render_markdown
from evals.ip_asset_retrieval.runner import _score_case, evaluate_path, main


def test_ip_asset_retrieval_fixture_is_balanced_and_v3_passes_gates() -> None:
    cases = load_eval_cases()
    report = evaluate_path()

    assert len(cases) == 41
    assert Counter(case.category for case in cases) == Counter(
        {
            "action": 5,
            "asset_type": 5,
            "character": 5,
            "combined_filters": 6,
            "emotion": 5,
            "intended_use": 5,
            "scene": 5,
            "transparent_background": 5,
        }
    )
    assert "小赛和赛先生在空间站" in {case.query for case in cases}
    aggregate = report["aggregate"]
    assert aggregate["v2"]["macro_recall_at_5"] == 0.839024
    assert aggregate["v3"]["macro_recall_at_5"] == 0.921951
    assert aggregate["v3"]["macro_mrr_at_5"] == 1.0
    assert aggregate["v3"]["macro_ndcg_at_5"] == 0.970931
    assert aggregate["v3"]["zero_result_rate"] == 0.195122
    assert aggregate["exact_metadata_priority_passed"] is True


def test_ip_asset_retrieval_report_is_stable_and_truthfully_scoped() -> None:
    report = evaluate_path()

    assert canonical_json(report) == canonical_json(evaluate_path())
    markdown = render_markdown(report)
    assert "provider-free" in markdown
    assert "not a live embedding" in markdown
    assert "production-effectiveness claim" in markdown


def test_ip_asset_retrieval_oracle_cannot_change_production_order() -> None:
    case = next(item for item in load_eval_cases() if item.candidates)
    original = _score_case(case)
    changed = _score_case(
        case.model_copy(
            update={
                "candidates": tuple(
                    candidate.model_copy(
                        update={"relevance_grade": (candidate.relevance_grade + 1) % 4}
                    )
                    for candidate in case.candidates
                )
            }
        )
    )

    assert original["v2"]["selected_candidate_ids"] == changed["v2"]["selected_candidate_ids"]
    assert original["v3"]["selected_candidate_ids"] == changed["v3"]["selected_candidate_ids"]


def test_ip_asset_ranker_freezes_v2_and_v3_lane_semantics() -> None:
    now = datetime(2026, 8, 31, tzinfo=UTC)
    candidates = (
        IpAssetRankCandidate(
            asset_ref="metadata-only",
            created_at=now,
            stable_id="1",
            metadata_rank=1,
            metadata_score=0.2,
        ),
        IpAssetRankCandidate(
            asset_ref="semantic-only",
            created_at=now,
            stable_id="2",
            semantic_rank=1,
            semantic_similarity=0.99,
        ),
        IpAssetRankCandidate(
            asset_ref="overlap",
            created_at=now,
            stable_id="3",
            metadata_rank=2,
            semantic_rank=2,
            metadata_score=0.1,
            semantic_similarity=0.1,
        ),
    )

    assert rank_ip_asset_candidates(candidates, version=IP_ASSET_SEARCH_V2_VERSION, limit=3) == (
        "semantic-only",
        "overlap",
        "metadata-only",
    )
    assert rank_ip_asset_candidates(candidates, version=IP_ASSET_SEARCH_V3_VERSION, limit=3) == (
        "overlap",
        "metadata-only",
        "semantic-only",
    )


def test_ip_asset_rrf_stable_tie_uses_created_at_then_identity() -> None:
    now = datetime(2026, 8, 31, tzinfo=UTC)
    candidates = tuple(
        IpAssetRankCandidate(
            asset_ref=asset_ref,
            created_at=now,
            stable_id=stable_id,
            metadata_rank=1,
            metadata_score=1.0,
        )
        for asset_ref, stable_id in (("older-id", "1"), ("newer-id", "2"))
    )

    assert rank_ip_asset_candidates(candidates, version=IP_ASSET_SEARCH_V3_VERSION, limit=2) == (
        "newer-id",
        "older-id",
    )


def test_ip_asset_eval_rejects_prohibited_identity_fields(tmp_path: Path) -> None:
    rows = [json.loads(line) for line in _case_lines()]
    rows[0]["candidates"][0]["profile_id"] = "forbidden"
    path = tmp_path / "unsafe.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    with pytest.raises(IpAssetRetrievalEvalDatasetError, match="prohibited identity"):
        load_eval_cases(path)


def test_ip_asset_eval_rejects_exact_priority_without_metadata_lane(tmp_path: Path) -> None:
    rows = [json.loads(line) for line in _case_lines()]
    rows[0]["exact_metadata_priority"] = True
    rows[0]["candidates"] = [
        {
            "candidate_id": "semantic-only",
            "semantic_rank": 1,
            "semantic_similarity": 0.9,
            "relevance_grade": 3,
        }
    ]
    path = tmp_path / "invalid-exact-priority.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    with pytest.raises(IpAssetRetrievalEvalDatasetError, match="invalid case"):
        load_eval_cases(path)


def test_ip_asset_retrieval_canonical_check_passes() -> None:
    assert main(["--check"]) == 0


def _case_lines() -> tuple[str, ...]:
    from evals.ip_asset_retrieval.dataset import DEFAULT_CASES_PATH

    return tuple(DEFAULT_CASES_PATH.read_text(encoding="utf-8").splitlines())
