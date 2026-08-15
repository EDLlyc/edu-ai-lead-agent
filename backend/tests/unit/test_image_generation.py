# ruff: noqa: RUF001
from __future__ import annotations

import base64
import json
from io import BytesIO
from uuid import uuid4

import httpx
import pytest
from app.application.ports.image_generation import ImageGenerationRequest, ImageReference
from app.core.config import Settings
from app.core.errors import (
    ImageOutputValidationError,
    ImageProviderQuotaError,
    ImageProviderRejectedError,
    ProviderAuthenticationError,
)
from app.image_live_smoke import _prompt_for_profile
from app.infrastructure.ai.image_generation import (
    DeterministicFakeImageGenerator,
    OpenAICompatibleImageGenerator,
    ToApisImageGenerator,
    _generation_payload,
    _solid_png,
)
from PIL import Image
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


@pytest.mark.asyncio
async def test_toapis_single_reference_fallback_is_explicit_and_keeps_ordered_first_asset() -> None:
    image = _solid_png("toapis-fallback", "result")
    uploaded: list[bytes] = []
    generation_payload: dict[str, object] | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal generation_payload
        if request.url.path == "/v1/uploads/images":
            uploaded.append(request.content)
            return httpx.Response(
                200, json={"id": "upload-fallback", "url": "https://files.toapis.com/u/1"}
            )
        if request.url.path == "/v1/images/generations":
            generation_payload = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "task_id": "fallback-task",
                    "status": "completed",
                    "result": {"data": [{"url": "https://files.toapis.com/i/1"}]},
                },
            )
        if request.url.path == "/v1/images/generations/fallback-task":
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

    first = _solid_png("first-reference", "approved")
    second = _solid_png("second-reference", "approved")
    request = ImageGenerationRequest(
        uuid4(),
        uuid4(),
        "parent-facing science illustration",
        "fallback-fingerprint",
        references=(
            ImageReference("identity_reference", "asset-first", "first.png", "a" * 64, first),
            ImageReference("action_reference", "asset-second", "second.png", "b" * 64, second),
        ),
        reference_mode="single_fallback",
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator = ToApisImageGenerator(
            client=client,
            base_url="https://toapis.com",
            api_key=SecretStr("test-key"),
            initial_poll_seconds=0,
            poll_interval_seconds=0,
            sleep=lambda _seconds: __import__("asyncio").sleep(0),
        )
        result = await generator.generate(request)

    assert result.image_bytes == image
    assert len(uploaded) == 1
    assert first in uploaded[0]
    assert second not in uploaded[0]
    assert generation_payload is not None
    assert generation_payload["reference_images"] == ["https://files.toapis.com/u/1"]


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


def _comfly_generator(
    client: httpx.AsyncClient, **overrides: object
) -> OpenAICompatibleImageGenerator:
    options: dict[str, object] = {
        "client": client,
        "base_url": "https://ai.comfly.org",
        "api_key": SecretStr("test-key"),
        "initial_poll_seconds": 0,
        "poll_interval_seconds": 0,
        "sleep": lambda _seconds: __import__("asyncio").sleep(0),
        "resolver": _public_resolver,
    }
    options.update(overrides)
    return OpenAICompatibleImageGenerator(**options)  # type: ignore[arg-type]


async def _public_resolver(_host: str) -> list[str]:
    return ["93.184.216.34"]


def _image_request(
    reference_image: bytes | None = None,
    prompt: str = "parent-facing science illustration",
) -> ImageGenerationRequest:
    return ImageGenerationRequest(
        uuid4(),
        uuid4(),
        prompt,
        "comfly-fingerprint",
        reference_image,
        "reference.png" if reference_image is not None else None,
    )


def _direct_raster(media_type: str, *, webp_lossless: bool = False) -> bytes:
    image = Image.new("RGB", (1024, 1024), (37, 97, 158))
    output = BytesIO()
    options: dict[str, str | bool] = {
        "format": {
            "image/png": "PNG",
            "image/jpeg": "JPEG",
            "image/webp": "WEBP",
        }[media_type]
    }
    if media_type == "image/webp":
        options["lossless"] = webp_lossless
    image.save(output, **options)
    return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_type", "webp_lossless"),
    [
        ("image/png", False),
        ("image/jpeg", False),
        ("image/webp", False),
        ("image/webp", True),
    ],
)
async def test_comfly_accepts_direct_raster_creation_response(
    media_type: str,
    webp_lossless: bool,
) -> None:
    image = _direct_raster(media_type, webp_lossless=webp_lossless)
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, headers={"content-type": media_type}, content=image)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _comfly_generator(client).generate(_image_request())

    assert seen_paths == ["/v1/images/generations"]
    assert result.image_bytes == image
    assert (result.width, result.height, result.media_type) == (1024, 1024, media_type)


