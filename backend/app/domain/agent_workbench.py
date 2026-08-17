from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from uuid import UUID

JsonScalar = str | int | float | bool | None
SafeTraceValue = JsonScalar | tuple[str, ...]


class AgentRunStatus(StrEnum):
    COMPLETED = "completed"
    REFUSED = "refused"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentClaimKind(StrEnum):
    EXTERNAL_FACT = "external_fact"
    BRAND_STATEMENT = "brand_statement"
    OPINION = "opinion"


class AgentCitationKind(StrEnum):
    EVIDENCE = "evidence"
    BRAND_CONTEXT = "brand_context"


class AgentTraceKind(StrEnum):
    MODEL_DECISION = "model_decision"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINAL = "final"
    ERROR = "error"


class AgentTraceStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AgentToolErrorCode(StrEnum):
    INVALID_ARGUMENTS = "agent_tool_invalid_arguments"
    UNKNOWN = "agent_tool_unknown"
    TIMEOUT = "agent_tool_timeout"
    UNAVAILABLE = "agent_tool_unavailable"
    NOT_FOUND = "agent_tool_not_found"
    OUTPUT_TOO_LARGE = "agent_tool_output_too_large"


class AgentModelErrorCode(StrEnum):
    UNAVAILABLE = "agent_model_unavailable"
    INVALID_OUTPUT = "agent_model_invalid_output"


@dataclass(frozen=True, slots=True)
class AgentRunLimits:
    max_model_turns: int = 4
    max_tool_calls: int = 4
    model_timeout_seconds: float = 15.0
    total_timeout_seconds: float = 30.0
    recursion_limit: int = 16
    max_model_response_bytes: int = 256 * 1024
    max_tool_argument_bytes: int = 16 * 1024
    max_tool_result_bytes: int = 32 * 1024
    max_run_response_bytes: int = 128 * 1024

    def __post_init__(self) -> None:
        if not 1 <= self.max_model_turns <= 4:
            raise ValueError("agent model-turn budget must be between one and four")
        if not 1 <= self.max_tool_calls <= 4:
            raise ValueError("agent tool-call budget must be between one and four")
        if not 0 < self.model_timeout_seconds <= self.total_timeout_seconds <= 30:
            raise ValueError("agent timeout budget is invalid")
        if self.recursion_limit < self.max_model_turns + self.max_tool_calls:
            raise ValueError("agent graph recursion limit cannot cover the business budget")
        if (
            min(
                self.max_model_response_bytes,
                self.max_tool_argument_bytes,
                self.max_tool_result_bytes,
                self.max_run_response_bytes,
            )
            <= 0
        ):
            raise ValueError("agent byte budgets must be positive")


@dataclass(frozen=True, slots=True)
class AgentClaim:
    text: str
    kind: AgentClaimKind
    citation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.text.strip() or len(self.text) > 400:
            raise ValueError("agent claim text must be 1-400 characters")
        if len(self.citation_ids) > 5 or len(set(self.citation_ids)) != len(self.citation_ids):
            raise ValueError("agent claim citations must be unique and bounded")
        if any(
            not citation_id.strip() or len(citation_id) > 80 for citation_id in self.citation_ids
        ):
            raise ValueError("agent citation IDs must be bounded and non-blank")


@dataclass(frozen=True, slots=True)
class ProposedAgentAnswer:
    status: Literal["completed", "refused"]
    summary: str
    claims: tuple[AgentClaim, ...] = ()
    refusal_code: Literal["insufficient_evidence", "policy_refused"] | None = None

    def __post_init__(self) -> None:
        if not self.summary.strip() or len(self.summary) > 1_200:
            raise ValueError("agent summary must be 1-1200 characters")
        if len(self.claims) > 8:
            raise ValueError("agent answer cannot contain more than eight claims")
        if self.status == "refused" and self.claims:
            raise ValueError("a refused agent answer cannot contain claims")
        if self.status == "completed" and self.refusal_code is not None:
            raise ValueError("a completed agent answer cannot contain a refusal code")


@dataclass(frozen=True, slots=True)
class AgentCitation:
    id: str
    kind: AgentCitationKind
    source_name: str
    title: str
    url: str | None
    evidence_eligible: bool

    def __post_init__(self) -> None:
        if not self.id.strip() or len(self.id) > 80:
            raise ValueError("agent citation ID must be bounded and non-blank")
        if not self.source_name.strip() or len(self.source_name) > 120:
            raise ValueError("agent citation source name must be 1-120 characters")
        if not self.title.strip() or len(self.title) > 200:
            raise ValueError("agent citation title must be 1-200 characters")
        if self.kind is AgentCitationKind.EVIDENCE:
            if not self.evidence_eligible or self.url is None:
                raise ValueError("evidence citations require an eligible public URL")
        elif self.evidence_eligible or self.url is not None:
            raise ValueError("brand citations cannot be factual evidence or expose a URL")


@dataclass(frozen=True, slots=True)
class AgentTraceStep:
    ordinal: int
    kind: AgentTraceKind
    status: AgentTraceStatus
    code: str | None = None
    tool_name: str | None = None
    call_id: str | None = None
    safe_arguments: tuple[tuple[str, SafeTraceValue], ...] = ()
    duration_ms: int = 0
    item_count: int | None = None
    issue_count: int | None = None
    citation_ids: tuple[str, ...] = ()
    provider: str | None = None
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0

    def __post_init__(self) -> None:
        if self.ordinal < 1 or self.duration_ms < 0:
            raise ValueError("agent trace ordinal and duration must be non-negative")
        if min(self.prompt_tokens, self.completion_tokens, self.reasoning_tokens) < 0:
            raise ValueError("agent trace token usage must be non-negative")
        if len(self.citation_ids) > 20:
            raise ValueError("agent trace citation projection is too large")


@dataclass(frozen=True, slots=True)
class AgentRunMetrics:
    model_turns: int
    tool_calls: int
    successful_tool_calls: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    model_latency_ms: int
    tool_latency_ms: int
    duration_ms: int

    def __post_init__(self) -> None:
        values = (
            self.model_turns,
            self.tool_calls,
            self.successful_tool_calls,
            self.prompt_tokens,
            self.completion_tokens,
            self.reasoning_tokens,
            self.model_latency_ms,
            self.tool_latency_ms,
            self.duration_ms,
        )
        if any(value < 0 for value in values):
            raise ValueError("agent metrics must be non-negative")
        if self.successful_tool_calls > self.tool_calls:
            raise ValueError("successful tool calls cannot exceed total tool calls")


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    run_id: UUID
    status: AgentRunStatus
    summary: str
    claims: tuple[AgentClaim, ...]
    citations: tuple[AgentCitation, ...]
    steps: tuple[AgentTraceStep, ...]
    metrics: AgentRunMetrics
    error_code: str | None = None

    def __post_init__(self) -> None:
        if len(self.summary) > 1_200:
            raise ValueError("agent result summary is too large")
        if len(self.claims) > 8 or len(self.citations) > 20:
            raise ValueError("agent result collections exceed their bounds")
        if any(step.ordinal != index for index, step in enumerate(self.steps, 1)):
            raise ValueError("agent trace ordinals must be contiguous")
