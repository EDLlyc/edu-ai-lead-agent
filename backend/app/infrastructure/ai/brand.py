from __future__ import annotations

from app.application.ports.brand_knowledge import (
    BrandEmbeddingModel,
    BrandEmbeddingRequest,
    BrandEmbeddingResult,
)
from app.application.ports.governance import EmbeddingModel, EmbeddingRequest
from app.domain.governance_enums import EmbeddingPurpose


class GovernanceEmbeddingBrandAdapter(BrandEmbeddingModel):
    """Reuses provider transport while preserving a brand-specific application port."""

    def __init__(self, model: EmbeddingModel) -> None:
        self._model = model

    async def embed_brand(self, request: BrandEmbeddingRequest) -> BrandEmbeddingResult:
        result = await self._model.embed(
            EmbeddingRequest(
                artifact_id=request.chunk_id,
                purpose=EmbeddingPurpose.BRAND_RETRIEVAL,
                input_hash=request.input_hash,
                text=request.text,
            )
        )
        return BrandEmbeddingResult(
            vector=result.vector,
            provider=result.provider,
            model=result.model,
            request_fingerprint=result.request_fingerprint,
            provider_request_id=result.provider_request_id,
        )