@pytest.mark.asyncio
async def test_comfly_rejects_invalid_direct_raster_without_json_parsing() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=b"not-an-image",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageOutputValidationError) as raised:
            await _comfly_generator(client).generate(_image_request())

    assert raised.value.reason == "image_raster_signature_invalid"


@pytest.mark.asyncio
async def test_comfly_rejects_oversized_direct_raster() -> None:
    image = _direct_raster("image/png")
    assert len(image) > 1_024

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "image/png; charset=binary"},
            content=image,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageOutputValidationError) as raised:
            await _comfly_generator(client, max_download_bytes=1_024).generate(_image_request())

    assert raised.value.reason == "image_download_too_large"


@pytest.mark.asyncio
async def test_comfly_non_raster_non_json_response_is_rejected_with_safe_diagnostics() -> None:
    raw_marker = "PRIVATE-COMFLY-RESPONSE"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=raw_marker.encode(),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageProviderRejectedError) as raised:
            await _comfly_generator(client).generate(_image_request())

    assert raised.value.http_status == 200
    assert raised.value.response_kind == "other"
    assert raw_marker not in str(raised.value)
    assert raw_marker not in repr(raised.value)


@pytest.mark.asyncio
async def test_comfly_malformed_json_envelope_has_only_safe_response_diagnostics() -> None:
    raw_marker = "PRIVATE-COMFLY-JSON"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"data": [{"detail": raw_marker}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageProviderRejectedError) as raised:
            await _comfly_generator(client).generate(_image_request())

    assert raised.value.http_status == 200
    assert raised.value.response_kind == "json"
    assert raw_marker not in str(raised.value)
    assert raw_marker not in repr(raised.value)


@pytest.mark.asyncio
async def test_comfly_direct_url_maps_documented_payload_and_downloads_one_image() -> None:
    image = _solid_png("comfly", "direct-url")
    seen_payload: dict[str, object] | None = None
    seen_auth: str | None = None
    seen_idempotency_key: str | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_payload, seen_auth, seen_idempotency_key
        if request.url.path == "/v1/images/generations":
            seen_auth = request.headers.get("authorization")
            seen_idempotency_key = request.headers.get("idempotency-key")
            seen_payload = json.loads(request.content)
            return httpx.Response(
                200,
                json={"created": 1, "data": [{"url": "https://images.comfly.org/result.png"}]},
            )
        if request.url.host == "images.comfly.org":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=image)
        return httpx.Response(404)

    reference = _solid_png("reference", "approved")

    resolved_hosts: list[str] = []

    async def resolver(host: str) -> list[str]:
        resolved_hosts.append(host)
        return ["93.184.216.34"]

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _comfly_generator(client, resolver=resolver).generate(
            _image_request(reference)
        )

    assert result.provider == "comfly"
    assert result.provider_task_id is None
    assert result.provider_upload_id is None
    assert result.image_bytes == image
    assert resolved_hosts == ["images.comfly.org"]
    assert (result.width, result.height, result.media_type) == (1024, 1024, "image/png")
    assert seen_auth == "Bearer test-key"
    assert seen_idempotency_key == "comfly-fingerprint"
    assert seen_payload is not None
    assert seen_payload["model"] == "gpt-image-2"
    assert seen_payload["size"] == "1024x1024"
    assert seen_payload["response_format"] == "b64_json"
    assert "aspect_ratio" not in seen_payload
    assert seen_payload["prompt"] == "parent-facing science illustration"
    image_values = seen_payload["image"]
    assert isinstance(image_values, list) and len(image_values) == 1
    assert isinstance(image_values[0], str) and image_values[0].startswith("data:image/png;base64,")
    assert base64.b64decode(image_values[0].split(",", 1)[1]) == reference


