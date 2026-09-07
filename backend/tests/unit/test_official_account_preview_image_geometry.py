from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from typing import Literal, cast
from uuid import UUID

import httpx
import pytest
from app.application.ports.image_generation import ImageGenerationRequest, ImageReference
from app.core.errors import (
    ImageOutputValidationError,
    ImageProviderTimeoutError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from app.domain.image_provider_input import (
    IMAGE_REFERENCE_INPUT_V2,
    normalize_image_provider_reference,
)
from app.infrastructure.ai.image_generation import (
    DeterministicFakeImageGenerator,
    OpenAICompatibleImageGenerator,
    ToApisImageGenerator,
)
from PIL import Image
from pydantic import SecretStr

_OutputSize = Literal["1024x1024", "1536x1024"]
_ROUTES = ("raster", "base64", "url", "task_base64", "task_url")
_GENERATE_PATH = "/v1/images/generations"
_TASK_PATH = "/v1/images/tasks/geometry-task"
_OUTPUT_PATH = "/output-image"
_OUTPUT_URL = f"https://cdn.example.com{_OUTPUT_PATH}"


def _request(output_size: _OutputSize = "1024x1024") -> ImageGenerationRequest:
    return ImageGenerationRequest(
        run_id=UUID(int=1),
        draft_version_id=UUID(int=2),
        prompt="A science education scene illustration",
        request_fingerprint=f"preview-{output_size}",
        output_size=output_size,
    )


def _raster(width: int, height: int, media_type: str = "image/png") -> bytes:
    output = BytesIO()
    with Image.new("RGB", (width, height), (35, 100, 155)) as image:
        image.save(output, format=media_type.split("/", 1)[1].upper())
    return output.getvalue()


async def _public_resolver(_host: str) -> list[str]:
    return ["93.184.216.34"]


def _comfly(client: httpx.AsyncClient) -> OpenAICompatibleImageGenerator:
    return OpenAICompatibleImageGenerator(
        client=client,
        base_url="https://ai.comfly.org",
        api_key=SecretStr("test-key"),
        max_attempts=1,
        initial_poll_seconds=0,
        poll_interval_seconds=0,
        resolver=_public_resolver,
    )


def _response_for_route(
    request: httpx.Request,
    *,
    route: str,
    body: bytes,
    media_type: str,
) -> httpx.Response:
    if request.url.path == _OUTPUT_PATH:
        return httpx.Response(200, headers={"content-type": media_type}, content=body)
    if route == "raster":
        return httpx.Response(200, headers={"content-type": media_type}, content=body)
    if route.startswith("task_") and request.url.path == _GENERATE_PATH:
        return httpx.Response(
            200, json={"data": {"task_id": "geometry-task", "status": "IN_PROGRESS"}}
        )
    entry = (
        {"url": _OUTPUT_URL}
        if route.endswith("url")
        else {"b64_json": base64.b64encode(body).decode("ascii")}
    )
    if route.startswith("task_"):
        return httpx.Response(
            200,
            json={
                "data": {
                    "task_id": "geometry-task",
                    "status": "SUCCESS",
                    "data": {"data": [entry]},
                }
            },
        )
    return httpx.Response(200, json={"data": [entry]})


def _expected_paths(route: str) -> list[str]:
    return (
        [_GENERATE_PATH]
        + ([_TASK_PATH] if route.startswith("task_") else [])
        + ([_OUTPUT_PATH] if route.endswith("url") else [])
    )


@pytest.mark.parametrize(("output_size", "width"), [("1024x1024", 1024), ("1536x1024", 1536)])
@pytest.mark.parametrize("route", _ROUTES)
@pytest.mark.parametrize("media_type", ["image/png", "image/jpeg", "image/webp"])
async def test_comfly_returns_exact_native_geometry_and_bytes_for_every_route(
    output_size: _OutputSize, width: int, route: str, media_type: str
) -> None:
    body = _raster(width, 1024, media_type)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response_for_route(request, route=route, body=body, media_type=media_type)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _comfly(client).generate(_request(output_size))

    assert [request.url.path for request in requests] == _expected_paths(route)
    assert sum(request.method == "POST" for request in requests) == 1
    assert json.loads(requests[0].content) == {
        "model": "gpt-image-2",
        "prompt": "A science education scene illustration",
        "size": output_size,
        "response_format": "url",
    }
    assert requests[0].headers["Idempotency-Key"] == f"preview-{output_size}"
    assert (result.width, result.height, result.media_type, result.attempts) == (
        width,
        1024,
        media_type,
        1,
    )
    assert result.image_bytes == body
    assert result.request_fingerprint == f"preview-{output_size}"
    assert result.provider_task_id == ("geometry-task" if route.startswith("task_") else None)
    with Image.open(BytesIO(result.image_bytes)) as image:
        image.load()
        assert image.size == (width, 1024)


@pytest.mark.parametrize(
    ("output_size", "returned_dimensions"),
    [
        ("1024x1024", (1536, 1024)),
        ("1536x1024", (1024, 1024)),
        ("1536x1024", (1024, 1536)),
        ("1536x1024", (1535, 1024)),
    ],
)
@pytest.mark.parametrize("route", _ROUTES)
async def test_comfly_rejects_mismatched_geometry_without_resizing_or_fallback(
    output_size: _OutputSize, returned_dimensions: tuple[int, int], route: str
) -> None:
    body = _raster(*returned_dimensions)
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return _response_for_route(request, route=route, body=body, media_type="image/png")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageOutputValidationError) as error:
            await _comfly(client).generate(_request(output_size))

    assert error.value.reason == "image_dimensions_invalid"
    assert not error.value.retryable
    assert paths == _expected_paths(route)


