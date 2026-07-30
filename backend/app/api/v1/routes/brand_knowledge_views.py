from __future__ import annotations

from app.domain.brand_knowledge import BrandAudience, BrandDocumentKind, BrandRetrievalHit
from app.infrastructure.db.brand_knowledge import BrandDocumentProjection
from app.infrastructure.db.models import BrandDocumentVersionModel, BrandIngestionJobModel
from app.schemas.brand_knowledge import (
    BrandContextChunkResponse,
    BrandDocumentResponse,
    BrandIngestionJobResponse,
    BrandVersionResponse,
)


def brand_document_response(projection: BrandDocumentProjection) -> BrandDocumentResponse:
    document = projection.document
    return BrandDocumentResponse(
        id=document.id,
        brand_slug="sai-xiansheng",
        title=document.title,
        document_kind=BrandDocumentKind(document.document_kind),
        audience=BrandAudience(document.audience),
        language="zh-CN",
        status="active" if document.status == "active" else "inactive",
        active_version_id=document.active_version_id,
        versions=[
            brand_version_response(version, projection.jobs_by_version.get(version.id))
            for version in projection.versions
        ],
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def brand_version_response(
    version: BrandDocumentVersionModel, job: BrandIngestionJobModel | None
) -> BrandVersionResponse:
    return BrandVersionResponse(
        id=version.id,
        document_id=version.document_id,
        version=version.version,
        safe_filename=version.safe_filename,
        media_type=version.media_type,
        byte_size=version.byte_size,
        status=version.status,
        active=version.active,
        valid_from=version.valid_from,
        valid_until=version.valid_until,
        tone_tags=_strings(version.tone_tags),
        safety_tags=_strings(version.safety_tags),
        visual_tags=_strings(version.visual_tags),
        parser_version=version.parser_version,
        chunk_version=version.chunk_version,
        embedding_input_version=version.embedding_input_version,
        embedding_provider=version.embedding_provider,
        embedding_model=version.embedding_model,
        embedding_dimensions=version.embedding_dimensions,
        page_count=version.page_count,
        character_count=version.character_count,
        chunk_count=version.chunk_count,
        error_code=version.error_code,
        created_at=version.created_at,
        completed_at=version.completed_at,
        activated_at=version.activated_at,
        deactivated_at=version.deactivated_at,
        ingestion_job_id=job.id if job is not None else None,
        ingestion_job_status=job.status if job is not None else None,
    )


def brand_ingestion_job_response(job: BrandIngestionJobModel) -> BrandIngestionJobResponse:
    return BrandIngestionJobResponse(
        id=job.id,
        version_id=job.version_id,
        status=job.status,
        attempt_count=job.attempt_count,
        error_code=job.error_code,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def brand_context_chunk_response(hit: BrandRetrievalHit) -> BrandContextChunkResponse:
    return BrandContextChunkResponse(
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        version_id=hit.version_id,
        document_title=hit.document_title,
        document_kind=hit.document_kind,
        audience=hit.audience,
        text=hit.text,
        tone_tags=list(hit.tone_tags),
        safety_tags=list(hit.safety_tags),
        visual_tags=list(hit.visual_tags),
        full_text_score=hit.full_text_score,
        vector_score=hit.vector_score,
        fused_score=hit.fused_score,
    )


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