@pytest.mark.asyncio
async def test_comfly_sends_ordered_multi_reference_images() -> None:
    image = _solid_png("comfly", "multi-reference")
    seen_payload: dict[str, object] | None = None
    first = _solid_png("multi-first", "approved")
    second = _solid_png("multi-second", "approved")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_payload
        if request.url.path == "/v1/images/generations":
            seen_payload = json.loads(request.content)
            return httpx.Response(
                200,
                json={"data": [{"url": "https://images.comfly.org/multi.png"}]},
            )
        if request.url.host == "images.comfly.org":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=image)
        return httpx.Response(404)

    request = ImageGenerationRequest(
        uuid4(),
        uuid4(),
        "parent-facing science illustration",
        "multi-fingerprint",
        references=(
            ImageReference("identity_reference", "asset-first", "first.png", "a" * 64, first),
            ImageReference("action_reference", "asset-second", "second.png", "b" * 64, second),
        ),
        reference_mode="multi_reference",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _comfly_generator(client).generate(request)

    assert result.image_bytes == image
    assert seen_payload is not None
    encoded = seen_payload["image"]
    assert isinstance(encoded, list)
    assert [base64.b64decode(value.split(",", 1)[1]) for value in encoded] == [first, second]


@pytest.mark.asyncio
async def test_comfly_output_host_observer_can_stop_before_url_download() -> None:
    observed_hosts: list[str] = []
    seen_paths: list[str] = []

    def observe(hostname: str) -> bool:
        observed_hosts.append(hostname)
        return False

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/v1/images/generations":
            return httpx.Response(
                200,
                json={"data": [{"url": "https://IMAGES.comfly.org./result.png?signature=secret"}]},
            )
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageOutputValidationError):
            await _comfly_generator(client, output_host_observer=observe).generate(_image_request())

    assert observed_hosts == ["images.comfly.org"]
    assert seen_paths == ["/v1/images/generations"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_url",
    [
        "https://bad-.example/result.png",
        "https://cdn..example/result.png",
    ],
)
async def test_comfly_output_host_observer_rejects_invalid_dns_labels(unsafe_url: str) -> None:
    observed_hosts: list[str] = []

    def observe(hostname: str) -> bool:
        observed_hosts.append(hostname)
        return False

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"data": [{"url": unsafe_url}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageOutputValidationError):
            await _comfly_generator(client, output_host_observer=observe).generate(_image_request())

    assert observed_hosts == []


@pytest.mark.asyncio
async def test_comfly_output_host_observer_skips_base64_and_malformed_urls() -> None:
    observed_hosts: list[str] = []

    def observe(hostname: str) -> bool:
        observed_hosts.append(hostname)
        return True

    image = _solid_png("comfly", "base64-no-host")

    def base64_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(image).decode("ascii")}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(base64_handler)) as client:
        result = await _comfly_generator(client, output_host_observer=observe).generate(
            _image_request()
        )

    assert result.image_bytes == image
    assert observed_hosts == []

    def malformed_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"url": "https://images.comfly.org/result.png#fragment"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(malformed_handler)) as client:
        with pytest.raises(ImageOutputValidationError):
            await _comfly_generator(client, output_host_observer=observe).generate(_image_request())

    assert observed_hosts == []

    def unsafe_host_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"url": "https://cdn.\x1bexample/result.png"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(unsafe_host_handler)) as client:
        with pytest.raises(ImageOutputValidationError):
            await _comfly_generator(client, output_host_observer=observe).generate(_image_request())

    assert observed_hosts == []


