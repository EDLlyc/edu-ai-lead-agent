"""Bounded HTTPS adapter for the Enterprise WeChat self-built-app API."""

from __future__ import annotations

import asyncio
import json
import math
import re
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from app.application.ports.wecom import (
    WECOM_DUPLICATE_CHECK_INTERVAL_SECONDS,
    WECOM_MAX_IMAGE_BYTES,
    WECOM_MAX_RESPONSE_BYTES,
    WECOM_MAX_TEXT_BYTES,
    WECOM_MIN_IMAGE_BYTES,
    SendResult,
    UploadedMedia,
    WeComInvalidInputError,
    WeComInvalidResponseError,
    WeComProviderError,
    WeComProviderRejectedError,
    WeComRateLimitError,
    WeComTokenInvalidError,
    WeComTransientError,
    WeComUnknownTimeoutError,
)
from app.core.config import Settings

_Sleep = Callable[[float], Awaitable[None]]
_Clock = Callable[[], float]
_WECOM_HOST = "qyapi.weixin.qq.com"
_ACCEPT_ENCODING = "gzip"
_SAFE_PROVIDER_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}")
_TOKEN_INVALID_CODES = frozenset({40001, 40014, 42001, 42007, 42009})
_RATE_LIMIT_CODES = frozenset({45009, 45011, 45024, 45033, 9001001})
_TRANSIENT_CODES = frozenset({-1})


@dataclass(frozen=True, slots=True)
class _CachedToken:
    value: str = field(repr=False)
    refresh_at: float


@dataclass(frozen=True, slots=True)
class _ProviderResponse:
    status_code: int
    headers: httpx.Headers
    payload: dict[str, object]


