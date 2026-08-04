from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.api_main import app
from app.application.services.enqueue_runs import enqueue_manual_run
from app.application.services.execute_acquisition import AcquisitionExecutor
from app.domain.entities import FetchedResponse, SourceProfile
from app.domain.enums import JobStatus, ObservationOutcome, RunStatus
from app.domain.value_objects import sha256_bytes
from app.infrastructure.db.models import (
    AcquisitionJobModel,
    EvidenceCandidateModel,
    SourceCursorModel,
    SourceFetchLeaseModel,
    SourceObservationModel,
)
from app.infrastructure.db.repositories import (
    PostgresAcquisitionRepository,
    get_run,
    seed_sources,
)
from app.infrastructure.ingestion.source_profiles import SOURCE_SEEDS
from app.infrastructure.storage.minio_snapshot_store import MinioSnapshotStore
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from .conftest import IntegrationContext


class RelevanceFixtureFetcher:
    def __init__(self, records: list[dict[str, str]]) -> None:
        self.records = records
        self.requested_urls: list[str] = []

    async def fetch(
        self,
        url: str,
        profile: SourceProfile,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchedResponse:
        del etag, last_modified
        self.requested_urls.append(url)
        if url == profile.entry_url:
            body = json.dumps({"data": {"list": self.records}}, ensure_ascii=False).encode()
            media_type = "application/json"
        else:
            record = next(record for record in self.records if record["URL"] == url)
            title = record["TITLE"]
            body = (
                "<!doctype html><html><head>"
                f"<title>{title}</title>"
                f'<link rel="canonical" href="{url}">'
                '</head><body><main class="pages_content">'
                f"<p>{title}。这是用于验证标题相关性过滤、不可变快照和下游交接的受控正文,"
                "内容长度足以通过解析器,并且不会触发任何外部模型或任意网站请求。</p>"
                "<p>第二段继续提供确定性的测试文本,用于证明候选正文来自已存储详情快照。</p>"
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
            fetched_at=datetime(2026, 7, 29, 1, 0, tzinfo=UTC),
            headers={},
        )


async def _no_sleep(_seconds: float) -> None:
    return None


async def _cancel_nonterminal(context: IntegrationContext) -> None:
    async with context.session_factory() as session:
        await session.execute(
            update(AcquisitionJobModel)
            .where(
                AcquisitionJobModel.status.in_(
                    [
                        JobStatus.QUEUED.value,
                        JobStatus.RUNNING.value,
                        JobStatus.RETRY_SCHEDULED.value,
                    ]
                )
            )
            .values(status=JobStatus.CANCELLED.value, completed_at=datetime.now(UTC))
        )
        await session.execute(SourceFetchLeaseModel.__table__.delete())
        await session.commit()


async def _execute_government_run(
    context: IntegrationContext,
    fetcher: RelevanceFixtureFetcher,
    *,
    sleep: Callable[[float], Awaitable[None]] = _no_sleep,
) -> tuple[object, AcquisitionJobModel]:
    await _cancel_nonterminal(context)
    async with context.session_factory() as session:
        await seed_sources(session)
    repository = PostgresAcquisitionRepository(context.session_factory)
    run_id, created = await enqueue_manual_run(
        repository,
        context.settings,
        source_ids=[SOURCE_SEEDS[0].source_id],
        idempotency_key=f"title-relevance-{uuid4()}",
    )
    assert created is True
    executor = AcquisitionExecutor(
        repository,
        fetcher,
        MinioSnapshotStore(context.settings),
        context.settings,
        sleep=sleep,
        jitter=lambda: 0.0,
    )
    assert await executor.execute_next("title-relevance-worker") is True
    async with context.session_factory() as session:
        run = await get_run(session, run_id)
        job = await session.scalar(
            select(AcquisitionJobModel).where(AcquisitionJobModel.run_id == run_id)
        )
    assert job is not None
    return run, job


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_mixed_list_filters_before_detail_fetch_and_exposes_stored_handoff(
    integration_context: IntegrationContext,
) -> None:
    entry_url = SOURCE_SEEDS[0].entry_url
    records = [
        {
            "TITLE": "教育数字化公共服务持续完善",
            "URL": "https://www.gov.cn/zhengce/content/202607/content_mixed_unrelated.htm",
            "DOCRELPUBTIME": "2026-07-30",
        },
        {
            "TITLE": "人工智能教育治理标准发布",
            "URL": "https://www.gov.cn/zhengce/content/202607/content_mixed_ai_new.htm",
            "DOCRELPUBTIME": "2026-07-29",
        },
        {
            "TITLE": "机器人支持课堂实验教学",
            "URL": "https://www.gov.cn/zhengce/content/202607/content_mixed_ai_old.htm",
            "DOCRELPUBTIME": "2026-07-28",
        },
    ]
    fetcher = RelevanceFixtureFetcher(records)
    sleep_calls: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    run, job = await _execute_government_run(integration_context, fetcher, sleep=record_sleep)

    assert run.status == RunStatus.SUCCEEDED.value
    assert run.new_count == 1
    assert run.filtered_count == 1
    assert job.outcome == "succeeded"
    assert job.filtered_count == 1
    assert fetcher.requested_urls == [entry_url, records[1]["URL"]]
    assert sleep_calls == pytest.approx([SOURCE_SEEDS[0].rate_limit_seconds], abs=0.2)

    async with integration_context.session_factory() as session:
        cursor = await session.get(SourceCursorModel, SOURCE_SEEDS[0].source_version_id)
        candidate = await session.scalar(
            select(EvidenceCandidateModel).where(
                EvidenceCandidateModel.source_version_id == SOURCE_SEEDS[0].source_version_id,
                EvidenceCandidateModel.source_item_id == "content_mixed_ai_new.htm",
            )
        )
        filter_observation = await session.scalar(
            select(SourceObservationModel).where(
                SourceObservationModel.job_id == job.id,
                SourceObservationModel.outcome == ObservationOutcome.FILTERED.value,
            )
        )
    assert cursor is not None and cursor.last_item_id == "content_mixed_unrelated.htm"
    assert candidate is not None
    assert candidate.title == records[1]["TITLE"]
    assert candidate.relevance_rule_version == "ai-title-v1"
    assert candidate.extraction_metadata["relevance_rule_version"] == "ai-title-v1"
    assert "人工智能" in candidate.extraction_metadata["matched_title_terms"]
    assert filter_observation is not None
    assert filter_observation.observation_metadata == {
        "scanned_count": 3,
        "relevant_count": 2,
        "accepted_count": 1,
        "filtered_count": 1,
        "deferred_relevant_count": 1,
        "relevance_rule_version": "ai-title-v1",
    }

    app.state.settings = integration_context.settings
    app.state.session_factory = integration_context.session_factory
    request_count_before_api = len(fetcher.requested_urls)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get(
            "/api/v1/evidence-candidates",
            params={
                "source_id": str(SOURCE_SEEDS[0].source_id),
                "relevance_rule_version": "ai-title-v1",
                "limit": 100,
            },
        )
        assert listed.status_code == 200
        summary = next(item for item in listed.json()["items"] if item["id"] == str(candidate.id))
        assert summary["source_slug"] == SOURCE_SEEDS[0].slug
        assert summary["source_display_name"] == SOURCE_SEEDS[0].display_name
        assert summary["original_url"] == records[1]["URL"]
        assert summary["canonical_url"] == records[1]["URL"]
        assert summary["relevance_rule_version"] == "ai-title-v1"

        legacy_queue = await client.get(
            "/api/v1/evidence-candidates",
            params={
                "source_id": str(SOURCE_SEEDS[0].source_id),
                "relevance_rule_version": "legacy-unfiltered",
                "limit": 100,
            },
        )
        assert legacy_queue.status_code == 200
        assert all(item["id"] != str(candidate.id) for item in legacy_queue.json()["items"])

        detail = await client.get(f"/api/v1/evidence-candidates/{candidate.id}")
        assert detail.status_code == 200
        assert detail.json()["clean_text"] == candidate.clean_text
        assert detail.json()["snapshot"]["sha256"]
        assert any(
            observation["metadata"].get("relevance_rule_version") == "ai-title-v1"
            for observation in detail.json()["observations"]
        )
    assert len(fetcher.requested_urls) == request_count_before_api


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_zero_match_succeeds_without_detail_request_and_advances_raw_cursor(
    integration_context: IntegrationContext,
) -> None:
    records = [
        {
            "TITLE": "文化产业发展规划印发",
            "URL": "https://www.gov.cn/zhengce/content/202607/content_zero_new.htm",
            "DOCRELPUBTIME": "2026-07-30",
        },
        {
            "TITLE": "教育数字化服务持续完善",
            "URL": "https://www.gov.cn/zhengce/content/202607/content_zero_old.htm",
            "DOCRELPUBTIME": "2026-07-29",
        },
    ]
    fetcher = RelevanceFixtureFetcher(records)

    run, job = await _execute_government_run(integration_context, fetcher)

    assert run.status == RunStatus.SUCCEEDED.value
    assert run.new_count == 0
    assert run.filtered_count == 2
    assert job.status == JobStatus.SUCCEEDED.value
    assert job.outcome == ObservationOutcome.NO_RELEVANT_ITEMS.value
    assert job.filtered_count == 2
    assert fetcher.requested_urls == [SOURCE_SEEDS[0].entry_url]

    async with integration_context.session_factory() as session:
        cursor = await session.get(SourceCursorModel, SOURCE_SEEDS[0].source_version_id)
        observations = list(
            (
                await session.scalars(
                    select(SourceObservationModel).where(SourceObservationModel.job_id == job.id)
                )
            ).all()
        )
        candidates = list(
            (
                await session.scalars(
                    select(EvidenceCandidateModel).where(
                        EvidenceCandidateModel.source_version_id
                        == SOURCE_SEEDS[0].source_version_id,
                        EvidenceCandidateModel.source_item_id.in_(
                            ["content_zero_new.htm", "content_zero_old.htm"]
                        ),
                    )
                )
            ).all()
        )
    assert cursor is not None and cursor.last_item_id == "content_zero_new.htm"
    assert candidates == []
    no_match = next(
        observation
        for observation in observations
        if observation.outcome == ObservationOutcome.NO_RELEVANT_ITEMS.value
    )
    assert no_match.observation_metadata == {
        "scanned_count": 2,
        "relevant_count": 0,
        "accepted_count": 0,
        "filtered_count": 2,
        "deferred_relevant_count": 0,
        "relevance_rule_version": "ai-title-v1",
    }
