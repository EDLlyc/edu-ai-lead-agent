from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class CreateTopicSelectionRunRequest(BaseModel):
    business_date: date | None = None


class TopicSelectionRunResponse(BaseModel):
    id: UUID
    trigger: str
    business_date: date
    timezone: str
    scoring_version: str
    scoring_profile: str
    revision: int
    config_fingerprint: str
    config: dict[str, Any]
    status: str
    considered_count: int
    eligible_count: int
    selected_event_id: UUID | None
    selected_event_version_id: UUID | None
    no_topic_code: str | None
    cutoff_at: datetime
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    superseded_at: datetime | None
    superseded_by_run_id: UUID | None
    is_current: bool
    status_url: str
    scores_url: str


class TopicScoreResponse(BaseModel):
    id: UUID
    run_id: UUID
    event_id: UUID
    event_version_id: UUID
    event_title: str
    event_time: datetime | None
    scoring_version: str
    scoring_profile: str
    raw_features: dict[str, float]
    normalized_features: dict[str, float]
    weights: dict[str, float]
    penalty_weights: dict[str, float]
    positive_components: dict[str, float]
    penalty_components: dict[str, float]
    total: float
    threshold: float
    passes_threshold: bool
    eligible: bool
    veto_codes: list[str]
    rank: int


class TopicScoreListResponse(BaseModel):
    items: list[TopicScoreResponse]
    count: int


class DailyTopicResponse(BaseModel):
    business_date: date
    timezone: str
    scoring_version: str
    scoring_profile: str
    revision: int
    decision: Literal["selected", "no_topic"]
    run_id: UUID
    selected_event_id: UUID | None
    selected_event_version_id: UUID | None
    no_topic_code: str | None
    decided_at: datetime
    selected_score: TopicScoreResponse | None
