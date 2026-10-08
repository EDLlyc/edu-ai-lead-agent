from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AdminSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["html", "rss"]
    link_contains: list[str] = Field(default_factory=list, max_length=20)
    content_selectors: list[str] = Field(default_factory=list, max_length=20)
    list_selectors: list[str] = Field(default_factory=list, max_length=20)


class AdminSourcePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_url: str = Field(min_length=1, max_length=500)
    config: AdminSourceConfig


class AdminSourceDraftRequest(AdminSourcePreviewRequest):
    display_name: str = Field(min_length=1, max_length=80)
    organization_type: Literal[
        "government", "education_institution", "research_organization", "authoritative_media"
    ]
    tier: Literal["A", "B"]


class AdminSourceLatestJob(BaseModel):
    status: str
    outcome: str | None
    error_code: str | None
    new_count: int
    filtered_count: int
    duplicate_count: int
    completed_at: datetime | None


class AdminSourceResponse(BaseModel):
    id: UUID
    display_name: str
    organization_type: str
    tier: Literal["A", "B"]
    managed_by: Literal["seed", "operator"]
    enabled: bool
    archived_at: datetime | None
    entry_url: str
    kind: Literal["code", "html", "rss"]
    config: AdminSourceConfig | None
    version: int
    robots_status: str
    latest_job: AdminSourceLatestJob | None
    new_last_7_days: int


class AdminSourceListResponse(BaseModel):
    items: list[AdminSourceResponse]
    count: int


class AdminSourcePreviewLink(BaseModel):
    title: str | None
    url: str
    published_at: datetime | None


class AdminSourcePreviewSample(BaseModel):
    title: str | None
    url: str
    published_at: datetime | None
    characters: int
    excerpt: str
    freshness: Literal["fresh", "stale", "unknown"]
    relevant: bool
    topic: Literal["education", "frontier", "other"] | None
    problem: str | None


class AdminSourcePreviewResponse(BaseModel):
    ok: bool
    robots: Literal["allowed", "no_robots_file", "disallowed"] | None
    problem: str | None
    links: list[AdminSourcePreviewLink]
    samples: list[AdminSourcePreviewSample]
