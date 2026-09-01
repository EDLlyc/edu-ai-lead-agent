"""Explainable metrics for the provider-free image-quality policy track."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Literal

from app.domain.image_quality_eval import (
    IMAGE_EVAL_DECISION_POLICY_VERSION,
    ImageEvalCase,
    ImageEvalDecisionKind,
    ImageEvalDimension,
    ImageEvalFixtureKind,
    ImageEvalIssueCode,
    ImageEvalObservation,
    ImageEvalObservationStatus,
    ImageEvalRubric,
    ImageEvalSeverity,
    decide_image_eval,
    issue_contract,
)
from pydantic import BaseModel, ConfigDict, Field

REPORT_SCHEMA_VERSION = "image-quality-eval-report-v1"
REPORT_TRACK = "frozen_observation_policy_contract"
REPORT_DISCLAIMER = (
    "This provider-free baseline measures strict schema, metric aggregation, and decision-policy "
    "conformance on sanitized hand-authored fixtures. It does not measure live model quality, "
    "human agreement, production effectiveness, or calibrated image-quality thresholds."
)


class _ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ImageEvalCaseScore(_ReportModel):
    case_id: str
    dimension: ImageEvalDimension
    fixture_kind: ImageEvalFixtureKind
    expected_decision: ImageEvalDecisionKind
    actual_decision: ImageEvalDecisionKind
    expected_issue_codes: tuple[ImageEvalIssueCode, ...]
    actual_issue_codes: tuple[ImageEvalIssueCode, ...]
    matched_expected_decision: bool
    matched_expected_issues: bool
    passed: bool
    failure_codes: tuple[str, ...]


class ImageEvalDimensionScore(_ReportModel):
    dimension: ImageEvalDimension
    case_count: int = Field(ge=1)
    available_observation_count: int = Field(ge=0)
    observation_coverage: float = Field(ge=0, le=1)
    gold_defect_case_count: int = Field(ge=0)
    predicted_defect_case_count: int = Field(ge=0)
    defect_precision: float = Field(ge=0, le=1)
    defect_recall: float = Field(ge=0, le=1)
    defect_f1: float = Field(ge=0, le=1)
    critical_gold_case_count: int = Field(ge=0)
    false_pass_count: int = Field(ge=0)
    false_pass_rate: float = Field(ge=0, le=1)
    manual_review_count: int = Field(ge=0)
    manual_review_rate: float = Field(ge=0, le=1)


class ImageEvalAggregateScore(_ReportModel):
    case_count: int = Field(ge=1)
    passed_count: int = Field(ge=0)
    failed_case_ids: tuple[str, ...]
    critical_gold_case_count: int = Field(ge=0)
    critical_predicted_case_count: int = Field(ge=0)
    critical_true_positive_count: int = Field(ge=0)
    critical_precision: float = Field(ge=0, le=1)
    critical_recall: float = Field(ge=0, le=1)
    critical_f1: float = Field(ge=0, le=1)
    false_pass_count: int = Field(ge=0)
    false_pass_rate: float = Field(ge=0, le=1)
    manual_review_count: int = Field(ge=0)
    manual_review_rate: float = Field(ge=0, le=1)
    unavailable_count: int = Field(ge=0)
    unavailable_rate: float = Field(ge=0, le=1)


class ImageEvalFixtureDistribution(_ReportModel):
    fixture_kind: ImageEvalFixtureKind
    case_count: int = Field(ge=0)


class ImageQualityEvalReport(_ReportModel):
    schema_version: Literal["image-quality-eval-report-v1"]
    track: Literal["frozen_observation_policy_contract"]
    disclaimer: str
    dataset_version: str
    dataset_sha256: str = Field(min_length=64, max_length=64)
    rubric_version: str
    rubric_sha256: str = Field(min_length=64, max_length=64)
    decision_policy_version: str
    fixture_distribution: tuple[ImageEvalFixtureDistribution, ...]
    aggregate: ImageEvalAggregateScore
    dimensions: tuple[ImageEvalDimensionScore, ...]
    cases: tuple[ImageEvalCaseScore, ...]


def score_case(
    case: ImageEvalCase,
    observation: ImageEvalObservation,
    rubric: ImageEvalRubric,
) -> ImageEvalCaseScore:
    """Compare one frozen observation with evaluator-only gold labels."""

    decision = decide_image_eval(observation, rubric)
    expected_issues = tuple(sorted(case.gold_issue_codes, key=str))
    actual_issues = tuple(sorted((issue.code for issue in observation.issues), key=str))
    decision_match = decision.decision is case.expected_decision
    issues_match = actual_issues == expected_issues
    failures: list[str] = []
    if not decision_match:
        failures.append(
            f"decision_mismatch:expected={case.expected_decision.value}:"
            f"actual={decision.decision.value}"
        )
    if not issues_match:
        failures.append(
            "issue_mismatch:expected="
            + ",".join(code.value for code in expected_issues)
            + ":actual="
            + ",".join(code.value for code in actual_issues)
        )
    return ImageEvalCaseScore(
        case_id=case.case_id,
        dimension=case.dimension,
        fixture_kind=case.fixture_kind,
        expected_decision=case.expected_decision,
        actual_decision=decision.decision,
        expected_issue_codes=expected_issues,
        actual_issue_codes=actual_issues,
        matched_expected_decision=decision_match,
        matched_expected_issues=issues_match,
        passed=decision_match and issues_match,
        failure_codes=tuple(failures),
    )


def build_report(
    *,
    cases: Sequence[ImageEvalCase],
    observations: Sequence[ImageEvalObservation],
    rubric: ImageEvalRubric,
    dataset_sha256: str,
    rubric_sha256: str,
) -> ImageQualityEvalReport:
    if not cases:
        raise ValueError("image quality eval requires at least one case")
    observation_by_subject = {item.subject_ref: item for item in observations}
    ordered_cases = tuple(sorted(cases, key=lambda item: item.case_id))
    scores = tuple(
        score_case(case, observation_by_subject[case.case_id], rubric) for case in ordered_cases
    )
    dimensions = tuple(
        _score_dimension(
            dimension=dimension,
            cases=tuple(case for case in ordered_cases if case.dimension is dimension),
            observations=observation_by_subject,
            scores=scores,
        )
        for dimension in ImageEvalDimension
    )
    aggregate = _aggregate(ordered_cases, observation_by_subject, scores)
    distribution = Counter(case.fixture_kind for case in ordered_cases)
    return ImageQualityEvalReport(
        schema_version=REPORT_SCHEMA_VERSION,
        track=REPORT_TRACK,
        disclaimer=REPORT_DISCLAIMER,
        dataset_version="image-quality-eval-dataset-v1",
        dataset_sha256=dataset_sha256,
        rubric_version=rubric.rubric_version,
        rubric_sha256=rubric_sha256,
        decision_policy_version=IMAGE_EVAL_DECISION_POLICY_VERSION,
        fixture_distribution=tuple(
            ImageEvalFixtureDistribution(fixture_kind=kind, case_count=distribution[kind])
            for kind in ImageEvalFixtureKind
        ),
        aggregate=aggregate,
        dimensions=dimensions,
        cases=scores,
    )


def _score_dimension(
    *,
    dimension: ImageEvalDimension,
    cases: Sequence[ImageEvalCase],
    observations: Mapping[str, ImageEvalObservation],
    scores: Sequence[ImageEvalCaseScore],
) -> ImageEvalDimensionScore:
    dimension_scores = tuple(score for score in scores if score.dimension is dimension)
    gold_defects = {case.case_id for case in cases if case.gold_issue_codes}
    predicted_defects = {score.case_id for score in dimension_scores if score.actual_issue_codes}
    true_positives = gold_defects.intersection(predicted_defects)
    critical_gold = {case.case_id for case in cases if _has_critical(case.gold_issue_codes)}
    false_passes = {
        score.case_id
        for score in dimension_scores
        if score.case_id in critical_gold
        and score.actual_decision is ImageEvalDecisionKind.ACCEPTED
    }
    manual = {
        score.case_id
        for score in dimension_scores
        if score.actual_decision
        in {ImageEvalDecisionKind.MANUAL_REVIEW, ImageEvalDecisionKind.UNAVAILABLE}
    }
    available_count = sum(
        observations[case.case_id].status is ImageEvalObservationStatus.AVAILABLE for case in cases
    )
    precision = _ratio(len(true_positives), len(predicted_defects))
    recall = _ratio(len(true_positives), len(gold_defects))
    return ImageEvalDimensionScore(
        dimension=dimension,
        case_count=len(cases),
        available_observation_count=available_count,
        observation_coverage=_ratio(available_count, len(cases)),
        gold_defect_case_count=len(gold_defects),
        predicted_defect_case_count=len(predicted_defects),
        defect_precision=precision,
        defect_recall=recall,
        defect_f1=_f1(precision, recall),
        critical_gold_case_count=len(critical_gold),
        false_pass_count=len(false_passes),
        false_pass_rate=_ratio(len(false_passes), len(critical_gold)),
        manual_review_count=len(manual),
        manual_review_rate=_ratio(len(manual), len(cases)),
    )


def _aggregate(
    cases: Sequence[ImageEvalCase],
    observations: Mapping[str, ImageEvalObservation],
    scores: Sequence[ImageEvalCaseScore],
) -> ImageEvalAggregateScore:
    critical_gold = {case.case_id for case in cases if _has_critical(case.gold_issue_codes)}
    critical_predicted = {
        case.case_id
        for case in cases
        if any(
            issue.severity is ImageEvalSeverity.CRITICAL
            for issue in observations[case.case_id].issues
        )
    }
    critical_true_positive = critical_gold.intersection(critical_predicted)
    false_passes = {
        score.case_id
        for score in scores
        if score.case_id in critical_gold
        and score.actual_decision is ImageEvalDecisionKind.ACCEPTED
    }
    manual = {
        score.case_id
        for score in scores
        if score.actual_decision
        in {ImageEvalDecisionKind.MANUAL_REVIEW, ImageEvalDecisionKind.UNAVAILABLE}
    }
    unavailable = {
        score.case_id
        for score in scores
        if score.actual_decision is ImageEvalDecisionKind.UNAVAILABLE
    }
    precision = _ratio(len(critical_true_positive), len(critical_predicted))
    recall = _ratio(len(critical_true_positive), len(critical_gold))
    return ImageEvalAggregateScore(
        case_count=len(cases),
        passed_count=sum(score.passed for score in scores),
        failed_case_ids=tuple(score.case_id for score in scores if not score.passed),
        critical_gold_case_count=len(critical_gold),
        critical_predicted_case_count=len(critical_predicted),
        critical_true_positive_count=len(critical_true_positive),
        critical_precision=precision,
        critical_recall=recall,
        critical_f1=_f1(precision, recall),
        false_pass_count=len(false_passes),
        false_pass_rate=_ratio(len(false_passes), len(critical_gold)),
        manual_review_count=len(manual),
        manual_review_rate=_ratio(len(manual), len(cases)),
        unavailable_count=len(unavailable),
        unavailable_rate=_ratio(len(unavailable), len(cases)),
    )


def _has_critical(codes: Sequence[ImageEvalIssueCode]) -> bool:
    return any(issue_contract(code)[1] is ImageEvalSeverity.CRITICAL for code in codes)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return round(numerator / denominator, 6)


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 6)
