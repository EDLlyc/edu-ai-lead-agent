from __future__ import annotations

import base64
import binascii
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.application.ports.ip_assets import (
    IpAssetGenerationRecord,
    IpAssetQuery,
    IpAssetRecord,
)
from app.application.services.ip_asset_recognition import IpAssetRecognitionService
from app.application.services.ip_assets import (
    IpAssetService,
    enqueue_ip_asset_generation,
)
from app.core.config import Settings
from app.core.errors import (
    ConflictError,
    IpAssetRecognitionUnavailableError,
    IpAssetUploadRejectedError,
    NotFoundError,
)
from app.domain.ip_assets import (
    IP_ASSET_MAX_BYTES,
    IpAssetCharacter,
    IpAssetMetadata,
    IpAssetOrientation,
    IpAssetSource,
    IpAssetType,
    canonical_download_filename,
    parse_tags,
    validate_asset_ref,
    validate_generation_ref,
)
from app.infrastructure.db.ip_assets import PostgresIpAssetRepository
from app.schemas.ip_assets import (
    IpAssetCapabilitiesResponse,
    IpAssetCardResponse,
    IpAssetDetailResponse,
    IpAssetGenerationRequest,
    IpAssetGenerationResponse,
    IpAssetListResponse,
    IpAssetRecognitionResponse,
    IpAssetSearchItemResponse,
    IpAssetSearchResponse,
    IpAssetTextSearchRequest,
    IpAssetUploadResponse,
    IpAssetZipRequest,
)

router = APIRouter(prefix="/ip-assets", tags=["ip-assets"])
_READ_CHUNK_BYTES = 64 * 1024


@router.get("/capabilities", response_model=IpAssetCapabilitiesResponse)
async def capabilities(request: Request) -> IpAssetCapabilitiesResponse:
    settings: Settings = request.app.state.settings
    return IpAssetCapabilitiesResponse(
        enabled=settings.ip_asset_hub_enabled,
        semantic_search_available=(
            settings.ip_asset_hub_enabled
            and settings.visual_semantic_enabled
            and request.app.state.ip_asset_service is not None
        ),
        generation_available=(
            settings.ip_asset_hub_enabled
            and settings.ip_asset_generation_enabled
            and request.app.state.image_generator is not None
        ),
        recognition_available=(
            settings.ip_asset_hub_enabled
            and getattr(settings, "ip_asset_recognition_enabled", False)
            and getattr(request.app.state, "ip_asset_recognition_service", None) is not None
        ),
        accepted_media_types=["image/png", "image/jpeg", "image/webp"],
    )


@router.get("", response_model=IpAssetListResponse)
@router.get("/", response_model=IpAssetListResponse, include_in_schema=False)
async def list_ip_assets(
    request: Request,
    query: Annotated[str, Query(max_length=200)] = "",
    character: IpAssetCharacter | None = None,
    asset_type: IpAssetType | None = None,
    department: Annotated[str, Query(max_length=80)] = "",
    source_kind: IpAssetSource | None = None,
    orientation: IpAssetOrientation | None = None,
    tag: Annotated[str, Query(max_length=40)] = "",
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=60)] = 24,
) -> IpAssetListResponse:
    service = _service(request)
    cursor_time, cursor_id = _decode_cursor(cursor)
    page = await service.list(
        IpAssetQuery(
            query=query.strip(),
            character=character,
            asset_type=asset_type,
            department=department.strip(),
            source_kind=source_kind,
            orientation=orientation,
            tag=tag.strip(),
            cursor_created_at=cursor_time,
            cursor_id=cursor_id,
            limit=limit,
        )
    )
    return IpAssetListResponse(
        items=[_card(item) for item in page.items],
        next_cursor=_encode_cursor(page.next_cursor_created_at, page.next_cursor_id),
    )


