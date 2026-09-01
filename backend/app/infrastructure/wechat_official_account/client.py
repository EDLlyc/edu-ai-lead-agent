"""Strict HTTPS adapter for WeChat Official Account draft creation."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from app.application.ports.wechat_official_account import (
    WECHAT_MP_MAX_CONTENT_SOURCE_URL_BYTES,
    WECHAT_MP_MAX_DRAFT_AUTHOR_CHARACTERS,
    WECHAT_MP_MAX_DRAFT_CONTENT_BYTES,
    WECHAT_MP_MAX_DRAFT_CONTENT_CHARACTERS,
    WECHAT_MP_MAX_DRAFT_DIGEST_CHARACTERS,
    WECHAT_MP_MAX_DRAFT_MEDIA_ID_CHARACTERS,
    WECHAT_MP_MAX_DRAFT_TITLE_CHARACTERS,
    WECHAT_MP_MAX_IMAGE_BYTES,
    WECHAT_MP_MAX_INLINE_IMAGE_BYTES,
    WECHAT_MP_MAX_RESPONSE_BYTES,
    WECHAT_MP_MAX_THUMB_BYTES,
    WECHAT_MP_MIN_IMAGE_BYTES,
    WeChatDraftArticleRequest,
    WeChatDraftCreated,
    WeChatInlineImage,
    WeChatMpConfigurationError,
    WeChatMpEndpoint,
    WeChatMpInvalidInputError,
    WeChatMpInvalidResponseError,
    WeChatMpOutcomeUnknownError,
    WeChatMpProviderRejectedError,
    WeChatMpRateLimitError,
    WeChatMpTokenInvalidError,
    WeChatMpTransientError,
    WeChatOfficialAccountError,
    WeChatThumbMedia,
)
from app.core.config import Settings

_Clock = Callable[[], float]
_WECHAT_MP_HOST = "api.weixin.qq.com"
_WECHAT_MP_IMAGE_HOSTS = frozenset({"mmbiz.qpic.cn"})
_TOKEN_INVALID_CODES = frozenset({40001, 40014, 42001})
_RATE_LIMIT_CODES = frozenset({45009, 45011})
_TRANSIENT_CODES = frozenset({-1})
_ENDPOINT_PATHS: dict[WeChatMpEndpoint, str] = {
    "stable_token": "/cgi-bin/stable_token",
    "media_uploadimg": "/cgi-bin/media/uploadimg",
    "material_add_thumb": "/cgi-bin/material/add_material",
    "draft_add": "/cgi-bin/draft/add",
}


@dataclass(frozen=True, slots=True)
class _CachedToken:
    value: str = field(repr=False)
    refresh_at: float


@dataclass(frozen=True, slots=True)
class _ProviderResponse:
    payload: dict[str, object]


class WeChatOfficialAccountApiClient:
    """Process-local draft adapter with stable-token caching and one token refresh."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        app_id: SecretStr,
        app_secret: SecretStr,
        base_url: str = "https://api.weixin.qq.com",
        timeout_seconds: float = 15.0,
        max_image_bytes: int = WECHAT_MP_MAX_IMAGE_BYTES,
        max_response_bytes: int = WECHAT_MP_MAX_RESPONSE_BYTES,
        token_refresh_skew_seconds: float = 300.0,
        clock: _Clock = monotonic,
    ) -> None:
        _validate_base_url(base_url)
        _validate_secret(app_id)
        _validate_secret(app_secret)
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("WeChat Official Account request timeout must be positive")
        if (
            max_image_bytes < WECHAT_MP_MIN_IMAGE_BYTES
            or max_image_bytes > WECHAT_MP_MAX_IMAGE_BYTES
        ):
            raise ValueError("WeChat Official Account image byte limit is invalid")
        if max_response_bytes < 1024 or max_response_bytes > 1024 * 1024:
            raise ValueError("WeChat Official Account response byte limit is invalid")
        if not math.isfinite(token_refresh_skew_seconds) or token_refresh_skew_seconds < 0:
            raise ValueError("WeChat Official Account token refresh skew must not be negative")

        self._client = client
        self._app_id = SecretStr(app_id.get_secret_value().strip())
        self._app_secret = SecretStr(app_secret.get_secret_value().strip())
        self._base_url = base_url.strip().rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._total_timeout_seconds = timeout_seconds
        self._max_image_bytes = max_image_bytes
        self._max_response_bytes = max_response_bytes
        self._token_refresh_skew_seconds = token_refresh_skew_seconds
        self._clock = clock
        self._token_cache: _CachedToken | None = None
        self._token_lock = asyncio.Lock()

    async def upload_inline_image(
        self,
        image_bytes: bytes,
        media_type: str,
        filename: str,
    ) -> WeChatInlineImage:
        try:
            normalized_media_type = _validate_image(
                image_bytes,
                media_type,
                max_bytes=min(self._max_image_bytes, WECHAT_MP_MAX_INLINE_IMAGE_BYTES),
                allowed_media_types=frozenset({"image/jpeg", "image/png"}),
            )
            _validate_filename(filename, media_type=normalized_media_type)
        except (TypeError, UnicodeError, ValueError):
            raise WeChatMpInvalidInputError(endpoint="media_uploadimg") from None
        response = await self._authenticated_request(
            endpoint="media_uploadimg",
            params={},
            files={"media": (filename, image_bytes, normalized_media_type)},
            json_payload=None,
        )
        url = response.payload.get("url")
        if not isinstance(url, str):
            raise WeChatMpInvalidResponseError(endpoint="media_uploadimg")
        try:
            normalized_url = _normalize_provider_image_url(url)
        except ValueError:
            raise WeChatMpInvalidResponseError(endpoint="media_uploadimg") from None
        return WeChatInlineImage(url=normalized_url)

    async def upload_thumb(
        self,
        image_bytes: bytes,
        media_type: str,
        filename: str,
    ) -> WeChatThumbMedia:
        try:
            normalized_media_type = _validate_image(
                image_bytes,
                media_type,
                max_bytes=min(self._max_image_bytes, WECHAT_MP_MAX_THUMB_BYTES),
                allowed_media_types=frozenset({"image/jpeg"}),
            )
            _validate_filename(filename, media_type=normalized_media_type)
        except (TypeError, UnicodeError, ValueError):
            raise WeChatMpInvalidInputError(endpoint="material_add_thumb") from None
        response = await self._authenticated_request(
            endpoint="material_add_thumb",
            params={"type": "thumb"},
            files={"media": (filename, image_bytes, normalized_media_type)},
            json_payload=None,
        )
        media_id = response.payload.get("media_id")
        if not _is_safe_provider_identifier(
            media_id,
            maximum=WECHAT_MP_MAX_DRAFT_MEDIA_ID_CHARACTERS,
        ):
            raise WeChatMpInvalidResponseError(endpoint="material_add_thumb")
        return WeChatThumbMedia(media_id=cast(str, media_id))

    async def add_draft(self, article: WeChatDraftArticleRequest) -> WeChatDraftCreated:
        try:
            _validate_draft_article(article)
        except (TypeError, UnicodeError, ValueError):
            raise WeChatMpInvalidInputError(endpoint="draft_add") from None
        provider_article: dict[str, object] = {
            "article_type": "news",
            "title": article.title,
            "author": article.author,
            "digest": article.digest,
            "content": article.content,
            "thumb_media_id": article.thumb_media_id,
            "need_open_comment": int(article.need_open_comment),
            "only_fans_can_comment": int(article.only_fans_can_comment),
        }
        if article.content_source_url is not None:
            provider_article["content_source_url"] = article.content_source_url
        response = await self._authenticated_request(
            endpoint="draft_add",
            params={},
            files=None,
            json_payload={"articles": [provider_article]},
        )
        media_id = response.payload.get("media_id")
        if not _is_safe_provider_identifier(
            media_id,
            maximum=WECHAT_MP_MAX_DRAFT_MEDIA_ID_CHARACTERS,
        ):
            raise WeChatMpInvalidResponseError(endpoint="draft_add")
        return WeChatDraftCreated(media_id=cast(str, media_id))

    async def _authenticated_request(
        self,
        *,
        endpoint: WeChatMpEndpoint,
        params: dict[str, str],
        files: dict[str, tuple[str, bytes, str]] | None,
        json_payload: dict[str, object] | None,
    ) -> _ProviderResponse:
        token = await self._get_access_token()
        for refresh_attempt in range(2):
            try:
                return await self._request_once(
                    endpoint=endpoint,
                    params={**params, "access_token": token.value},
                    files=files,
                    json_payload=json_payload,
                    authenticated=True,
                    unknown_on_timeout=True,
                )
            except WeChatMpTokenInvalidError:
                if refresh_attempt == 1:
                    raise
                token = await self._refresh_invalid_token(token.value)
        raise AssertionError("unreachable WeChat Official Account token refresh state")

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
            return await self._fetch_access_token(force_refresh=force_refresh)

    async def _refresh_invalid_token(self, stale_token: str) -> _CachedToken:
        """Coalesce concurrent refreshes for the same rejected token."""

        async with self._token_lock:
            cached = self._token_cache
            if (
                cached is not None
                and cached.value != stale_token
                and cached.refresh_at > self._clock()
            ):
                return cached
            self._token_cache = None
            return await self._fetch_access_token(force_refresh=True)

    async def _fetch_access_token(self, *, force_refresh: bool) -> _CachedToken:
        response = await self._request_once(
            endpoint="stable_token",
            params={},
            files=None,
            json_payload={
                "grant_type": "client_credential",
                "appid": self._app_id.get_secret_value(),
                "secret": self._app_secret.get_secret_value(),
                "force_refresh": force_refresh,
            },
            authenticated=False,
            unknown_on_timeout=False,
        )
        access_token = response.payload.get("access_token")
        expires_in = response.payload.get("expires_in")
        if (
            not _is_safe_provider_identifier(access_token, maximum=4096)
            or isinstance(expires_in, bool)
            or not isinstance(expires_in, int)
            or expires_in < 1
            or expires_in > 7200
        ):
            raise WeChatMpInvalidResponseError(endpoint="stable_token")
        early_seconds = min(self._token_refresh_skew_seconds, expires_in / 10)
        cached = _CachedToken(
            value=cast(str, access_token),
            refresh_at=self._clock() + expires_in - early_seconds,
        )
        self._token_cache = cached
        return cached

    async def _request_once(
        self,
        *,
        endpoint: WeChatMpEndpoint,
        params: dict[str, str],
        files: dict[str, tuple[str, bytes, str]] | None,
        json_payload: dict[str, object] | None,
        authenticated: bool,
        unknown_on_timeout: bool,
    ) -> _ProviderResponse:
        path = _ENDPOINT_PATHS[endpoint]
        try:
            async with asyncio.timeout(self._total_timeout_seconds):
                async with self._client.stream(
                    "POST",
                    f"{self._base_url}{path}",
                    params=params,
                    files=files,
                    json=json_payload,
                    follow_redirects=False,
                    headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                    timeout=self._timeout,
                ) as response:
                    if response.status_code < 200 or response.status_code >= 300:
                        raise _http_error(
                            endpoint=endpoint,
                            status_code=response.status_code,
                        )
                    body = await _read_bounded_response(
                        response,
                        endpoint=endpoint,
                        max_response_bytes=self._max_response_bytes,
                    )
        except WeChatOfficialAccountError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            if unknown_on_timeout:
                raise WeChatMpOutcomeUnknownError(endpoint=endpoint) from None
            raise WeChatMpTransientError(endpoint=endpoint) from None
        except httpx.RequestError:
            raise WeChatMpTransientError(endpoint=endpoint) from None

        payload = _parse_json_payload(body, endpoint=endpoint)
        _raise_for_provider_error(payload, endpoint=endpoint, authenticated=authenticated)
        return _ProviderResponse(payload=payload)