class WeComApiClient:
    """Enterprise WeChat adapter implementing the application delivery boundary.

    The client owns a process-local access-token cache. Temporary media IDs and tokens are
    returned only to the immediate caller and are deliberately excluded from representations
    and all provider error projections.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        corp_id: str,
        corp_secret: SecretStr | str,
        base_url: str = "https://qyapi.weixin.qq.com",
        timeout_seconds: float = 15.0,
        max_attempts: int = 2,
        max_image_bytes: int = WECOM_MAX_IMAGE_BYTES,
        max_response_bytes: int = WECOM_MAX_RESPONSE_BYTES,
        max_text_bytes: int = WECOM_MAX_TEXT_BYTES,
        token_refresh_skew_seconds: float = 300.0,
        sleep: _Sleep = asyncio.sleep,
        clock: _Clock = monotonic,
    ) -> None:
        _validate_base_url(base_url)
        _validate_identifier(corp_id, maximum=128)
        secret_value = (
            corp_secret.get_secret_value() if isinstance(corp_secret, SecretStr) else corp_secret
        )
        if (
            not isinstance(secret_value, str)
            or not secret_value.strip()
            or any(character in secret_value for character in "\r\n")
        ):
            raise ValueError("WeCom CorpSecret must be a non-blank value without line breaks")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("WeCom request timeout must be positive")
        if max_attempts < 1 or max_attempts > 10:
            raise ValueError("WeCom max attempts must be between 1 and 10")
        if max_image_bytes < WECOM_MIN_IMAGE_BYTES or max_image_bytes > WECOM_MAX_IMAGE_BYTES:
            raise ValueError("WeCom image byte limit must be between 6 bytes and 10 MiB")
        if max_response_bytes < 1 or max_response_bytes > 1024 * 1024:
            raise ValueError("WeCom response byte limit must be bounded")
        if max_text_bytes < 1 or max_text_bytes > WECOM_MAX_TEXT_BYTES:
            raise ValueError("WeCom text byte limit must be between 1 and 2048 bytes")
        if not math.isfinite(token_refresh_skew_seconds) or token_refresh_skew_seconds < 0:
            raise ValueError("WeCom token refresh skew must not be negative")

        self._client = client
        self._base_url = base_url.strip().rstrip("/")
        self._corp_id = corp_id.strip()
        self._corp_secret = SecretStr(secret_value.strip())
        self._timeout = httpx.Timeout(timeout_seconds)
        self._total_timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._max_image_bytes = max_image_bytes
        self._max_response_bytes = max_response_bytes
        self._max_text_bytes = max_text_bytes
        self._token_refresh_skew_seconds = token_refresh_skew_seconds
        self._sleep = sleep
        self._clock = clock
        self._token_cache: _CachedToken | None = None
        self._token_lock = asyncio.Lock()

    async def upload_image(
        self, image_bytes: bytes, media_type: str, filename: str
    ) -> UploadedMedia:
        try:
            normalized_media_type = _validate_image(
                image_bytes,
                media_type,
                max_bytes=self._max_image_bytes,
            )
            _validate_filename(filename)
        except (TypeError, UnicodeError, ValueError):
            raise WeComInvalidInputError() from None

        response = await self._authenticated_request(
            method="POST",
            path="/cgi-bin/media/upload",
            params={"type": "image"},
            files={"media": (filename, image_bytes, normalized_media_type)},
            json_payload=None,
            unknown_on_timeout=True,
        )
        media_id = response.payload.get("media_id")
        if not isinstance(media_id, str) or not _is_safe_media_id(media_id):
            raise WeComInvalidResponseError()
        return UploadedMedia(
            media_id=media_id,
            provider_request_id=_provider_request_id(response.headers),
            response_code=_response_code(response.payload),
        )

    async def send_text(
        self,
        recipient_id: str,
        agent_id: int | None,
        content: str,
        request_fingerprint: str,
    ) -> SendResult:
        try:
            _validate_recipient_id(recipient_id)
            if agent_id is None:
                raise ValueError("agent id is required")
            _validate_agent_id(agent_id)
            _validate_text(content, max_bytes=self._max_text_bytes)
            _validate_request_fingerprint(request_fingerprint)
        except (TypeError, UnicodeError, ValueError):
            raise WeComInvalidInputError() from None

        response = await self._authenticated_request(
            method="POST",
            path="/cgi-bin/message/send",
            params={},
            files=None,
            json_payload={
                "touser": recipient_id,
                "msgtype": "text",
                "agentid": agent_id,
                "text": {"content": content},
                "enable_duplicate_check": 1,
                "duplicate_check_interval": WECOM_DUPLICATE_CHECK_INTERVAL_SECONDS,
            },
            unknown_on_timeout=True,
        )
        return _send_result(response)

    async def send_image_bytes(
        self,
        recipient_id: str,
        agent_id: int | None,
        image_bytes: bytes,
        media_type: str,
        filename: str,
        request_fingerprint: str,
    ) -> SendResult:
        """Upload and send an image while satisfying the byte-oriented delivery port."""

        if agent_id is None:
            raise WeComInvalidInputError()
        try:
            _validate_image(image_bytes, media_type, max_bytes=self._max_image_bytes)
            _validate_filename(filename)
        except (TypeError, UnicodeError, ValueError):
            raise WeComInvalidInputError() from None
        uploaded = await self.upload_image(image_bytes, media_type, filename)
        return await self.send_image(
            recipient_id=recipient_id,
            agent_id=agent_id,
            media_id=uploaded.media_id,
            request_fingerprint=request_fingerprint,
        )

    async def send_image(
        self,
        recipient_id: str,
        agent_id: int,
        media_id: str,
        request_fingerprint: str,
    ) -> SendResult:
        try:
            _validate_recipient_id(recipient_id)
            _validate_agent_id(agent_id)
            _validate_media_id(media_id)
            _validate_request_fingerprint(request_fingerprint)
        except (TypeError, UnicodeError, ValueError):
            raise WeComInvalidInputError() from None

        response = await self._authenticated_request(
            method="POST",
            path="/cgi-bin/message/send",
            params={},
            files=None,
            json_payload={
                "touser": recipient_id,
                "msgtype": "image",
                "agentid": agent_id,
                "image": {"media_id": media_id},
                "enable_duplicate_check": 1,
                "duplicate_check_interval": WECOM_DUPLICATE_CHECK_INTERVAL_SECONDS,
            },
            unknown_on_timeout=True,
        )
        return _send_result(response)

    async def _authenticated_request(
        self,
        *,
        method: str,
        path: str,
        params: dict[str, str],
        files: dict[str, tuple[str, bytes, str]] | None,
        json_payload: dict[str, object] | None,
        unknown_on_timeout: bool,
    ) -> _ProviderResponse:
        token = await self._get_access_token()
        for refresh_attempt in range(2):
            try:
                authenticated_params = {**params, "access_token": token.value}
                return await self._request_with_retries(
                    method=method,
                    path=path,
                    params=authenticated_params,
                    files=files,
                    json_payload=json_payload,
                    unknown_on_timeout=unknown_on_timeout,
                )
            except WeComTokenInvalidError:
                if refresh_attempt == 1:
                    raise
                await self._invalidate_token(token.value)
                token = await self._get_access_token(force_refresh=True)
        raise AssertionError("unreachable token refresh state")

    async def _get_access_token(self, *, force_refresh: bool = False) -> _CachedToken:
        now = self._clock()
        cached = self._token_cache
        if not force_refresh and cached is not None and cached.refresh_at > now:
            return cached

        async with self._token_lock:
            now = self._clock()
            cached = self._token_cache
            if not force_refresh and cached is not None and cached.refresh_at > now:
                return cached
            response = await self._request_with_retries(
                method="GET",
                path="/cgi-bin/gettoken",
                params={
                    "corpid": self._corp_id,
                    "corpsecret": self._corp_secret.get_secret_value(),
                },
                files=None,
                json_payload=None,
                unknown_on_timeout=False,
            )
            access_token = response.payload.get("access_token")
            expires_in = response.payload.get("expires_in")
            if (
                not isinstance(access_token, str)
                or not access_token.strip()
                or any(character.isspace() for character in access_token)
                or len(access_token) > 4096
                or isinstance(expires_in, bool)
                or not isinstance(expires_in, int)
                or expires_in < 1
                or expires_in > 7 * 24 * 60 * 60
            ):
                raise WeComInvalidResponseError()
            cached = _CachedToken(
                value=access_token,
                refresh_at=self._clock() + expires_in - self._token_refresh_skew_seconds,
            )
            self._token_cache = cached
            return cached

    async def _invalidate_token(self, token: str) -> None:
        async with self._token_lock:
            if self._token_cache is not None and self._token_cache.value == token:
                self._token_cache = None

    async def _request_with_retries(
        self,
        *,
        method: str,
        path: str,
        params: dict[str, str],
        files: dict[str, tuple[str, bytes, str]] | None,
        json_payload: dict[str, object] | None,
        unknown_on_timeout: bool,
    ) -> _ProviderResponse:
        last_error: WeComRateLimitError | WeComTransientError | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await self._request_once(
                    method=method,
                    path=path,
                    params=params,
                    files=files,
                    json_payload=json_payload,
                    unknown_on_timeout=unknown_on_timeout,
                )
            except (WeComRateLimitError, WeComTransientError) as error:
                last_error = error
                if attempt >= self._max_attempts:
                    raise
                await self._sleep(min(0.25 * (2 ** (attempt - 1)), 2.0))
        if last_error is None:
            raise WeComTransientError()
        raise last_error

    async def _request_once(
        self,
        *,
        method: str,
        path: str,
        params: dict[str, str],
        files: dict[str, tuple[str, bytes, str]] | None,
        json_payload: dict[str, object] | None,
        unknown_on_timeout: bool,
    ) -> _ProviderResponse:
        try:
            async with asyncio.timeout(self._total_timeout_seconds):
                async with self._client.stream(
                    method,
                    f"{self._base_url}{path}",
                    params=params,
                    files=files,
                    json=json_payload,
                    follow_redirects=False,
                    headers={"Accept": "application/json", "Accept-Encoding": _ACCEPT_ENCODING},
                    timeout=self._timeout,
                ) as response:
                    request_id = _provider_request_id(response.headers)
                    status_code = response.status_code
                    if status_code < 200 or status_code >= 300:
                        raise _error_for_http_status(
                            status_code,
                            provider_request_id=request_id,
                        )
                    body = await _read_bounded_response(
                        response,
                        max_response_bytes=self._max_response_bytes,
                    )
        except WeComProviderError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            if unknown_on_timeout:
                raise WeComUnknownTimeoutError() from None
            raise WeComTransientError() from None
        except httpx.RequestError:
            raise WeComTransientError() from None

        payload = _parse_json_payload(body)
        response_code = _response_code(payload)
        if response_code != 0:
            raise _error_for_provider_code(
                response_code,
                provider_request_id=request_id,
            )
        return _ProviderResponse(status_code, response.headers, payload)


class WeComHttpClient(WeComApiClient):
    """Settings-bound Enterprise WeChat client used by the dispatcher process."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        if settings.wecom_corp_secret is None:
            raise ValueError("WeCom CorpSecret is required for the HTTP client")
        self._owns_client = client is None
        super().__init__(
            client=client if client is not None else httpx.AsyncClient(),
            corp_id=settings.wecom_corp_id,
            corp_secret=settings.wecom_corp_secret,
            base_url=settings.wecom_api_base_url,
            timeout_seconds=settings.wecom_request_timeout_seconds,
            max_attempts=settings.wecom_max_attempts,
            max_image_bytes=settings.wecom_max_image_bytes,
            max_text_bytes=settings.wecom_max_text_bytes,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


async def _read_bounded_response(
    response: httpx.Response,
    *,
    max_response_bytes: int,
) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_bytes = int(content_length)
        except ValueError:
            raise WeComInvalidResponseError() from None
        if declared_bytes < 0 or declared_bytes > max_response_bytes:
            raise WeComInvalidResponseError()

    content_encoding = response.headers.get("content-encoding", "identity").strip().casefold()
    if content_encoding not in {"", "identity", _ACCEPT_ENCODING}:
        raise WeComInvalidResponseError()
    if response.is_stream_consumed:
        content = response.content
        if len(content) > max_response_bytes:
            raise WeComInvalidResponseError()
        return content

    decoder = (
        zlib.decompressobj(zlib.MAX_WBITS | 16) if content_encoding == _ACCEPT_ENCODING else None
    )
    chunks: list[bytes] = []
    raw_byte_count = 0
    decoded_byte_count = 0
    try:
        async for raw_chunk in response.aiter_raw():
            raw_byte_count += len(raw_chunk)
            if raw_byte_count > max_response_bytes:
                raise WeComInvalidResponseError()
            decoded_chunk = raw_chunk
            if decoder is not None:
                decoded_chunk = decoder.decompress(
                    raw_chunk,
                    max_response_bytes - decoded_byte_count + 1,
                )
            decoded_byte_count += len(decoded_chunk)
            if decoded_byte_count > max_response_bytes:
                raise WeComInvalidResponseError()
            if decoder is not None and decoder.unconsumed_tail:
                raise WeComInvalidResponseError()
            chunks.append(decoded_chunk)
        if decoder is not None:
            trailing = decoder.flush(max_response_bytes - decoded_byte_count + 1)
            decoded_byte_count += len(trailing)
            if decoded_byte_count > max_response_bytes:
                raise WeComInvalidResponseError()
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise WeComInvalidResponseError()
            chunks.append(trailing)
    except zlib.error:
        raise WeComInvalidResponseError() from None
    return b"".join(chunks)


def _parse_json_payload(body: bytes) -> dict[str, object]:
    try:
        raw_payload: Any = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise WeComInvalidResponseError() from None
    if not isinstance(raw_payload, dict) or any(not isinstance(key, str) for key in raw_payload):
        raise WeComInvalidResponseError()
    return cast(dict[str, object], raw_payload)


def _response_code(payload: dict[str, object]) -> int:
    value = payload.get("errcode")
    if isinstance(value, bool) or not isinstance(value, int):
        raise WeComInvalidResponseError()
    return value


def _send_result(response: _ProviderResponse) -> SendResult:
    provider_request_id = _provider_request_id(response.headers)
    if provider_request_id is None:
        provider_request_id = _safe_provider_request_id(response.payload.get("msgid"))
    response_code = _response_code(response.payload)
    if _has_invalid_recipient(response.payload):
        raise WeComProviderRejectedError(
            response_code=response_code,
            provider_request_id=provider_request_id,
        )
    return SendResult(
        provider_request_id=provider_request_id,
        response_code=response_code,
    )


def _has_invalid_recipient(payload: dict[str, object]) -> bool:
    """Treat provider-reported invalid recipients as terminal for the fixed recipient MVP."""

    for field_name in ("invaliduser", "unlicenseduser", "invalidparty", "invalidtag"):
        value = payload.get(field_name)
        if isinstance(value, str):
            if value.strip():
                return True
        elif isinstance(value, (list, tuple, set, dict)):
            if value:
                return True
        elif value is not None:
            return True
    return False


def _error_for_http_status(
    status_code: int,
    *,
    provider_request_id: str | None,
) -> WeComProviderError:
    if status_code in {401, 403}:
        return WeComTokenInvalidError(
            response_code=status_code,
            provider_request_id=provider_request_id,
        )
    if status_code == 429:
        return WeComRateLimitError(
            response_code=status_code,
            provider_request_id=provider_request_id,
        )
    if 500 <= status_code <= 599:
        return WeComTransientError(
            response_code=status_code,
            provider_request_id=provider_request_id,
        )
    return WeComProviderRejectedError(
        response_code=status_code,
        provider_request_id=provider_request_id,
    )


def _error_for_provider_code(
    response_code: int,
    *,
    provider_request_id: str | None,
) -> WeComProviderError:
    if response_code in _TOKEN_INVALID_CODES:
        return WeComTokenInvalidError(
            response_code=response_code,
            provider_request_id=provider_request_id,
        )
    if response_code in _RATE_LIMIT_CODES:
        return WeComRateLimitError(
            response_code=response_code,
            provider_request_id=provider_request_id,
        )
    if response_code in _TRANSIENT_CODES:
        return WeComTransientError(
            response_code=response_code,
            provider_request_id=provider_request_id,
        )
    return WeComProviderRejectedError(
        response_code=response_code,
        provider_request_id=provider_request_id,
    )


def _provider_request_id(headers: httpx.Headers) -> str | None:
    for header_name in ("x-request-id", "request-id", "trace-id"):
        value = headers.get(header_name)
        safe_value = _safe_provider_request_id(value)
        if safe_value is not None:
            return safe_value
    return None


def _safe_provider_request_id(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str) or _SAFE_PROVIDER_REQUEST_ID.fullmatch(value) is None:
        return None
    return value


def _is_safe_media_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 512
        and not any(character.isspace() or ord(character) < 32 for character in value)
    )


