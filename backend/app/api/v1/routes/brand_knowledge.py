from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.v1.routes.brand_knowledge_views import (
    brand_context_chunk_response,
    brand_document_response,
    brand_ingestion_job_response,
    digital_ip_document_bindings,
    digital_ip_profile_response,
)
from app.application.ports.brand_knowledge import BrandEmbeddingModel, BrandOriginalStore
from app.application.services.brand_knowledge import retrieve_brand_context
from app.application.services.visual_retrieval import VisualRetrievalService
from app.core.config import Settings
from app.core.errors import BrandUploadRejectedError, ConflictError
from app.domain.brand_knowledge import (
    BrandAudience,
    BrandDocumentKind,
    BrandUploadMetadata,
    validated_brand_upload,
)
from app.domain.digital_ip import (
    project_digital_ip_profile,
    project_visual_catalog,
    unavailable_visual_catalog,
)
from app.domain.visual_assets import VisualAssetError, VisualAssetKind
from app.domain.visual_retrieval import (
    MAX_VISUAL_QUERY_IMAGE_BYTES,
    NormalizedVisualImage,
    VisualIndexUnavailableError,
    VisualRetrievalUnavailableReason,
    normalize_visual_embedding_image,
)
from app.infrastructure.brand.visual_catalog import load_visual_catalog
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
    BrandVisualSearchItemResponse,
    BrandVisualSearchResponse,
    DigitalIpProfileResponse,
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


@router.get(
    "/digital-ip/profile",
    response_model=DigitalIpProfileResponse,
    summary="Read the local Sai Xiansheng and Xiao Sai digital-IP profile",
    description=(
        "Projects active-ready brand-version metadata and bounded approved visual-asset metadata. "
        "It exposes no private paths or image bytes, and the result is never factual evidence."
    ),
)
async def read_digital_ip_profile(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DigitalIpProfileResponse:
    projections = await list_brand_documents(session)
    settings: Settings = request.app.state.settings
    try:
        loaded = await asyncio.to_thread(load_visual_catalog, settings.image_asset_manifest)
        visual_catalog = project_visual_catalog(loaded.catalog)
    except (OSError, RuntimeError, VisualAssetError):
        visual_catalog = unavailable_visual_catalog()
    profile = project_digital_ip_profile(
        digital_ip_document_bindings(projections),
        visual_catalog,
    )
    return digital_ip_profile_response(profile)


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
        retrieval_version=settings.brand_retrieval_version,
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


@router.post(
    "/brand-visual-search",
    response_model=BrandVisualSearchResponse,
    summary="Search the approved private visual catalog",
    description=(
        "Internal personal-project demo. Accepts text or one PNG and returns bounded safe "
        "asset references; it never returns paths, filenames, bytes, vectors, or evidence."
    ),
)
async def search_brand_visual_catalog(
    request: Request,
    text_query: Annotated[str | None, Form(max_length=2_000)] = None,
    image: Annotated[UploadFile | None, File(description="Optional bounded PNG query")] = None,
    limit: Annotated[int, Form(ge=1, le=20)] = 5,
) -> BrandVisualSearchResponse:
    settings: Settings = request.app.state.settings
    normalized_text = (text_query or "").strip()
    if bool(normalized_text) == (image is not None):
        raise BrandUploadRejectedError(
            "invalid_visual_query", "provide exactly one text query or PNG image"
        )
    modality: Literal["text", "image"] = "image" if image is not None else "text"
    normalized_image: NormalizedVisualImage | None = None
    if image is not None:
        if (image.content_type or "").split(";", 1)[0].strip().casefold() != "image/png":
            raise BrandUploadRejectedError(
                "invalid_visual_query", "visual image query must be a PNG"
            )
        normalized_image = await _read_visual_query_image(image, MAX_VISUAL_QUERY_IMAGE_BYTES)
    service: VisualRetrievalService | None = getattr(
        request.app.state, "visual_retrieval_service", None
    )
    if not settings.visual_semantic_enabled or service is None:
        return BrandVisualSearchResponse(
            status="semantic_unavailable",
            reason=VisualRetrievalUnavailableReason.DISABLED,
            query_modality=modality,
            catalog_version=None,
            items=[],
            count=0,
        )
    try:
        loaded = await asyncio.to_thread(load_visual_catalog, settings.image_asset_manifest)
        if image is not None:
            assert normalized_image is not None
            ranking = await service.search_normalized_image(
                normalized=normalized_image, catalog=loaded.catalog
            )
        else:
            ranking = await service.search_text(text=normalized_text, catalog=loaded.catalog)
    except VisualIndexUnavailableError as error:
        return BrandVisualSearchResponse(
            status="semantic_unavailable",
            reason=error.reason,
            query_modality=modality,
            catalog_version=None,
            items=[],
            count=0,
        )
    except (OSError, VisualAssetError):
        return BrandVisualSearchResponse(
            status="semantic_unavailable",
            reason=VisualRetrievalUnavailableReason.CATALOG_CHANGED,
            query_modality=modality,
            catalog_version=None,
            items=[],
            count=0,
        )
    assets = loaded.catalog.asset_by_id
    items = [
        BrandVisualSearchItemResponse(
            asset_ref=score.asset_id[:16],
            asset_kind=VisualAssetKind(str(assets[score.asset_id].asset_kind)),
            roles=[role.value for role in assets[score.asset_id].roles],
            tags=list(assets[score.asset_id].selection_tags),
            approved=True,
            catalog_version=ranking.catalog_version,
            similarity=score.similarity,
        )
        for score in ranking.scores[:limit]
        if score.asset_id in assets
    ]
    return BrandVisualSearchResponse(
        status="ready",
        reason=None,
        query_modality=modality,
        catalog_version=ranking.catalog_version,
        items=items,
        count=len(items),
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


async def _read_visual_query_image(file: UploadFile, max_bytes: int) -> NormalizedVisualImage:
    body = await _read_upload_bounded(file, max_bytes)
    try:
        return await asyncio.to_thread(normalize_visual_embedding_image, body)
    except ValueError:
        raise BrandUploadRejectedError(
            "invalid_visual_query", "visual image query must be a bounded PNG"
        ) from None


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
