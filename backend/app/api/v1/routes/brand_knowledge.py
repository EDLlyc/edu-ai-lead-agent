from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.v1.routes.brand_knowledge_views import (
    brand_context_chunk_response,
    brand_document_response,
    brand_ingestion_job_response,
)
from app.application.ports.brand_knowledge import BrandEmbeddingModel, BrandOriginalStore
from app.application.services.brand_knowledge import retrieve_brand_context
from app.core.config import Settings
from app.core.errors import BrandUploadRejectedError, ConflictError
from app.domain.brand_knowledge import (
    BrandAudience,
    BrandDocumentKind,
    BrandUploadMetadata,
    validated_brand_upload,
)
from app.infrastructure.db.brand_knowledge import (
    PostgresBrandKnowledgeRepository,
    activate_brand_version,
    deactivate_brand_document,
    get_brand_document,
    get_brand_ingestion_job,
    list_brand_documents,
)
from app.schemas.brand_knowledge import (
    BrandContextResponse,
    BrandDocumentListResponse,
    BrandDocumentResponse,
    BrandIngestionJobResponse,
    BrandRetrievalRequest,
    BrandUploadAcceptedResponse,
)

router = APIRouter(tags=["brand-knowledge"])
_READ_CHUNK_BYTES = 64 * 1024


