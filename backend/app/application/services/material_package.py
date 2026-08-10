from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import structlog
from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageGenerator,
    ImageReference,
)
from app.application.ports.image_validation import (
    ImageQualityAuditor,
    ImageQualityAuditRequest,
    ImageTextRecognitionRequest,
    ImageTextRecognizer,
)
from app.core.config import Settings
from app.core.errors import (
    AppError,
    ConflictError,
    ImageOutputValidationError,
    ImageProviderRejectedError,
    NotFoundError,
    ProviderIdentityMismatchError,
)
from app.domain.image_fallback import (
    IMAGE_CATALOG_FALLBACK_RENDERER_VERSION,
    build_provider_rejection_retry_prompt,
    provider_rejection_retry_fingerprint,
    render_catalog_fallback_image,
)
from app.domain.image_generation import (
    IMAGE_REFERENCE_BUDGET_BYTES,
    image_checksum,
    image_request_fingerprint,
)
from app.domain.image_validation import (
    build_image_repair_prompt,
    image_repair_fingerprint,
    validate_exact_visual_text,
    validate_image_output,
)
from app.domain.visual_assets import AssetSelectionRequest, SelectedVisualAsset, VisualAssetRole
from app.domain.visual_brief import (
    AcceptedVisualContext,
    VisualBrief,
    VisualReferenceDescriptor,
    VisualReferenceRole,
    build_visual_brief,
    build_visual_prompt_bundle,
)
from app.infrastructure.brand.visual_catalog import (
    load_visual_catalog,
    read_selected_reference,
    select_visual_assets,
)
from app.infrastructure.db.models import (
    BrandChunkModel,
    BrandDocumentModel,
    BrandDocumentVersionModel,
    CopyAuditModel,
    CopyClaimBrandBindingModel,
    CopyClaimEvidenceBindingModel,
    CopyDraftClaimModel,
    CopyDraftVersionModel,
    CopyGenerationRunModel,
    CopyIssueModel,
    CopyValidationResultModel,
    DailyTopicSelectionModel,
    EventClusterVersionModel,
    ImageArtifactModel,
    ImageArtifactReferenceModel,
    MaterialPackageModel,
    MaterialReviewModel,
    TopicScoreModel,
)
from app.infrastructure.storage.minio_image_store import ImageObjectDescriptor, MinioImageStore

logger = structlog.get_logger()


_PRIVATE_STORAGE_METADATA: dict[str, object] = {
    "access": "private",
    "immutable": True,
    "content_addressed": True,
}


@dataclass(frozen=True, slots=True)
class MaterialPackageResult:
    package: MaterialPackageModel
    image: ImageArtifactModel


@dataclass(frozen=True, slots=True)
class AcceptedMaterialInput:
    run: CopyGenerationRunModel
    draft: CopyDraftVersionModel
    prompt: str
    topic_snapshot: dict[str, Any]
    copy_snapshot: dict[str, Any]
    source_snapshot: list[dict[str, Any]]
    brand_snapshot: list[dict[str, Any]]
    validation_snapshot: dict[str, Any]
    audit_snapshot: dict[str, Any]
    version_snapshot: dict[str, Any]
    visual_brief: VisualBrief | None = None


@dataclass(frozen=True, slots=True)
class ReservedVisualReference:
    role: str
    asset_id: str
    filename: str
    sha256: str
    selection_reason: str
    fallback: bool


@dataclass(frozen=True, slots=True)
class PreparedImageInput:
    prompt: str
    references: tuple[ImageReference, ...]
    reserved_references: tuple[ReservedVisualReference, ...]
    reference_mode: str
    visual_brief_snapshot: dict[str, Any]
    visual_brief_fingerprint: str
    catalog_version: str
    selector_version: str
    selection_seed: str = ""


@dataclass(frozen=True, slots=True)
class ClaimedMaterialPackage:
    package_id: UUID
    image_id: UUID
    run_id: UUID
    draft_version_id: UUID
    request_fingerprint: str
    provider: str
    model: str
    prompt: str
    reference_sha256: str | None
    lease_token: UUID
    attempt_number: int
    eligible: bool = True
    references: tuple[ReservedVisualReference, ...] = ()
    reference_mode: str = "legacy_single"
    visual_brief_snapshot: dict[str, Any] | None = None
    catalog_version: str = "no-catalog"
    selector_version: str = "no-selector"
    repair_count: int = 0
    provider_rejection_retry_count: int = 0
    visual_brief: VisualBrief | None = None


