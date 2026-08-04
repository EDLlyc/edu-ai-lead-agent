# ruff: noqa: RUF001
from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from app.application.ports.image_generation import ImageGenerationRequest
from app.core.errors import ImageProviderQuotaError, ProviderAuthenticationError
from app.image_live_smoke import _prompt_for_profile
from app.infrastructure.ai.image_generation import (
    DeterministicFakeImageGenerator,
    ToApisImageGenerator,
    _generation_payload,
    _solid_png,
)
from pydantic import SecretStr


@pytest.mark.asyncio
async def test_fake_image_is_deterministic_and_1024_square() -> None:
    request = ImageGenerationRequest(uuid4(), uuid4(), "面向家长的科学探索插画", "fingerprint")
    first = await DeterministicFakeImageGenerator().generate(request)
    second = await DeterministicFakeImageGenerator().generate(request)
    assert first.image_bytes == second.image_bytes
    assert (first.width, first.height, first.media_type) == (1024, 1024, "image/png")


@pytest.mark.asyncio
async def test_toapis_generation_uploads_polls_and_downloads_without_persisting_url() -> None:
    image = _solid_png("seed", "prompt")
    poll_count = 0
    generation_payload: dict[str, object] | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal generation_payload, poll_count
        if request.url.path == "/v1/uploads/images":
            return httpx.Response(
                200, json={"id": "upload-1", "url": "https://files.toapis.com/u/1"}
            )
        if request.url.path == "/v1/images/generations" and request.method == "POST":
            generation_payload = json.loads(request.content)
            return httpx.Response(200, json={"task_id": "task-1", "status": "queued"})
        if request.url.path == "/v1/images/generations/task-1":
            poll_count += 1
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "result": {"data": [{"url": "https://files.toapis.com/i/1"}]},
                },
            )
        if request.url.host == "files.toapis.com":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=image)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator = ToApisImageGenerator(
            client=client,
            base_url="https://toapis.com",
            api_key=SecretStr("test-key"),
            initial_poll_seconds=0,
            poll_interval_seconds=0,
            sleep=lambda _seconds: __import__("asyncio").sleep(0),
        )
        result = await generator.generate(
            ImageGenerationRequest(
                uuid4(),
                uuid4(),
                "面向家长的科学探索插画",
                "fingerprint",
                _solid_png("reference", "approved"),
                "ref.png",
            )
        )
    assert result.provider_task_id == "task-1"
    assert result.provider_upload_id == "upload-1"
    assert result.image_bytes == image
    assert poll_count == 1
    assert generation_payload is not None
    assert generation_payload["model"] == "gpt-image-2"
    assert generation_payload["resolution"] == "1k"
    assert generation_payload["response_format"] == "url"
    assert generation_payload["reference_images"] == ["https://files.toapis.com/u/1"]
    assert "metadata" not in generation_payload
    assert "image_urls" not in generation_payload


