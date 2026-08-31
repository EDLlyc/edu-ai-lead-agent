from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TypeVar

import httpx
from pydantic import SecretStr

from app.application.ports.brand_knowledge import BrandDocumentOcrModel, BrandEmbeddingModel
from app.application.ports.copy_generation import MaterialDraftAuditor, MaterialDraftGenerator
from app.application.ports.governance import EmbeddingModel, FactualAnalysisModel
from app.application.ports.image_generation import ImageGenerator
from app.application.ports.image_validation import ImageQualityAuditor, ImageTextRecognizer
from app.application.ports.ip_assets import IpAssetRecognitionModel
from app.core.config import Settings
from app.infrastructure.ai.brand import (
    AlibabaMultimodalBrandEmbeddingAdapter,
    GovernanceEmbeddingBrandAdapter,
)
from app.infrastructure.ai.copy_generation import (
    DeterministicFakeMaterialDraftAuditor,
    DeterministicFakeMaterialDraftGenerator,
    create_zhipu_copy_models,
)
from app.infrastructure.ai.fake import (
    DeterministicFakeEmbeddingModel,
    DeterministicFakeFactualAnalysisModel,
)
from app.infrastructure.ai.image_generation import (
    DeterministicFakeImageGenerator,
    OpenAICompatibleImageGenerator,
    OutputHostObserver,
    ToApisImageGenerator,
)
from app.infrastructure.ai.image_validation import (
    OpenAICompatibleImageQualityAuditor,
)
from app.infrastructure.ai.ip_asset_recognition import ZhipuIpAssetRecognitionAdapter
from app.infrastructure.ai.visual_embedding import AlibabaVisualEmbeddingAdapter
from app.infrastructure.ai.zhipu import (
    ZhipuBrandDocumentOcrModel,
    ZhipuEmbeddingModel,
    ZhipuFactualAnalysisModel,
    ZhipuImageTextRecognizer,
)

_ImageValidationProvider = TypeVar("_ImageValidationProvider")


def create_ip_asset_recognition_model(
    settings: Settings, *, client: httpx.AsyncClient | None = None
) -> IpAssetRecognitionModel | None:
    """Create the optional API-side vision assistant only when fully configured."""

    if not settings.ip_asset_recognition_enabled:
        return None
    base_url = (settings.ai_platform_base_url or "").strip()
    api_key = settings.ai_platform_api_key
    api_key_value = api_key.get_secret_value().strip() if api_key is not None else ""
    if client is None or settings.ai_provider_mode != "zhipu" or not base_url or not api_key_value:
        return None
    return ZhipuIpAssetRecognitionAdapter(
        client=client,
        base_url=base_url,
        api_key=SecretStr(api_key_value),
        model=settings.ip_asset_recognition_model,
        connect_timeout_seconds=min(
            settings.ai_connect_timeout_seconds,
            settings.ip_asset_recognition_timeout_seconds,
        ),
        total_timeout_seconds=settings.ip_asset_recognition_timeout_seconds,
        concurrency=settings.ip_asset_recognition_concurrency,
        max_request_bytes=settings.ip_asset_recognition_max_request_bytes,
        max_response_bytes=settings.ip_asset_recognition_max_response_bytes,
    )


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


def create_brand_embedding_model(
    settings: Settings, *, client: httpx.AsyncClient | None = None
) -> BrandEmbeddingModel:
    """Create the brand-only vector model without changing governance embeddings."""

    mode = settings.resolved_brand_embedding_provider_mode
    if mode == "disabled":
        raise RuntimeError("brand embedding model provider is disabled")
    if mode == "fake":
        return GovernanceEmbeddingBrandAdapter(create_embedding_model(settings, client=client))
    if (
        client is None
        or settings.visual_embedding_endpoint is None
        or settings.visual_embedding_api_key is None
    ):
        raise RuntimeError("Alibaba brand embedding requires an owned HTTP client")
    multimodal = AlibabaVisualEmbeddingAdapter(
        client=client,
        endpoint=settings.visual_embedding_endpoint,
        api_key=settings.visual_embedding_api_key,
        timeout_seconds=settings.visual_embedding_timeout_seconds,
        concurrency=settings.visual_embedding_concurrency,
    )
    return AlibabaMultimodalBrandEmbeddingAdapter(
        multimodal,
        identity=settings.visual_embedding_identity,
    )


def create_brand_ocr_model(
    settings: Settings, *, client: httpx.AsyncClient | None = None
) -> BrandDocumentOcrModel:
    if settings.ai_provider_mode != "zhipu":
        raise RuntimeError("brand OCR is available only in AI_PROVIDER_MODE=zhipu")
    if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
        raise RuntimeError("validated Zhipu OCR settings are unavailable")
    if client is None:
        raise RuntimeError("Zhipu OCR requires an owned HTTP client")
    return ZhipuBrandDocumentOcrModel(
        client=client,
        base_url=settings.ai_platform_base_url,
        api_key=SecretStr(settings.ai_platform_api_key.get_secret_value()),
        model=settings.brand_ocr_model,
        connect_timeout_seconds=settings.ai_connect_timeout_seconds,
        read_timeout_seconds=settings.brand_ocr_timeout_seconds,
        total_timeout_seconds=settings.brand_ocr_timeout_seconds,
        concurrency=settings.ai_provider_concurrency,
        max_attempts=settings.ai_max_attempts,
        max_request_bytes=settings.brand_ocr_max_request_bytes,
        max_response_bytes=settings.brand_ocr_max_response_bytes,
        max_pages=settings.brand_ocr_max_pages,
    )


