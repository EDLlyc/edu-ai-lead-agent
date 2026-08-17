from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol
from uuid import UUID

from app.domain.agent_workbench import AgentModelErrorCode, ProposedAgentAnswer
from app.domain.brand_knowledge import BrandAudience, BrandDocumentKind, BrandRetrievalHit
from app.domain.copy_generation import ActiveBrandContext, EligibleEvidence, LockedTopicContext

_SAFE_CALL_ID = re.compile(r"[A-Za-z0-9_.:-]{1,120}")
_SAFE_TOOL_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")


@dataclass(frozen=True, slots=True)
class AgentEvidenceRecord:
    evidence: EligibleEvidence
    event_id: UUID
    event_version_id: UUID
    source_id: UUID
    event_title: str

    def __post_init__(self) -> None:
        if not self.event_title.strip() or len(self.event_title) > 500:
            raise ValueError("agent evidence event title must be bounded and non-blank")


@dataclass(frozen=True, slots=True)
class AgentEventMemberRecord:
    candidate_id: UUID
    title: str
    url: str
    published_at: datetime | None
    source_ids: tuple[UUID, ...]
    source_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.title.strip() or not self.url.strip():
            raise ValueError("agent event member metadata must be non-blank")
        if self.published_at is not None and self.published_at.tzinfo is None:
            raise ValueError("agent event member publication time must be timezone-aware")
        if len(self.source_ids) != len(self.source_names):
            raise ValueError("agent event member source projections must align")


@dataclass(frozen=True, slots=True)
class AgentEventRecord:
    event_id: UUID
    current_version_id: UUID
    representative_title: str
    summary: str | None
    source_diversity: int
    categories: tuple[str, ...]
    members: tuple[AgentEventMemberRecord, ...]

    def __post_init__(self) -> None:
        if not self.representative_title.strip():
            raise ValueError("agent event title must be non-blank")
        if self.source_diversity < 0:
            raise ValueError("agent event source diversity must be non-negative")


@dataclass(frozen=True, slots=True)
class CopyValidationContext:
    copy_run_id: UUID
    topic: LockedTopicContext
    brand_context: tuple[ActiveBrandContext, ...]
    rule_version: str

    def __post_init__(self) -> None:
        if not self.rule_version.strip() or len(self.rule_version) > 120:
            raise ValueError("copy validation rule version must be bounded and non-blank")


class AgentKnowledgeReader(Protocol):
    async def search_evidence(
        self,
        *,
        query: str,
        limit: int,
        candidate_id: UUID | None,
    ) -> tuple[AgentEvidenceRecord, ...]: ...

    async def get_event(self, event_id: UUID) -> AgentEventRecord: ...

    async def retrieve_brand_context(
        self,
        *,
        query: str,
        audience: BrandAudience,
        document_kinds: tuple[BrandDocumentKind, ...],
        valid_on: date,
        limit: int,
    ) -> tuple[BrandRetrievalHit, ...]: ...

    async def load_copy_validation_context(
        self,
        *,
        copy_run_id: UUID,
        brand_chunk_ids: tuple[UUID, ...],
    ) -> CopyValidationContext: ...


@dataclass(frozen=True, slots=True)
class AgentToolCall:
    call_id: str
    name: str
    arguments_json: str

    def __post_init__(self) -> None:
        if _SAFE_CALL_ID.fullmatch(self.call_id) is None:
            raise ValueError("agent tool-call ID is invalid")
        if _SAFE_TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError("agent tool name is invalid")
        if not self.arguments_json or len(self.arguments_json.encode("utf-8")) > 16 * 1024:
            raise ValueError("agent tool arguments are empty or too large")


@dataclass(frozen=True, slots=True)
class AgentToolObservation:
    call_id: str
    name: str
    status: Literal["succeeded", "failed"]
    content_json: str
    error_code: str | None = None

    def __post_init__(self) -> None:
        if _SAFE_CALL_ID.fullmatch(self.call_id) is None:
            raise ValueError("agent observation call ID is invalid")
        if _SAFE_TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError("agent observation tool name is invalid")
        if not self.content_json or len(self.content_json.encode("utf-8")) > 32 * 1024:
            raise ValueError("agent observation content is empty or too large")
        if (self.status == "failed") != (self.error_code is not None):
            raise ValueError("agent observation error metadata is inconsistent")


@dataclass(frozen=True, slots=True)
class AgentToolExchange:
    calls: tuple[AgentToolCall, ...]
    observations: tuple[AgentToolObservation, ...]

    def __post_init__(self) -> None:
        if not self.calls or len(self.calls) != len(self.observations):
            raise ValueError("agent tool exchange must contain aligned calls and observations")
        for call, observation in zip(self.calls, self.observations, strict=True):
            if call.call_id != observation.call_id or call.name != observation.name:
                raise ValueError("agent tool exchange call and observation identities differ")


@dataclass(frozen=True, slots=True)
class ModelDecisionRequest:
    query: str
    tools: tuple[Mapping[str, object], ...]
    history: tuple[AgentToolExchange, ...]

    def __post_init__(self) -> None:
        if not self.query.strip() or len(self.query) > 500:
            raise ValueError("agent model query must be 1-500 characters")
        if not self.tools or len(self.tools) > 16:
            raise ValueError("agent model tools must be non-empty and bounded")


@dataclass(frozen=True, slots=True)
class ModelDecisionMetadata:
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    latency_ms: int = 0
    finish_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip() or len(self.provider) > 80:
            raise ValueError("agent model provider identity is invalid")
        if not self.model.strip() or len(self.model) > 120:
            raise ValueError("agent model identity is invalid")
        if (
            min(
                self.prompt_tokens,
                self.completion_tokens,
                self.reasoning_tokens,
                self.latency_ms,
            )
            < 0
        ):
            raise ValueError("agent model usage must be non-negative")
        if self.finish_reason is not None and len(self.finish_reason) > 80:
            raise ValueError("agent model finish reason is too large")


@dataclass(frozen=True, slots=True)
class ToolCallsDecision:
    calls: tuple[AgentToolCall, ...]
    metadata: ModelDecisionMetadata

    def __post_init__(self) -> None:
        if not self.calls or len(self.calls) > 4:
            raise ValueError("agent model must return one to four tool calls")
        call_ids = tuple(call.call_id for call in self.calls)
        if len(set(call_ids)) != len(call_ids):
            raise ValueError("agent model tool-call IDs must be unique")


@dataclass(frozen=True, slots=True)
class FinalAnswerDecision:
    answer: ProposedAgentAnswer
    metadata: ModelDecisionMetadata


ModelDecision = ToolCallsDecision | FinalAnswerDecision


class ToolCallingModel(Protocol):
    async def decide(self, request: ModelDecisionRequest) -> ModelDecision: ...


class MonotonicClock(Protocol):
    def monotonic(self) -> float: ...


class AgentModelFailure(Exception):
    def __init__(self, code: AgentModelErrorCode) -> None:
        super().__init__(code.value)
        self.code = code
