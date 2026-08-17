from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.errors import PolicyRejectedError
from app.core.security import normalize_public_https_url
from app.domain.agent_workbench import (
    AgentCitationKind,
    AgentClaimKind,
    AgentRunResult,
    AgentRunStatus,
    AgentTraceKind,
    AgentTraceStatus,
)
from app.domain.brand_knowledge import BrandDocumentKind
from app.schemas.copy_generation import MaterialDraft


def _validated_https_url(value: str) -> str:
    try:
        return normalize_public_https_url(value)
    except PolicyRejectedError:
        raise ValueError("citation URL must be a normalized public HTTPS URL") from None


HttpsUrl = Annotated[
    str,
    Field(min_length=9, max_length=2_000),
    AfterValidator(_validated_https_url),
]
TraceValue = str | int | float | bool | list[str] | None


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class SearchEvidenceArguments(_StrictModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=5)
    candidate_id: UUID | None = None


class EvidenceToolItem(_StrictModel):
    evidence_id: UUID
    event_id: UUID
    event_version_id: UUID
    candidate_id: UUID
    source_id: UUID
    source_name: str = Field(min_length=1, max_length=120)
    source_tier: Literal["A", "B"]
    title: str = Field(min_length=1, max_length=200)
    url: HttpsUrl
    published_at: datetime | None = None
    quote: str = Field(min_length=1, max_length=500)
    evidence_eligible: Literal[True] = True


class SearchEvidenceResult(_StrictModel):
    items: tuple[EvidenceToolItem, ...] = Field(default=(), max_length=5)


class GetEventArguments(_StrictModel):
    event_id: UUID


class EventMemberToolItem(_StrictModel):
    candidate_id: UUID
    title: str = Field(min_length=1, max_length=200)
    url: HttpsUrl
    published_at: datetime | None = None
    source_ids: tuple[UUID, ...] = Field(default=(), max_length=8)
    source_names: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def source_fields_align(self) -> Self:
        if len(self.source_ids) != len(self.source_names):
            raise ValueError("event member source projections must align")
        return self


