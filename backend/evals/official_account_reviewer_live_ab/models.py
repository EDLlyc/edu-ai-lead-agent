"""Strict evidence schemas for the opt-in Reviewer live A/B harness."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

CASE_SCHEMA_VERSION = "official-account-review-live-ab-case-v1"
DATASET_VERSION = "official-account-review-live-ab-dataset-v1"
MANIFEST_SCHEMA_VERSION = "official-account-review-live-ab-manifest-v1"
AUTHORIZATION_SCHEMA_VERSION = "official-account-review-live-ab-authorization-v1"
ATTEMPT_SCHEMA_VERSION = "official-account-review-live-ab-attempt-v1"
WORKSHEET_SCHEMA_VERSION = "official-account-review-live-ab-worksheet-v1"
BLIND_MAP_SCHEMA_VERSION = "official-account-review-live-ab-blind-map-v1"
JUDGMENT_SCHEMA_VERSION = "official-account-review-live-ab-judgment-v1"
ADJUDICATION_SCHEMA_VERSION = "official-account-review-live-ab-adjudication-v1"
REPORT_SCHEMA_VERSION = "official-account-review-live-ab-report-v1"
FAILURE_LEDGER_SCHEMA_VERSION = "official-account-review-live-ab-failure-ledger-v1"
CALIBRATION_CANDIDATE_SCHEMA_VERSION = "official-account-review-live-ab-calibration-candidate-v1"

LIVE_AUTHORIZATION_ACKNOWLEDGEMENT = "I_AUTHORIZE_REVIEWER_LIVE_AB_V1"
REPORT_CONFIRMATION_ACKNOWLEDGEMENT = "I_CONFIRM_REVIEWER_LIVE_AB_REPORT_V1"
MAX_SAMPLE_COUNT = 64
MAX_REPETITIONS = 5
MAX_PROVIDER_CALLS_PER_TREATMENT = 3
MAX_TOTAL_PROVIDER_CALLS = MAX_SAMPLE_COUNT * MAX_REPETITIONS * 3

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SafeIdentifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}$")]
PositiveMoney = Annotated[float, Field(gt=0, le=100)]


def canonical_json_bytes(value: object) -> bytes:
    """Encode an evidence object with the one hash-stable representation."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def evidence_sha256(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise TypeError("naive datetime is not canonical evidence")
        normalized = value.astimezone(UTC).isoformat()
        return normalized.replace("+00:00", "Z")
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"unsupported evidence type: {type(value).__name__}")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExperimentArm(StrEnum):
    BASELINE = "baseline_single_writer"
    TREATMENT = "treatment_governed_reviewer"


class AttemptStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    RESULT_UNKNOWN = "result_unknown"


class ProviderCallStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    RESULT_UNKNOWN = "result_unknown"
    BUDGET_DENIED = "budget_denied"


class ReviewOutcome(StrEnum):
    ACCEPTED = "accepted"
    MANUAL_REVIEW = "manual_review"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


class FailureCode(StrEnum):
    AUTHORIZATION_MISSING = "authorization_missing"
    AUTHORIZATION_MISMATCH = "authorization_mismatch"
    AUTHORIZATION_EXPIRED = "authorization_expired"
    EXECUTOR_NOT_INSTALLED = "executor_not_installed"
    PRIVACY_SCAN_FAILED = "privacy_scan_failed"
    ARTIFACT_INTEGRITY_FAILED = "artifact_integrity_failed"
    PROVIDER_FAILED = "provider_failed"
    PROVIDER_RESULT_UNKNOWN = "provider_result_unknown"
    USAGE_UNKNOWN_COST = "usage_unknown_cost"
    BUDGET_EXCEEDED = "budget_exceeded"
    INCOMPLETE_ATTEMPTS = "incomplete_attempts"
    INCOMPLETE_HUMAN_LABELS = "incomplete_human_labels"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    HUMAN_CALIBRATION_INCOMPLETE = "human_calibration_incomplete"


