from __future__ import annotations

import hashlib

from app.application.ports.brand_knowledge import (
    BrandEmbeddingModel,
    BrandEmbeddingRequest,
    BrandEmbeddingResult,
)
from app.application.ports.governance import EmbeddingModel, EmbeddingRequest
from app.domain.governance_enums import EmbeddingPurpose
from app.domain.visual_retrieval import VisualEmbeddingIdentity
from app.infrastructure.ai.visual_embedding import AlibabaVisualEmbeddingAdapter


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


class AlibabaMultimodalBrandEmbeddingAdapter(BrandEmbeddingModel):
    """Projects Alibaba's shared text/image vector space onto the brand-RAG port."""

    _MAX_TEXT_CHARACTERS = 40_000
    _REQUEST_FINGERPRINT_VERSION = "alibaba-brand-embedding-request-v1"

    def __init__(
        self,
        model: AlibabaVisualEmbeddingAdapter,
        *,
        identity: VisualEmbeddingIdentity,
    ) -> None:
        self._model = model
        self._identity = identity

    async def embed_brand(self, request: BrandEmbeddingRequest) -> BrandEmbeddingResult:
        result = await self._model.embed_brand_text(
            text=request.text,
            input_sha256=request.input_hash,
            identity=self._identity,
            max_characters=self._MAX_TEXT_CHARACTERS,
        )
        request_fingerprint = hashlib.sha256(
            "\0".join(
                (
                    self._REQUEST_FINGERPRINT_VERSION,
                    str(request.chunk_id),
                    result.request_fingerprint,
                )
            ).encode()
        ).hexdigest()
        return BrandEmbeddingResult(
            vector=result.vector,
            provider=result.identity.provider,
            model=result.identity.model,
            request_fingerprint=request_fingerprint,
            provider_request_id=None,
        )