@pytest.mark.asyncio
async def test_comfly_downloads_public_signed_cdn_url_without_a_host_allowlist() -> None:
    image = _solid_png("comfly", "public-cdn")
    resolved_hosts: list[str] = []
    downloaded_urls: list[str] = []
    signed_url = "https://cdn.example/result.png?Expires=fixture&X-Amz-Signature=fixture"

    async def resolver(host: str) -> list[str]:
        resolved_hosts.append(host)
        return ["93.184.216.34"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/images/generations":
            return httpx.Response(200, json={"data": [{"url": signed_url}]})
        if request.url.host == "cdn.example":
            downloaded_urls.append(str(request.url))
            return httpx.Response(200, headers={"content-type": "image/png"}, content=image)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _comfly_generator(client, resolver=resolver).generate(_image_request())

    assert result.image_bytes == image
    assert (result.width, result.height, result.media_type) == (1024, 1024, "image/png")
    assert resolved_hosts == ["cdn.example"]
    assert downloaded_urls == [signed_url]


@pytest.mark.asyncio
async def test_comfly_accepts_generic_cdn_content_type_after_raster_verification() -> None:
    image = _solid_png("comfly", "generic-content-type")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/images/generations":
            return httpx.Response(
                200,
                json={"data": [{"url": "https://cdn.example/result.png"}]},
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/octet-stream"},
            content=image,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _comfly_generator(client).generate(_image_request())

    assert result.image_bytes == image
    assert result.media_type == "image/png"


@pytest.mark.asyncio
async def test_comfly_rejects_explicit_media_type_that_conflicts_with_verified_bytes() -> None:
    image = _solid_png("comfly", "content-type-mismatch")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/images/generations":
            return httpx.Response(
                200,
                json={"data": [{"url": "https://cdn.example/result.png"}]},
            )
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=image)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageOutputValidationError) as raised:
            await _comfly_generator(client).generate(_image_request())

    assert raised.value.reason == "image_raster_signature_invalid"


@pytest.mark.asyncio
async def test_comfly_persists_a_safe_reason_for_invalid_raster_bytes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/images/generations":
            return httpx.Response(
                200,
                json={"data": [{"url": "https://cdn.example/result.png"}]},
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/octet-stream"},
            content=b"not-an-image",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageOutputValidationError) as raised:
            await _comfly_generator(client).generate(_image_request())

    assert raised.value.reason == "image_raster_signature_invalid"


@pytest.mark.asyncio
async def test_comfly_direct_base64_response_is_normalized_without_provider_url() -> None:
    image = _solid_png("comfly", "base64")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(image).decode("ascii")}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _comfly_generator(client).generate(_image_request())

    assert result.image_bytes == image
    assert result.media_type == "image/png"