class ArticleSection(_FrozenModel):
    section_ref: SafeIdentifier
    heading: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=20, max_length=1_200)


class SanitizedInitialArticle(_FrozenModel):
    title: str = Field(min_length=4, max_length=120)
    sections: tuple[ArticleSection, ...] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def validate_sections(self) -> Self:
        refs = tuple(section.section_ref for section in self.sections)
        if len(refs) != len(set(refs)):
            raise ValueError("article section refs must be unique")
        return self


class LiveAbCase(_FrozenModel):
    schema_version: Literal["official-account-review-live-ab-case-v1"]
    case_id: SafeIdentifier
    split: Literal["calibration", "holdout"]
    source_snapshot_ref: SafeIdentifier
    brand_profile_ref: SafeIdentifier
    initial_article: SanitizedInitialArticle


class CaseBinding(_FrozenModel):
    case_id: SafeIdentifier
    initial_article_sha256: Sha256Hex
    baseline_initial_sha256: Sha256Hex
    treatment_initial_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_pair(self) -> Self:
        if not (
            self.initial_article_sha256
            == self.baseline_initial_sha256
            == self.treatment_initial_sha256
        ):
            raise ValueError("paired arms must start from the exact same initial article")
        return self


class ExperimentVersions(_FrozenModel):
    writer_version: SafeIdentifier
    reviewer_r1_version: SafeIdentifier
    repair_writer_version: SafeIdentifier
    reviewer_r2_version: SafeIdentifier
    prompt_version: SafeIdentifier
    rubric_version: SafeIdentifier
    review_policy_version: SafeIdentifier
    repair_policy_version: SafeIdentifier
    enforce_policy_version: SafeIdentifier
    registry_sha256: Sha256Hex


class PricingSnapshot(_FrozenModel):
    currency: Literal["USD"] = "USD"
    effective_date: str = Field(pattern=r"^20\d{2}-\d{2}-\d{2}$")
    input_usd_per_million_tokens: float = Field(ge=0, le=100)
    output_usd_per_million_tokens: float = Field(ge=0, le=100)
    reasoning_usd_per_million_tokens: float = Field(ge=0, le=100)
    pricing_source_sha256: Sha256Hex


