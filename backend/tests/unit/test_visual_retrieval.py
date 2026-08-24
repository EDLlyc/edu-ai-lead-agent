from __future__ import annotations

import hashlib
import struct
import zlib
from io import BytesIO
from uuid import uuid4

import pytest
from app.application.ports.visual_retrieval import VisualIndexClaim
from app.application.services.visual_retrieval import (
    VisualCatalogIndexService,
    VisualRetrievalService,
)
from app.domain.visual_assets import (
    VisualAsset,
    VisualAssetCatalog,
    VisualAssetKind,
    VisualAssetRole,
)
from app.domain.visual_retrieval import (
    VisualAssetDerivation,
    VisualEmbeddingError,
    VisualEmbeddingIdentity,
    VisualEmbeddingRequest,
    VisualEmbeddingResult,
    VisualIndexUnavailableError,
    VisualRetrievalUnavailableReason,
    VisualSemanticRanking,
    VisualSemanticScore,
    normalize_visual_embedding_image,
)
from PIL import Image, PngImagePlugin


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\xff"))
        + chunk(b"IEND", b"")
    )


def _vector() -> tuple[float, ...]:
    return (1.0, *([0.0] * 2047))


class _Embedding:
    def __init__(self) -> None:
        self.requests: list[VisualEmbeddingRequest] = []

    async def embed_visual(self, request: VisualEmbeddingRequest) -> VisualEmbeddingResult:
        self.requests.append(request)
        return VisualEmbeddingResult(
            identity=request.identity,
            input_sha256=request.input_sha256,
            request_fingerprint=request.request_fingerprint,
            vector=_vector(),
            image_tokens=1,
        )


class _InvalidEmbedding:
    async def embed_visual(self, request: VisualEmbeddingRequest) -> VisualEmbeddingResult:
        raise VisualEmbeddingError(VisualRetrievalUnavailableReason.INVALID_PROVIDER_OUTPUT)


class _Repository:
    def __init__(self) -> None:
        self.persisted = False
        self.failure_code: str | None = None
        self.last_derivation: VisualAssetDerivation | None = None

    async def claim_asset(
        self,
        *,
        derivation: VisualAssetDerivation,
        worker_id: str,
        lease_seconds: int,
    ) -> VisualIndexClaim | None:
        self.last_derivation = derivation
        return VisualIndexClaim(
            job_id=uuid4(),
            lease_token=uuid4(),
            derivation=derivation,
            attempt_number=1,
        )

    async def persist_embedding(
        self, *, claim: VisualIndexClaim, embedding: VisualEmbeddingResult
    ) -> bool:
        self.persisted = True
        return True

    async def fail_asset(self, *, claim: VisualIndexClaim, error_code: str) -> bool:
        self.failure_code = error_code
        return True

    async def search_complete_catalog(
        self,
        *,
        catalog_version: str,
        catalog_assets: tuple[tuple[str, str], ...],
        identity: VisualEmbeddingIdentity,
        query: VisualEmbeddingResult,
    ) -> VisualSemanticRanking:
        raise AssertionError("index test must not search")


class _BrokenSearchRepository(_Repository):
    async def search_complete_catalog(
        self,
        *,
        catalog_version: str,
        catalog_assets: tuple[tuple[str, str], ...],
        identity: VisualEmbeddingIdentity,
        query: VisualEmbeddingResult,
    ) -> VisualSemanticRanking:
        raise RuntimeError("synthetic database detail")


class _ReadySearchRepository(_Repository):
    async def search_complete_catalog(
        self,
        *,
        catalog_version: str,
        catalog_assets: tuple[tuple[str, str], ...],
        identity: VisualEmbeddingIdentity,
        query: VisualEmbeddingResult,
    ) -> VisualSemanticRanking:
        return VisualSemanticRanking(
            catalog_version=catalog_version,
            identity=identity,
            query_fingerprint=query.request_fingerprint,
            scores=tuple(
                VisualSemanticScore(asset_id=asset_id, similarity=0.5)
                for asset_id, _checksum in catalog_assets
            ),
            indexed_asset_count=len(catalog_assets),
            catalog_asset_count=len(catalog_assets),
            complete=True,
        )


def test_visual_embedding_identity_is_frozen() -> None:
    with pytest.raises(ValueError, match="not supported"):
        VisualEmbeddingIdentity(model="different-model")


@pytest.mark.asyncio
async def test_visual_search_preserves_typed_provider_failure() -> None:
    checksum = hashlib.sha256(b"approved-asset").hexdigest()
    catalog = VisualAssetCatalog(
        schema_version="brand-visual-assets-v2",
        catalog_version="brand-visual-catalog-v1",
        assets=(
            VisualAsset(
                asset_id=checksum,
                relative_path="approved.png",
                filename="approved.png",
                category="fixture",
                byte_size=100,
                media_type="image/png",
                width=10,
                height=10,
                has_alpha=True,
                asset_kind=VisualAssetKind.ACTION,
                roles=(VisualAssetRole.ACTION_REFERENCE,),
                approved=True,
            ),
        ),
    )
    service = VisualRetrievalService(embeddings=_InvalidEmbedding(), repository=_Repository())

    with pytest.raises(VisualIndexUnavailableError) as captured:
        await service.search_text(text="science", catalog=catalog)

    assert captured.value.reason is VisualRetrievalUnavailableReason.INVALID_PROVIDER_OUTPUT


