"""Official Enterprise WeChat group-webhook adapter and image preparation."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import warnings
from collections import deque
from dataclasses import dataclass
from io import BytesIO
from time import monotonic

import httpx
from PIL import Image, ImageFile, ImageOps
from PIL.Image import DecompressionBombError, DecompressionBombWarning
from pydantic import SecretStr

from app.application.ports.wecom import (
    WECOM_GROUP_MAX_IMAGE_BYTES,
    WECOM_GROUP_MAX_MESSAGES_PER_MINUTE,
    WECOM_MAX_IMAGE_BYTES,
    WECOM_MAX_RESPONSE_BYTES,
    WECOM_MIN_IMAGE_BYTES,
    SendResult,
    WeComDeliveryClient,
    WeComInvalidInputError,
    WeComProviderError,
    WeComProviderRejectedError,
    WeComRateLimitError,
    WeComTransientError,
    WeComUnknownTimeoutError,
)
from app.core.config import Settings
from app.infrastructure.wecom.client import (
    _parse_json_payload,
    _provider_request_id,
    _read_bounded_response,
    _response_code,
    _safe_provider_request_id,
    _validate_filename,
    _validate_identifier,
    _validate_image,
    _validate_request_fingerprint,
    _validate_text,
)

_WEBHOOK_HOST = "https://qyapi.weixin.qq.com"
_WEBHOOK_PATH = "/cgi-bin/webhook/send"
_ACCEPT_ENCODING = "gzip"
_MAX_IMAGE_DIMENSION = 8_192
_MAX_IMAGE_PIXELS = 32_000_000
_QUALITY_STEPS = (90, 80, 70, 60, 50, 40)
_SCALE_STEPS = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.125, 0.0625)

ImageFile.LOAD_TRUNCATED_IMAGES = False


@dataclass(frozen=True, slots=True)
class PreparedGroupImage:
    """An in-memory image payload prepared for the webhook's 2 MiB raw limit."""

    body: bytes
    media_type: str


def prepare_group_webhook_image(
    image_bytes: bytes,
    media_type: str,
    *,
    max_bytes: int = WECOM_GROUP_MAX_IMAGE_BYTES,
    max_input_bytes: int = WECOM_MAX_IMAGE_BYTES,
) -> PreparedGroupImage:
    """Validate and deterministically fit a JPG/PNG image into the webhook limit.

    The source bytes are never modified. A source already within the limit is returned unchanged;
    larger images are decoded with bounded raster dimensions and encoded through deterministic
    PNG/JPEG candidates until one satisfies the official raw-byte limit.
    """

    if max_bytes < WECOM_MIN_IMAGE_BYTES or max_bytes > WECOM_GROUP_MAX_IMAGE_BYTES:
        raise ValueError("group webhook image limit is outside the official bound")
    normalized = _validate_image(image_bytes, media_type, max_bytes=max_input_bytes)
    loaded = _load_safe_image(image_bytes)
    if len(image_bytes) <= max_bytes:
        return PreparedGroupImage(body=image_bytes, media_type=normalized)

    png_candidate = _encode_png(loaded)
    if len(png_candidate) <= max_bytes:
        return PreparedGroupImage(body=png_candidate, media_type="image/png")

    rgb_image = _to_rgb(loaded)
    for scale in _SCALE_STEPS:
        candidate_image = _scaled(rgb_image, scale)
        for quality in _QUALITY_STEPS:
            candidate = _encode_jpeg(candidate_image, quality)
            if len(candidate) <= max_bytes:
                return PreparedGroupImage(body=candidate, media_type="image/jpeg")
    raise ValueError("image could not be compressed below the group webhook limit")


