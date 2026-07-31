from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.application.ports.image_generation import ImageGenerator
from app.application.services.material_package import (
    create_material_package,
    review_material_package,
)
from app.core.errors import ConflictError, NotFoundError
from app.infrastructure.db.models import ImageArtifactModel, MaterialPackageModel
from app.infrastructure.storage.minio_image_store import ImageObjectDescriptor, MinioImageStore
from app.schemas.material_package import (
    ImageArtifactResponse,
    MaterialPackageCreateRequest,
    MaterialPackageListResponse,
    MaterialPackageResponse,
    MaterialPackageSummaryResponse,
    MaterialReviewRequest,
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
    image_generator: ImageGenerator | None = request.app.state.image_generator
    if not settings.content_enabled or not settings.image_enabled or image_generator is None:
        raise ConflictError("image generation is disabled or not configured")
    result = await create_material_package(
        session_factory=request.app.state.session_factory,
        image_generator=image_generator,
        image_store=request.app.state.image_store,
        run_id=payload.copy_generation_run_id,
        reference_asset=settings.image_reference_asset,
        image_prompt_version=settings.image_prompt_version,
        image_pipeline_version=settings.image_pipeline_version,
        image_provider=settings.image_provider_mode,
        image_model=settings.image_model,
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
    return MaterialPackageResponse(
        **summary.model_dump(),
        package_version=package.package_version,
        topic=package.topic_snapshot,
        copy=package.copy_snapshot,
        sources=package.source_snapshot,
        audit=package.audit_snapshot,
        image=ImageArtifactResponse(
            id=image.id,
            status=cast(Any, image.status),
            provider=image.provider,
            model=image.model,
            width=image.width,
            height=image.height,
            media_type=image.media_type,
            byte_size=image.byte_size,
            sha256=image.sha256,
            error_code=image.error_code,
            download_url=(
                f"/api/v1/material-packages/{package.id}/image"
                if image.status == "succeeded"
                else None
            ),
        ),
        review_note=package.review_note,
        reviewed_at=package.reviewed_at,
        review_url=f"/api/v1/material-packages/{package.id}/review",
    )
