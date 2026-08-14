from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ContentSlotValue = Literal["morning", "noon", "evening"]


class SourceResponse(BaseModel):
    id: UUID
    slug: str
    display_name: str
    organization_type: str
    enabled: bool
    owner: str
    tier: str
    entry_url: str
    connector_key: str
    version: int
    connector_version: str
    parser_version: str
    relevance_rule_version: str | None
    allow_http_fallback: bool
    topic_priority_policy: str | None
    cadence: str
    timezone: str
    latest_success_at: datetime | None
    latest_filtered_count: int | None


class SourceListResponse(BaseModel):
    items: list[SourceResponse]
    count: int


class CreateAcquisitionRunRequest(BaseModel):
    source_ids: list[UUID] | None = Field(default=None, max_length=9)
    business_date: date | None = Field(
        default=None,
        description="Optional isolated business date used by local preview runs.",
    )


class AcquisitionRunResponse(BaseModel):
    id: UUID
    trigger: str
    business_date: date | None
    timezone: str
    acquisition_version: str
    content_slot: ContentSlotValue | None
    status: str
    total_jobs: int
    succeeded_jobs: int
    failed_jobs: int
    new_count: int
    unchanged_count: int
    duplicate_count: int
    filtered_count: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    status_url: str


class AcquisitionJobResponse(BaseModel):
    id: UUID
    source_id: UUID
    source_slug: str
    status: str
    outcome: str | None
    error_code: str | None
    attempt_count: int
    new_count: int
    unchanged_count: int
    duplicate_count: int
    filtered_count: int
    byte_count: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class AcquisitionJobListResponse(BaseModel):
    items: list[AcquisitionJobResponse]
    count: int
