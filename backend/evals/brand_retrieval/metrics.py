"""Deterministic relevance, diversity, and safety metrics for brand retrieval."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Final, Literal

from app.domain.brand_knowledge import (
    LEGACY_BRAND_RETRIEVAL_VERSION,
    STRUCTURED_BRAND_RETRIEVAL_VERSION,
    BrandClaimScope,
    BrandContentType,
)
from pydantic import BaseModel, ConfigDict, Field

from .models import BrandRetrievalEvalCase

REPORT_SCHEMA_VERSION: Final[Literal["brand-retrieval-eval-report-v1"]] = (
    "brand-retrieval-eval-report-v1"
)
REPORT_TRACK: Final[Literal["fixture_retrieval_policy_regression"]] = (
    "fixture_retrieval_policy_regression"
)
REPORT_DISCLAIMER = (
    "This provider-free report measures deterministic RRF and diversity-policy behavior on "
    "sanitized fixture observations. It is not a live embedding recall, private-corpus quality, "
    "generation-quality, or production-effectiveness claim."
)
TOP_K: Final[Literal[5]] = 5


class _ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BrandRetrievalTrackScore(_ReportModel):
    retrieval_version: str
    recall_at_5: float = Field(ge=0, le=1)
    mrr_at_5: float = Field(ge=0, le=1)
    ndcg_at_5: float = Field(ge=0, le=1)
    parent_diversity_at_5: float = Field(ge=0, le=1)
    verification_coverage: float = Field(ge=0, le=1)
    brand_as_fact_violation_count: int = Field(ge=0)
    selected_candidate_ids: tuple[str, ...]


class BrandRetrievalCaseScore(_ReportModel):
    case_id: str
    category: BrandContentType
    passed: bool
    legacy_v2: BrandRetrievalTrackScore
    structured_v3: BrandRetrievalTrackScore
    failure_codes: tuple[str, ...]


class BrandRetrievalAggregateTrack(_ReportModel):
    retrieval_version: str
    macro_recall_at_5: float = Field(ge=0, le=1)
    macro_mrr_at_5: float = Field(ge=0, le=1)
    macro_ndcg_at_5: float = Field(ge=0, le=1)
    macro_parent_diversity_at_5: float = Field(ge=0, le=1)
    verification_coverage: float = Field(ge=0, le=1)
    brand_as_fact_violation_count: int = Field(ge=0)


class BrandRetrievalAggregateScore(_ReportModel):
    case_count: int = Field(ge=1)
    passed_count: int = Field(ge=0)
    legacy_v2: BrandRetrievalAggregateTrack
    structured_v3: BrandRetrievalAggregateTrack
    parent_diversity_delta: float = Field(ge=-1, le=1)
    failed_case_ids: tuple[str, ...]


class BrandRetrievalEvalReport(_ReportModel):
    schema_version: Literal["brand-retrieval-eval-report-v1"]
    track: Literal["fixture_retrieval_policy_regression"]
    disclaimer: str
    dataset_version: str
    top_k: Literal[5]
    aggregate: BrandRetrievalAggregateScore
    cases: tuple[BrandRetrievalCaseScore, ...]


def score_track(
    *,
    case: BrandRetrievalEvalCase,
    selected_candidate_ids: Sequence[str],
    retrieval_version: str,
) -> BrandRetrievalTrackScore:
    by_id = {candidate.candidate_id: candidate for candidate in case.candidates}
    if len(selected_candidate_ids) != TOP_K or len(selected_candidate_ids) != len(
        set(selected_candidate_ids)
    ):
        raise ValueError("selected candidate IDs are invalid")
    try:
        selected = tuple(by_id[candidate_id] for candidate_id in selected_candidate_ids)
    except KeyError as exc:
        raise ValueError("selected candidate ID is not in the eval observation") from exc

    relevant_total = sum(candidate.relevance_grade > 0 for candidate in case.candidates)
    relevant_selected = sum(candidate.relevance_grade > 0 for candidate in selected)
    recall = _ratio(relevant_selected, relevant_total)
    reciprocal_rank = 0.0
    for rank, candidate in enumerate(selected, start=1):
        if candidate.relevance_grade > 0:
            reciprocal_rank = 1.0 / rank
            break
    gains = tuple(candidate.relevance_grade for candidate in selected)
    ideal_gains = tuple(
        sorted((candidate.relevance_grade for candidate in case.candidates), reverse=True)[:TOP_K]
    )
    ndcg = _ratio(_dcg(gains), _dcg(ideal_gains))
    parent_count = len({candidate.section_key for candidate in selected})
    parent_diversity = _ratio(parent_count, len(selected))
    external = tuple(
        candidate
        for candidate in selected
        if candidate.claim_scope is BrandClaimScope.EXTERNAL_CLAIM
    )
    verification_coverage = _ratio(
        sum(candidate.verification_required for candidate in external), len(external)
    )
    return BrandRetrievalTrackScore(
        retrieval_version=retrieval_version,
        recall_at_5=_rounded(recall),
        mrr_at_5=_rounded(reciprocal_rank),
        ndcg_at_5=_rounded(ndcg),
        parent_diversity_at_5=_rounded(parent_diversity),
        verification_coverage=_rounded(verification_coverage),
        brand_as_fact_violation_count=sum(candidate.evidence_eligible for candidate in selected),
        selected_candidate_ids=tuple(selected_candidate_ids),
    )


def score_case(
    *,
    case: BrandRetrievalEvalCase,
    legacy_ids: Sequence[str],
    structured_ids: Sequence[str],
) -> BrandRetrievalCaseScore:
    legacy = score_track(
        case=case,
        selected_candidate_ids=legacy_ids,
        retrieval_version=LEGACY_BRAND_RETRIEVAL_VERSION,
    )
    structured = score_track(
        case=case,
        selected_candidate_ids=structured_ids,
        retrieval_version=STRUCTURED_BRAND_RETRIEVAL_VERSION,
    )
    failures: list[str] = []
    if structured.recall_at_5 < legacy.recall_at_5:
        failures.append("structured_recall_regressed")
    if structured.mrr_at_5 < legacy.mrr_at_5:
        failures.append("structured_mrr_regressed")
    if structured.ndcg_at_5 < legacy.ndcg_at_5:
        failures.append("structured_ndcg_regressed")
    if legacy.verification_coverage != 1.0 or structured.verification_coverage != 1.0:
        failures.append("external_claim_verification_missing")
    if legacy.brand_as_fact_violation_count or structured.brand_as_fact_violation_count:
        failures.append("brand_marked_as_fact_evidence")
    return BrandRetrievalCaseScore(
        case_id=case.case_id,
        category=case.category,
        passed=not failures,
        legacy_v2=legacy,
        structured_v3=structured,
        failure_codes=tuple(failures),
    )


def build_report(
    *, dataset_version: str, scores: Sequence[BrandRetrievalCaseScore]
) -> BrandRetrievalEvalReport:
    ordered = tuple(sorted(scores, key=lambda score: score.case_id))
    if not ordered:
        raise ValueError("brand retrieval eval requires at least one score")
    legacy = _aggregate_track(tuple(score.legacy_v2 for score in ordered))
    structured = _aggregate_track(tuple(score.structured_v3 for score in ordered))
    aggregate = BrandRetrievalAggregateScore(
        case_count=len(ordered),
        passed_count=sum(score.passed for score in ordered),
        legacy_v2=legacy,
        structured_v3=structured,
        parent_diversity_delta=_rounded(
            structured.macro_parent_diversity_at_5 - legacy.macro_parent_diversity_at_5
        ),
        failed_case_ids=tuple(score.case_id for score in ordered if not score.passed),
    )
    return BrandRetrievalEvalReport(
        schema_version=REPORT_SCHEMA_VERSION,
        track=REPORT_TRACK,
        disclaimer=REPORT_DISCLAIMER,
        dataset_version=dataset_version,
        top_k=TOP_K,
        aggregate=aggregate,
        cases=ordered,
    )


def _aggregate_track(
    scores: Sequence[BrandRetrievalTrackScore],
) -> BrandRetrievalAggregateTrack:
    if not scores:
        raise ValueError("brand retrieval aggregate requires at least one track score")
    retrieval_version = scores[0].retrieval_version
    if any(score.retrieval_version != retrieval_version for score in scores):
        raise ValueError("brand retrieval aggregate cannot mix retrieval versions")
    # Coverage is already case-normalized, including the no-external-claim identity of 1.0.
    verification_coverage = _mean(tuple(score.verification_coverage for score in scores))
    return BrandRetrievalAggregateTrack(
        retrieval_version=retrieval_version,
        macro_recall_at_5=_mean(tuple(score.recall_at_5 for score in scores)),
        macro_mrr_at_5=_mean(tuple(score.mrr_at_5 for score in scores)),
        macro_ndcg_at_5=_mean(tuple(score.ndcg_at_5 for score in scores)),
        macro_parent_diversity_at_5=_mean(tuple(score.parent_diversity_at_5 for score in scores)),
        verification_coverage=verification_coverage,
        brand_as_fact_violation_count=sum(score.brand_as_fact_violation_count for score in scores),
    )


def _dcg(grades: Sequence[int]) -> float:
    return float(
        sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1))
    )


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return 1.0 if denominator == 0 else float(numerator / denominator)


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("metric mean requires at least one value")
    return _rounded(sum(values) / len(values))


def _rounded(value: float) -> float:
    return round(value, 6)
