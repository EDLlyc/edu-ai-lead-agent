from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.application.services.material_package import (
    enqueue_material_package,
    retry_material_package_image,
    review_material_package,
)
from app.core.errors import ConflictError, NotFoundError
from app.domain.image_generation import IMAGE_REFERENCE_BUDGET_BYTES
from app.infrastructure.db.models import ImageArtifactModel, MaterialPackageModel
from app.infrastructure.storage.minio_image_store import ImageObjectDescriptor, MinioImageStore
from app.schemas.material_package import (
    ImageArtifactResponse,
    ImageAuditResponse,
    ImageStorageMetadataResponse,
    ImageValidationResponse,
    MaterialPackageCreateRequest,
    MaterialPackageDownloadResponse,
    MaterialPackageListResponse,
    MaterialPackageResponse,
    MaterialPackageSummaryResponse,
    MaterialReviewRequest,
    VisualBriefResponse,
    VisualReferenceResponse,
)

router = APIRouter(tags=["material-packages"])


@router.post(
    "/material-packages",
    response_model=MaterialPackageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_material_package(
    payload: MaterialPackageCreateRequest,
    request: Request,
    response: Response,
) -> MaterialPackageResponse:
    settings = request.app.state.settings
    if (
        not settings.content_enabled
        or not settings.image_enabled
        or settings.image_provider_mode == "disabled"
    ):
        raise ConflictError("image generation is disabled or not configured")
    result = await enqueue_material_package(
        session_factory=request.app.state.session_factory,
        run_id=payload.copy_generation_run_id,
        reference_asset=settings.image_reference_asset,
        image_prompt_version=settings.image_prompt_version,
        image_pipeline_version=settings.image_pipeline_version,
        image_provider=settings.image_provider_mode,
        image_model=settings.image_model,
        image_asset_manifest=getattr(settings, "image_asset_manifest", None),
        image_selector_version=getattr(
            settings, "image_selector_version", "visual-asset-selector-v1"
        ),
        image_selector_enabled=getattr(settings, "image_selector_enabled", False),
        image_max_reference_images=getattr(settings, "image_max_reference_images", 3),
        image_reference_budget_bytes=getattr(
            settings, "image_reference_budget_bytes", IMAGE_REFERENCE_BUDGET_BYTES
        ),
    )
    response.headers["Location"] = f"/api/v1/material-packages/{result.package.id}"
    return _detail_response(result.package, result.image)


@router.get("/material-packages", response_model=MaterialPackageListResponse)
async def list_material_packages(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> MaterialPackageListResponse:
    packages = tuple(
        (
            await session.scalars(
                select(MaterialPackageModel)
                .order_by(MaterialPackageModel.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return MaterialPackageListResponse(
        items=[_summary_response(item) for item in packages], count=len(packages)
    )


@router.get("/material-packages/{package_id}", response_model=MaterialPackageResponse)
async def read_material_package(
    package_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MaterialPackageResponse:
    package = await session.get(MaterialPackageModel, package_id)
    if package is None:
        raise NotFoundError("material package")
    image = await session.get(ImageArtifactModel, package.image_artifact_id)
    if image is None:
        raise NotFoundError("image artifact")
    return _detail_response(package, image)


@router.post("/material-packages/{package_id}/review", response_model=MaterialPackageResponse)
async def review_material_package_route(
    package_id: UUID,
    payload: MaterialReviewRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MaterialPackageResponse:
    package = await review_material_package(
        session=session,
        package_id=package_id,
        decision=payload.decision,
        reviewer=payload.reviewer,
        note=payload.note,
    )
    image = await session.get(ImageArtifactModel, package.image_artifact_id)
    if image is None:
        raise NotFoundError("image artifact")
    return _detail_response(package, image)


@router.post(
    "/material-packages/{package_id}/image/retry",
    response_model=MaterialPackageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_material_package_image_route(
    package_id: UUID,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MaterialPackageResponse:
    settings = request.app.state.settings
    if (
        not settings.content_enabled
        or not settings.image_enabled
        or settings.image_provider_mode == "disabled"
    ):
        raise ConflictError("image generation is disabled or not configured")
    result = await retry_material_package_image(
        session=session,
        package_id=package_id,
        max_attempts=settings.image_max_attempts,
    )
    response.headers["Location"] = f"/api/v1/material-packages/{result.package.id}"
    return _detail_response(result.package, result.image)


@router.get(
    "/material-packages/{package_id}/download",
    response_model=MaterialPackageDownloadResponse,
)
async def download_material_package(
    package_id: UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MaterialPackageDownloadResponse:
    """Return a safe, attachment-friendly JSON package without object-store internals."""

    package = await session.get(MaterialPackageModel, package_id)
    if package is None:
        raise NotFoundError("material package")
    image = await session.get(ImageArtifactModel, package.image_artifact_id)
    if image is None:
        raise NotFoundError("image artifact")
    response.headers.update(
        {
            "Content-Disposition": f'attachment; filename="sai-xiansheng-{package.id}.json"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        }
    )
    detail = _detail_response(package, image)
    return MaterialPackageDownloadResponse(**detail.model_dump())


@router.get("/material-packages/{package_id}/image")
async def download_material_package_image(
    package_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    package = await session.get(MaterialPackageModel, package_id)
    if package is None:
        raise NotFoundError("material package")
    image = await session.get(ImageArtifactModel, package.image_artifact_id)
    if image is None or image.status != "succeeded":
        raise ConflictError("material package image is not available")
    if any(
        value is None
        for value in (
            image.bucket,
            image.object_key,
            image.media_type,
            image.byte_size,
            image.sha256,
        )
    ):
        raise ConflictError("material package image metadata is incomplete")
    descriptor = ImageObjectDescriptor(
        bucket=cast(str, image.bucket),
        object_key=cast(str, image.object_key),
        media_type=cast(str, image.media_type),
        byte_size=cast(int, image.byte_size),
        sha256=cast(str, image.sha256),
    )
    store: MinioImageStore = request.app.state.image_store
    body = await store.get_bytes(descriptor)
    return Response(
        content=body,
        media_type=descriptor.media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="sai-xiansheng-{package.id}.'
                f'{_media_extension(descriptor.media_type)}"'
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _media_extension(media_type: str) -> str:
    return {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(media_type, "bin")


def _summary_response(package: MaterialPackageModel) -> MaterialPackageSummaryResponse:
    business_date = package.topic_snapshot.get("business_date")
    return MaterialPackageSummaryResponse(
        id=package.id,
        copy_generation_run_id=package.run_id,
        status=cast(Any, package.status),
        review_status=cast(Any, package.review_status),
        business_date=business_date if isinstance(business_date, str) else "unknown",
        created_at=package.created_at,
        detail_url=f"/api/v1/material-packages/{package.id}",
    )


def _detail_response(
    package: MaterialPackageModel, image: ImageArtifactModel
) -> MaterialPackageResponse:
    summary = _summary_response(package)
    image_snapshot = package.version_snapshot.get("image", {})
    safe_image_snapshot = image_snapshot if isinstance(image_snapshot, dict) else {}
    visual_brief = safe_image_snapshot.get("visual_brief", {})
    references = safe_image_snapshot.get("references", [])
    reference_mode = safe_image_snapshot.get(
        "reference_mode", getattr(image, "reference_mode", "legacy_single")
    )
    return MaterialPackageResponse(
        **summary.model_dump(),
        package_version=package.package_version,
        topic=package.topic_snapshot,
        copy=package.copy_snapshot,
        sources=package.source_snapshot,
        brand_bindings=package.brand_snapshot,
        validation=package.validation_snapshot,
        audit=package.audit_snapshot,
        versions=package.version_snapshot,
        image=ImageArtifactResponse(
            id=image.id,
            status=cast(Any, image.status),
            provider=image.provider,
            model=image.model,
            request_fingerprint=image.request_fingerprint,
            width=image.width,
            height=image.height,
            media_type=image.media_type,
            byte_size=image.byte_size,
            sha256=image.sha256,
            storage_metadata=ImageStorageMetadataResponse(
                access="private",
                immutable=bool(
                    isinstance(image.storage_metadata, dict)
                    and image.storage_metadata.get("immutable") is True
                ),
                content_addressed=bool(
                    isinstance(image.storage_metadata, dict)
                    and image.storage_metadata.get("content_addressed") is True
                ),
            ),
            error_code=image.error_code,
            download_url=(
                f"/api/v1/material-packages/{package.id}/image"
                if image.status == "succeeded"
                else None
            ),
            reference_mode=cast(Any, reference_mode),
            visual_brief=_safe_visual_brief(visual_brief),
            references=_safe_visual_references(references),
            repair_count=max(0, min(int(getattr(image, "repair_count", 0)), 1)),
            validation=_safe_image_validation(getattr(image, "validation_snapshot", {})),
            audit=_safe_image_audit(getattr(image, "audit_snapshot", {})),
        ),
        review_note=package.review_note,
        reviewed_at=package.reviewed_at,
        review_url=f"/api/v1/material-packages/{package.id}/review",
        download_url=f"/api/v1/material-packages/{package.id}/download",
    )


def _safe_visual_brief(value: object) -> VisualBriefResponse | None:
    if not isinstance(value, dict) or not value:
        return None
    try:
        return VisualBriefResponse.model_validate(value)
    except ValidationError:
        return None


def _safe_visual_references(value: object) -> list[VisualReferenceResponse]:
    if not isinstance(value, list):
        return []
    safe_values: list[VisualReferenceResponse] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            safe_values.append(VisualReferenceResponse.model_validate(item))
        except ValidationError:
            continue
    return safe_values


def _safe_image_validation(value: object) -> ImageValidationResponse:
    fallback = {
        "version": "image-validation-v1",
        "configured": False,
        "passed": None,
        "issue_codes": [],
        "provider": None,
        "model": None,
    }
    if isinstance(value, dict):
        fallback.update(value)
    try:
        return ImageValidationResponse.model_validate(fallback)
    except ValidationError:
        return ImageValidationResponse(
            version="image-validation-v1",
            configured=False,
            passed=None,
            issue_codes=[],
            provider=None,
            model=None,
        )


def _safe_image_audit(value: object) -> ImageAuditResponse:
    fallback = {
        "version": "image-audit-v1",
        "configured": False,
        "status": "not_configured",
        "passed": None,
        "issue_codes": [],
        "provider": None,
        "model": None,
    }
    if isinstance(value, dict):
        fallback.update(value)
    try:
        return ImageAuditResponse.model_validate(fallback)
    except ValidationError:
        return ImageAuditResponse(
            version="image-audit-v1",
            configured=False,
            status="not_configured",
            passed=None,
            issue_codes=[],
            provider=None,
            model=None,
        )
