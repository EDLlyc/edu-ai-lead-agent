from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

import httpx
import pytest
from app import api_main
from app.application.ports.brand_knowledge import BrandEmbeddingRequest
from app.core.config import Settings
from app.infrastructure.ai.factory import (
    create_brand_embedding_model,
    select_brand_embedding_client,
)
from pydantic import SecretStr, ValidationError

_ZHIPU_BASE_URL = "https://open.bigmodel.invalid/api/paas/v4"
_ALIBABA_ENDPOINT = (
    "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)


def _zhipu_settings(*, provider_mode: Literal["auto", "zhipu"] = "zhipu") -> Settings:
    return Settings(
        _env_file=None,
        ai_provider_mode="zhipu",
        ai_platform_base_url=_ZHIPU_BASE_URL,
        ai_platform_api_key=SecretStr("test-only-zhipu-key"),
        brand_embedding_provider_mode=provider_mode,
    )


def test_brand_provider_auto_resolution_is_compatible_and_fail_closed() -> None:
    zhipu = _zhipu_settings(provider_mode="auto")
    assert zhipu.resolved_brand_embedding_provider_mode == "zhipu"
    assert (
        zhipu.brand_embedding_provider,
        zhipu.brand_embedding_model,
        zhipu.brand_embedding_dimensions,
    ) == ("zhipu", "embedding-3", 2048)

    alibaba_preferred = Settings(
        _env_file=None,
        ai_provider_mode="zhipu",
        ai_platform_base_url=_ZHIPU_BASE_URL,
        ai_platform_api_key=SecretStr("test-only-zhipu-key"),
        visual_embedding_provider_mode="alibaba",
        visual_embedding_endpoint=SecretStr(_ALIBABA_ENDPOINT),
        visual_embedding_api_key=SecretStr("test-only-alibaba-key"),
    )
    assert alibaba_preferred.resolved_brand_embedding_provider_mode == "alibaba"
    assert alibaba_preferred.brand_embedding_provider == "alibaba-model-studio"

    with pytest.raises(ValidationError, match="requires Zhipu AI provider"):
        Settings(_env_file=None, brand_embedding_provider_mode="zhipu")
    with pytest.raises(ValidationError, match="non-blank API key"):
        Settings(
            _env_file=None,
            ai_provider_mode="zhipu",
            ai_platform_base_url=_ZHIPU_BASE_URL,
            brand_embedding_provider_mode="zhipu",
        )
    with pytest.raises(ValidationError, match="embedding-3 model identity"):
        Settings(
            _env_file=None,
            ai_provider_mode="zhipu",
            ai_platform_base_url=_ZHIPU_BASE_URL,
            ai_platform_api_key=SecretStr("test-only-zhipu-key"),
            ai_embedding_model="other-model",
            brand_embedding_provider_mode="zhipu",
        )


def test_content_worker_brand_gate_preserves_provider_free_selection() -> None:
    selection_only = Settings(
        _env_file=None,
        content_enabled=True,
        content_worker_enabled=True,
        content_llm_rerank_enabled=False,
        ai_provider_mode="fake",
        brand_embedding_provider_mode="disabled",
    )
    assert selection_only.resolved_brand_embedding_provider_mode == "disabled"

    with pytest.raises(ValidationError, match="enabled brand embedding provider"):
        Settings(
            _env_file=None,
            content_enabled=True,
            content_worker_enabled=True,
            content_copy_provider_required=True,
            content_llm_rerank_enabled=False,
            ai_provider_mode="fake",
            brand_embedding_provider_mode="disabled",
        )

    with pytest.raises(ValidationError, match="copy-capable AI provider"):
        Settings(
            _env_file=None,
            content_enabled=True,
            content_worker_enabled=True,
            content_copy_provider_required=True,
            content_llm_rerank_enabled=False,
        )

    automatic_delivery_upstream = Settings(
        _env_file=None,
        content_enabled=True,
        content_worker_enabled=True,
        content_copy_provider_required=True,
        content_llm_rerank_enabled=False,
        ai_provider_mode="fake",
    )
    assert automatic_delivery_upstream.resolved_brand_embedding_provider_mode == "fake"


def test_brand_client_selection_never_crosses_provider_ownership() -> None:
    zhipu_client = object()
    alibaba_client = object()
    assert (
        select_brand_embedding_client(
            _zhipu_settings(),
            zhipu_client=zhipu_client,  # type: ignore[arg-type]
            alibaba_client=alibaba_client,  # type: ignore[arg-type]
        )
        is zhipu_client
    )
    alibaba = Settings(
        _env_file=None,
        ai_provider_mode="disabled",
        brand_embedding_provider_mode="alibaba",
        visual_embedding_endpoint=SecretStr(_ALIBABA_ENDPOINT),
        visual_embedding_api_key=SecretStr("test-only-alibaba-key"),
    )
    assert (
        select_brand_embedding_client(
            alibaba,
            zhipu_client=zhipu_client,  # type: ignore[arg-type]
            alibaba_client=alibaba_client,  # type: ignore[arg-type]
        )
        is alibaba_client
    )
    assert (
        select_brand_embedding_client(
            Settings(_env_file=None),
            zhipu_client=zhipu_client,  # type: ignore[arg-type]
            alibaba_client=alibaba_client,  # type: ignore[arg-type]
        )
        is None
    )


def test_zhipu_brand_factory_requires_an_owned_client() -> None:
    with pytest.raises(RuntimeError, match="owned HTTP client"):
        create_brand_embedding_model(_zhipu_settings())

    unvalidated_drift = _zhipu_settings().model_copy(update={"ai_provider_mode": "fake"})
    with pytest.raises(RuntimeError, match="requires Zhipu AI provider"):
        create_brand_embedding_model(unvalidated_drift)


@pytest.mark.asyncio
async def test_zhipu_brand_adapter_makes_one_bounded_embedding_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "brand-embedding-request-1",
                "model": "embedding-3",
                "data": [{"index": 0, "embedding": [0.25] * 2048}],
                "usage": {"prompt_tokens": 8, "total_tokens": 8},
            },
        )

    text = "赛先生品牌语气,准确、克制、温暖。"
    request = BrandEmbeddingRequest(
        chunk_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        input_hash=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = create_brand_embedding_model(_zhipu_settings(), client=client)
        result = await model.embed_brand(request)

    assert captured == {
        "url": f"{_ZHIPU_BASE_URL}/embeddings",
        "authorization": "Bearer test-only-zhipu-key",
        "payload": {"model": "embedding-3", "input": text, "dimensions": 2048},
    }
    assert result.provider == "zhipu"
    assert result.model == "embedding-3"
    assert len(result.vector) == 2048
    assert len(result.request_fingerprint) == 64
    assert result.provider_request_id == "brand-embedding-request-1"
    assert "test-only-zhipu-key" not in repr(result)


@pytest.mark.asyncio
async def test_api_lifespan_owns_and_closes_dedicated_zhipu_brand_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[object] = []
    factory_clients: list[object | None] = []

    class _Client:
        def __init__(self, **_: object) -> None:
            self.closed = False
            clients.append(self)

        async def aclose(self) -> None:
            self.closed = True

    class _Engine:
        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(api_main, "settings", _zhipu_settings())
    monkeypatch.setattr(api_main, "engine", _Engine())
    monkeypatch.setattr(api_main.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(
        api_main,
        "create_brand_embedding_model",
        lambda _settings, *, client=None: factory_clients.append(client) or object(),
    )

    test_app = api_main.FastAPI()
    async with api_main.lifespan(test_app):
        assert len(clients) == 1
        assert factory_clients == clients
        assert clients[0].closed is False  # type: ignore[attr-defined]

    assert clients[0].closed is True  # type: ignore[attr-defined]