class RunManifest(_FrozenModel):
    schema_version: Literal["official-account-review-live-ab-manifest-v1"]
    track: Literal["opt_in_live_ab"] = "opt_in_live_ab"
    run_ref: SafeIdentifier
    created_at: datetime
    execution_window_start: datetime
    execution_window_end: datetime
    git_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    dataset_version: Literal["official-account-review-live-ab-dataset-v1"]
    dataset_sha256: Sha256Hex
    selected_case_ids: tuple[SafeIdentifier, ...]
    sample_count: int = Field(ge=1, le=MAX_SAMPLE_COUNT)
    repetitions: int = Field(ge=1, le=MAX_REPETITIONS)
    arms: tuple[ExperimentArm, ExperimentArm]
    provider: SafeIdentifier
    model: SafeIdentifier
    temperature: float = Field(ge=0, le=2)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    versions: ExperimentVersions
    pricing: PricingSnapshot
    max_input_tokens_per_call: int = Field(ge=1, le=128_000)
    max_output_tokens_per_call: int = Field(ge=1, le=32_768)
    max_provider_calls_per_treatment: Literal[3] = 3
    max_provider_calls: int = Field(ge=1, le=MAX_TOTAL_PROVIDER_CALLS)
    max_cost_per_provider_call_usd: PositiveMoney
    max_total_cost_usd: PositiveMoney
    minimum_evidence_pairs: int = Field(ge=2, le=MAX_SAMPLE_COUNT * MAX_REPETITIONS)
    minimum_double_annotated_pairs: int = Field(ge=1, le=MAX_SAMPLE_COUNT * MAX_REPETITIONS)
    bootstrap_samples: int = Field(ge=1_000, le=20_000)
    bootstrap_seed: int = Field(ge=0, le=2_147_483_647)
    blinding_secret_sha256: Sha256Hex
    case_bindings: tuple[CaseBinding, ...]
    manifest_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        for moment in (
            self.created_at,
            self.execution_window_start,
            self.execution_window_end,
        ):
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise ValueError("manifest timestamps must be timezone-aware")
        if self.execution_window_start >= self.execution_window_end:
            raise ValueError("execution window must be increasing")
        if self.created_at > self.execution_window_start:
            raise ValueError("manifest must be frozen before its execution window")
        try:
            pricing_effective_date = date.fromisoformat(self.pricing.effective_date)
        except ValueError as exc:
            raise ValueError("pricing effective date must be a real calendar date") from exc
        if pricing_effective_date > self.execution_window_start.astimezone(UTC).date():
            raise ValueError("pricing snapshot cannot postdate the execution window")
        if self.arms != (ExperimentArm.BASELINE, ExperimentArm.TREATMENT):
            raise ValueError("manifest arms must use the frozen baseline/treatment order")
        if len(self.selected_case_ids) != self.sample_count:
            raise ValueError("manifest sample count does not match selected cases")
        if len(self.selected_case_ids) != len(set(self.selected_case_ids)):
            raise ValueError("manifest selected case IDs must be unique")
        binding_ids = tuple(binding.case_id for binding in self.case_bindings)
        if binding_ids != self.selected_case_ids:
            raise ValueError("manifest bindings must follow the selected-case order")
        expected_calls = (
            self.sample_count * self.repetitions * self.max_provider_calls_per_treatment
        )
        if self.max_provider_calls != expected_calls:
            raise ValueError("manifest maximum provider-call count is not exact")
        expected_cost = round(
            self.max_provider_calls * self.max_cost_per_provider_call_usd,
            6,
        )
        if self.max_total_cost_usd != expected_cost:
            raise ValueError("manifest total cost ceiling is not derived from the call ceiling")
        if self.minimum_evidence_pairs > self.sample_count * self.repetitions:
            raise ValueError("minimum evidence exceeds the number of planned pairs")
        if self.minimum_double_annotated_pairs > self.sample_count * self.repetitions:
            raise ValueError("double-annotation minimum exceeds the number of planned pairs")
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if evidence_sha256(payload) != self.manifest_sha256:
            raise ValueError("manifest SHA-256 does not match its canonical payload")
        return self


class LiveAuthorization(_FrozenModel):
    schema_version: Literal["official-account-review-live-ab-authorization-v1"]
    manifest_sha256: Sha256Hex
    provider: SafeIdentifier
    model: SafeIdentifier
    sample_count: int = Field(ge=1, le=MAX_SAMPLE_COUNT)
    repetitions: int = Field(ge=1, le=MAX_REPETITIONS)
    max_provider_calls: int = Field(ge=1, le=MAX_TOTAL_PROVIDER_CALLS)
    max_cost_per_provider_call_usd: PositiveMoney
    max_total_cost_usd: PositiveMoney
    valid_from: datetime
    valid_until: datetime
    approved_by_ref: SafeIdentifier
    acknowledgement: Literal["I_AUTHORIZE_REVIEWER_LIVE_AB_V1"]

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.valid_from.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("authorization timestamps must be timezone-aware")
        if self.valid_from >= self.valid_until:
            raise ValueError("authorization window must be increasing")
        return self


