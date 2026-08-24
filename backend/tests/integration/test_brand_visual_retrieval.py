from __future__ import annotations

import asyncio
import hashlib
import struct
import zlib

import pytest
from app.domain.visual_retrieval import (
    VISUAL_EMBEDDING_INPUT_POLICY_V1,
    VisualAssetDerivation,
    VisualEmbeddingIdentity,
    VisualEmbeddingRequest,
    VisualEmbeddingResult,
)
from app.infrastructure.db.models import (
    BrandVisualAssetEmbeddingModel,
    BrandVisualIndexJobModel,
)
from app.infrastructure.db.visual_retrieval import PostgresVisualIndexRepository
from sqlalchemy import delete, update

from .conftest import IntegrationContext


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _vector(index: int) -> tuple[float, ...]:
    values = [0.0] * 2048
    values[index] = 1.0
    return tuple(values)


def _png(seed: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    pixel = bytes((0, seed, seed, seed, 255))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixel))
        + chunk(b"IEND", b"")
    )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_visual_index_is_idempotent_complete_and_identity_scoped(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresVisualIndexRepository(integration_context.session_factory)
    catalog_version = f"test-catalog-{_digest('catalog')[:16]}"
    bodies = (_png(1), _png(2))
    first = VisualAssetDerivation(
        asset_id=_digest("visual-first"),
        asset_checksum=hashlib.sha256(bodies[0]).hexdigest(),
        embedding_input_sha256=hashlib.sha256(bodies[0]).hexdigest(),
        catalog_version=catalog_version,
    )
    second = VisualAssetDerivation(
        asset_id=_digest("visual-second"),
        asset_checksum=hashlib.sha256(bodies[1]).hexdigest(),
        embedding_input_sha256=hashlib.sha256(bodies[1]).hexdigest(),
        catalog_version=catalog_version,
    )
    try:
        for ordinal, (derivation, body) in enumerate(zip((first, second), bodies, strict=True)):
            claim = await repository.claim_asset(
                derivation=derivation,
                worker_id="integration-worker",
                lease_seconds=60,
            )
            assert claim is not None
            request = VisualEmbeddingRequest.for_image(body)
            embedding = VisualEmbeddingResult(
                identity=derivation.identity,
                input_sha256=request.input_sha256,
                request_fingerprint=request.request_fingerprint,
                vector=_vector(ordinal),
                image_tokens=1,
            )
            assert await repository.persist_embedding(claim=claim, embedding=embedding)
            assert (
                await repository.claim_asset(
                    derivation=derivation,
                    worker_id="integration-worker",
                    lease_seconds=60,
                )
                is None
            )

        query_request = VisualEmbeddingRequest.for_text("synthetic visual query")
        query = VisualEmbeddingResult(
            identity=first.identity,
            input_sha256=query_request.input_sha256,
            request_fingerprint=query_request.request_fingerprint,
            vector=_vector(0),
            input_tokens=1,
        )
        ranking = await repository.search_complete_catalog(
            catalog_version=catalog_version,
            catalog_assets=(
                (first.asset_id, first.asset_checksum),
                (second.asset_id, second.asset_checksum),
            ),
            identity=first.identity,
            query=query,
        )
        assert ranking.complete is True
        assert ranking.indexed_asset_count == 2
        assert ranking.scores[0].asset_id == first.asset_id
        assert ranking.scores[0].similarity == pytest.approx(1.0)

        legacy_identity = VisualEmbeddingIdentity(
            input_policy_version=VISUAL_EMBEDDING_INPUT_POLICY_V1
        )
        legacy_derivation = VisualAssetDerivation(
            asset_id=first.asset_id,
            asset_checksum=first.asset_checksum,
            embedding_input_sha256=first.asset_checksum,
            catalog_version=catalog_version,
            identity=legacy_identity,
        )
        legacy_claim = await repository.claim_asset(
            derivation=legacy_derivation,
            worker_id="legacy-integration-worker",
            lease_seconds=60,
        )
        assert legacy_claim is not None
        legacy_image_request = VisualEmbeddingRequest.for_image(bodies[0], identity=legacy_identity)
        assert await repository.persist_embedding(
            claim=legacy_claim,
            embedding=VisualEmbeddingResult(
                identity=legacy_identity,
                input_sha256=legacy_image_request.input_sha256,
                request_fingerprint=legacy_image_request.request_fingerprint,
                vector=_vector(1),
                image_tokens=1,
            ),
        )
        legacy_query_request = VisualEmbeddingRequest.for_text(
            "synthetic legacy query", identity=legacy_identity
        )
        legacy_ranking = await repository.search_complete_catalog(
            catalog_version=catalog_version,
            catalog_assets=((first.asset_id, first.asset_checksum),),
            identity=legacy_identity,
            query=VisualEmbeddingResult(
                identity=legacy_identity,
                input_sha256=legacy_query_request.input_sha256,
                request_fingerprint=legacy_query_request.request_fingerprint,
                vector=_vector(1),
                input_tokens=1,
            ),
        )
        assert legacy_ranking.complete is True
        assert legacy_ranking.scores[0].similarity == pytest.approx(1.0)

        v2_after_legacy = await repository.search_complete_catalog(
            catalog_version=catalog_version,
            catalog_assets=(
                (first.asset_id, first.asset_checksum),
                (second.asset_id, second.asset_checksum),
            ),
            identity=first.identity,
            query=query,
        )
        assert v2_after_legacy.complete is True
        assert v2_after_legacy.scores[0].asset_id == first.asset_id

        incomplete = await repository.search_complete_catalog(
            catalog_version=catalog_version,
            catalog_assets=((first.asset_id, _digest("changed-checksum")),),
            identity=first.identity,
            query=query,
        )
        assert incomplete.complete is False
        assert incomplete.scores == ()

        async with integration_context.session_factory() as session:
            await session.execute(
                update(BrandVisualAssetEmbeddingModel)
                .where(BrandVisualAssetEmbeddingModel.asset_id == first.asset_id)
                .values(model="other-visual-space")
            )
            await session.commit()
        wrong_space = await repository.search_complete_catalog(
            catalog_version=catalog_version,
            catalog_assets=((first.asset_id, first.asset_checksum),),
            identity=first.identity,
            query=query,
        )
        assert wrong_space.complete is False
        assert wrong_space.scores == ()
    finally:
        async with integration_context.session_factory() as session:
            await session.execute(
                delete(BrandVisualIndexJobModel).where(
                    BrandVisualIndexJobModel.catalog_version == catalog_version
                )
            )
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_existing_v1_rows_cannot_complete_a_v2_catalog(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresVisualIndexRepository(integration_context.session_factory)
    catalog_version = f"test-catalog-{_digest('v1-v2-isolation')[:16]}"
    body = _png(7)
    checksum = hashlib.sha256(body).hexdigest()
    asset_id = _digest("legacy-only-visual")
    v1_identity = VisualEmbeddingIdentity(input_policy_version=VISUAL_EMBEDDING_INPUT_POLICY_V1)
    v1_derivation = VisualAssetDerivation(
        asset_id=asset_id,
        asset_checksum=checksum,
        embedding_input_sha256=checksum,
        catalog_version=catalog_version,
        identity=v1_identity,
    )
    try:
        claim = await repository.claim_asset(
            derivation=v1_derivation,
            worker_id="legacy-isolation-worker",
            lease_seconds=60,
        )
        assert claim is not None
        v1_request = VisualEmbeddingRequest.for_image(body, identity=v1_identity)
        assert await repository.persist_embedding(
            claim=claim,
            embedding=VisualEmbeddingResult(
                identity=v1_identity,
                input_sha256=v1_request.input_sha256,
                request_fingerprint=v1_request.request_fingerprint,
                vector=_vector(0),
                image_tokens=1,
            ),
        )

        v2_identity = VisualEmbeddingIdentity()
        v2_request = VisualEmbeddingRequest.for_text("v2 isolation query", identity=v2_identity)
        ranking = await repository.search_complete_catalog(
            catalog_version=catalog_version,
            catalog_assets=((asset_id, checksum),),
            identity=v2_identity,
            query=VisualEmbeddingResult(
                identity=v2_identity,
                input_sha256=v2_request.input_sha256,
                request_fingerprint=v2_request.request_fingerprint,
                vector=_vector(0),
                input_tokens=1,
            ),
        )

        assert ranking.complete is False
        assert ranking.indexed_asset_count == 0
        assert ranking.scores == ()
    finally:
        async with integration_context.session_factory() as session:
            await session.execute(
                delete(BrandVisualIndexJobModel).where(
                    BrandVisualIndexJobModel.catalog_version == catalog_version
                )
            )
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_visual_index_first_claim_is_concurrency_safe(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresVisualIndexRepository(integration_context.session_factory)
    catalog_version = f"test-catalog-{_digest('claim-race')[:16]}"
    body = _png(3)
    derivation = VisualAssetDerivation(
        asset_id=_digest("visual-claim-race"),
        asset_checksum=hashlib.sha256(body).hexdigest(),
        embedding_input_sha256=hashlib.sha256(body).hexdigest(),
        catalog_version=catalog_version,
    )
    try:
        claims = await asyncio.gather(
            repository.claim_asset(
                derivation=derivation,
                worker_id="integration-worker-a",
                lease_seconds=60,
            ),
            repository.claim_asset(
                derivation=derivation,
                worker_id="integration-worker-b",
                lease_seconds=60,
            ),
        )
        owned = [claim for claim in claims if claim is not None]
        assert len(owned) == 1
        assert await repository.fail_asset(claim=owned[0], error_code="provider_unavailable")

        changed_input = VisualAssetDerivation(
            asset_id=derivation.asset_id,
            asset_checksum=derivation.asset_checksum,
            embedding_input_sha256=_digest("different-normalized-input"),
            catalog_version=catalog_version,
        )
        assert changed_input.key != derivation.key
        changed_claim = await repository.claim_asset(
            derivation=changed_input,
            worker_id="integration-worker-c",
            lease_seconds=60,
        )
        assert changed_claim is not None
        assert await repository.fail_asset(
            claim=changed_claim, error_code="input_normalization_failed"
        )
    finally:
        async with integration_context.session_factory() as session:
            await session.execute(
                delete(BrandVisualIndexJobModel).where(
                    BrandVisualIndexJobModel.catalog_version == catalog_version
                )
            )
            await session.commit()
