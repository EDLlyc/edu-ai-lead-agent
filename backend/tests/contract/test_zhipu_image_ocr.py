from __future__ import annotations

import base64
import json
from collections.abc import Callable
from io import BytesIO
from typing import Any

import httpx
import pytest
from app.application.ports.image_validation import ImageTextRecognitionRequest
from app.core.errors import (
    InvalidProviderOutputError,
    ProviderAuthenticationError,
    ProviderIdentityMismatchError,
    ProviderInputLimitError,
    ProviderRateLimitError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.infrastructure.ai.zhipu import ZhipuImageTextRecognizer
from PIL import Image
from pydantic import SecretStr

EXPECTED_TEXT = ("赛先生科学", "人工智能", "理解智能如何学习与反馈")


def _raster(format_name: str = "PNG") -> bytes:
    output = BytesIO()
    Image.new("RGB", (16, 16), (20, 54, 96)).save(output, format=format_name)
    return output.getvalue()


PNG_BODY = _raster()
JPEG_BODY = _raster("JPEG")
WEBP_BODY = _raster("WEBP")


async def _no_sleep(_: float) -> None:
    return None


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    max_attempts: int = 1,
    max_input_bytes: int = 10 * 1024 * 1024,
    max_response_bytes: int = 1024 * 1024,
) -> tuple[ZhipuImageTextRecognizer, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    return (
        ZhipuImageTextRecognizer(
            client=client,
            base_url="https://open.bigmodel.invalid/api/paas/v4",
            api_key=SecretStr("local-contract-secret"),
            model="glm-ocr",
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=3,
            concurrency=1,
            max_attempts=max_attempts,
            max_input_bytes=max_input_bytes,
            max_response_bytes=max_response_bytes,
            sleep=_no_sleep,
        ),
        client,
    )


@pytest.mark.parametrize(
    ("max_input_bytes", "max_response_bytes", "message"),
    (
        (10 * 1024 * 1024 + 1, 1024 * 1024, "input limit"),
        (10 * 1024 * 1024, 1024 * 1024 + 1, "response limit"),
    ),
)
def test_image_ocr_adapter_rejects_limits_above_the_reviewed_envelope(
    max_input_bytes: int,
    max_response_bytes: int,
    message: str,
) -> None:
    client = httpx.AsyncClient()
    try:
        with pytest.raises(ValueError, match=message):
            ZhipuImageTextRecognizer(
                client=client,
                base_url="https://open.bigmodel.invalid/api/paas/v4",
                api_key=SecretStr("local-contract-secret"),
                model="glm-ocr",
                connect_timeout_seconds=1,
                read_timeout_seconds=2,
                total_timeout_seconds=3,
                concurrency=1,
                max_attempts=1,
                max_input_bytes=max_input_bytes,
                max_response_bytes=max_response_bytes,
            )
    finally:
        import asyncio

        asyncio.run(client.aclose())


def _request(
    image_bytes: bytes = PNG_BODY,
    *,
    media_type: str = "image/png",
    expected_text: tuple[str, ...] = EXPECTED_TEXT,
) -> ImageTextRecognitionRequest:
    return ImageTextRecognitionRequest(
        image_bytes=image_bytes,
        request_fingerprint="controlled-image-ocr-fingerprint",
        expected_text=expected_text,
        media_type=media_type,
        require_order=True,
    )


def _layout_element(
    index: object,
    content: object,
    *,
    bbox: object,
    label: object = "text",
) -> dict[str, object]:
    return {
        "index": index,
        "label": label,
        "bbox_2d": bbox,
        "content": content,
    }


def _response(
    *,
    model: object = "glm-ocr",
    layout_details: object | None = None,
    data_info: object | None = None,
) -> dict[str, object]:
    return {
        "id": "private-provider-request-id",
        "model": model,
        "layout_details": layout_details
        if layout_details is not None
        else [
            _layout_element(3, EXPECTED_TEXT[2], bbox=[0.1, 0.7, 0.9, 0.8]),
            _layout_element(4, "", bbox=[0.2, 0.4, 0.8, 0.6], label="image"),
            _layout_element(1, EXPECTED_TEXT[0], bbox=[0.1, 0.1, 0.9, 0.2]),
            _layout_element(2, EXPECTED_TEXT[1], bbox=[0.1, 0.4, 0.9, 0.5]),
        ],
        "data_info": data_info if data_info is not None else {"num_pages": 1},
        "md_results": "provider markdown must not be projected",
    }


@pytest.mark.parametrize(
    ("image_bytes", "media_type", "expected_prefix"),
    (
        (PNG_BODY, "image/png", "data:image/png;base64,"),
        (JPEG_BODY, "image/jpeg", "data:image/jpeg;base64,"),
    ),
)
@pytest.mark.asyncio
async def test_image_layout_parsing_uses_private_bounded_raster_and_ordered_text(
    image_bytes: bytes,
    media_type: str,
    expected_prefix: str,
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_response(model="GLM-OCR"))

    adapter, client = _adapter(handler)
    async with client:
        result = await adapter.recognize(_request(image_bytes, media_type=media_type))

    payload = captured["payload"]
    assert captured["url"] == "https://open.bigmodel.invalid/api/paas/v4/layout_parsing"
    assert captured["authorization"] == "Bearer local-contract-secret"
    assert isinstance(payload, dict)
    assert payload == {
        "model": "glm-ocr",
        "file": payload["file"],
        "return_crop_images": False,
        "need_layout_visualization": False,
    }
    encoded_file = payload["file"]
    assert isinstance(encoded_file, str)
    assert encoded_file.startswith(expected_prefix)
    assert base64.b64decode(encoded_file.split(",", 1)[1], validate=True) == image_bytes
    assert result.recognized_lines == EXPECTED_TEXT
    assert result.provider == "zhipu"
    assert result.model == "glm-ocr"
    assert result.request_fingerprint == "controlled-image-ocr-fingerprint"
    assert "local-contract-secret" not in repr(result)
    assert "provider markdown" not in repr(result)


@pytest.mark.parametrize(
    "layout_details",
    (
        [_layout_element(0, EXPECTED_TEXT[0], bbox=[0.1, 0.1, 0.9, 0.2])],
        [_layout_element("1", EXPECTED_TEXT[0], bbox=[0.1, 0.1, 0.9, 0.2])],
        [
            _layout_element(1, EXPECTED_TEXT[0], bbox=[0.1, 0.1, 0.9, 0.2]),
            _layout_element(1, EXPECTED_TEXT[1], bbox=[0.1, 0.4, 0.9, 0.5]),
        ],
        [_layout_element(1, EXPECTED_TEXT[0], bbox=[0.1, 0.1, 1.1, 0.2])],
        [_layout_element(1, EXPECTED_TEXT[0], bbox=[0.9, 0.1, 0.1, 0.2])],
        [_layout_element(1, EXPECTED_TEXT[0], bbox=[0.1, True, 0.9, 0.2])],
        [_layout_element(1, EXPECTED_TEXT[0], bbox=[0.1, 0.2, 0.9])],
        [_layout_element(1, EXPECTED_TEXT[0], bbox=[0.1, 0.1, 0.9, 0.2], label="unknown")],
        [_layout_element(1, "unprojected text", bbox=[0.1, 0.1, 0.9, 0.2], label="title")],
        [_layout_element(1, "bad\x00text", bbox=[0.1, 0.1, 0.9, 0.2])],
        [
            _layout_element(
                1,
                "\n".join(f"line-{number}" for number in range(9)),
                bbox=[0.1, 0.1, 0.9, 0.9],
            )
        ],
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_rejects_malformed_layout_without_exposing_body(
    layout_details: object,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=layout_details))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert raised.value.issue_codes == ("invalid_schema",)
    assert "bad\x00text" not in str(raised.value)


@pytest.mark.parametrize(
    "data_info",
    (
        {},
        {"num_pages": 0},
        {"num_pages": 2},
        {"pages": True},
        {"num_pages": 1, "page_count": 2},
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_requires_exactly_one_page(data_info: object) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(data_info=data_info))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError):
            await adapter.recognize(_request())


@pytest.mark.parametrize(
    ("lines", "expected_issue"),
    (
        ((), "missing_visual_text"),
        ((EXPECTED_TEXT[0], EXPECTED_TEXT[2]), "missing_visual_text"),
        ((*EXPECTED_TEXT, "额外文字"), "unexpected_visual_text"),
        (tuple(reversed(EXPECTED_TEXT)), "misordered_visual_text"),
        (
            (EXPECTED_TEXT[0], EXPECTED_TEXT[1], EXPECTED_TEXT[1], EXPECTED_TEXT[2]),
            "duplicate_visual_text",
        ),
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_preserves_existing_exact_text_gate(
    lines: tuple[str, ...],
    expected_issue: str,
) -> None:
    layout = [
        _layout_element(
            index,
            line,
            bbox=[0.1, index / 10, 0.9, index / 10 + 0.05],
        )
        for index, line in enumerate(lines, start=1)
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=layout))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request())

    assert expected_issue in raised.value.issue_codes


@pytest.mark.asyncio
async def test_image_ocr_rejects_wrong_model_identity() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(model="glm-5.2"))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(ProviderIdentityMismatchError):
            await adapter.recognize(_request())


@pytest.mark.parametrize("body", (b"not-json", b"[]", b'{"model":"glm-ocr"}'))
@pytest.mark.asyncio
async def test_image_ocr_rejects_malformed_response_envelopes(body: bytes) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request())
    assert raised.value.issue_codes == ("invalid_schema",)
    assert body.decode("utf-8") not in str(raised.value)


