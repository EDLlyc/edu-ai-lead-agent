from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class EvidenceCandidateSummary(BaseModel):
    id: UUID
    source_id: UUID
    source_slug: str
    source_display_name: str
    source_item_id: str
    original_url: str
    canonical_url: str
    trust_tier: str
    title: str
    published_at: datetime | None
    first_fetched_at: datetime
    language: str
    content_hash: str
    parser_version: str
    relevance_rule_version: str | None
    created_at: datetime


class EvidenceCandidateListResponse(BaseModel):
    items: list[EvidenceCandidateSummary]
    next_cursor: UUID | None


class SnapshotMetadataResponse(BaseModel):
    id: UUID
    bucket: str
    object_key: str
    media_type: str
    byte_size: int
    sha256: str
    fetched_at: datetime


class ObservationResponse(BaseModel):
    id: UUID
    run_id: UUID
    job_id: UUID
    outcome: str
    observed_at: datetime
    error_code: str | None
    snapshot_id: UUID | None
    metadata: dict[str, Any]


class EvidenceCandidateDetailResponse(EvidenceCandidateSummary):
    clean_text: str
    extraction_metadata: dict[str, Any]
    snapshot: SnapshotMetadataResponse
    observations: list[ObservationResponse]