def create_image_text_recognizer(
    settings: Settings, *, client: httpx.AsyncClient | None = None
) -> ImageTextRecognizer | None:
    """Create the optional worker-only image OCR adapter when its capability is usable."""

    if (
        not settings.image_ocr_enabled
        or settings.image_provider_mode not in {"toapis", "comfly"}
        or settings.ai_provider_mode != "zhipu"
    ):
        return None
    base_url = (settings.ai_platform_base_url or "").strip()
    api_key = settings.ai_platform_api_key
    api_key_value = api_key.get_secret_value().strip() if api_key is not None else ""
    if client is None or not base_url or not api_key_value:
        return None
    return ZhipuImageTextRecognizer(
        client=client,
        base_url=base_url,
        api_key=SecretStr(api_key_value),
        model=settings.image_ocr_model,
        connect_timeout_seconds=settings.ai_connect_timeout_seconds,
        read_timeout_seconds=settings.image_ocr_timeout_seconds,
        total_timeout_seconds=settings.image_ocr_timeout_seconds,
        concurrency=settings.ai_provider_concurrency,
        max_attempts=settings.ai_max_attempts,
        max_input_bytes=settings.image_ocr_max_input_bytes,
        max_response_bytes=settings.image_ocr_max_response_bytes,
    )


def create_image_quality_auditor(
    settings: Settings, *, client: httpx.AsyncClient | None = None
) -> ImageQualityAuditor | None:
    """Create the optional worker-only image quality adapter when its capability is usable."""

    if not settings.image_quality_audit_enabled:
        return None
    return _create_image_validation_provider(
        settings,
        client=client,
        provider_class=OpenAICompatibleImageQualityAuditor,
    )


def _create_image_validation_provider(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None,
    provider_class: Callable[..., _ImageValidationProvider],
) -> _ImageValidationProvider | None:
    """Resolve an OpenAI-compatible validation adapter without creating API-side clients."""

    if settings.image_provider_mode == "fake" or settings.ai_provider_mode != "zhipu":
        return None
    base_url = (settings.ai_platform_base_url or "").strip()
    api_key = settings.ai_platform_api_key
    api_key_value = api_key.get_secret_value().strip() if api_key is not None else ""
    if client is None or not base_url or not api_key_value:
        return None

    return provider_class(
        client=client,
        base_url=base_url,
        api_key=SecretStr(api_key_value),
        model=settings.ai_chat_model,
        connect_timeout_seconds=settings.ai_connect_timeout_seconds,
        read_timeout_seconds=settings.ai_read_timeout_seconds,
        total_timeout_seconds=settings.ai_total_timeout_seconds,
        concurrency=settings.ai_provider_concurrency,
        max_attempts=settings.ai_max_attempts,
        max_request_bytes=settings.image_max_request_bytes,
        max_response_bytes=settings.image_max_provider_response_bytes,
    )


def create_image_generator(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    output_host_observer: OutputHostObserver | None = None,
) -> ImageGenerator:
    if output_host_observer is not None and settings.image_provider_mode != "comfly":
        raise RuntimeError("output hostname discovery is available only for the Comfly provider")
    if settings.image_provider_mode == "disabled":
        raise RuntimeError("image provider is disabled")
    if settings.image_provider_mode == "fake":
        return DeterministicFakeImageGenerator(model=settings.image_model)
    if settings.image_provider_mode == "toapis":
        if client is None or settings.toapis_api_key is None:
            raise RuntimeError("ToAPIs image provider requires an owned client and API key")
        return ToApisImageGenerator(
            client=client,
            base_url=settings.toapis_base_url,
            api_key=SecretStr(settings.toapis_api_key.get_secret_value()),
            model=settings.image_model,
            max_attempts=settings.image_max_attempts,
            initial_poll_seconds=settings.image_poll_initial_seconds,
            poll_interval_seconds=settings.image_poll_interval_seconds,
            provider_window_seconds=settings.image_provider_window_seconds,
            timeout_seconds=settings.image_provider_timeout_seconds,
            max_download_bytes=settings.image_max_download_bytes,
        )
    if client is None or settings.comfly_api_key is None:
        raise RuntimeError("Comfly image provider requires an owned client and API key")
    return OpenAICompatibleImageGenerator(
        client=client,
        base_url=settings.comfly_base_url,
        api_key=SecretStr(settings.comfly_api_key.get_secret_value()),
        model=settings.image_model,
        max_attempts=settings.image_max_attempts,
        initial_poll_seconds=settings.image_poll_initial_seconds,
        poll_interval_seconds=settings.image_poll_interval_seconds,
        provider_window_seconds=settings.image_provider_window_seconds,
        timeout_seconds=settings.image_provider_timeout_seconds,
        max_download_bytes=settings.image_max_download_bytes,
        max_request_bytes=settings.image_max_request_bytes,
        max_provider_response_bytes=settings.image_max_provider_response_bytes,
        max_reference_images=settings.image_max_reference_images,
        output_host_observer=output_host_observer,
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


@asynccontextmanager
async def copy_models(
    settings: Settings,
) -> AsyncIterator[tuple[MaterialDraftGenerator, MaterialDraftAuditor]]:
    if settings.ai_provider_mode == "disabled":
        raise RuntimeError("copy model provider is disabled")
    if settings.ai_provider_mode == "fake":
        yield (
            DeterministicFakeMaterialDraftGenerator(model=settings.ai_chat_model),
            DeterministicFakeMaterialDraftAuditor(model=settings.ai_chat_model),
        )
        return
    if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
        raise RuntimeError("validated Zhipu settings are unavailable")
    client = httpx.AsyncClient(follow_redirects=False)
    try:
        yield create_zhipu_copy_models(
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
            max_output_tokens=settings.copy_max_output_tokens,
            max_validation_corrections=settings.ai_max_validation_corrections,
        )
    finally:
        await client.aclose()
