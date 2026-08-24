from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
from time import perf_counter_ns
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.application.ports.visual_retrieval import VisualEmbeddingModel
from app.domain.visual_retrieval import (
    MAX_VISUAL_PROVIDER_REQUEST_BYTES,
    VISUAL_EMBEDDING_DIMENSIONS,
    VISUAL_EMBEDDING_MODEL,
    VisualEmbeddingError,
    VisualEmbeddingIdentity,
    VisualEmbeddingModality,
    VisualEmbeddingRequest,
    VisualEmbeddingResult,
    VisualRetrievalUnavailableReason,
)

_REST_PATH = "/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"
_HOST_SUFFIX = ".cn-beijing.maas.aliyuncs.com"
_MAX_PROVIDER_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_METRIC = 10_000_000


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class _ProviderEmbedding(_ProviderModel):
    embedding: list[float] = Field(
        min_length=VISUAL_EMBEDDING_DIMENSIONS,
        max_length=VISUAL_EMBEDDING_DIMENSIONS,
    )


class _ProviderOutput(_ProviderModel):
    embeddings: list[_ProviderEmbedding] = Field(min_length=1, max_length=1)


class _ProviderUsage(_ProviderModel):
    input_tokens: int = Field(default=0, ge=0, le=_MAX_METRIC)
    image_tokens: int = Field(default=0, ge=0, le=_MAX_METRIC)


class _ProviderResponse(_ProviderModel):
    output: _ProviderOutput
    usage: _ProviderUsage = Field(default_factory=_ProviderUsage)
    model: str | None = None
    provider: str | None = None


