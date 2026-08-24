from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from app.domain.brand_knowledge import (
    STRUCTURED_BRAND_RETRIEVAL_VERSION,
    BrandClaimScope,
    BrandContentType,
    fuse_brand_retrieval_score,
)
from evals.brand_retrieval.dataset import (
    BrandRetrievalEvalDatasetError,
    load_eval_cases,
)
from evals.brand_retrieval.metrics import score_track
from evals.brand_retrieval.reporting import canonical_json, render_markdown
from evals.brand_retrieval.runner import _score_observation, evaluate_path, main


def test_brand_retrieval_fixture_report_covers_balanced_relevance_and_safety() -> None:
    cases = load_eval_cases()
    report = evaluate_path()

    assert len(cases) == 36
    assert Counter(case.category for case in cases) == Counter(
        {category: 4 for category in BrandContentType}
    )
    assert report.aggregate.passed_count == report.aggregate.case_count == 36
    assert report.aggregate.legacy_v2.macro_recall_at_5 == 0.8
    assert report.aggregate.structured_v3.macro_recall_at_5 == 0.95
    assert report.aggregate.structured_v3.macro_mrr_at_5 == 1.0
    assert report.aggregate.structured_v3.macro_ndcg_at_5 == 0.928633
    assert report.aggregate.legacy_v2.macro_parent_diversity_at_5 == 0.85
    assert report.aggregate.structured_v3.macro_parent_diversity_at_5 == 1.0
    assert report.aggregate.parent_diversity_delta == 0.15
    assert report.aggregate.legacy_v2.verification_coverage == 1.0
    assert report.aggregate.structured_v3.verification_coverage == 1.0
    assert report.aggregate.legacy_v2.brand_as_fact_violation_count == 0
    assert report.aggregate.structured_v3.brand_as_fact_violation_count == 0


def test_brand_retrieval_report_is_stable_and_disclaims_live_semantic_quality() -> None:
    report = evaluate_path()

    assert canonical_json(report) == canonical_json(evaluate_path())
    markdown = render_markdown(report)
    assert "fixture observations" in markdown
    assert "not a live embedding recall" in markdown
    assert "Parent-diversity delta: `+0.150000`" in markdown


def test_brand_retrieval_oracle_is_not_used_to_construct_the_selected_order() -> None:
    case = load_eval_cases()[0]
    original = _score_observation(case)
    candidates = tuple(
        candidate.model_copy(
            update={
                "relevance_grade": 3
                if candidate.candidate_id.endswith("-c2")
                else candidate.relevance_grade
            }
        )
        for candidate in case.candidates
    )
    mismatched_oracle = case.model_copy(update={"candidates": candidates})

    changed = _score_observation(mismatched_oracle)

    assert (
        original.structured_v3.selected_candidate_ids
        == changed.structured_v3.selected_candidate_ids
    )
    assert changed.passed is False
    assert "structured_ndcg_regressed" in changed.failure_codes


def test_brand_retrieval_eval_detects_brand_as_fact_violation() -> None:
    case = load_eval_cases()[0]
    candidates = tuple(
        candidate.model_copy(update={"evidence_eligible": candidate.candidate_id.endswith("-c1")})
        for candidate in case.candidates
    )

    score = _score_observation(case.model_copy(update={"candidates": candidates}))

    assert score.passed is False
    assert score.legacy_v2.brand_as_fact_violation_count == 1
    assert score.structured_v3.brand_as_fact_violation_count == 1
    assert "brand_marked_as_fact_evidence" in score.failure_codes


def test_brand_retrieval_eval_detects_missing_external_claim_verification() -> None:
    case, external_id = next(
        (case, candidate.candidate_id)
        for case in load_eval_cases()
        for candidate in case.candidates
        if candidate.candidate_id
        in set(_score_observation(case).structured_v3.selected_candidate_ids)
        and candidate.claim_scope is BrandClaimScope.EXTERNAL_CLAIM
    )
    candidates = tuple(
        candidate.model_copy(update={"verification_required": False})
        if candidate.candidate_id == external_id
        else candidate
        for candidate in case.candidates
    )

    score = _score_observation(case.model_copy(update={"candidates": candidates}))

    assert score.passed is False
    assert score.structured_v3.verification_coverage < 1.0
    assert "external_claim_verification_missing" in score.failure_codes


def test_brand_retrieval_track_requires_exactly_five_unique_results() -> None:
    case = load_eval_cases()[0]

    with pytest.raises(ValueError, match="selected candidate IDs are invalid"):
        score_track(
            case=case,
            selected_candidate_ids=tuple(
                candidate.candidate_id for candidate in case.candidates[:4]
            ),
            retrieval_version=STRUCTURED_BRAND_RETRIEVAL_VERSION,
        )


def test_brand_retrieval_dataset_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    rows = [json.loads(line) for line in _case_lines()]
    rows[-1]["case_id"] = rows[0]["case_id"]
    path = tmp_path / "duplicate.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    with pytest.raises(BrandRetrievalEvalDatasetError, match="case IDs must be unique"):
        load_eval_cases(path)


def test_brand_retrieval_rrf_helper_preserves_frozen_weighted_formula() -> None:
    assert fuse_brand_retrieval_score(full_text_rank=1, vector_rank=2) == pytest.approx(
        0.45 / 61 + 0.55 / 62
    )
    assert fuse_brand_retrieval_score(full_text_rank=3, vector_rank=None) == pytest.approx(
        0.45 / 63
    )
    with pytest.raises(ValueError, match="at least one rank"):
        fuse_brand_retrieval_score(full_text_rank=None, vector_rank=None)
    with pytest.raises(ValueError, match="positive integers"):
        fuse_brand_retrieval_score(full_text_rank=0, vector_rank=1)


def test_brand_retrieval_canonical_check_passes() -> None:
    assert main(["--check"]) == 0


def _case_lines() -> tuple[str, ...]:
    from evals.brand_retrieval.dataset import DEFAULT_CASES_PATH

    return tuple(DEFAULT_CASES_PATH.read_text(encoding="utf-8").splitlines())
