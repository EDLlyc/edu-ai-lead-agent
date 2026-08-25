from __future__ import annotations

import asyncio
import hashlib
import io
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from app.application.ports.image_generation import ImageGenerationRequest, ImageGenerationResult
from app.application.ports.ip_assets import IpAssetQuery
from app.application.services.ip_assets import IpAssetWorkerService
from app.core.errors import ConflictError
from app.domain.ip_assets import (
    IpAssetCharacter,
    IpAssetLeaderboardPeriod,
    IpAssetMembershipSource,
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
from app.infrastructure.db.models import (
    IpAssetEmbeddingJobModel,
    IpAssetFavoriteModel,
    IpAssetGenerationJobModel,
    IpAssetModel,
    IpAssetProfileMembershipModel,
    IpAssetProfileModel,
)
from app.infrastructure.storage.minio_ip_asset_store import MinioIpAssetStore
from PIL import Image
from sqlalchemy import delete, func, select, update

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
            profile_id=None,
            references=((first.id, first.blob_sha256),),
            provider="fake",
            model="gpt-image-2",
        )
        replay, replay_created = await repository.enqueue_generation(
            idempotency_key=idempotency_key,
            request_fingerprint="f" * 64,
            prompt="为科学课堂生成一张小赛开心讲解的方形插画",
            metadata=metadata,
            ratio="1:1",
            profile_id=None,
            references=((first.id, first.blob_sha256),),
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
    class UnusedEmbeddings:
        async def embed_visual(self, _request: VisualEmbeddingRequest) -> VisualEmbeddingResult:
            raise AssertionError("generation completion must not call the embedding provider")

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
        profile_id=None,
        references=(),
        provider="fake",
        model="gpt-image-2",
    )
    assert created is True
    service = IpAssetWorkerService(
        repository=repository,
        store=MinioIpAssetStore(integration_context.settings),
        embeddings=UnusedEmbeddings(),
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
        async with integration_context.session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(IpAssetEmbeddingJobModel)
                    .where(IpAssetEmbeddingJobModel.asset_id == output_id)
                )
                == 1
            )
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
                profile_id=None,
                references=(),
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
async def test_profile_bootstrap_and_upload_membership_are_concurrency_safe(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresIpAssetRepository(integration_context.session_factory)
    store = MinioIpAssetStore(integration_context.settings)
    token_digest = hashlib.sha256(uuid4().bytes).hexdigest()
    profiles = await asyncio.gather(
        *(
            repository.bootstrap_profile(
                token_digest=token_digest,
                display_name="integration-concurrent",
                department="integration-studio",
            )
            for _ in range(8)
        )
    )
    profile = profiles[0][0]
    assert sum(created for _record, created in profiles) == 1
    assert {record.id for record, _created in profiles} == {profile.id}

    color_seed = uuid4().int
    upload = validate_ip_asset_upload(
        filename="concurrent-profile-upload.png",
        declared_media_type="image/png",
        body=_png(
            (
                color_seed & 255,
                (color_seed >> 8) & 255,
                (color_seed >> 16) & 255,
            )
        ),
    )
    descriptor = await store.put_immutable(upload)
    assets = await asyncio.gather(
        *(
            repository.create_asset(
                upload=upload,
                metadata=IpAssetMetadata(
                    character=IpAssetCharacter.XIAO_SAI,
                    asset_type=IpAssetType.MEME_STICKER,
                    department=profile.department,
                    contributor=profile.display_name,
                ),
                descriptor=descriptor,
                source_kind=IpAssetSource.UPLOADED,
                semantic_enabled=False,
                membership_profile_id=profile.id,
                membership_source=IpAssetMembershipSource.UPLOADED,
            )
            for _ in range(8)
        )
    )
    asset = assets[0][0]
    try:
        assert sum(created for _record, created in assets) == 1
        assert {record.id for record, _created in assets} == {asset.id}
        personal = await repository.list_personal_assets(
            profile_id=profile.id,
            source="uploaded",
            cursor_created_at=None,
            cursor_id=None,
            limit=10,
        )
        assert [item.asset.id for item in personal.items] == [asset.id]
    finally:
        async with integration_context.session_factory() as session:
            await session.execute(delete(IpAssetModel).where(IpAssetModel.id == asset.id))
            await session.execute(
                delete(IpAssetProfileModel).where(IpAssetProfileModel.id == profile.id)
            )
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_profile_library_keeps_generated_output_private_until_explicit_share(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresIpAssetRepository(integration_context.session_factory)
    store = MinioIpAssetStore(integration_context.settings)
    profile, profile_created = await repository.bootstrap_profile(
        token_digest=hashlib.sha256(uuid4().bytes).hexdigest(),
        display_name="integration-creator",
        department="integration-studio",
    )
    assert profile_created is True
    other_profile, other_profile_created = await repository.bootstrap_profile(
        token_digest=hashlib.sha256(uuid4().bytes).hexdigest(),
        display_name="integration-other",
        department="integration-studio",
    )
    assert other_profile_created is True
    reference_ids = []
    output_id = None
    job = None
    other_job = None
    try:
        references = []
        for index, color in enumerate(((19, 111, 102), (189, 102, 72))):
            upload = validate_ip_asset_upload(
                filename=f"reference-{index}.png",
                declared_media_type="image/png",
                body=_png(color),
            )
            descriptor = await store.put_immutable(upload)
            reference, created = await repository.create_asset(
                upload=upload,
                metadata=IpAssetMetadata(
                    character=IpAssetCharacter.XIAO_SAI,
                    asset_type=IpAssetType.IDENTITY_REFERENCE,
                    department="integration-studio",
                ),
                descriptor=descriptor,
                source_kind=IpAssetSource.UPLOADED,
                semantic_enabled=False,
                membership_profile_id=profile.id,
                membership_source=IpAssetMembershipSource.UPLOADED,
            )
            assert created is True
            reference_ids.append(reference.id)
            references.append((reference.id, reference.blob_sha256))

        uploaded = await repository.list_personal_assets(
            profile_id=profile.id,
            source="uploaded",
            cursor_created_at=None,
            cursor_id=None,
            limit=10,
        )
        assert {item.asset.id for item in uploaded.items} == set(reference_ids)
        assert all(
            await asyncio.gather(
                *(
                    repository.favorite_asset(
                        profile_id=profile.id,
                        asset_ref=uploaded.items[0].asset.asset_ref,
                        favorite=True,
                    )
                    for _ in range(8)
                )
            )
        )
        favorites = await repository.list_personal_assets(
            profile_id=profile.id,
            source="favorite",
            cursor_created_at=None,
            cursor_id=None,
            limit=10,
        )
        assert [item.asset.asset_ref for item in favorites.items] == [
            uploaded.items[0].asset.asset_ref
        ]

        idempotency_key = f"personal-generation-{uuid4()}"
        job, created = await repository.enqueue_generation(
            idempotency_key=idempotency_key,
            request_fingerprint=hashlib.sha256(uuid4().bytes).hexdigest(),
            prompt="使用两张参考图生成小赛科学课堂方形插画",
            metadata=IpAssetMetadata(
                character=IpAssetCharacter.XIAO_SAI,
                asset_type=IpAssetType.SCENE_ILLUSTRATION,
                department=profile.department,
                contributor=profile.display_name,
            ),
            ratio="1:1",
            profile_id=profile.id,
            references=tuple(references),
            provider="fake",
            model="gpt-image-2",
        )
        assert created is True
        assert [reference.asset_id for reference in job.references] == reference_ids
        assert [reference.ordinal for reference in job.references] == [0, 1]
        claim = await repository.claim_generation_job(
            worker_id="integration-personal-generation",
            lease_seconds=60,
            max_attempts=3,
        )
        assert claim is not None and claim.job.id == job.id
        generated_upload = validate_ip_asset_upload(
            filename="personal-output.png",
            declared_media_type="image/png",
            body=_png((74, 140, 211)),
        )
        generated = await repository.complete_generation_asset(
            claim=claim,
            upload=generated_upload,
            metadata=IpAssetMetadata(
                character=IpAssetCharacter.XIAO_SAI,
                asset_type=IpAssetType.SCENE_ILLUSTRATION,
                department=profile.department,
                contributor=profile.display_name,
            ),
            descriptor=await store.put_immutable(generated_upload),
            semantic_enabled=False,
        )
        assert generated is not None
        output_id = generated.id
        assert generated.shared_at is None
        assert await repository.get_shared_by_ref(generated.asset_ref) is None
        assert (
            await repository.get_accessible_by_ref(generated.asset_ref, profile_id=profile.id)
        ) is not None
        assert (
            await repository.get_accessible_by_ref(generated.asset_ref, profile_id=other_profile.id)
        ) is None
        assert not await repository.favorite_asset(
            profile_id=other_profile.id,
            asset_ref=generated.asset_ref,
            favorite=True,
        )
        async with integration_context.session_factory() as session:
            session.add(
                IpAssetFavoriteModel(id=uuid4(), profile_id=other_profile.id, asset_id=generated.id)
            )
            await session.commit()
        orphan_favorites = await repository.list_personal_assets(
            profile_id=other_profile.id,
            source="favorite",
            cursor_created_at=None,
            cursor_id=None,
            limit=10,
        )
        assert generated.id not in {item.asset.id for item in orphan_favorites.items}
        with pytest.raises(ConflictError, match="generated personal asset"):
            await repository.share_generated_asset(
                profile_id=other_profile.id, asset_ref=generated.asset_ref
            )
        other_job, other_created = await repository.enqueue_generation(
            idempotency_key=idempotency_key,
            request_fingerprint=hashlib.sha256(uuid4().bytes).hexdigest(),
            prompt="另一个名片使用同一幂等键也应创建独立任务",
            metadata=IpAssetMetadata(
                character=IpAssetCharacter.XIAO_SAI,
                asset_type=IpAssetType.SCENE_ILLUSTRATION,
                department=other_profile.department,
                contributor=other_profile.display_name,
            ),
            ratio="1:1",
            profile_id=other_profile.id,
            references=tuple(references),
            provider="fake",
            model="gpt-image-2",
        )
        assert other_created is True
        assert other_job.id != job.id

        personal_generated = await repository.list_personal_assets(
            profile_id=profile.id,
            source="generated",
            cursor_created_at=None,
            cursor_id=None,
            limit=10,
        )
        assert [item.asset.id for item in personal_generated.items] == [generated.id]
        shared = await repository.share_generated_asset(
            profile_id=profile.id, asset_ref=generated.asset_ref
        )
        assert shared.shared_at is not None
        assert await repository.get_shared_by_ref(generated.asset_ref) is not None

        await asyncio.gather(
            repository.increment_downloads(
                asset_ids=(generated.id, generated.id), business_date=date(2026, 8, 24)
            ),
            *(
                repository.increment_downloads(
                    asset_ids=(generated.id,), business_date=date(2026, 8, 24)
                )
                for _ in range(7)
            ),
            repository.increment_downloads(
                asset_ids=(generated.id,), business_date=date(2026, 8, 25)
            ),
        )
        ranking = await repository.leaderboard(
            period=IpAssetLeaderboardPeriod.THIRTY_DAYS,
            start_date=date(2026, 7, 26),
            limit=20,
        )
        ranked = {item.asset.id: item.download_count for item in ranking.items}
        assert ranked[generated.id] == 8
        all_time = await repository.leaderboard(
            period=IpAssetLeaderboardPeriod.ALL,
            start_date=None,
            limit=20,
        )
        all_time_ranked = {item.asset.id: item.download_count for item in all_time.items}
        assert all_time_ranked[generated.id] == 9
    finally:
        async with integration_context.session_factory() as session:
            job_ids = [item.id for item in (job, other_job) if item is not None]
            if job_ids:
                await session.execute(
                    delete(IpAssetProfileMembershipModel).where(
                        IpAssetProfileMembershipModel.generation_job_id.in_(job_ids)
                    )
                )
                await session.execute(
                    delete(IpAssetGenerationJobModel).where(
                        IpAssetGenerationJobModel.id.in_(job_ids)
                    )
                )
                await session.commit()
            if output_id is not None:
                await session.execute(delete(IpAssetModel).where(IpAssetModel.id == output_id))
                await session.commit()
            if reference_ids:
                await session.execute(
                    delete(IpAssetModel).where(IpAssetModel.id.in_(reference_ids))
                )
                await session.commit()
            await session.execute(
                delete(IpAssetProfileModel).where(
                    IpAssetProfileModel.id.in_((profile.id, other_profile.id))
                )
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
        profile_id=None,
        references=(),
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
        profile_id=None,
        references=(),
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