@pytest.mark.asyncio
async def test_visual_search_maps_repository_failure_to_typed_incomplete_index() -> None:
    checksum = hashlib.sha256(b"approved-asset").hexdigest()
    catalog = VisualAssetCatalog(
        schema_version="brand-visual-assets-v2",
        catalog_version="brand-visual-catalog-v1",
        assets=(
            VisualAsset(
                asset_id=checksum,
                relative_path="approved.png",
                filename="approved.png",
                category="fixture",
                byte_size=100,
                media_type="image/png",
                width=10,
                height=10,
                has_alpha=True,
                asset_kind=VisualAssetKind.ACTION,
                roles=(VisualAssetRole.ACTION_REFERENCE,),
                approved=True,
            ),
        ),
    )
    service = VisualRetrievalService(embeddings=_Embedding(), repository=_BrokenSearchRepository())

    with pytest.raises(VisualIndexUnavailableError) as captured:
        await service.search_text(text="science", catalog=catalog)

    assert captured.value.reason is VisualRetrievalUnavailableReason.INDEX_INCOMPLETE
    assert "synthetic database detail" not in str(captured.value)


@pytest.mark.asyncio
async def test_visual_index_revalidates_after_provider_before_persistence() -> None:
    body = _png()
    checksum = hashlib.sha256(body).hexdigest()
    embeddings = _Embedding()
    repository = _Repository()
    service = VisualCatalogIndexService(embeddings=embeddings, repository=repository)
    verification_calls = 0

    async def verify_current() -> bool:
        nonlocal verification_calls
        verification_calls += 1
        return False

    result = await service.index_asset(
        catalog_version="brand-visual-catalog-v1",
        asset_id=checksum,
        checksum=checksum,
        body=body,
        worker_id="unit-worker",
        verify_current=verify_current,
    )

    assert result == "failed"
    assert len(embeddings.requests) == 1
    assert verification_calls == 1
    assert repository.persisted is False
    assert repository.failure_code == "catalog_changed"


@pytest.mark.asyncio
async def test_visual_index_rejects_checksum_mismatch_before_claim_or_provider() -> None:
    body = _png()
    embeddings = _Embedding()
    repository = _Repository()
    service = VisualCatalogIndexService(embeddings=embeddings, repository=repository)

    async def verify_current() -> bool:
        return True

    with pytest.raises(ValueError, match="checksum"):
        await service.index_asset(
            catalog_version="brand-visual-catalog-v1",
            asset_id=hashlib.sha256(b"asset").hexdigest(),
            checksum=hashlib.sha256(b"different").hexdigest(),
            body=body,
            worker_id="unit-worker",
            verify_current=verify_current,
        )

    assert embeddings.requests == []


@pytest.mark.asyncio
async def test_index_and_image_query_share_the_same_v2_normalized_input() -> None:
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("large-private-metadata", "x" * (8 * 1024 * 1024))
    buffer = BytesIO()
    Image.new("RGB", (1, 1), (1, 2, 3)).save(buffer, format="PNG", pnginfo=metadata)
    source = buffer.getvalue()
    checksum = hashlib.sha256(source).hexdigest()
    normalized = normalize_visual_embedding_image(source)
    asset = VisualAsset(
        asset_id=checksum,
        relative_path="approved.png",
        filename="approved.png",
        category="fixture",
        byte_size=len(source),
        media_type="image/png",
        width=1,
        height=1,
        has_alpha=False,
        asset_kind=VisualAssetKind.ACTION,
        roles=(VisualAssetRole.ACTION_REFERENCE,),
        approved=True,
    )
    catalog = VisualAssetCatalog(
        schema_version="brand-visual-assets-v2",
        catalog_version="brand-visual-catalog-v1",
        assets=(asset,),
    )
    embeddings = _Embedding()
    repository = _ReadySearchRepository()
    index_service = VisualCatalogIndexService(embeddings=embeddings, repository=repository)
    search_service = VisualRetrievalService(embeddings=embeddings, repository=repository)

    async def verify_current() -> bool:
        return True

    assert (
        await index_service.index_asset(
            catalog_version=catalog.catalog_version,
            asset_id=asset.asset_id,
            checksum=checksum,
            body=source,
            worker_id="unit-worker",
            verify_current=verify_current,
        )
        == "indexed"
    )
    ranking = await search_service.search_image(body=source, catalog=catalog)

    assert ranking.complete is True
    assert len(embeddings.requests) == 2
    assert embeddings.requests[0].image_png == normalized.png_bytes
    assert embeddings.requests[1].image_png == normalized.png_bytes
    assert embeddings.requests[0].input_sha256 == normalized.embedding_input_sha256
    assert embeddings.requests[1].input_sha256 == normalized.embedding_input_sha256
    assert repository.last_derivation is not None
    assert repository.last_derivation.asset_checksum == checksum
    assert repository.last_derivation.embedding_input_sha256 == normalized.embedding_input_sha256
