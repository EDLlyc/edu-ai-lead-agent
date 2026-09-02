from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

EXECUTION_GOVERNANCE_POLICY_VERSION: Final = "execution-governance-v1"
DEFAULT_MAX_AGENT_DEPTH: Final = 1
HARD_MAX_AGENT_DEPTH: Final = 2
DELEGATION_THRESHOLD_PERCENT: Final = 70

_SAFE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SAFE_NAME = re.compile(r"[a-z][a-z0-9_.:-]{0,79}")
_SAFE_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9.+-]{0,63}/[a-z0-9][a-z0-9.+-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ExecutionRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    PLANNER = "planner"
    WORKER = "worker"
    REVIEWER = "reviewer"


class ExecutionRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionEventKind(StrEnum):
    RUN_STARTED = "run_started"
    RUN_FINISHED = "run_finished"
    RUN_FAILED = "run_failed"
    NODE_STARTED = "node_started"
    NODE_FINISHED = "node_finished"
    NODE_FAILED = "node_failed"
    MODEL_REQUESTED = "model_requested"
    MODEL_RESULT = "model_result"
    TOOL_REQUESTED = "tool_requested"
    TOOL_RESULT = "tool_result"
    ARTIFACT_PRODUCED = "artifact_produced"
    BUDGET_DENIED = "budget_denied"
    PERMISSION_DENIED = "permission_denied"


class ExecutionEventStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"


class ArtifactKind(StrEnum):
    ARTICLE = "article"
    MARKDOWN = "markdown"
    HTML = "html"
    IMAGE = "image"
    REPORT = "report"
    CHECKPOINT = "checkpoint"
    OTHER = "other"


class ArtifactLifecycleStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class CapabilityAccess(StrEnum):
    READ = "read"
    PLAN = "plan"
    CHECK = "check"
    BUSINESS_WRITE = "business_write"


class GovernanceErrorCode(StrEnum):
    BUDGET_EXHAUSTED = "budget_exhausted"
    RECURSION_DISABLED = "recursion_disabled"
    DEPTH_EXHAUSTED = "depth_exhausted"
    DELEGATION_THRESHOLD_REACHED = "delegation_threshold_reached"
    CHILD_LIMIT_EXHAUSTED = "child_limit_exhausted"
    CAPABILITY_UNKNOWN = "capability_unknown"
    ROLE_FORBIDDEN = "role_forbidden"
    TASK_SCOPE_FORBIDDEN = "task_scope_forbidden"
    ARTIFACT_SCOPE_FORBIDDEN = "artifact_scope_forbidden"
    WRITE_FORBIDDEN = "write_forbidden"
    ARGUMENT_TOO_LARGE = "argument_too_large"
    RESULT_TOO_LARGE = "result_too_large"
    CAPABILITY_TIMEOUT = "capability_timeout"
    CAPABILITY_FAILED = "capability_failed"
    CAPABILITY_CANCELLED = "capability_cancelled"
    INVALID_EVENT = "invalid_event"
    UNKNOWN_ARTIFACT = "unknown_artifact"
    ALLOCATION_NOT_ACTIVE = "allocation_not_active"


class GovernanceDeniedError(Exception):
    def __init__(self, code: GovernanceErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExecutionIdentity:
    run_id: UUID
    task_id: str
    agent_id: str

    def __post_init__(self) -> None:
        _validate_ref(self.task_id, "task")
        _validate_ref(self.agent_id, "agent")

    def as_dict(self) -> dict[str, str]:
        return {
            "run_id": str(self.run_id),
            "task_id": self.task_id,
            "agent_id": self.agent_id,
        }


@dataclass(frozen=True, slots=True)
class BudgetVector:
    elapsed_ms: int = 0
    model_turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    tool_result_bytes: int = 0
    artifact_bytes: int = 0

    def __post_init__(self) -> None:
        if any(value < 0 for value in self.values()):
            raise ValueError("execution budget values must be non-negative")

    def values(self) -> tuple[int, ...]:
        return (
            self.elapsed_ms,
            self.model_turns,
            self.input_tokens,
            self.output_tokens,
            self.tool_calls,
            self.tool_result_bytes,
            self.artifact_bytes,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "elapsed_ms": self.elapsed_ms,
            "model_turns": self.model_turns,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_calls": self.tool_calls,
            "tool_result_bytes": self.tool_result_bytes,
            "artifact_bytes": self.artifact_bytes,
        }


@dataclass(frozen=True, slots=True)
class BudgetLimits(BudgetVector):
    max_children: int = 0
    max_depth: int = DEFAULT_MAX_AGENT_DEPTH
    allow_child_agents: bool = False

    def __post_init__(self) -> None:
        BudgetVector.__post_init__(self)
        if self.elapsed_ms <= 0:
            raise ValueError("execution elapsed-time budget must be positive")
        if self.max_children < 0:
            raise ValueError("execution child budget must be non-negative")
        if not 0 <= self.max_depth <= HARD_MAX_AGENT_DEPTH:
            raise ValueError("execution depth exceeds the system hard limit")
        if not self.allow_child_agents and self.max_children != 0:
            raise ValueError("disabled child execution must have a zero child budget")
        if self.allow_child_agents and (self.max_children == 0 or self.max_depth == 0):
            raise ValueError("enabled child execution requires child and depth budgets")

    def ceiling_vector(self) -> BudgetVector:
        return BudgetVector(**BudgetVector.as_dict(self))

    def as_dict(self) -> dict[str, int | bool]:
        return {
            **BudgetVector.as_dict(self),
            "max_children": self.max_children,
            "max_depth": self.max_depth,
            "allow_child_agents": self.allow_child_agents,
        }


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    elapsed_ms: int = 0
    model_turns: int = 0
    input_tokens: int | None = 0
    output_tokens: int | None = 0
    tool_calls: int = 0
    tool_result_bytes: int = 0
    artifact_bytes: int = 0
    child_count: int = 0

    def __post_init__(self) -> None:
        values = (
            self.elapsed_ms,
            self.model_turns,
            self.tool_calls,
            self.tool_result_bytes,
            self.artifact_bytes,
            self.child_count,
        )
        if any(value < 0 for value in values):
            raise ValueError("execution usage values must be non-negative")
        if self.input_tokens is not None and self.input_tokens < 0:
            raise ValueError("execution input-token usage must be non-negative or unknown")
        if self.output_tokens is not None and self.output_tokens < 0:
            raise ValueError("execution output-token usage must be non-negative or unknown")

    def as_dict(self) -> dict[str, int | None]:
        return {
            "elapsed_ms": self.elapsed_ms,
            "model_turns": self.model_turns,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_calls": self.tool_calls,
            "tool_result_bytes": self.tool_result_bytes,
            "artifact_bytes": self.artifact_bytes,
            "child_count": self.child_count,
        }


@dataclass(frozen=True, slots=True)
class SafeExecutionEvent:
    identity: ExecutionIdentity
    event_id: UUID
    seq_no: int
    kind: ExecutionEventKind
    status: ExecutionEventStatus
    parent_event_id: UUID | None = None
    artifact_id: UUID | None = None
    target_name: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    error_code: str | None = None
    duration_ms: int = 0
    model_turns: int = 0
    input_tokens: int | None = 0
    output_tokens: int | None = 0
    tool_calls: int = 0
    result_bytes: int = 0

    def __post_init__(self) -> None:
        if (
            self.seq_no < 0
            or min(
                self.duration_ms,
                self.model_turns,
                self.tool_calls,
                self.result_bytes,
            )
            < 0
        ):
            raise ValueError("execution event counters must be non-negative")
        if self.input_tokens is not None and self.input_tokens < 0:
            raise ValueError("execution event input tokens must be non-negative or unknown")
        if self.output_tokens is not None and self.output_tokens < 0:
            raise ValueError("execution event output tokens must be non-negative or unknown")
        for value, label in (
            (self.target_name, "target"),
            (self.provider_name, "provider"),
            (self.model_name, "model"),
            (self.error_code, "error"),
        ):
            if value is not None:
                _validate_name(value, label)
        if self.kind is ExecutionEventKind.RUN_STARTED:
            if self.seq_no != 0 or self.parent_event_id is not None:
                raise ValueError("run-start event must be the root event")
        elif self.parent_event_id is None:
            raise ValueError("non-root execution event requires a parent event")
        if (self.kind is ExecutionEventKind.ARTIFACT_PRODUCED) != (self.artifact_id is not None):
            raise ValueError("artifact-produced events require exactly one artifact ID")
        if self.status is ExecutionEventStatus.DENIED and self.error_code is None:
            raise ValueError("denied execution events require a stable error code")

    def as_dict(self) -> dict[str, object]:
        return {
            **self.identity.as_dict(),
            "event_id": str(self.event_id),
            "seq_no": self.seq_no,
            "kind": self.kind.value,
            "status": self.status.value,
            "parent_event_id": (
                str(self.parent_event_id) if self.parent_event_id is not None else None
            ),
            "artifact_id": str(self.artifact_id) if self.artifact_id is not None else None,
            "target_name": self.target_name,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "error_code": self.error_code,
            "duration_ms": self.duration_ms,
            "model_turns": self.model_turns,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_calls": self.tool_calls,
            "result_bytes": self.result_bytes,
        }


@dataclass(frozen=True, slots=True)
class SafeEventDraft:
    identity: ExecutionIdentity
    event_id: UUID
    kind: ExecutionEventKind
    status: ExecutionEventStatus
    parent_event_id: UUID | None = None
    artifact_id: UUID | None = None
    target_name: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    error_code: str | None = None
    duration_ms: int = 0
    model_turns: int = 0
    input_tokens: int | None = 0
    output_tokens: int | None = 0
    tool_calls: int = 0
    result_bytes: int = 0

    def materialize(self, seq_no: int) -> SafeExecutionEvent:
        return SafeExecutionEvent(
            identity=self.identity,
            event_id=self.event_id,
            seq_no=seq_no,
            kind=self.kind,
            status=self.status,
            parent_event_id=self.parent_event_id,
            artifact_id=self.artifact_id,
            target_name=self.target_name,
            provider_name=self.provider_name,
            model_name=self.model_name,
            error_code=self.error_code,
            duration_ms=self.duration_ms,
            model_turns=self.model_turns,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            tool_calls=self.tool_calls,
            result_bytes=self.result_bytes,
        )


@dataclass(frozen=True, slots=True)
class ArtifactMetadata:
    identity: ExecutionIdentity
    artifact_id: UUID
    producer_event_id: UUID
    kind: ArtifactKind
    media_type: str
    byte_size: int
    sha256: str
    lifecycle_status: ArtifactLifecycleStatus = ArtifactLifecycleStatus.ACTIVE

    def __post_init__(self) -> None:
        if _SAFE_MEDIA_TYPE.fullmatch(self.media_type) is None:
            raise ValueError("artifact media type is invalid")
        if self.byte_size < 0:
            raise ValueError("artifact byte size must be non-negative")
        if _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("artifact SHA-256 must be lowercase hexadecimal")

    def as_dict(self) -> dict[str, object]:
        return {
            **self.identity.as_dict(),
            "artifact_id": str(self.artifact_id),
            "producer_event_id": str(self.producer_event_id),
            "kind": self.kind.value,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "lifecycle_status": self.lifecycle_status.value,
        }


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    name: str
    access: CapabilityAccess
    allowed_roles: frozenset[ExecutionRole]
    timeout_ms: int
    max_argument_bytes: int
    max_result_bytes: int
    task_scoped: bool = True
    artifact_scoped: bool = False

    def __post_init__(self) -> None:
        _validate_name(self.name, "capability")
        if not self.allowed_roles:
            raise ValueError("capability role allowlist cannot be empty")
        if not 1 <= self.timeout_ms <= 15 * 60 * 1000:
            raise ValueError("capability timeout must be between one and 900000 milliseconds")
        if not 1 <= self.max_argument_bytes <= 256 * 1024:
            raise ValueError("capability argument budget is invalid")
        if not 1 <= self.max_result_bytes <= 1024 * 1024:
            raise ValueError("capability result budget is invalid")


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    identity: ExecutionIdentity
    role: ExecutionRole
    capability_name: str
    target_task_id: str
    parent_event_id: UUID
    argument_bytes: int
    artifact_ids: tuple[UUID, ...] = ()
    expected_input_tokens: int = 0
    expected_output_tokens: int = 0
    model_turns: int = 0
    tool_calls: int = 1
    expected_artifact_bytes: int = 0

    def __post_init__(self) -> None:
        _validate_name(self.capability_name, "capability")
        _validate_ref(self.target_task_id, "target task")
        if (
            min(
                self.argument_bytes,
                self.expected_input_tokens,
                self.expected_output_tokens,
                self.model_turns,
                self.tool_calls,
                self.expected_artifact_bytes,
            )
            < 0
        ):
            raise ValueError("capability request usage must be non-negative")
        if len(self.artifact_ids) > 32 or len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("capability artifact scope must be unique and bounded")


def authorize_capability(
    definition: CapabilityDefinition,
    request: CapabilityRequest,
) -> None:
    if request.role not in definition.allowed_roles:
        raise GovernanceDeniedError(GovernanceErrorCode.ROLE_FORBIDDEN)
    if request.role in {ExecutionRole.ORCHESTRATOR, ExecutionRole.PLANNER} and (
        definition.access is CapabilityAccess.BUSINESS_WRITE
    ):
        raise GovernanceDeniedError(GovernanceErrorCode.WRITE_FORBIDDEN)
    if request.role is ExecutionRole.REVIEWER and definition.access in {
        CapabilityAccess.PLAN,
        CapabilityAccess.BUSINESS_WRITE,
    }:
        raise GovernanceDeniedError(GovernanceErrorCode.WRITE_FORBIDDEN)
    if definition.task_scoped and request.target_task_id != request.identity.task_id:
        raise GovernanceDeniedError(GovernanceErrorCode.TASK_SCOPE_FORBIDDEN)
    if definition.artifact_scoped and not request.artifact_ids:
        raise GovernanceDeniedError(GovernanceErrorCode.ARTIFACT_SCOPE_FORBIDDEN)
    if request.argument_bytes > definition.max_argument_bytes:
        raise GovernanceDeniedError(GovernanceErrorCode.ARGUMENT_TOO_LARGE)


def delegation_usage_percent(
    *,
    limits: BudgetLimits,
    usage: BudgetUsage,
    reserved: BudgetVector,
) -> int:
    pairs = (
        (usage.elapsed_ms + reserved.elapsed_ms, limits.elapsed_ms),
        (usage.model_turns + reserved.model_turns, limits.model_turns),
        (
            (usage.input_tokens or 0) + reserved.input_tokens,
            limits.input_tokens,
        ),
        (
            (usage.output_tokens or 0) + reserved.output_tokens,
            limits.output_tokens,
        ),
        (usage.tool_calls + reserved.tool_calls, limits.tool_calls),
        (
            usage.tool_result_bytes + reserved.tool_result_bytes,
            limits.tool_result_bytes,
        ),
        (usage.artifact_bytes + reserved.artifact_bytes, limits.artifact_bytes),
    )
    ratios = tuple((used * 100) // ceiling for used, ceiling in pairs if ceiling > 0)
    return max(ratios, default=0)


def _validate_ref(value: str, label: str) -> None:
    if _SAFE_REF.fullmatch(value) is None:
        raise ValueError(f"execution {label} identity is invalid")


def _validate_name(value: str, label: str) -> None:
    if _SAFE_NAME.fullmatch(value) is None:
        raise ValueError(f"execution {label} name is invalid")