def _validate_base_url(base_url: str) -> None:
    if not isinstance(base_url, str):
        raise ValueError("WeCom API base URL must be HTTPS")
    parsed = urlsplit(base_url.strip())
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("WeCom API base URL must use the official host") from None
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != _WECOM_HOST
        or port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("WeCom API base URL must be exactly the official HTTPS origin")


def _validate_identifier(value: str, *, maximum: int) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise ValueError("identifier is invalid")


def _validate_recipient_id(value: str) -> None:
    _validate_identifier(value, maximum=128)


def _validate_agent_id(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 2**31 - 1:
        raise ValueError("agent id is invalid")


def _validate_request_fingerprint(value: str) -> None:
    _validate_identifier(value, maximum=256)


def _validate_media_id(value: str) -> None:
    if not _is_safe_media_id(value):
        raise ValueError("media id is invalid")


def _validate_text(value: str, *, max_bytes: int) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("message content is invalid")
    if len(value.encode("utf-8")) > max_bytes:
        raise ValueError("message content exceeds the configured limit")


def _validate_filename(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 255
        or any(character in value for character in "/\\\x00\r\n")
    ):
        raise ValueError("image filename is invalid")


def _validate_image(image_bytes: bytes, media_type: str, *, max_bytes: int) -> str:
    if not isinstance(image_bytes, bytes):
        raise TypeError("image input must be bytes")
    if len(image_bytes) < WECOM_MIN_IMAGE_BYTES or len(image_bytes) > max_bytes:
        raise ValueError("image input is outside the official byte limits")
    if not isinstance(media_type, str):
        raise TypeError("image media type must be text")
    normalized = media_type.strip().casefold()
    if normalized == "image/jpg":
        normalized = "image/jpeg"
    if normalized not in {"image/jpeg", "image/png"}:
        raise ValueError("WeCom accepts JPG or PNG images only")
    signature = {
        "image/png": b"\x89PNG\r\n\x1a\n",
        "image/jpeg": b"\xff\xd8\xff",
    }[normalized]
    if not image_bytes.startswith(signature):
        raise ValueError("image bytes do not match the declared media type")
    return normalized


__all__ = ["WeComApiClient", "WeComHttpClient"]
