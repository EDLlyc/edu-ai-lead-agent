from __future__ import annotations

import asyncio
import json
import re
import struct
import time
import zlib
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerationResult,
)
from app.core.errors import (
    ImageOutputValidationError,
    ImageProviderRejectedError,
    ImageProviderTimeoutError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from app.domain.image_generation import (
    IMAGE_HEIGHT,
    IMAGE_MODEL,
    IMAGE_RESOLUTION,
    IMAGE_SIZE,
    IMAGE_WIDTH,
    image_checksum,
    validate_image_prompt,
)

_Sleep = Callable[[float], Awaitable[None]]
_ALLOWED_MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp"}
_MAX_PROVIDER_ID = 200
_MAX_JSON_BYTES = 256 * 1024
_TOAPIS_HOST = "toapis.com"
_TOAPIS_FILES_HOST = "files.toapis.com"
_SAFE_PROVIDER_ID = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
_GPT_IMAGE_MODEL = "gpt-image-2"
_FLUX_IMAGE_MODEL = "flux-2-pro"
_GEMINI_IMAGE_MODEL = "gemini-3-pro-image-preview-official"
_SUPPORTED_IMAGE_MODELS = {_GPT_IMAGE_MODEL, _FLUX_IMAGE_MODEL, _GEMINI_IMAGE_MODEL}


def _generation_payload(
    *, model: str, prompt: str, fingerprint: str, upload_url: str | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": IMAGE_SIZE,
        "client_business_id": fingerprint,
    }
    if model == _GPT_IMAGE_MODEL:
        payload.update({"resolution": IMAGE_RESOLUTION, "response_format": "url"})
        if upload_url is not None:
            payload["reference_images"] = [upload_url]
        return payload
    if model == _FLUX_IMAGE_MODEL:
        payload["metadata"] = {"resolution": "1K"}
        if upload_url is not None:
            payload["image_urls"] = [upload_url]
        return payload
    if model == _GEMINI_IMAGE_MODEL:
        payload["metadata"] = {
            "resolution": "1K",
            "thinkingConfig": {"thinkingLevel": "HIGH"},
            "imageOutputOptions": {"mimeType": "image/png"},
        }
        if upload_url is not None:
            payload["image_urls"] = [upload_url]
        return payload
    raise ValueError("unsupported ToAPIs image model profile")


class DeterministicFakeImageGenerator:
    """Offline provider that produces a deterministic 1024x1024 PNG."""

    def __init__(self, *, model: str = IMAGE_MODEL) -> None:
        self._model = model

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        prompt = validate_image_prompt(request.prompt)
        body = _solid_png(request.request_fingerprint, prompt)
        return ImageGenerationResult(
            provider="fake",
            model=self._model,
            request_fingerprint=request.request_fingerprint,
            provider_task_id=None,
            provider_upload_id=None,
            image_bytes=body,
            media_type="image/png",
            width=IMAGE_WIDTH,
            height=IMAGE_HEIGHT,
            attempts=1,
        )


class ToApisImageGenerator:
    """Bounded ToAPIs image adapter; provider payloads never leave this boundary."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: SecretStr,
        model: str = IMAGE_MODEL,
        max_attempts: int = 3,
        initial_poll_seconds: float = 5.0,
        poll_interval_seconds: float = 7.0,
        provider_window_seconds: float = 120.0,
        timeout_seconds: float = 30.0,
        max_download_bytes: int = 20 * 1024 * 1024,
        sleep: _Sleep = asyncio.sleep,
    ) -> None:
        parsed = urlsplit(base_url.strip())
        key = api_key.get_secret_value().strip()
        if (
            parsed.scheme != "https"
            or parsed.hostname != _TOAPIS_HOST
            or parsed.port not in {None, 443}
            or parsed.path not in {"", "/"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("ToAPIs base URL must be exactly https://toapis.com")
        if not key or any(ch in key for ch in "\r\n"):
            raise ValueError("ToAPIs API key must be non-blank and contain no line breaks")
        if max_attempts < 1 or provider_window_seconds <= 0 or max_download_bytes < 1024:
            raise ValueError("ToAPIs bounds are invalid")
        normalized_model = model.strip()
        if normalized_model not in _SUPPORTED_IMAGE_MODELS:
            raise ValueError("unsupported ToAPIs image model profile")
        self._client = client
        self._base_url = "https://toapis.com"
        self._api_key = SecretStr(key)
        self._model = normalized_model
        self._max_attempts = max_attempts
        self._initial_poll_seconds = initial_poll_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._provider_window_seconds = provider_window_seconds
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_download_bytes = max_download_bytes
        self._sleep = sleep

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        # Upload, polling, and the expiring result download share one provider deadline. This
        # prevents a sequence of per-request retries from outliving the durable worker lease.
        try:
            async with asyncio.timeout(self._provider_window_seconds):
                prompt = validate_image_prompt(request.prompt)
                upload_id: str | None = None
                upload_url: str | None = None
                if request.reference_image is not None:
                    upload_id, upload_url = await self._upload_reference(request.reference_image)
                payload = _generation_payload(
                    model=self._model,
                    prompt=prompt,
                    fingerprint=request.request_fingerprint,
                    upload_url=upload_url,
                )
                created = await self._post_json("/v1/images/generations", payload)
                task_id = _safe_id(_first_value(created, "task_id", "id"))
                if task_id is None:
                    raise ImageProviderRejectedError()
                result = await self._poll(task_id)
                image_url = _extract_result_url(result)
                body, media_type, width, height = await self._download_image(image_url)
        except TimeoutError as exc:
            raise ImageProviderTimeoutError() from exc
        return ImageGenerationResult(
            provider="toapis",
            model=self._model,
            request_fingerprint=request.request_fingerprint,
            provider_task_id=task_id,
            provider_upload_id=upload_id,
            image_bytes=body,
            media_type=media_type,
            width=width,
            height=height,
            attempts=1,
        )

    async def _upload_reference(self, body: bytes) -> tuple[str | None, str]:
        if len(body) > self._max_download_bytes:
            raise ImageOutputValidationError()
        if len(body) < 24 or body[:8] != b"\x89PNG\r\n\x1a\n" or body[12:16] != b"IHDR":
            raise ImageOutputValidationError()
        response = await self._request(
            "POST",
            "/v1/uploads/images",
            files={"file": ("reference.png", body, "image/png")},
        )
        payload = self._json(response)
        upload_url = _safe_url(_first_value(payload, "url", "image_url", "download_url"))
        upload_id = _safe_id(_first_value(payload, "id", "upload_id", "file_id"))
        if upload_url is None:
            raise ImageProviderRejectedError()
        return upload_id, upload_url

    async def _poll(self, task_id: str) -> dict[str, Any]:
        started = time.monotonic()
        await self._sleep(self._initial_poll_seconds)
        while time.monotonic() - started <= self._provider_window_seconds:
            response = await self._request("GET", f"/v1/images/generations/{task_id}")
            payload = self._json(response)
            status = _first_value(payload, "status")
            if status == "completed":
                return payload
            if status == "failed":
                raise ImageProviderRejectedError()
            if status not in {"queued", "in_progress"}:
                raise ImageProviderRejectedError()
            remaining = self._provider_window_seconds - (time.monotonic() - started)
            await self._sleep(min(self._poll_interval_seconds, max(0.1, remaining)))
        raise ImageProviderTimeoutError()

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._json(await self._request("POST", path, json=payload))

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        for attempt in range(self._max_attempts):
            try:
                response = await self._client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=headers,
                    timeout=self._timeout,
                    follow_redirects=False,
                    **kwargs,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 >= self._max_attempts:
                    raise ImageProviderTimeoutError() from exc
                await self._sleep(min(2.0**attempt, 8.0))
                continue
            except httpx.HTTPError as exc:
                if attempt + 1 >= self._max_attempts:
                    raise ProviderUnavailableError() from exc
                await self._sleep(min(2.0**attempt, 8.0))
                continue
            if response.status_code in {401, 403}:
                raise ProviderAuthenticationError()
            if response.status_code == 429:
                if attempt + 1 >= self._max_attempts:
                    raise ProviderRateLimitError()
                await self._sleep(_retry_after(response) or min(2.0**attempt, 8.0))
                continue
            if response.status_code >= 500:
                if attempt + 1 >= self._max_attempts:
                    raise ProviderUnavailableError()
                await self._sleep(_retry_after(response) or min(2.0**attempt, 8.0))
                continue
            if response.status_code >= 400:
                raise ImageProviderRejectedError()
            if len(response.content) > _MAX_JSON_BYTES:
                raise ImageProviderRejectedError()
            return response
        raise ProviderUnavailableError()

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            value = response.json()
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise ImageProviderRejectedError() from exc
        if not isinstance(value, dict):
            raise ImageProviderRejectedError()
        return value

    async def _download_image(self, url: str) -> tuple[bytes, str, int, int]:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != _TOAPIS_FILES_HOST
            or parsed.port not in {None, 443}
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ImageOutputValidationError()
        try:
            async with self._client.stream(
                "GET", url, timeout=self._timeout, follow_redirects=False
            ) as response:
                if response.is_redirect or response.status_code >= 400:
                    raise ImageOutputValidationError()
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        if int(content_length) > self._max_download_bytes:
                            raise ImageOutputValidationError()
                    except ValueError as exc:
                        raise ImageOutputValidationError() from exc
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in _ALLOWED_MEDIA_TYPES:
                    raise ImageOutputValidationError()
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes(64 * 1024):
                    total += len(chunk)
                    if total > self._max_download_bytes:
                        raise ImageOutputValidationError()
                    chunks.append(chunk)
                body = b"".join(chunks)
        except httpx.HTTPError as exc:
            raise ImageProviderTimeoutError() from exc
        width, height = _image_dimensions(body, content_type)
        if width != IMAGE_WIDTH or height != IMAGE_HEIGHT:
            raise ImageOutputValidationError()
        return body, content_type, width, height


def _first_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    data = payload.get("data")
    if isinstance(data, dict):
        return _first_value(data, *keys)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return _first_value(data[0], *keys)
    return None


def _extract_result_url(payload: dict[str, Any]) -> str:
    data = payload.get("result", payload)
    if isinstance(data, dict):
        nested = data.get("data")
        if isinstance(nested, list) and len(nested) == 1 and isinstance(nested[0], dict):
            value = nested[0].get("url")
            if isinstance(value, str):
                return value
        value = data.get("url")
        if isinstance(value, str) and "data" not in data:
            return value
    raise ImageProviderRejectedError()


def _safe_id(value: Any) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= _MAX_PROVIDER_ID:
        return None
    if _SAFE_PROVIDER_ID.fullmatch(value) is None:
        return None
    return value


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _TOAPIS_FILES_HOST
        or parsed.port not in {None, 443}
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        return None
    return value


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after", "").strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    return max(0.0, min(value, 30.0))


def _image_dimensions(body: bytes, media_type: str) -> tuple[int, int]:
    if media_type == "image/png":
        if len(body) < 24 or body[:8] != b"\x89PNG\r\n\x1a\n":
            raise ImageOutputValidationError()
        return struct.unpack(">II", body[16:24])
    if media_type == "image/webp":
        if len(body) < 30 or body[:4] != b"RIFF" or body[8:12] != b"WEBP":
            raise ImageOutputValidationError()
        if body[12:16] == b"VP8X":
            return 1 + int.from_bytes(body[24:27], "little"), 1 + int.from_bytes(
                body[27:30], "little"
            )
    if media_type == "image/jpeg":
        return _jpeg_dimensions(body)
    raise ImageOutputValidationError()


def _jpeg_dimensions(body: bytes) -> tuple[int, int]:
    index = 2
    while index + 9 < len(body) and body[index] == 0xFF:
        marker = body[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(body):
            break
        length = int.from_bytes(body[index : index + 2], "big")
        if marker in range(0xC0, 0xC4) and length >= 7:
            return int.from_bytes(body[index + 5 : index + 7], "big"), int.from_bytes(
                body[index + 3 : index + 5], "big"
            )
        index += length
    raise ImageOutputValidationError()


def _solid_png(seed: str, prompt: str) -> bytes:
    # A deterministic, dependency-free 1024x1024 RGB PNG for offline tests.
    digest = bytes.fromhex(image_checksum(f"{seed}\0{prompt}".encode()))
    row = b"\x00" + bytes((digest[0], digest[1], digest[2])) * IMAGE_WIDTH
    raw = row * IMAGE_HEIGHT

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", IMAGE_WIDTH, IMAGE_HEIGHT, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