class AttemptPlan(_FrozenModel):
    attempt_ref: SafeIdentifier
    manifest_sha256: Sha256Hex
    authorization_sha256: Sha256Hex
    case_id: SafeIdentifier
    repetition: int = Field(ge=1, le=MAX_REPETITIONS)
    arm: ExperimentArm
    initial_article_sha256: Sha256Hex
    max_provider_calls: int = Field(ge=0, le=MAX_PROVIDER_CALLS_PER_TREATMENT)
    max_cost_per_provider_call_usd: PositiveMoney
    max_input_tokens_per_call: int = Field(ge=1, le=128_000)
    max_output_tokens_per_call: int = Field(ge=1, le=32_768)

    @model_validator(mode="after")
    def validate_arm_budget(self) -> Self:
        expected = 0 if self.arm is ExperimentArm.BASELINE else 3
        if self.max_provider_calls != expected:
            raise ValueError("attempt provider-call budget does not match its arm")
        return self


class ProviderUsage(_FrozenModel):
    input_tokens: int = Field(ge=0, le=2_000_000)
    output_tokens: int = Field(ge=0, le=2_000_000)
    reasoning_tokens: int = Field(ge=0, le=2_000_000)


class ProviderCallObservation(_FrozenModel):
    call_index: int = Field(ge=1, le=MAX_PROVIDER_CALLS_PER_TREATMENT)
    phase: Literal["reviewer_r1", "repair_writer", "reviewer_r2"]
    status: ProviderCallStatus
    request_fingerprint: Sha256Hex
    latency_ms: int = Field(ge=0, le=1_800_000)
    usage: ProviderUsage | None = None
    failure_code: FailureCode | None = None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status is ProviderCallStatus.COMPLETED and self.failure_code is not None:
            raise ValueError("completed provider call cannot have a failure code")
        if self.status is not ProviderCallStatus.COMPLETED and self.failure_code is None:
            raise ValueError("non-completed provider call requires a closed failure code")
        expected_failure = {
            ProviderCallStatus.FAILED: FailureCode.PROVIDER_FAILED,
            ProviderCallStatus.RESULT_UNKNOWN: FailureCode.PROVIDER_RESULT_UNKNOWN,
            ProviderCallStatus.BUDGET_DENIED: FailureCode.BUDGET_EXCEEDED,
        }.get(self.status)
        if expected_failure is not None and self.failure_code is not expected_failure:
            raise ValueError("provider-call status requires its exact closed failure code")
        return self


class RevisionArtifact(_FrozenModel):
    revision_no: Literal[1, 2]
    artifact_sha256: Sha256Hex
    artifact_ref: SafeIdentifier


