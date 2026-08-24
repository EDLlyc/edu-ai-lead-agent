from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.domain.visual_retrieval import (
    VisualAssetDerivation,
    VisualEmbeddingIdentity,
    VisualEmbeddingRequest,
    VisualEmbeddingResult,
    VisualSemanticRanking,
)


@dataclass(frozen=True, slots=True)
class VisualIndexClaim:
    job_id: UUID
    lease_token: UUID
    derivation: VisualAssetDerivation
    attempt_number: int


class VisualEmbeddingModel(Protocol):
    async def embed_visual(self, request: VisualEmbeddingRequest) -> VisualEmbeddingResult: ...


class VisualIndexRepository(Protocol):
    async def claim_asset(
        self,
        *,
        derivation: VisualAssetDerivation,
        worker_id: str,
        lease_seconds: int,
    ) -> VisualIndexClaim | None: ...

    async def persist_embedding(
        self, *, claim: VisualIndexClaim, embedding: VisualEmbeddingResult
    ) -> bool: ...

    async def fail_asset(self, *, claim: VisualIndexClaim, error_code: str) -> bool: ...

    async def prove_complete_catalog(
        self,
        *,
        catalog_version: str,
        catalog_assets: tuple[tuple[str, str], ...],
        identity: VisualEmbeddingIdentity,
    ) -> bool: ...

    async def search_complete_catalog(
        self,
        *,
        catalog_version: str,
        catalog_assets: tuple[tuple[str, str], ...],
        identity: VisualEmbeddingIdentity,
        query: VisualEmbeddingResult,
    ) -> VisualSemanticRanking: ...
