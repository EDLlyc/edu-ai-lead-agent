from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.enums import SourceTier


@dataclass(frozen=True, slots=True)
class SourceProfile:
    source_id: UUID
    source_version_id: UUID
    slug: str
    display_name: str
    organization_type: str
    tier: SourceTier
    connector_key: str
    entry_url: str
    allowed_hosts: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    connector_version: str
    parser_version: str
    relevance_rule_version: str | None = None
    allow_http_fallback: bool = False
    topic_priority_policy: str | None = None
    language: str = "zh-CN"
    timezone: str = "Asia/Shanghai"
    rate_limit_seconds: float = 2.0
    robots_status: str = "allowed"
    terms_reviewed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FetchedResponse:
    requested_url: str
    final_url: str
    status_code: int
    media_type: str | None
    body: bytes
    sha256: str
    fetched_at: datetime
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DiscoveredItem:
    source_item_id: str
    url: str
    title: str | None = None
    published_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SourceImageReference:
    """A bounded, policy-approved image occurrence extracted from one detail page.

    This value carries provenance only.  It is not evidence and extraction performs no I/O.
    """

    image_url: str
    source_page_url: str
    ordinal: int
    role: str
    alt_text: str | None = None
    caption: str | None = None
    credit: str | None = None
    extraction_version: str = "source-image-extractor-v1"


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    source_item_id: str
    original_url: str
    canonical_url: str
    title: str
    clean_text: str
    published_at: datetime | None
    language: str
    parser_version: str
    extraction_metadata: dict[str, Any] = field(default_factory=dict)
    source_images: tuple[SourceImageReference, ...] = ()


@dataclass(frozen=True, slots=True)
class SnapshotDescriptor:
    bucket: str
    object_key: str
    media_type: str
    byte_size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ValidatedSourceImage:
    response: FetchedResponse
    width: int
    height: int
