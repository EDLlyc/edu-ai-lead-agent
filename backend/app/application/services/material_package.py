from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.image_generation import ImageGenerationRequest, ImageGenerator
from app.core.errors import (
    AppError,
    ConflictError,
    ImageOutputValidationError,
    ImageProviderRejectedError,
    NotFoundError,
    ProviderIdentityMismatchError,
)
from app.domain.image_generation import image_checksum, image_request_fingerprint
from app.infrastructure.db.models import (
    CopyAuditModel,
    CopyClaimEvidenceBindingModel,
    CopyDraftClaimModel,
    CopyDraftVersionModel,
    CopyGenerationRunModel,
    ImageArtifactModel,
    MaterialPackageModel,
    MaterialReviewModel,
)
from app.infrastructure.storage.minio_image_store import MinioImageStore


@dataclass(frozen=True, slots=True)
class MaterialPackageResult:
    package: MaterialPackageModel
    image: ImageArtifactModel


async def create_material_package(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    image_generator: ImageGenerator,
    image_store: MinioImageStore,
    run_id: UUID,
    reference_asset: str | None = None,
    image_prompt_version: str = "image-prompt-v1",
    image_pipeline_version: str = "image-pipeline-v1",
    image_provider: str = "fake",
    image_model: str = "gpt-image-2",
) -> MaterialPackageResult:
    (
        run,
        draft,
        prompt,
        audit_snapshot,
        topic_snapshot,
        copy_snapshot,
        source_snapshot,
    ) = await _load_accepted_input(session_factory, run_id)
    reference_body = await _read_reference_asset(reference_asset)
    reference_sha256 = image_checksum(reference_body) if reference_body is not None else None
    fingerprint = image_request_fingerprint(
        run_id=run.id,
        draft_version_id=draft.id,
        prompt=prompt,
        provider=image_provider,
        model=image_model,
        prompt_version=image_prompt_version,
        pipeline_version=image_pipeline_version,
        reference_sha256=reference_sha256,
    )

    # Reserve both rows before crossing the provider boundary.  The unique fingerprint is the
    # idempotency gate; a concurrent/replayed request observes the durable running package and
    # returns it without making another provider call.
    async with session_factory() as session:
        existing = await session.scalar(
            select(ImageArtifactModel)
            .where(ImageArtifactModel.request_fingerprint == fingerprint)
            .with_for_update()
        )
        package = await session.scalar(
            select(MaterialPackageModel).where(
                MaterialPackageModel.request_fingerprint == fingerprint
            )
        )
        if existing is not None:
            if package is None:
                raise ConflictError("image reservation is incomplete; no retry was attempted")
            return MaterialPackageResult(package=package, image=existing)
        image_id = uuid4()
        package_id = uuid4()
        try:
            image = ImageArtifactModel(
                id=image_id,
                run_id=run.id,
                draft_version_id=draft.id,
                request_fingerprint=fingerprint,
                provider=image_provider,
                model=image_model,
                prompt_version=image_prompt_version,
                pipeline_version=image_pipeline_version,
                reference_sha256=reference_sha256,
                status="running",
                attempt_count=1,
            )
            package = MaterialPackageModel(
                id=package_id,
                run_id=run.id,
                draft_version_id=draft.id,
                image_artifact_id=image_id,
                package_version=1,
                request_fingerprint=fingerprint,
                status="queued",
                topic_snapshot=topic_snapshot,
                copy_snapshot=copy_snapshot,
                source_snapshot=source_snapshot,
                audit_snapshot=audit_snapshot,
                review_status="pending",
            )
            session.add_all((image, package))
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = await session.scalar(
                select(ImageArtifactModel).where(
                    ImageArtifactModel.request_fingerprint == fingerprint
                )
            )
            package = await session.scalar(
                select(MaterialPackageModel).where(
                    MaterialPackageModel.request_fingerprint == fingerprint
                )
            )
            if existing is None or package is None:
                raise
            return MaterialPackageResult(package=package, image=existing)

    try:
        result = await image_generator.generate(
            ImageGenerationRequest(
                run_id=run.id,
                draft_version_id=draft.id,
                prompt=prompt,
                request_fingerprint=fingerprint,
                reference_image=reference_body,
                reference_filename="reference.png",
            )
        )
        if (
            result.request_fingerprint != fingerprint
            or result.provider != image_provider
            or result.model != image_model
        ):
            raise ProviderIdentityMismatchError()
        if (
            result.width != 1024
            or result.height != 1024
            or result.media_type not in {"image/png", "image/jpeg", "image/webp"}
        ):
            raise ImageOutputValidationError()
        descriptor = await image_store.put_immutable(
            result.image_bytes, media_type=result.media_type
        )
    except (AppError, ValueError) as error:
        await _finish_failed_material_package(
            session_factory,
            image_id=image_id,
            package_id=package_id,
            error_code=error.code if isinstance(error, AppError) else "image_output_invalid",
            review_required=(
                isinstance(error, (ImageOutputValidationError, ImageProviderRejectedError))
                or isinstance(error, ValueError)
            ),
        )
        async with session_factory() as session:
            loaded_image = await session.get(ImageArtifactModel, image_id)
            loaded_package = await session.get(MaterialPackageModel, package_id)
            if loaded_image is None or loaded_package is None:
                raise ConflictError("image reservation disappeared") from None
            return MaterialPackageResult(package=loaded_package, image=loaded_image)

    now = datetime.now(UTC)
    async with session_factory() as session:
        loaded_image = await session.get(ImageArtifactModel, image_id)
        loaded_package = await session.get(MaterialPackageModel, package_id)
        if loaded_image is None or loaded_package is None:
            raise ConflictError("image reservation disappeared")
        loaded_image.provider_task_id = result.provider_task_id
        loaded_image.provider_upload_id = result.provider_upload_id
        loaded_image.status = "succeeded"
        loaded_image.attempt_count = max(1, result.attempts)
        loaded_image.media_type = result.media_type
        loaded_image.width = result.width
        loaded_image.height = result.height
        loaded_image.byte_size = descriptor.byte_size
        loaded_image.sha256 = descriptor.sha256
        loaded_image.bucket = descriptor.bucket
        loaded_image.object_key = descriptor.object_key
        loaded_image.completed_at = now
        loaded_package.status = "awaiting_manual_use"
        await session.commit()
        return MaterialPackageResult(package=loaded_package, image=loaded_image)


