from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.core.errors import PolicyRejectedError
from app.domain.entities import FetchedResponse, SourceProfile
from app.domain.enums import SourceTier
from app.live_smoke import run_live_smoke


class RecordingFetcher:
    def __init__(self) -> None:
        self.slugs: list[str] = []

    async def fetch(
        self,
        url: str,
        profile: SourceProfile,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchedResponse:
        del etag, last_modified
        self.slugs.append(profile.slug)
        if profile.slug == "blocked-source":
            raise PolicyRejectedError("non_public_address", "non-public DNS answer")
        return FetchedResponse(
            requested_url=url,
            final_url=url,
            status_code=200,
            media_type="text/html",
            body=b"ok",
            sha256="ok",
            fetched_at=datetime.now(UTC),
        )


def profile(slug: str) -> SourceProfile:
    return SourceProfile(
        source_id=uuid4(),
        source_version_id=uuid4(),
        slug=slug,
        display_name=slug,
        organization_type="test",
        tier=SourceTier.A,
        connector_key="test",
        entry_url=f"https://{slug}.example/articles",
        allowed_hosts=(f"{slug}.example",),
        allowed_path_prefixes=("/articles",),
        connector_version="test",
        parser_version="test",
        rate_limit_seconds=0,
    )


async def no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.asyncio
async def test_live_smoke_reports_all_sources_after_a_typed_failure() -> None:
    fetcher = RecordingFetcher()
    failures = await run_live_smoke(
        fetcher,
        [profile("blocked-source"), profile("healthy-source")],
        sleep=no_sleep,
    )

    assert fetcher.slugs == ["blocked-source", "healthy-source"]
    assert failures == [("blocked-source", "non_public_address")]