@pytest.mark.asyncio
async def test_comfly_accepts_url_with_empty_base64_placeholder() -> None:
    image = _solid_png("comfly", "url-with-empty-base64")

    async def resolver(_host: str) -> list[str]:
        return ["93.184.216.34"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/images/generations":
            return httpx.Response(
                200,
                json={
                    "created": 1,
                    "data": [
                        {
                            "url": "https://cdn.example/result.png",
                            "b64_json": "",
                            "revised_prompt": "provider metadata",
                        }
                    ],
                    "model": "gpt-image-2",
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                },
            )
        return httpx.Response(200, headers={"content-type": "image/png"}, content=image)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _comfly_generator(client, resolver=resolver).generate(_image_request())

    assert result.image_bytes == image
    assert result.media_type == "image/png"


@pytest.mark.asyncio
async def test_comfly_accepts_base64_with_empty_url_placeholder() -> None:
    image = _solid_png("comfly", "base64-with-empty-url")

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={"data": [{"url": "", "b64_json": base64.b64encode(image).decode("ascii")}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _comfly_generator(client).generate(_image_request())

    assert result.image_bytes == image
    assert result.media_type == "image/png"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry",
    [
        {"url": "https://cdn.example/result.png", "b64_json": "not-empty"},
        {"url": "", "b64_json": ""},
        {"url": 123, "b64_json": "valid-but-must-reject"},
        {"url": "https://cdn.example/result.png", "b64_json": 123},
        {"url": "https://cdn.example/result.png", "b64_json": None},
        {"url": None, "b64_json": "valid-but-must-reject"},
    ],
)
async def test_comfly_rejects_ambiguous_or_invalid_image_placeholders(
    entry: dict[str, object],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"data": [entry]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageProviderRejectedError):
            await _comfly_generator(client).generate(_image_request())


@pytest.mark.asyncio
async def test_comfly_async_task_polls_tasks_route_and_accepts_completed_result() -> None:
    image = _solid_png("comfly", "async")
    poll_count = 0
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        paths.append(request.url.path)
        if request.url.path == "/v1/images/generations":
            return httpx.Response(200, json={"id": "task-1", "status": "queued"})
        if request.url.path == "/v1/images/tasks/task-1":
            poll_count += 1
            if poll_count == 1:
                return httpx.Response(200, json={"id": "task-1", "status": "processing"})
            return httpx.Response(
                200,
                json={
                    "id": "task-1",
                    "status": "completed",
                    "data": [{"b64_json": base64.b64encode(image).decode("ascii")}],
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _comfly_generator(client).generate(_image_request())

    assert result.provider_task_id == "task-1"
    assert result.image_bytes == image
    assert paths == [
        "/v1/images/generations",
        "/v1/images/tasks/task-1",
        "/v1/images/tasks/task-1",
    ]


@pytest.mark.asyncio
async def test_comfly_nested_task_envelope_is_polled_without_treating_metadata_as_image() -> None:
    image = _solid_png("comfly", "nested-task")
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v1/images/generations":
            return httpx.Response(200, json={"data": {"id": "nested-task-1", "status": "queued"}})
        if request.url.path == "/v1/images/tasks/nested-task-1":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "nested-task-1",
                        "status": "completed",
                        "url": "https://images.comfly.org/nested.png",
                    }
                },
            )
        if request.url.host == "images.comfly.org":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=image)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _comfly_generator(client).generate(_image_request())

    assert result.provider_task_id == "nested-task-1"
    assert result.image_bytes == image
    assert paths == [
        "/v1/images/generations",
        "/v1/images/tasks/nested-task-1",
        "/nested.png",
    ]