async def _read_reference_asset(reference_asset: str | None) -> bytes | None:
    if reference_asset is None:
        return None
    path = Path(reference_asset)
    if not await asyncio.to_thread(path.is_file):
        raise ConflictError("approved image reference is unavailable")
    body = await asyncio.to_thread(path.read_bytes)
    if not body:
        raise ConflictError("approved image reference is empty")
    return body


async def _finish_failed_material_package(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    image_id: UUID,
    package_id: UUID,
    error_code: str,
    review_required: bool,
) -> None:
    async with session_factory() as session:
        image = await session.get(ImageArtifactModel, image_id)
        package = await session.get(MaterialPackageModel, package_id)
        if image is None or package is None:
            return
        image.status = "review_required" if review_required else "failed"
        image.error_code = error_code
        package.status = "failed"
        await session.commit()


async def review_material_package(
    *,
    session: AsyncSession,
    package_id: UUID,
    decision: str,
    reviewer: str,
    note: str | None,
) -> MaterialPackageModel:
    package = await session.get(MaterialPackageModel, package_id)
    if package is None:
        raise NotFoundError("material package")
    if package.status not in {"awaiting_manual_use", "ready", "completed", "rejected"}:
        raise ConflictError("material package is not reviewable")
    review = await session.scalar(
        select(MaterialReviewModel)
        .where(MaterialReviewModel.package_id == package_id)
        .with_for_update()
    )
    if review is not None:
        if review.decision != decision or review.reviewer != reviewer or review.note != note:
            raise ConflictError("material package already has a different review decision")
        return package
    now = datetime.now(UTC)
    review = MaterialReviewModel(
        id=uuid4(), package_id=package_id, decision=decision, reviewer=reviewer, note=note
    )
    session.add(review)
    package.review_status = decision
    package.review_note = note
    package.reviewed_at = now
    package.status = "completed" if decision == "approved" else "rejected"
    await session.commit()
    return package


async def _load_accepted_input(
    session_factory: async_sessionmaker[AsyncSession], run_id: UUID
) -> tuple[
    CopyGenerationRunModel,
    CopyDraftVersionModel,
    str,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
]:
    async with session_factory() as session:
        run = await session.get(CopyGenerationRunModel, run_id)
        if run is None:
            raise NotFoundError("copy generation run")
        if run.status != "accepted" or run.active_draft_version_id is None:
            raise ConflictError("copy generation run does not have an accepted draft")
        draft = await session.get(CopyDraftVersionModel, run.active_draft_version_id)
        if draft is None or not draft.validation_passed or draft.audit_accepted is not True:
            raise ConflictError("accepted draft is unavailable for image generation")
        audit = await session.scalar(
            select(CopyAuditModel).where(CopyAuditModel.draft_version_id == draft.id)
        )
        audit_snapshot: dict[str, Any] = {
            "accepted": bool(draft.audit_accepted),
            "rule_version": draft.rule_version,
            "audit_id": str(audit.id) if audit else None,
        }
        topic_snapshot = {
            "business_date": run.business_date.isoformat(),
            "timezone": run.timezone,
            "decision_kind": run.decision_kind,
            "selected_event_id": str(run.selected_event_id) if run.selected_event_id else None,
            "selected_event_version_id": str(run.selected_event_version_id)
            if run.selected_event_version_id
            else None,
        }
        copy_snapshot = {
            "draft_version_id": str(draft.id),
            "version": draft.version,
            "copywriting": draft.copywriting,
            "parent_takeaway": draft.parent_takeaway,
            "interaction": draft.interaction,
            "source_note": draft.source_note,
        }
        claims = tuple(
            (
                await session.scalars(
                    select(CopyDraftClaimModel)
                    .where(CopyDraftClaimModel.draft_version_id == draft.id)
                    .order_by(CopyDraftClaimModel.ordinal)
                )
            ).all()
        )
        bindings: list[dict[str, Any]] = []
        for claim in claims:
            evidence = tuple(
                (
                    await session.scalars(
                        select(CopyClaimEvidenceBindingModel).where(
                            CopyClaimEvidenceBindingModel.claim_id == claim.id
                        )
                    )
                ).all()
            )
            for item in evidence:
                bindings.append(
                    {
                        "claim_id": claim.claim_key,
                        "source_url": item.source_url,
                        "source_tier": item.source_tier,
                        "published_at": item.published_at.isoformat()
                        if item.published_at
                        else None,
                        "exact_quote": item.exact_quote,
                    }
                )
        return (
            run,
            draft,
            draft.image_prompt,
            audit_snapshot,
            topic_snapshot,
            copy_snapshot,
            bindings,
        )
