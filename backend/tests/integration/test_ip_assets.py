from __future__ import annotations

import asyncio
import hashlib
import io
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.application.ports.image_generation import ImageGenerationRequest, ImageGenerationResult
from app.application.ports.ip_assets import IpAssetQuery
from app.application.services.ip_assets import IpAssetWorkerService
from app.domain.ip_assets import (
    IpAssetCharacter,
    IpAssetMetadata,
    IpAssetSource,
    IpAssetType,
    validate_ip_asset_upload,
)
from app.domain.visual_retrieval import (
    VisualEmbeddingIdentity,
    VisualEmbeddingRequest,
    VisualEmbeddingResult,
)
from app.infrastructure.ai.image_generation import DeterministicFakeImageGenerator
from app.infrastructure.db.ip_assets import PostgresIpAssetRepository
from app.infrastructure.db.models import IpAssetGenerationJobModel, IpAssetModel
from app.infrastructure.storage.minio_ip_asset_store import MinioIpAssetStore
from PIL import Image
from sqlalchemy import delete, update

from .conftest import IntegrationContext


def _png(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (96, 64), color).save(output, format="PNG")
    return output.getvalue()


def _vector(index: int) -> tuple[float, ...]:
    values = [0.0] * 2048
    values[index] = 1.0
    return tuple(values)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_dynamic_ip_asset_dedupe_gallery_minio_vector_and_generation_jobs(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresIpAssetRepository(integration_context.session_factory)
    store = MinioIpAssetStore(integration_context.settings)
    first_upload = validate_ip_asset_upload(
        filename="xiao-sai-happy.png",
        declared_media_type="image/png",
        body=_png((244, 196, 48)),
    )
    second_upload = validate_ip_asset_upload(
        filename="sai-xiansheng-blue.png",
        declared_media_type="image/png",
        body=_png((45, 225, 194)),
    )
    metadata = IpAssetMetadata(
        character=IpAssetCharacter.XIAO_SAI,
        asset_type=IpAssetType.MEME_STICKER,
        department="integration-department",
        emotion="开心",
        style="3D",
        tags=("science", "social"),
    )
    created_ids = []
    try:
        first_descriptor = await store.put_immutable(first_upload)
        first, created = await repository.create_asset(
            upload=first_upload,
            metadata=metadata,
            descriptor=first_descriptor,
            source_kind=IpAssetSource.UPLOADED,
            semantic_enabled=True,
        )
        created_ids.append(first.id)
        assert created is True
        assert await store.get_verified(first_descriptor) == first_upload.body

        duplicate, duplicate_created = await repository.create_asset(
            upload=first_upload,
            metadata=metadata,
            descriptor=first_descriptor,
            source_kind=IpAssetSource.UPLOADED,
            semantic_enabled=True,
        )
        assert duplicate_created is False
        assert duplicate.asset_ref == first.asset_ref

        second_descriptor = await store.put_immutable(second_upload)
        second, second_created = await repository.create_asset(
            upload=second_upload,
            metadata=IpAssetMetadata(
                character=IpAssetCharacter.SAI_XIANSHENG,
                asset_type=IpAssetType.IDENTITY_REFERENCE,
                department="integration-department",
                tags=("identity",),
            ),
            descriptor=second_descriptor,
            source_kind=IpAssetSource.UPLOADED,
            semantic_enabled=True,
        )
        created_ids.append(second.id)
        assert second_created is True

        page = await repository.list_assets(
            IpAssetQuery(
                character=IpAssetCharacter.XIAO_SAI,
                department="integration-department",
                tag="science",
                limit=10,
            )
        )
        assert [item.asset_ref for item in page.items] == [first.asset_ref]
        style_page = await repository.list_assets(
            IpAssetQuery(query="3D", department="integration-department", limit=10)
        )
        assert [item.asset_ref for item in style_page.items] == [first.asset_ref]

        identity = VisualEmbeddingIdentity()
        for index in range(2):
            claim = await repository.claim_embedding_job(
                worker_id=f"integration-ip-asset-{index}", lease_seconds=60
            )
            assert claim is not None
            request = VisualEmbeddingRequest.for_image(
                first_upload.body if claim.asset.id == first.id else second_upload.body,
                identity=identity,
            )
            result = VisualEmbeddingResult(
                identity=identity,
                input_sha256=request.input_sha256,
                request_fingerprint=request.request_fingerprint,
                vector=_vector(0 if claim.asset.id == first.id else 1),
                image_tokens=1,
            )
            assert await repository.complete_embedding(
                claim=claim, embedding=result, identity=identity
            )
            assert claim.asset.id in {first.id, second.id}

        query_request = VisualEmbeddingRequest.for_text("小赛开心表情包", identity=identity)
        hits = await repository.search_vectors(
            query=IpAssetQuery(department="integration-department", limit=10),
            embedding=VisualEmbeddingResult(
                identity=identity,
                input_sha256=query_request.input_sha256,
                request_fingerprint=query_request.request_fingerprint,
                vector=_vector(0),
                input_tokens=1,
            ),
            identity=identity,
        )
        assert [hit.record.asset_ref for hit in hits[:2]] == [first.asset_ref, second.asset_ref]
        assert hits[0].similarity == pytest.approx(1.0)

        idempotency_key = f"integration-generation-{uuid4()}"
        generation, generation_created = await repository.enqueue_generation(
            idempotency_key=idempotency_key,
            request_fingerprint="f" * 64,
            prompt="为科学课堂生成一张小赛开心讲解的方形插画",
            metadata=metadata,
            ratio="1:1",
            reference_asset_id=first.id,
            provider="fake",
            model="gpt-image-2",
        )
        replay, replay_created = await repository.enqueue_generation(
            idempotency_key=idempotency_key,
            request_fingerprint="f" * 64,
            prompt="为科学课堂生成一张小赛开心讲解的方形插画",
            metadata=metadata,
            ratio="1:1",
            reference_asset_id=first.id,
            provider="fake",
            model="gpt-image-2",
        )
        assert generation_created is True
        assert replay_created is False
        assert replay.job_ref == generation.job_ref
        claim = await repository.claim_generation_job(
            worker_id="integration-generation-worker", lease_seconds=60, max_attempts=3
        )
        assert claim is not None
        assert await repository.complete_generation(claim=claim, output_asset_id=second.id)
        complete = await repository.get_generation(generation.job_ref)
        assert complete is not None
        assert complete.status == "succeeded"
        assert complete.output_asset_id == second.id
    finally:
        async with integration_context.session_factory() as session:
            await session.execute(
                delete(IpAssetGenerationJobModel).where(
                    IpAssetGenerationJobModel.reference_asset_id.in_(created_ids)
                )
            )
            await session.execute(delete(IpAssetModel).where(IpAssetModel.id.in_(created_ids)))
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_enabling_semantics_backfills_previously_unavailable_asset(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresIpAssetRepository(integration_context.session_factory)
    store = MinioIpAssetStore(integration_context.settings)
    random_value = uuid4().int
    upload = validate_ip_asset_upload(
        filename="previously-uploaded.png",
        declared_media_type="image/png",
        body=_png(
            (
                random_value & 255,
                (random_value >> 8) & 255,
                (random_value >> 16) & 255,
            )
        ),
    )
    descriptor = await store.put_immutable(upload)
    asset, created = await repository.create_asset(
        upload=upload,
        metadata=IpAssetMetadata(
            character=IpAssetCharacter.XIAO_SAI,
            asset_type=IpAssetType.FULL_BODY_ACTION,
            department="integration-embedding-backfill",
        ),
        descriptor=descriptor,
        source_kind=IpAssetSource.UPLOADED,
        semantic_enabled=False,
    )
    assert created is True
    assert asset.semantic_status.value == "unavailable"
    try:
        counts = await asyncio.gather(
            repository.enqueue_unavailable_embeddings(limit=500),
            repository.enqueue_unavailable_embeddings(limit=500),
        )
        assert sorted(counts) == [0, 1]
        assert await repository.enqueue_unavailable_embeddings(limit=500) == 0

        queued = await repository.get_by_ref(asset.asset_ref)
        assert queued is not None
        assert queued.semantic_status.value == "queued"
        claim = await repository.claim_embedding_job(
            worker_id="integration-embedding-backfill", lease_seconds=60
        )
        assert claim is not None
        assert claim.asset.id == asset.id
    finally:
        async with integration_context.session_factory() as session:
            await session.execute(delete(IpAssetModel).where(IpAssetModel.id == asset.id))
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_fake_generation_worker_ingests_exactly_one_shared_library_asset(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresIpAssetRepository(integration_context.session_factory)
    idempotency_key = f"integration-worker-generation-{uuid4()}"
    job, created = await repository.enqueue_generation(
        idempotency_key=idempotency_key,
        request_fingerprint="e" * 64,
        prompt="为科学课堂生成一张小赛开心讲解知识的方形插画",
        metadata=IpAssetMetadata(
            character=IpAssetCharacter.XIAO_SAI,
            asset_type=IpAssetType.SCENE_ILLUSTRATION,
            department="integration-generation",
        ),
        ratio="1:1",
        reference_asset_id=None,
        provider="fake",
        model="gpt-image-2",
    )
    assert created is True
    service = IpAssetWorkerService(
        repository=repository,
        store=MinioIpAssetStore(integration_context.settings),
        embeddings=None,
        identity=VisualEmbeddingIdentity(),
        image_generator=DeterministicFakeImageGenerator(model="gpt-image-2"),
    )
    output_id = None
    try:
        assert await service.process_one_generation(
            worker_id="integration-fake-generation",
            lease_seconds=60,
            max_attempts=3,
        )
        completed = await repository.get_generation(job.job_ref)
        assert completed is not None
        assert completed.status == "succeeded"
        assert completed.output_asset_id is not None
        output_id = completed.output_asset_id
        output = await repository.get_by_id(output_id)
        assert output is not None
        assert output.source_kind is IpAssetSource.GENERATED
        assert output.department == "integration-generation"
        assert (
            await service.process_one_generation(
                worker_id="integration-fake-generation",
                lease_seconds=60,
                max_attempts=3,
            )
            is False
        )
    finally:
        async with integration_context.session_factory() as session:
            await session.execute(
                delete(IpAssetGenerationJobModel).where(IpAssetGenerationJobModel.id == job.id)
            )
            if output_id is not None:
                await session.execute(delete(IpAssetModel).where(IpAssetModel.id == output_id))
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_generation_enqueue_is_atomic_across_concurrent_replays(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresIpAssetRepository(integration_context.session_factory)
    fingerprint = hashlib.sha256(uuid4().bytes).hexdigest()
    metadata = IpAssetMetadata(
        character=IpAssetCharacter.XIAO_SAI,
        asset_type=IpAssetType.SCENE_ILLUSTRATION,
        department="integration-concurrent-generation",
    )

    results = await asyncio.gather(
        *(
            repository.enqueue_generation(
                idempotency_key=f"concurrent-generation-{uuid4()}",
                request_fingerprint=fingerprint,
                prompt="为科学课堂生成一张小赛开心讲解知识的方形插画",
                metadata=metadata,
                ratio="1:1",
                reference_asset_id=None,
                provider="fake",
                model="gpt-image-2",
            )
            for _index in range(4)
        )
    )

    job_ids = {job.id for job, _created in results}
    assert len(job_ids) == 1
    assert sum(1 for _job, created in results if created) == 1
    async with integration_context.session_factory() as session:
        await session.execute(
            delete(IpAssetGenerationJobModel).where(IpAssetGenerationJobModel.id.in_(job_ids))
        )
        await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_expired_generation_claim_cannot_publish_a_gallery_asset(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresIpAssetRepository(integration_context.session_factory)
    random_value = uuid4().int
    upload = validate_ip_asset_upload(
        filename="stale-generated.png",
        declared_media_type="image/png",
        body=_png(
            (
                random_value & 255,
                (random_value >> 8) & 255,
                (random_value >> 16) & 255,
            )
        ),
    )
    descriptor = await MinioIpAssetStore(integration_context.settings).put_immutable(upload)
    metadata = IpAssetMetadata(
        character=IpAssetCharacter.XIAO_SAI,
        asset_type=IpAssetType.SCENE_ILLUSTRATION,
        department="integration-stale-generation",
    )
    job, _created = await repository.enqueue_generation(
        idempotency_key=f"stale-generation-{uuid4()}",
        request_fingerprint=hashlib.sha256(uuid4().bytes).hexdigest(),
        prompt="为科学课堂生成一张小赛开心讲解知识的方形插画",
        metadata=metadata,
        ratio="1:1",
        reference_asset_id=None,
        provider="fake",
        model="gpt-image-2",
    )
    claim = await repository.claim_generation_job(
        worker_id="integration-stale-worker", lease_seconds=60, max_attempts=3
    )
    assert claim is not None
    try:
        async with integration_context.session_factory() as session:
            await session.execute(
                update(IpAssetGenerationJobModel)
                .where(IpAssetGenerationJobModel.id == job.id)
                .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await session.commit()

        result = await repository.complete_generation_asset(
            claim=claim,
            upload=upload,
            metadata=metadata,
            descriptor=descriptor,
            semantic_enabled=False,
        )

        assert result is None
        assert await repository.get_by_sha256(upload.sha256) is None
    finally:
        async with integration_context.session_factory() as session:
            await session.execute(
                delete(IpAssetGenerationJobModel).where(IpAssetGenerationJobModel.id == job.id)
            )
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_generation_worker_rejects_mismatched_provider_identity_without_asset(
    integration_context: IntegrationContext,
) -> None:
    class MismatchedGenerator:
        async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
            body = _png((13, 37, 91))
            return ImageGenerationResult(
                provider="unexpected-provider",
                model="gpt-image-2",
                request_fingerprint=request.request_fingerprint,
                provider_task_id=None,
                provider_upload_id=None,
                image_bytes=body,
                media_type="image/png",
                width=96,
                height=64,
                attempts=1,
            )

    repository = PostgresIpAssetRepository(integration_context.session_factory)
    job, _created = await repository.enqueue_generation(
        idempotency_key=f"identity-mismatch-{uuid4()}",
        request_fingerprint=hashlib.sha256(uuid4().bytes).hexdigest(),
        prompt="为科学课堂生成一张小赛开心讲解知识的方形插画",
        metadata=IpAssetMetadata(
            character=IpAssetCharacter.XIAO_SAI,
            asset_type=IpAssetType.SCENE_ILLUSTRATION,
        ),
        ratio="1:1",
        reference_asset_id=None,
        provider="fake",
        model="gpt-image-2",
    )
    service = IpAssetWorkerService(
        repository=repository,
        store=MinioIpAssetStore(integration_context.settings),
        embeddings=None,
        identity=VisualEmbeddingIdentity(),
        image_generator=MismatchedGenerator(),
    )
    try:
        assert await service.process_one_generation(
            worker_id="integration-identity-mismatch",
            lease_seconds=60,
            max_attempts=3,
        )
        completed = await repository.get_generation(job.job_ref)
        assert completed is not None
        assert completed.status == "failed"
        assert completed.error_code == "provider_rejected"
        assert completed.output_asset_id is None
    finally:
        async with integration_context.session_factory() as session:
            await session.execute(
                delete(IpAssetGenerationJobModel).where(IpAssetGenerationJobModel.id == job.id)
            )
            await session.commit()
