from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from pydantic import SecretStr

from app.application.ports.governance import EmbeddingModel, FactualAnalysisModel
from app.core.config import Settings
from app.infrastructure.ai.fake import (
    DeterministicFakeEmbeddingModel,
    DeterministicFakeFactualAnalysisModel,
)
from app.infrastructure.ai.zhipu import ZhipuEmbeddingModel, ZhipuFactualAnalysisModel


def create_embedding_model(
    settings: Settings, *, client: httpx.AsyncClient | None = None
) -> EmbeddingModel:
    if settings.ai_provider_mode == "disabled":
        raise RuntimeError("embedding model provider is disabled")
    if settings.ai_provider_mode == "fake":
        return DeterministicFakeEmbeddingModel(
            model=settings.ai_embedding_model,
            dimensions=settings.ai_embedding_dimensions,
        )
    if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
        raise RuntimeError("validated Zhipu settings are unavailable")
    if client is None:
        raise RuntimeError("Zhipu embedding model requires an owned HTTP client")
    return ZhipuEmbeddingModel(
        client=client,
        base_url=settings.ai_platform_base_url,
        api_key=SecretStr(settings.ai_platform_api_key.get_secret_value()),
        model=settings.ai_embedding_model,
        dimensions=settings.ai_embedding_dimensions,
        connect_timeout_seconds=settings.ai_connect_timeout_seconds,
        read_timeout_seconds=settings.ai_read_timeout_seconds,
        total_timeout_seconds=settings.ai_total_timeout_seconds,
        concurrency=settings.ai_provider_concurrency,
        max_attempts=settings.ai_max_attempts,
        max_input_characters=settings.ai_max_input_characters,
    )


@asynccontextmanager
async def governance_models(
    settings: Settings,
) -> AsyncIterator[tuple[FactualAnalysisModel, EmbeddingModel]]:
    if settings.ai_provider_mode == "disabled":
        raise RuntimeError("governance model provider is disabled")
    if settings.ai_provider_mode == "fake":
        yield (
            DeterministicFakeFactualAnalysisModel(model=settings.ai_chat_model),
            DeterministicFakeEmbeddingModel(
                model=settings.ai_embedding_model,
                dimensions=settings.ai_embedding_dimensions,
            ),
        )
        return
    if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
        raise RuntimeError("validated Zhipu settings are unavailable")

    client = httpx.AsyncClient(follow_redirects=False)
    try:
        yield (
            ZhipuFactualAnalysisModel(
                client=client,
                base_url=settings.ai_platform_base_url,
                api_key=SecretStr(settings.ai_platform_api_key.get_secret_value()),
                model=settings.ai_chat_model,
                connect_timeout_seconds=settings.ai_connect_timeout_seconds,
                read_timeout_seconds=settings.ai_read_timeout_seconds,
                total_timeout_seconds=settings.ai_total_timeout_seconds,
                concurrency=settings.ai_provider_concurrency,
                max_attempts=settings.ai_max_attempts,
                max_input_characters=settings.ai_max_input_characters,
                max_output_tokens=settings.ai_max_output_tokens,
            ),
            ZhipuEmbeddingModel(
                client=client,
                base_url=settings.ai_platform_base_url,
                api_key=SecretStr(settings.ai_platform_api_key.get_secret_value()),
                model=settings.ai_embedding_model,
                dimensions=settings.ai_embedding_dimensions,
                connect_timeout_seconds=settings.ai_connect_timeout_seconds,
                read_timeout_seconds=settings.ai_read_timeout_seconds,
                total_timeout_seconds=settings.ai_total_timeout_seconds,
                concurrency=settings.ai_provider_concurrency,
                max_attempts=settings.ai_max_attempts,
                max_input_characters=settings.ai_max_input_characters,
            ),
        )
    finally:
        await client.aclose()
