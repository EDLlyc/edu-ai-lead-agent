"""Strict, provider-neutral contracts for bounded model-panel evaluations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MODEL_PANEL_CONTRACT_VERSION = "model-panel-contract-v1"
MODEL_PANEL_PROMPT_BOUNDARY_VERSION = "model-panel-untrusted-boundary-v1"
MODEL_PANEL_MANIFEST_SCHEMA_VERSION = "model-panel-manifest-v1"
MODEL_PANEL_AUTHORIZATION_SCHEMA_VERSION = "model-panel-authorization-v1"
MODEL_PANEL_REQUEST_SCHEMA_VERSION = "model-panel-pairwise-request-v1"
MODEL_PANEL_VOTE_SCHEMA_VERSION = "model-panel-vote-v1"
MODEL_PANEL_ATTEMPT_SCHEMA_VERSION = "model-panel-attempt-v1"
MODEL_PANEL_CONSENSUS_SCHEMA_VERSION = "model-panel-consensus-v1"
MODEL_PANEL_JOURNAL_SCHEMA_VERSION = "model-panel-journal-v1"
MODEL_PANEL_ARTIFACT_HASHES_SCHEMA_VERSION = "model-panel-artifact-hashes-v1"
MODEL_PANEL_AUTHORIZATION_ACKNOWLEDGEMENT = "I_AUTHORIZE_MODEL_PANEL_V1"

MAX_MODELS = 16
MAX_ATTEMPTS = 2_048
MAX_ISSUE_CODES = 32
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_REQUEST_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_TOKENS = 4_096

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SafeIdentifier = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:_.\/-]{0,191}$"),
]
PositiveDecimal = Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=8)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=8)]


def canonical_json_bytes(value: object) -> bytes:
    """Return the only hash-stable representation used by panel evidence."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")


def evidence_sha256(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def pairwise_request_fingerprint(payload: dict[str, object]) -> str:
    """Hash semantic request fields without circular manifest/authorization bindings."""

    semantic = dict(payload)
    semantic.pop("request_fingerprint", None)
    semantic.pop("manifest_sha256", None)
    semantic.pop("authorization_sha256", None)
    semantic.setdefault("contract_version", MODEL_PANEL_CONTRACT_VERSION)
    semantic.setdefault("prompt_boundary_version", MODEL_PANEL_PROMPT_BOUNDARY_VERSION)
    return evidence_sha256(semantic)


def panel_manifest_fingerprint(payload: dict[str, object]) -> str:
    """Hash a manifest payload after materializing versioned schema defaults."""

    canonical = dict(payload)
    canonical.pop("manifest_sha256", None)
    canonical.setdefault("contract_version", MODEL_PANEL_CONTRACT_VERSION)
    return evidence_sha256(canonical)


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise TypeError("naive datetime is not canonical evidence")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"unsupported evidence type: {type(value).__name__}")


