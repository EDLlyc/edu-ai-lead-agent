from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from io import BytesIO
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image, UnidentifiedImageError

from app.core.config import Settings
from app.core.errors import (
    PermanentFetchError,
    PolicyRejectedError,
    ResponseLimitError,
    TransientFetchError,
    UnsupportedContentError,
)
from app.core.security import (
    Resolver,
    system_resolver,
    validate_allowlist,
    validate_public_resolution,
)
from app.domain.entities import (
    FetchedResponse,
    SourceImageReference,
    SourceProfile,
    ValidatedSourceImage,
)
from app.domain.value_objects import sha256_bytes

SOURCE_IMAGE_MAX_BYTES = 15 * 1024 * 1024
SOURCE_IMAGE_MAX_PIXELS = 40_000_000
SOURCE_IMAGE_MIN_WIDTH = 320
SOURCE_IMAGE_MIN_HEIGHT = 180
SOURCE_IMAGE_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_FORMAT_MEDIA_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class SafeSourceImageFetcher:
    """Fetch and fully validate one same-source editorial raster image."""

    def __init__(
        self,
        settings: Settings,
        *,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._resolver = resolver
        self._transport = transport

    async def fetch(
        self,
        reference: SourceImageReference,
        profile: SourceProfile,
    ) -> ValidatedSourceImage:
        article_page = validate_allowlist(
            reference.source_page_url,
            allowed_hosts=profile.allowed_hosts,
            allowed_path_prefixes=profile.allowed_path_prefixes,
            allow_http_fallback=False,
        )
        article_parts = urlsplit(article_page)
        if article_parts.query:
            raise PolicyRejectedError(
                "source_image_page_query_rejected",
                "source image page URL query is not allowed",
            )
        article_host = article_parts.hostname
        _validate_media_url(reference.image_url, profile, article_host=article_host)
        timeout = httpx.Timeout(
            connect=self._settings.acquisition_connect_timeout_seconds,
            read=self._settings.acquisition_read_timeout_seconds,
            write=self._settings.acquisition_connect_timeout_seconds,
            pool=self._settings.acquisition_connect_timeout_seconds,
        )
        try:
            async with asyncio.timeout(self._settings.acquisition_total_timeout_seconds):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=False,
                    headers={
                        "User-Agent": self._settings.acquisition_user_agent,
                        "Accept": "image/jpeg, image/png, image/webp",
                    },
                ) as client:
                    return await self._fetch_redirect_chain(
                        client,
                        reference.image_url,
                        profile,
                        article_host=article_host,
                    )
        except TimeoutError as error:
            raise TransientFetchError("source_image_total_timeout") from error
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise TransientFetchError("source_image_network_failure") from error

    async def _fetch_redirect_chain(
        self,
        client: httpx.AsyncClient,
        requested_url: str,
        profile: SourceProfile,
        *,
        article_host: str | None,
    ) -> ValidatedSourceImage:
        current_url = requested_url
        for redirect_count in range(self._settings.acquisition_max_redirects + 1):
            current_url = _validate_media_url(current_url, profile, article_host=article_host)
            host = urlsplit(current_url).hostname
            assert host is not None
            await validate_public_resolution(host, self._resolver)
            async with client.stream("GET", current_url) as response:
                client.cookies.clear()
                if response.status_code in _REDIRECT_STATUSES:
                    if redirect_count >= self._settings.acquisition_max_redirects:
                        raise PermanentFetchError("source_image_redirect_limit")
                    location = response.headers.get("location")
                    if not location:
                        raise PermanentFetchError("source_image_invalid_redirect")
                    current_url = urljoin(current_url, location)
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    raise TransientFetchError(f"source_image_http_{response.status_code}")
                if response.status_code >= 400:
                    raise PermanentFetchError(f"source_image_http_{response.status_code}")
                declared_type = _media_type(response.headers.get("content-type"))
                if declared_type not in SOURCE_IMAGE_MEDIA_TYPES:
                    raise UnsupportedContentError()
                declared_size = response.headers.get("content-length")
                if (
                    declared_size
                    and declared_size.isdigit()
                    and int(declared_size) > SOURCE_IMAGE_MAX_BYTES
                ):
                    raise ResponseLimitError()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > SOURCE_IMAGE_MAX_BYTES:
                        raise ResponseLimitError()
                width, height, detected_type = _validate_raster(bytes(body))
                if detected_type != declared_type:
                    raise PermanentFetchError(
                        "source_image_mime_mismatch",
                        "source image MIME does not match decoded bytes",
                    )
                immutable_body = bytes(body)
                fetched_at = datetime.now(UTC)
                return ValidatedSourceImage(
                    response=FetchedResponse(
                        requested_url=requested_url,
                        final_url=current_url,
                        status_code=response.status_code,
                        media_type=detected_type,
                        body=immutable_body,
                        sha256=sha256_bytes(immutable_body),
                        fetched_at=fetched_at,
                        headers={
                            key.lower(): value
                            for key, value in response.headers.items()
                            if key.lower()
                            in {"content-type", "content-length", "etag", "last-modified"}
                        },
                    ),
                    width=width,
                    height=height,
                )
        raise PermanentFetchError("source_image_redirect_limit")


def _validate_media_url(
    value: str,
    profile: SourceProfile,
    *,
    article_host: str | None,
) -> str:
    parts = urlsplit(value)
    if parts.query:
        raise PolicyRejectedError(
            "source_image_query_rejected", "source image URL query is not allowed"
        )
    normalized = validate_allowlist(
        value,
        allowed_hosts=profile.allowed_hosts,
        allowed_path_prefixes=profile.allowed_path_prefixes,
        allow_http_fallback=False,
    )
    normalized_host = urlsplit(normalized).hostname
    if article_host is None or normalized_host != article_host.rstrip(".").casefold():
        raise PolicyRejectedError(
            "source_image_cross_host_rejected",
            "source image host must match the article host",
        )
    return normalized


def _validate_raster(body: bytes) -> tuple[int, int, str]:
    if not body:
        raise PermanentFetchError("source_image_empty")
    try:
        with Image.open(BytesIO(body)) as image:
            media_type = _FORMAT_MEDIA_TYPES.get(image.format or "")
            if media_type is None:
                raise UnsupportedContentError()
            if getattr(image, "is_animated", False) or int(getattr(image, "n_frames", 1)) != 1:
                raise PermanentFetchError("source_image_animated_rejected")
            width, height = image.size
            if width < SOURCE_IMAGE_MIN_WIDTH or height < SOURCE_IMAGE_MIN_HEIGHT:
                raise PermanentFetchError("source_image_too_small")
            if width > 8192 or height > 8192 or width * height > SOURCE_IMAGE_MAX_PIXELS:
                raise PermanentFetchError("source_image_dimensions_exceeded")
            image.load()
    except Image.DecompressionBombError as error:
        raise PermanentFetchError("source_image_dimensions_exceeded") from error
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise PermanentFetchError("source_image_decode_failed") from error
    return width, height, media_type


def _media_type(value: str | None) -> str | None:
    return value.split(";", 1)[0].strip().lower() if value else None
