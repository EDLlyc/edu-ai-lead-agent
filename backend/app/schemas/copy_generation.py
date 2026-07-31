from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class DraftClaim(_StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(min_length=2, max_length=300)
    kind: Literal["external_fact", "brand_statement", "opinion"]
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=8)
    brand_chunk_ids: tuple[UUID, ...] = Field(default=(), max_length=8)

    @field_validator("evidence_ids", "brand_chunk_ids")
    @classmethod
    def binding_ids_must_be_unique(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("claim binding IDs must be unique")
        return value


class MaterialDraft(_StrictModel):
    copywriting: str = Field(min_length=1, max_length=1_200)
    parent_takeaway: str = Field(min_length=1, max_length=300)
    interaction: str = Field(min_length=1, max_length=180)
    source_note: str = Field(min_length=1, max_length=500)
    image_prompt: str = Field(min_length=1, max_length=800)
    claims: tuple[DraftClaim, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def claim_ids_must_be_unique(self) -> Self:
        claim_ids = [claim.id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("draft claim IDs must be unique")
        return self


class CopyIssue(_StrictModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=1, max_length=240)
    severity: Literal["warning", "error"] = "error"
    field: str | None = Field(default=None, max_length=80)
    claim_id: str | None = Field(default=None, max_length=80)


class AuditVerdict(_StrictModel):
    accepted: bool
    issues: tuple[CopyIssue, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def accepted_verdict_has_no_errors(self) -> Self:
        if self.accepted and any(issue.severity == "error" for issue in self.issues):
            raise ValueError("accepted audit cannot contain error issues")
        if not self.accepted and not any(issue.severity == "error" for issue in self.issues):
            raise ValueError("rejected audit requires at least one error issue")
        return self


class CreateCopyGenerationRunRequest(BaseModel):
    business_date: date
    scoring_profile: str = Field(default="preview", min_length=1, max_length=40)


class CopyClaimResponse(BaseModel):
    claim_id: str
    text: str
    kind: Literal["external_fact", "brand_statement", "opinion"]
    evidence_ids: list[UUID]
    brand_chunk_ids: list[UUID]


class CopyDraftResponse(BaseModel):
    id: UUID
    version: int
    repair_of_version_id: UUID | None
    copywriting: str
    parent_takeaway: str
    interaction: str
    source_note: str
    image_prompt: str
    validation_passed: bool
    audit_accepted: bool | None
    claims: list[CopyClaimResponse]
    issues: list[CopyIssue]
    created_at: datetime


class CopyGenerationRunResponse(BaseModel):
    id: UUID
    daily_topic_selection_id: UUID
    business_date: date
    timezone: str
    scoring_profile: str
    decision_kind: Literal["selected", "no_topic"]
    selected_event_id: UUID | None
    selected_event_version_id: UUID | None
    no_topic_code: str | None
    status: Literal[
        "queued",
        "running",
        "no_topic",
        "accepted",
        "review_required",
        "failed",
    ]
    active_draft_version_id: UUID | None
    repair_count: int
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    status_url: str
    detail_url: str


class CopyGenerationDetailResponse(CopyGenerationRunResponse):
    drafts: list[CopyDraftResponse]