def require_aware(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


class FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class PresentationOrder(StrEnum):
    AB = "AB"
    BA = "BA"


class PresentedChoice(StrEnum):
    A = "A"
    B = "B"
    TIE = "tie"
    ABSTAIN = "abstain"


class CanonicalChoice(StrEnum):
    FIRST = "first"
    SECOND = "second"
    TIE = "tie"
    ABSTAIN = "abstain"
    UNRESOLVED = "unresolved"


class PanelIssueCode(StrEnum):
    SEMANTIC_MISMATCH = "semantic_mismatch"
    APPROVED_IDENTITY_MISMATCH = "approved_identity_mismatch"
    VISIBLE_TEXT_ERROR = "visible_text_error"
    RENDERING_ARTIFACT = "rendering_artifact"
    CROP_LAYOUT_ERROR = "crop_layout_error"
    BATCH_DUPLICATE = "batch_duplicate"
    EDITORIAL_DEFECT = "editorial_defect"
    CRITICAL_DEFECT = "critical_defect"
    POLICY_VIOLATION = "policy_violation"
    INSUFFICIENT_CONTEXT = "insufficient_context"


class VoteProfile(StrEnum):
    TEXT_PAIR = "text_pair"
    TEXT_PAIR_ARM_VERDICT = "text_pair_arm_verdict"
    IMAGE_PAIR_ARM_VERDICT = "image_pair_arm_verdict"


class ArmDecision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    ABSTAIN = "abstain"


class PresentedArtifactGroup(StrEnum):
    REFERENCE = "reference"
    A = "A"
    B = "B"


class AttemptStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    RESULT_UNKNOWN = "result_unknown"
    BUDGET_DENIED = "budget_denied"


class PanelFailureCode(StrEnum):
    AUTHORIZATION_INVALID = "authorization_invalid"
    AUTHORIZATION_EXPIRED = "authorization_expired"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_CONNECTION_FAILED = "provider_connection_failed"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_RESULT_UNKNOWN = "provider_result_unknown"
    PROVIDER_IDENTITY_MISMATCH = "provider_identity_mismatch"
    PROVIDER_ENVELOPE_INVALID = "provider_envelope_invalid"
    JUDGE_CONTENT_FRAMING_INVALID = "judge_content_framing_invalid"
    JUDGE_CONTENT_SCHEMA_INVALID = "judge_content_schema_invalid"
    JUDGE_CONTENT_POLICY_INVALID = "judge_content_policy_invalid"
    # Retained so model-panel-attempt-v1 evidence from before staged diagnostics still parses.
    JUDGE_CONTENT_INVALID = "judge_content_invalid"
    # Retained so model-panel-attempt-v1 evidence from the generic failure era still parses.
    INVALID_PROVIDER_OUTPUT = "invalid_provider_output"
    PROVIDER_USAGE_INVALID = "provider_usage_invalid"
    USAGE_UNKNOWN = "usage_unknown"
    ADAPTER_CRASH = "adapter_crash"
    EVIDENCE_IO_FAILED = "evidence_io_failed"


class JournalEventKind(StrEnum):
    ATTEMPT_STARTED = "attempt_started"
    ATTEMPT_TERMINAL = "attempt_terminal"


class OrderControlStatus(StrEnum):
    CONSISTENT = "consistent"
    ABSTAINED = "abstained"
    INCOMPLETE = "incomplete"
    POSITION_CONFLICT = "position_conflict"


class PanelModelIdentity(FrozenModel):
    schema_version: Literal["model-panel-model-identity-v1"] = "model-panel-model-identity-v1"
    identity_ref: SafeIdentifier
    gateway: SafeIdentifier
    provider: SafeIdentifier
    model_family: SafeIdentifier
    requested_model: SafeIdentifier
    returned_model: SafeIdentifier
    endpoint_host_sha256: Sha256Hex
    adapter_version: SafeIdentifier
    pricing_snapshot_sha256: Sha256Hex

    @model_validator(mode="after")
    def exact_returned_identity(self) -> Self:
        if self.returned_model != self.requested_model:
            raise ValueError("returned model must exactly match the requested model")
        return self


class ArtifactReference(FrozenModel):
    artifact_ref: SafeIdentifier
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    byte_size: int = Field(ge=1, le=MAX_IMAGE_BYTES)
    sha256: Sha256Hex
    presented_group: PresentedArtifactGroup
    group_index: int = Field(ge=1, le=2)


class PairwiseJudgeRequest(FrozenModel):
    schema_version: Literal["model-panel-pairwise-request-v1"]
    contract_version: Literal["model-panel-contract-v1"] = "model-panel-contract-v1"
    prompt_boundary_version: Literal["model-panel-untrusted-boundary-v1"] = (
        "model-panel-untrusted-boundary-v1"
    )
    run_ref: SafeIdentifier
    manifest_sha256: Sha256Hex
    authorization_sha256: Sha256Hex
    attempt_ref: SafeIdentifier
    pair_ref: SafeIdentifier
    case_ref: SafeIdentifier
    dimension: SafeIdentifier
    vote_profile: VoteProfile
    evaluator_model_ref: SafeIdentifier
    target_model_ref: SafeIdentifier | None = None
    rubric_version: SafeIdentifier
    rubric_sha256: Sha256Hex
    prompt_version: SafeIdentifier
    prompt_sha256: Sha256Hex
    blind_a_ref: SafeIdentifier
    blind_b_ref: SafeIdentifier
    candidate_a_text_sha256: Sha256Hex
    candidate_b_text_sha256: Sha256Hex
    presentation_order: PresentationOrder
    repeat_index: int = Field(ge=0, le=8)
    allowed_issue_codes: tuple[PanelIssueCode, ...] = Field(
        min_length=1,
        max_length=MAX_ISSUE_CODES,
    )
    artifacts: tuple[ArtifactReference, ...] = Field(default=(), max_length=MAX_IMAGES)
    max_input_tokens: int = Field(ge=1, le=1_000_000)
    max_output_tokens: int = Field(ge=1, le=MAX_OUTPUT_TOKENS)
    native_cost_unit: SafeIdentifier
    maximum_native_cost: PositiveDecimal
    max_attempts: Literal[1] = 1
    request_fingerprint: Sha256Hex

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if self.blind_a_ref == self.blind_b_ref:
            raise ValueError("blind candidates must be distinct")
        if self.target_model_ref == self.evaluator_model_ref:
            raise ValueError("a target model cannot evaluate itself")
        issue_codes = tuple(code.value for code in self.allowed_issue_codes)
        if issue_codes != tuple(sorted(set(issue_codes))):
            raise ValueError("allowed issue codes must be unique and lexically sorted")
        artifact_refs = tuple(item.artifact_ref for item in self.artifacts)
        if len(artifact_refs) != len(set(artifact_refs)):
            raise ValueError("artifact references must be unique")
        if self.vote_profile in {
            VoteProfile.TEXT_PAIR,
            VoteProfile.TEXT_PAIR_ARM_VERDICT,
        }:
            if self.artifacts:
                raise ValueError("text vote profile cannot contain image artifacts")
        else:
            groups = {
                group: tuple(
                    item.group_index for item in self.artifacts if item.presented_group is group
                )
                for group in PresentedArtifactGroup
            }
            if not groups[PresentedArtifactGroup.A] or not groups[PresentedArtifactGroup.B]:
                raise ValueError("image vote profile requires both presented arms")
            if len(groups[PresentedArtifactGroup.REFERENCE]) > 1:
                raise ValueError("image vote profile permits at most one reference image")
            for indexes in groups.values():
                if indexes and indexes != tuple(range(1, len(indexes) + 1)):
                    raise ValueError("image group indexes must be contiguous and ordered")
        payload: dict[str, object] = self.model_dump(
            mode="json",
            exclude={"request_fingerprint", "manifest_sha256", "authorization_sha256"},
        )
        if pairwise_request_fingerprint(payload) != self.request_fingerprint:
            raise ValueError("request fingerprint does not match its canonical payload")
        return self


class NativeCost(FrozenModel):
    unit: SafeIdentifier
    amount: NonNegativeDecimal


class ProviderUsage(FrozenModel):
    input_tokens: int | None = Field(default=None, ge=0, le=10_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=10_000_000)
    reasoning_tokens: int | None = Field(default=None, ge=0, le=10_000_000)
    native_cost: NativeCost | None = None

    @property
    def fully_known(self) -> bool:
        return all(
            value is not None
            for value in (
                self.input_tokens,
                self.output_tokens,
                self.native_cost,
            )
        )


class ArmVerdict(FrozenModel):
    decision: ArmDecision
    critical: bool | None
    issue_codes: tuple[PanelIssueCode, ...] = Field(default=(), max_length=MAX_ISSUE_CODES)

    @model_validator(mode="after")
    def validate_verdict(self) -> Self:
        codes = tuple(code.value for code in self.issue_codes)
        if codes != tuple(sorted(set(codes))):
            raise ValueError("arm issue codes must be unique and lexically sorted")
        if self.decision is ArmDecision.ABSTAIN:
            if self.critical is not None or self.issue_codes:
                raise ValueError("abstaining arm cannot claim critical state or issues")
        elif self.critical is None:
            raise ValueError("decided arm requires an explicit critical flag")
        elif self.decision is ArmDecision.ACCEPT and (self.critical or self.issue_codes):
            raise ValueError("an accepted arm requires critical false and no issue codes")
        elif self.decision is ArmDecision.REJECT and not self.issue_codes:
            raise ValueError("a rejected arm requires at least one issue code")
        elif self.critical and not self.issue_codes:
            raise ValueError("critical arm verdict requires at least one issue code")
        return self


class JudgeVote(FrozenModel):
    schema_version: Literal["model-panel-vote-v1"]
    attempt_ref: SafeIdentifier
    pair_ref: SafeIdentifier
    case_ref: SafeIdentifier
    evaluator_model_ref: SafeIdentifier
    request_fingerprint: Sha256Hex
    presentation_order: PresentationOrder
    repeat_index: int = Field(ge=0, le=8)
    vote_profile: VoteProfile
    presented_choice: PresentedChoice
    canonical_choice: CanonicalChoice
    issue_codes: tuple[PanelIssueCode, ...] = Field(default=(), max_length=MAX_ISSUE_CODES)
    presented_a_verdict: ArmVerdict | None = None
    presented_b_verdict: ArmVerdict | None = None
    canonical_first_verdict: ArmVerdict | None = None
    canonical_second_verdict: ArmVerdict | None = None
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_vote(self) -> Self:
        expected = canonicalize_choice(self.presented_choice, self.presentation_order)
        if self.canonical_choice is not expected:
            raise ValueError("canonical choice does not match presentation order")
        codes = tuple(code.value for code in self.issue_codes)
        if codes != tuple(sorted(set(codes))):
            raise ValueError("issue codes must be unique and lexically sorted")
        arm_values = (
            self.presented_a_verdict,
            self.presented_b_verdict,
            self.canonical_first_verdict,
            self.canonical_second_verdict,
        )
        if self.vote_profile is VoteProfile.TEXT_PAIR:
            if any(value is not None for value in arm_values):
                raise ValueError("text-pair vote cannot contain arm verdicts")
        else:
            if self.issue_codes:
                raise ValueError("arm-verdict vote cannot use pair-scoped issue codes")
            if any(value is None for value in arm_values):
                raise ValueError("arm-verdict vote requires both presented and canonical arms")
            expected_first, expected_second = canonicalize_arm_verdicts(
                self.presented_a_verdict,
                self.presented_b_verdict,
                self.presentation_order,
            )
            if (
                self.canonical_first_verdict != expected_first
                or self.canonical_second_verdict != expected_second
            ):
                raise ValueError("canonical arm verdicts do not match presentation order")
        return self


class ModelRequestLimit(FrozenModel):
    model_ref: SafeIdentifier
    request_limit: int = Field(ge=1, le=MAX_ATTEMPTS)
    input_token_limit: int = Field(ge=1, le=2_000_000_000)
    output_token_limit: int = Field(ge=1, le=2_000_000_000)


class ProviderNativeLimit(FrozenModel):
    provider_ref: SafeIdentifier
    unit: SafeIdentifier
    maximum: PositiveDecimal


class ModelBudgetUsage(FrozenModel):
    model_ref: SafeIdentifier
    request_limit: int = Field(ge=1, le=MAX_ATTEMPTS)
    requests_used: int = Field(ge=0, le=MAX_ATTEMPTS)
    requests_reserved: int = Field(ge=0, le=MAX_ATTEMPTS)
    input_token_limit: int = Field(ge=1, le=2_000_000_000)
    input_tokens_used: int = Field(ge=0, le=2_000_000_000)
    input_tokens_reserved: int = Field(ge=0, le=2_000_000_000)
    output_token_limit: int = Field(ge=1, le=2_000_000_000)
    output_tokens_used: int = Field(ge=0, le=2_000_000_000)
    output_tokens_reserved: int = Field(ge=0, le=2_000_000_000)
    unknown_usage_count: int = Field(ge=0, le=MAX_ATTEMPTS)

    @model_validator(mode="after")
    def validate_usage(self) -> Self:
        if self.requests_used + self.requests_reserved > self.request_limit:
            raise ValueError("model request usage exceeds its limit")
        if self.input_tokens_used + self.input_tokens_reserved > self.input_token_limit:
            raise ValueError("model input-token usage exceeds its limit")
        if self.output_tokens_used + self.output_tokens_reserved > self.output_token_limit:
            raise ValueError("model output-token usage exceeds its limit")
        if self.unknown_usage_count > self.requests_used:
            raise ValueError("unknown model usage cannot exceed used requests")
        return self


class ProviderBudgetUsage(FrozenModel):
    provider_ref: SafeIdentifier
    unit: SafeIdentifier
    maximum: PositiveDecimal
    spent: NonNegativeDecimal
    reserved: NonNegativeDecimal
    unknown_cost_count: int = Field(ge=0, le=MAX_ATTEMPTS)

    @model_validator(mode="after")
    def validate_usage(self) -> Self:
        if self.spent + self.reserved > self.maximum:
            raise ValueError("provider native-cost usage exceeds its limit")
        return self


class PanelBudgetSnapshot(FrozenModel):
    schema_version: Literal["model-panel-budget-snapshot-v1"] = "model-panel-budget-snapshot-v1"
    total_request_limit: int = Field(ge=1, le=MAX_ATTEMPTS)
    total_requests_used: int = Field(ge=0, le=MAX_ATTEMPTS)
    total_requests_reserved: int = Field(ge=0, le=MAX_ATTEMPTS)
    model_usage: tuple[ModelBudgetUsage, ...] = Field(min_length=1, max_length=MAX_MODELS)
    provider_usage: tuple[ProviderBudgetUsage, ...] = Field(
        min_length=1,
        max_length=MAX_MODELS,
    )
    observed_at: datetime

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        require_aware(self.observed_at, label="budget snapshot time")
        if self.total_requests_used + self.total_requests_reserved > self.total_request_limit:
            raise ValueError("total request usage exceeds its limit")
        model_refs = tuple(item.model_ref for item in self.model_usage)
        if model_refs != tuple(sorted(set(model_refs))):
            raise ValueError("model budget usage must be unique and sorted")
        provider_refs = tuple(item.provider_ref for item in self.provider_usage)
        if provider_refs != tuple(sorted(set(provider_refs))):
            raise ValueError("provider budget usage must be unique and sorted")
        if self.total_requests_used != sum(item.requests_used for item in self.model_usage):
            raise ValueError("total used requests do not match model usage")
        if self.total_requests_reserved != sum(item.requests_reserved for item in self.model_usage):
            raise ValueError("total reserved requests do not match model usage")
        return self


class AttemptBinding(FrozenModel):
    attempt_ref: SafeIdentifier
    pair_ref: SafeIdentifier
    case_ref: SafeIdentifier
    evaluator_model_ref: SafeIdentifier
    target_model_ref: SafeIdentifier | None = None
    presentation_order: PresentationOrder
    repeat_index: int = Field(ge=0, le=8)
    max_input_tokens: int = Field(ge=1, le=1_000_000)
    max_output_tokens: int = Field(ge=1, le=MAX_OUTPUT_TOKENS)
    native_cost_unit: SafeIdentifier
    maximum_native_cost: PositiveDecimal
    request_fingerprint: Sha256Hex

    @model_validator(mode="after")
    def target_is_not_evaluator(self) -> Self:
        if self.target_model_ref == self.evaluator_model_ref:
            raise ValueError("a target model cannot evaluate itself")
        return self


class PanelManifest(FrozenModel):
    schema_version: Literal["model-panel-manifest-v1"]
    contract_version: Literal["model-panel-contract-v1"] = "model-panel-contract-v1"
    run_ref: SafeIdentifier
    track: SafeIdentifier
    created_at: datetime
    execution_window_start: datetime
    execution_window_end: datetime
    git_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    dataset_version: SafeIdentifier
    dataset_sha256: Sha256Hex
    rubric_version: SafeIdentifier
    rubric_sha256: Sha256Hex
    prompt_version: SafeIdentifier
    prompt_sha256: Sha256Hex
    identities: tuple[PanelModelIdentity, ...] = Field(min_length=1, max_length=MAX_MODELS)
    attempt_bindings: tuple[AttemptBinding, ...] = Field(min_length=1, max_length=MAX_ATTEMPTS)
    total_request_limit: int = Field(ge=1, le=MAX_ATTEMPTS)
    model_request_limits: tuple[ModelRequestLimit, ...] = Field(
        min_length=1,
        max_length=MAX_MODELS,
    )
    provider_native_limits: tuple[ProviderNativeLimit, ...] = Field(
        min_length=1,
        max_length=MAX_MODELS,
    )
    manifest_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        created = require_aware(self.created_at, label="manifest created_at")
        start = require_aware(self.execution_window_start, label="execution window start")
        end = require_aware(self.execution_window_end, label="execution window end")
        if created > start or start >= end:
            raise ValueError("manifest timestamps must precede an increasing execution window")
        identity_refs = tuple(item.identity_ref for item in self.identities)
        if identity_refs != tuple(sorted(set(identity_refs))):
            raise ValueError("model identities must be unique and lexically sorted")
        attempt_refs = tuple(item.attempt_ref for item in self.attempt_bindings)
        if len(attempt_refs) != len(set(attempt_refs)):
            raise ValueError("attempt references must be unique")
        if self.total_request_limit != len(self.attempt_bindings):
            raise ValueError("total request limit must exactly equal the frozen attempts")
        model_limits = tuple(item.model_ref for item in self.model_request_limits)
        if model_limits != tuple(sorted(set(model_limits))):
            raise ValueError("model request limits must be unique and lexically sorted")
        if set(model_limits) != set(identity_refs):
            raise ValueError("every model identity requires one request limit")
        expected_counts = {model_ref: [0, 0, 0] for model_ref in identity_refs}
        for binding in self.attempt_bindings:
            if binding.evaluator_model_ref not in expected_counts:
                raise ValueError("attempt references an undeclared evaluator model")
            counters = expected_counts[binding.evaluator_model_ref]
            counters[0] += 1
            counters[1] += binding.max_input_tokens
            counters[2] += binding.max_output_tokens
        actual_counts = {
            item.model_ref: [
                item.request_limit,
                item.input_token_limit,
                item.output_token_limit,
            ]
            for item in self.model_request_limits
        }
        if actual_counts != expected_counts:
            raise ValueError("per-model request limits must exactly match frozen attempts")
        provider_refs = tuple(item.provider_ref for item in self.provider_native_limits)
        if provider_refs != tuple(sorted(set(provider_refs))):
            raise ValueError("provider native limits must be unique and lexically sorted")
        declared_providers = {item.provider for item in self.identities}
        if set(provider_refs) != declared_providers:
            raise ValueError("every declared provider requires one native-cost limit")
        providers_by_identity = {item.identity_ref: item.provider for item in self.identities}
        units_by_provider = {item.provider_ref: item.unit for item in self.provider_native_limits}
        for binding in self.attempt_bindings:
            provider_ref = providers_by_identity[binding.evaluator_model_ref]
            if binding.native_cost_unit != units_by_provider[provider_ref]:
                raise ValueError("attempt native-cost unit does not match its provider limit")
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if panel_manifest_fingerprint(payload) != self.manifest_sha256:
            raise ValueError("manifest SHA-256 does not match its canonical payload")
        return self


class PanelAuthorization(FrozenModel):
    schema_version: Literal["model-panel-authorization-v1"]
    manifest_sha256: Sha256Hex
    valid_from: datetime
    valid_until: datetime
    approved_by_ref: SafeIdentifier
    total_request_limit: int = Field(ge=1, le=MAX_ATTEMPTS)
    model_request_limits: tuple[ModelRequestLimit, ...] = Field(
        min_length=1,
        max_length=MAX_MODELS,
    )
    provider_native_limits: tuple[ProviderNativeLimit, ...] = Field(
        min_length=1,
        max_length=MAX_MODELS,
    )
    acknowledgement: Literal["I_AUTHORIZE_MODEL_PANEL_V1"]
    authorization_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_authorization(self) -> Self:
        start = require_aware(self.valid_from, label="authorization start")
        end = require_aware(self.valid_until, label="authorization end")
        if start >= end:
            raise ValueError("authorization window must be increasing")
        model_refs = tuple(item.model_ref for item in self.model_request_limits)
        if model_refs != tuple(sorted(set(model_refs))):
            raise ValueError("authorization model limits must be unique and sorted")
        provider_refs = tuple(item.provider_ref for item in self.provider_native_limits)
        if provider_refs != tuple(sorted(set(provider_refs))):
            raise ValueError("authorization provider limits must be unique and sorted")
        payload = self.model_dump(mode="json", exclude={"authorization_sha256"})
        if evidence_sha256(payload) != self.authorization_sha256:
            raise ValueError("authorization SHA-256 does not match its canonical payload")
        return self


class PanelAttempt(FrozenModel):
    schema_version: Literal["model-panel-attempt-v1"]
    run_ref: SafeIdentifier
    manifest_sha256: Sha256Hex
    authorization_sha256: Sha256Hex
    attempt_ref: SafeIdentifier
    pair_ref: SafeIdentifier
    case_ref: SafeIdentifier
    evaluator_model_ref: SafeIdentifier
    presentation_order: PresentationOrder
    repeat_index: int = Field(ge=0, le=8)
    request_fingerprint: Sha256Hex
    max_attempts: Literal[1] = 1
    status: AttemptStatus
    started_at: datetime
    finished_at: datetime | None = None
    identity: PanelModelIdentity | None = None
    usage: ProviderUsage | None = None
    latency_ms: int | None = Field(default=None, ge=0, le=1_800_000)
    vote: JudgeVote | None = None
    failure_code: PanelFailureCode | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        started = require_aware(self.started_at, label="attempt start")
        if self.status is AttemptStatus.STARTED:
            if any(
                value is not None
                for value in (
                    self.finished_at,
                    self.identity,
                    self.usage,
                    self.latency_ms,
                    self.vote,
                    self.failure_code,
                )
            ):
                raise ValueError("started attempt cannot contain terminal fields")
            return self
        if self.finished_at is None or self.latency_ms is None:
            raise ValueError("terminal attempt requires finish time and latency")
        finished = require_aware(self.finished_at, label="attempt finish")
        if finished < started:
            raise ValueError("attempt finish cannot precede start")
        if self.identity is not None and self.identity.identity_ref != self.evaluator_model_ref:
            raise ValueError("attempt identity must match the evaluator model")
        if self.status is AttemptStatus.COMPLETED:
            if self.identity is None or self.usage is None or self.vote is None:
                raise ValueError("completed attempt requires identity, usage, and vote")
            if self.failure_code is not None:
                raise ValueError("completed attempt cannot have a failure code")
            if not self.usage.fully_known:
                raise ValueError("completed attempt requires fully known usage and native cost")
            expected_vote_binding = (
                self.attempt_ref,
                self.pair_ref,
                self.case_ref,
                self.evaluator_model_ref,
                self.presentation_order,
                self.repeat_index,
                self.request_fingerprint,
            )
            actual_vote_binding = (
                self.vote.attempt_ref,
                self.vote.pair_ref,
                self.vote.case_ref,
                self.vote.evaluator_model_ref,
                self.vote.presentation_order,
                self.vote.repeat_index,
                self.vote.request_fingerprint,
            )
            if actual_vote_binding != expected_vote_binding:
                raise ValueError("vote must be bound to the exact attempt identity")
        elif self.failure_code is None:
            raise ValueError("non-completed terminal attempt requires a closed failure code")
        elif self.status is AttemptStatus.RESULT_UNKNOWN:
            if self.vote is not None:
                raise ValueError("result-unknown attempt cannot project a vote")
        elif self.status is AttemptStatus.BUDGET_DENIED:
            if any(value is not None for value in (self.identity, self.usage, self.vote)):
                raise ValueError("budget-denied attempt cannot project provider output")
        elif self.vote is not None:
            raise ValueError("failed attempt cannot project a vote")
        return self


class OrderControlledVote(FrozenModel):
    evaluator_model_ref: SafeIdentifier
    pair_ref: SafeIdentifier
    case_ref: SafeIdentifier
    repeat_index: int = Field(ge=0, le=8)
    vote_profile: VoteProfile
    ab_attempt_ref: SafeIdentifier | None = None
    ba_attempt_ref: SafeIdentifier | None = None
    canonical_choice: CanonicalChoice
    canonical_first_verdict: ArmVerdict | None = None
    canonical_second_verdict: ArmVerdict | None = None
    status: OrderControlStatus

    @model_validator(mode="after")
    def validate_order_result(self) -> Self:
        if self.status in {
            OrderControlStatus.POSITION_CONFLICT,
            OrderControlStatus.INCOMPLETE,
        }:
            if self.canonical_choice is not CanonicalChoice.UNRESOLVED:
                raise ValueError("conflicted or incomplete order votes must be unresolved")
        elif self.status is OrderControlStatus.ABSTAINED:
            if self.canonical_choice is not CanonicalChoice.ABSTAIN:
                raise ValueError("abstentions must have the abstain label")
        elif self.canonical_choice in {CanonicalChoice.ABSTAIN, CanonicalChoice.UNRESOLVED}:
            raise ValueError("eligible order-controlled votes require a substantive label")
        if self.vote_profile is VoteProfile.TEXT_PAIR:
            if (
                self.canonical_first_verdict is not None
                or self.canonical_second_verdict is not None
            ):
                raise ValueError("text order-controlled vote cannot contain arm verdicts")
        elif (
            self.canonical_first_verdict is None or self.canonical_second_verdict is None
        ) and self.status in {OrderControlStatus.CONSISTENT, OrderControlStatus.ABSTAINED}:
            raise ValueError("complete image vote requires canonical arm verdicts")
        if self.status in {
            OrderControlStatus.INCOMPLETE,
            OrderControlStatus.POSITION_CONFLICT,
        } and (
            self.canonical_first_verdict is not None or self.canonical_second_verdict is not None
        ):
            raise ValueError("ineligible order-controlled vote cannot project arm verdicts")
        return self


class EligibleSubsetCoverage(FrozenModel):
    schema_version: Literal["model-panel-eligible-subset-v1"] = "model-panel-eligible-subset-v1"
    required_model_refs: tuple[SafeIdentifier, ...] = Field(min_length=2, max_length=MAX_MODELS)
    total_case_refs: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=MAX_ATTEMPTS)
    eligible_case_refs: tuple[SafeIdentifier, ...] = Field(default=(), max_length=MAX_ATTEMPTS)
    eligible_case_count: int = Field(ge=0, le=MAX_ATTEMPTS)
    total_case_count: int = Field(ge=1, le=MAX_ATTEMPTS)
    coverage: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        if self.required_model_refs != tuple(sorted(set(self.required_model_refs))):
            raise ValueError("required model refs must be unique and sorted")
        if self.total_case_refs != tuple(sorted(set(self.total_case_refs))):
            raise ValueError("total case refs must be unique and sorted")
        if self.eligible_case_refs != tuple(sorted(set(self.eligible_case_refs))):
            raise ValueError("eligible case refs must be unique and sorted")
        if not set(self.eligible_case_refs).issubset(self.total_case_refs):
            raise ValueError("eligible cases must be drawn from the total subset")
        if self.total_case_count != len(self.total_case_refs):
            raise ValueError("total case count does not match its refs")
        if self.eligible_case_count != len(self.eligible_case_refs):
            raise ValueError("eligible case count does not match its refs")
        expected = self.eligible_case_count / self.total_case_count
        if abs(self.coverage - expected) > 1e-12:
            raise ValueError("eligible-subset coverage does not match its counts")
        return self