@pytest.mark.parametrize(
    ("image_bytes", "media_type", "max_input_bytes"),
    (
        (WEBP_BODY, "image/webp", 10 * 1024 * 1024),
        (b"not-a-raster", "image/png", 10 * 1024 * 1024),
        (PNG_BODY, "image/png", len(PNG_BODY) - 1),
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_rejects_unsupported_malformed_or_oversized_input_before_http(
    image_bytes: bytes,
    media_type: str,
    max_input_bytes: int,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, client = _adapter(handler, max_input_bytes=max_input_bytes)
    async with client:
        with pytest.raises(ProviderInputLimitError):
            await adapter.recognize(_request(image_bytes, media_type=media_type))
    assert calls == 0


def test_image_ocr_request_rejects_empty_and_non_image_media_before_http() -> None:
    with pytest.raises(ValueError):
        _request(b"")
    with pytest.raises(ValueError):
        _request(b"%PDF-1.7", media_type="application/pdf")


@pytest.mark.asyncio
async def test_image_ocr_response_limit_is_terminal_and_body_free() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": "2048"},
            content=b'{"private":"provider body"}',
        )

    adapter, client = _adapter(handler, max_response_bytes=1024)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request())
    assert raised.value.issue_codes == ("output_limit_exceeded",)
    assert "provider body" not in str(raised.value)


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    (
        (400, ProviderRejectedError),
        (422, ProviderRejectedError),
        (401, ProviderAuthenticationError),
        (403, ProviderAuthenticationError),
        (429, ProviderRateLimitError),
        (500, ProviderUnavailableError),
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_http_failures_are_typed_and_body_free(
    status_code: int,
    error_type: type[Exception],
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": {"message": "private provider body"}})

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(error_type) as raised:
            await adapter.recognize(_request())
    assert "private provider body" not in str(raised.value)


@pytest.mark.asyncio
async def test_image_ocr_timeout_is_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout detail", request=request)

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(ProviderTimeoutError) as raised:
            await adapter.recognize(_request())
    assert "private timeout detail" not in str(raised.value)