@pytest.mark.asyncio
async def test_comfly_documented_task_envelope_extracts_nested_base64_result() -> None:
    image = _solid_png("comfly", "documented-task")
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v1/images/generations":
            return httpx.Response(
                200,
                json={
                    "code": "success",
                    "data": {"task_id": "documented-task-1", "status": "IN_PROGRESS"},
                },
            )
        if request.url.path == "/v1/images/tasks/documented-task-1":
            return httpx.Response(
                200,
                json={
                    "code": "success",
                    "data": {
                        "task_id": "documented-task-1",
                        "status": "SUCCESS",
                        "data": {"data": [{"b64_json": base64.b64encode(image).decode("ascii")}]},
                    },
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _comfly_generator(client).generate(_image_request())

    assert result.provider_task_id == "documented-task-1"
    assert result.image_bytes == image
    assert paths == [
        "/v1/images/generations",
        "/v1/images/tasks/documented-task-1",
    ]


@pytest.mark.asyncio
async def test_comfly_rate_limit_retries_but_authentication_does_not() -> None:
    image = _solid_png("comfly", "retry")
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"error": {"message": "private-rate-limit"}})
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(image).decode("ascii")}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _comfly_generator(client, max_attempts=2).generate(_image_request())

    assert attempts == 2
    assert result.image_bytes == image

    auth_attempts = 0

    def auth_handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_attempts
        auth_attempts += 1
        return httpx.Response(401, json={"error": {"message": "private-auth-body"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(auth_handler)) as client:
        with pytest.raises(ProviderAuthenticationError) as raised:
            await _comfly_generator(client, max_attempts=3).generate(_image_request())

    assert auth_attempts == 1
    assert "private-auth-body" not in str(raised.value)
    assert "private-auth-body" not in repr(raised.value)


@pytest.mark.asyncio
async def test_comfly_quota_response_is_non_retryable_and_redacted() -> None:
    raw_marker = "PRIVATE-COMFLY-QUOTA-RESPONSE"
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            json={"code": "insufficient_quota", "message": raw_marker, "data": {"raw": raw_marker}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageProviderQuotaError) as raised:
            await _comfly_generator(client, max_attempts=3).generate(_image_request())

    assert attempts == 1
    assert raised.value.retryable is False
    assert raw_marker not in str(raised.value)
    assert raw_marker not in repr(raised.value)


@pytest.mark.asyncio
async def test_comfly_rejects_non_public_image_url_and_oversized_provider_body() -> None:
    seen_paths: list[str] = []

    async def private_resolver(_host: str) -> list[str]:
        return ["127.0.0.1"]

    def untrusted_handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={"data": [{"url": "https://evil.example/result.png"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(untrusted_handler)) as client:
        with pytest.raises(ImageOutputValidationError):
            await _comfly_generator(client, resolver=private_resolver).generate(_image_request())

    assert seen_paths == ["/v1/images/generations"]

    def oversized_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{" + b"x" * 2_000 + b"}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(oversized_handler)) as client:
        with pytest.raises(ImageProviderRejectedError) as raised:
            await _comfly_generator(client, max_provider_response_bytes=1_024).generate(
                _image_request()
            )
    assert raised.value.code == "image_provider_rejected"


@pytest.mark.asyncio
async def test_comfly_rejects_non_global_dns_answers_before_download() -> None:
    seen_paths: list[str] = []
    observed_hosts: list[str] = []

    async def private_resolver(_host: str) -> list[str]:
        return ["198.18.1.161", "93.184.216.34"]

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/v1/images/generations":
            return httpx.Response(
                200,
                json={"data": [{"url": "https://cdn.example/private-result.png"}]},
            )
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=_solid_png("x", "y"),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageOutputValidationError):
            await _comfly_generator(
                client,
                resolver=private_resolver,
                output_host_observer=lambda hostname: observed_hosts.append(hostname) or True,
            ).generate(_image_request())

    assert seen_paths == ["/v1/images/generations"]
    assert observed_hosts == ["cdn.example"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_url", ["https://images.comfly.org/result.png#", "https://[::1"])
async def test_comfly_rejects_malformed_output_urls_with_typed_error(bad_url: str) -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/v1/images/generations":
            return httpx.Response(200, json={"data": [{"url": bad_url}]})
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"unexpected")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageOutputValidationError):
            await _comfly_generator(client).generate(_image_request())

    assert seen_paths == ["/v1/images/generations"]


@pytest.mark.asyncio
async def test_comfly_maps_dns_resolution_failure_to_typed_output_error() -> None:
    seen_paths: list[str] = []

    async def failing_resolver(_host: str) -> list[str]:
        raise OSError("resolver unavailable")

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(
            200,
            json={"data": [{"url": "https://cdn.example/unresolved-result.png"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageOutputValidationError):
            await _comfly_generator(client, resolver=failing_resolver).generate(_image_request())

    assert seen_paths == ["/v1/images/generations"]


@pytest.mark.asyncio
async def test_comfly_rejects_multiple_image_representations_in_one_response() -> None:
    image = _solid_png("comfly", "multiple")

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "data": [{"b64_json": base64.b64encode(image).decode("ascii")}],
                "result": {"data": [{"b64_json": base64.b64encode(image).decode("ascii")}]},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageProviderRejectedError):
            await _comfly_generator(client).generate(_image_request())


@pytest.mark.asyncio
async def test_comfly_maps_unsafe_prompt_to_typed_output_validation_error() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    ) as client:
        with pytest.raises(ImageOutputValidationError):
            await _comfly_generator(client).generate(_image_request(prompt="为儿童生成血腥画面"))


@pytest.mark.asyncio
async def test_comfly_rejects_redirect_and_whitespace_result_urls() -> None:
    redirect_calls = 0

    def redirect_handler(request: httpx.Request) -> httpx.Response:
        nonlocal redirect_calls
        redirect_calls += 1
        return httpx.Response(302, headers={"location": "https://ai.comfly.org/result.png"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect_handler)) as client:
        with pytest.raises(ImageProviderRejectedError):
            await _comfly_generator(client).generate(_image_request())
    assert redirect_calls == 1

    def whitespace_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"url": "https://images.comfly.org/result image.png"}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(whitespace_handler)) as client:
        with pytest.raises(ImageOutputValidationError):
            await _comfly_generator(client).generate(_image_request())