class PanelConsensus(FrozenModel):
    schema_version: Literal["model-panel-consensus-v1"]
    pair_ref: SafeIdentifier
    case_ref: SafeIdentifier
    repeat_index: int = Field(ge=0, le=8)
    target_model_ref: SafeIdentifier | None = None
    quorum: int = Field(ge=2, le=MAX_MODELS)
    member_votes: tuple[OrderControlledVote, ...] = Field(min_length=1, max_length=MAX_MODELS)
    excluded_model_refs: tuple[SafeIdentifier, ...] = Field(default=(), max_length=MAX_MODELS)
    consensus_choice: CanonicalChoice
    supporting_models: tuple[SafeIdentifier, ...] = Field(default=(), max_length=MAX_MODELS)
    eligible_vote_count: int = Field(ge=0, le=MAX_MODELS)
    abstention_count: int = Field(ge=0, le=MAX_MODELS)
    position_conflict_count: int = Field(ge=0, le=MAX_MODELS)
    incomplete_count: int = Field(ge=0, le=MAX_MODELS)

    @model_validator(mode="after")
    def validate_consensus(self) -> Self:
        members = tuple(vote.evaluator_model_ref for vote in self.member_votes)
        if members != tuple(sorted(set(members))):
            raise ValueError("consensus members must be unique and sorted")
        excluded = tuple(self.excluded_model_refs)
        if excluded != tuple(sorted(set(excluded))):
            raise ValueError("excluded models must be unique and sorted")
        if self.target_model_ref is not None and self.target_model_ref in members:
            raise ValueError("target model cannot participate in its proxy consensus")
        if set(members) & set(excluded):
            raise ValueError("excluded models cannot appear as consensus members")
        eligible = tuple(
            vote for vote in self.member_votes if vote.status is OrderControlStatus.CONSISTENT
        )
        if self.eligible_vote_count != len(eligible):
            raise ValueError("eligible vote count does not match member votes")
        if self.abstention_count != sum(
            vote.status is OrderControlStatus.ABSTAINED for vote in self.member_votes
        ):
            raise ValueError("abstention count does not match member votes")
        if self.position_conflict_count != sum(
            vote.status is OrderControlStatus.POSITION_CONFLICT for vote in self.member_votes
        ):
            raise ValueError("position conflict count does not match member votes")
        if self.incomplete_count != sum(
            vote.status is OrderControlStatus.INCOMPLETE for vote in self.member_votes
        ):
            raise ValueError("incomplete count does not match member votes")
        supporters = tuple(sorted(self.supporting_models))
        if supporters != self.supporting_models or len(supporters) != len(set(supporters)):
            raise ValueError("supporting models must be unique and sorted")
        if not set(supporters).issubset(members):
            raise ValueError("supporting models must belong to the consensus")
        if self.consensus_choice is CanonicalChoice.UNRESOLVED:
            if supporters:
                raise ValueError("unresolved consensus cannot have supporting models")
        elif len(supporters) < self.quorum:
            raise ValueError("resolved consensus requires quorum support")
        return self