class AlibabaVisualEmbeddingAdapter(VisualEmbeddingModel):
    """One-attempt adapter for Alibaba Model Studio's Beijing multimodal endpoint."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        endpoint: SecretStr,
        api_key: SecretStr,
        timeout_seconds: float = 60.0,
        concurrency: int = 1,
    ) -> None:
        endpoint_value = endpoint.get_secret_value().strip()
        parsed = urlsplit(endpoint_value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(_HOST_SUFFIX)
            or parsed.path != _REST_PATH
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("visual embedding endpoint must be the exact Beijing REST endpoint")
        secret = api_key.get_secret_value().strip()
        if not secret or any(character in secret for character in "\r\n"):
            raise ValueError("visual embedding API key is invalid")
        if not 0 < timeout_seconds <= 180 or not 1 <= concurrency <= 4:
            raise ValueError("visual embedding runtime bounds are invalid")
        self._client = client
        self._endpoint = SecretStr(endpoint_value)
        self._api_key = SecretStr(secret)
        self._timeout = httpx.Timeout(timeout_seconds)
        self._total_timeout = timeout_seconds
        self._semaphore = asyncio.Semaphore(concurrency)

    async def embed_visual(self, request: VisualEmbeddingRequest) -> VisualEmbeddingResult:
        if request.identity != VisualEmbeddingIdentity():
            raise VisualEmbeddingError(
                VisualRetrievalUnavailableReason.IDENTITY_MISMATCH,
                "visual embedding request identity does not match",
            )
        content: dict[str, str]
        if request.modality is VisualEmbeddingModality.TEXT:
            assert request.text is not None
            content = {"text": request.text}
        else:
            assert request.image_png is not None
            encoded = base64.b64encode(request.image_png).decode("ascii")
            content = {"image": f"data:image/png;base64,{encoded}"}
        payload = {
            "model": VISUAL_EMBEDDING_MODEL,
            "input": {"contents": [content]},
            "parameters": {
                "dimension": VISUAL_EMBEDDING_DIMENSIONS,
                "output_type": "dense",
            },
        }
        request_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if len(request_body) >= MAX_VISUAL_PROVIDER_REQUEST_BYTES:
            raise VisualEmbeddingError(
                VisualRetrievalUnavailableReason.INPUT_NORMALIZATION_FAILED,
                "visual embedding request exceeds the provider envelope",
            )
        started = perf_counter_ns()
        try:
            async with asyncio.timeout(self._total_timeout):
                async with self._semaphore:
                    async with self._client.stream(
                        "POST",
                        self._endpoint.get_secret_value(),
                        headers={
                            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
                            "Content-Type": "application/json",
                        },
                        content=request_body,
                        timeout=self._timeout,
                    ) as response:
                        if response.status_code < 200 or response.status_code >= 300:
                            raise VisualEmbeddingError(
                                VisualRetrievalUnavailableReason.PROVIDER_UNAVAILABLE,
                                "visual embedding provider rejected the request",
                            )
                        declared_size = response.headers.get("content-length")
                        if declared_size is not None:
                            try:
                                if int(declared_size) > _MAX_PROVIDER_RESPONSE_BYTES:
                                    raise VisualEmbeddingError(
                                        VisualRetrievalUnavailableReason.INVALID_PROVIDER_OUTPUT,
                                        "visual embedding provider response is too large",
                                    )
                            except ValueError:
                                pass
                        response_body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(chunk) > _MAX_PROVIDER_RESPONSE_BYTES - len(response_body):
                                raise VisualEmbeddingError(
                                    VisualRetrievalUnavailableReason.INVALID_PROVIDER_OUTPUT,
                                    "visual embedding provider response is too large",
                                )
                            response_body.extend(chunk)
        except (TimeoutError, httpx.HTTPError) as error:
            raise VisualEmbeddingError(
                VisualRetrievalUnavailableReason.PROVIDER_UNAVAILABLE
            ) from error
        latency_ms = max(0, (perf_counter_ns() - started) // 1_000_000)
        try:
            parsed = _ProviderResponse.model_validate(json.loads(response_body))
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as error:
            raise VisualEmbeddingError(
                VisualRetrievalUnavailableReason.INVALID_PROVIDER_OUTPUT,
                "visual embedding provider output is invalid",
            ) from error
        if parsed.model is not None and parsed.model != request.identity.model:
            raise VisualEmbeddingError(
                VisualRetrievalUnavailableReason.IDENTITY_MISMATCH,
                "visual embedding provider identity does not match",
            )
        if parsed.provider is not None and parsed.provider != request.identity.provider:
            raise VisualEmbeddingError(
                VisualRetrievalUnavailableReason.IDENTITY_MISMATCH,
                "visual embedding provider identity does not match",
            )
        vector = tuple(float(value) for value in parsed.output.embeddings[0].embedding)
        if any(not math.isfinite(value) for value in vector):
            raise VisualEmbeddingError(
                VisualRetrievalUnavailableReason.INVALID_PROVIDER_OUTPUT,
                "visual embedding provider vector is invalid",
            )
        try:
            return VisualEmbeddingResult(
                identity=request.identity,
                input_sha256=request.input_sha256,
                request_fingerprint=request.request_fingerprint,
                vector=vector,
                input_tokens=parsed.usage.input_tokens,
                image_tokens=parsed.usage.image_tokens,
                latency_ms=latency_ms,
            )
        except ValueError as error:
            raise VisualEmbeddingError(
                VisualRetrievalUnavailableReason.INVALID_PROVIDER_OUTPUT,
                "visual embedding provider output is invalid",
            ) from error


class DeterministicFakeVisualEmbedding(VisualEmbeddingModel):
    """Provider-free contract fake used by tests and local dry runs."""

    async def embed_visual(self, request: VisualEmbeddingRequest) -> VisualEmbeddingResult:
        digest = hashlib.sha256(
            f"{request.modality.value}\0{request.input_sha256}".encode()
        ).digest()
        values = [0.0] * request.identity.dimensions
        for ordinal, value in enumerate(digest):
            index = (value * 31 + ordinal * 131) % request.identity.dimensions
            values[index] += (value + 1) / 256.0
        norm = math.sqrt(sum(value * value for value in values))
        vector = tuple(value / norm for value in values)
        return VisualEmbeddingResult(
            identity=request.identity,
            input_sha256=request.input_sha256,
            request_fingerprint=request.request_fingerprint,
            vector=vector,
            input_tokens=1 if request.modality is VisualEmbeddingModality.TEXT else 0,
            image_tokens=1 if request.modality is VisualEmbeddingModality.IMAGE else 0,
            latency_ms=0,
        )