class GetEventResult(_StrictModel):
    event_id: UUID
    current_version_id: UUID
    representative_title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=1_000)
    source_diversity: int = Field(ge=0)
    categories: tuple[str, ...] = Field(default=(), max_length=8)
    members: tuple[EventMemberToolItem, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def source_overview_is_globally_bounded(self) -> Self:
        if sum(len(member.source_ids) for member in self.members) > 8:
            raise ValueError("event source overview cannot contain more than eight sources")
        return self


class RetrieveBrandContextArguments(_StrictModel):
    query: str = Field(min_length=1, max_length=500)
    valid_on: date
    audience: Literal["parents"] = "parents"
    document_kinds: tuple[BrandDocumentKind, ...] = Field(default=(), max_length=4)
    limit: int = Field(default=5, ge=1, le=5)

    @field_validator("document_kinds")
    @classmethod
    def document_kinds_are_unique(
        cls, value: tuple[BrandDocumentKind, ...]
    ) -> tuple[BrandDocumentKind, ...]:
        if len(value) != len(set(value)):
            raise ValueError("brand document kinds must be unique")
        return value


class BrandContextToolItem(_StrictModel):
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    document_title: str = Field(min_length=1, max_length=200)
    document_kind: BrandDocumentKind
    excerpt: str = Field(min_length=1, max_length=500)
    tone_tags: tuple[str, ...] = Field(default=(), max_length=12)
    safety_tags: tuple[str, ...] = Field(default=(), max_length=12)
    evidence_eligible: Literal[False] = False


class RetrieveBrandContextResult(_StrictModel):
    items: tuple[BrandContextToolItem, ...] = Field(default=(), max_length=5)


class ValidateCopyArguments(_StrictModel):
    copy_run_id: UUID
    draft: MaterialDraft
    brand_chunk_ids: tuple[UUID, ...] = Field(default=(), max_length=16)

    @field_validator("brand_chunk_ids")
    @classmethod
    def brand_chunk_ids_are_unique(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("brand chunk IDs must be unique")
        return value


class CopyValidationIssue(_StrictModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    severity: Literal["warning", "error"]
    field: str | None = Field(default=None, max_length=80)
    claim_id: str | None = Field(default=None, max_length=80)


class ValidateCopyResult(_StrictModel):
    copy_run_id: UUID
    accepted: bool
    issues: tuple[CopyValidationIssue, ...] = Field(default=(), max_length=32)
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=24)
    brand_chunk_ids: tuple[UUID, ...] = Field(default=(), max_length=16)
    rule_version: str = Field(min_length=1, max_length=120)


class AgentProposedClaim(_StrictModel):
    text: str = Field(min_length=1, max_length=400)
    kind: AgentClaimKind
    citation_ids: tuple[str, ...] = Field(default=(), max_length=5)

    @field_validator("citation_ids")
    @classmethod
    def citation_ids_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("agent claim citation IDs must be unique")
        if any(not item or len(item) > 80 for item in value):
            raise ValueError("agent claim citation IDs must be bounded and non-blank")
        return value


class AgentProposedAnswer(_StrictModel):
    status: Literal["completed", "refused"]
    summary: str = Field(min_length=1, max_length=1_200)
    claims: tuple[AgentProposedClaim, ...] = Field(default=(), max_length=8)
    refusal_code: Literal["insufficient_evidence", "policy_refused"] | None = None

    @model_validator(mode="after")
    def refused_answer_has_no_claims(self) -> Self:
        if self.status == "refused" and self.claims:
            raise ValueError("a refused answer cannot contain claims")
        if self.status == "completed" and self.refusal_code is not None:
            raise ValueError("a completed answer cannot contain a refusal code")
        return self


class AgentWorkbenchRunRequest(_StrictModel):
    query: str = Field(min_length=1, max_length=500)
    scenario_id: (
        Literal[
            "evidence",
            "event",
            "brand",
            "copy_validation",
            "multi_tool",
            "insufficient",
        ]
        | None
    ) = None
    model_mode: Literal["deterministic", "openai"] | None = None


class AgentClaimResponse(_StrictModel):
    text: str
    kind: AgentClaimKind
    citation_ids: list[str]


class AgentCitationResponse(_StrictModel):
    id: str
    kind: AgentCitationKind
    source_name: str
    title: str
    url: HttpsUrl | None
    evidence_eligible: bool


class AgentTraceStepResponse(_StrictModel):
    ordinal: int = Field(ge=1)
    kind: AgentTraceKind
    status: AgentTraceStatus
    code: str | None = None
    tool_name: str | None = None
    call_id: str | None = None
    argument_summary: dict[str, TraceValue]
    duration_ms: int = Field(ge=0)
    item_count: int | None = Field(default=None, ge=0)
    issue_count: int | None = Field(default=None, ge=0)
    citation_ids: list[str]
    provider: str | None = None
    model: str | None = None
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)


class AgentRunMetricsResponse(_StrictModel):
    model_turns: int = Field(ge=0, le=4)
    tool_calls: int = Field(ge=0, le=4)
    successful_tool_calls: int = Field(ge=0, le=4)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    model_latency_ms: int = Field(ge=0)
    tool_latency_ms: int = Field(ge=0)
    duration_ms: int = Field(ge=0)


class AgentWorkbenchRunResponse(_StrictModel):
    run_id: UUID
    status: AgentRunStatus
    summary: str = Field(max_length=1_200)
    claims: list[AgentClaimResponse] = Field(max_length=8)
    citations: list[AgentCitationResponse] = Field(max_length=20)
    steps: list[AgentTraceStepResponse]
    metrics: AgentRunMetricsResponse
    error_code: str | None = None

    @classmethod
    def from_result(cls, result: AgentRunResult) -> AgentWorkbenchRunResponse:
        return cls(
            run_id=result.run_id,
            status=result.status,
            summary=result.summary,
            claims=[
                AgentClaimResponse(
                    text=claim.text,
                    kind=claim.kind,
                    citation_ids=list(claim.citation_ids),
                )
                for claim in result.claims
            ],
            citations=[
                AgentCitationResponse(
                    id=citation.id,
                    kind=citation.kind,
                    source_name=citation.source_name,
                    title=citation.title,
                    url=citation.url,
                    evidence_eligible=citation.evidence_eligible,
                )
                for citation in result.citations
            ],
            steps=[
                AgentTraceStepResponse(
                    ordinal=step.ordinal,
                    kind=step.kind,
                    status=step.status,
                    code=step.code,
                    tool_name=step.tool_name,
                    call_id=step.call_id,
                    argument_summary={
                        key: list(value) if isinstance(value, tuple) else value
                        for key, value in step.safe_arguments
                    },
                    duration_ms=step.duration_ms,
                    item_count=step.item_count,
                    issue_count=step.issue_count,
                    citation_ids=list(step.citation_ids),
                    provider=step.provider,
                    model=step.model,
                    prompt_tokens=step.prompt_tokens,
                    completion_tokens=step.completion_tokens,
                    reasoning_tokens=step.reasoning_tokens,
                )
                for step in result.steps
            ],
            metrics=AgentRunMetricsResponse(
                model_turns=result.metrics.model_turns,
                tool_calls=result.metrics.tool_calls,
                successful_tool_calls=result.metrics.successful_tool_calls,
                prompt_tokens=result.metrics.prompt_tokens,
                completion_tokens=result.metrics.completion_tokens,
                reasoning_tokens=result.metrics.reasoning_tokens,
                model_latency_ms=result.metrics.model_latency_ms,
                tool_latency_ms=result.metrics.tool_latency_ms,
                duration_ms=result.metrics.duration_ms,
            ),
            error_code=result.error_code,
        )
