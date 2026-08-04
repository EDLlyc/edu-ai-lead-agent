from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.brand_knowledge import BrandAudience, BrandDocumentKind


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
