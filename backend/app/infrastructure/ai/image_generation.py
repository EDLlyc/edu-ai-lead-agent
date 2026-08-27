from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import json
import re
import struct
import time
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageReference,
    validate_image_generation_request_prompt,
)
from app.core.errors import (
    ImageOutputValidationError,
    ImageProviderQuotaError,
    ImageProviderRejectedError,
    ImageProviderTimeoutError,
    PolicyRejectedError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from app.core.security import (
    METADATA_ADDRESSES,
    Resolver,
    system_resolver,
    validate_public_resolution,
)
from app.domain.image_generation import (
    IMAGE_HEIGHT,
    IMAGE_MODEL,
    IMAGE_RESOLUTION,
    IMAGE_SIZE,
    IMAGE_WIDTH,
    image_checksum,
)
from app.domain.image_provider_input import (
    IMAGE_REFERENCE_INPUT_V1_PNG_ONLY,
    IMAGE_REFERENCE_INPUT_V2,
    normalize_image_provider_reference,
)

_Sleep = Callable[[float], Awaitable[None]]
OutputHostObserver = Callable[[str], bool]
_ALLOWED_MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp"}
_MAX_PROVIDER_ID = 200
_MAX_JSON_BYTES = 256 * 1024
_TOAPIS_HOST = "toapis.com"
_TOAPIS_FILES_HOST = "files.toapis.com"
_SAFE_PROVIDER_ID = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
_TOAPIS_QUOTA_CODES = frozenset({"quota_not_enough", "insufficient_quota"})
_GPT_IMAGE_MODEL = "gpt-image-2"
_FLUX_IMAGE_MODEL = "flux-2-pro"
_GEMINI_IMAGE_MODEL = "gemini-3-pro-image-preview-official"
_SUPPORTED_IMAGE_MODELS = {_GPT_IMAGE_MODEL, _FLUX_IMAGE_MODEL, _GEMINI_IMAGE_MODEL}
_COMFLY_IMAGE_SIZE = "1024x1024"
_COMFLY_RESPONSE_FORMAT = "url"
_SAFE_OUTPUT_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_GENERIC_DOWNLOAD_MEDIA_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream"})


@dataclass(frozen=True, slots=True)
class _ComflyResponse:
    status_code: int
    body: bytes
    too_large: bool
    retry_after_seconds: float | None
    content_type: str


def _request_references(request: ImageGenerationRequest) -> tuple[ImageReference, ...]:
    """Return the new ordered references while retaining the legacy one-image contract."""

    if request.references and request.reference_image is not None:
        raise ImageOutputValidationError()
    if request.references:
        return request.references
    if request.reference_image is None:
        return ()
    return (
        ImageReference(
            role="legacy",
            asset_id="legacy-reference",
            filename=request.reference_filename or "reference.png",
            sha256=image_checksum(request.reference_image),
            image_bytes=request.reference_image,
        ),
    )


def _provider_references(request: ImageGenerationRequest) -> tuple[ImageReference, ...]:
    """Apply only an explicitly persisted provider capability fallback."""

    references = _request_references(request)
    if request.reference_mode == "single_fallback" and len(references) > 1:
        return references[:1]
    return references


def _provider_reference_png(reference: ImageReference) -> bytes:
    """Build provider bytes under the reference's explicit replay identity.

    The legacy profile retains its exact PNG-only behavior. The v2 profile is used by the
    official-account catalog path and accepts its exact JPEG publication bytes, while preserving
    already-valid PNG bytes byte-for-byte.
    """

    if reference.input_normalization_version == IMAGE_REFERENCE_INPUT_V1_PNG_ONLY:
        if reference.provider_input_sha256 is not None:
            raise ImageOutputValidationError()
        return reference.image_bytes
    if reference.input_normalization_version != IMAGE_REFERENCE_INPUT_V2:
        raise ImageOutputValidationError()
    try:
        normalized = normalize_image_provider_reference(
            reference.image_bytes,
            version=reference.input_normalization_version,
        )
    except ValueError:
        raise ImageOutputValidationError() from None
    if (
        image_checksum(reference.image_bytes) != reference.sha256
        or reference.provider_input_sha256 is None
        or normalized.sha256 != reference.provider_input_sha256
    ):
        raise ImageOutputValidationError()
    return normalized.image_png


def _generation_payload(
    *,
    model: str,
    prompt: str,
    fingerprint: str,
    upload_url: str | None = None,
    upload_urls: tuple[str, ...] = (),
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": IMAGE_SIZE,
        "client_business_id": fingerprint,
    }
    urls = upload_urls or ((upload_url,) if upload_url is not None else ())
    if model == _GPT_IMAGE_MODEL:
        payload.update({"resolution": IMAGE_RESOLUTION, "response_format": "url"})
        if urls:
            payload["reference_images"] = list(urls)
        return payload
    if model == _FLUX_IMAGE_MODEL:
        payload["metadata"] = {"resolution": "1K"}
        if urls:
            payload["image_urls"] = list(urls)
        return payload
    if model == _GEMINI_IMAGE_MODEL:
        payload["metadata"] = {
            "resolution": "1K",
            "thinkingConfig": {"thinkingLevel": "HIGH"},
            "imageOutputOptions": {"mimeType": "image/png"},
        }
        if urls:
            payload["image_urls"] = list(urls)
        return payload
    raise ValueError("unsupported ToAPIs image model profile")


class DeterministicFakeImageGenerator:
    """Offline provider that produces a deterministic 1024x1024 PNG."""

    def __init__(self, *, model: str = IMAGE_MODEL) -> None:
        self._model = model

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        prompt = validate_image_generation_request_prompt(request)
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
                prompt = validate_image_generation_request_prompt(request)
                upload_id: str | None = None
                upload_url: str | None = None
                references = _provider_references(request)
                if len(references) > 1:
                    raise ImageProviderRejectedError()
                if references:
                    upload_id, upload_url = await self._upload_reference(references[0])
                payload = _generation_payload(
                    model=self._model,
                    prompt=prompt,
                    fingerprint=(
                        request.provider_request_fingerprint or request.request_fingerprint
                    ),
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

    async def _upload_reference(self, reference: ImageReference) -> tuple[str | None, str]:
        body = _provider_reference_png(reference)
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
            if len(response.content) <= _MAX_JSON_BYTES:
                _raise_for_quota_response(response)
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
        except (json.JSONDecodeError, ValueError, TypeError):
            raise ImageProviderRejectedError() from None
        if not isinstance(value, dict):
            raise ImageProviderRejectedError()
        if value.get("code") in _TOAPIS_QUOTA_CODES:
            raise ImageProviderQuotaError()
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


class OpenAICompatibleImageGenerator:
    """Bounded adapter for the Comfly OpenAI-compatible image contract."""

    _PENDING_STATUSES = frozenset({"queued", "pending", "in_progress", "processing"})
    _COMPLETE_STATUSES = frozenset({"completed", "complete", "succeeded", "success"})
    _FAILED_STATUSES = frozenset({"failed", "error", "cancelled", "canceled"})
    _AUTH_CODES = frozenset(
        {"invalid_api_key", "invalid_token", "unauthorized", "authentication_error"}
    )
    _QUOTA_CODES = frozenset(
        {
            "quota_not_enough",
            "insufficient_quota",
            "insufficient_balance",
            "balance_not_enough",
            "billing_hard_limit_reached",
        }
    )

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
        max_request_bytes: int = 8 * 1024 * 1024,
        max_provider_response_bytes: int = 32 * 1024 * 1024,
        max_reference_images: int = 3,
        resolver: Resolver = system_resolver,
        output_host_observer: OutputHostObserver | None = None,
        sleep: _Sleep = asyncio.sleep,
    ) -> None:
        normalized_base_url = base_url.strip().rstrip("/")
        parsed = urlsplit(normalized_base_url)
        key = api_key.get_secret_value().strip()
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Comfly base URL must be a valid HTTPS origin") from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or port not in {None, 443}
            or parsed.path not in {"", "/"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(character.isspace() for character in normalized_base_url)
        ):
            raise ValueError("Comfly base URL must be an HTTPS origin without credentials")
        if not key or any(character in key for character in "\r\n"):
            raise ValueError("Comfly API key must be non-blank and contain no line breaks")
        if (
            max_attempts < 1
            or provider_window_seconds <= 0
            or max_download_bytes < 1024
            or max_request_bytes < 1024
            or max_provider_response_bytes < 1024
            or max_reference_images < 1
            or max_reference_images > 4
        ):
            raise ValueError("Comfly image bounds are invalid")
        normalized_model = model.strip()
        if (
            not normalized_model
            or len(normalized_model) > 120
            or any(character.isspace() for character in normalized_model)
        ):
            raise ValueError("Comfly image model identifier is invalid")
        self._client = client
        self._base_url = normalized_base_url
        self._api_key = SecretStr(key)
        self._model = normalized_model
        self._max_attempts = max_attempts
        self._initial_poll_seconds = initial_poll_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._provider_window_seconds = provider_window_seconds
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_download_bytes = max_download_bytes
        self._max_request_bytes = max_request_bytes
        self._max_provider_response_bytes = max_provider_response_bytes
        self._max_reference_images = max_reference_images
        self._resolver = resolver
        self._output_host_observer = output_host_observer
        self._sleep = sleep

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        task_id: str | None = None
        try:
            async with asyncio.timeout(self._provider_window_seconds):
                try:
                    prompt = validate_image_generation_request_prompt(request)
                except ValueError:
                    raise ImageOutputValidationError() from None
                payload = self._payload(prompt, request)
                created_response = await self._request(
                    "POST",
                    "/v1/images/generations",
                    idempotency_key=(
                        request.provider_request_fingerprint or request.request_fingerprint
                    ),
                    json=payload,
                )
                direct_image = self._direct_image(created_response)
                if direct_image is not None:
                    body, media_type, width, height = direct_image
                else:
                    created = self._json_response(created_response)
                    try:
                        representation = _extract_compatible_image(created)
                    except ImageProviderRejectedError as error:
                        raise _with_response_diagnostics(error, created_response) from error
                    if representation is None:
                        task_id = _safe_id(_first_value(created, "task_id", "id"))
                        if task_id is None:
                            raise ImageProviderRejectedError(
                                http_status=created_response.status_code,
                                response_kind=_response_kind(created_response.content_type),
                            )
                        completed = await self._poll(task_id)
                        representation = _extract_compatible_image(completed)
                        if representation is None:
                            raise ImageProviderRejectedError()
                    body, media_type, width, height = await self._normalize_image(representation)
        except TimeoutError:
            raise ImageProviderTimeoutError() from None
        except ImageProviderTimeoutError:
            raise
        return ImageGenerationResult(
            provider="comfly",
            model=self._model,
            request_fingerprint=request.request_fingerprint,
            provider_task_id=task_id,
            provider_upload_id=None,
            image_bytes=body,
            media_type=media_type,
            width=width,
            height=height,
            attempts=1,
        )

    def _payload(self, prompt: str, request: ImageGenerationRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "size": _COMFLY_IMAGE_SIZE,
            # GPT-Image-2 documents URL output as its current primary contract. The response
            # decoder remains compatible with valid Base64, direct raster, and task results.
            "response_format": _COMFLY_RESPONSE_FORMAT,
        }
        references = _request_references(request)
        if len(references) > self._max_reference_images:
            raise ImageOutputValidationError()
        if references:
            payload["image"] = [self._reference_data_url(reference) for reference in references]
        try:
            serialized_size = len(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
        except (TypeError, UnicodeError):
            raise ImageOutputValidationError() from None
        if serialized_size > self._max_request_bytes:
            raise ImageOutputValidationError()
        return payload

    def _reference_data_url(self, reference: ImageReference) -> str:
        body = _provider_reference_png(reference)
        if (
            len(body) > self._max_download_bytes
            or len(body) < 24
            or body[:8] != b"\x89PNG\r\n\x1a\n"
            or body[12:16] != b"IHDR"
        ):
            raise ImageOutputValidationError()
        width, height = _image_dimensions(body, "image/png")
        if width <= 0 or height <= 0:
            raise ImageOutputValidationError()
        encoded = base64.b64encode(body).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    async def _poll(self, task_id: str) -> dict[str, Any]:
        started = time.monotonic()
        await self._sleep(self._initial_poll_seconds)
        while time.monotonic() - started <= self._provider_window_seconds:
            payload = await self._request_json("GET", f"/v1/images/tasks/{task_id}")
            if _extract_compatible_image(payload) is not None:
                return payload
            status = _compatible_status(payload)
            if status in self._COMPLETE_STATUSES or status in self._FAILED_STATUSES:
                raise ImageProviderRejectedError()
            if status not in self._PENDING_STATUSES:
                raise ImageProviderRejectedError()
            remaining = self._provider_window_seconds - (time.monotonic() - started)
            await self._sleep(min(self._poll_interval_seconds, max(0.1, remaining)))
        raise ImageProviderTimeoutError()

    def _direct_image(self, response: _ComflyResponse) -> tuple[bytes, str, int, int] | None:
        if response.content_type not in _ALLOWED_MEDIA_TYPES:
            return None
        if response.too_large:
            raise ImageOutputValidationError("image_download_too_large")
        return self._normalize_image_bytes(
            response.body,
            declared_media_type=response.content_type,
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        response = await self._request(
            method,
            path,
            idempotency_key=idempotency_key,
            json=payload if payload is not None else None,
        )
        return self._json_response(response)

    def _json_response(self, response: _ComflyResponse) -> dict[str, Any]:
        if response.too_large:
            raise ImageProviderRejectedError()
        try:
            value = json.loads(response.body)
        except (json.JSONDecodeError, TypeError, ValueError):
            raise ImageProviderRejectedError(
                http_status=response.status_code,
                response_kind=_response_kind(response.content_type),
            ) from None
        if not isinstance(value, dict):
            raise ImageProviderRejectedError(
                http_status=response.status_code,
                response_kind=_response_kind(response.content_type),
            )
        _raise_for_compatible_payload(value)
        return value

    async def _request(
        self, method: str, path: str, *, idempotency_key: str | None = None, **kwargs: Any
    ) -> _ComflyResponse:
        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        if idempotency_key is not None:
            if _SAFE_PROVIDER_ID.fullmatch(idempotency_key) is None:
                raise ImageProviderRejectedError()
            headers["Idempotency-Key"] = idempotency_key
        for attempt in range(self._max_attempts):
            try:
                async with self._client.stream(
                    method,
                    f"{self._base_url}{path}",
                    headers=headers,
                    timeout=self._timeout,
                    follow_redirects=False,
                    **kwargs,
                ) as response:
                    body, too_large = await _read_bounded_response(
                        response, self._max_provider_response_bytes
                    )
                    status_code = response.status_code
                    retry_after_seconds = _retry_after(response)
                    content_type = _normalized_content_type(
                        response.headers.get("content-type", "")
                    )
            except httpx.TimeoutException:
                if attempt + 1 >= self._max_attempts:
                    raise ImageProviderTimeoutError() from None
                await self._sleep(min(2.0**attempt, 8.0))
                continue
            except httpx.HTTPError:
                if attempt + 1 >= self._max_attempts:
                    raise ProviderUnavailableError() from None
                await self._sleep(min(2.0**attempt, 8.0))
                continue
            if not too_large:
                _raise_for_compatible_status(status_code, body)
            if status_code in {401, 403}:
                raise ProviderAuthenticationError()
            if status_code == 429:
                if attempt + 1 >= self._max_attempts:
                    raise ProviderRateLimitError()
                await self._sleep(retry_after_seconds or min(2.0**attempt, 8.0))
                continue
            if status_code >= 500:
                if attempt + 1 >= self._max_attempts:
                    raise ProviderUnavailableError()
                await self._sleep(retry_after_seconds or min(2.0**attempt, 8.0))
                continue
            if 300 <= status_code < 400:
                raise ImageProviderRejectedError(
                    http_status=status_code,
                    response_kind=_response_kind(content_type),
                )
            if too_large:
                raise ImageProviderRejectedError(
                    http_status=status_code,
                    response_kind=_response_kind(content_type),
                )
            if status_code >= 400:
                raise ImageProviderRejectedError(
                    http_status=status_code,
                    response_kind=_response_kind(content_type),
                )
            return _ComflyResponse(
                status_code=status_code,
                body=body,
                too_large=False,
                retry_after_seconds=retry_after_seconds,
                content_type=content_type,
            )
        raise ProviderUnavailableError()

    async def _normalize_image(
        self, representation: tuple[str, str]
    ) -> tuple[bytes, str, int, int]:
        kind, value = representation
        if kind == "url":
            return await self._download_image(value)
        try:
            if len(value) > 4 * ((self._max_download_bytes + 2) // 3) + 4:
                raise ImageOutputValidationError()
            body = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError, TypeError):
            raise ImageOutputValidationError("image_output_representation_invalid") from None
        return self._normalize_image_bytes(body)

    def _normalize_image_bytes(
        self,
        body: bytes,
        *,
        declared_media_type: str | None = None,
    ) -> tuple[bytes, str, int, int]:
        if not body or len(body) > self._max_download_bytes:
            raise ImageOutputValidationError("image_download_too_large")
        media_type = _detect_image_media_type(body)
        if declared_media_type in _ALLOWED_MEDIA_TYPES and media_type != declared_media_type:
            raise ImageOutputValidationError("image_raster_signature_invalid")
        width, height = _image_dimensions(body, media_type)
        if width != IMAGE_WIDTH or height != IMAGE_HEIGHT:
            raise ImageOutputValidationError("image_dimensions_invalid")
        return body, media_type, width, height

    async def _download_image(self, url: str) -> tuple[bytes, str, int, int]:
        try:
            parsed = urlsplit(url)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            raise ImageOutputValidationError("image_download_url_invalid") from None
        if (
            parsed.scheme != "https"
            or hostname is None
            or port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or "#" in url
            or any(character.isspace() for character in url)
        ):
            raise ImageOutputValidationError("image_download_url_invalid")
        normalized_host = _normalize_output_hostname(hostname)
        if normalized_host is None:
            raise ImageOutputValidationError("image_download_url_invalid")
        if self._output_host_observer is not None:
            if not self._output_host_observer(normalized_host):
                # The local live-smoke can stop here after safely learning only the hostname.
                raise ImageOutputValidationError("image_download_url_invalid")
        try:
            address = ipaddress.ip_address(normalized_host)
        except ValueError:
            try:
                await validate_public_resolution(normalized_host, self._resolver)
            except PolicyRejectedError:
                raise ImageOutputValidationError("image_download_address_invalid") from None
        else:
            if address in METADATA_ADDRESSES or not address.is_global:
                raise ImageOutputValidationError("image_download_address_invalid")
        for attempt in range(self._max_attempts):
            try:
                async with self._client.stream(
                    "GET", url, timeout=self._timeout, follow_redirects=False
                ) as response:
                    if response.is_redirect or response.status_code >= 400:
                        if response.status_code == 429 and attempt + 1 < self._max_attempts:
                            await self._sleep(_retry_after(response) or min(2.0**attempt, 8.0))
                            continue
                        if response.status_code >= 500 and attempt + 1 < self._max_attempts:
                            await self._sleep(_retry_after(response) or min(2.0**attempt, 8.0))
                            continue
                        if response.status_code == 429:
                            raise ProviderRateLimitError()
                        if response.status_code >= 500:
                            raise ProviderUnavailableError()
                        raise ImageOutputValidationError("image_download_url_invalid")
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            if int(content_length) > self._max_download_bytes:
                                raise ImageOutputValidationError("image_download_too_large")
                        except ValueError:
                            raise ImageOutputValidationError(
                                "image_download_content_type_invalid"
                            ) from None
                    content_type = _normalized_content_type(
                        response.headers.get("content-type", "")
                    )
                    if (
                        content_type not in _ALLOWED_MEDIA_TYPES
                        and content_type not in _GENERIC_DOWNLOAD_MEDIA_TYPES
                    ):
                        raise ImageOutputValidationError("image_download_content_type_invalid")
                    body, too_large = await _read_bounded_response(
                        response, self._max_download_bytes
                    )
                    if too_large:
                        raise ImageOutputValidationError("image_download_too_large")
            except httpx.TimeoutException:
                if attempt + 1 >= self._max_attempts:
                    raise ImageProviderTimeoutError() from None
                await self._sleep(min(2.0**attempt, 8.0))
                continue
            except httpx.HTTPError:
                if attempt + 1 >= self._max_attempts:
                    raise ProviderUnavailableError() from None
                await self._sleep(min(2.0**attempt, 8.0))
                continue
            return self._normalize_image_bytes(
                body,
                declared_media_type=content_type,
            )
        raise ProviderUnavailableError()


def _normalize_output_hostname(hostname: str) -> str | None:
    """Return one valid ASCII DNS name for the smoke-only observer."""
    if not hostname or hostname.endswith(".."):
        return None
    candidate = hostname[:-1] if hostname.endswith(".") else hostname
    try:
        normalized = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    if len(normalized) > 253:
        return None
    labels = normalized.split(".")
    if not labels or any(_SAFE_OUTPUT_HOST_LABEL.fullmatch(label) is None for label in labels):
        return None
    return normalized


async def _read_bounded_response(response: httpx.Response, limit: int) -> tuple[bytes, bool]:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) < 0 or int(content_length) > limit:
                return b"", True
        except ValueError:
            return b"", True
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes(64 * 1024):
        total += len(chunk)
        if total > limit:
            return b"", True
        chunks.append(chunk)
    return b"".join(chunks), False


def _extract_compatible_image(payload: dict[str, Any]) -> tuple[str, str] | None:
    """Extract one recognized image representation without retaining provider metadata."""
    documented_task_image = _extract_documented_task_image(payload)
    if documented_task_image is not None:
        return documented_task_image
    containers: list[dict[str, Any]] = [payload]
    result = payload.get("result")
    if isinstance(result, dict):
        containers.append(result)
    representations: list[tuple[str, str]] = []
    for container in containers:
        if "data" in container:
            data = container["data"]
            if isinstance(data, list):
                if len(data) != 1 or not isinstance(data[0], dict):
                    raise ImageProviderRejectedError()
                entry = data[0]
            elif isinstance(data, dict):
                entry = data
            else:
                raise ImageProviderRejectedError()
            if not ("url" in entry or "b64_json" in entry):
                if _is_compatible_task_container(entry, payload):
                    continue
                raise ImageProviderRejectedError()
            representations.append(_extract_compatible_image_entry(entry))
            continue
        if "url" in container or "b64_json" in container:
            representations.append(_extract_compatible_image_entry(container))
    if len(representations) > 1:
        raise ImageProviderRejectedError()
    return representations[0] if representations else None


def _extract_documented_task_image(payload: dict[str, Any]) -> tuple[str, str] | None:
    """Extract the documented Comfly task result without accepting arbitrary nesting."""

    task = payload.get("data")
    if not isinstance(task, dict) or not _is_compatible_task_container(task, payload):
        return None
    result = task.get("data")
    if not isinstance(result, dict):
        return None
    entries = result.get("data")
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        return None
    return _extract_compatible_image_entry(entries[0])


def _extract_compatible_image_entry(entry: dict[str, Any]) -> tuple[str, str]:
    url = entry.get("url")
    b64_json = entry.get("b64_json")
    for key in ("url", "b64_json"):
        if key in entry and not isinstance(entry[key], str):
            raise ImageProviderRejectedError()
    has_url = isinstance(url, str) and bool(url)
    has_b64_json = isinstance(b64_json, str) and bool(b64_json)
    if has_url == has_b64_json:
        raise ImageProviderRejectedError()
    if has_url:
        assert isinstance(url, str)
        return "url", url
    assert isinstance(b64_json, str)
    return "b64_json", b64_json


def _compatible_status(payload: dict[str, Any]) -> str | None:
    containers: list[dict[str, Any]] = [payload]
    result = payload.get("result")
    if isinstance(result, dict):
        containers.append(result)
    data = payload.get("data")
    if isinstance(data, dict):
        containers.append(data)
    elif isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        containers.append(data[0])
    for container in containers:
        status = container.get("status")
        if isinstance(status, str):
            return status.strip().lower()
    return None


def _is_compatible_task_container(container: dict[str, Any], outer: dict[str, Any]) -> bool:
    if _compatible_status(container) is None:
        return False
    return (
        _safe_id(_first_value(container, "task_id", "id")) is not None
        or _safe_id(_first_value(outer, "task_id", "id")) is not None
    )


def _provider_error_code(body: bytes) -> str | None:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    values: list[Any] = [payload]
    error = payload.get("error")
    if isinstance(error, dict):
        values.append(error)
    for value in values:
        for key in ("code", "error_code", "type"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate.strip().lower()
    return None


def _raise_for_compatible_status(status_code: int, body: bytes) -> None:
    code = _provider_error_code(body)
    if code in OpenAICompatibleImageGenerator._QUOTA_CODES:
        raise ImageProviderQuotaError()
    if code in OpenAICompatibleImageGenerator._AUTH_CODES or status_code in {401, 403}:
        raise ProviderAuthenticationError()


def _raise_for_compatible_payload(payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    _raise_for_compatible_status(200, body)


def _detect_image_media_type(body: bytes) -> str:
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    raise ImageOutputValidationError("image_raster_signature_invalid")


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


def _normalized_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _response_kind(content_type: str) -> str:
    if content_type in _ALLOWED_MEDIA_TYPES:
        return "raster"
    if content_type == "application/json" or content_type.endswith("+json"):
        return "json"
    return "other"


def _with_response_diagnostics(
    error: ImageProviderRejectedError,
    response: _ComflyResponse,
) -> ImageProviderRejectedError:
    return ImageProviderRejectedError(
        http_status=error.http_status if error.http_status is not None else response.status_code,
        response_kind=(
            error.response_kind
            if error.response_kind is not None
            else _response_kind(response.content_type)
        ),
    )


def _raise_for_quota_response(response: httpx.Response) -> None:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError, TypeError):
        return
    if isinstance(payload, dict) and payload.get("code") in _TOAPIS_QUOTA_CODES:
        raise ImageProviderQuotaError()


def _image_dimensions(body: bytes, media_type: str) -> tuple[int, int]:
    if media_type == "image/png":
        if len(body) < 24 or body[:8] != b"\x89PNG\r\n\x1a\n":
            raise ImageOutputValidationError("image_raster_signature_invalid")
        return struct.unpack(">II", body[16:24])
    if media_type == "image/webp":
        if len(body) < 30 or body[:4] != b"RIFF" or body[8:12] != b"WEBP":
            raise ImageOutputValidationError("image_raster_signature_invalid")
        chunk_type = body[12:16]
        if chunk_type == b"VP8X":
            return 1 + int.from_bytes(body[24:27], "little"), 1 + int.from_bytes(
                body[27:30], "little"
            )
        if chunk_type == b"VP8 ":
            if body[23:26] != b"\x9d\x01\x2a":
                raise ImageOutputValidationError("image_raster_signature_invalid")
            return (
                int.from_bytes(body[26:28], "little") & 0x3FFF,
                int.from_bytes(body[28:30], "little") & 0x3FFF,
            )
        if chunk_type == b"VP8L":
            if len(body) < 25 or body[20] != 0x2F:
                raise ImageOutputValidationError("image_raster_signature_invalid")
            return (
                1 + body[21] + ((body[22] & 0x3F) << 8),
                1 + (body[22] >> 6) + (body[23] << 2) + ((body[24] & 0x0F) << 10),
            )
    if media_type == "image/jpeg":
        return _jpeg_dimensions(body)
    raise ImageOutputValidationError("image_raster_signature_invalid")


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
    raise ImageOutputValidationError("image_raster_signature_invalid")


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