async def enqueue_material_package(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    reference_asset: str | None = None,
    image_prompt_version: str = "image-prompt-v1",
    image_pipeline_version: str = "image-pipeline-v1",
    image_provider: str = "fake",
    image_model: str = "gpt-image-2",
    image_asset_manifest: str | None = None,
    image_selector_version: str = "visual-asset-selector-v1",
    image_selector_enabled: bool = True,
    image_max_reference_images: int = 3,
    image_reference_budget_bytes: int = IMAGE_REFERENCE_BUDGET_BYTES,
) -> MaterialPackageResult:
    accepted = await _load_accepted_input(session_factory, run_id)
    prepared = await asyncio.to_thread(
        _prepare_image_input,
        accepted,
        reference_asset=reference_asset,
        image_asset_manifest=image_asset_manifest,
        image_provider=image_provider,
        image_prompt_version=image_prompt_version,
        image_pipeline_version=image_pipeline_version,
        image_selector_version=image_selector_version,
        image_selector_enabled=image_selector_enabled,
        image_max_reference_images=image_max_reference_images,
        image_reference_budget_bytes=image_reference_budget_bytes,
        selection_seed=str(accepted.run.id),
    )
    reference_sha256 = prepared.references[0].sha256 if prepared.references else None
    fingerprint = image_request_fingerprint(
        run_id=accepted.run.id,
        draft_version_id=accepted.draft.id,
        prompt=prepared.prompt,
        provider=image_provider,
        model=image_model,
        prompt_version=image_prompt_version,
        pipeline_version=image_pipeline_version,
        reference_sha256=reference_sha256,
        reference_sha256s=tuple(reference.sha256 for reference in prepared.references),
        visual_brief_fingerprint=prepared.visual_brief_fingerprint,
        catalog_version=prepared.catalog_version,
        selector_version=prepared.selector_version,
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
        conflicting = await session.scalar(
            select(ImageArtifactModel)
            .where(
                ImageArtifactModel.run_id == accepted.run.id,
                ImageArtifactModel.draft_version_id == accepted.draft.id,
            )
            .with_for_update()
        )
        if conflicting is not None:
            raise ConflictError("accepted draft already has a different image request")
        image_id = uuid4()
        package_id = uuid4()
        try:
            image = ImageArtifactModel(
                id=image_id,
                run_id=accepted.run.id,
                draft_version_id=accepted.draft.id,
                request_fingerprint=fingerprint,
                provider=image_provider,
                model=image_model,
                prompt_version=image_prompt_version,
                pipeline_version=image_pipeline_version,
                reference_sha256=reference_sha256,
                reference_mode=prepared.reference_mode,
                visual_brief_snapshot=prepared.visual_brief_snapshot,
                status="queued",
                available_at=datetime.now(UTC),
                attempt_count=0,
                repair_count=0,
                provider_rejection_retry_count=0,
                validation_snapshot={},
                audit_snapshot={},
                storage_metadata=dict(_PRIVATE_STORAGE_METADATA),
            )
            package = MaterialPackageModel(
                id=package_id,
                run_id=accepted.run.id,
                draft_version_id=accepted.draft.id,
                image_artifact_id=image_id,
                package_version=1,
                request_fingerprint=fingerprint,
                status="queued",
                topic_snapshot=accepted.topic_snapshot,
                copy_snapshot=accepted.copy_snapshot,
                source_snapshot=accepted.source_snapshot,
                brand_snapshot=accepted.brand_snapshot,
                validation_snapshot=accepted.validation_snapshot,
                audit_snapshot=accepted.audit_snapshot,
                version_snapshot={
                    **accepted.version_snapshot,
                    "image": {
                        "provider": image_provider,
                        "model": image_model,
                        "prompt_version": image_prompt_version,
                        "pipeline_version": image_pipeline_version,
                        "reference_mode": prepared.reference_mode,
                        "visual_brief": prepared.visual_brief_snapshot,
                        "references": [
                            {
                                "role": reference.role,
                                "asset_id": reference.asset_id,
                                "filename": reference.filename,
                                "sha256": reference.sha256,
                                "selection_reason": reference.selection_reason,
                                "fallback": reference.fallback,
                            }
                            for reference in prepared.reserved_references
                        ],
                        "catalog_version": prepared.catalog_version,
                        "selector_version": prepared.selector_version,
                        "selection_seed": prepared.selection_seed,
                        "fallback": _image_fallback_snapshot(
                            state="not_used",
                            provider_rejection_retry_count=0,
                        ),
                    },
                },
                review_status="pending",
            )
            reference_rows = tuple(
                ImageArtifactReferenceModel(
                    id=uuid4(),
                    image_artifact_id=image_id,
                    asset_id=reference.asset_id,
                    reference_role=reference.role,
                    ordinal=ordinal,
                    asset_sha256=reference.sha256,
                    filename=reference.filename,
                    catalog_version=prepared.catalog_version,
                    selector_version=prepared.selector_version,
                    selection_reason=reference.selection_reason,
                    fallback_used=reference.fallback,
                )
                for ordinal, reference in enumerate(prepared.reserved_references)
            )
            session.add_all((image, package, *reference_rows))
            await session.commit()
        except IntegrityError as error:
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
                conflicting = await session.scalar(
                    select(ImageArtifactModel).where(
                        ImageArtifactModel.run_id == accepted.run.id,
                        ImageArtifactModel.draft_version_id == accepted.draft.id,
                    )
                )
                if conflicting is not None:
                    raise ConflictError(
                        "accepted draft already has a different image request"
                    ) from error
                raise
            return MaterialPackageResult(package=package, image=existing)
    async with session_factory() as session:
        loaded_image = await session.get(ImageArtifactModel, image_id)
        loaded_package = await session.get(MaterialPackageModel, package_id)
        if loaded_image is None or loaded_package is None:
            raise ConflictError("image reservation disappeared")
        return MaterialPackageResult(package=loaded_package, image=loaded_image)


async def create_material_package(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    reference_asset: str | None = None,
    image_prompt_version: str = "image-prompt-v1",
    image_pipeline_version: str = "image-pipeline-v1",
    image_provider: str = "fake",
    image_model: str = "gpt-image-2",
    image_generator: ImageGenerator | None = None,
    image_store: MinioImageStore | None = None,
) -> MaterialPackageResult:
    """Compatibility name for the enqueue-only package boundary.

    The provider and storage arguments remain accepted for callers compiled against the first
    package slice, but are intentionally unused.  Image generation belongs to the content worker.
    """

    del image_generator, image_store
    return await enqueue_material_package(
        session_factory=session_factory,
        run_id=run_id,
        reference_asset=reference_asset,
        image_prompt_version=image_prompt_version,
        image_pipeline_version=image_pipeline_version,
        image_provider=image_provider,
        image_model=image_model,
    )


async def retry_material_package_image(
    *,
    session: AsyncSession,
    package_id: UUID,
    max_attempts: int,
) -> MaterialPackageResult:
    """Explicitly requeue one terminal image without changing its accepted copy version."""

    if max_attempts < 1:
        raise ValueError("image retry limit must be positive")
    package = await session.scalar(
        select(MaterialPackageModel).where(MaterialPackageModel.id == package_id).with_for_update()
    )
    if package is None:
        raise NotFoundError("material package")
    image = await session.scalar(
        select(ImageArtifactModel)
        .where(ImageArtifactModel.id == package.image_artifact_id)
        .with_for_update()
    )
    if image is None:
        raise ConflictError("material package image is unavailable")
    if package.status != "failed" or image.status not in {"failed", "review_required"}:
        raise ConflictError("material package image is not eligible for retry")
    if image.attempt_count >= max_attempts:
        raise ConflictError("material package image retry limit is exhausted")

    now = datetime.now(UTC)
    image.status = "queued"
    image.error_code = None
    image.available_at = now
    image.completed_at = None
    _clear_image_lease(image)
    package.status = "queued"
    await session.commit()
    return MaterialPackageResult(package=package, image=image)


async def _read_reference_asset(reference_asset: str | None) -> bytes | None:
    if reference_asset is None:
        return None
    path = Path(reference_asset)
    if await asyncio.to_thread(path.is_symlink) or not await asyncio.to_thread(path.is_file):
        raise ConflictError("approved image reference is unavailable")
    body = await asyncio.to_thread(path.read_bytes)
    if not body:
        raise ConflictError("approved image reference is empty")
    return body


def _prepare_image_input(
    accepted: AcceptedMaterialInput,
    *,
    reference_asset: str | None,
    image_asset_manifest: str | None,
    image_provider: str,
    image_prompt_version: str,
    image_pipeline_version: str,
    image_selector_version: str,
    image_selector_enabled: bool,
    image_max_reference_images: int,
    image_reference_budget_bytes: int,
    selection_seed: str = "",
) -> PreparedImageInput:
    brief = accepted.visual_brief
    if not image_selector_enabled or image_asset_manifest is None or brief is None:
        reference_body = _read_reference_asset_sync(reference_asset)
        references: tuple[ImageReference, ...] = ()
        if reference_body is not None:
            references = (
                ImageReference(
                    role="legacy",
                    asset_id="legacy-reference",
                    filename="reference.png",
                    sha256=image_checksum(reference_body),
                    image_bytes=reference_body,
                    selection_reason="legacy configured reference",
                ),
            )
        return PreparedImageInput(
            prompt=accepted.prompt,
            references=references,
            reserved_references=tuple(
                ReservedVisualReference(
                    role=reference.role,
                    asset_id=reference.asset_id,
                    filename=reference.filename,
                    sha256=reference.sha256,
                    selection_reason=reference.selection_reason,
                    fallback=False,
                )
                for reference in references
            ),
            reference_mode="legacy_single",
            visual_brief_snapshot={},
            visual_brief_fingerprint="no-visual-brief",
            catalog_version="no-catalog",
            selector_version="no-selector",
            selection_seed="",
        )

    try:
        loaded = load_visual_catalog(image_asset_manifest)
        selection_request = AssetSelectionRequest(
            category=brief.category.value,
            topic=brief.text_layer.title,
            asset_tags=brief.asset_tags,
            characters=brief.characters,
            main_action=brief.main_action,
            poses=brief.asset_tags,
            reference_roles=tuple(VisualAssetRole(role.value) for role in brief.reference_roles),
            max_references=image_max_reference_images,
            max_reference_bytes=image_reference_budget_bytes,
            selection_seed=selection_seed,
        )
        selection = select_visual_assets(
            loaded,
            selection_request,
            selector_version=image_selector_version,
            max_references=image_max_reference_images,
            max_reference_bytes=image_reference_budget_bytes,
        )
        references = tuple(
            read_selected_reference(loaded, selected) for selected in selection.selected_assets
        )
        descriptors = tuple(
            VisualReferenceDescriptor(
                asset_id=reference.asset_id,
                role=VisualReferenceRole(reference.role),
                filename=reference.filename,
                checksum=reference.sha256,
            )
            for reference in references
        )
        prompt_bundle = build_visual_prompt_bundle(
            brief,
            descriptors,
            prompt_version=image_prompt_version,
            pipeline_version=image_pipeline_version,
        )
    except (OSError, ValueError) as error:
        raise ConflictError("approved visual asset selection is invalid") from error

    provider_single_reference = image_provider == "toapis" and len(references) > 1
    reserved_references = tuple(
        ReservedVisualReference(
            role=selected.role.value,
            asset_id=selected.asset_id,
            filename=selected.filename,
            sha256=selected.asset.checksum,
            selection_reason=selected.reason,
            fallback=selected.fallback or provider_single_reference,
        )
        for selected in selection.selected_assets
    )
    # ToAPIs currently accepts one uploaded reference. Keep every selected asset in the immutable
    # package snapshot, but make the provider limitation explicit for the worker and UI.
    reference_mode = (
        "single_fallback" if provider_single_reference else selection.reference_mode.value
    )
    return PreparedImageInput(
        prompt=prompt_bundle.prompt,
        references=references,
        reserved_references=reserved_references,
        reference_mode=reference_mode,
        visual_brief_snapshot=brief.as_metadata(),
        visual_brief_fingerprint=brief.fingerprint,
        catalog_version=selection.catalog_version,
        selector_version=selection.selector_version,
        selection_seed=selection.selection_seed,
    )


def _read_reference_asset_sync(reference_asset: str | None) -> bytes | None:
    if reference_asset is None:
        return None
    path = Path(reference_asset)
    if not path.is_file() or path.is_symlink():
        raise ConflictError("approved image reference is unavailable")
    body = path.read_bytes()
    if not body:
        raise ConflictError("approved image reference is empty")
    return body


def _reserved_references_from_rows(
    rows: tuple[ImageArtifactReferenceModel, ...],
) -> tuple[ReservedVisualReference, ...]:
    return tuple(
        ReservedVisualReference(
            role=row.reference_role,
            asset_id=row.asset_id,
            filename=row.filename,
            sha256=row.asset_sha256,
            selection_reason=row.selection_reason,
            fallback=row.fallback_used,
        )
        for row in sorted(rows, key=lambda item: item.ordinal)
    )


def _claim_prompt(
    *,
    package: MaterialPackageModel,
    draft: CopyDraftVersionModel,
    image: ImageArtifactModel,
    references: tuple[ReservedVisualReference, ...],
) -> tuple[str, dict[str, Any] | None, VisualBrief | None]:
    provider_rejection_retry_count = getattr(image, "provider_rejection_retry_count", 0)
    if image.reference_mode == "legacy_single":
        if provider_rejection_retry_count > 0:
            legacy_title = package.topic_snapshot.get("title")
            legacy_summary = package.topic_snapshot.get("summary")
            brief = build_visual_brief(
                AcceptedVisualContext(
                    topic_title=legacy_title if isinstance(legacy_title, str) else "科学探索",
                    topic_summary=legacy_summary if isinstance(legacy_summary, str) else None,
                    copywriting=draft.copywriting,
                    image_prompt=draft.image_prompt,
                )
            )
            return build_provider_rejection_retry_prompt(brief, ()), brief.as_metadata(), brief
        prompt = draft.image_prompt
        if getattr(image, "repair_count", 0) > 0:
            prompt = build_image_repair_prompt(
                prompt,
                _image_issue_codes(
                    getattr(image, "validation_snapshot", {}),
                    getattr(image, "audit_snapshot", {}),
                ),
            )
        return prompt, None, None
    topic_snapshot = package.topic_snapshot
    title = topic_snapshot.get("title")
    summary = topic_snapshot.get("summary")
    version_value = image.visual_brief_snapshot.get("version")
    visual_version = version_value if isinstance(version_value, str) else "visual-brief-v1"
    brief = build_visual_brief(
        AcceptedVisualContext(
            topic_title=title if isinstance(title, str) and title else "科学探索",
            topic_summary=summary if isinstance(summary, str) else None,
            copywriting=draft.copywriting,
            image_prompt=draft.image_prompt,
        ),
        version=visual_version,
    )
    descriptors = tuple(
        VisualReferenceDescriptor(
            asset_id=reference.asset_id,
            role=VisualReferenceRole(reference.role),
            filename=reference.filename,
            checksum=reference.sha256,
        )
        for reference in references
    )
    prompt = build_visual_prompt_bundle(
        brief,
        descriptors,
        prompt_version=image.prompt_version,
        pipeline_version=image.pipeline_version,
    ).prompt
    if provider_rejection_retry_count > 0:
        prompt = build_provider_rejection_retry_prompt(brief, descriptors)
    elif getattr(image, "repair_count", 0) > 0:
        prompt = build_image_repair_prompt(
            prompt,
            _image_issue_codes(
                getattr(image, "validation_snapshot", {}), getattr(image, "audit_snapshot", {})
            ),
        )
    return prompt, brief.as_metadata(), brief


class MaterialPackageExecutor:
    """Claim queued image reservations and assemble their package outside API requests."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        image_generator: ImageGenerator,
        image_store: MinioImageStore,
        settings: Settings,
        reference_asset: str | None,
        image_text_recognizer: ImageTextRecognizer | None = None,
        image_quality_auditor: ImageQualityAuditor | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._image_generator = image_generator
        self._image_store = image_store
        self._settings = settings
        self._reference_asset = reference_asset
        self._image_text_recognizer = image_text_recognizer
        self._image_quality_auditor = image_quality_auditor
        self._lease_events: dict[UUID, asyncio.Event] = {}

    async def reconcile_ready_packages(self, *, limit: int = 20) -> int:
        """Reserve images for accepted copy runs that have not reached the image stage yet."""
        async with self._session_factory() as session:
            runs = tuple(
                (
                    await session.scalars(
                        select(CopyGenerationRunModel)
                        .outerjoin(
                            MaterialPackageModel,
                            MaterialPackageModel.run_id == CopyGenerationRunModel.id,
                        )
                        .where(
                            CopyGenerationRunModel.status == "accepted",
                            CopyGenerationRunModel.active_draft_version_id.is_not(None),
                            MaterialPackageModel.id.is_(None),
                        )
                        .order_by(CopyGenerationRunModel.created_at)
                        .limit(limit)
                    )
                ).all()
            )

        created = 0
        for run in runs:
            try:
                await enqueue_material_package(
                    session_factory=self._session_factory,
                    run_id=run.id,
                    reference_asset=self._reference_asset,
                    image_prompt_version=self._settings.image_prompt_version,
                    image_pipeline_version=self._settings.image_pipeline_version,
                    image_provider=self._settings.image_provider_mode,
                    image_model=self._settings.image_model,
                    image_asset_manifest=self._settings.image_asset_manifest,
                    image_selector_version=self._settings.image_selector_version,
                    image_selector_enabled=self._settings.image_selector_enabled,
                    image_max_reference_images=self._settings.image_max_reference_images,
                    image_reference_budget_bytes=self._settings.image_reference_budget_bytes,
                )
            except ConflictError as error:
                # Another API request or worker may have won the same idempotency race.
                logger.info(
                    "material_package_reconcile_skipped",
                    run_id=str(run.id),
                    error_code=error.code,
                )
                continue
            except AppError as error:
                # Keep malformed local input visible without taking down the worker loop.
                logger.warning(
                    "material_package_reconcile_failed",
                    run_id=str(run.id),
                    error_code=error.code,
                )
                continue
            created += 1
        return created

    async def execute_next(self, worker_id: str) -> bool:
        claimed = await self._claim(worker_id)
        if claimed is None:
            return False
        if not claimed.eligible:
            return True

        lease_lost = asyncio.Event()
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat_loop(claimed, stop, lease_lost))
        self._lease_events[claimed.image_id] = lease_lost
        validation_snapshot: dict[str, Any] = {}
        audit_snapshot = _image_audit_not_run_snapshot()
        references: tuple[ImageReference, ...] = ()
        try:
            self._ensure_lease(lease_lost)
            references = await self._read_claimed_references(claimed)
            reference_body = (
                await _read_reference_asset(self._reference_asset) if not references else None
            )
            if references:
                if claimed.reference_sha256 != references[0].sha256:
                    raise ConflictError("approved visual reference changed after reservation")
            elif (claimed.reference_sha256 is None and reference_body is not None) or (
                claimed.reference_sha256 is not None
                and (
                    reference_body is None
                    or image_checksum(reference_body) != claimed.reference_sha256
                )
            ):
                raise ConflictError("approved image reference changed after reservation")
            self._ensure_lease(lease_lost)
            provider_request_fingerprint = None
            if claimed.provider_rejection_retry_count:
                provider_request_fingerprint = provider_rejection_retry_fingerprint(
                    claimed.request_fingerprint, claimed.prompt
                )
            elif claimed.repair_count:
                provider_request_fingerprint = image_repair_fingerprint(
                    claimed.request_fingerprint,
                    claimed.repair_count,
                    claimed.prompt,
                )
            result = await self._image_generator.generate(
                ImageGenerationRequest(
                    run_id=claimed.run_id,
                    draft_version_id=claimed.draft_version_id,
                    prompt=claimed.prompt,
                    request_fingerprint=claimed.request_fingerprint,
                    reference_image=reference_body,
                    reference_filename="reference.png",
                    references=references,
                    reference_mode=claimed.reference_mode,
                    provider_request_fingerprint=provider_request_fingerprint,
                )
            )
            if (
                result.request_fingerprint != claimed.request_fingerprint
                or result.provider != claimed.provider
                or result.model != claimed.model
            ):
                raise ProviderIdentityMismatchError()
            output_validation = validate_image_output(
                image_bytes=result.image_bytes,
                media_type=result.media_type,
                reported_dimensions=(result.width, result.height)
                if result.width is not None and result.height is not None
                else None,
                max_bytes=self._settings.image_max_download_bytes,
            )
            validation_snapshot = _image_validation_snapshot(output_validation, configured=True)
            audit_snapshot = _image_audit_not_run_snapshot()
            if not output_validation.passed:
                await self._finish_attempt(
                    claimed,
                    error_code="image_output_validation_failed",
                    retryable=False,
                    review_required=True,
                    validation_snapshot=validation_snapshot,
                    audit_snapshot=audit_snapshot,
                )
                return True
            if self._settings.image_ocr_enabled:
                if self._image_text_recognizer is None or claimed.visual_brief is None:
                    await self._finish_generated_quality_attempt(
                        claimed,
                        references=references,
                        validation_snapshot={
                            **validation_snapshot,
                            "configured": True,
                            "passed": False,
                            "issue_codes": ["image_ocr_not_configured"],
                        },
                        audit_snapshot=audit_snapshot,
                        error_code="image_ocr_not_configured",
                    )
                    return True
                expected_text = _expected_visual_text(claimed.visual_brief)
                ocr_result = await self._image_text_recognizer.recognize(
                    ImageTextRecognitionRequest(
                        request_fingerprint=claimed.request_fingerprint,
                        image_bytes=result.image_bytes,
                        expected_text=expected_text,
                        media_type=result.media_type,
                    )
                )
                if (
                    ocr_result.request_fingerprint != claimed.request_fingerprint
                    or not ocr_result.provider.strip()
                    or not ocr_result.model.strip()
                ):
                    raise ProviderIdentityMismatchError()
                text_validation = validate_exact_visual_text(
                    ocr_result.recognized_lines, expected_text
                )
                validation_snapshot = _image_validation_snapshot(
                    text_validation,
                    configured=True,
                    provider=ocr_result.provider,
                    model=ocr_result.model,
                )
                validation_snapshot.update(
                    {
                        "media_type": output_validation.media_type,
                        "width": output_validation.width,
                        "height": output_validation.height,
                        "byte_size": output_validation.byte_size,
                    }
                )
                if not text_validation.passed:
                    await self._finish_generated_quality_attempt(
                        claimed,
                        references=references,
                        validation_snapshot=validation_snapshot,
                        audit_snapshot=audit_snapshot,
                        error_code="image_text_validation_failed",
                    )
                    return True
            if self._settings.image_quality_audit_enabled:
                if self._image_quality_auditor is None or claimed.visual_brief is None:
                    await self._finish_generated_quality_attempt(
                        claimed,
                        references=references,
                        validation_snapshot=validation_snapshot,
                        audit_snapshot={
                            **audit_snapshot,
                            "configured": True,
                            "passed": False,
                            "issue_codes": ["image_quality_audit_not_configured"],
                        },
                        error_code="image_quality_audit_not_configured",
                    )
                    return True
                audit_result = await self._image_quality_auditor.audit(
                    ImageQualityAuditRequest(
                        request_fingerprint=claimed.request_fingerprint,
                        image_bytes=result.image_bytes,
                        visual_brief=claimed.visual_brief,
                        references=references,
                        media_type=result.media_type,
                    )
                )
                if (
                    audit_result.request_fingerprint != claimed.request_fingerprint
                    or not audit_result.provider.strip()
                    or not audit_result.model.strip()
                ):
                    raise ProviderIdentityMismatchError()
                audit_snapshot = _image_audit_snapshot(audit_result)
                if not audit_result.accepted:
                    if any(issue.severity == "error" for issue in audit_result.issues):
                        await self._finish_attempt(
                            claimed,
                            error_code="image_quality_audit_hard_failure",
                            retryable=False,
                            review_required=True,
                            validation_snapshot=validation_snapshot,
                            audit_snapshot=audit_snapshot,
                        )
                    else:
                        await self._finish_generated_quality_attempt(
                            claimed,
                            references=references,
                            validation_snapshot=validation_snapshot,
                            audit_snapshot=audit_snapshot,
                            error_code="image_quality_audit_failed",
                        )
                    return True
            self._ensure_lease(lease_lost)
            descriptor = await self._image_store.put_immutable(
                result.image_bytes, media_type=result.media_type
            )
            if not await self._persist_success(
                claimed,
                result,
                descriptor,
                validation_snapshot=validation_snapshot,
                audit_snapshot=audit_snapshot,
            ):
                logger.warning(
                    "material_package_image_lease_lost",
                    package_id=str(claimed.package_id),
                    image_id=str(claimed.image_id),
                )
        except asyncio.CancelledError:
            raise
        except ImageProviderRejectedError:
            if claimed.provider_rejection_retry_count == 0:
                if await self._schedule_provider_rejection_retry(claimed):
                    logger.warning(
                        "material_package_image_provider_rejected",
                        package_id=str(claimed.package_id),
                        image_id=str(claimed.image_id),
                        provider=claimed.provider,
                        model=claimed.model,
                        attempt=claimed.attempt_number,
                        repair_count=claimed.repair_count,
                        provider_rejection_retry_count=1,
                        next_action="neutralized_retry",
                    )
            else:
                await self._persist_catalog_fallback(
                    claimed,
                    references=references,
                    validation_snapshot=validation_snapshot,
                    audit_snapshot=audit_snapshot,
                    initial_error_code="image_provider_rejected",
                )
        except AppError as error:
            if isinstance(error, ImageOutputValidationError) and not validation_snapshot:
                validation_snapshot = _image_output_error_snapshot(
                    error,
                    provider=claimed.provider,
                    model=claimed.model,
                )
            await self._finish_transient_or_finish(
                claimed,
                error_code=error.code,
                retryable=error.retryable,
                references=references,
                validation_snapshot=validation_snapshot,
                audit_snapshot=audit_snapshot,
                review_required=isinstance(
                    error,
                    (
                        ImageOutputValidationError,
                        ProviderIdentityMismatchError,
                    ),
                ),
            )
        except ValueError:
            await self._finish_attempt(
                claimed,
                error_code="image_output_invalid",
                retryable=False,
                validation_snapshot=validation_snapshot,
                audit_snapshot=audit_snapshot,
                review_required=True,
            )
        except Exception:
            await self._finish_transient_or_finish(
                claimed,
                error_code="image_provider_unavailable",
                retryable=True,
                references=references,
                validation_snapshot=validation_snapshot,
                audit_snapshot=audit_snapshot,
                review_required=False,
            )
        finally:
            self._lease_events.pop(claimed.image_id, None)
            stop.set()
            await asyncio.gather(heartbeat, return_exceptions=True)
        return True

    async def _finish_transient_or_finish(
        self,
        claimed: ClaimedMaterialPackage,
        *,
        error_code: str,
        retryable: bool,
        review_required: bool,
        references: tuple[ImageReference, ...],
        validation_snapshot: dict[str, Any] | None = None,
        audit_snapshot: dict[str, Any] | None = None,
    ) -> None:
        if retryable and claimed.attempt_number >= self._settings.image_max_attempts:
            await self._persist_catalog_fallback(
                claimed,
                references=references,
                validation_snapshot=validation_snapshot or {},
                audit_snapshot=audit_snapshot or _image_audit_not_run_snapshot(),
                initial_error_code=error_code,
            )
            return
        await self._finish_attempt(
            claimed,
            error_code=error_code,
            retryable=retryable,
            review_required=review_required,
            validation_snapshot=validation_snapshot,
            audit_snapshot=audit_snapshot,
        )

    async def _read_claimed_references(
        self, claimed: ClaimedMaterialPackage
    ) -> tuple[ImageReference, ...]:
        if not claimed.references:
            return ()
        try:
            loaded = await asyncio.to_thread(
                load_visual_catalog, self._settings.image_asset_manifest
            )
            references: list[ImageReference] = []
            for reserved in claimed.references:
                asset = loaded.catalog.asset_by_id.get(reserved.asset_id)
                if asset is None or asset.filename != reserved.filename:
                    raise ConflictError("approved visual reference is no longer in the catalog")
                selected = SelectedVisualAsset(
                    asset=asset,
                    role=VisualAssetRole(reserved.role),
                    score=0,
                    reason=reserved.selection_reason,
                    fallback=reserved.fallback,
                )
                reference = await asyncio.to_thread(read_selected_reference, loaded, selected)
                if reference.sha256 != reserved.sha256:
                    raise ConflictError("approved visual reference checksum changed")
                references.append(reference)
            return tuple(references)
        except (OSError, ValueError) as error:
            if isinstance(error, ConflictError):
                raise
            raise ConflictError("approved visual references are unavailable") from error

    async def _claim(self, worker_id: str) -> ClaimedMaterialPackage | None:
        now = datetime.now(UTC)
        image_attempt_budget = (
            self._settings.image_max_attempts
            + ImageArtifactModel.repair_count
            + ImageArtifactModel.provider_rejection_retry_count
        )
        async with self._session_factory() as session:
            exhausted_images = tuple(
                (
                    await session.scalars(
                        select(ImageArtifactModel)
                        .join(
                            MaterialPackageModel,
                            MaterialPackageModel.image_artifact_id == ImageArtifactModel.id,
                        )
                        .where(
                            MaterialPackageModel.status == "queued",
                            ImageArtifactModel.provider == self._settings.image_provider_mode,
                            ImageArtifactModel.model == self._settings.image_model,
                            ImageArtifactModel.attempt_count >= image_attempt_budget,
                            or_(
                                and_(
                                    ImageArtifactModel.status == "queued",
                                    ImageArtifactModel.available_at <= now,
                                ),
                                and_(
                                    ImageArtifactModel.status == "running",
                                    or_(
                                        ImageArtifactModel.lease_expires_at.is_(None),
                                        ImageArtifactModel.lease_expires_at <= now,
                                    ),
                                ),
                            ),
                        )
                        .order_by(ImageArtifactModel.created_at)
                        .limit(100)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for exhausted_image in exhausted_images:
                exhausted_image.status = "failed"
                exhausted_image.error_code = "lease_expired"
                exhausted_image.completed_at = now
                _clear_image_lease(exhausted_image)
                exhausted_package = await session.scalar(
                    select(MaterialPackageModel).where(
                        MaterialPackageModel.image_artifact_id == exhausted_image.id
                    )
                )
                if exhausted_package is not None:
                    exhausted_package.status = "failed"
            image = await session.scalar(
                select(ImageArtifactModel)
                .join(
                    MaterialPackageModel,
                    MaterialPackageModel.image_artifact_id == ImageArtifactModel.id,
                )
                .where(
                    MaterialPackageModel.status == "queued",
                    ImageArtifactModel.provider == self._settings.image_provider_mode,
                    ImageArtifactModel.model == self._settings.image_model,
                    or_(
                        and_(
                            ImageArtifactModel.status == "queued",
                            ImageArtifactModel.available_at <= now,
                            ImageArtifactModel.attempt_count < image_attempt_budget,
                        ),
                        and_(
                            ImageArtifactModel.status == "running",
                            ImageArtifactModel.attempt_count < image_attempt_budget,
                            or_(
                                ImageArtifactModel.lease_expires_at.is_(None),
                                ImageArtifactModel.lease_expires_at <= now,
                            ),
                        ),
                    ),
                )
                .order_by(ImageArtifactModel.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if image is None:
                if exhausted_images:
                    await session.commit()
                return None
            package = await session.scalar(
                select(MaterialPackageModel).where(
                    MaterialPackageModel.image_artifact_id == image.id
                )
            )
            if package is None:
                return None
            reserved_references: tuple[ReservedVisualReference, ...] = ()
            if getattr(image, "reference_mode", "legacy_single") != "legacy_single":
                reference_rows = tuple(
                    (
                        await session.scalars(
                            select(ImageArtifactReferenceModel)
                            .where(ImageArtifactReferenceModel.image_artifact_id == image.id)
                            .order_by(ImageArtifactReferenceModel.ordinal)
                        )
                    ).all()
                )
                reserved_references = _reserved_references_from_rows(reference_rows)
            run = await session.get(CopyGenerationRunModel, image.run_id)
            draft = await session.get(CopyDraftVersionModel, image.draft_version_id)
            if (
                run is None
                or draft is None
                or run.status != "accepted"
                or run.active_draft_version_id != draft.id
                or not draft.validation_passed
                or draft.audit_accepted is not True
            ):
                image.status = "review_required"
                image.error_code = "accepted_draft_unavailable"
                _clear_image_lease(image)
                package.status = "failed"
                await session.commit()
                return ClaimedMaterialPackage(
                    package_id=package.id,
                    image_id=image.id,
                    run_id=image.run_id,
                    draft_version_id=image.draft_version_id,
                    request_fingerprint=image.request_fingerprint,
                    provider=image.provider,
                    model=image.model,
                    prompt=draft.image_prompt if draft is not None else "",
                    reference_sha256=image.reference_sha256,
                    lease_token=uuid4(),
                    attempt_number=image.attempt_count,
                    eligible=False,
                )
            try:
                claim_prompt, claim_brief_snapshot, claim_brief = _claim_prompt(
                    package=package,
                    draft=draft,
                    image=image,
                    references=reserved_references,
                )
            except (OSError, ValueError):
                image.status = "review_required"
                image.error_code = "visual_input_invalid"
                _clear_image_lease(image)
                package.status = "failed"
                await session.commit()
                return ClaimedMaterialPackage(
                    package_id=package.id,
                    image_id=image.id,
                    run_id=image.run_id,
                    draft_version_id=image.draft_version_id,
                    request_fingerprint=image.request_fingerprint,
                    provider=image.provider,
                    model=image.model,
                    prompt="",
                    reference_sha256=image.reference_sha256,
                    lease_token=uuid4(),
                    attempt_number=image.attempt_count,
                    eligible=False,
                    references=reserved_references,
                    reference_mode=getattr(image, "reference_mode", "legacy_single"),
                    visual_brief_snapshot=getattr(image, "visual_brief_snapshot", None),
                    catalog_version=(
                        package.version_snapshot.get("image", {}).get(
                            "catalog_version", "no-catalog"
                        )
                        if isinstance(package.version_snapshot.get("image", {}), dict)
                        else "no-catalog"
                    ),
                    selector_version=(
                        package.version_snapshot.get("image", {}).get(
                            "selector_version", "no-selector"
                        )
                        if isinstance(package.version_snapshot.get("image", {}), dict)
                        else "no-selector"
                    ),
                )
            lease_token = uuid4()
            image.status = "running"
            image.attempt_count += 1
            image.lease_owner = worker_id
            image.lease_token = lease_token
            image.lease_expires_at = now + timedelta(seconds=self._settings.content_lease_seconds)
            image.heartbeat_at = now
            image.error_code = None
            image.completed_at = None
            await session.commit()
            return ClaimedMaterialPackage(
                package_id=package.id,
                image_id=image.id,
                run_id=image.run_id,
                draft_version_id=image.draft_version_id,
                request_fingerprint=image.request_fingerprint,
                provider=image.provider,
                model=image.model,
                prompt=claim_prompt,
                reference_sha256=image.reference_sha256,
                lease_token=lease_token,
                attempt_number=image.attempt_count,
                references=reserved_references,
                reference_mode=getattr(image, "reference_mode", "legacy_single"),
                visual_brief_snapshot=claim_brief_snapshot,
                repair_count=getattr(image, "repair_count", 0),
                provider_rejection_retry_count=getattr(image, "provider_rejection_retry_count", 0),
                visual_brief=claim_brief,
                catalog_version=(
                    package.version_snapshot.get("image", {}).get("catalog_version", "no-catalog")
                    if isinstance(package.version_snapshot.get("image", {}), dict)
                    else "no-catalog"
                ),
                selector_version=(
                    package.version_snapshot.get("image", {}).get("selector_version", "no-selector")
                    if isinstance(package.version_snapshot.get("image", {}), dict)
                    else "no-selector"
                ),
            )

    async def _schedule_provider_rejection_retry(self, claimed: ClaimedMaterialPackage) -> bool:
        """Persist the one provider-rejection recovery transition."""

        now = datetime.now(UTC)
        async with self._session_factory() as session:
            image = await session.scalar(
                select(ImageArtifactModel)
                .where(
                    ImageArtifactModel.id == claimed.image_id,
                    ImageArtifactModel.lease_token == claimed.lease_token,
                    ImageArtifactModel.status == "running",
                    ImageArtifactModel.lease_expires_at >= now,
                )
                .with_for_update()
            )
            package = await session.get(MaterialPackageModel, claimed.package_id)
            if image is None or package is None:
                return False
            if getattr(image, "provider_rejection_retry_count", 0) >= 1:
                return False
            image.provider_rejection_retry_count = 1
            image.status = "queued"
            image.available_at = now
            image.error_code = "image_provider_rejected"
            image.completed_at = None
            _set_package_image_fallback(
                package,
                state="neutralized_retry",
                provider_rejection_retry_count=1,
                initial_error_code="image_provider_rejected",
                primary_provider=claimed.provider,
                primary_model=claimed.model,
            )
            _clear_image_lease(image)
            package.status = "queued"
            await session.commit()
            return True

    async def _persist_catalog_fallback(
        self,
        claimed: ClaimedMaterialPackage,
        *,
        references: tuple[ImageReference, ...],
        validation_snapshot: dict[str, Any],
        audit_snapshot: dict[str, Any],
        initial_error_code: str = "image_provider_rejected",
    ) -> None:
        logger.warning(
            "material_package_image_fallback_requested",
            package_id=str(claimed.package_id),
            image_id=str(claimed.image_id),
            attempt=claimed.attempt_number,
            repair_count=claimed.repair_count,
            provider_rejection_retry_count=claimed.provider_rejection_retry_count,
            error_code=initial_error_code,
            next_action="brand_catalog_fallback",
        )
        selected = _select_catalog_fallback_reference(claimed.references, references)
        if selected is None:
            await self._finish_attempt(
                claimed,
                error_code="brand_asset_fallback_unavailable",
                retryable=False,
                review_required=True,
                validation_snapshot=validation_snapshot,
                audit_snapshot=audit_snapshot,
            )
            logger.error(
                "material_package_image_fallback_failed",
                package_id=str(claimed.package_id),
                image_id=str(claimed.image_id),
                error_code="brand_asset_fallback_unavailable",
                action="review_required",
            )
            return

        reserved, reference = selected
        try:
            fallback_body = await asyncio.to_thread(
                render_catalog_fallback_image, reference.image_bytes
            )
            output_validation = validate_image_output(
                fallback_body,
                "image/png",
                max_bytes=self._settings.image_max_download_bytes,
            )
            fallback_validation = _image_validation_snapshot(
                output_validation,
                configured=True,
                provider="brand_catalog",
                model=claimed.catalog_version,
            )
            fallback_validation["stage"] = "brand_catalog_fallback"
            fallback_validation["renderer_version"] = IMAGE_CATALOG_FALLBACK_RENDERER_VERSION
            if not output_validation.passed:
                raise ValueError("brand catalog fallback failed raster validation")
            descriptor = await self._image_store.put_immutable(
                fallback_body, media_type="image/png"
            )
            fallback_audit = _image_audit_catalog_fallback_snapshot(claimed.catalog_version)
            if await self._persist_catalog_fallback_success(
                claimed,
                descriptor,
                validation_snapshot=fallback_validation,
                audit_snapshot=fallback_audit,
                asset=reserved,
                initial_error_code=initial_error_code,
            ):
                logger.info(
                    "material_package_image_fallback_ready",
                    package_id=str(claimed.package_id),
                    image_id=str(claimed.image_id),
                    fallback_state="brand_catalog",
                    asset_id=reserved.asset_id,
                    renderer_version=IMAGE_CATALOG_FALLBACK_RENDERER_VERSION,
                    width=output_validation.width,
                    height=output_validation.height,
                    byte_size=output_validation.byte_size,
                )
        except AppError:
            await self._finish_attempt(
                claimed,
                error_code="brand_asset_fallback_storage_failed",
                retryable=False,
                review_required=True,
                validation_snapshot=validation_snapshot,
                audit_snapshot=audit_snapshot,
            )
            logger.error(
                "material_package_image_fallback_failed",
                package_id=str(claimed.package_id),
                image_id=str(claimed.image_id),
                error_code="brand_asset_fallback_storage_failed",
                action="review_required",
            )
        except (OSError, ValueError):
            await self._finish_attempt(
                claimed,
                error_code="brand_asset_fallback_invalid",
                retryable=False,
                review_required=True,
                validation_snapshot=validation_snapshot,
                audit_snapshot=audit_snapshot,
            )
            logger.error(
                "material_package_image_fallback_failed",
                package_id=str(claimed.package_id),
                image_id=str(claimed.image_id),
                error_code="brand_asset_fallback_invalid",
                action="review_required",
            )
        except Exception:
            await self._finish_attempt(
                claimed,
                error_code="brand_asset_fallback_storage_failed",
                retryable=False,
                review_required=True,
                validation_snapshot=validation_snapshot,
                audit_snapshot=audit_snapshot,
            )
            logger.error(
                "material_package_image_fallback_failed",
                package_id=str(claimed.package_id),
                image_id=str(claimed.image_id),
                error_code="brand_asset_fallback_storage_failed",
                action="review_required",
            )

    async def _persist_catalog_fallback_success(
        self,
        claimed: ClaimedMaterialPackage,
        descriptor: ImageObjectDescriptor,
        *,
        validation_snapshot: dict[str, Any],
        audit_snapshot: dict[str, Any],
        asset: ReservedVisualReference,
        initial_error_code: str,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            image = await session.scalar(
                select(ImageArtifactModel)
                .where(
                    ImageArtifactModel.id == claimed.image_id,
                    ImageArtifactModel.lease_token == claimed.lease_token,
                    ImageArtifactModel.status == "running",
                    ImageArtifactModel.lease_expires_at >= now,
                )
                .with_for_update()
            )
            package = await session.get(MaterialPackageModel, claimed.package_id)
            if image is None or package is None:
                return False
            image.status = "succeeded"
            image.media_type = descriptor.media_type
            image.width = 1024
            image.height = 1024
            image.byte_size = descriptor.byte_size
            image.sha256 = descriptor.sha256
            image.bucket = descriptor.bucket
            image.object_key = descriptor.object_key
            image.validation_snapshot = validation_snapshot
            image.audit_snapshot = audit_snapshot
            image.storage_metadata = dict(_PRIVATE_STORAGE_METADATA)
            image.repair_count = claimed.repair_count
            image.provider_rejection_retry_count = claimed.provider_rejection_retry_count
            image.error_code = None
            image.completed_at = now
            _set_package_image_quality(
                package,
                validation_snapshot=validation_snapshot,
                audit_snapshot=audit_snapshot,
                repair_count=claimed.repair_count,
                provider_rejection_retry_count=claimed.provider_rejection_retry_count,
            )
            _set_package_image_fallback(
                package,
                state="brand_catalog",
                provider_rejection_retry_count=claimed.provider_rejection_retry_count,
                initial_error_code=initial_error_code,
                primary_provider=claimed.provider,
                primary_model=claimed.model,
                asset=asset,
            )
            _clear_image_lease(image)
            package.status = "awaiting_manual_use"
            await session.commit()
            return True

    async def _finish_generated_quality_attempt(
        self,
        claimed: ClaimedMaterialPackage,
        *,
        references: tuple[ImageReference, ...],
        validation_snapshot: dict[str, Any],
        audit_snapshot: dict[str, Any],
        error_code: str,
    ) -> None:
        """Avoid additional provider calls after the single neutralized recovery request."""

        if claimed.provider_rejection_retry_count > 0 or claimed.repair_count > 0:
            await self._persist_catalog_fallback(
                claimed,
                references=references,
                validation_snapshot=validation_snapshot,
                audit_snapshot=audit_snapshot,
                initial_error_code=error_code,
            )
            return
        await self._finish_quality_attempt(
            claimed,
            validation_snapshot=validation_snapshot,
            audit_snapshot=audit_snapshot,
            error_code=error_code,
        )

    async def _persist_success(
        self,
        claimed: ClaimedMaterialPackage,
        result: ImageGenerationResult,
        descriptor: ImageObjectDescriptor,
        *,
        validation_snapshot: dict[str, Any],
        audit_snapshot: dict[str, Any],
    ) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            image = await session.scalar(
                select(ImageArtifactModel)
                .where(
                    ImageArtifactModel.id == claimed.image_id,
                    ImageArtifactModel.lease_token == claimed.lease_token,
                    ImageArtifactModel.status == "running",
                    ImageArtifactModel.lease_expires_at >= now,
                )
                .with_for_update()
            )
            package = await session.get(MaterialPackageModel, claimed.package_id)
            if image is None or package is None:
                return False
            image.provider_task_id = result.provider_task_id
            image.provider_upload_id = result.provider_upload_id
            image.status = "succeeded"
            image.attempt_count = max(image.attempt_count, result.attempts)
            image.media_type = result.media_type
            image.width = result.width
            image.height = result.height
            image.byte_size = descriptor.byte_size
            image.sha256 = descriptor.sha256
            image.bucket = descriptor.bucket
            image.object_key = descriptor.object_key
            image.validation_snapshot = validation_snapshot
            image.audit_snapshot = audit_snapshot
            image.repair_count = claimed.repair_count
            image.provider_rejection_retry_count = claimed.provider_rejection_retry_count
            _set_package_image_quality(
                package,
                validation_snapshot=validation_snapshot,
                audit_snapshot=audit_snapshot,
                repair_count=claimed.repair_count,
                provider_rejection_retry_count=claimed.provider_rejection_retry_count,
            )
            image.storage_metadata = dict(_PRIVATE_STORAGE_METADATA)
            image.error_code = None
            image.completed_at = now
            _clear_image_lease(image)
            package.status = "awaiting_manual_use"
            await session.commit()
            return True

    async def _finish_quality_attempt(
        self,
        claimed: ClaimedMaterialPackage,
        *,
        validation_snapshot: dict[str, Any],
        audit_snapshot: dict[str, Any],
        error_code: str,
    ) -> None:
        """Persist a visual-quality failure and schedule only one targeted repair."""
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            image = await session.scalar(
                select(ImageArtifactModel)
                .where(
                    ImageArtifactModel.id == claimed.image_id,
                    ImageArtifactModel.lease_token == claimed.lease_token,
                    ImageArtifactModel.status == "running",
                    ImageArtifactModel.lease_expires_at >= now,
                )
                .with_for_update()
            )
            package = await session.get(MaterialPackageModel, claimed.package_id)
            if image is None or package is None:
                return
            image.validation_snapshot = validation_snapshot
            image.audit_snapshot = audit_snapshot
            image.error_code = error_code
            _set_package_image_quality(
                package,
                validation_snapshot=validation_snapshot,
                audit_snapshot=audit_snapshot,
                repair_count=image.repair_count,
                provider_rejection_retry_count=getattr(image, "provider_rejection_retry_count", 0),
            )
            _clear_image_lease(image)
            if image.repair_count < 1:
                image.repair_count += 1
                image.status = "queued"
                image.available_at = now
                image.completed_at = None
                package.status = "queued"
                next_action = "targeted_repair"
            else:
                image.status = "review_required"
                image.completed_at = now
                package.status = "failed"
                next_action = "review_required"
            await session.commit()
            logger.warning(
                "material_package_image_quality_transition",
                package_id=str(claimed.package_id),
                image_id=str(claimed.image_id),
                attempt=claimed.attempt_number,
                repair_count=image.repair_count,
                provider_rejection_retry_count=getattr(image, "provider_rejection_retry_count", 0),
                error_code=error_code,
                next_action=next_action,
            )

    async def _finish_attempt(
        self,
        claimed: ClaimedMaterialPackage,
        *,
        error_code: str,
        retryable: bool,
        review_required: bool,
        validation_snapshot: dict[str, Any] | None = None,
        audit_snapshot: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(UTC)
        retry = retryable and claimed.attempt_number < self._settings.image_max_attempts
        retry_at = (
            now + timedelta(seconds=min(30 * 2 ** (claimed.attempt_number - 1), 300))
            if retry
            else None
        )
        async with self._session_factory() as session:
            image = await session.scalar(
                select(ImageArtifactModel)
                .where(
                    ImageArtifactModel.id == claimed.image_id,
                    ImageArtifactModel.lease_token == claimed.lease_token,
                    ImageArtifactModel.status == "running",
                    ImageArtifactModel.lease_expires_at >= now,
                )
                .with_for_update()
            )
            package = await session.get(MaterialPackageModel, claimed.package_id)
            if image is None or package is None:
                return
            image.error_code = error_code
            if validation_snapshot:
                image.validation_snapshot = validation_snapshot
            if audit_snapshot:
                image.audit_snapshot = audit_snapshot
            _set_package_image_quality(
                package,
                validation_snapshot=validation_snapshot or image.validation_snapshot,
                audit_snapshot=audit_snapshot or image.audit_snapshot,
                repair_count=image.repair_count,
                provider_rejection_retry_count=getattr(image, "provider_rejection_retry_count", 0),
            )
            _clear_image_lease(image)
            if retry:
                image.status = "queued"
                image.available_at = retry_at or now
                package.status = "queued"
            else:
                image.status = "review_required" if review_required else "failed"
                image.completed_at = now
                package.status = "failed"
            await session.commit()
            logger.warning(
                "material_package_image_attempt_finished",
                package_id=str(claimed.package_id),
                image_id=str(claimed.image_id),
                attempt=claimed.attempt_number,
                error_code=error_code,
                retry_scheduled=retry,
                next_action=(
                    "retry" if retry else "review_required" if review_required else "failed"
                ),
            )

    async def _heartbeat_loop(
        self,
        claimed: ClaimedMaterialPackage,
        stop: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=self._settings.content_heartbeat_seconds
                )
            except TimeoutError:
                now = datetime.now(UTC)
                try:
                    async with self._session_factory() as session:
                        result = cast(
                            CursorResult[object],
                            await session.execute(
                                update(ImageArtifactModel)
                                .where(
                                    ImageArtifactModel.id == claimed.image_id,
                                    ImageArtifactModel.lease_token == claimed.lease_token,
                                    ImageArtifactModel.status == "running",
                                    ImageArtifactModel.lease_expires_at >= now,
                                )
                                .values(
                                    heartbeat_at=now,
                                    lease_expires_at=now
                                    + timedelta(seconds=self._settings.content_lease_seconds),
                                )
                            ),
                        )
                        if not result.rowcount:
                            await session.rollback()
                            lease_lost.set()
                            return
                        await session.commit()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.warning(
                        "material_package_heartbeat_failed",
                        image_id=str(claimed.image_id),
                        error_code="material_package_lease_lost",
                        exception_type=type(error).__name__,
                    )
                    lease_lost.set()
                    return

    @staticmethod
    def _ensure_lease(lease_lost: asyncio.Event) -> None:
        if lease_lost.is_set():
            raise ConflictError("material package image lease was lost")


def _clear_image_lease(image: ImageArtifactModel) -> None:
    image.lease_owner = None
    image.lease_token = None
    image.lease_expires_at = None
    image.heartbeat_at = None


def _expected_visual_text(brief: VisualBrief) -> tuple[str, ...]:
    return tuple(
        value
        for value in (
            brief.text_layer.title,
            brief.text_layer.learning_line,
            *brief.text_layer.keywords,
            *brief.text_layer.brand_values,
        )
        if value
    )


def _image_validation_snapshot(
    result: Any,
    *,
    configured: bool,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    return {
        "version": "image-validation-v1",
        "configured": configured,
        "passed": bool(getattr(result, "passed", False)),
        "issue_codes": list(_safe_image_issue_codes(getattr(result, "issue_codes", ()))),
        "provider": provider,
        "model": model,
        "media_type": getattr(result, "media_type", None),
        "width": getattr(result, "width", None),
        "height": getattr(result, "height", None),
        "byte_size": getattr(result, "byte_size", None),
    }


def _image_output_error_snapshot(
    error: ImageOutputValidationError,
    *,
    provider: str,
    model: str,
) -> dict[str, Any]:
    """Project one adapter validation reason without retaining provider-controlled data."""

    return {
        "version": "image-validation-v1",
        "configured": True,
        "passed": False,
        "stage": "provider_output",
        "issue_codes": [error.reason],
        "provider": provider,
        "model": model,
        "media_type": None,
        "width": None,
        "height": None,
        "byte_size": None,
    }


def _image_audit_not_run_snapshot() -> dict[str, Any]:
    return {
        "version": "image-audit-v1",
        "configured": False,
        "status": "not_configured",
        "passed": None,
        "issue_codes": [],
        "provider": None,
        "model": None,
    }


def _image_audit_catalog_fallback_snapshot(catalog_version: str) -> dict[str, Any]:
    return {
        "version": "image-audit-v1",
        "configured": False,
        "status": "not_applicable",
        "passed": None,
        "issue_codes": [],
        "provider": "brand_catalog",
        "model": catalog_version,
    }


def _image_audit_snapshot(result: Any) -> dict[str, Any]:
    issue_codes = getattr(result, "issue_codes", ())
    if not issue_codes:
        issue_codes = tuple(
            getattr(issue, "code", "audit_issue") for issue in getattr(result, "issues", ())
        )
    accepted = bool(getattr(result, "accepted", False))
    return {
        "version": "image-audit-v1",
        "configured": True,
        "status": "accepted" if accepted else "rejected",
        "passed": accepted,
        "issue_codes": list(_safe_image_issue_codes(issue_codes)),
        "provider": getattr(result, "provider", None),
        "model": getattr(result, "model", None),
    }


def _safe_image_issue_codes(values: object) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        return ()
    safe: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if 1 <= len(normalized) <= 80 and all(
            character.isalnum() or character in "._-" for character in normalized
        ):
            safe.append(normalized)
    return tuple(dict.fromkeys(safe))


def _image_issue_codes(*snapshots: object) -> tuple[str, ...]:
    values: list[str] = []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        values.extend(_safe_image_issue_codes(snapshot.get("issue_codes", [])))
    return tuple(dict.fromkeys(values)) or ("image_quality_review",)


def _select_catalog_fallback_reference(
    reserved_references: tuple[ReservedVisualReference, ...],
    references: tuple[ImageReference, ...],
) -> tuple[ReservedVisualReference, ImageReference] | None:
    references_by_asset = {reference.asset_id: reference for reference in references}
    role_order = {
        "action_reference": 0,
        "style_reference": 1,
        "identity_reference": 2,
        "legacy": 3,
    }
    candidates = [
        (reserved, references_by_asset[reserved.asset_id])
        for reserved in reserved_references
        if reserved.asset_id in references_by_asset
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            role_order.get(item[0].role, len(role_order)),
            item[0].asset_id,
        ),
    )


def _image_fallback_snapshot(
    *,
    state: str,
    provider_rejection_retry_count: int,
    initial_error_code: str | None = None,
    primary_provider: str | None = None,
    primary_model: str | None = None,
    asset: ReservedVisualReference | None = None,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "version": "image-fallback-v1",
        "state": state,
        "provider_rejection_retry_count": max(0, min(provider_rejection_retry_count, 1)),
        "initial_error_code": initial_error_code,
        "primary_provider": primary_provider,
        "primary_model": primary_model,
    }
    if asset is not None:
        snapshot["asset"] = {
            "asset_id": asset.asset_id,
            "filename": asset.filename,
            "sha256": asset.sha256,
            "role": asset.role,
            "selection_reason": asset.selection_reason,
            "fallback": asset.fallback,
        }
    return snapshot


def _set_package_image_fallback(
    package: MaterialPackageModel,
    *,
    state: str,
    provider_rejection_retry_count: int,
    initial_error_code: str | None = None,
    primary_provider: str | None = None,
    primary_model: str | None = None,
    asset: ReservedVisualReference | None = None,
) -> None:
    current = package.version_snapshot if isinstance(package.version_snapshot, dict) else {}
    image_snapshot = current.get("image", {})
    image_values = dict(image_snapshot) if isinstance(image_snapshot, dict) else {}
    image_values["fallback"] = _image_fallback_snapshot(
        state=state,
        provider_rejection_retry_count=provider_rejection_retry_count,
        initial_error_code=initial_error_code,
        primary_provider=primary_provider,
        primary_model=primary_model,
        asset=asset,
    )
    package.version_snapshot = {**current, "image": image_values}


def _set_package_image_quality(
    package: MaterialPackageModel,
    *,
    validation_snapshot: object,
    audit_snapshot: object,
    repair_count: int,
    provider_rejection_retry_count: int = 0,
) -> None:
    current = package.version_snapshot if isinstance(package.version_snapshot, dict) else {}
    image_snapshot = current.get("image", {})
    image_values = dict(image_snapshot) if isinstance(image_snapshot, dict) else {}
    image_values.update(
        {
            "validation": validation_snapshot,
            "audit": audit_snapshot,
            "repair_count": max(0, min(repair_count, 1)),
            "provider_rejection_retry_count": max(0, min(provider_rejection_retry_count, 1)),
        }
    )
    package.version_snapshot = {**current, "image": image_values}


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
) -> AcceptedMaterialInput:
    async with session_factory() as session:
        run = await session.get(CopyGenerationRunModel, run_id)
        if run is None:
            raise NotFoundError("copy generation run")
        if run.status != "accepted" or run.active_draft_version_id is None:
            raise ConflictError("copy generation run does not have an accepted draft")
        draft = await session.get(CopyDraftVersionModel, run.active_draft_version_id)
        if draft is None or not draft.validation_passed or draft.audit_accepted is not True:
            raise ConflictError("accepted draft is unavailable for image generation")

        selection = await session.get(DailyTopicSelectionModel, run.daily_topic_selection_id)
        event_version = (
            await session.get(EventClusterVersionModel, run.selected_event_version_id)
            if run.selected_event_version_id is not None
            else None
        )
        score = (
            await session.scalar(
                select(TopicScoreModel).where(
                    TopicScoreModel.run_id == selection.run_id,
                    TopicScoreModel.event_id == run.selected_event_id,
                )
            )
            if selection is not None and run.selected_event_id is not None
            else None
        )
        summary_value = event_version.summary_projection.get("summary") if event_version else None
        topic_snapshot: dict[str, Any] = {
            "topic_selection_id": str(run.daily_topic_selection_id),
            "topic_selection_run_id": str(run.topic_selection_run_id),
            "business_date": run.business_date.isoformat(),
            "timezone": run.timezone,
            "scoring_profile": run.scoring_profile,
            "decision_kind": run.decision_kind,
            "selected_event_id": str(run.selected_event_id) if run.selected_event_id else None,
            "selected_event_version_id": (
                str(run.selected_event_version_id) if run.selected_event_version_id else None
            ),
            "title": event_version.representative_title if event_version else None,
            "summary": summary_value if isinstance(summary_value, str) else None,
            "selection_revision": selection.revision if selection is not None else None,
            "config_fingerprint": selection.config_fingerprint if selection is not None else None,
            "score": _score_snapshot(score),
        }

        audit = await session.scalar(
            select(CopyAuditModel).where(CopyAuditModel.draft_version_id == draft.id)
        )
        validation = await session.scalar(
            select(CopyValidationResultModel).where(
                CopyValidationResultModel.draft_version_id == draft.id
            )
        )
        deterministic_issues = tuple(
            (
                await session.scalars(
                    select(CopyIssueModel)
                    .where(
                        CopyIssueModel.draft_version_id == draft.id,
                        CopyIssueModel.stage == "deterministic",
                    )
                    .order_by(CopyIssueModel.ordinal)
                )
            ).all()
        )
        audit_issues = (
            tuple(
                (
                    await session.scalars(
                        select(CopyIssueModel)
                        .where(
                            CopyIssueModel.draft_version_id == draft.id,
                            CopyIssueModel.stage == "audit",
                        )
                        .order_by(CopyIssueModel.ordinal)
                    )
                ).all()
            )
            if audit is not None
            else ()
        )
        validation_snapshot = {
            "passed": (
                bool(validation.passed) if validation is not None else draft.validation_passed
            ),
            "rule_version": (
                validation.rule_version if validation is not None else draft.rule_version
            ),
            "result_fingerprint": (
                validation.result_fingerprint if validation is not None else None
            ),
            "issues": [_issue_snapshot(issue) for issue in deterministic_issues],
        }
        audit_snapshot: dict[str, Any] = {
            "accepted": bool(draft.audit_accepted),
            "audit_id": str(audit.id) if audit else None,
            "prompt_version": audit.prompt_version if audit else None,
            "schema_version": audit.schema_version if audit else None,
            "rule_version": audit.rule_version if audit else draft.rule_version,
            "result_fingerprint": audit.result_fingerprint if audit else None,
            "issues": [_issue_snapshot(issue) for issue in audit_issues],
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
        claim_ids = [claim.id for claim in claims]
        evidence_rows = (
            tuple(
                (
                    await session.scalars(
                        select(CopyClaimEvidenceBindingModel)
                        .where(CopyClaimEvidenceBindingModel.claim_id.in_(claim_ids))
                        .order_by(
                            CopyClaimEvidenceBindingModel.claim_id,
                            CopyClaimEvidenceBindingModel.id,
                        )
                    )
                ).all()
            )
            if claim_ids
            else ()
        )
        brand_rows = (
            tuple(
                (
                    await session.execute(
                        select(
                            CopyClaimBrandBindingModel,
                            BrandChunkModel,
                            BrandDocumentVersionModel,
                            BrandDocumentModel,
                        )
                        .join(
                            BrandChunkModel,
                            BrandChunkModel.id == CopyClaimBrandBindingModel.brand_chunk_id,
                        )
                        .join(
                            BrandDocumentVersionModel,
                            BrandDocumentVersionModel.id == BrandChunkModel.version_id,
                        )
                        .join(
                            BrandDocumentModel,
                            BrandDocumentModel.id == BrandDocumentVersionModel.document_id,
                        )
                        .where(CopyClaimBrandBindingModel.claim_id.in_(claim_ids))
                        .order_by(
                            CopyClaimBrandBindingModel.claim_id,
                            CopyClaimBrandBindingModel.id,
                        )
                    )
                ).tuples()
            )
            if claim_ids
            else ()
        )
        evidence_by_claim: dict[UUID, list[CopyClaimEvidenceBindingModel]] = {}
        for item in evidence_rows:
            evidence_by_claim.setdefault(item.claim_id, []).append(item)
        brand_by_claim: dict[UUID, list[tuple[Any, Any, Any, Any]]] = {}
        for row in brand_rows:
            brand_by_claim.setdefault(row[0].claim_id, []).append(row)

        claim_snapshots: list[dict[str, Any]] = []
        source_snapshot: list[dict[str, Any]] = []
        brand_snapshot: list[dict[str, Any]] = []
        for claim in claims:
            evidence = evidence_by_claim.get(claim.id, [])
            brand = brand_by_claim.get(claim.id, [])
            claim_snapshots.append(
                {
                    "claim_id": claim.claim_key,
                    "text": claim.text,
                    "kind": claim.kind,
                    "evidence_ids": [str(item.evidence_binding_id) for item in evidence],
                    "brand_chunk_ids": [str(item.brand_chunk_id) for item, *_ in brand],
                }
            )
            for item in evidence:
                source_snapshot.append(
                    {
                        "claim_id": claim.claim_key,
                        "claim_text": claim.text,
                        "evidence_binding_id": str(item.evidence_binding_id),
                        "candidate_id": str(item.candidate_id),
                        "passage_id": str(item.passage_id),
                        "occurrence_id": str(item.occurrence_id),
                        "snapshot_id": str(item.snapshot_id),
                        "source_url": item.source_url,
                        "source_tier": item.source_tier,
                        "published_at": item.published_at.isoformat()
                        if item.published_at
                        else None,
                        "exact_quote": item.exact_quote,
                    }
                )
            for binding, chunk, version, document in brand:
                brand_snapshot.append(
                    {
                        "claim_id": claim.claim_key,
                        "claim_text": claim.text,
                        "brand_chunk_id": str(binding.brand_chunk_id),
                        "document_id": str(document.id),
                        "version_id": str(version.id),
                        "document_title": document.title,
                        "document_kind": document.document_kind,
                        "audience": document.audience,
                        "text": chunk.text,
                        "tone_tags": list(version.tone_tags),
                        "safety_tags": list(version.safety_tags),
                        "visual_tags": list(version.visual_tags),
                    }
                )
        copy_snapshot = {
            "draft_version_id": str(draft.id),
            "version": draft.version,
            "repair_of_version_id": (
                str(draft.repair_of_version_id) if draft.repair_of_version_id else None
            ),
            "copywriting": draft.copywriting,
            "parent_takeaway": draft.parent_takeaway,
            "interaction": draft.interaction,
            "source_note": draft.source_note,
            "image_prompt": draft.image_prompt,
            "claims": claim_snapshots,
            "provider": draft.provider,
            "model": draft.model,
            "request_fingerprint": draft.request_fingerprint,
            "prompt_version": draft.prompt_version,
            "schema_version": draft.schema_version,
            "rule_version": draft.rule_version,
        }
        version_snapshot = {
            "package_schema_version": "material-package-v2",
            "copy": {
                "prompt_version": draft.prompt_version,
                "schema_version": draft.schema_version,
                "rule_version": draft.rule_version,
                "provider": draft.provider,
                "model": draft.model,
            },
            "validation": {"rule_version": validation_snapshot["rule_version"]},
            "audit": {
                "prompt_version": audit_snapshot["prompt_version"],
                "schema_version": audit_snapshot["schema_version"],
                "rule_version": audit_snapshot["rule_version"],
            },
        }
        visual_brief = build_visual_brief(
            AcceptedVisualContext(
                topic_title=(
                    event_version.representative_title
                    if event_version is not None and event_version.representative_title
                    else "科学探索"
                ),
                topic_summary=(summary_value if isinstance(summary_value, str) else None),
                copywriting=draft.copywriting,
                image_prompt=draft.image_prompt,
            )
        )
        return AcceptedMaterialInput(
            run=run,
            draft=draft,
            prompt=draft.image_prompt,
            topic_snapshot=topic_snapshot,
            copy_snapshot=copy_snapshot,
            source_snapshot=source_snapshot,
            brand_snapshot=brand_snapshot,
            validation_snapshot=validation_snapshot,
            audit_snapshot=audit_snapshot,
            version_snapshot=version_snapshot,
            visual_brief=visual_brief,
        )


def _issue_snapshot(issue: CopyIssueModel) -> dict[str, Any]:
    return {
        "code": issue.code,
        "severity": issue.severity,
        "field": issue.field_name,
        "claim_id": issue.claim_key,
        "message": issue.safe_message,
    }


def _score_snapshot(score: TopicScoreModel | None) -> dict[str, Any] | None:
    if score is None:
        return None
    return {
        "total": score.total,
        "threshold": score.threshold,
        "passes_threshold": score.passes_threshold,
        "eligible": score.eligible,
        "rank": score.rank,
        "veto_codes": list(score.veto_codes),
        "explanation": score.explanation,
    }
