from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.api_main import app
from app.application.services.enqueue_runs import enqueue_manual_run
from app.application.services.execute_acquisition import AcquisitionExecutor
from app.core.config import Settings
from app.domain.editorial_relevance import SCIENCE_TECH_EDITORIAL_RULE_VERSION
from app.domain.entities import FetchedResponse, SourceProfile
from app.domain.enums import JobStatus, ObservationOutcome, RunStatus
from app.domain.value_objects import sha256_bytes
from app.infrastructure.db.models import (
    AcquisitionJobModel,
    EvidenceCandidateModel,
    SourceCursorModel,
    SourceFetchLeaseModel,
    SourceModel,
    SourceObservationModel,
    SourceVersionModel,
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

FIXTURE_EVALUATED_AT = datetime(2026, 7, 30, 1, 0, tzinfo=UTC)
XINHUA_EVALUATED_AT = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
XINHUA_FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "sources" / "xinhua_tech_v1"


def fixture_clock() -> datetime:
    return FIXTURE_EVALUATED_AT


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


class XinhuaAerospaceFixtureFetcher:
    def __init__(self) -> None:
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
        path = "list.html" if url == profile.entry_url else "detail.html"
        body = (XINHUA_FIXTURE_ROOT / path).read_bytes()
        return FetchedResponse(
            requested_url=url,
            final_url=url,
            status_code=200,
            media_type="text/html",
            body=body,
            sha256=sha256_bytes(body),
            fetched_at=XINHUA_EVALUATED_AT,
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
    settings: Settings | None = None,
    seed_before_run: bool = True,
) -> tuple[object, AcquisitionJobModel]:
    await _cancel_nonterminal(context)
    if seed_before_run:
        async with context.session_factory() as session:
            await seed_sources(session)
    repository = PostgresAcquisitionRepository(context.session_factory)
    run_id, created = await enqueue_manual_run(
        repository,
        settings or context.settings,
        source_ids=[SOURCE_SEEDS[0].source_id],
        idempotency_key=f"title-relevance-{uuid4()}",
    )
    assert created is True
    executor = AcquisitionExecutor(
        repository,
        fetcher,
        MinioSnapshotStore(context.settings),
        settings or context.settings,
        sleep=sleep,
        jitter=lambda: 0.0,
        clock=fixture_clock,
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
async def test_xinhua_aerospace_recovery_is_frontier_candidate_under_current_rule(
    integration_context: IntegrationContext,
) -> None:
    await _cancel_nonterminal(integration_context)
    async with integration_context.session_factory() as session:
        await seed_sources(session)
    xinhua = next(seed for seed in SOURCE_SEEDS if seed.slug == "xinhua-tech")
    repository = PostgresAcquisitionRepository(integration_context.session_factory)
    run_id, created = await enqueue_manual_run(
        repository,
        integration_context.settings,
        source_ids=[xinhua.source_id],
        idempotency_key=f"xinhua-aerospace-{uuid4()}",
    )
    assert created is True
    fetcher = XinhuaAerospaceFixtureFetcher()
    executor = AcquisitionExecutor(
        repository,
        fetcher,
        MinioSnapshotStore(integration_context.settings),
        integration_context.settings,
        sleep=_no_sleep,
        jitter=lambda: 0.0,
        clock=lambda: XINHUA_EVALUATED_AT,
    )

    assert await executor.execute_next("xinhua-aerospace-worker") is True

    async with integration_context.session_factory() as session:
        run = await get_run(session, run_id)
        candidate = await session.scalar(
            select(EvidenceCandidateModel).where(
                EvidenceCandidateModel.source_version_id == xinhua.source_version_id,
                EvidenceCandidateModel.original_url
                == "https://www.news.cn/tech/20260819/661cedb9b6cf44a6976a167bf60b5d73/c.html",
            )
        )
        observation = await session.scalar(
            select(SourceObservationModel).where(
                SourceObservationModel.run_id == run_id,
                SourceObservationModel.outcome == ObservationOutcome.NEW.value,
            )
        )
    assert run.new_count == 1
    assert candidate is not None
    assert candidate.relevance_rule_version == SCIENCE_TECH_EDITORIAL_RULE_VERSION
    assert candidate.extraction_metadata["editorial_cohort"] == "frontier_science_technology"
    assert candidate.extraction_metadata["content_signals"] == ["completed_progress"]
    assert candidate.extraction_metadata["matched_title_progress_terms"] == [
        "aerospace_recovery_or_landing"
    ]
    assert observation is not None
    assert observation.observation_metadata["science_tech_editorial_rule_version"] == (
        SCIENCE_TECH_EDITORIAL_RULE_VERSION
    )
    assert fetcher.requested_urls == [xinhua.entry_url, candidate.original_url]


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_historical_science_ai_education_source_version_keeps_its_hard_boundary(
    integration_context: IntegrationContext,
) -> None:
    seed = SOURCE_SEEDS[0]
    legacy_version_id = uuid4()
    async with integration_context.session_factory() as session:
        await seed_sources(session)
        source = await session.get(SourceModel, seed.source_id)
        current = await session.get(SourceVersionModel, seed.source_version_id)
        assert source is not None and current is not None
        session.add(
            SourceVersionModel(
                id=legacy_version_id,
                source_id=current.source_id,
                version=current.version + 100_000,
                trust_tier=current.trust_tier,
                connector_key=current.connector_key,
                entry_url=current.entry_url,
                allowed_hosts=current.allowed_hosts,
                allowed_path_prefixes=current.allowed_path_prefixes,
                cadence=current.cadence,
                timezone=current.timezone,
                language=current.language,
                robots_status=current.robots_status,
                terms_reviewed_at=current.terms_reviewed_at,
                rate_limit_seconds=current.rate_limit_seconds,
                connector_version=current.connector_version,
                parser_version=current.parser_version,
                relevance_rule_version="science-ai-education-v1",
                allow_http_fallback=current.allow_http_fallback,
                topic_priority_policy=current.topic_priority_policy,
                config_fingerprint=uuid4().hex,
            )
        )
        await session.flush()
        source.active_version_id = legacy_version_id
        await session.commit()

    records = [
        {
            "TITLE": "人工智能新算法刷新推理纪录",
            "URL": "https://www.gov.cn/zhengce/content/202607/content_legacy_frontier.htm",
            "DOCRELPUBTIME": "2026-07-30",
        }
    ]
    fetcher = RelevanceFixtureFetcher(records)
    run, job = await _execute_government_run(
        integration_context,
        fetcher,
        seed_before_run=False,
    )

    assert run.new_count == 0
    assert job.outcome == ObservationOutcome.NO_RELEVANT_ITEMS.value
    async with integration_context.session_factory() as session:
        no_match = await session.scalar(
            select(SourceObservationModel).where(
                SourceObservationModel.job_id == job.id,
                SourceObservationModel.outcome == ObservationOutcome.NO_RELEVANT_ITEMS.value,
            )
        )
        await seed_sources(session)
    assert no_match is not None
    assert no_match.observation_metadata["relevance_rule_version"] == ("science-ai-education-v1")


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_tiered_list_order_is_education_then_frontier_then_neutral_and_stable(
    integration_context: IntegrationContext,
) -> None:
    records = [
        {
            "TITLE": "文化产业发展规划发布",
            "URL": "https://www.gov.cn/zhengce/content/202607/content_tiered_neutral.htm",
            "DOCRELPUBTIME": "2026-07-30",
        },
        {
            "TITLE": "量子计算实现重大突破",
            "URL": "https://www.gov.cn/zhengce/content/202607/content_tiered_frontier.htm",
            "DOCRELPUBTIME": "2026-07-29",
        },
        {
            "TITLE": "学校科技教育课程实践成果发布",
            "URL": "https://www.gov.cn/zhengce/content/202607/content_tiered_education.htm",
            "DOCRELPUBTIME": "2026-07-28",
        },
    ]
    settings = integration_context.settings.model_copy(
        update={
            "acquisition_first_run_item_limit": 3,
            "acquisition_daily_item_limit": 3,
        }
    )
    first_fetcher = RelevanceFixtureFetcher(records)
    first_run, first_job = await _execute_government_run(
        integration_context,
        first_fetcher,
        settings=settings,
    )
    second_fetcher = RelevanceFixtureFetcher(records)
    second_run, second_job = await _execute_government_run(
        integration_context,
        second_fetcher,
        settings=settings,
    )

    expected_urls = [
        SOURCE_SEEDS[0].entry_url,
        records[2]["URL"],
        records[1]["URL"],
        records[0]["URL"],
    ]
    assert first_fetcher.requested_urls == expected_urls
    assert second_fetcher.requested_urls == expected_urls
    assert first_run.new_count == 2
    assert first_run.filtered_count == 1
    assert second_run.filtered_count == 1

    async with integration_context.session_factory() as session:
        observation = await session.scalar(
            select(SourceObservationModel).where(
                SourceObservationModel.job_id == first_job.id,
                SourceObservationModel.source_item_id.is_(None),
                SourceObservationModel.outcome == ObservationOutcome.FILTERED.value,
            )
        )
    assert observation is not None
    assert observation.observation_metadata["education_title_count"] == 1
    assert observation.observation_metadata["frontier_title_count"] == 1
    assert observation.observation_metadata["neutral_probe_count"] == 1
    assert second_job.status == JobStatus.SUCCEEDED.value


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
            "TITLE": "学校人工智能教育课程建设",
            "URL": "https://www.gov.cn/zhengce/content/202607/content_mixed_ai_new.htm",
            "DOCRELPUBTIME": "2026-07-29",
        },
        {
            "TITLE": "学校人工智能教育与人工智能素养项目",
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
    assert run.filtered_count == 0
    assert job.outcome == "succeeded"
    assert job.filtered_count == 0
    assert fetcher.requested_urls == [entry_url, records[2]["URL"]]
    assert sleep_calls == pytest.approx([SOURCE_SEEDS[0].rate_limit_seconds], abs=0.2)

    async with integration_context.session_factory() as session:
        cursor = await session.get(SourceCursorModel, SOURCE_SEEDS[0].source_version_id)
        candidate = await session.scalar(
            select(EvidenceCandidateModel).where(
                EvidenceCandidateModel.source_version_id == SOURCE_SEEDS[0].source_version_id,
                EvidenceCandidateModel.source_item_id == "content_mixed_ai_old.htm",
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
    assert candidate.title == records[2]["TITLE"]
    assert candidate.relevance_rule_version == SCIENCE_TECH_EDITORIAL_RULE_VERSION
    assert candidate.extraction_metadata["relevance_rule_version"] == (
        SCIENCE_TECH_EDITORIAL_RULE_VERSION
    )
    assert "人工智能" in candidate.extraction_metadata["matched_title_topic_terms"]
    assert candidate.extraction_metadata["science_tech_candidate"] is True
    assert candidate.extraction_metadata["editorial_cohort"] == (
        "science_technology_education_priority"
    )
    assert candidate.extraction_metadata["product_matrix_fit_score"] > 0
    assert candidate.extraction_metadata["product_matrix_direction_ids"] == [
        "ai_literacy_project_learning"
    ]
    assert filter_observation is not None
    assert filter_observation.observation_metadata["scanned_count"] == 3
    assert filter_observation.observation_metadata["relevant_count"] == 1
    assert filter_observation.observation_metadata["accepted_count"] == 1
    assert filter_observation.observation_metadata["filtered_count"] == 0
    assert filter_observation.observation_metadata["deferred_relevant_count"] == 1
    assert filter_observation.observation_metadata["education_title_count"] == 1
    assert filter_observation.observation_metadata["frontier_title_count"] == 0
    assert filter_observation.observation_metadata["neutral_probe_count"] == 0
    assert filter_observation.observation_metadata["relevance_rule_version"] == (
        SCIENCE_TECH_EDITORIAL_RULE_VERSION
    )

    app.state.settings = integration_context.settings
    app.state.session_factory = integration_context.session_factory
    request_count_before_api = len(fetcher.requested_urls)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get(
            "/api/v1/evidence-candidates",
            params={
                "source_id": str(SOURCE_SEEDS[0].source_id),
                "relevance_rule_version": SCIENCE_TECH_EDITORIAL_RULE_VERSION,
                "limit": 100,
            },
        )
        assert listed.status_code == 200
        summary = next(item for item in listed.json()["items"] if item["id"] == str(candidate.id))
        assert summary["source_slug"] == SOURCE_SEEDS[0].slug
        assert summary["source_display_name"] == SOURCE_SEEDS[0].display_name
        assert summary["original_url"] == records[2]["URL"]
        assert summary["canonical_url"] == records[2]["URL"]
        assert summary["relevance_rule_version"] == SCIENCE_TECH_EDITORIAL_RULE_VERSION

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
            observation["metadata"].get("relevance_rule_version")
            == SCIENCE_TECH_EDITORIAL_RULE_VERSION
            for observation in detail.json()["observations"]
        )
    assert len(fetcher.requested_urls) == request_count_before_api


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_zero_match_uses_bounded_neutral_probe_and_advances_raw_cursor(
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
    assert run.filtered_count == 1
    assert job.status == JobStatus.SUCCEEDED.value
    assert job.outcome == ObservationOutcome.NO_RELEVANT_ITEMS.value
    assert job.filtered_count == 1
    assert fetcher.requested_urls == [SOURCE_SEEDS[0].entry_url, records[0]["URL"]]

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
    assert no_match.observation_metadata["scanned_count"] == 2
    assert no_match.observation_metadata["relevant_count"] == 0
    assert no_match.observation_metadata["accepted_count"] == 1
    assert no_match.observation_metadata["filtered_count"] == 1
    assert no_match.observation_metadata["deferred_relevant_count"] == 0
    assert no_match.observation_metadata["education_title_count"] == 0
    assert no_match.observation_metadata["frontier_title_count"] == 0
    assert no_match.observation_metadata["neutral_probe_count"] == 1
    assert no_match.observation_metadata["deferred_detail_count"] == 1
    assert no_match.observation_metadata["relevance_rule_version"] == (
        SCIENCE_TECH_EDITORIAL_RULE_VERSION
    )
