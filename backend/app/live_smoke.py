from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence

from app.application.ports.acquisition import Fetcher
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.domain.entities import SourceProfile
from app.infrastructure.ingestion.fetcher import SafeHttpFetcher
from app.infrastructure.ingestion.source_profiles import SOURCE_SEEDS


def source_profiles() -> list[SourceProfile]:
    return [
        SourceProfile(
            source_id=seed.source_id,
            source_version_id=seed.source_version_id,
            slug=seed.slug,
            display_name=seed.display_name,
            organization_type=seed.organization_type,
            tier=seed.tier,
            connector_key=seed.connector_key,
            entry_url=seed.entry_url,
            allowed_hosts=seed.allowed_hosts,
            allowed_path_prefixes=seed.allowed_path_prefixes,
            connector_version=seed.connector_version,
            parser_version=seed.parser_version,
            language=seed.language,
            timezone=seed.timezone,
            rate_limit_seconds=seed.rate_limit_seconds,
        )
        for seed in SOURCE_SEEDS
    ]


async def run_live_smoke(
    fetcher: Fetcher,
    profiles: Sequence[SourceProfile],
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[tuple[str, str]]:
    failures: list[tuple[str, str]] = []
    for index, profile in enumerate(profiles):
        try:
            response = await fetcher.fetch(profile.entry_url, profile)
        except AppError as error:
            failures.append((profile.slug, error.code))
            print(f"{profile.slug}: ERROR {error.code}")
        else:
            print(f"{profile.slug}: HTTP {response.status_code}, {len(response.body)} bytes")
        if index + 1 < len(profiles):
            await sleep(profile.rate_limit_seconds)
    return failures


async def _main() -> None:
    settings = get_settings()
    configure_logging(json_output=settings.app_env != "development")
    failures = await run_live_smoke(SafeHttpFetcher(settings), source_profiles())
    if failures:
        failed = ", ".join(f"{slug}={code}" for slug, code in failures)
        raise SystemExit(f"Live source smoke failed: {failed}")


if __name__ == "__main__":
    asyncio.run(_main())
