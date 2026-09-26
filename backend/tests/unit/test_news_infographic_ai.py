"""The local portrait trial pins its image model without changing global defaults."""

from __future__ import annotations

import json
from io import BytesIO
from uuid import uuid4

import httpx
import pytest
from app.application.ports.image_generation import ImageGenerationRequest
from app.core.config import Settings
from app.infrastructure.ai.news_infographic import (
    LOCAL_INFOGRAPHIC_IMAGE_MODEL,
    LocalInfographicAI,
)
from PIL import Image
from pydantic import SecretStr


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        ai_provider_mode="zhipu",
        ai_platform_base_url="https://open.bigmodel.cn/api/paas/v4",
        ai_platform_api_key=SecretStr("test-chat-key"),
        image_provider_mode="comfly",
        comfly_api_key=SecretStr("test-image-key"),
        image_model="gpt-image-2",
        image_ocr_enabled=False,
        image_quality_audit_enabled=False,
    )


@pytest.mark.asyncio
async def test_local_image_model_is_25_and_request_is_portrait_even_if_settings_are_2() -> None:
    output = BytesIO()
    Image.new("RGB", (1152, 2048), (24, 90, 160)).save(output, format="PNG")
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://ai.comfly.org/v1/images/generations"
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=output.getvalue())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        models = LocalInfographicAI(_settings(), client)
        result = await models.generate(
            ImageGenerationRequest(
                run_id=uuid4(),
                draft_version_id=uuid4(),
                prompt="中文科学课探究活动竖版海报",
                request_fingerprint="f" * 64,
                unrestricted_prompt_length=True,
            )
        )

    assert models.image_model == LOCAL_INFOGRAPHIC_IMAGE_MODEL == "gpt-image-2.5-sunburst"
    assert requests == [
        {
            "model": "gpt-image-2.5-sunburst",
            "prompt": "中文科学课探究活动竖版海报",
            "size": "1152x2048",
            "response_format": "url",
        }
    ]
    assert result.model == "gpt-image-2.5-sunburst"
    assert (result.width, result.height, result.attempts) == (1152, 2048, 1)
