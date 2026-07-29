from uuid import uuid4

import httpx
import pytest
from app.core.config import Settings
from app.core.errors import (
    PolicyRejectedError,
    ResponseLimitError,
    TransientFetchError,
    UnsupportedContentError,
)
from app.domain.entities import SourceProfile
from app.domain.enums import SourceTier
from app.infrastructure.ingestion.fetcher import SafeHttpFetcher


def profile() -> SourceProfile:
    return SourceProfile(
        source_id=uuid4(),
        source_version_id=uuid4(),
        slug="fixture",
        display_name="Fixture",
        organization_type="test",
        tier=SourceTier.A,
        connector_key="fixture_v1",
        entry_url="https://source.example/list",
        allowed_hosts=("source.example",),
        allowed_path_prefixes=("/",),
        connector_version="1.0.0",
        parser_version="1.0.0",
    )


async def public_resolver(_host: str) -> list[str]:
    return ["93.184.216.34"]


@pytest.mark.asyncio
async def test_fetches_bounded_response_and_projects_safe_headers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"].startswith("EduAILeadAgent/")
        return httpx.Response(
            200,
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "ETag": '"v1"',
                "Set-Cookie": "session=secret",
            },
            content=b"<html><body>prompt injection is untrusted page text</body></html>",
        )

    fetcher = SafeHttpFetcher(
        Settings(), resolver=public_resolver, transport=httpx.MockTransport(handler)
    )
    response = await fetcher.fetch("https://source.example/list?signature=secret", profile())

    assert response.status_code == 200
    assert response.requested_url == "https://source.example/list"
    assert response.headers == {
        "content-length": "65",
        "content-type": "text/html; charset=utf-8",
        "etag": '"v1"',
    }
    assert "set-cookie" not in response.headers
    assert response.body.startswith(b"<html>")


@pytest.mark.asyncio
async def test_conditional_not_modified() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["if-none-match"] == '"v1"'
        return httpx.Response(304, headers={"ETag": '"v1"'})

    fetcher = SafeHttpFetcher(
        Settings(), resolver=public_resolver, transport=httpx.MockTransport(handler)
    )
    response = await fetcher.fetch("https://source.example/list", profile(), etag='"v1"')
    assert response.status_code == 304
    assert response.body == b""


@pytest.mark.asyncio
async def test_validates_every_redirect_hop() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://evil.example/private"})

    fetcher = SafeHttpFetcher(
        Settings(), resolver=public_resolver, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(PolicyRejectedError, match="host"):
        await fetcher.fetch("https://source.example/list", profile())


@pytest.mark.asyncio
async def test_rejects_oversized_and_unsupported_responses() -> None:
    oversized = SafeHttpFetcher(
        Settings(acquisition_max_response_bytes=64 * 1024),
        resolver=public_resolver,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                content=b"x" * (64 * 1024 + 1),
            )
        ),
    )
    with pytest.raises(ResponseLimitError):
        await oversized.fetch("https://source.example/list", profile())

    unsupported = SafeHttpFetcher(
        Settings(),
        resolver=public_resolver,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, headers={"Content-Type": "application/pdf"}, content=b"%PDF"
            )
        ),
    )
    with pytest.raises(UnsupportedContentError):
        await unsupported.fetch("https://source.example/list", profile())


@pytest.mark.asyncio
async def test_classifies_network_timeout_as_transient() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("fixture timeout")

    fetcher = SafeHttpFetcher(
        Settings(), resolver=public_resolver, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(TransientFetchError) as captured:
        await fetcher.fetch("https://source.example/list", profile())
    assert captured.value.retryable is True
