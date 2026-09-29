# ruff: noqa: RUF001
from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.application.services.enqueue_runs import enqueue_manual_run
from app.application.services.execute_acquisition import AcquisitionExecutor
from app.core.errors import PermanentFetchError
from app.domain.entities import FetchedResponse, SourceImageReference, SourceProfile
from app.domain.enums import JobStatus
from app.domain.value_objects import sha256_bytes
from app.infrastructure.db.models import AcquisitionJobModel, SourceArticleImageModel
from app.infrastructure.db.repositories import PostgresAcquisitionRepository, seed_sources
from app.infrastructure.ingestion.source_profiles import SOURCE_SEEDS
from app.infrastructure.storage.minio_snapshot_store import MinioSnapshotStore
from sqlalchemy import select

from .conftest import IntegrationContext
from .test_title_relevance_ingestion import GOV_YAOWEN_FIXTURE_ROOT, _cancel_nonterminal, _no_sleep

SOURCE_SLUG = "china-government-news"
FETCHED_AT = datetime(2026, 8, 27, 1, 0, tzinfo=UTC)


class ChangingDetailFetcher:
    """The article text stays the same; the page HTML gains a counter on every fetch."""

    def __init__(self) -> None:
        self.detail_fetches = 0
        # A unique article per test run, so the shared test database never sees it before.
        self.target = f"content_{uuid4().int % 10**9}.htm"

    async def fetch(
        self,
        url: str,
        profile: SourceProfile,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchedResponse:
        del etag, last_modified
        if url == profile.entry_url:
            body = json.dumps(
                {
                    "data": {
                        "list": [
                            {
                                "TITLE": "融合升级 新型工业化提速",
                                "URL": f"https://www.gov.cn/yaowen/liebiao/202608/{self.target}",
                                "DOCRELPUBTIME": "2026-08-26 23:04",
                            }
                        ]
                    }
                },
                ensure_ascii=False,
            ).encode()
            media_type = "application/json"
        elif url.endswith(self.target):
            self.detail_fetches += 1
            html = (GOV_YAOWEN_FIXTURE_ROOT / "detail.html").read_text(encoding="utf-8")
            # Unique article text (a unique content hash); the head comment below changes the
            # page bytes on every fetch without changing that text.
            html = html.replace("</p>", f"本条为图片回归测试文章，编号{self.target}。</p>", 1)
            html = html.replace(
                "</head>",
                '<meta property="og:image" content="/yaowen/liebiao/202608/lead.jpg">'
                f"<!-- page view counter {self.detail_fetches} --></head>",
                1,
            )
            body = html.encode()
            media_type = "text/html"
        else:
            body = (
                "<!doctype html><html><head><title>有关部门部署防汛救灾工作</title></head>"
                "<body><main class='pages_content'>"
                f"<p>{'有关部门部署防汛救灾和应急保障工作,要求压实责任并保障群众安全。' * 5}</p>"
                "</main></body></html>"
            ).encode()
            media_type = "text/html"
        return FetchedResponse(
            requested_url=url,
            final_url=url,
            status_code=200,
            media_type=media_type,
            body=body,
            sha256=sha256_bytes(body),
            fetched_at=FETCHED_AT,
            headers={},
        )


class UnavailableImageFetcher:
    async def fetch(self, reference: SourceImageReference, profile: SourceProfile) -> None:
        del reference, profile
        raise PermanentFetchError("source_image_http_404")


async def _run(context: IntegrationContext, fetcher: ChangingDetailFetcher) -> AcquisitionJobModel:
    await _cancel_nonterminal(context)
    repository = PostgresAcquisitionRepository(context.session_factory)
    source = next(seed for seed in SOURCE_SEEDS if seed.slug == SOURCE_SLUG)
    settings = context.settings.model_copy(
        update={"acquisition_first_run_item_limit": 2, "acquisition_daily_item_limit": 2}
    )
    run_id, _created = await enqueue_manual_run(
        repository,
        settings,
        source_ids=[source.source_id],
        idempotency_key=f"image-refetch-{uuid4()}",
    )
    executor = AcquisitionExecutor(
        repository,
        fetcher,
        MinioSnapshotStore(context.settings),
        settings,
        source_image_fetcher=UnavailableImageFetcher(),
        sleep=_no_sleep,
        jitter=lambda: 0.0,
        clock=lambda: FETCHED_AT,
    )
    assert await executor.execute_next("image-refetch-worker") is True
    async with context.session_factory() as session:
        job = await session.scalar(
            select(AcquisitionJobModel).where(AcquisitionJobModel.run_id == run_id)
        )
    assert job is not None
    return job


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_refetching_a_known_article_with_changed_html_does_not_fail_the_source(
    integration_context: IntegrationContext,
) -> None:
    async with integration_context.session_factory() as session:
        await seed_sources(session)
    fetcher = ChangingDetailFetcher()

    first = await _run(integration_context, fetcher)
    second = await _run(integration_context, fetcher)

    assert fetcher.detail_fetches >= 2
    assert first.status == JobStatus.SUCCEEDED.value
    # Before the fix the second fetch raised `conflict` from the source-image lineage check.
    assert second.status == JobStatus.SUCCEEDED.value, second.error_code
    assert second.error_code is None
    async with integration_context.session_factory() as session:
        images = list(
            (
                await session.scalars(
                    select(SourceArticleImageModel).where(
                        SourceArticleImageModel.image_url.like("%/yaowen/liebiao/202608/lead.jpg")
                    )
                )
            ).all()
        )
    # The image discovered from the first snapshot is kept; the changed re-fetch adds none.
    assert len({image.detail_snapshot_id for image in images}) == 1
