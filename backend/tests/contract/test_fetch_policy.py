from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from app.core.config import Settings
from app.core.errors import PolicyRejectedError, TransientFetchError
from app.domain.entities import SourceProfile
from app.domain.enums import SourceTier
from app.infrastructure.ingestion.fetcher import SafeHttpFetcher


def _profile(
    *,
    robots_status: str = "allowed",
    terms_reviewed: bool = True,
    allow_http_fallback: bool = False,
) -> SourceProfile:
    return SourceProfile(
        source_id=uuid4(),
        source_version_id=uuid4(),
        slug="policy-test",
        display_name="policy-test",
        organization_type="test",
        tier=SourceTier.A,
        connector_key="test",
        entry_url="https://source.example/articles",
        allowed_hosts=("source.example",),
        allowed_path_prefixes=("/articles",),
        connector_version="test",
        parser_version="test",
        rate_limit_seconds=0,
        robots_status=robots_status,
        terms_reviewed_at=datetime(2026, 8, 1, tzinfo=UTC) if terms_reviewed else None,
        allow_http_fallback=allow_http_fallback,
    )


async def _resolver(_host: str) -> list[str]:
    return ["93.184.216.34"]


@pytest.mark.asyncio
async def test_429_retry_after_is_exposed_and_clamped() -> None:
    fetcher = SafeHttpFetcher(
        Settings(acquisition_max_retry_after_seconds=7),
        resolver=_resolver,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                429,
                headers={"Retry-After": "99"},
                content=b"ignored",
            )
        ),
    )

    with pytest.raises(TransientFetchError) as captured:
        await fetcher.fetch("https://source.example/articles", _profile())

    assert captured.value.code == "http_429"
    assert captured.value.retry_after_seconds == 7


@pytest.mark.asyncio
async def test_disallowed_recorded_policy_stops_before_transport() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, content=b"ok")

    fetcher = SafeHttpFetcher(
        Settings(),
        resolver=_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PolicyRejectedError) as captured:
        await fetcher.fetch(
            "https://source.example/articles",
            _profile(robots_status="disallowed"),
        )

    assert captured.value.code == "source_policy_disallowed"
    assert called is False


@pytest.mark.asyncio
async def test_manual_review_without_terms_record_is_terminal() -> None:
    fetcher = SafeHttpFetcher(
        Settings(),
        resolver=_resolver,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"ok")),
    )

    with pytest.raises(PolicyRejectedError) as captured:
        await fetcher.fetch(
            "https://source.example/articles",
            _profile(robots_status="manual_review", terms_reviewed=False),
        )

    assert captured.value.code == "source_policy_unreviewed"


@pytest.mark.asyncio
async def test_http_fallback_is_denied_by_default_before_transport() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, content=b"<html>unexpected</html>")

    fetcher = SafeHttpFetcher(
        Settings(),
        resolver=_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PolicyRejectedError) as captured:
        await fetcher.fetch("http://source.example/articles", _profile())

    assert captured.value.code == "https_required"
    assert called is False


@pytest.mark.asyncio
async def test_http_fallback_is_source_scoped_and_keeps_public_dns_validation() -> None:
    fetcher = SafeHttpFetcher(
        Settings(),
        resolver=_resolver,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                content=f"<html><body>{request.url}</body></html>".encode(),
            )
        ),
    )

    response = await fetcher.fetch(
        "http://source.example/articles",
        _profile(allow_http_fallback=True),
    )

    assert response.status_code == 200
    assert response.final_url == "http://source.example/articles"
