from __future__ import annotations

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class CreateGovernanceRunRequest(BaseModel):
    acquisition_run_id: UUID | None = None
    candidate_ids: tuple[UUID, ...] = Field(default=(), min_length=0, max_length=100)

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if self.acquisition_run_id is None and not self.candidate_ids:
            raise ValueError("provide an acquisition run or at least one candidate")
        if self.acquisition_run_id is not None and self.candidate_ids:
            raise ValueError("acquisition run and candidate selection are mutually exclusive")
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("candidate IDs must be unique")
        return self


class GovernanceRunResponse(BaseModel):
    id: UUID
    trigger: str
    acquisition_run_id: UUID | None
    timezone: str
    profile_fingerprint: str
    version_bundle: dict[str, str | int]
    status: str
    total_jobs: int
    succeeded_jobs: int
    review_jobs: int
    failed_jobs: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    model_latency_ms: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    status_url: str


class GovernanceJobResponse(BaseModel):
    id: UUID
    run_id: UUID
    candidate_id: UUID
    status: str
    current_stage: str | None
    attempt_count: int
    outcome: str | None
    error_code: str | None
    safe_metadata: dict[str, Any]
    available_at: datetime
    heartbeat_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class GovernanceJobListResponse(BaseModel):
    items: list[GovernanceJobResponse]
    next_cursor: UUID | None


class GovernancePassageResponse(BaseModel):
    id: UUID
    normalized_article_id: UUID
    ordinal: int
    passage_hash: str
    text: str
    source_start: int
    source_end: int


class GovernanceFactResponse(BaseModel):
    id: UUID
    ordinal: int
    text: str
    event_time_start: datetime | None
    event_time_end: datetime | None
    event_time_precision: str


class GovernanceEntityResponse(BaseModel):
    id: UUID
    ordinal: int
    entity_type: str
    source_mention: str
    canonical_name: str
    support_passage_id: UUID


class GovernanceCategoryResponse(BaseModel):
    category: str
    is_primary: bool
    confidence: float
    taxonomy_version: str


class GovernanceEvidenceBindingResponse(BaseModel):
    id: UUID
    statement_kind: str
    fact_id: UUID | None
    passage_id: UUID
    candidate_id: UUID
    occurrence_id: UUID
    snapshot_id: UUID
    exact_quote: str
    quote_start: int
    quote_end: int
    validated: bool


class GovernanceOccurrenceResponse(BaseModel):
    id: UUID
    candidate_id: UUID
    observation_id: UUID
    snapshot_id: UUID
    source_id: UUID
    source_version_id: UUID
    source_item_id: str
    source_slug: str
    source_display_name: str
    trust_tier: str
    original_url: str
    final_url: str
    published_at: datetime | None
    fetched_at: datetime
    parser_version: str
    relevance_rule_version: str | None


class DuplicateRelationResponse(BaseModel):
    id: UUID
    left_article_id: UUID
    right_article_id: UUID
    relation_kind: str
    policy_version: str
    outcome: str
    threshold: float | None
    features: dict[str, Any]
    created_at: datetime


class EventAssignmentResponse(BaseModel):
    id: UUID
    normalized_article_id: UUID
    governance_run_id: UUID
    selected_event_id: UUID | None
    policy_version: str
    outcome: str
    review_required: bool
    recent_window_start: datetime
    recent_window_end: datetime
    features: dict[str, Any]
    thresholds: dict[str, Any]
    alternatives: list[dict[str, Any]]
    created_at: datetime


class CandidateAnalysisSummaryResponse(BaseModel):
    candidate_id: UUID
    normalized_article_id: UUID
    analysis_id: UUID
    title: str
    original_url: str
    canonical_url: str
    published_at: datetime | None
    status: str
    summary: str | None
    primary_category: str | None
    keywords: list[str]
    event_time_start: datetime | None
    event_time_end: datetime | None
    event_time_precision: str
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    taxonomy_version: str
    created_at: datetime


class CandidateAnalysisListResponse(BaseModel):
    items: list[CandidateAnalysisSummaryResponse]
    next_cursor: UUID | None


class CandidateAnalysisDetailResponse(CandidateAnalysisSummaryResponse):
    requested_candidate_id: UUID
    analysis_candidate_id: UUID
    analysis_reused: bool
    facts: list[GovernanceFactResponse]
    entities: list[GovernanceEntityResponse]
    categories: list[GovernanceCategoryResponse]
    passages: list[GovernancePassageResponse]
    evidence_bindings: list[GovernanceEvidenceBindingResponse]
    source_occurrences: list[GovernanceOccurrenceResponse]
    duplicate_relations: list[DuplicateRelationResponse]
    assignment: EventAssignmentResponse | None
    active_event_id: UUID | None
    active_event_version_id: UUID | None


class EventVersionResponse(BaseModel):
    id: UUID
    event_id: UUID
    version: int
    representative_article_id: UUID
    representative_title: str
    summary_projection: dict[str, Any]
    event_time_start: datetime | None
    event_time_end: datetime | None
    event_time_precision: str
    member_set_hash: str
    source_diversity: int
    category_projection: list[str]
    entity_projection: list[dict[str, Any]]
    clustering_policy_version: str
    version_bundle_fingerprint: str
    created_by_run_id: UUID
    created_at: datetime


class EventSummaryResponse(BaseModel):
    id: UUID
    status: str
    current_version_id: UUID
    representative_title: str
    summary: str | None
    event_time_start: datetime | None
    event_time_end: datetime | None
    source_diversity: int
    categories: list[str]
    member_count: int
    review_count: int
    updated_at: datetime


class EventListResponse(BaseModel):
    items: list[EventSummaryResponse]
    next_cursor: UUID | None


class EventMemberResponse(BaseModel):
    membership_id: UUID
    normalized_article_id: UUID
    candidate_id: UUID
    title: str
    original_url: str
    canonical_url: str
    published_at: datetime | None
    active: bool
    policy_version: str
    analysis_id: UUID | None
    summary: str | None
    passages: list[GovernancePassageResponse]
    source_occurrences: list[GovernanceOccurrenceResponse]
    assignment: EventAssignmentResponse


class EventDetailResponse(EventSummaryResponse):
    created_at: datetime
    current_version: EventVersionResponse
    versions: list[EventVersionResponse]
    members: list[EventMemberResponse]
    review_decisions: list[EventAssignmentResponse]
