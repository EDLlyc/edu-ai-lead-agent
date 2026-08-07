from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.application.services.enqueue_runs import enqueue_manual_run, reconcile_daily_run
from app.application.services.execute_acquisition import AcquisitionExecutor
from app.core.errors import PermanentFetchError
from app.domain.entities import FetchedResponse, SourceProfile
from app.domain.enums import JobStatus, RunStatus
from app.domain.value_objects import sha256_bytes
from app.infrastructure.db.models import (
    AcquisitionJobModel,
    EvidenceCandidateModel,
    SourceObservationModel,
)
from app.infrastructure.db.repositories import (
    PostgresAcquisitionRepository,
    get_run,
    seed_sources,
)
from app.infrastructure.ingestion.source_profiles import SOURCE_SEEDS
from app.infrastructure.storage.minio_snapshot_store import MinioSnapshotStore
from sqlalchemy import func, select, update

from .conftest import IntegrationContext

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "sources" / "gov_cn_policy_v1"
FIXTURE_EVALUATED_AT = datetime(2026, 7, 30, 1, 0, tzinfo=UTC)


def fixture_clock() -> datetime:
    return FIXTURE_EVALUATED_AT


class FixtureFetcher:
    def __init__(self, *, fail_bnu: bool = False) -> None:
        self.fail_bnu = fail_bnu

    async def fetch(
        self,
        url: str,
        profile: SourceProfile,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchedResponse:
        del etag, last_modified
        if self.fail_bnu and profile.connector_key == "bnu_news_v1":
            raise PermanentFetchError("fixture_source_failure")
        if url == profile.entry_url:
            path = FIXTURE_ROOT / "list.json"
            media_type = "application/json"
        else:
            path = FIXTURE_ROOT / "detail.html"
            media_type = "text/html"
        body = path.read_bytes()
        return FetchedResponse(
            requested_url=url,
            final_url=url,
            status_code=200,
            media_type=media_type,
            body=body,
            sha256=sha256_bytes(body),
            fetched_at=datetime(2026, 7, 28, 1, 0, tzinfo=UTC),
            headers={"etag": '"fixture-v1"'} if media_type == "application/json" else {},
        )


async def no_sleep(_seconds: float) -> None:
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
        await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_scheduler_is_same_day_bounded_and_database_idempotent(
    integration_context: IntegrationContext,
) -> None:
    async with integration_context.session_factory() as session:
        await seed_sources(session)
    repository = PostgresAcquisitionRepository(integration_context.session_factory)
    before = await reconcile_daily_run(
        repository,
        integration_context.settings,
        now=datetime(2033, 1, 1, 22, 29, tzinfo=UTC),
    )
    assert before is None
    at_schedule = datetime(2033, 1, 1, 22, 30, tzinfo=UTC)
    first = await reconcile_daily_run(repository, integration_context.settings, now=at_schedule)
    second = await reconcile_daily_run(repository, integration_context.settings, now=at_schedule)
    assert first is not None and second is not None
    assert first[0] == second[0]
    assert first[1] is True
    assert second[1] is False
    too_late = await reconcile_daily_run(
        repository,
        integration_context.settings,
        now=datetime(2033, 1, 2, 11, 0, 1, tzinfo=UTC),
    )
    assert too_late is None
    await _cancel_nonterminal(integration_context)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_end_to_end_worker_persists_snapshot_candidate_and_repeat_observation(
    integration_context: IntegrationContext,
) -> None:
    await _cancel_nonterminal(integration_context)
    async with integration_context.session_factory() as session:
        await seed_sources(session)
    async with integration_context.session_factory() as session:
        baseline_candidate_count = await session.scalar(
            select(func.count()).select_from(EvidenceCandidateModel)
        )
        baseline_observation_count = await session.scalar(
            select(func.count()).select_from(SourceObservationModel)
        )
    repository = PostgresAcquisitionRepository(integration_context.session_factory)
    store = MinioSnapshotStore(integration_context.settings)
    executor = AcquisitionExecutor(
        repository,
        FixtureFetcher(),
        store,
        integration_context.settings,
        sleep=no_sleep,
        jitter=lambda: 0.0,
        clock=fixture_clock,
    )
    run_one, created = await enqueue_manual_run(
        repository,
        integration_context.settings,
        source_ids=[SOURCE_SEEDS[0].source_id],
        idempotency_key=f"e2e-one-{uuid4()}",
    )
    assert created is True
    assert await executor.execute_next("integration-worker") is True

    async with integration_context.session_factory() as session:
        completed = await get_run(session, run_one)
        candidate_count = await session.scalar(
            select(func.count()).select_from(EvidenceCandidateModel)
        )
        observation_count = await session.scalar(
            select(func.count()).select_from(SourceObservationModel)
        )
    assert completed.status == RunStatus.SUCCEEDED.value
    assert completed.new_count == 1
    assert candidate_count == baseline_candidate_count + 1
    assert observation_count == baseline_observation_count + 1

    run_two, _ = await enqueue_manual_run(
        repository,
        integration_context.settings,
        source_ids=[SOURCE_SEEDS[0].source_id],
        idempotency_key=f"e2e-two-{uuid4()}",
    )
    assert await executor.execute_next("integration-worker") is True
    async with integration_context.session_factory() as session:
        repeated = await get_run(session, run_two)
        repeated_candidate_count = await session.scalar(
            select(func.count()).select_from(EvidenceCandidateModel)
        )
        repeated_observation_count = await session.scalar(
            select(func.count()).select_from(SourceObservationModel)
        )
    assert repeated.status == RunStatus.SUCCEEDED.value
    assert repeated.unchanged_count == 1
    assert repeated_candidate_count == baseline_candidate_count + 1
    assert repeated_observation_count == observation_count + 1


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_one_source_failure_yields_partial_success(
    integration_context: IntegrationContext,
) -> None:
    await _cancel_nonterminal(integration_context)
    repository = PostgresAcquisitionRepository(integration_context.session_factory)
    executor = AcquisitionExecutor(
        repository,
        FixtureFetcher(fail_bnu=True),
        MinioSnapshotStore(integration_context.settings),
        integration_context.settings,
        sleep=no_sleep,
        jitter=lambda: 0.0,
        clock=fixture_clock,
    )
    run_id, _ = await enqueue_manual_run(
        repository,
        integration_context.settings,
        source_ids=[SOURCE_SEEDS[0].source_id, SOURCE_SEEDS[1].source_id],
        idempotency_key=f"partial-{uuid4()}",
    )
    assert await executor.execute_next("integration-worker") is True
    assert await executor.execute_next("integration-worker") is True
    async with integration_context.session_factory() as session:
        run = await get_run(session, run_id)
    assert run.status == RunStatus.PARTIALLY_SUCCEEDED.value
    assert run.succeeded_jobs == 1
    assert run.failed_jobs == 1