class AttemptObservation(_FrozenModel):
    schema_version: Literal["official-account-review-live-ab-attempt-v1"]
    attempt_ref: SafeIdentifier
    manifest_sha256: Sha256Hex
    authorization_sha256: Sha256Hex
    case_id: SafeIdentifier
    repetition: int = Field(ge=1, le=MAX_REPETITIONS)
    arm: ExperimentArm
    initial_article_sha256: Sha256Hex
    status: AttemptStatus
    initial_decision: ReviewOutcome | None = None
    final_decision: ReviewOutcome | None = None
    critical_defect_detected_on_initial: bool | None = None
    repair_performed: bool = False
    revisions: tuple[RevisionArtifact, ...] = Field(default=(), max_length=2)
    provider_calls: tuple[ProviderCallObservation, ...] = Field(default=(), max_length=3)
    total_latency_ms: int = Field(ge=0, le=3_600_000)
    failure_code: FailureCode | None = None

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        call_indices = tuple(call.call_index for call in self.provider_calls)
        if call_indices != tuple(range(1, len(self.provider_calls) + 1)):
            raise ValueError("provider calls must be a contiguous ordered attempt ledger")
        phases = tuple(call.phase for call in self.provider_calls)
        if phases != ("reviewer_r1", "repair_writer", "reviewer_r2")[: len(phases)]:
            raise ValueError("provider-call phases must follow the frozen governed order")
        revision_numbers = tuple(item.revision_no for item in self.revisions)
        if revision_numbers not in {(1,), (1, 2), ()}:
            raise ValueError("revision artifacts must be ordered revision 1 then optional 2")
        if self.revisions and self.revisions[0].artifact_sha256 != self.initial_article_sha256:
            raise ValueError("revision 1 must equal the paired frozen initial article")
        if self.arm is ExperimentArm.BASELINE:
            if self.provider_calls or self.repair_performed or revision_numbers not in {(1,), ()}:
                raise ValueError("baseline cannot call a provider or create a repair revision")
        elif self.status is AttemptStatus.COMPLETED:
            if not self.provider_calls:
                raise ValueError("completed treatment must contain its Reviewer call")
            if self.repair_performed and len(self.provider_calls) != 3:
                raise ValueError("completed repair treatment requires r1, repair, and r2 calls")
            if not self.repair_performed and len(self.provider_calls) != 1:
                raise ValueError("non-repair treatment must stop after the r1 Reviewer")
        if self.repair_performed != (revision_numbers == (1, 2)):
            raise ValueError("repair flag must match revision-2 evidence")
        if self.status is AttemptStatus.COMPLETED:
            if (
                self.failure_code is not None
                or not self.revisions
                or self.initial_decision is None
                or self.final_decision is None
                or self.critical_defect_detected_on_initial is None
            ):
                raise ValueError("completed attempt requires bound decisions and revision evidence")
            if any(call.status is not ProviderCallStatus.COMPLETED for call in self.provider_calls):
                raise ValueError("completed attempt cannot contain a failed provider call")
            if ReviewOutcome.UNAVAILABLE in (self.initial_decision, self.final_decision):
                raise ValueError("provider unavailability cannot be a completed attempt")
            if self.arm is ExperimentArm.BASELINE:
                if revision_numbers != (1,) or self.initial_decision is not self.final_decision:
                    raise ValueError(
                        "completed baseline must retain one initial revision and one decision"
                    )
            elif self.repair_performed:
                if self.initial_decision is not ReviewOutcome.REJECTED:
                    raise ValueError("repair treatment requires an initial rejection")
                if (
                    self.revisions[0].artifact_sha256 == self.revisions[1].artifact_sha256
                    or self.revisions[0].artifact_ref == self.revisions[1].artifact_ref
                ):
                    raise ValueError("repair revision must be distinct from the initial revision")
            elif self.initial_decision is not self.final_decision:
                raise ValueError("non-repair treatment cannot change the Reviewer decision")
        elif self.failure_code is None:
            raise ValueError("non-completed attempt requires a closed failure code")
        return self


class WorksheetRow(_FrozenModel):
    schema_version: Literal["official-account-review-live-ab-worksheet-v1"]
    blind_ref: SafeIdentifier
    pair_ref: SafeIdentifier
    candidate: Literal["A", "B"]
    artifact_ref: SafeIdentifier
    artifact_commitment_sha256: Sha256Hex
    annotator_ref: SafeIdentifier | None = None
    editorial_pass: bool | None = None
    critical_defect_present: bool | None = None
    defect_codes: tuple[SafeIdentifier, ...] = Field(default=(), max_length=12)


class BlindMapRow(_FrozenModel):
    schema_version: Literal["official-account-review-live-ab-blind-map-v1"]
    blind_ref: SafeIdentifier
    pair_ref: SafeIdentifier
    candidate: Literal["A", "B"]
    case_id: SafeIdentifier
    repetition: int = Field(ge=1, le=MAX_REPETITIONS)
    arm: ExperimentArm
    revision_no: Literal[1, 2]
    source_artifact_ref: SafeIdentifier
    artifact_sha256: Sha256Hex
    artifact_commitment_sha256: Sha256Hex


class HumanJudgment(_FrozenModel):
    schema_version: Literal["official-account-review-live-ab-judgment-v1"]
    blind_ref: SafeIdentifier
    annotator_ref: SafeIdentifier
    editorial_pass: bool
    critical_defect_present: bool
    defect_codes: tuple[SafeIdentifier, ...] = Field(default=(), max_length=12)