@router.post(
    "/brand-documents",
    response_model=BrandUploadAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_brand_document(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[UploadFile, File(description="PDF, DOCX, UTF-8 TXT, or Markdown")],
    title: Annotated[str, Form(min_length=1, max_length=200)],
    document_kind: Annotated[BrandDocumentKind, Form()] = BrandDocumentKind.OTHER,
    audience: Annotated[BrandAudience, Form()] = BrandAudience.PARENTS,
    valid_from: Annotated[date | None, Form()] = None,
    valid_until: Annotated[date | None, Form()] = None,
    tone_tags: Annotated[str, Form(max_length=800)] = "",
    safety_tags: Annotated[str, Form(max_length=800)] = "",
    visual_tags: Annotated[str, Form(max_length=800)] = "",
) -> BrandUploadAcceptedResponse:
    settings: Settings = request.app.state.settings
    if not settings.content_enabled:
        raise ConflictError("content production is disabled")
    if request.app.state.brand_embedding_model is None:
        raise ConflictError("brand embedding provider is unavailable")
    body = await _read_upload_bounded(file, settings.brand_upload_max_bytes)
    try:
        upload = validated_brand_upload(
            filename=file.filename or "",
            declared_media_type=file.content_type,
            body=body,
        )
        metadata = BrandUploadMetadata(
            brand_slug="sai-xiansheng",
            title=title,
            document_kind=document_kind,
            audience=audience,
            language="zh-CN",
            valid_from=valid_from,
            valid_until=valid_until,
            tone_tags=_parse_tags(tone_tags),
            safety_tags=_parse_tags(safety_tags),
            visual_tags=_parse_tags(visual_tags),
        )
    except ValueError:
        raise BrandUploadRejectedError(
            "invalid_brand_upload", "brand upload failed validation"
        ) from None
    original_store: BrandOriginalStore = request.app.state.brand_original_store
    original = await original_store.put_immutable(upload)
    repository = PostgresBrandKnowledgeRepository(request.app.state.session_factory)
    document_id, version_id, job_id, created = await repository.create_upload(
        metadata=metadata,
        upload=upload,
        original=original,
        parser_version=settings.brand_parser_version,
        chunk_version=settings.brand_chunk_version,
        embedding_input_version=settings.brand_embedding_input_version,
        embedding_provider=settings.ai_provider_mode,
        embedding_model=settings.ai_embedding_model,
        dimensions=settings.ai_embedding_dimensions,
    )
    durable_job = await get_brand_ingestion_job(session, job_id)
    status_url = f"/api/v1/brand-ingestion-jobs/{job_id}"
    response.headers["Location"] = status_url
    return BrandUploadAcceptedResponse(
        document_id=document_id,
        version_id=version_id,
        ingestion_job_id=job_id,
        created=created,
        status=durable_job.status,
        document_url=f"/api/v1/brand-documents/{document_id}",
        status_url=status_url,
    )


@router.get("/brand-documents", response_model=BrandDocumentListResponse)
async def read_brand_documents(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BrandDocumentListResponse:
    projections = await list_brand_documents(session)
    return BrandDocumentListResponse(
        items=[brand_document_response(projection) for projection in projections],
        count=len(projections),
    )


@router.get("/brand-documents/{document_id}", response_model=BrandDocumentResponse)
async def read_brand_document(
    document_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BrandDocumentResponse:
    return brand_document_response(await get_brand_document(session, document_id))


@router.get("/brand-ingestion-jobs/{job_id}", response_model=BrandIngestionJobResponse)
async def read_brand_ingestion_job(
    job_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BrandIngestionJobResponse:
    return brand_ingestion_job_response(await get_brand_ingestion_job(session, job_id))


@router.post(
    "/brand-documents/{document_id}/versions/{version_id}/activate",
    response_model=BrandDocumentResponse,
)
async def activate_brand_document_version(
    document_id: UUID,
    version_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BrandDocumentResponse:
    _require_content_enabled(request)
    return brand_document_response(
        await activate_brand_version(
            session,
            document_id=document_id,
            version_id=version_id,
        )
    )


@router.post(
    "/brand-documents/{document_id}/deactivate",
    response_model=BrandDocumentResponse,
)
async def deactivate_brand_document_route(
    document_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BrandDocumentResponse:
    _require_content_enabled(request)
    return brand_document_response(
        await deactivate_brand_document(session, document_id=document_id)
    )


@router.post(
    "/brand-context/retrieve",
    response_model=BrandContextResponse,
    summary="Retrieve internal brand context for copy generation",
    description=(
        "Returns bounded active brand guidance for the internal WeChat Moments copy-generation "
        "pipeline and operator diagnostics. The audience field describes the target reader of "
        "generated copy; this endpoint is not a parent-facing search product, and its results "
        "cannot be used as factual evidence."
    ),
)
async def retrieve_brand_context_route(
    payload: BrandRetrievalRequest,
    request: Request,
) -> BrandContextResponse:
    settings: Settings = request.app.state.settings
    embedding_model: BrandEmbeddingModel | None = request.app.state.brand_embedding_model
    if not settings.content_enabled or embedding_model is None:
        raise ConflictError("brand retrieval is disabled")
    repository = PostgresBrandKnowledgeRepository(request.app.state.session_factory)
    valid_on = payload.valid_on or datetime.now(ZoneInfo(settings.business_timezone)).date()
    hits = await retrieve_brand_context(
        repository=repository,
        embeddings=embedding_model,
        query=payload.query,
        audience=payload.audience,
        document_kinds=tuple(payload.document_kinds),
        valid_on=valid_on,
        limit=payload.limit,
    )
    return BrandContextResponse(
        retrieval_version=settings.brand_retrieval_version,
        query=payload.query.strip(),
        audience=payload.audience,
        valid_on=valid_on,
        items=[brand_context_chunk_response(hit) for hit in hits],
        count=len(hits),
        evidence_eligible=False,
    )


async def _read_upload_bounded(file: UploadFile, max_bytes: int) -> bytes:
    declared_length = file.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > max_bytes:
                raise BrandUploadRejectedError(
                    "brand_upload_too_large", "brand upload exceeded the configured limit"
                )
        except ValueError:
            raise BrandUploadRejectedError(
                "invalid_brand_upload", "brand upload content length is invalid"
            ) from None
    chunks: list[bytes] = []
    byte_count = 0
    while True:
        chunk = await file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        byte_count += len(chunk)
        if byte_count > max_bytes:
            raise BrandUploadRejectedError(
                "brand_upload_too_large", "brand upload exceeded the configured limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_tags(value: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for item in value.replace("\uff0c", ",").split(","):
        tag = item.strip()
        if tag and tag not in normalized:
            normalized.append(tag)
    return tuple(normalized)


def _require_content_enabled(request: Request) -> None:
    settings: Settings = request.app.state.settings
    if not settings.content_enabled:
        raise ConflictError("content production is disabled")
