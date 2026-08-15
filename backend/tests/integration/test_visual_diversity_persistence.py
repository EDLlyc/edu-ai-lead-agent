from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from app.application.ports.image_generation import ImageGenerationRequest, ImageGenerationResult
from app.application.ports.image_validation import (
    ImageTextRecognitionRequest,
    ImageTextRecognitionResult,
)
from app.application.services.material_package import (
    MaterialPackageExecutor,
    enqueue_material_package,
)
from app.core.config import Settings
from app.domain.visual_diversity import ControlledVisualPlan
from app.infrastructure.ai.image_generation import _solid_png
from app.infrastructure.db.models import (
    CopyGenerationRunModel,
    ImageArtifactModel,
    ImageArtifactReferenceModel,
    ImageSimilarityAttemptModel,
    ImageVisualPlanReservationModel,
    MaterialPackageModel,
    WeComDeliveryJobModel,
)
from app.infrastructure.storage.minio_image_store import ImageObjectDescriptor
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from .conftest import IntegrationContext
from .test_wecom_slot_delivery_concurrency import _seed_slot_delivery_lane


def _write_visual_catalog(root: Path) -> Path:
    asset_root = root / "05-visual-assets"
    asset_root.mkdir(parents=True)
    entries: list[dict[str, object]] = []
    definitions = (
        ("xiaosai-identity.png", "identity_reference", ["xiao-sai"], 100),
        ("sai-identity.png", "identity_reference", ["sai-xiansheng"], 95),
        ("science-action.png", "action_reference", [], 80),
        ("science-style.png", "style_reference", [], 70),
    )
    for filename, role, characters, priority in definitions:
        body = _solid_png(filename, "visual-diversity-integration")
        (asset_root / filename).write_bytes(body)
        digest = hashlib.sha256(body).hexdigest()
        entries.append(
            {
                "asset_id": digest,
                "sha256": digest,
                "checksum": digest,
                "relative_path": f"05-visual-assets/{filename}",
                "category": "visual-asset",
                "filename": filename,
                "byte_size": len(body),
                "media_type": "image/png",
                "width": 1024,
                "height": 1024,
                "has_alpha": False,
                "characters": characters,
                "roles": [role],
                "topics": [
                    "science",
                    "robotics",
                    "ai",
                    "astronomy",
                    "reading",
                    "experiment",
                ],
                "poses": ["observation", "discovery"],
                "scene_tags": ["science_lab", "future_classroom"],
                "variant_group": role,
                "priority": priority,
                "approved": True,
            }
        )
    manifest = root / "visual-assets.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "brand-visual-assets-v2",
                "catalog_version": "visual-diversity-integration-v1",
                "private": True,
                "text_rag_eligible": False,
                "asset_count": len(entries),
                "assets": entries,
            }
        ),
        encoding="utf-8",
    )
    return manifest


class _RepeatingGenerator:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests: list[ImageGenerationRequest] = []

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        self.requests.append(request)
        return ImageGenerationResult(
            provider="fake",
            model="gpt-image-2",
            request_fingerprint=request.request_fingerprint,
            provider_task_id=f"fake-task-{len(self.requests)}",
            provider_upload_id=None,
            image_bytes=self.body,
            media_type="image/png",
            width=1024,
            height=1024,
            attempts=1,
        )


class _RecordingStore:
    def __init__(self) -> None:
        self.calls = 0

    async def put_immutable(
        self, body: bytes, *, media_type: str = "image/png"
    ) -> ImageObjectDescriptor:
        self.calls += 1
        digest = hashlib.sha256(body).hexdigest()
        return ImageObjectDescriptor(
            bucket="integration-private",
            object_key=f"generated-images/{digest}.png",
            media_type=media_type,
            byte_size=len(body),
            sha256=digest,
        )


class _ExactExpectedTextRecognizer:
    async def recognize(self, request: ImageTextRecognitionRequest) -> ImageTextRecognitionResult:
        return ImageTextRecognitionResult(
            recognized_lines=request.expected_text,
            provider="fake-ocr",
            model="ocr-v1",
            request_fingerprint=request.request_fingerprint,
        )