class HumanAdjudication(_FrozenModel):
    schema_version: Literal["official-account-review-live-ab-adjudication-v1"]
    blind_ref: SafeIdentifier
    source_annotator_refs: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=8)
    method: Literal["single", "consensus", "adjudicated"]
    adjudicator_ref: SafeIdentifier | None = None
    editorial_pass: bool
    critical_defect_present: bool
    defect_codes: tuple[SafeIdentifier, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        if len(self.source_annotator_refs) != len(set(self.source_annotator_refs)):
            raise ValueError("adjudication source annotators must be unique")
        if self.method == "single" and len(self.source_annotator_refs) != 1:
            raise ValueError("single adjudication must have one source annotator")
        if self.method != "single" and len(self.source_annotator_refs) < 2:
            raise ValueError("reviewed adjudication requires at least two source annotators")
        if self.method == "adjudicated":
            if self.adjudicator_ref is None:
                raise ValueError("disputed labels require an independent adjudicator")
            if self.adjudicator_ref in self.source_annotator_refs:
                raise ValueError("adjudicator must be independent from source annotators")
        elif self.adjudicator_ref is not None:
            raise ValueError("only disputed labels may name an adjudicator")
        return self


class FailureLedger(_FrozenModel):
    schema_version: Literal["official-account-review-live-ab-failure-ledger-v1"]
    manifest_sha256: Sha256Hex
    dataset_sha256: Sha256Hex
    created_at: datetime
    reason: FailureCode
    planned_max_provider_calls: int = Field(ge=0, le=MAX_TOTAL_PROVIDER_CALLS)
    planned_max_cost_usd: float = Field(ge=0, le=100)
    live_model_calls: int | None = Field(default=None, ge=0, le=MAX_TOTAL_PROVIDER_CALLS)
    conclusion_eligible: Literal[False] = False
    uplift_claims: tuple[str, ...] = Field(default=(), max_length=0)
    authorization_sha256: Sha256Hex | None = None
    ledger_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("failure-ledger timestamp must be timezone-aware")
        if (
            self.reason
            in {
                FailureCode.AUTHORIZATION_MISSING,
                FailureCode.AUTHORIZATION_MISMATCH,
                FailureCode.AUTHORIZATION_EXPIRED,
                FailureCode.EXECUTOR_NOT_INSTALLED,
                FailureCode.PRIVACY_SCAN_FAILED,
            }
            and self.live_model_calls != 0
        ):
            raise ValueError("pre-provider failure ledger must record zero live calls")
        payload = self.model_dump(mode="json", exclude={"ledger_sha256"})
        if evidence_sha256(payload) != self.ledger_sha256:
            raise ValueError("failure-ledger SHA-256 does not match its canonical payload")
        return self


class CalibrationCandidate(_FrozenModel):
    schema_version: Literal["official-account-review-live-ab-calibration-candidate-v1"]
    report_sha256: Sha256Hex
    manifest_sha256: Sha256Hex
    authorization_sha256: Sha256Hex
    dataset_version: Literal["official-account-review-live-ab-dataset-v1"]
    dataset_sha256: Sha256Hex
    sample_count: int = Field(ge=1, le=MAX_SAMPLE_COUNT)
    repetitions: int = Field(ge=1, le=MAX_REPETITIONS)
    confirmed_at: datetime
    confirmed_by_ref: SafeIdentifier
    confirmation: Literal["I_CONFIRM_REVIEWER_LIVE_AB_REPORT_V1"]
    production_mode_changed: Literal[False] = False
    candidate_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if self.confirmed_at.tzinfo is None or self.confirmed_at.utcoffset() is None:
            raise ValueError("calibration confirmation timestamp must be timezone-aware")
        payload = self.model_dump(mode="json", exclude={"candidate_sha256"})
        if evidence_sha256(payload) != self.candidate_sha256:
            raise ValueError("calibration-candidate SHA-256 does not match its payload")
        return self


def utc_now() -> datetime:
    return datetime.now(UTC)