@pytest.mark.parametrize("route", _ROUTES)
async def test_comfly_requires_actual_decodable_pixels_after_matching_header_geometry(
    route: str,
) -> None:
    body = _raster(1536, 1024)[:33]  # Valid PNG signature and IHDR, no pixel data.
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return _response_for_route(request, route=route, body=body, media_type="image/png")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ImageOutputValidationError) as error:
            await _comfly(client).generate(_request("1536x1024"))

    assert error.value.reason == "image_raster_signature_invalid"
    assert paths == _expected_paths(route)


@pytest.mark.parametrize("provider", ["comfly", "toapis", "fake"])
@pytest.mark.parametrize("output_size", ["auto", "1024x1536", "2048x2048", "", None, 1536, []])
async def test_unsupported_request_sizes_fail_before_any_provider_work(
    provider: str, output_size: object
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("unsupported output size must not upload, generate, poll, or download")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator = {
            "comfly": _comfly(client),
            "toapis": ToApisImageGenerator(
                client=client, base_url="https://toapis.com", api_key=SecretStr("test-key")
            ),
            "fake": DeterministicFakeImageGenerator(),
        }[provider]
        request = replace(
            _request(),
            output_size=cast(_OutputSize, output_size),
            reference_image=_raster(32, 32),
        )
        with pytest.raises(ImageOutputValidationError) as error:
            await generator.generate(request)
    assert error.value.reason == "image_dimensions_invalid"


@pytest.mark.parametrize("provider", ["toapis", "fake"])
async def test_square_only_providers_reject_landscape_before_reference_upload(
    provider: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("landscape is unsupported by this provider profile")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator = (
            ToApisImageGenerator(
                client=client, base_url="https://toapis.com", api_key=SecretStr("test-key")
            )
            if provider == "toapis"
            else DeterministicFakeImageGenerator()
        )
        with pytest.raises(ImageOutputValidationError) as error:
            await generator.generate(
                replace(_request("1536x1024"), reference_image=_raster(32, 32))
            )
    assert error.value.reason == "image_dimensions_invalid"


async def test_landscape_keeps_exact_versioned_reference_normalization() -> None:
    reference_body = _raster(640, 480, "image/jpeg")
    normalized = normalize_image_provider_reference(reference_body)
    reference = ImageReference(
        role="approved_ip_reference",
        asset_id="reference-asset",
        filename="reference.jpg",
        sha256=sha256(reference_body).hexdigest(),
        image_bytes=reference_body,
        input_normalization_version=IMAGE_REFERENCE_INPUT_V2,
        provider_input_sha256=normalized.sha256,
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, headers={"content-type": "image/png"}, content=_raster(1536, 1024)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _comfly(client).generate(replace(_request("1536x1024"), references=(reference,)))

    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert payload["size"] == "1536x1024"
    assert payload["image"] == [
        "data:image/png;base64," + base64.b64encode(normalized.image_png).decode("ascii")
    ]
    with Image.open(BytesIO(normalized.image_png)) as image:
        assert image.size == (640, 480)


async def test_concurrent_square_and_landscape_requests_keep_their_own_geometry() -> None:
    square_started = asyncio.Event()
    landscape_returned = asyncio.Event()
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        size = json.loads(request.content)["size"]
        requests.append(size)
        if size == "1024x1024":
            square_started.set()
            await landscape_returned.wait()
            body = _raster(1024, 1024)
        else:
            await square_started.wait()
            body = _raster(1536, 1024)
            landscape_returned.set()
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(body).decode()}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator = _comfly(client)
        square, landscape = await asyncio.wait_for(
            asyncio.gather(
                generator.generate(_request()), generator.generate(_request("1536x1024"))
            ),
            timeout=5,
        )
    assert (square.width, square.height) == (1024, 1024)
    assert (landscape.width, landscape.height) == (1536, 1024)
    assert requests == ["1024x1024", "1536x1024"]


@pytest.mark.parametrize("route", ["url", "task_url"])
@pytest.mark.parametrize("failure", ["private_dns", "redirect"])
async def test_landscape_download_keeps_dns_and_no_redirect_guards(
    route: str, failure: str
) -> None:
    paths: list[str] = []
    resolved_hosts: list[str] = []

    async def resolver(host: str) -> list[str]:
        resolved_hosts.append(host)
        return ["127.0.0.1"] if failure == "private_dns" else ["93.184.216.34"]

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == _OUTPUT_PATH:
            return httpx.Response(302, headers={"location": "https://cdn.example.com/redirected"})
        if request.url.path == "/redirected":
            pytest.fail("the adapter must disable client redirect following")
        return _response_for_route(request, route=route, body=b"", media_type="image/png")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        generator = OpenAICompatibleImageGenerator(
            client=client,
            base_url="https://ai.comfly.org",
            api_key=SecretStr("test-key"),
            max_attempts=1,
            initial_poll_seconds=0,
            resolver=resolver,
        )
        with pytest.raises(ImageOutputValidationError) as error:
            await generator.generate(_request("1536x1024"))
    assert resolved_hosts == ["cdn.example.com"]
    expected_paths = _expected_paths(route)
    if failure == "private_dns":
        expected_paths.pop()
    assert paths == expected_paths
    assert error.value.reason == (
        "image_download_address_invalid"
        if failure == "private_dns"
        else "image_download_url_invalid"
    )


@pytest.mark.parametrize("failure", ["rate_limit", "unavailable", "timeout"])
async def test_one_attempt_landscape_does_not_retry_generation_on_transport_failure(
    failure: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(429 if failure == "rate_limit" else 503)

    expected_error = {
        "rate_limit": ProviderRateLimitError,
        "unavailable": ProviderUnavailableError,
        "timeout": ImageProviderTimeoutError,
    }[failure]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(expected_error):
            await _comfly(client).generate(_request("1536x1024"))
    assert len(requests) == 1
    assert requests[0].url.path == _GENERATE_PATH