class WeChatOfficialAccountHttpClient(WeChatOfficialAccountApiClient):
    """Explicit settings-bound client; no default dependency graph constructs it."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        if (
            not settings.wechat_mp_enabled
            or settings.app_env != "development"
            or settings.wechat_mp_mode != "draft_only"
            or settings.wechat_mp_app_id is None
            or settings.wechat_mp_app_secret is None
        ):
            raise WeChatMpConfigurationError()
        self._owns_client = client is None
        super().__init__(
            client=client if client is not None else httpx.AsyncClient(),
            app_id=settings.wechat_mp_app_id,
            app_secret=settings.wechat_mp_app_secret,
            base_url=settings.wechat_mp_api_base_url,
            timeout_seconds=settings.wechat_mp_request_timeout_seconds,
            max_image_bytes=settings.wechat_mp_max_image_bytes,
            max_response_bytes=settings.wechat_mp_max_response_bytes,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


async def _read_bounded_response(
    response: httpx.Response,
    *,
    endpoint: WeChatMpEndpoint,
    max_response_bytes: int,
) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_bytes = int(content_length)
        except ValueError:
            raise WeChatMpInvalidResponseError(endpoint=endpoint) from None
        if declared_bytes < 0 or declared_bytes > max_response_bytes:
            raise WeChatMpInvalidResponseError(endpoint=endpoint)
    content_encoding = response.headers.get("content-encoding", "identity").strip().casefold()
    if content_encoding not in {"", "identity"}:
        raise WeChatMpInvalidResponseError(endpoint=endpoint)
    chunks: list[bytes] = []
    byte_count = 0
    async for chunk in response.aiter_bytes():
        byte_count += len(chunk)
        if byte_count > max_response_bytes:
            raise WeChatMpInvalidResponseError(endpoint=endpoint)
        chunks.append(chunk)
    return b"".join(chunks)


def _reject_duplicate_pairs(pairs: list[tuple[object, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            raise ValueError("invalid JSON object")
        result[key] = value
    return result


def _parse_json_payload(body: bytes, *, endpoint: WeChatMpEndpoint) -> dict[str, object]:
    try:
        raw_payload: Any = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise WeChatMpInvalidResponseError(endpoint=endpoint) from None
    if not isinstance(raw_payload, dict):
        raise WeChatMpInvalidResponseError(endpoint=endpoint)
    return cast(dict[str, object], raw_payload)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _raise_for_provider_error(
    payload: dict[str, object],
    *,
    endpoint: WeChatMpEndpoint,
    authenticated: bool,
) -> None:
    raw_code = payload.get("errcode")
    if raw_code is None:
        return
    if isinstance(raw_code, bool) or not isinstance(raw_code, int):
        raise WeChatMpInvalidResponseError(endpoint=endpoint)
    if raw_code == 0:
        return
    if authenticated and raw_code in _TOKEN_INVALID_CODES:
        raise WeChatMpTokenInvalidError(endpoint=endpoint, provider_code=raw_code)
    if raw_code in _RATE_LIMIT_CODES:
        raise WeChatMpRateLimitError(endpoint=endpoint, provider_code=raw_code)
    if raw_code in _TRANSIENT_CODES:
        raise WeChatMpTransientError(endpoint=endpoint, provider_code=raw_code)
    raise WeChatMpProviderRejectedError(endpoint=endpoint, provider_code=raw_code)


def _http_error(
    *,
    endpoint: WeChatMpEndpoint,
    status_code: int,
) -> WeChatOfficialAccountError:
    if status_code == 429:
        return WeChatMpRateLimitError(endpoint=endpoint, provider_code=status_code)
    if 500 <= status_code <= 599:
        return WeChatMpTransientError(endpoint=endpoint, provider_code=status_code)
    return WeChatMpProviderRejectedError(endpoint=endpoint, provider_code=status_code)


def _validate_base_url(base_url: str) -> None:
    if not isinstance(base_url, str):
        raise ValueError("WeChat Official Account API base URL must be HTTPS")
    parsed = urlsplit(base_url.strip())
    try:
        port = parsed.port
    except ValueError:
        raise ValueError(
            "WeChat Official Account API base URL must use the official host"
        ) from None
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != _WECHAT_MP_HOST
        or port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "WeChat Official Account API base URL must be exactly the official HTTPS origin"
        )


def _validate_secret(value: SecretStr) -> None:
    if not isinstance(value, SecretStr):
        raise TypeError("WeChat Official Account credentials must use SecretStr")
    secret = value.get_secret_value()
    if (
        not secret.strip()
        or len(secret) > 512
        or any(character.isspace() or ord(character) < 32 for character in secret)
    ):
        raise ValueError("WeChat Official Account credential is invalid")


def _validate_filename(value: str, *, media_type: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or any(character in value for character in "/\\\x00\r\n")
    ):
        raise ValueError("WeChat Official Account image filename is invalid")
    suffix = value.rsplit(".", 1)[-1].casefold() if "." in value else ""
    expected_suffixes = {
        "image/jpeg": frozenset({"jpg", "jpeg"}),
        "image/png": frozenset({"png"}),
    }
    if suffix not in expected_suffixes[media_type]:
        raise ValueError("WeChat Official Account image filename does not match its media type")


def _validate_image(
    image_bytes: bytes,
    media_type: str,
    *,
    max_bytes: int,
    allowed_media_types: frozenset[str],
) -> str:
    if not isinstance(image_bytes, bytes):
        raise TypeError("WeChat Official Account image input must be bytes")
    if len(image_bytes) < WECHAT_MP_MIN_IMAGE_BYTES or len(image_bytes) > max_bytes:
        raise ValueError("WeChat Official Account image input is outside the byte limit")
    if not isinstance(media_type, str):
        raise TypeError("WeChat Official Account image media type must be text")
    normalized = media_type.strip().casefold()
    if normalized == "image/jpg":
        normalized = "image/jpeg"
    signatures = {
        "image/png": b"\x89PNG\r\n\x1a\n",
        "image/jpeg": b"\xff\xd8\xff",
    }
    signature = signatures.get(normalized)
    if (
        normalized not in allowed_media_types
        or signature is None
        or not image_bytes.startswith(signature)
    ):
        raise ValueError("WeChat Official Account accepts matching JPEG or PNG images only")
    return normalized


def _is_safe_provider_identifier(value: object, *, maximum: int = 512) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and not any(character.isspace() or ord(character) < 32 for character in value)
    )


def _is_safe_https_url(value: str) -> bool:
    if any(character.isspace() or ord(character) < 32 for character in value):
        return False
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme.casefold() == "https"
        and parsed.hostname
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and len(value) <= 2048
    )


def _normalize_provider_image_url(value: str) -> str:
    """Accept only the documented WeChat image CDN and upgrade its HTTP example URL."""

    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or any(character.isspace() or ord(character) < 32 for character in value)
        or any(character in value for character in "\"'<>")
    ):
        raise ValueError("provider image URL is invalid")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("provider image URL is invalid") from None
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or parsed.hostname is None
        or parsed.hostname.casefold() not in _WECHAT_MP_IMAGE_HOSTS
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/")
        or parsed.path == "/"
        or parsed.fragment
    ):
        raise ValueError("provider image URL is invalid")
    return parsed._replace(scheme="https", netloc=parsed.hostname.casefold()).geturl()


def _validate_draft_article(article: WeChatDraftArticleRequest) -> None:
    if not isinstance(article, WeChatDraftArticleRequest):
        raise TypeError("draft article contract is invalid")
    if not _is_safe_draft_copy(
        article.title,
        maximum=WECHAT_MP_MAX_DRAFT_TITLE_CHARACTERS,
    ):
        raise ValueError("draft title is invalid")
    if not _is_safe_draft_copy(
        article.author,
        maximum=WECHAT_MP_MAX_DRAFT_AUTHOR_CHARACTERS,
    ):
        raise ValueError("draft author is invalid")
    if not _is_safe_draft_copy(
        article.digest,
        maximum=WECHAT_MP_MAX_DRAFT_DIGEST_CHARACTERS,
    ):
        raise ValueError("draft digest is invalid")
    if (
        not article.content.strip()
        or len(article.content) > WECHAT_MP_MAX_DRAFT_CONTENT_CHARACTERS
        or len(article.content.encode("utf-8")) > WECHAT_MP_MAX_DRAFT_CONTENT_BYTES
    ):
        raise ValueError("draft content is invalid")
    if not _is_safe_provider_identifier(
        article.thumb_media_id,
        maximum=WECHAT_MP_MAX_DRAFT_MEDIA_ID_CHARACTERS,
    ):
        raise ValueError("draft thumb media id is invalid")
    if article.content_source_url is not None:
        if (
            not _is_safe_https_url(article.content_source_url)
            or len(article.content_source_url.encode("utf-8"))
            > WECHAT_MP_MAX_CONTENT_SOURCE_URL_BYTES
        ):
            raise ValueError("draft source URL is invalid")
    if not isinstance(article.need_open_comment, bool) or not isinstance(
        article.only_fans_can_comment,
        bool,
    ):
        raise TypeError("draft comment policy is invalid")
    if article.only_fans_can_comment and not article.need_open_comment:
        raise ValueError("fans-only comments require comments to be enabled")


def _is_safe_draft_copy(value: object, *, maximum: int) -> bool:
    return bool(
        isinstance(value, str)
        and value.strip()
        and len(value) <= maximum
        and not any(ord(character) < 32 for character in value)
    )


__all__ = ["WeChatOfficialAccountApiClient", "WeChatOfficialAccountHttpClient"]
