"""Strict case and evaluator-only oracle schemas for Reviewer evaluation."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from app.domain.official_account_reviewer import (
    BoundedIdentifier,
    ReviewDecision,
    ReviewDimension,
    ReviewHardGateFailure,
    ReviewInputIdentity,
    ReviewIssueCode,
    ReviewReference,
    issue_contract,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

CASE_SCHEMA_VERSION = "official-account-review-eval-case-v1"
ORACLE_SCHEMA_VERSION = "official-account-review-eval-oracle-v1"
DATASET_VERSION = "official-account-review-eval-dataset-v1"


class ReviewFixtureKind(StrEnum):
    POSITIVE = "positive"
    WARNING = "warning"
    REPAIRABLE = "repairable"
    HARD_NEGATIVE = "hard_negative"
    UNAVAILABLE = "unavailable"
    HARD_GATE_OVERRIDE = "hard_gate_override"


class FixtureProviderStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    INVALID_OUTPUT = "invalid_output"


class ReviewFixtureSignal(StrEnum):
    CLAIM_CONTEXT_UNCLEAR = "claim_context_unclear"
    TONE_DEPARTS_BRAND = "tone_departs_brand"
    TONE_CONTEXT_UNCLEAR = "tone_context_unclear"
    HEADING_LEVELS_SKIP = "heading_levels_skip"
    PARAGRAPH_OVER_DENSE = "paragraph_over_dense"
    STRUCTURE_CONTEXT_UNCLEAR = "structure_context_unclear"
    INSTRUCTION_CONTEXT_UNCLEAR = "instruction_context_unclear"
    ABSOLUTE_MARKETING_CLAIM = "absolute_marketing_claim"
    AGGRESSIVE_CALL_TO_ACTION = "aggressive_call_to_action"
    MARKETING_CONTEXT_UNCLEAR = "marketing_context_unclear"


_SIGNAL_TO_ISSUE = {
    ReviewFixtureSignal.CLAIM_CONTEXT_UNCLEAR: ReviewIssueCode.FACTUAL_CONTEXT_AMBIGUOUS,
    ReviewFixtureSignal.TONE_DEPARTS_BRAND: ReviewIssueCode.BRAND_TONE_MISMATCH,
    ReviewFixtureSignal.TONE_CONTEXT_UNCLEAR: ReviewIssueCode.BRAND_VOICE_AMBIGUOUS,
    ReviewFixtureSignal.HEADING_LEVELS_SKIP: ReviewIssueCode.HEADING_HIERARCHY_INVALID,
    ReviewFixtureSignal.PARAGRAPH_OVER_DENSE: ReviewIssueCode.PARAGRAPH_DENSITY_HIGH,
    ReviewFixtureSignal.STRUCTURE_CONTEXT_UNCLEAR: ReviewIssueCode.STRUCTURE_AMBIGUOUS,
    ReviewFixtureSignal.INSTRUCTION_CONTEXT_UNCLEAR: (
        ReviewIssueCode.INSTRUCTION_CONTEXT_AMBIGUOUS
    ),
    ReviewFixtureSignal.ABSOLUTE_MARKETING_CLAIM: ReviewIssueCode.MARKETING_CLAIM_EXAGGERATED,
    ReviewFixtureSignal.AGGRESSIVE_CALL_TO_ACTION: (ReviewIssueCode.CALL_TO_ACTION_TOO_AGGRESSIVE),
    ReviewFixtureSignal.MARKETING_CONTEXT_UNCLEAR: ReviewIssueCode.MARKETING_CONTEXT_AMBIGUOUS,
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewSignalObservation(_FrozenModel):
    signal: ReviewFixtureSignal
    reference: ReviewReference


class ReviewEvalCase(_FrozenModel):
    schema_version: Literal["official-account-review-eval-case-v1"]
    case_id: BoundedIdentifier
    fixture_kind: ReviewFixtureKind
    focus_dimension: ReviewDimension
    identity: ReviewInputIdentity
    signals: tuple[ReviewSignalObservation, ...] = Field(default=(), max_length=8)
    hard_gate_failures: tuple[ReviewHardGateFailure, ...] = Field(default=(), max_length=8)
    provider_status: FixtureProviderStatus

    @model_validator(mode="after")
    def validate_case(self) -> Self:
        signal_keys = tuple(
            (item.signal, item.reference.kind, item.reference.ref) for item in self.signals
        )
        if len(signal_keys) != len(set(signal_keys)):
            raise ValueError("fixture signals must be unique")
        signal_dimensions = tuple(
            issue_contract(fixture_signal_issue_code(item.signal)).dimension
            for item in self.signals
        )
        if len(signal_dimensions) != len(set(signal_dimensions)):
            raise ValueError("fixture signals must use unique review dimensions")
        if self.provider_status is not FixtureProviderStatus.AVAILABLE and self.signals:
            raise ValueError("unavailable fixture provider cannot produce reviewer signals")
        return self


class ExpectedReviewIssue(_FrozenModel):
    code: ReviewIssueCode
    references: tuple[ReviewReference, ...] = Field(min_length=1, max_length=8)


class ReviewEvalOracle(_FrozenModel):
    schema_version: Literal["official-account-review-eval-oracle-v1"]
    case_id: BoundedIdentifier
    expected_decision: ReviewDecision
    expected_issues: tuple[ExpectedReviewIssue, ...] = Field(default=(), max_length=16)
    expected_repair_issue_codes: tuple[ReviewIssueCode, ...] = Field(default=(), max_length=8)
    expected_hard_gate_override: bool = False

    @model_validator(mode="after")
    def validate_oracle(self) -> Self:
        issue_codes = tuple(item.code for item in self.expected_issues)
        if len(issue_codes) != len(set(issue_codes)):
            raise ValueError("oracle issue codes must be unique")
        repair_codes = self.expected_repair_issue_codes
        if len(repair_codes) != len(set(repair_codes)):
            raise ValueError("oracle repair issue codes must be unique")
        if any(not issue_contract(code).repairable for code in repair_codes):
            raise ValueError("oracle repair labels must use code-owned repairable issues")
        if not set(repair_codes).issubset(issue_codes):
            raise ValueError("oracle repair labels must be expected issues")
        return self


def fixture_signal_issue_code(signal: ReviewFixtureSignal) -> ReviewIssueCode:
    """Project one typed fixture observation through the frozen provider-free policy."""

    return _SIGNAL_TO_ISSUE[signal]