@router.post("", response_model=IpAssetUploadResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=IpAssetUploadResponse, include_in_schema=False)
async def upload_ip_asset(
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File(description="PNG, JPEG, or WebP up to 25 MiB")],
    character: Annotated[IpAssetCharacter, Form()],
    asset_type: Annotated[IpAssetType, Form()],
    department: Annotated[str, Form(max_length=80)] = "",
    contributor: Annotated[str, Form(max_length=80)] = "",
    emotion: Annotated[str, Form(max_length=40)] = "",
    action: Annotated[str, Form(max_length=40)] = "",
    scene: Annotated[str, Form(max_length=60)] = "",
    intended_use: Annotated[str, Form(max_length=60)] = "",
    style: Annotated[str, Form(max_length=40)] = "",
    tags: Annotated[str, Form(max_length=900)] = "",
) -> IpAssetUploadResponse:
    service = _service(request)
    semaphore = request.app.state.ip_asset_upload_semaphore
    async with semaphore:
        body = await _read_upload_bounded(file, IP_ASSET_MAX_BYTES)
        try:
            metadata = IpAssetMetadata(
                character=character,
                asset_type=asset_type,
                department=department,
                contributor=contributor,
                emotion=emotion,
                action=action,
                scene=scene,
                intended_use=intended_use,
                style=style,
                tags=parse_tags(tags),
            )
        except ValueError as error:
            raise IpAssetUploadRejectedError("invalid_ip_asset_metadata") from error
        result = await service.upload(
            filename=file.filename or "asset",
            media_type=file.content_type,
            body=body,
            metadata=metadata,
        )
    response.status_code = status.HTTP_200_OK if result.duplicate else status.HTTP_201_CREATED
    response.headers["Location"] = f"/api/v1/ip-assets/{result.asset.asset_ref}"
    return IpAssetUploadResponse(
        asset=_detail(result.asset),
        duplicate=result.duplicate,
        near_duplicate_ref=result.near_duplicate_ref,
        near_duplicate_distance=result.near_duplicate_distance,
    )


@router.post("/recognitions", response_model=IpAssetRecognitionResponse)
async def recognize_ip_asset(
    request: Request,
    file: Annotated[UploadFile, File(description="Transient PNG, JPEG, or WebP up to 25 MiB")],
) -> IpAssetRecognitionResponse:
    service = _recognition_service(request)
    semaphore = request.app.state.ip_asset_upload_semaphore
    async with semaphore:
        body = await _read_upload_bounded(file, IP_ASSET_MAX_BYTES)
        suggestion = await service.recognize(
            filename=file.filename or "recognition-image",
            media_type=file.content_type,
            body=body,
        )
    return IpAssetRecognitionResponse(
        character=suggestion.character,
        asset_type=suggestion.asset_type,
        emotion=suggestion.emotion,
        action=suggestion.action,
        scene=suggestion.scene,
        intended_use=suggestion.intended_use,
        style=suggestion.style,
        tags=list(suggestion.tags),
        provider=suggestion.provider,
        model=suggestion.model,
    )


@router.post("/search/text", response_model=IpAssetSearchResponse)
async def search_ip_assets_text(
    payload: IpAssetTextSearchRequest, request: Request
) -> IpAssetSearchResponse:
    service = _service(request)
    result = await service.search_text(
        message=payload.message,
        prior_turns=tuple(payload.prior_turns),
        filters=IpAssetQuery(
            query=payload.message,
            character=payload.character,
            asset_type=payload.asset_type,
            department=payload.department,
            source_kind=payload.source_kind,
            orientation=payload.orientation,
            tag=payload.tag,
            limit=payload.limit,
        ),
    )
    return _search_response(result)


@router.post("/search/image", response_model=IpAssetSearchResponse)
async def search_ip_assets_image(
    request: Request,
    file: Annotated[UploadFile, File(description="Transient PNG, JPEG, or WebP query")],
    character: Annotated[IpAssetCharacter | None, Form()] = None,
    asset_type: Annotated[IpAssetType | None, Form()] = None,
    orientation: Annotated[IpAssetOrientation | None, Form()] = None,
    limit: Annotated[int, Form(ge=1, le=40)] = 20,
) -> IpAssetSearchResponse:
    service = _service(request)
    semaphore = request.app.state.ip_asset_upload_semaphore
    # Similarity inputs are transient, but they have the same worst-case raster size as durable
    # uploads. Hold the shared in-process budget through decode/provider use so parallel no-auth
    # requests cannot retain an unbounded number of maximum-sized bodies.
    async with semaphore:
        body = await _read_upload_bounded(file, IP_ASSET_MAX_BYTES)
        result = await service.search_image(
            body=body,
            media_type=file.content_type,
            filters=IpAssetQuery(
                character=character,
                asset_type=asset_type,
                orientation=orientation,
                limit=limit,
            ),
        )
    return _search_response(result)