class AttemptJournalRecord(FrozenModel):
    schema_version: Literal["model-panel-journal-v1"]
    seq_no: int = Field(ge=0, le=MAX_ATTEMPTS * 2)
    event_kind: JournalEventKind
    recorded_at: datetime
    attempt: PanelAttempt
    previous_event_sha256: Sha256Hex | None = None
    event_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        recorded = require_aware(self.recorded_at, label="journal timestamp")
        started = require_aware(self.attempt.started_at, label="attempt start")
        if recorded < started:
            raise ValueError("journal timestamp cannot precede the attempt start")
        if self.attempt.finished_at is not None:
            finished = require_aware(self.attempt.finished_at, label="attempt finish")
            if recorded < finished:
                raise ValueError("journal timestamp cannot precede the attempt finish")
        if self.seq_no == 0 and self.previous_event_sha256 is not None:
            raise ValueError("the first journal record cannot have a previous hash")
        if self.seq_no > 0 and self.previous_event_sha256 is None:
            raise ValueError("non-first journal records require a previous hash")
        expected_kind = (
            JournalEventKind.ATTEMPT_STARTED
            if self.attempt.status is AttemptStatus.STARTED
            else JournalEventKind.ATTEMPT_TERMINAL
        )
        if self.event_kind is not expected_kind:
            raise ValueError("journal event kind does not match attempt status")
        payload = self.model_dump(mode="json", exclude={"event_sha256"})
        if evidence_sha256(payload) != self.event_sha256:
            raise ValueError("journal record hash does not match its canonical payload")
        return self


