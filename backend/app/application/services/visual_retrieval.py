from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.application.ports.visual_retrieval import (
    VisualEmbeddingModel,
    VisualIndexRepository,
)
from app.domain.visual_assets import VisualAssetCatalog
from app.domain.visual_retrieval import (
    NormalizedVisualImage,
    VisualAssetDerivation,
    VisualEmbeddingError,
    VisualEmbeddingIdentity,
    VisualEmbeddingRequest,
    VisualIndexUnavailableError,
    VisualRetrievalUnavailableReason,
    VisualSemanticRanking,
    normalize_visual_embedding_image,
)


def approved_catalog_assets(catalog: VisualAssetCatalog) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted((asset.asset_id, asset.checksum) for asset in catalog.assets if asset.approved)
    )


class VisualRetrievalService:
    def __init__(
        self,
        *,
        embeddings: VisualEmbeddingModel,
        repository: VisualIndexRepository,
        identity: VisualEmbeddingIdentity | None = None,
    ) -> None:
        self._embeddings = embeddings
        self._repository = repository
        self._identity = identity or VisualEmbeddingIdentity()

    async def search_text(self, *, text: str, catalog: VisualAssetCatalog) -> VisualSemanticRanking:
        return await self._search(
            VisualEmbeddingRequest.for_text(text, identity=self._identity), catalog
        )

    async def search_image(
        self, *, body: bytes, catalog: VisualAssetCatalog
    ) -> VisualSemanticRanking:
        try:
            normalized = await asyncio.to_thread(
                normalize_visual_embedding_image, body, identity=self._identity
            )
        except ValueError as error:
            raise VisualIndexUnavailableError(
                VisualRetrievalUnavailableReason.INPUT_NORMALIZATION_FAILED
            ) from error
        return await self.search_normalized_image(normalized=normalized, catalog=catalog)

    async def search_normalized_image(
        self, *, normalized: NormalizedVisualImage, catalog: VisualAssetCatalog
    ) -> VisualSemanticRanking:
        if normalized.input_policy_version != self._identity.input_policy_version:
            raise VisualIndexUnavailableError(VisualRetrievalUnavailableReason.IDENTITY_MISMATCH)
        try:
            request = await asyncio.to_thread(
                VisualEmbeddingRequest.for_normalized_image,
                normalized.png_bytes,
                identity=self._identity,
            )
        except ValueError as error:
            raise VisualIndexUnavailableError(
                VisualRetrievalUnavailableReason.INPUT_NORMALIZATION_FAILED
            ) from error
        return await self._search(
            request,
            catalog,
        )

    async def _search(
        self, request: VisualEmbeddingRequest, catalog: VisualAssetCatalog
    ) -> VisualSemanticRanking:
        try:
            embedding = await self._embeddings.embed_visual(request)
        except VisualIndexUnavailableError:
            raise
        except VisualEmbeddingError as error:
            raise VisualIndexUnavailableError(error.reason) from error
        except Exception as error:
            raise VisualIndexUnavailableError(
                VisualRetrievalUnavailableReason.PROVIDER_UNAVAILABLE
            ) from error
        if (
            embedding.identity != self._identity
            or embedding.input_sha256 != request.input_sha256
            or embedding.request_fingerprint != request.request_fingerprint
        ):
            raise VisualIndexUnavailableError(VisualRetrievalUnavailableReason.IDENTITY_MISMATCH)
        catalog_assets = approved_catalog_assets(catalog)
        try:
            ranking = await self._repository.search_complete_catalog(
                catalog_version=catalog.catalog_version,
                catalog_assets=catalog_assets,
                identity=self._identity,
                query=embedding,
            )
        except VisualIndexUnavailableError:
            raise
        except Exception as error:
            raise VisualIndexUnavailableError(
                VisualRetrievalUnavailableReason.INDEX_INCOMPLETE
            ) from error
        expected_asset_ids = {asset_id for asset_id, _checksum in catalog_assets}
        if (
            ranking.identity != self._identity
            or ranking.catalog_version != catalog.catalog_version
            or ranking.query_fingerprint != request.request_fingerprint
        ):
            raise VisualIndexUnavailableError(VisualRetrievalUnavailableReason.IDENTITY_MISMATCH)
        if not ranking.complete:
            raise VisualIndexUnavailableError(VisualRetrievalUnavailableReason.INDEX_INCOMPLETE)
        if set(ranking.score_map) != expected_asset_ids:
            raise VisualIndexUnavailableError(VisualRetrievalUnavailableReason.INDEX_INCOMPLETE)
        return ranking


@dataclass(frozen=True, slots=True)
class VisualIndexRunSummary:
    catalog_asset_count: int
    attempted_count: int
    indexed_count: int
    existing_count: int
    failed_count: int


class VisualCatalogIndexService:
    def __init__(
        self,
        *,
        embeddings: VisualEmbeddingModel,
        repository: VisualIndexRepository,
        identity: VisualEmbeddingIdentity | None = None,
        lease_seconds: int = 300,
    ) -> None:
        self._embeddings = embeddings
        self._repository = repository
        self._identity = identity or VisualEmbeddingIdentity()
        self._lease_seconds = lease_seconds

    async def index_asset(
        self,
        *,
        catalog_version: str,
        asset_id: str,
        checksum: str,
        body: bytes,
        worker_id: str,
        verify_current: Callable[[], Awaitable[bool]],
    ) -> str:
        if hashlib.sha256(body).hexdigest() != checksum:
            raise ValueError("visual asset bytes do not match the claimed checksum")
        normalized = await asyncio.to_thread(
            normalize_visual_embedding_image, body, identity=self._identity
        )
        if normalized.source_sha256 != checksum:
            raise ValueError("visual asset normalization source hash changed")
        request = await asyncio.to_thread(
            VisualEmbeddingRequest.for_normalized_image,
            normalized.png_bytes,
            identity=self._identity,
        )
        derivation = VisualAssetDerivation(
            asset_id=asset_id,
            asset_checksum=checksum,
            embedding_input_sha256=request.input_sha256,
            catalog_version=catalog_version,
            identity=self._identity,
        )
        claim = await self._repository.claim_asset(
            derivation=derivation,
            worker_id=worker_id,
            lease_seconds=self._lease_seconds,
        )
        if claim is None:
            return "existing"
        try:
            embedding = await self._embeddings.embed_visual(request)
            if (
                embedding.identity != self._identity
                or embedding.input_sha256 != derivation.embedding_input_sha256
                or embedding.request_fingerprint != request.request_fingerprint
            ):
                await self._repository.fail_asset(claim=claim, error_code="identity_mismatch")
                return "failed"
        except VisualEmbeddingError as error:
            await self._repository.fail_asset(claim=claim, error_code=error.reason.value)
            return "failed"
        except Exception:
            await self._repository.fail_asset(claim=claim, error_code="provider_unavailable")
            return "failed"
        try:
            current = await verify_current()
        except Exception:
            current = False
        if not current:
            await self._repository.fail_asset(claim=claim, error_code="catalog_changed")
            return "failed"
        try:
            persisted = await self._repository.persist_embedding(claim=claim, embedding=embedding)
        except Exception:
            try:
                await self._repository.fail_asset(claim=claim, error_code="provider_unavailable")
            except Exception:
                raise VisualIndexUnavailableError(
                    VisualRetrievalUnavailableReason.PROVIDER_UNAVAILABLE
                ) from None
            return "failed"
        return "indexed" if persisted else "failed"