class WeComGroupWebhookClient(WeComDeliveryClient):
    """Bounded HTTPS client for the official Enterprise WeChat group webhook."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        key = (
            settings.wecom_group_webhook_key.get_secret_value().strip()
            if settings.wecom_group_webhook_key is not None
            else ""
        )
        _validate_webhook_key(key)
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient()
        self._key = SecretStr(key)
        self._timeout = httpx.Timeout(settings.wecom_request_timeout_seconds)
        self._total_timeout_seconds = settings.wecom_request_timeout_seconds
        self._max_attempts = settings.wecom_max_attempts
        self._max_response_bytes = WECOM_MAX_RESPONSE_BYTES
        self._max_text_bytes = settings.wecom_group_max_text_bytes
        self._max_image_bytes = settings.wecom_group_max_image_bytes
        self._max_input_image_bytes = settings.wecom_max_image_bytes
        self._message_timestamps: deque[float] = deque()
        self._message_rate_lock = asyncio.Lock()

    async def send_text(
        self,
        recipient_id: str,
        agent_id: int | None,
        content: str,
        request_fingerprint: str,
    ) -> SendResult:
        del agent_id
        try:
            _validate_identifier(recipient_id, maximum=128)
            _validate_text(content, max_bytes=self._max_text_bytes)
            _validate_request_fingerprint(request_fingerprint)
        except (TypeError, UnicodeError, ValueError):
            raise WeComInvalidInputError() from None
        payload: dict[str, object] = {
            "msgtype": "markdown",
            "markdown": {"content": content},
        }
        return await self._send_payload(payload)

    async def send_image_bytes(
        self,
        recipient_id: str,
        agent_id: int | None,
        image_bytes: bytes,
        media_type: str,
        filename: str,
        request_fingerprint: str,
    ) -> SendResult:
        del agent_id
        try:
            _validate_identifier(recipient_id, maximum=128)
            _validate_filename(filename)
            _validate_request_fingerprint(request_fingerprint)
            prepared = prepare_group_webhook_image(
                image_bytes,
                media_type,
                max_bytes=self._max_image_bytes,
                max_input_bytes=self._max_input_image_bytes,
            )
        except (TypeError, UnicodeError, ValueError, OSError, DecompressionBombError):
            raise WeComInvalidInputError() from None
        payload: dict[str, object] = {
            "msgtype": "image",
            "image": {
                "base64": base64.b64encode(prepared.body).decode("ascii"),
                "md5": hashlib.md5(prepared.body).hexdigest(),
            },
        }
        return await self._send_payload(payload)

    async def _send_payload(self, payload: dict[str, object]) -> SendResult:
        last_error: WeComRateLimitError | WeComTransientError | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                await self._acquire_message_slot()
                return await self._request_once(payload)
            except (WeComRateLimitError, WeComTransientError) as error:
                last_error = error
                if attempt >= self._max_attempts:
                    raise
                await asyncio.sleep(min(0.25 * (2 ** (attempt - 1)), 2.0))
        if last_error is None:
            raise WeComTransientError()
        raise last_error

    async def _acquire_message_slot(self) -> None:
        while True:
            async with self._message_rate_lock:
                now = monotonic()
                while self._message_timestamps and now - self._message_timestamps[0] >= 60:
                    self._message_timestamps.popleft()
                if len(self._message_timestamps) < WECOM_GROUP_MAX_MESSAGES_PER_MINUTE:
                    self._message_timestamps.append(now)
                    return
                wait_seconds = max(0.01, 60 - (now - self._message_timestamps[0]))
            await asyncio.sleep(wait_seconds)

    async def _request_once(self, payload: dict[str, object]) -> SendResult:
        try:
            async with asyncio.timeout(self._total_timeout_seconds):
                async with self._client.stream(
                    "POST",
                    f"{_WEBHOOK_HOST}{_WEBHOOK_PATH}",
                    params={"key": self._key.get_secret_value()},
                    json=payload,
                    follow_redirects=False,
                    headers={"Accept": "application/json", "Accept-Encoding": _ACCEPT_ENCODING},
                    timeout=self._timeout,
                ) as response:
                    request_id = _provider_request_id(response.headers)
                    if response.status_code < 200 or response.status_code >= 300:
                        raise _group_http_error(response.status_code, request_id)
                    body = await _read_bounded_response(
                        response,
                        max_response_bytes=self._max_response_bytes,
                    )
        except WeComProviderError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise WeComUnknownTimeoutError() from None
        except httpx.RequestError:
            raise WeComUnknownTimeoutError() from None

        payload_body = _parse_json_payload(body)
        response_code = _response_code(payload_body)
        if response_code != 0:
            raise _group_provider_error(
                response_code,
                _provider_request_id_from_payload(payload_body),
            )
        return SendResult(
            provider_request_id=request_id,
            response_code=response_code,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _load_safe_image(image_bytes: bytes) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", DecompressionBombWarning)
            with Image.open(BytesIO(image_bytes)) as checked:
                _validate_dimensions(checked.size)
                checked.verify()
            with Image.open(BytesIO(image_bytes)) as source:
                _validate_dimensions(source.size)
                source.load()
                transposed = ImageOps.exif_transpose(source)
                transposed.load()
                return transposed.copy()
    except (DecompressionBombError, DecompressionBombWarning, OSError, ValueError) as error:
        raise ValueError("image raster is invalid or exceeds safe dimensions") from error


def _validate_dimensions(size: tuple[int, int]) -> None:
    width, height = size
    if (
        not isinstance(width, int)
        or not isinstance(height, int)
        or width < 1
        or height < 1
        or width > _MAX_IMAGE_DIMENSION
        or height > _MAX_IMAGE_DIMENSION
        or width * height > _MAX_IMAGE_PIXELS
    ):
        raise ValueError("image dimensions exceed the safe group-webhook bound")


def _encode_png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True, compress_level=9)
    return output.getvalue()


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    output = BytesIO()
    image.save(output, format="JPEG", quality=quality, optimize=True, progressive=False)
    return output.getvalue()


def _to_rgb(image: Image.Image) -> Image.Image:
    if "A" not in image.getbands():
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, "white")
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background


def _scaled(image: Image.Image, scale: float) -> Image.Image:
    if math.isclose(scale, 1.0):
        return image
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def _validate_webhook_key(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise ValueError("group webhook key is invalid")


def _group_http_error(status_code: int, request_id: str | None) -> WeComProviderError:
    if status_code == 429:
        return WeComRateLimitError(response_code=status_code, provider_request_id=request_id)
    if 500 <= status_code <= 599:
        return WeComTransientError(response_code=status_code, provider_request_id=request_id)
    return WeComProviderRejectedError(response_code=status_code, provider_request_id=request_id)


def _group_provider_error(
    response_code: int, provider_request_id: str | None
) -> WeComProviderError:
    if response_code in {45009, 45011, 45024, 45033, 9001001}:
        return WeComRateLimitError(
            response_code=response_code,
            provider_request_id=provider_request_id,
        )
    if response_code == -1:
        return WeComTransientError(
            response_code=response_code,
            provider_request_id=provider_request_id,
        )
    return WeComProviderRejectedError(
        response_code=response_code,
        provider_request_id=provider_request_id,
    )


def _provider_request_id_from_payload(payload: dict[str, object]) -> str | None:
    for field_name in ("msgid", "request_id"):
        value = _safe_provider_request_id(payload.get(field_name))
        if value is not None:
            return value
    return None


__all__ = ["PreparedGroupImage", "WeComGroupWebhookClient", "prepare_group_webhook_image"]
