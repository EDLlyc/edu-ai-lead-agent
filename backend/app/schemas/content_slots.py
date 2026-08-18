from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.topic_rerank import TopicRerankSummaryResponse

ContentSlotValue = Literal["morning", "noon", "evening"]


class CreateContentSlotRunRequest(BaseModel):
    business_date: date | None = None
    content_slot: ContentSlotValue


class ContentSlotRunResponse(BaseModel):
    id: UUID
    trigger: Literal["manual", "scheduled"]
    business_date: date
    timezone: str
    content_slot: ContentSlotValue
    display_name: str
    scoring_profile: str
    acquisition_run_id: UUID
    governance_run_id: UUID
    governed_event_cutoff: datetime
    config_fingerprint: str
    rerank_config_fingerprint: str
    rerank_config: dict[str, Any]
    rerank: TopicRerankSummaryResponse
    slot_policy_version: str
    slot_policy_fingerprint: str
    preparation_at: datetime
    target_at: datetime
    expires_at: datetime
    item_limit: int = Field(ge=1, le=3)
    status: Literal["queued", "running", "succeeded", "failed"]
    total_scores: int
    eligible_scores: int
    selected_count: int
    unfilled_count: int
    unfilled_reason_codes: list[str]
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    status_url: str
    scores_url: str


class ContentSlotScoreResponse(BaseModel):
    id: UUID
    run_id: UUID
    event_id: UUID
    event_version_id: UUID
    event_title: str
    event_time: datetime | None
    total: float
    threshold: float
    passes_threshold: bool
    eligible: bool
    veto_codes: list[str]
    slot_affinity: float
    slot_affinity_reasons: list[str]
    same_day_excluded: bool
    same_day_exclusion_reason: str | None
    final_ordering_value: float
    final_ordering_key: str
    rank: int
    deterministic_rank: int
    final_rank: int
    rerank_reason_codes: list[str]
    rerank_explanation: str | None
    selected_ordinal: int | None = Field(default=None, ge=1, le=3)
    explanation: dict[str, Any]


class ContentSlotScoreListResponse(BaseModel):
    items: list[ContentSlotScoreResponse]
    count: int


class ContentEditionSourceResponse(BaseModel):
    source_name: str
    title: str | None
    url: str


class ContentEditionSelectionResponse(BaseModel):
    selection_id: UUID
    ordinal: int = Field(ge=1, le=3)
    event_id: UUID
    event_version_id: UUID
    title: str
    event_time: datetime | None
    source_links: list[ContentEditionSourceResponse]
    copy_generation_run_id: UUID | None
    copy_status: str | None
    material_package_id: UUID | None
    material_package_status: str | None
    delivery_id: UUID | None
    delivery_status: str | None
    state: Literal[
        "preparing",
        "ready",
        "failed",
        "expired",
        "delivered",
        "delivery_unknown",
    ]
    copy_url: str | None
    material_package_url: str | None
    delivery_url: str | None


class ContentEditionSlotResponse(BaseModel):
    content_slot: ContentSlotValue
    display_name: str
    enabled: bool
    target_at: datetime
    expires_at: datetime
    state: Literal["disabled", "missing", "preparing", "ready", "failed", "expired"]
    run_id: UUID | None
    run_status: str | None
    item_limit: int = Field(ge=1, le=3)
    selected_count: int
    unfilled_count: int
    unfilled_reason_codes: list[str]
    error_code: str | None
    selections: list[ContentEditionSelectionResponse]
    run_url: str | None


class ContentEditionResponse(BaseModel):
    business_date: date
    timezone: str
    scoring_profile: str
    slot_mode_enabled: bool
    slots: list[ContentEditionSlotResponse]