class ArtifactHashEntry(FrozenModel):
    artifact_ref: SafeIdentifier
    media_type: SafeIdentifier
    byte_size: int = Field(ge=1, le=128 * 1024 * 1024)
    sha256: Sha256Hex


class ArtifactHashes(FrozenModel):
    schema_version: Literal["model-panel-artifact-hashes-v1"]
    run_ref: SafeIdentifier
    manifest_sha256: Sha256Hex
    journal_tail_sha256: Sha256Hex
    artifacts: tuple[ArtifactHashEntry, ...] = Field(min_length=1, max_length=128)
    artifact_hashes_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_hashes(self) -> Self:
        refs = tuple(item.artifact_ref for item in self.artifacts)
        if refs != tuple(sorted(set(refs))):
            raise ValueError("artifact hash entries must be unique and sorted")
        payload = self.model_dump(mode="json", exclude={"artifact_hashes_sha256"})
        if evidence_sha256(payload) != self.artifact_hashes_sha256:
            raise ValueError("artifact-hashes SHA-256 does not match its canonical payload")
        return self


def canonicalize_choice(
    choice: PresentedChoice,
    order: PresentationOrder,
) -> CanonicalChoice:
    if choice is PresentedChoice.TIE:
        return CanonicalChoice.TIE
    if choice is PresentedChoice.ABSTAIN:
        return CanonicalChoice.ABSTAIN
    if order is PresentationOrder.AB:
        return CanonicalChoice.FIRST if choice is PresentedChoice.A else CanonicalChoice.SECOND
    return CanonicalChoice.SECOND if choice is PresentedChoice.A else CanonicalChoice.FIRST


def canonicalize_arm_verdicts(
    presented_a: ArmVerdict | None,
    presented_b: ArmVerdict | None,
    order: PresentationOrder,
) -> tuple[ArmVerdict | None, ArmVerdict | None]:
    if order is PresentationOrder.AB:
        return presented_a, presented_b
    return presented_b, presented_a
