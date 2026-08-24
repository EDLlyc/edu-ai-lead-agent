from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.brand_knowledge import (
    BrandAudience,
    BrandClaimScope,
    BrandContentType,
    BrandDocumentKind,
    BrandSectionKind,
)
from app.domain.digital_ip import DigitalIpVisualCatalogStatus
from app.domain.visual_assets import VisualAssetKind
from app.domain.visual_retrieval import VisualRetrievalUnavailableReason


class BrandVersionResponse(BaseModel):
    id: UUID
    document_id: UUID
    version: int
    safe_filename: str
    media_type: str
    byte_size: int
    status: str
    active: bool
    valid_from: date | None
    valid_until: date | None
    tone_tags: list[str]
    safety_tags: list[str]
    visual_tags: list[str]
    extraction_method: str | None
    ocr_provider: str | None
    ocr_model: str | None
    ocr_request_fingerprint: str | None
    ocr_provider_request_id: str | None
    ocr_page_count: int | None
    ocr_prompt_tokens: int | None
    ocr_completion_tokens: int | None
    ocr_latency_ms: int | None
    parser_version: str
    chunk_version: str
    embedding_input_version: str
    embedding_provider: str | None
    embedding_model: str
    embedding_dimensions: int
    page_count: int | None
    character_count: int | None
    chunk_count: int
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None
    activated_at: datetime | None
    deactivated_at: datetime | None
    ingestion_job_id: UUID | None
    ingestion_job_status: str | None


class BrandDocumentResponse(BaseModel):
    id: UUID
    brand_slug: Literal["sai-xiansheng"]
    title: str
    document_kind: BrandDocumentKind
    audience: BrandAudience
    language: Literal["zh-CN"]
    status: Literal["active", "inactive"]
    active_version_id: UUID | None
    versions: list[BrandVersionResponse]
    created_at: datetime
    updated_at: datetime


class BrandDocumentListResponse(BaseModel):
    items: list[BrandDocumentResponse]
    count: int


class BrandUploadAcceptedResponse(BaseModel):
    document_id: UUID
    version_id: UUID
    ingestion_job_id: UUID
    created: bool
    status: str
    document_url: str
    status_url: str


class BrandIngestionJobResponse(BaseModel):
    id: UUID
    version_id: UUID
    status: str
    attempt_count: int
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class BrandRetrievalRequest(BaseModel):
    """Internal retrieval input consumed by copy-generation and operator diagnostics."""

    query: str = Field(
        min_length=1,
        max_length=2_000,
        description=(
            "Selected topic or draft intent used to retrieve brand guidance for copy generation."
        ),
    )
    audience: BrandAudience = Field(
        default=BrandAudience.PARENTS,
        description=(
            "Target audience metadata for the generated copy; this is not the identity of a "
            "search user."
        ),
    )
    document_kinds: list[BrandDocumentKind] = Field(
        default_factory=list,
        max_length=7,
        description="Optional brand-document kinds allowed in the generation context.",
    )
    valid_on: date | None = Field(
        default=None,
        description="Business date used to filter valid brand guidance.",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum number of bounded brand chunks returned to the generation pipeline.",
    )


class BrandContextChunkResponse(BaseModel):
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    document_title: str
    document_kind: BrandDocumentKind
    audience: BrandAudience
    text: str
    tone_tags: list[str]
    safety_tags: list[str]
    visual_tags: list[str]
    section_id: UUID | None
    section_title: str | None
    section_kind: BrandSectionKind | None
    source_page: int | None
    question_number: int | None
    question_text: str | None
    content_type: BrandContentType | None
    claim_scope: BrandClaimScope | None
    verification_required: bool
    full_text_score: float
    vector_score: float
    fused_score: float


class BrandContextResponse(BaseModel):
    """Bounded internal brand context for copy generation, never factual evidence."""

    retrieval_version: str
    query: str
    audience: BrandAudience
    valid_on: date
    items: list[BrandContextChunkResponse]
    count: int
    evidence_eligible: Literal[False] = Field(
        default=False,
        description="Always false: brand guidance cannot support externally verifiable claims.",
    )


class DigitalIpCharacterResponse(BaseModel):
    character_id: str
    display_name: str
    role: str


class DigitalIpDocumentBindingResponse(BaseModel):
    document_id: UUID
    version_id: UUID
    version: int
    title: str
    document_kind: BrandDocumentKind
    audience: BrandAudience
    valid_from: date | None
    valid_until: date | None
    tone_tags: list[str]
    safety_tags: list[str]
    visual_tags: list[str]


class DigitalIpVisualAssetResponse(BaseModel):
    """Browser-safe metadata: no path, URL, object key, filename, bytes, or full digest."""

    asset_ref: str = Field(min_length=16, max_length=16)
    checksum_ref: str = Field(min_length=16, max_length=16)
    display_name: str
    asset_kind: VisualAssetKind
    characters: list[str]
    roles: list[str]
    topics: list[str]
    poses: list[str]
    scene_tags: list[str]
    width: int = Field(ge=1, le=8_192)
    height: int = Field(ge=1, le=8_192)
    approved: Literal[True]
    priority: int = Field(ge=0, le=1_000)


class DigitalIpProfileResponse(BaseModel):
    """Read-only projection joining active brand metadata with safe visual metadata."""

    profile_id: Literal["sai-xiansheng-xiao-sai"]
    profile_version: Literal["digital-ip-profile-v1"]
    display_name: str
    brand_slug: Literal["sai-xiansheng"]
    identity_summary: str
    characters: list[DigitalIpCharacterResponse]
    audiences: list[BrandAudience]
    channels: list[str]
    content_scenarios: list[str]
    document_bindings: list[DigitalIpDocumentBindingResponse]
    active_document_count: int = Field(ge=0)
    active_version_ids: list[UUID]
    document_kinds: list[BrandDocumentKind]
    tone_tags: list[str]
    safety_tags: list[str]
    visual_tags: list[str]
    visual_catalog_status: DigitalIpVisualCatalogStatus
    visual_catalog_version: str | None
    visual_assets: list[DigitalIpVisualAssetResponse]
    profile_fingerprint: str = Field(min_length=64, max_length=64)
    evidence_eligible: Literal[False] = Field(
        default=False,
        description="Always false: digital-IP guidance is not external-fact evidence.",
    )


class BrandVisualSearchItemResponse(BaseModel):
    """Safe visual hit: no path, filename, bytes, vectors, or provider metadata."""

    asset_ref: str = Field(min_length=16, max_length=16)
    asset_kind: VisualAssetKind
    roles: list[str]
    tags: list[str]
    approved: Literal[True] = True
    catalog_version: str
    similarity: float = Field(ge=-1.0, le=1.0)
    ranking_source: Literal["semantic_primary"] = "semantic_primary"


class BrandVisualSearchResponse(BaseModel):
    status: Literal["ready", "semantic_unavailable"]
    reason: VisualRetrievalUnavailableReason | None = None
    query_modality: Literal["text", "image"]
    catalog_version: str | None
    items: list[BrandVisualSearchItemResponse]
    count: int = Field(ge=0, le=20)
    evidence_eligible: Literal[False] = False