async def _remove_seeded_materials(
    context: IntegrationContext,
    *,
    business_date: date,
) -> tuple[UUID, UUID]:
    async with context.session_factory() as session:
        run_ids = tuple(
            (
                await session.scalars(
                    select(CopyGenerationRunModel.id)
                    .where(CopyGenerationRunModel.business_date == business_date)
                    .order_by(CopyGenerationRunModel.id)
                    .limit(2)
                )
            ).all()
        )
        packages = tuple(
            (
                await session.scalars(
                    select(MaterialPackageModel).where(MaterialPackageModel.run_id.in_(run_ids))
                )
            ).all()
        )
        package_ids = tuple(package.id for package in packages)
        image_ids = tuple(package.image_artifact_id for package in packages)
        await session.execute(
            delete(WeComDeliveryJobModel).where(
                WeComDeliveryJobModel.material_package_id.in_(package_ids)
            )
        )
        await session.execute(
            delete(MaterialPackageModel).where(MaterialPackageModel.id.in_(package_ids))
        )
        await session.execute(
            delete(ImageArtifactModel).where(ImageArtifactModel.id.in_(image_ids))
        )
        await session.commit()
    assert len(run_ids) == 2
    return run_ids[0], run_ids[1]


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_plan_reservation_replay_and_warning_delivery_contract(
    integration_context: IntegrationContext,
    tmp_path: Path,
) -> None:
    target_at = datetime(2097, 8, 15, 1, 0, tzinfo=UTC)
    _window_id, _job_ids, business_date, _profile = await _seed_slot_delivery_lane(
        integration_context,
        target_at=target_at,
    )
    first_run_id, second_run_id = await _remove_seeded_materials(
        integration_context,
        business_date=business_date,
    )
    manifest = _write_visual_catalog(tmp_path / "brand-materials")
    enqueue_options = {
        "session_factory": integration_context.session_factory,
        "reference_asset": None,
        "image_provider": "fake",
        "image_model": "gpt-image-2",
        "image_asset_manifest": str(manifest),
        "image_selector_enabled": True,
        "image_max_reference_images": 3,
        "image_reference_budget_bytes": 6 * 1024 * 1024,
        "image_diversity_enabled": True,
    }

    first, second, replay = await asyncio.gather(
        enqueue_material_package(run_id=first_run_id, **enqueue_options),
        enqueue_material_package(run_id=second_run_id, **enqueue_options),
        enqueue_material_package(run_id=first_run_id, **enqueue_options),
    )

    assert first.image.id == replay.image.id
    assert first.package.id == replay.package.id
    assert first.image.id != second.image.id
    async with integration_context.session_factory() as session:
        reservations = tuple(
            (
                await session.scalars(
                    select(ImageVisualPlanReservationModel)
                    .where(
                        ImageVisualPlanReservationModel.image_artifact_id.in_(
                            (first.image.id, second.image.id)
                        )
                    )
                    .order_by(
                        ImageVisualPlanReservationModel.image_artifact_id,
                        ImageVisualPlanReservationModel.attempt_ordinal,
                    )
                )
            ).all()
        )
        references = tuple(
            (
                await session.scalars(
                    select(ImageArtifactReferenceModel).where(
                        ImageArtifactReferenceModel.image_artifact_id.in_(
                            (first.image.id, second.image.id)
                        )
                    )
                )
            ).all()
        )
    assert len(reservations) == 4
    assert len({row.plan_fingerprint for row in reservations}) == 4
    assert {row.attempt_ordinal for row in reservations} == {1, 2}
    reservation_identity = {
        (row.id, row.image_artifact_id, row.attempt_ordinal) for row in reservations
    }
    assert all(
        (row.plan_reservation_id, row.image_artifact_id, row.attempt_ordinal)
        in reservation_identity
        for row in references
    )
    async with integration_context.session_factory() as session:
        first_reference = await session.scalar(
            select(ImageArtifactReferenceModel).where(
                ImageArtifactReferenceModel.image_artifact_id == first.image.id,
                ImageArtifactReferenceModel.attempt_ordinal == 1,
            )
        )
        foreign_plan = await session.scalar(
            select(ImageVisualPlanReservationModel).where(
                ImageVisualPlanReservationModel.image_artifact_id == second.image.id,
                ImageVisualPlanReservationModel.attempt_ordinal == 1,
            )
        )
        assert first_reference is not None and foreign_plan is not None
        first_reference.plan_reservation_id = foreign_plan.id
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    repeated_body = _solid_png("repeated-output", "visual-diversity")
    repeated_sha = hashlib.sha256(repeated_body).hexdigest()
    now = datetime.now(UTC)
    async with integration_context.session_factory() as session:
        historical = await session.get(ImageArtifactModel, second.image.id)
        historical_package = await session.get(MaterialPackageModel, second.package.id)
        assert historical is not None and historical_package is not None
        historical.status = "succeeded"
        historical.media_type = "image/png"
        historical.width = 1024
        historical.height = 1024
        historical.byte_size = len(repeated_body)
        historical.sha256 = repeated_sha
        historical.bucket = "integration-private"
        historical.object_key = f"generated-images/{repeated_sha}.png"
        historical.completed_at = now
        historical_package.status = "awaiting_manual_use"
        await session.commit()

    settings = Settings(
        _env_file=None,
        image_enabled=True,
        image_provider_mode="fake",
        image_diversity_enabled=True,
        image_ocr_enabled=True,
        image_asset_manifest=str(manifest),
    )
    generator = _RepeatingGenerator(repeated_body)
    store = _RecordingStore()
    executor = MaterialPackageExecutor(
        session_factory=integration_context.session_factory,
        image_generator=generator,
        image_store=store,  # type: ignore[arg-type]
        settings=settings,
        reference_asset=None,
        image_text_recognizer=_ExactExpectedTextRecognizer(),
    )

    assert await executor.execute_next("visual-diversity-worker") is True
    async with integration_context.session_factory() as session:
        after_first = await session.get(ImageArtifactModel, first.image.id)
        first_attempts = tuple(
            (
                await session.scalars(
                    select(ImageSimilarityAttemptModel).where(
                        ImageSimilarityAttemptModel.image_artifact_id == first.image.id
                    )
                )
            ).all()
        )
    assert after_first is not None
    assert after_first.status == "queued"
    assert after_first.active_plan_ordinal == 2
    assert after_first.diversity_retry_count == 1
    assert [(item.attempt_ordinal, item.decision) for item in first_attempts] == [(1, "regenerate")]

    assert await executor.execute_next("visual-diversity-worker") is True
    assert await executor.execute_next("visual-diversity-worker") is False
    async with integration_context.session_factory() as session:
        final_image = await session.get(ImageArtifactModel, first.image.id)
        final_package = await session.get(MaterialPackageModel, first.package.id)
        attempts = tuple(
            (
                await session.scalars(
                    select(ImageSimilarityAttemptModel)
                    .where(ImageSimilarityAttemptModel.image_artifact_id == first.image.id)
                    .order_by(ImageSimilarityAttemptModel.attempt_ordinal)
                )
            ).all()
        )
    assert final_image is not None and final_package is not None
    assert final_image.status == "succeeded"
    assert final_package.status == "awaiting_manual_use"
    assert final_image.final_plan_ordinal == 2
    assert final_image.diversity_warning == "near_duplicate_after_retry"
    assert [(item.attempt_ordinal, item.decision) for item in attempts] == [
        (1, "regenerate"),
        (2, "accepted_with_warning"),
    ]
    assert len(generator.requests) == 2
    assert generator.requests[0].provider_request_fingerprint is None
    assert generator.requests[1].provider_request_fingerprint is not None
    assert store.calls == 1
    assert ControlledVisualPlan.from_metadata(reservations[0].plan_snapshot).fingerprint
