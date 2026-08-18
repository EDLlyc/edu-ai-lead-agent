"""Deterministic grading for digital-IP fixture contract conformance."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final, Literal

from app.domain.brand_knowledge import BrandDocumentKind
from app.domain.digital_ip import DigitalIpProfile
from pydantic import BaseModel, ConfigDict, Field

from .models import DigitalIpEvalCase, DigitalIpEvalCategory

REPORT_SCHEMA_VERSION: Final[Literal["digital-ip-eval-report-v1"]] = "digital-ip-eval-report-v1"
TRACK_NAME: Final[Literal["fixture_contract_conformance"]] = "fixture_contract_conformance"
TRACK_DISCLAIMER = (
    "This deterministic fixture report measures versioned projection contracts only; it is not "
    "a live embedding, retrieval, model-accuracy, or production-quality score."
)


class _ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DigitalIpCaseScore(_ReportModel):
    case_id: str
    category: DigitalIpEvalCategory
    passed: bool
    expected_type_count: int = Field(ge=0)
    matched_type_count: int = Field(ge=0)
    expected_tag_count: int = Field(ge=0)
    matched_tag_count: int = Field(ge=0)
    prohibited_rule_required: bool
    prohibited_rule_hit: bool
    brand_as_fact_count: int = Field(ge=0)
    failure_codes: tuple[str, ...]


class DigitalIpAggregateScore(_ReportModel):
    case_count: int = Field(ge=1)
    passed_count: int = Field(ge=0)
    expected_type_coverage: float = Field(ge=0, le=1)
    expected_tag_coverage: float = Field(ge=0, le=1)
    prohibited_rule_required_count: int = Field(ge=0)
    prohibited_rule_hit_count: int = Field(ge=0)
    prohibited_rule_hit_rate: float = Field(ge=0, le=1)
    brand_as_fact_count: int = Field(ge=0)
    failed_case_ids: tuple[str, ...]


class DigitalIpEvalReport(_ReportModel):
    schema_version: Literal["digital-ip-eval-report-v1"]
    track: Literal["fixture_contract_conformance"]
    disclaimer: str
    dataset_version: str
    aggregate: DigitalIpAggregateScore
    cases: tuple[DigitalIpCaseScore, ...]


def score_case(case: DigitalIpEvalCase, profile: DigitalIpProfile) -> DigitalIpCaseScore:
    actual_kinds = set(profile.document_kinds)
    expected_kinds = set(case.expected_document_kinds)
    expected_tags = set(
        (*case.expected_tone_tags, *case.expected_safety_tags, *case.expected_visual_tags)
    )
    actual_tags = set((*profile.tone_tags, *profile.safety_tags, *profile.visual_tags))
    expected_characters = set(case.expected_visual_characters)
    actual_characters = {
        character for asset in profile.visual_assets for character in asset.characters
    }
    matched_type_count = len(expected_kinds.intersection(actual_kinds))
    matched_tag_count = len(expected_tags.intersection(actual_tags)) + len(
        expected_characters.intersection(actual_characters)
    )
    expected_tag_count = len(expected_tags) + len(expected_characters)
    prohibited_hit = (
        BrandDocumentKind.PROHIBITED_LANGUAGE in actual_kinds
        if case.prohibited_rule_required
        else True
    )
    brand_as_fact_count = int(profile.evidence_eligible)
    failures: list[str] = []
    if matched_type_count != len(expected_kinds):
        failures.append("expected_document_kind_missing")
    if matched_tag_count != expected_tag_count:
        failures.append("expected_tag_missing")
    if not prohibited_hit:
        failures.append("prohibited_rule_missing")
    if brand_as_fact_count:
        failures.append("brand_marked_as_fact_evidence")
    return DigitalIpCaseScore(
        case_id=case.case_id,
        category=case.category,
        passed=not failures,
        expected_type_count=len(expected_kinds),
        matched_type_count=matched_type_count,
        expected_tag_count=expected_tag_count,
        matched_tag_count=matched_tag_count,
        prohibited_rule_required=case.prohibited_rule_required,
        prohibited_rule_hit=prohibited_hit,
        brand_as_fact_count=brand_as_fact_count,
        failure_codes=tuple(failures),
    )


def build_report(
    *, dataset_version: str, scores: Sequence[DigitalIpCaseScore]
) -> DigitalIpEvalReport:
    ordered = tuple(sorted(scores, key=lambda score: score.case_id))
    if not ordered:
        raise ValueError("digital IP eval requires at least one score")
    type_expected = sum(score.expected_type_count for score in ordered)
    type_matched = sum(score.matched_type_count for score in ordered)
    tag_expected = sum(score.expected_tag_count for score in ordered)
    tag_matched = sum(score.matched_tag_count for score in ordered)
    prohibited_scores = tuple(
        score for score in ordered if score.category is DigitalIpEvalCategory.PROHIBITED_LANGUAGE
    )
    aggregate = DigitalIpAggregateScore(
        case_count=len(ordered),
        passed_count=sum(score.passed for score in ordered),
        expected_type_coverage=_ratio(type_matched, type_expected),
        expected_tag_coverage=_ratio(tag_matched, tag_expected),
        prohibited_rule_required_count=len(prohibited_scores),
        prohibited_rule_hit_count=sum(score.prohibited_rule_hit for score in prohibited_scores),
        prohibited_rule_hit_rate=_mean(score.prohibited_rule_hit for score in prohibited_scores),
        brand_as_fact_count=sum(score.brand_as_fact_count for score in ordered),
        failed_case_ids=tuple(score.case_id for score in ordered if not score.passed),
    )
    return DigitalIpEvalReport(
        schema_version=REPORT_SCHEMA_VERSION,
        track=TRACK_NAME,
        disclaimer=TRACK_DISCLAIMER,
        dataset_version=dataset_version,
        aggregate=aggregate,
        cases=ordered,
    )


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else round(numerator / denominator, 6)


def _mean(values: Iterable[bool]) -> float:
    materialized = tuple(values)
    return 1.0 if not materialized else round(sum(materialized) / len(materialized), 6)
