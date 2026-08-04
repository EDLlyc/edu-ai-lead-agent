from __future__ import annotations

import base64
import json
from typing import Any
from uuid import UUID

import httpx
import pytest
from app.application.ports.brand_knowledge import BrandDocumentOcrRequest
from app.core.errors import (
    BrandOcrIdentityMismatchError,
    BrandOcrInputLimitError,
    BrandOcrInvalidOutputError,
    BrandOcrRateLimitError,
)
from app.domain.value_objects import sha256_bytes
from app.infrastructure.ai.zhipu import ZhipuBrandDocumentOcrModel
from pydantic import SecretStr

VERSION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PDF_BODY = b"%PDF-1.7\nminimal contract fixture"


def _request(body: bytes = PDF_BODY) -> BrandDocumentOcrRequest:
    return BrandDocumentOcrRequest(
        version_id=VERSION_ID,
        input_hash=sha256_bytes(body),
        media_type="application/pdf",
        page_count=2,
        original_bytes=body,
    )


async def _no_sleep(_: float) -> None:
    return None


def _adapter(
    transport: httpx.AsyncBaseTransport,
    *,
    max_attempts: int = 2,
    max_request_bytes: int = 10 * 1024 * 1024,
    max_response_bytes: int = 1024 * 1024,
) -> tuple[ZhipuBrandDocumentOcrModel, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=transport)
    return (
        ZhipuBrandDocumentOcrModel(
            client=client,
            base_url="https://open.bigmodel.invalid/api/paas/v4",
            api_key=SecretStr("local-contract-secret"),
            model="glm-ocr",
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=3,
            concurrency=1,
            max_attempts=max_attempts,
            max_request_bytes=max_request_bytes,
            max_response_bytes=max_response_bytes,
            max_pages=100,
            sleep=_no_sleep,
        ),
        client,
    )


def _response_payload(
    *, model: str = "glm-ocr", markdown: str = "# 赛先生\n\n品牌原则"
) -> dict[str, Any]:
    return {
        "id": "ocr-request-1",
        "model": model,
        "md_results": markdown,
        "data_info": {"num_pages": 2, "num_chars": 8},
        "usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46},
    }


@pytest.mark.asyncio
async def test_layout_parsing_sends_bounded_private_base64_pdf() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        payload = json.loads(request.content)
        captured["payload"] = payload
        return httpx.Response(200, json=_response_payload())

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        result = await adapter.parse_document(_request())

    payload = captured["payload"]
    assert captured["url"] == "https://open.bigmodel.invalid/api/paas/v4/layout_parsing"
    assert captured["authorization"] == "Bearer local-contract-secret"
    assert isinstance(payload, dict)
    encoded_file = payload["file"]
    assert encoded_file.startswith("data:application/pdf;base64,")
    assert base64.b64decode(encoded_file.split(",", 1)[1]) == PDF_BODY
    assert payload["model"] == "glm-ocr"
    assert payload["return_crop_images"] is False
    assert payload["need_layout_visualization"] is False
    assert result.markdown == "# 赛先生\n\n品牌原则"
    assert result.page_count == 2
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 34
    assert "local-contract-secret" not in repr(result)


@pytest.mark.asyncio
async def test_ocr_rejects_encoded_request_before_provider_call() -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    adapter, client = _adapter(
        httpx.MockTransport(handler), max_attempts=2, max_request_bytes=len(PDF_BODY)
    )
    async with client:
        with pytest.raises(BrandOcrInputLimitError):
            await adapter.parse_document(_request())
    assert requests == 0


@pytest.mark.asyncio
async def test_ocr_invalid_output_and_identity_are_terminal() -> None:
    responses = iter(
        (
            {**_response_payload(), "md_results": "   "},
            _response_payload(model="other-ocr"),
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(BrandOcrInvalidOutputError):
            await adapter.parse_document(_request())
        with pytest.raises(BrandOcrIdentityMismatchError):
            await adapter.parse_document(_request())


@pytest.mark.asyncio
async def test_ocr_response_limit_is_a_brand_typed_terminal_failure() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": "2048"},
            content=b"{}",
        )

    adapter, client = _adapter(
        httpx.MockTransport(handler), max_attempts=1, max_response_bytes=1024
    )
    async with client:
        with pytest.raises(BrandOcrInvalidOutputError):
            await adapter.parse_document(_request())


@pytest.mark.asyncio
async def test_ocr_rate_limit_retries_and_exhaustion_is_typed() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, json={"error": {"message": "private body"}})

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=2)
    async with client:
        with pytest.raises(BrandOcrRateLimitError) as raised:
            await adapter.parse_document(_request())
    assert attempts == 2
    assert raised.value.retryable is True
    assert "private body" not in str(raised.value)
