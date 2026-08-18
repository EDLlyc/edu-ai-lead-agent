from __future__ import annotations

import httpx
import pytest
from app.core.config import Settings
from app.infrastructure.ai import factory
from pydantic import SecretStr


def test_validation_adapters_are_absent_by_default_and_in_fake_mode() -> None:
    client = httpx.AsyncClient()

    try:
        defaults = Settings(_env_file=None)
        assert factory.create_image_text_recognizer(defaults, client=client) is None
        assert factory.create_image_quality_auditor(defaults, client=client) is None

        fake = Settings(
            _env_file=None,
            image_ocr_enabled=True,
            image_quality_audit_enabled=True,
            ai_provider_mode="fake",
        )
        assert factory.create_image_text_recognizer(fake, client=client) is None
        assert factory.create_image_quality_auditor(fake, client=client) is None

        image_fake = Settings(
            _env_file=None,
            image_provider_mode="fake",
            image_ocr_enabled=True,
            image_quality_audit_enabled=True,
            ai_provider_mode="zhipu",
            ai_platform_base_url="https://ai.example.test/v1",
            ai_platform_api_key=SecretStr("test-key"),
        )
        assert factory.create_image_text_recognizer(image_fake, client=client) is None
        assert factory.create_image_quality_auditor(image_fake, client=client) is None

        missing_client = image_fake.model_copy(update={"image_provider_mode": "comfly"})
        assert factory.create_image_text_recognizer(missing_client) is None
        assert factory.create_image_quality_auditor(missing_client) is None

        fake_image_with_real_ai = Settings(
            _env_file=None,
            image_enabled=True,
            image_provider_mode="fake",
            image_ocr_enabled=True,
            image_quality_audit_enabled=True,
            ai_provider_mode="zhipu",
            ai_platform_base_url="https://ai.example.test/v1",
            ai_platform_api_key=SecretStr("test-key"),
        )
        assert factory.create_image_text_recognizer(fake_image_with_real_ai, client=client) is None
        assert factory.create_image_quality_auditor(fake_image_with_real_ai, client=client) is None

        controlled_without_ocr = Settings(
            _env_file=None,
            image_enabled=True,
            image_provider_mode="comfly",
            comfly_api_key=SecretStr("image-test-key"),
            image_diversity_enabled=True,
            image_ocr_enabled=False,
            image_ocr_model="unused-while-disabled",
            ai_provider_mode="zhipu",
            ai_platform_base_url="https://ai.example.test/v1",
            ai_platform_api_key=SecretStr("test-key"),
        )
        assert factory.create_image_text_recognizer(controlled_without_ocr, client=client) is None
    finally:
        import asyncio

        asyncio.run(client.aclose())


def test_validation_adapters_share_the_supplied_ai_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class _Provider:
        def __init__(self, **kwargs: object) -> None:
            calls.append((self.__class__.__name__, kwargs))

    class ZhipuImageTextRecognizer(_Provider):
        pass

    class OpenAICompatibleImageQualityAuditor(_Provider):
        pass

    monkeypatch.setattr(
        factory,
        "ZhipuImageTextRecognizer",
        ZhipuImageTextRecognizer,
    )
    monkeypatch.setattr(
        factory,
        "OpenAICompatibleImageQualityAuditor",
        OpenAICompatibleImageQualityAuditor,
    )

    settings = Settings(
        _env_file=None,
        image_ocr_enabled=True,
        image_quality_audit_enabled=True,
        image_provider_mode="comfly",
        comfly_api_key=SecretStr("image-test-key"),
        ai_provider_mode="zhipu",
        ai_platform_base_url="https://ai.example.test/v1",
        ai_platform_api_key=SecretStr("test-key"),
        ai_chat_model="glm-5.2",
        image_ocr_model="glm-ocr",
    )
    client = object()

    recognizer = factory.create_image_text_recognizer(settings, client=client)  # type: ignore[arg-type]
    auditor = factory.create_image_quality_auditor(settings, client=client)  # type: ignore[arg-type]

    assert isinstance(recognizer, ZhipuImageTextRecognizer)
    assert isinstance(auditor, OpenAICompatibleImageQualityAuditor)
    assert calls[0][1]["client"] is client
    assert calls[1][1]["client"] is client
    api_key = calls[0][1]["api_key"]
    assert isinstance(api_key, SecretStr)
    assert api_key.get_secret_value() == "test-key"
    assert calls[0][1]["model"] == "glm-ocr"
    assert calls[0][1]["max_input_bytes"] == 10 * 1024 * 1024
    assert calls[0][1]["max_response_bytes"] == 1024 * 1024
    assert calls[1][1]["model"] == "glm-5.2"
    assert calls[1][1]["max_request_bytes"] == settings.image_max_request_bytes