@pytest.mark.asyncio
async def test_comfly_constructor_rejects_non_https_and_line_break_key() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="HTTPS"):
            OpenAICompatibleImageGenerator(
                client=client,
                base_url="http://ai.comfly.org",
                api_key=SecretStr("test-key"),
            )
        with pytest.raises(ValueError, match="HTTPS origin"):
            OpenAICompatibleImageGenerator(
                client=client,
                base_url="https://ai.comfly.org/v1",
                api_key=SecretStr("test-key"),
            )
        with pytest.raises(ValueError, match="line breaks"):
            OpenAICompatibleImageGenerator(
                client=client,
                base_url="https://ai.comfly.org",
                api_key=SecretStr("test-key\nwith-newline"),
            )


def test_settings_rejects_a_comfly_base_url_with_an_api_path() -> None:
    with pytest.raises(ValueError, match="HTTPS origin"):
        Settings(
            _env_file=None,
            image_provider_mode="comfly",
            comfly_api_key=SecretStr("test-key"),
            comfly_base_url="https://ai.comfly.org/v1",
        )


def test_settings_do_not_require_a_comfly_output_host_policy() -> None:
    settings = Settings(_env_file=None)

    assert not hasattr(settings, "comfly_output_hosts")
    assert not hasattr(settings, "comfly_allow_public_output_urls")


def test_settings_use_a_provider_friendly_reference_budget_by_default() -> None:
    assert Settings(_env_file=None).image_reference_budget_bytes == 6 * 1024 * 1024


def test_image_provider_defaults_use_bounded_comfly_timeouts_and_retries() -> None:
    settings = Settings(_env_file=None)

    assert settings.image_provider_timeout_seconds == 300.0
    assert settings.image_provider_window_seconds == 300.0
    assert settings.image_max_attempts == 3


def test_settings_accept_the_300_second_comfly_timeout_bounds() -> None:
    settings = Settings(
        _env_file=None,
        image_provider_timeout_seconds=300,
        image_provider_window_seconds=300,
    )

    assert settings.image_provider_timeout_seconds == 300.0
    assert settings.image_provider_window_seconds == 300.0


def test_visual_diversity_defaults_are_bounded_and_disabled() -> None:
    settings = Settings(_env_file=None)

    assert settings.image_diversity_enabled is False
    assert settings.image_diversity_history_days == 7
    assert settings.image_diversity_history_limit == 400
    assert settings.image_similarity_threshold == 6
    assert settings.image_diversity_max_regenerations == 1


def test_visual_diversity_requires_the_reviewed_image_bundle() -> None:
    with pytest.raises(ValueError, match="image generation"):
        Settings(_env_file=None, image_diversity_enabled=True)
    with pytest.raises(ValueError, match="exact image OCR"):
        Settings(
            _env_file=None,
            image_enabled=True,
            image_provider_mode="fake",
            image_diversity_enabled=True,
        )
    with pytest.raises(ValueError, match="reviewed bundle"):
        Settings(
            _env_file=None,
            image_enabled=True,
            image_provider_mode="fake",
            image_diversity_enabled=True,
            image_ocr_enabled=True,
            image_diversity_prompt_version="unreviewed-prompt",
        )
