"""Strict, hash-bound schemas for the local Agent retrieval live A/B."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

CASE_SCHEMA_VERSION: Literal["agent-retrieval-live-ab-case-v1"] = (
    "agent-retrieval-live-ab-case-v1"
)
ORACLE_SCHEMA_VERSION: Literal["agent-retrieval-live-ab-oracle-v1"] = (
    "agent-retrieval-live-ab-oracle-v1"
)
MANIFEST_SCHEMA_VERSION: Literal["agent-retrieval-live-ab-manifest-v3"] = (
    "agent-retrieval-live-ab-manifest-v3"
)
AUTHORIZATION_SCHEMA_VERSION: Literal["agent-retrieval-live-ab-authorization-v3"] = (
    "agent-retrieval-live-ab-authorization-v3"
)
ATTEMPT_SCHEMA_VERSION: Literal["agent-retrieval-live-ab-attempt-v3"] = (
    "agent-retrieval-live-ab-attempt-v3"
)
REPORT_SCHEMA_VERSION: Literal["agent-retrieval-live-ab-report-v3"] = (
    "agent-retrieval-live-ab-report-v3"
)
LIVE_AUTHORIZATION_ACKNOWLEDGEMENT: Literal[
    "I_AUTHORIZE_AGENT_RETRIEVAL_COMPATIBILITY_CANARY_V3"
] = "I_AUTHORIZE_AGENT_RETRIEVAL_COMPATIBILITY_CANARY_V3"
EVALUATION_POLICY_VERSION: Literal[
    "agent-retrieval-live-ab-policy-v3-compatibility-canary-only"
] = "agent-retrieval-live-ab-policy-v3-compatibility-canary-only"
EXECUTION_MODE: Literal["compatibility_canary_only"] = "compatibility_canary_only"

CASE_COUNT = 12
REPETITIONS = 3
MAX_AGENT_ATTEMPTS = CASE_COUNT * REPETITIONS * 2
MAX_AGENT_DECISIONS = MAX_AGENT_ATTEMPTS * 4
MAX_PLANNER_REQUESTS = 108
MAX_RERANK_REQUESTS = 108
MAX_EMBEDDING_REQUESTS = 108
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20_260_902
SCHEDULE_SEED = 20_260_902
CANARY_ATTEMPTS = 2
AGENT_MODEL_TURNS_PER_ATTEMPT = 4
AGENT_TOOL_CALLS_PER_ATTEMPT = 4

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SafeIdentifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}$")]


def canonical_json_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=_json_default,
    ).encode("utf-8")


def evidence_sha256(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise TypeError("naive datetime is not canonical evidence")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"unsupported evidence type: {type(value).__name__}")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ExperimentArm(StrEnum):
    RAW = "raw_query"
    ENHANCED = "rewrite_rrf_rerank"


class CaseCategory(StrEnum):
    EVIDENCE = "evidence_search"
    EVENT = "event_detail"
    BRAND = "brand_context"
    MULTI_TOOL = "evidence_brand_multi_tool"
    COPY_VALIDATION = "copy_validation"
    SAFETY = "safety_refusal"


class TargetKind(StrEnum):
    EVIDENCE = "evidence"
    BRAND = "brand_context"


class ExpectedTerminal(StrEnum):
    COMPLETED = "completed"
    REFUSED = "refused"


class AttemptExecutionStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class Capability(StrEnum):
    AGENT = "agent"
    PLANNER = "planner"
    RERANKER = "reranker"
    EMBEDDING = "embedding"


class LiveAbCase(_FrozenModel):
    schema_version: Literal["agent-retrieval-live-ab-case-v1"]
    case_id: SafeIdentifier
    category: CaseCategory
    query: str = Field(min_length=1, max_length=500)
    retrieval_sensitive: bool


class RelevanceQrel(_FrozenModel):
    target_kind: TargetKind
    target_id: str = Field(min_length=1, max_length=80)
    relevance: int = Field(ge=1, le=3)


class ExactArgument(_FrozenModel):
    tool: SafeIdentifier
    key: SafeIdentifier
    value: str = Field(min_length=1, max_length=500)


class CaseOracle(_FrozenModel):
    schema_version: Literal["agent-retrieval-live-ab-oracle-v1"]
    case_id: SafeIdentifier
    label_source: Literal["codex_seed_v1"] = "codex_seed_v1"
    required_tools: tuple[SafeIdentifier, ...] = Field(default=(), max_length=4)
    allowed_tools: tuple[SafeIdentifier, ...] = Field(default=(), max_length=4)
    exact_arguments: tuple[ExactArgument, ...] = Field(default=(), max_length=4)
    qrels: tuple[RelevanceQrel, ...] = Field(default=(), max_length=16)
    expected_terminal: ExpectedTerminal
    expect_refusal: bool

    @model_validator(mode="after")
    def validate_oracle(self) -> Self:
        if len(self.required_tools) != len(set(self.required_tools)):
            raise ValueError("required tools must be unique")
        if len(self.allowed_tools) != len(set(self.allowed_tools)):
            raise ValueError("allowed tools must be unique")
        if not set(self.required_tools).issubset(self.allowed_tools):
            raise ValueError("required tools must be allowed")
        qrel_keys = tuple((item.target_kind, item.target_id) for item in self.qrels)
        if len(qrel_keys) != len(set(qrel_keys)):
            raise ValueError("qrels must be unique")
        if self.expect_refusal != (self.expected_terminal is ExpectedTerminal.REFUSED):
            raise ValueError("refusal label and terminal must agree")
        return self


class DatabaseSnapshot(_FrozenModel):
    fingerprint: Sha256Hex
    table_counts: dict[SafeIdentifier, int]
    maximum_timestamps: dict[SafeIdentifier, str | None]


class ProviderIdentity(_FrozenModel):
    provider: SafeIdentifier
    model: SafeIdentifier


class CapabilityLimits(_FrozenModel):
    agent_attempts: Literal[2] = 2
    agent_decisions: Literal[8] = 8
    planner_requests: Literal[4] = 4
    rerank_requests: Literal[4] = 4
    embedding_requests: Literal[4] = 4


class RunManifest(_FrozenModel):
    schema_version: Literal["agent-retrieval-live-ab-manifest-v3"]
    evaluation_policy_version: Literal[
        "agent-retrieval-live-ab-policy-v3-compatibility-canary-only"
    ]
    execution_mode: Literal["compatibility_canary_only"]
    run_ref: SafeIdentifier
    created_at: datetime
    git_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    source_sha256: Sha256Hex
    worktree_dirty: bool
    dataset_sha256: Sha256Hex
    oracle_sha256: Sha256Hex
    database_snapshot: DatabaseSnapshot
    valid_on: date
    registry_sha256: Sha256Hex
    selected_case_ids: tuple[SafeIdentifier, ...]
    case_count: Literal[12] = 12
    repetitions: Literal[3] = 3
    arms: tuple[ExperimentArm, ExperimentArm]
    agent_identity: ProviderIdentity
    planner_identity: ProviderIdentity
    reranker_identity: ProviderIdentity
    embedding_identity: ProviderIdentity
    brand_retrieval_version: SafeIdentifier
    temperature: Literal[0] = 0
    schedule_seed: Literal[20260902] = 20_260_902
    bootstrap_seed: Literal[20260902] = 20_260_902
    bootstrap_samples: Literal[10000] = 10_000
    canary_attempts: Literal[2] = 2
    limits: CapabilityLimits
    manifest_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("manifest timestamp must be timezone-aware")
        if len(self.selected_case_ids) != CASE_COUNT:
            raise ValueError("manifest must bind exactly twelve cases")
        if len(self.selected_case_ids) != len(set(self.selected_case_ids)):
            raise ValueError("manifest case IDs must be unique")
        if self.arms != (ExperimentArm.RAW, ExperimentArm.ENHANCED):
            raise ValueError("manifest arms are not canonical")
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if evidence_sha256(payload) != self.manifest_sha256:
            raise ValueError("manifest SHA-256 does not match canonical payload")
        return self


class LiveAuthorization(_FrozenModel):
    schema_version: Literal["agent-retrieval-live-ab-authorization-v3"]
    manifest_sha256: Sha256Hex
    approved_at: datetime
    approved_by_ref: SafeIdentifier
    agent_attempt_limit: Literal[2] = 2
    acknowledgement: Literal["I_AUTHORIZE_AGENT_RETRIEVAL_COMPATIBILITY_CANARY_V3"]

    @model_validator(mode="after")
    def timezone_is_required(self) -> Self:
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise ValueError("authorization timestamp must be timezone-aware")
        return self


class CapabilityCounts(_FrozenModel):
    agent: int = Field(default=0, ge=0, le=MAX_AGENT_DECISIONS)
    planner: int = Field(default=0, ge=0, le=MAX_PLANNER_REQUESTS)
    reranker: int = Field(default=0, ge=0, le=MAX_RERANK_REQUESTS)
    embedding: int = Field(default=0, ge=0, le=MAX_EMBEDDING_REQUESTS)


class SafeToolObservation(_FrozenModel):
    name: SafeIdentifier
    succeeded: bool
    argument_keys: tuple[SafeIdentifier, ...] = Field(default=(), max_length=16)
    exact_arguments: dict[SafeIdentifier, str] = Field(default_factory=dict)
    citation_ids: tuple[str, ...] = Field(default=(), max_length=20)
    error_code: str | None = Field(default=None, max_length=120)


class SafeClaimObservation(_FrozenModel):
    kind: SafeIdentifier
    text_sha256: Sha256Hex
    citation_ids: tuple[str, ...] = Field(default=(), max_length=5)


class AttemptScore(_FrozenModel):
    task_success: bool
    terminal_match: bool
    tool_precision: float = Field(ge=0, le=1)
    tool_recall: float = Field(ge=0, le=1)
    argument_valid_rate: float = Field(ge=0, le=1)
    citation_precision: float = Field(ge=0, le=1)
    citation_coverage: float = Field(ge=0, le=1)
    unsupported_claim_rate: float = Field(ge=0, le=1)
    refusal_correct: bool
    hit_at_3: float | None = Field(default=None, ge=0, le=1)
    recall_at_3: float | None = Field(default=None, ge=0, le=1)
    mrr_at_3: float | None = Field(default=None, ge=0, le=1)
    ndcg_at_3: float | None = Field(default=None, ge=0, le=1)
    target_citation_coverage: float | None = Field(default=None, ge=0, le=1)
    failure_codes: tuple[SafeIdentifier, ...] = Field(default=(), max_length=24)


class AttemptObservation(_FrozenModel):
    schema_version: Literal["agent-retrieval-live-ab-attempt-v3"]
    attempt_ref: SafeIdentifier
    schedule_ordinal: int = Field(ge=1, le=MAX_AGENT_ATTEMPTS)
    canary: bool
    manifest_sha256: Sha256Hex
    authorization_sha256: Sha256Hex
    case_id: SafeIdentifier
    repetition: int = Field(ge=1, le=REPETITIONS)
    arm: ExperimentArm
    execution_status: AttemptExecutionStatus
    terminal_status: SafeIdentifier
    error_code: str | None = Field(default=None, max_length=120)
    summary_sha256: Sha256Hex
    tools: tuple[SafeToolObservation, ...] = Field(default=(), max_length=4)
    claims: tuple[SafeClaimObservation, ...] = Field(default=(), max_length=8)
    observed_citation_ids: tuple[str, ...] = Field(default=(), max_length=20)
    duration_ms: int = Field(ge=0, le=120_000)
    model_latency_ms: int = Field(ge=0, le=120_000)
    tool_latency_ms: int = Field(ge=0, le=120_000)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    capability_counts: CapabilityCounts
    capability_failure_counts: dict[SafeIdentifier, int] = Field(default_factory=dict)
    embedding_cache_hits: int = Field(ge=0)
    embedding_cache_misses: int = Field(ge=0)
    score: AttemptScore


class MetricEstimate(_FrozenModel):
    raw: float | None
    enhanced: float | None
    delta: float | None
    ci_low: float | None
    ci_high: float | None
    paired_case_count: int = Field(ge=0, le=CASE_COUNT)
    expected_case_count: int = Field(ge=1, le=CASE_COUNT)
    paired_matrix_complete: bool
    supports_uplift_claim: bool


class ArmSummary(_FrozenModel):
    arm: ExperimentArm
    attempt_count: int = Field(ge=0, le=MAX_AGENT_ATTEMPTS)
    task_success_rate: float = Field(ge=0, le=1)
    all_three_pass_rate: float = Field(ge=0, le=1)
    terminal_accuracy: float = Field(ge=0, le=1)
    tool_precision: float = Field(ge=0, le=1)
    tool_recall: float = Field(ge=0, le=1)
    citation_precision: float = Field(ge=0, le=1)
    citation_coverage: float = Field(ge=0, le=1)
    unsupported_claim_rate: float = Field(ge=0, le=1)
    refusal_accuracy: float = Field(ge=0, le=1)
    p50_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)


class PairedReport(_FrozenModel):
    schema_version: Literal["agent-retrieval-live-ab-report-v3"]
    run_ref: SafeIdentifier
    manifest_sha256: Sha256Hex
    label_source: Literal["codex_seed_v1"] = "codex_seed_v1"
    completed_attempts: int = Field(ge=0, le=CANARY_ATTEMPTS)
    expected_attempts: Literal[72] = 72
    complete: Literal[False] = False
    canary_passed: bool
    circuit_breaker_reason: SafeIdentifier | None = None
    retrieval_case_count: Literal[8] = 8
    negative_control_case_count: Literal[4] = 4
    arms: tuple[ArmSummary, ArmSummary]
    retrieval_estimates: dict[SafeIdentifier, MetricEstimate]
    all_case_estimates: dict[SafeIdentifier, MetricEstimate]
    negative_control_estimates: dict[SafeIdentifier, MetricEstimate]
    capability_counts: CapabilityCounts
    capability_counts_complete: bool
    started_attempt_count: int = Field(default=0, ge=0, le=MAX_AGENT_ATTEMPTS)
    provider_failure_count: int = Field(ge=0)
    bounded_run_failure_count: int = Field(default=0, ge=0)
    executor_failure_count: int = Field(default=0, ge=0)
    terminal_failure_counts_by_arm: dict[SafeIdentifier, dict[SafeIdentifier, int]] = Field(
        default_factory=dict
    )
    fallback_or_failure_codes: dict[SafeIdentifier, int]
    bad_case_ids: tuple[SafeIdentifier, ...]
    conclusion: str = Field(min_length=1, max_length=1_200)
    validity_notes: tuple[str, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_compatibility_report_boundary(self) -> Self:
        limits = CapabilityLimits()
        counts = self.capability_counts
        if (
            counts.agent > limits.agent_decisions
            or counts.planner > limits.planner_requests
            or counts.reranker > limits.rerank_requests
            or counts.embedding > limits.embedding_requests
        ):
            raise ValueError("v3 report capability counts exceed the authorization")
        if self.canary_passed and self.completed_attempts != CANARY_ATTEMPTS:
            raise ValueError("a passing compatibility canary requires exactly two attempts")
        return self
