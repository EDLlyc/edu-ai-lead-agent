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
from app.domain.image_generation import image_checksum, image_request_fingerprint
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


async def enqueue_material_package(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    reference_asset: str | None = None,
    image_prompt_version: str = "image-prompt-v1",
    image_pipeline_version: str = "image-pipeline-v1",
    image_provider: str = "fake",
    image_model: str = "gpt-image-2",
) -> MaterialPackageResult:
    accepted = await _load_accepted_input(session_factory, run_id)
    reference_body = await _read_reference_asset(reference_asset)
    reference_sha256 = image_checksum(reference_body) if reference_body is not None else None
    fingerprint = image_request_fingerprint(
        run_id=accepted.run.id,
        draft_version_id=accepted.draft.id,
        prompt=accepted.prompt,
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
                status="queued",
                available_at=datetime.now(UTC),
                attempt_count=0,
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
                    },
                },
                review_status="pending",
            )
            session.add_all((image, package))
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
    ) -> None:
        self._session_factory = session_factory
        self._image_generator = image_generator
        self._image_store = image_store
        self._settings = settings
        self._reference_asset = reference_asset
        self._lease_events: dict[UUID, asyncio.Event] = {}

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
        try:
            self._ensure_lease(lease_lost)
            reference_body = await _read_reference_asset(self._reference_asset)
            if (claimed.reference_sha256 is None and reference_body is not None) or (
                claimed.reference_sha256 is not None
                and (
                    reference_body is None
                    or image_checksum(reference_body) != claimed.reference_sha256
                )
            ):
                raise ConflictError("approved image reference changed after reservation")
            self._ensure_lease(lease_lost)
            result = await self._image_generator.generate(
                ImageGenerationRequest(
                    run_id=claimed.run_id,
                    draft_version_id=claimed.draft_version_id,
                    prompt=claimed.prompt,
                    request_fingerprint=claimed.request_fingerprint,
                    reference_image=reference_body,
                    reference_filename="reference.png",
                )
            )
            if (
                result.request_fingerprint != claimed.request_fingerprint
                or result.provider != claimed.provider
                or result.model != claimed.model
            ):
                raise ProviderIdentityMismatchError()
            if (
                result.width != 1024
                or result.height != 1024
                or result.media_type not in {"image/png", "image/jpeg", "image/webp"}
                or not result.image_bytes
            ):
                raise ImageOutputValidationError()
            self._ensure_lease(lease_lost)
            descriptor = await self._image_store.put_immutable(
                result.image_bytes, media_type=result.media_type
            )
            if not await self._persist_success(claimed, result, descriptor):
                logger.warning(
                    "material_package_image_lease_lost",
                    package_id=str(claimed.package_id),
                    image_id=str(claimed.image_id),
                )
        except asyncio.CancelledError:
            raise
        except AppError as error:
            await self._finish_attempt(
                claimed,
                error_code=error.code,
                retryable=error.retryable,
                review_required=isinstance(
                    error,
                    (
                        ImageOutputValidationError,
                        ImageProviderRejectedError,
                        ProviderIdentityMismatchError,
                    ),
                ),
            )
        except ValueError:
            await self._finish_attempt(
                claimed,
                error_code="image_output_invalid",
                retryable=False,
                review_required=True,
            )
        except Exception:
            await self._finish_attempt(
                claimed,
                error_code="image_provider_unavailable",
                retryable=True,
                review_required=False,
            )
        finally:
            self._lease_events.pop(claimed.image_id, None)
            stop.set()
            await asyncio.gather(heartbeat, return_exceptions=True)
        return True

    async def _claim(self, worker_id: str) -> ClaimedMaterialPackage | None:
        now = datetime.now(UTC)
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
                            ImageArtifactModel.attempt_count >= self._settings.image_max_attempts,
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
                            ImageArtifactModel.attempt_count < self._settings.image_max_attempts,
                        ),
                        and_(
                            ImageArtifactModel.status == "running",
                            ImageArtifactModel.attempt_count < self._settings.image_max_attempts,
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
                prompt=draft.image_prompt,
                reference_sha256=image.reference_sha256,
                lease_token=lease_token,
                attempt_number=image.attempt_count,
            )

    async def _persist_success(
        self,
        claimed: ClaimedMaterialPackage,
        result: ImageGenerationResult,
        descriptor: ImageObjectDescriptor,
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
            image.storage_metadata = dict(_PRIVATE_STORAGE_METADATA)
            image.error_code = None
            image.completed_at = now
            _clear_image_lease(image)
            package.status = "awaiting_manual_use"
            await session.commit()
            return True

    async def _finish_attempt(
        self,
        claimed: ClaimedMaterialPackage,
        *,
        error_code: str,
        retryable: bool,
        review_required: bool,
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