@router.post("/downloads")
async def download_ip_asset_zip(payload: IpAssetZipRequest, request: Request) -> StreamingResponse:
    service = _service(request)
    refs = tuple(_safe_asset_ref(item) for item in payload.asset_refs)
    body = await service.download_zip(refs)
    return StreamingResponse(
        _single_chunk(body),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="ip-assets.zip"',
            "Content-Length": str(len(body)),
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "/generations",
    response_model=IpAssetGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_ip_asset_generation(
    payload: IpAssetGenerationRequest, request: Request, response: Response
) -> IpAssetGenerationResponse:
    settings: Settings = request.app.state.settings
    _service(request)
    if not settings.ip_asset_generation_enabled or request.app.state.image_generator is None:
        raise ConflictError("IP asset image generation is unavailable")
    repository = PostgresIpAssetRepository(request.app.state.session_factory)
    reference = None
    if payload.reference_asset_ref is not None:
        reference = await repository.get_by_ref(_safe_asset_ref(payload.reference_asset_ref))
        if reference is None:
            raise NotFoundError("IP asset generation reference")
    try:
        metadata = IpAssetMetadata(
            character=payload.character,
            asset_type=payload.asset_type,
            department=payload.department,
            contributor=payload.contributor,
        )
    except ValueError as error:
        raise IpAssetUploadRejectedError("invalid_ip_asset_metadata") from error
    job, created = await enqueue_ip_asset_generation(
        repository=repository,
        prompt=payload.prompt,
        metadata=metadata,
        ratio=payload.ratio,
        reference_asset=reference,
        idempotency_key=payload.idempotency_key,
        provider=settings.image_provider_mode,
        model=settings.image_model,
    )
    response.headers["Location"] = f"/api/v1/ip-assets/generations/{job.job_ref}"
    return await _generation_response(repository, job, created=created)


@router.get("/generations/{job_ref}", response_model=IpAssetGenerationResponse)
async def read_ip_asset_generation(job_ref: str, request: Request) -> IpAssetGenerationResponse:
    _service(request)
    repository = PostgresIpAssetRepository(request.app.state.session_factory)
    try:
        safe_job_ref = validate_generation_ref(job_ref)
    except ValueError as error:
        raise IpAssetUploadRejectedError("invalid_ip_asset_metadata") from error
    job = await repository.get_generation(safe_job_ref)
    if job is None:
        raise NotFoundError("IP asset generation job")
    return await _generation_response(repository, job, created=False)


@router.get("/{asset_ref}", response_model=IpAssetDetailResponse)
async def read_ip_asset(asset_ref: str, request: Request) -> IpAssetDetailResponse:
    return _detail(await _service(request).get(_safe_asset_ref(asset_ref)))


@router.get("/{asset_ref}/preview")
async def preview_ip_asset(asset_ref: str, request: Request) -> StreamingResponse:
    asset, body = await _service(request).original(_safe_asset_ref(asset_ref))
    return StreamingResponse(
        _single_chunk(body),
        media_type=cast(Literal["image/png", "image/jpeg", "image/webp"], asset.media_type),
        headers={
            "Content-Length": str(len(body)),
            "ETag": f'"{asset.blob_sha256}"',
            "Cache-Control": "private, no-store",
            "Content-Disposition": "inline",
        },
    )


@router.get("/{asset_ref}/download")
async def download_ip_asset(asset_ref: str, request: Request) -> StreamingResponse:
    asset, body = await _service(request).original(_safe_asset_ref(asset_ref))
    filename = canonical_download_filename(asset.canonical_slug, asset.media_type)
    return StreamingResponse(
        _single_chunk(body),
        media_type=cast(Literal["image/png", "image/jpeg", "image/webp"], asset.media_type),
        headers={
            "Content-Length": str(len(body)),
            "ETag": f'"{asset.blob_sha256}"',
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def _service(request: Request) -> IpAssetService:
    settings: Settings = request.app.state.settings
    service: IpAssetService | None = request.app.state.ip_asset_service
    if not settings.ip_asset_hub_enabled or service is None:
        raise ConflictError("IP asset hub is disabled")
    return service


def _recognition_service(request: Request) -> IpAssetRecognitionService:
    settings: Settings = request.app.state.settings
    service = getattr(request.app.state, "ip_asset_recognition_service", None)
    if (
        not settings.ip_asset_hub_enabled
        or not getattr(settings, "ip_asset_recognition_enabled", False)
        or service is None
    ):
        raise IpAssetRecognitionUnavailableError()
    return cast(IpAssetRecognitionService, service)


def _safe_asset_ref(value: str) -> str:
    try:
        return validate_asset_ref(value)
    except ValueError as error:
        raise IpAssetUploadRejectedError("invalid_ip_asset_metadata") from error


async def _read_upload_bounded(file: UploadFile, maximum: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise IpAssetUploadRejectedError("image_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


async def _single_chunk(body: bytes) -> AsyncIterator[bytes]:
    yield body


def _card(asset: IpAssetRecord) -> IpAssetCardResponse:
    return IpAssetCardResponse(
        asset_ref=asset.asset_ref,
        canonical_name=asset.canonical_name,
        character=asset.character,
        asset_type=asset.asset_type,
        source_kind=asset.source_kind,
        department=asset.department,
        contributor=asset.contributor,
        emotion=asset.emotion,
        action=asset.action,
        scene=asset.scene,
        intended_use=asset.intended_use,
        style=asset.style,
        tags=list(asset.tags),
        media_type=cast(Literal["image/png", "image/jpeg", "image/webp"], asset.media_type),
        byte_size=asset.byte_size,
        width=asset.width,
        height=asset.height,
        has_alpha=asset.has_alpha,
        orientation=asset.orientation,
        status=asset.status,
        semantic_status=asset.semantic_status,
        created_at=asset.created_at,
        preview_url=f"/api/v1/ip-assets/{asset.asset_ref}/preview",
        download_url=f"/api/v1/ip-assets/{asset.asset_ref}/download",
    )


def _detail(asset: IpAssetRecord) -> IpAssetDetailResponse:
    return IpAssetDetailResponse(
        **_card(asset).model_dump(),
        safe_original_filename=asset.safe_original_filename,
        checksum_ref=asset.blob_sha256[:16],
        name_version=asset.name_version,
    )


def _search_response(result: object) -> IpAssetSearchResponse:
    from app.application.services.ip_assets import IpAssetSearchResult

    if not isinstance(result, IpAssetSearchResult):
        raise TypeError("IP asset search result is invalid")
    return IpAssetSearchResponse(
        mode=result.mode,
        degraded_reason=result.degraded_reason,
        search_version=result.search_version,
        items=[
            IpAssetSearchItemResponse(
                asset=_card(item.asset),
                similarity=item.similarity,
                explanation=item.explanation,
            )
            for item in result.items
        ],
    )


async def _generation_response(
    repository: PostgresIpAssetRepository,
    job: IpAssetGenerationRecord,
    *,
    created: bool,
) -> IpAssetGenerationResponse:
    output_ref = None
    if job.output_asset_id is not None:
        output = await repository.get_by_id(job.output_asset_id)
        output_ref = output.asset_ref if output is not None else None
    return IpAssetGenerationResponse(
        job_ref=job.job_ref,
        status=cast(Literal["queued", "running", "succeeded", "failed"], job.status),
        created=created,
        output_asset_ref=output_ref,
        error_code=job.error_code,
        status_url=f"/api/v1/ip-assets/generations/{job.job_ref}",
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


def _encode_cursor(created_at: datetime | None, asset_id: UUID | None) -> str | None:
    if created_at is None or asset_id is None:
        return None
    payload = json.dumps([created_at.isoformat(), str(asset_id)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str | None) -> tuple[datetime | None, UUID | None]:
    if value is None:
        return None, None
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if not isinstance(raw, list) or len(raw) != 2:
            raise ValueError
        created_at = datetime.fromisoformat(str(raw[0]))
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError
        return created_at, UUID(str(raw[1]))
    except (ValueError, TypeError, json.JSONDecodeError, binascii.Error):
        raise IpAssetUploadRejectedError("invalid_ip_asset_metadata") from None
