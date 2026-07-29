from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import Settings
from app.core.errors import (
    PermanentFetchError,
    ResponseLimitError,
    TransientFetchError,
    UnsupportedContentError,
)
from app.core.logging import safe_url
from app.core.security import (
    Resolver,
    system_resolver,
    validate_allowlist,
    validate_public_resolution,
)
from app.domain.entities import FetchedResponse, SourceProfile
from app.domain.value_objects import sha256_bytes

ACCEPTED_MEDIA_TYPES = {
    "application/json",
    "application/ld+json",
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
    "text/html",
    "text/plain",
}
SAFE_RESPONSE_HEADERS = {"etag", "last-modified", "content-type", "content-length"}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class SafeHttpFetcher:
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
        url: str,
        profile: SourceProfile,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchedResponse:
        headers = {
            "User-Agent": self._settings.acquisition_user_agent,
            "Accept": "application/json, text/html;q=0.9, application/xml;q=0.8, text/plain;q=0.5",
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
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
                    headers=headers,
                ) as client:
                    return await self._fetch_redirect_chain(client, url, profile)
        except TimeoutError as error:
            raise TransientFetchError("total_timeout") from error
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise TransientFetchError("network_failure") from error

    async def _fetch_redirect_chain(
        self, client: httpx.AsyncClient, requested_url: str, profile: SourceProfile
    ) -> FetchedResponse:
        current_url = requested_url
        for redirect_count in range(self._settings.acquisition_max_redirects + 1):
            current_url = validate_allowlist(
                current_url,
                allowed_hosts=profile.allowed_hosts,
                allowed_path_prefixes=profile.allowed_path_prefixes,
            )
            host = urlsplit(current_url).hostname
            assert host is not None
            await validate_public_resolution(host, self._resolver)
            async with client.stream("GET", current_url) as response:
                client.cookies.clear()
                if response.status_code in REDIRECT_STATUSES:
                    if redirect_count >= self._settings.acquisition_max_redirects:
                        raise PermanentFetchError(
                            "redirect_limit", "source redirected too many times"
                        )
                    location = response.headers.get("location")
                    if not location:
                        raise PermanentFetchError(
                            "invalid_redirect", "source redirect did not include a location"
                        )
                    current_url = urljoin(current_url, location)
                    continue
                if response.status_code == 304:
                    return self._build_response(requested_url, current_url, response, b"")
                if response.status_code == 429 or response.status_code >= 500:
                    raise TransientFetchError(f"http_{response.status_code}")
                if response.status_code >= 400:
                    raise PermanentFetchError(f"http_{response.status_code}")
                declared_type = _media_type(response.headers.get("content-type"))
                if declared_type is not None and declared_type not in ACCEPTED_MEDIA_TYPES:
                    raise UnsupportedContentError
                content_length = response.headers.get("content-length")
                if content_length and content_length.isdigit():
                    if int(content_length) > self._settings.acquisition_max_response_bytes:
                        raise ResponseLimitError
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self._settings.acquisition_max_response_bytes:
                        raise ResponseLimitError
                if declared_type is None and not _looks_like_supported_text(bytes(body)):
                    raise UnsupportedContentError
                return self._build_response(requested_url, current_url, response, bytes(body))
        raise PermanentFetchError("redirect_limit")

    @staticmethod
    def _build_response(
        requested_url: str, final_url: str, response: httpx.Response, body: bytes
    ) -> FetchedResponse:
        headers = {
            key.lower(): value
            for key, value in response.headers.items()
            if key.lower() in SAFE_RESPONSE_HEADERS
        }
        return FetchedResponse(
            requested_url=safe_url(requested_url),
            final_url=safe_url(final_url),
            status_code=response.status_code,
            media_type=_media_type(response.headers.get("content-type")),
            body=body,
            sha256=sha256_bytes(body),
            fetched_at=datetime.now(UTC),
            headers=headers,
        )


def _media_type(value: str | None) -> str | None:
    if value is None:
        return None
    return value.split(";", 1)[0].strip().lower()


def _looks_like_supported_text(body: bytes) -> bool:
    prefix = body.lstrip()[:100].lower()
    if prefix.startswith((b"{", b"[", b"<!doctype", b"<html", b"<?xml", b"<rss", b"<feed")):
        return True
    try:
        body[:1024].decode("utf-8")
    except UnicodeDecodeError:
        return False
    return bool(body)
