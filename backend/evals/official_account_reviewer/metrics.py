"""Honest metrics for the provider-free Reviewer contract track."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Final, Literal

from app.domain.official_account_reviewer import (
    REPAIR_POLICY_VERSION,
    REVIEW_POLICY_VERSION,
    REVIEW_RUBRIC_VERSION,
    ReviewContractError,
    ReviewDecision,
    ReviewDimension,
    ReviewIssueCode,
    ReviewIssueSource,
    ReviewSeverity,
    ReviewVerdict,
    build_review_request,
    issue_contract,
    project_repair_directives,
)
from pydantic import BaseModel, ConfigDict, Field

from .models import ReviewEvalCase, ReviewEvalOracle, ReviewFixtureKind
from .policy import FIXTURE_POLICY_VERSION, FIXTURE_PROMPT_VERSION, FIXTURE_REVIEWER_VERSION

REPORT_SCHEMA_VERSION: Final[Literal["official-account-review-eval-report-v1"]] = (
    "official-account-review-eval-report-v1"
)
REPORT_TRACK: Final[Literal["provider_free_fixture_contract"]] = "provider_free_fixture_contract"
REPORT_DISCLAIMER = (
    "This provider-free, hand-authored fixture track measures closed-schema, input-binding, "
    "hard-gate, repair-policy, and metric-pipeline conformance. It does not measure live Reviewer "
    "accuracy, human agreement, production uplift, model quality, or online safety effectiveness."
)


class _ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewEvalCaseScore(_ReportModel):
    case_id: str
    dimension: ReviewDimension
    fixture_kind: ReviewFixtureKind
    expected_decision: ReviewDecision
    actual_decision: ReviewDecision
    expected_issue_codes: tuple[ReviewIssueCode, ...]
    actual_issue_codes: tuple[ReviewIssueCode, ...]
    expected_repair_issue_codes: tuple[ReviewIssueCode, ...]
    actual_repair_issue_codes: tuple[ReviewIssueCode, ...]
    issue_precision: float = Field(ge=0, le=1)
    issue_recall: float = Field(ge=0, le=1)
    location_accuracy: float = Field(ge=0, le=1)
    repairability_matched: bool
    hard_gate_override_passed: bool
    passed: bool
    failure_codes: tuple[str, ...]


class ReviewDimensionScore(_ReportModel):
    dimension: ReviewDimension
    case_count: int = Field(ge=1)
    defect_case_count: int = Field(ge=0)
    defect_precision: float = Field(ge=0, le=1)
    defect_recall: float = Field(ge=0, le=1)
    defect_f1: float = Field(ge=0, le=1)
    failed_case_ids: tuple[str, ...]


class ReviewEvalAggregateScore(_ReportModel):
    case_count: int = Field(ge=1)
    passed_count: int = Field(ge=0)
    failed_case_ids: tuple[str, ...]
    critical_expected_count: int = Field(ge=0)
    critical_predicted_count: int = Field(ge=0)
    critical_true_positive_count: int = Field(ge=0)
    critical_precision: float = Field(ge=0, le=1)
    critical_recall: float = Field(ge=0, le=1)
    critical_f1: float = Field(ge=0, le=1)
    false_accept_count: int = Field(ge=0)
    false_accept_rate: float = Field(ge=0, le=1)
    false_reject_count: int = Field(ge=0)
    false_reject_rate: float = Field(ge=0, le=1)
    manual_review_count: int = Field(ge=0)
    manual_review_rate: float = Field(ge=0, le=1)
    unavailable_count: int = Field(ge=0)
    unavailable_rate: float = Field(ge=0, le=1)
    repairability_accuracy: float = Field(ge=0, le=1)
    location_accuracy: float = Field(ge=0, le=1)
    hard_gate_override_case_count: int = Field(ge=0)
    hard_gate_override_violation_count: int = Field(ge=0)


class ReviewFixtureDistribution(_ReportModel):
    fixture_kind: ReviewFixtureKind
    case_count: int = Field(ge=0)


class OfficialAccountReviewEvalReport(_ReportModel):
    schema_version: Literal["official-account-review-eval-report-v1"]
    track: Literal["provider_free_fixture_contract"]
    disclaimer: str
    provider_free: Literal[True]
    live_model_calls: Literal[0]
    dataset_version: str
    cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    oracle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric_version: str
    rubric_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_policy_version: str
    repair_policy_version: str
    fixture_policy_version: str
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runner_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_distribution: tuple[ReviewFixtureDistribution, ...]
    aggregate: ReviewEvalAggregateScore
    dimensions: tuple[ReviewDimensionScore, ...]
    cases: tuple[ReviewEvalCaseScore, ...]


def score_case(
    case: ReviewEvalCase,
    oracle: ReviewEvalOracle,
    verdict: ReviewVerdict,
) -> ReviewEvalCaseScore:
    expected_issue_keys = {
        (item.code, tuple((ref.kind, ref.ref) for ref in item.references))
        for item in oracle.expected_issues
    }
    actual_issue_keys = {
        (item.code, tuple((ref.kind, ref.ref) for ref in item.references))
        for item in verdict.issues
    }
    expected_codes = tuple(sorted((item.code for item in oracle.expected_issues), key=str))
    actual_codes = tuple(sorted((item.code for item in verdict.issues), key=str))
    issue_tp = expected_issue_keys.intersection(actual_issue_keys)
    issue_precision = _ratio(len(issue_tp), len(actual_issue_keys))
    issue_recall = _ratio(len(issue_tp), len(expected_issue_keys))
    location_accuracy = _ratio(len(issue_tp), len(expected_issue_keys))
    request = build_review_request(
        request_id=f"request:{case.case_id}",
        identity=case.identity,
        reviewer_version=FIXTURE_REVIEWER_VERSION,
        prompt_version=FIXTURE_PROMPT_VERSION,
        hard_gate_failures=case.hard_gate_failures,
    )
    binding_valid = True
    try:
        actual_repair_codes = tuple(
            item.issue_code for item in project_repair_directives(request, verdict)
        )
    except ReviewContractError:
        binding_valid = False
        actual_repair_codes = ()
    repairability_matched = actual_repair_codes == oracle.expected_repair_issue_codes
    expected_hard_gate_keys = expected_issue_keys if oracle.expected_hard_gate_override else set()
    actual_hard_gate_keys = {
        (item.code, tuple((ref.kind, ref.ref) for ref in item.references))
        for item in verdict.issues
        if item.source is ReviewIssueSource.HARD_GATE
    }
    hard_gate_passed = not oracle.expected_hard_gate_override or (
        verdict.decision is ReviewDecision.REJECTED
        and expected_hard_gate_keys.issubset(actual_hard_gate_keys)
    )
    failures: list[str] = []
    if not binding_valid:
        failures.append("input_binding_violation")
    if verdict.decision is not oracle.expected_decision:
        failures.append(
            f"decision_mismatch:expected={oracle.expected_decision.value}:"
            f"actual={verdict.decision.value}"
        )
    if actual_codes != expected_codes:
        failures.append("issue_code_mismatch")
    if actual_issue_keys != expected_issue_keys:
        failures.append("issue_reference_mismatch")
    if not repairability_matched:
        failures.append("repairability_mismatch")
    if not hard_gate_passed:
        failures.append("hard_gate_override_violation")
    return ReviewEvalCaseScore(
        case_id=case.case_id,
        dimension=case.focus_dimension,
        fixture_kind=case.fixture_kind,
        expected_decision=oracle.expected_decision,
        actual_decision=verdict.decision,
        expected_issue_codes=expected_codes,
        actual_issue_codes=actual_codes,
        expected_repair_issue_codes=oracle.expected_repair_issue_codes,
        actual_repair_issue_codes=actual_repair_codes,
        issue_precision=issue_precision,
        issue_recall=issue_recall,
        location_accuracy=location_accuracy,
        repairability_matched=repairability_matched,
        hard_gate_override_passed=hard_gate_passed,
        passed=not failures,
        failure_codes=tuple(failures),
    )


def build_report(
    *,
    cases: Sequence[ReviewEvalCase],
    oracles: Sequence[ReviewEvalOracle],
    verdicts: Mapping[str, ReviewVerdict],
    dataset_version: str,
    cases_sha256: str,
    oracle_sha256: str,
    rubric_sha256: str,
    policy_sha256: str,
    runner_sha256: str,
) -> OfficialAccountReviewEvalReport:
    if not cases:
        raise ValueError("review eval requires at least one case")
    oracle_by_id = {item.case_id: item for item in oracles}
    ordered_cases = tuple(sorted(cases, key=lambda item: item.case_id))
    scores = tuple(
        score_case(case, oracle_by_id[case.case_id], verdicts[case.case_id])
        for case in ordered_cases
    )
    dimensions = tuple(
        _score_dimension(
            dimension,
            tuple(case for case in ordered_cases if case.focus_dimension is dimension),
            scores,
        )
        for dimension in ReviewDimension
    )
    distribution = Counter(case.fixture_kind for case in ordered_cases)
    return OfficialAccountReviewEvalReport(
        schema_version=REPORT_SCHEMA_VERSION,
        track=REPORT_TRACK,
        disclaimer=REPORT_DISCLAIMER,
        provider_free=True,
        live_model_calls=0,
        dataset_version=dataset_version,
        cases_sha256=cases_sha256,
        oracle_sha256=oracle_sha256,
        rubric_version=REVIEW_RUBRIC_VERSION,
        rubric_sha256=rubric_sha256,
        review_policy_version=REVIEW_POLICY_VERSION,
        repair_policy_version=REPAIR_POLICY_VERSION,
        fixture_policy_version=FIXTURE_POLICY_VERSION,
        policy_sha256=policy_sha256,
        runner_sha256=runner_sha256,
        fixture_distribution=tuple(
            ReviewFixtureDistribution(fixture_kind=kind, case_count=distribution[kind])
            for kind in ReviewFixtureKind
        ),
        aggregate=_aggregate(ordered_cases, oracle_by_id, verdicts, scores),
        dimensions=dimensions,
        cases=scores,
    )


def _score_dimension(
    dimension: ReviewDimension,
    cases: Sequence[ReviewEvalCase],
    scores: Sequence[ReviewEvalCaseScore],
) -> ReviewDimensionScore:
    case_ids = {case.case_id for case in cases}
    dimension_scores = tuple(score for score in scores if score.case_id in case_ids)
    expected_defects = {score.case_id for score in dimension_scores if score.expected_issue_codes}
    predicted_defects = {score.case_id for score in dimension_scores if score.actual_issue_codes}
    true_positives = expected_defects.intersection(predicted_defects)
    precision = _ratio(len(true_positives), len(predicted_defects))
    recall = _ratio(len(true_positives), len(expected_defects))
    return ReviewDimensionScore(
        dimension=dimension,
        case_count=len(cases),
        defect_case_count=len(expected_defects),
        defect_precision=precision,
        defect_recall=recall,
        defect_f1=_f1(precision, recall),
        failed_case_ids=tuple(score.case_id for score in dimension_scores if not score.passed),
    )


def _aggregate(
    cases: Sequence[ReviewEvalCase],
    oracles: Mapping[str, ReviewEvalOracle],
    verdicts: Mapping[str, ReviewVerdict],
    scores: Sequence[ReviewEvalCaseScore],
) -> ReviewEvalAggregateScore:
    expected_critical = {
        (case.case_id, item.code)
        for case in cases
        for item in oracles[case.case_id].expected_issues
        if issue_contract(item.code).severity is ReviewSeverity.CRITICAL
    }
    predicted_critical = {
        (case.case_id, issue.code)
        for case in cases
        for issue in verdicts[case.case_id].issues
        if issue.severity is ReviewSeverity.CRITICAL
    }
    critical_tp = expected_critical.intersection(predicted_critical)
    critical_precision = _ratio(len(critical_tp), len(predicted_critical))
    critical_recall = _ratio(len(critical_tp), len(expected_critical))
    expected_nonaccepted = {
        case.case_id
        for case in cases
        if oracles[case.case_id].expected_decision is not ReviewDecision.ACCEPTED
    }
    expected_accepted = {
        case.case_id
        for case in cases
        if oracles[case.case_id].expected_decision is ReviewDecision.ACCEPTED
    }
    false_accepts = {
        case_id
        for case_id in expected_nonaccepted
        if verdicts[case_id].decision is ReviewDecision.ACCEPTED
    }
    false_rejects = {
        case_id
        for case_id in expected_accepted
        if verdicts[case_id].decision is not ReviewDecision.ACCEPTED
    }
    manual_count = sum(
        verdict.decision is ReviewDecision.MANUAL_REVIEW for verdict in verdicts.values()
    )
    unavailable_count = sum(
        verdict.decision is ReviewDecision.UNAVAILABLE for verdict in verdicts.values()
    )
    override_scores = tuple(
        score for score in scores if oracles[score.case_id].expected_hard_gate_override
    )
    expected_location_count = sum(len(oracles[case.case_id].expected_issues) for case in cases)
    matched_location_count = sum(
        round(score.location_accuracy * len(oracles[score.case_id].expected_issues))
        for score in scores
    )
    return ReviewEvalAggregateScore(
        case_count=len(cases),
        passed_count=sum(score.passed for score in scores),
        failed_case_ids=tuple(score.case_id for score in scores if not score.passed),
        critical_expected_count=len(expected_critical),
        critical_predicted_count=len(predicted_critical),
        critical_true_positive_count=len(critical_tp),
        critical_precision=critical_precision,
        critical_recall=critical_recall,
        critical_f1=_f1(critical_precision, critical_recall),
        false_accept_count=len(false_accepts),
        false_accept_rate=_ratio(len(false_accepts), len(expected_nonaccepted)),
        false_reject_count=len(false_rejects),
        false_reject_rate=_ratio(len(false_rejects), len(expected_accepted)),
        manual_review_count=manual_count,
        manual_review_rate=_ratio(manual_count, len(cases)),
        unavailable_count=unavailable_count,
        unavailable_rate=_ratio(unavailable_count, len(cases)),
        repairability_accuracy=_ratio(
            sum(score.repairability_matched for score in scores), len(scores)
        ),
        location_accuracy=_ratio(matched_location_count, expected_location_count),
        hard_gate_override_case_count=len(override_scores),
        hard_gate_override_violation_count=sum(
            not score.hard_gate_override_passed for score in override_scores
        ),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 1.0


def _f1(precision: float, recall: float) -> float:
    return round(2 * precision * recall / (precision + recall), 6) if precision + recall else 0.0
