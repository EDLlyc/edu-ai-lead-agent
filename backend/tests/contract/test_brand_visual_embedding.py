from __future__ import annotations

import base64
import json
import struct
import zlib

import httpx
import pytest
from app.domain.visual_retrieval import (
    MAX_VISUAL_PROVIDER_REQUEST_BYTES,
    VISUAL_EMBEDDING_DIMENSIONS,
    VisualEmbeddingError,
    VisualEmbeddingIdentity,
    VisualEmbeddingRequest,
    VisualRetrievalUnavailableReason,
)
from app.infrastructure.ai.visual_embedding import AlibabaVisualEmbeddingAdapter
from pydantic import SecretStr

_ENDPOINT = (
    "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )


def _adapter(
    handler: httpx.MockTransport,
    *,
    timeout_seconds: float = 3,
) -> tuple[AlibabaVisualEmbeddingAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=handler, follow_redirects=False)
    return (
        AlibabaVisualEmbeddingAdapter(
            client=client,
            endpoint=SecretStr(_ENDPOINT),
            api_key=SecretStr("test-visual-secret"),
            timeout_seconds=timeout_seconds,
            concurrency=1,
        ),
        client,
    )


@pytest.mark.asyncio
async def test_alibaba_visual_embedding_bounds_concurrency_wait_inside_total_timeout() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500)

    adapter, client = _adapter(httpx.MockTransport(handler), timeout_seconds=0.01)
    await adapter._semaphore.acquire()
    try:
        with pytest.raises(VisualEmbeddingError) as captured:
            await adapter.embed_visual(VisualEmbeddingRequest.for_text("test"))
    finally:
        adapter._semaphore.release()
        await client.aclose()

    assert attempts == 0
    assert captured.value.reason is VisualRetrievalUnavailableReason.PROVIDER_UNAVAILABLE


@pytest.mark.asyncio
async def test_alibaba_visual_embedding_sends_one_text_request_and_binds_omitted_model() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "output": {"embeddings": [{"embedding": [0.5] * 2048, "type": "vl"}]},
                "usage": {"input_tokens": 7, "image_tokens": 0},
            },
        )

    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        request = VisualEmbeddingRequest.for_text("青少年机器人实验")
        result = await adapter.embed_visual(request)
    finally:
        await client.aclose()

    assert len(captured) == 1
    assert captured[0].url == _ENDPOINT
    payload = json.loads(captured[0].content)
    assert payload == {
        "model": "qwen3-vl-embedding",
        "input": {"contents": [{"text": "青少年机器人实验"}]},
        "parameters": {"dimension": 2048, "output_type": "dense"},
    }
    assert result.identity == request.identity
    assert result.input_sha256 == request.input_sha256
    assert len(result.vector) == VISUAL_EMBEDDING_DIMENSIONS
    assert result.input_tokens == 7


@pytest.mark.asyncio
async def test_alibaba_visual_embedding_rejects_conflicting_model_without_retry() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            json={
                "model": "different-vector-space",
                "output": {"embeddings": [{"embedding": [0.5] * 2048}]},
            },
        )

    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(VisualEmbeddingError, match="identity") as captured:
            await adapter.embed_visual(VisualEmbeddingRequest.for_text("test"))
    finally:
        await client.aclose()
    assert attempts == 1
    assert captured.value.reason is VisualRetrievalUnavailableReason.IDENTITY_MISMATCH


@pytest.mark.asyncio
async def test_alibaba_visual_embedding_rejects_conflicting_provider_without_retry() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            json={
                "provider": "different-provider",
                "output": {"embeddings": [{"embedding": [0.5] * 2048}]},
            },
        )

    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(VisualEmbeddingError, match="identity") as captured:
            await adapter.embed_visual(VisualEmbeddingRequest.for_text("test"))
    finally:
        await client.aclose()
    assert attempts == 1
    assert captured.value.reason is VisualRetrievalUnavailableReason.IDENTITY_MISMATCH


@pytest.mark.asyncio
async def test_alibaba_visual_embedding_sends_bounded_png_data_uri() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "qwen3-vl-embedding",
                "output": {"embeddings": [{"embedding": [0.25] * 2048}]},
                "usage": {"input_tokens": 0, "image_tokens": 4},
            },
        )

    body = _png()
    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        result = await adapter.embed_visual(VisualEmbeddingRequest.for_image(body))
    finally:
        await client.aclose()

    contents = captured["input"]["contents"]  # type: ignore[index]
    assert contents == [
        {"image": "data:image/png;base64," + base64.b64encode(body).decode("ascii")}
    ]
    assert result.image_tokens == 4


@pytest.mark.asyncio
async def test_alibaba_visual_embedding_rejects_wrong_dimensions_without_secret_leak() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"output": {"embeddings": [{"embedding": [0.5] * 16}]}},
        )

    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(VisualEmbeddingError) as captured:
            await adapter.embed_visual(VisualEmbeddingRequest.for_text("test"))
    finally:
        await client.aclose()
    assert "test-visual-secret" not in str(captured.value)
    assert captured.value.reason is VisualRetrievalUnavailableReason.INVALID_PROVIDER_OUTPUT


@pytest.mark.asyncio
async def test_alibaba_visual_embedding_rejects_non_frozen_identity_without_request() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500)

    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        identity = VisualEmbeddingIdentity()
        object.__setattr__(identity, "model", "different-model")
        request = VisualEmbeddingRequest.for_text("test", identity=identity)
        with pytest.raises(VisualEmbeddingError, match="identity"):
            await adapter.embed_visual(request)
    finally:
        await client.aclose()
    assert attempts == 0


@pytest.mark.asyncio
async def test_alibaba_visual_embedding_stops_reading_oversized_response() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            headers={"content-length": str(4 * 1024 * 1024 + 1)},
            content=b"{}",
        )

    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(VisualEmbeddingError, match="too large"):
            await adapter.embed_visual(VisualEmbeddingRequest.for_text("test"))
    finally:
        await client.aclose()
    assert attempts == 1


@pytest.mark.asyncio
async def test_alibaba_visual_embedding_rejects_oversized_request_envelope_without_http() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500)

    request = VisualEmbeddingRequest.for_image(_png())
    object.__setattr__(request, "image_png", _png() + b"x" * (8 * 1024 * 1024))
    adapter, client = _adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(VisualEmbeddingError, match="envelope") as captured:
            await adapter.embed_visual(request)
    finally:
        await client.aclose()

    assert attempts == 0
    assert captured.value.reason is VisualRetrievalUnavailableReason.INPUT_NORMALIZATION_FAILED
    assert MAX_VISUAL_PROVIDER_REQUEST_BYTES == 10 * 1024 * 1024
