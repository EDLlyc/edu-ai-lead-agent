from __future__ import annotations

from datetime import datetime
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
from app.domain.visual_diversity import (
    IMAGE_PERCEPTUAL_HASH_VERSION,
    IMAGE_SIMILARITY_POLICY_VERSION,
    VISUAL_BRIEF_V2_VERSION,
    VISUAL_DIVERSITY_POLICY_VERSION,
    VISUAL_PIPELINE_V3_VERSION,
    VISUAL_PROMPT_V3_VERSION,
    VISUAL_SELECTOR_V2_VERSION,
)
from app.infrastructure.db.models import ImageArtifactModel, MaterialPackageModel
from app.infrastructure.storage.minio_image_store import ImageObjectDescriptor, MinioImageStore
from app.schemas.material_package import (
    ControlledVisualPlanResponse,
    ImageArtifactResponse,
    ImageAuditResponse,
    ImageDiversityResponse,
    ImageFallbackAssetResponse,
    ImageFallbackResponse,
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
        image_diversity_enabled=getattr(settings, "image_diversity_enabled", False),
        image_diversity_policy_version=getattr(
            settings, "image_diversity_policy_version", VISUAL_DIVERSITY_POLICY_VERSION
        ),
        image_visual_brief_version=getattr(
            settings, "image_visual_brief_version", VISUAL_BRIEF_V2_VERSION
        ),
        image_diversity_selector_version=getattr(
            settings,
            "image_diversity_selector_version",
            VISUAL_SELECTOR_V2_VERSION,
        ),
        image_diversity_prompt_version=getattr(
            settings,
            "image_diversity_prompt_version",
            VISUAL_PROMPT_V3_VERSION,
        ),
        image_diversity_pipeline_version=getattr(
            settings,
            "image_diversity_pipeline_version",
            VISUAL_PIPELINE_V3_VERSION,
        ),
        image_perceptual_hash_version=getattr(
            settings, "image_perceptual_hash_version", IMAGE_PERCEPTUAL_HASH_VERSION
        ),
        image_similarity_policy_version=getattr(
            settings, "image_similarity_policy_version", IMAGE_SIMILARITY_POLICY_VERSION
        ),
        image_diversity_history_days=getattr(settings, "image_diversity_history_days", 7),
        image_diversity_history_limit=getattr(settings, "image_diversity_history_limit", 400),
        visual_semantic_enabled=getattr(settings, "visual_semantic_enabled", False),
        visual_retrieval_service=getattr(request.app.state, "visual_retrieval_service", None),
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
    content_slot = package.topic_snapshot.get("content_slot")
    ordinal = package.topic_snapshot.get("ordinal")
    target_at = package.topic_snapshot.get("target_at")
    expires_at = package.topic_snapshot.get("expires_at")
    return MaterialPackageSummaryResponse(
        id=package.id,
        copy_generation_run_id=package.run_id,
        status=cast(Any, package.status),
        review_status=cast(Any, package.review_status),
        business_date=business_date if isinstance(business_date, str) else "unknown",
        content_slot=(
            cast(Any, content_slot) if content_slot in {"morning", "noon", "evening"} else None
        ),
        ordinal=ordinal if isinstance(ordinal, int) and 1 <= ordinal <= 3 else None,
        target_at=_safe_datetime(target_at),
        expires_at=_safe_datetime(expires_at),
        created_at=package.created_at,
        detail_url=f"/api/v1/material-packages/{package.id}",
    )


def _safe_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


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
    controlled_entry = _selected_controlled_plan_entry(safe_image_snapshot, image)
    if controlled_entry is not None:
        visual_brief = getattr(image, "visual_brief_snapshot", {})
        references = controlled_entry.get("references", [])
        reference_mode = controlled_entry.get("reference_mode", reference_mode)
    fallback = _safe_image_fallback(
        safe_image_snapshot.get("fallback"),
        provider_rejection_retry_count=getattr(image, "provider_rejection_retry_count", 0),
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
        versions=_safe_package_versions(package.version_snapshot, fallback=fallback),
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
            fallback=fallback,
            validation=_safe_image_validation(getattr(image, "validation_snapshot", {})),
            audit=_safe_image_audit(getattr(image, "audit_snapshot", {})),
            diversity=_safe_image_diversity(
                safe_image_snapshot,
                controlled_entry=controlled_entry,
                image=image,
            ),
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


def _selected_controlled_plan_entry(
    image_snapshot: dict[str, object], image: ImageArtifactModel
) -> dict[str, object] | None:
    plans = image_snapshot.get("plans")
    if not isinstance(plans, list):
        return None
    final_ordinal = getattr(image, "final_plan_ordinal", None)
    active_ordinal = getattr(image, "active_plan_ordinal", 1)
    selected_ordinal = final_ordinal if final_ordinal in {1, 2} else active_ordinal
    for item in plans:
        if isinstance(item, dict) and item.get("attempt_ordinal") == selected_ordinal:
            return item
    return None


def _safe_image_diversity(
    image_snapshot: dict[str, object],
    *,
    controlled_entry: dict[str, object] | None,
    image: ImageArtifactModel,
) -> ImageDiversityResponse | None:
    if controlled_entry is None:
        return None
    plan_value = controlled_entry.get("plan")
    if not isinstance(plan_value, dict):
        return None
    status_value = image_snapshot.get("diversity")
    status = status_value if isinstance(status_value, dict) else {}
    warning_code = getattr(image, "diversity_warning", None)
    try:
        return ImageDiversityResponse(
            policy_version=str(image_snapshot.get("diversity_policy_version", "")),
            brief_version=str(image_snapshot.get("visual_brief_version", "")),
            selector_version=str(image_snapshot.get("selector_version", "")),
            prompt_version=str(image_snapshot.get("prompt_version", "")),
            pipeline_version=str(image_snapshot.get("pipeline_version", "")),
            similarity_policy_version=str(image_snapshot.get("similarity_policy_version", "")),
            hash_version=str(image_snapshot.get("perceptual_hash_version", "")),
            plan=ControlledVisualPlanResponse.model_validate(plan_value),
            retry_count=max(0, min(int(getattr(image, "diversity_retry_count", 0)), 1)),
            active_plan_ordinal=max(1, min(int(getattr(image, "active_plan_ordinal", 1)), 2)),
            final_plan_ordinal=(
                getattr(image, "final_plan_ordinal", None)
                if getattr(image, "final_plan_ordinal", None) in {1, 2}
                else None
            ),
            warning=warning_code == "near_duplicate_after_retry",
            warning_code=(warning_code if warning_code == "near_duplicate_after_retry" else None),
            near_duplicate=(
                status.get("near_duplicate")
                if isinstance(status.get("near_duplicate"), bool)
                else None
            ),
            exact_duplicate=(
                status.get("exact_duplicate")
                if isinstance(status.get("exact_duplicate"), bool)
                else None
            ),
            nearest_distance=(
                status.get("nearest_distance")
                if isinstance(status.get("nearest_distance"), int)
                else None
            ),
            threshold=(
                status.get("threshold") if isinstance(status.get("threshold"), int) else None
            ),
            candidate_count=(
                status.get("candidate_count")
                if isinstance(status.get("candidate_count"), int)
                else None
            ),
            decision=(
                cast(Any, status.get("decision"))
                if status.get("decision") in {"accepted", "regenerate", "accepted_with_warning"}
                else None
            ),
        )
    except (TypeError, ValueError, ValidationError):
        return None


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


def _safe_image_fallback(
    value: object, *, provider_rejection_retry_count: object
) -> ImageFallbackResponse:
    fallback: dict[str, object] = {
        "version": "image-fallback-v1",
        "state": "not_used",
        "provider_rejection_retry_count": max(
            0,
            min(
                provider_rejection_retry_count
                if isinstance(provider_rejection_retry_count, int)
                else 0,
                1,
            ),
        ),
        "initial_error_code": None,
        "primary_provider": None,
        "primary_model": None,
        "asset": None,
    }
    if isinstance(value, dict):
        state = value.get("state")
        if state in {"not_used", "neutralized_retry", "brand_catalog"}:
            fallback["state"] = state
        initial_error_code = value.get("initial_error_code")
        if _safe_fallback_identifier(initial_error_code, limit=120):
            fallback["initial_error_code"] = initial_error_code
        for key in ("primary_provider", "primary_model"):
            item = value.get(key)
            if _safe_fallback_identifier(item, limit=120):
                fallback[key] = item
        asset = value.get("asset")
        safe_asset = _safe_image_fallback_asset(asset)
        if safe_asset is not None:
            fallback["asset"] = safe_asset
    try:
        return ImageFallbackResponse.model_validate(fallback)
    except ValidationError:
        return ImageFallbackResponse(
            version="image-fallback-v1",
            state="not_used",
            provider_rejection_retry_count=0,
            initial_error_code=None,
            primary_provider=None,
            primary_model=None,
        )


def _safe_package_versions(value: object, *, fallback: ImageFallbackResponse) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    safe_versions = dict(value)
    image = value.get("image")
    if isinstance(image, dict):
        safe_image = dict(image)
        if isinstance(image.get("diversity_policy_version"), str):
            for private_key in ("plans", "history_digest", "diversity"):
                safe_image.pop(private_key, None)
        safe_image["fallback"] = fallback.model_dump(mode="json")
        safe_versions["image"] = safe_image
    return safe_versions


def _safe_fallback_identifier(value: object, *, limit: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= limit
        and all(character.isalnum() or character in "._-" for character in value)
    )


def _safe_image_fallback_asset(value: object) -> ImageFallbackAssetResponse | None:
    if not isinstance(value, dict):
        return None
    filename = value.get("filename")
    selection_reason = value.get("selection_reason")
    role = value.get("role")
    sha256 = value.get("sha256")
    if (
        not _safe_fallback_identifier(value.get("asset_id"), limit=128)
        or not isinstance(filename, str)
        or not 1 <= len(filename) <= 200
        or "/" in filename
        or "\\" in filename
        or not isinstance(sha256, str)
        or len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256.lower())
        or role not in {"identity_reference", "action_reference", "style_reference", "legacy"}
        or not isinstance(selection_reason, str)
        or not 1 <= len(selection_reason) <= 320
        or "://" in selection_reason
        or not isinstance(value.get("fallback"), bool)
    ):
        return None
    try:
        return ImageFallbackAssetResponse.model_validate(
            {
                "asset_id": value["asset_id"],
                "filename": filename,
                "sha256": sha256,
                "role": role,
                "selection_reason": selection_reason,
                "fallback": value["fallback"],
            }
        )
    except ValidationError:
        return None


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
