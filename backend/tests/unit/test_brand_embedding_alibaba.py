from __future__ import annotations

import hashlib
import json
from uuid import UUID

import httpx
import pytest
from app.application.ports.brand_knowledge import BrandEmbeddingRequest
from app.core.config import Settings
from app.infrastructure.ai.factory import create_brand_embedding_model
from pydantic import SecretStr

_ENDPOINT = (
    "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)


def _alibaba_settings() -> Settings:
    return Settings(
        _env_file=None,
        ai_provider_mode="disabled",
        brand_embedding_provider_mode="alibaba",
        visual_embedding_endpoint=SecretStr(_ENDPOINT),
        visual_embedding_api_key=SecretStr("test-only-alibaba-key"),
    )


@pytest.mark.asyncio
async def test_alibaba_multimodal_brand_adapter_preserves_provider_identity() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "model": "qwen3-vl-embedding",
                "provider": "alibaba-model-studio",
                "output": {"embeddings": [{"embedding": [0.5] * 2048}]},
                "usage": {"input_tokens": 8, "image_tokens": 0},
            },
        )

    settings = _alibaba_settings()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = create_brand_embedding_model(settings, client=client)
        # Brand ingestion can embed a configured 3,000-character chunk even though the
        # public visual-search query contract is capped at 2,000 characters.
        text = "青少年人工智能教育安全" * 250
        result = await model.embed_brand(
            BrandEmbeddingRequest(
                chunk_id=UUID(int=1),
                input_hash=hashlib.sha256(text.encode()).hexdigest(),
                text=text,
            )
        )

    assert calls == 1
    assert result.provider == "alibaba-model-studio"
    assert result.model == "qwen3-vl-embedding"
    assert len(result.vector) == 2048
    assert len(result.request_fingerprint) == 64


@pytest.mark.asyncio
async def test_identical_brand_text_binds_fingerprint_to_each_chunk() -> None:
    provider_payloads: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        provider_payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "qwen3-vl-embedding",
                "provider": "alibaba-model-studio",
                "output": {"embeddings": [{"embedding": [0.25] * 2048}]},
            },
        )

    settings = _alibaba_settings()
    text = "重复但合法的品牌片段"
    input_hash = hashlib.sha256(text.encode()).hexdigest()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = create_brand_embedding_model(settings, client=client)
        first = await model.embed_brand(
            BrandEmbeddingRequest(
                chunk_id=UUID(int=101),
                input_hash=input_hash,
                text=text,
            )
        )
        second = await model.embed_brand(
            BrandEmbeddingRequest(
                chunk_id=UUID(int=102),
                input_hash=input_hash,
                text=text,
            )
        )

    assert len(provider_payloads) == 2
    assert provider_payloads[0] == provider_payloads[1]
    assert first.vector == second.vector
    assert first.request_fingerprint != second.request_fingerprint
    assert all(
        len(fingerprint) == 64 and set(fingerprint) <= set("0123456789abcdef")
        for fingerprint in (first.request_fingerprint, second.request_fingerprint)
    )


@pytest.mark.asyncio
async def test_alibaba_multimodal_brand_adapter_rejects_input_hash_drift_before_http() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    settings = _alibaba_settings()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = create_brand_embedding_model(settings, client=client)
        with pytest.raises(ValueError, match="input hash"):
            await model.embed_brand(
                BrandEmbeddingRequest(
                    chunk_id=UUID(int=2),
                    input_hash="0" * 64,
                    text="受控查询",
                )
            )

    assert calls == 0


def test_fake_brand_embedding_remains_available_for_provider_free_tests() -> None:
    settings = Settings(_env_file=None, ai_provider_mode="fake")

    model = create_brand_embedding_model(settings)

    assert model is not None