def test_provider_authentication_error_message_is_provider_neutral() -> None:
    error = ProviderAuthenticationError()

    assert str(error) == "provider credentials were rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "provider_code"),
    [(200, "quota_not_enough"), (400, "insufficient_quota")],
)
async def test_toapis_quota_codes_are_non_retryable_and_redact_provider_body(
    status_code: int, provider_code: str
) -> None:
    raw_marker = "PRIVATE-TOAPIS-QUOTA-RESPONSE"
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            status_code,
            request=request,
            json={"code": provider_code, "message": raw_marker, "details": {"raw": raw_marker}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator = ToApisImageGenerator(
            client=client,
            base_url="https://toapis.com",
            api_key=SecretStr("test-key"),
            max_attempts=3,
            initial_poll_seconds=0,
            poll_interval_seconds=0,
            sleep=lambda _seconds: __import__("asyncio").sleep(0),
        )
        with pytest.raises(ImageProviderQuotaError) as raised:
            await generator.generate(
                ImageGenerationRequest(
                    uuid4(), uuid4(), "parent-facing science illustration", "fingerprint"
                )
            )

    assert attempts == 1
    assert raised.value.code == "image_provider_quota_exhausted"
    assert raised.value.retryable is False
    assert raw_marker not in str(raised.value)
    assert raw_marker not in repr(raised.value)
    assert raw_marker not in repr(vars(raised.value))


def test_flux_2_pro_payload_uses_only_flux_profile_fields() -> None:
    payload = _generation_payload(
        model="flux-2-pro",
        prompt="parent-facing science illustration",
        fingerprint="fingerprint",
        upload_url="https://files.toapis.com/u/1",
    )

    assert payload == {
        "model": "flux-2-pro",
        "prompt": "parent-facing science illustration",
        "n": 1,
        "size": "1:1",
        "client_business_id": "fingerprint",
        "metadata": {"resolution": "1K"},
        "image_urls": ["https://files.toapis.com/u/1"],
    }
    assert "resolution" not in payload
    assert "response_format" not in payload
    assert "reference_images" not in payload


def test_gemini_3_pro_official_payload_uses_only_gemini_profile_fields() -> None:
    payload = _generation_payload(
        model="gemini-3-pro-image-preview-official",
        prompt="parent-facing science illustration",
        fingerprint="gemini-fingerprint",
        upload_url="https://files.toapis.com/u/1",
    )

    assert payload == {
        "model": "gemini-3-pro-image-preview-official",
        "prompt": "parent-facing science illustration",
        "n": 1,
        "size": "1:1",
        "client_business_id": "gemini-fingerprint",
        "metadata": {
            "resolution": "1K",
            "thinkingConfig": {"thinkingLevel": "HIGH"},
            "imageOutputOptions": {"mimeType": "image/png"},
        },
        "image_urls": ["https://files.toapis.com/u/1"],
    }
    assert "resolution" not in payload
    assert "response_format" not in payload
    assert "reference_images" not in payload


def test_chinese_smoke_prompt_allows_only_the_requested_visible_text() -> None:
    default_prompt = _prompt_for_profile("default")
    chinese_prompt = _prompt_for_profile("zh")
    required_text = (
        "具身智能",
        "从尝试中学习，在调整中成长",
        "尝试",
        "调整",
        "进步",
        "感知输入",
        "学习进行中",
        "自我纠正",
    )

    assert "no Chinese text" in default_prompt
    assert all(text not in default_prompt for text in required_text)
    assert all(text in chinese_prompt for text in required_text)
    assert "Do not render any English, Latin letters, digits, or any other words" in chinese_prompt
    assert "Preserve Sai Xiansheng and Xiaosai identities" in chinese_prompt


def test_minimal_chinese_smoke_prompt_limits_visible_text_to_four_labels() -> None:
    prompt = _prompt_for_profile("zh_minimal")

    assert all(text in prompt for text in ("具身智能", "尝试", "调整", "进步"))
    assert "Do not render any other Chinese text" in prompt
    assert "English, Latin letters, digits, clothing labels" in prompt
    assert "Preserve both Sai Xiansheng and Xiaosai identities" in prompt


def test_brand_chinese_localization_prompt_preserves_image_and_exact_copy() -> None:
    prompt = _prompt_for_profile("zh_brand_v2")
    exact_strings = (
        "具身智能",
        "在真实体验中学习，在不断调整中成长",
        "小赛在探索中尝试，在反馈中调整。",
        "每一次动手，都让理解更深。",
        "每一次进步，都值得被看见。",
        "守护好奇心 · 锤炼思考力 · 培养创造力",
        "尝试",
        "调整",
        "进步",
        "感知输入",
        "学习进行中",
        "自我纠正",
    )

    assert all(text in prompt for text in exact_strings)
    assert "single edit target, not a loose style reference" in prompt
    assert "Preserve its composition" in prompt
    assert "'Dr.S' and 'AI' may remain unchanged" in prompt
    assert "Do not render any other English or Latin text" in prompt
    assert "Do not change, replace, redesign, or add characters" in prompt
