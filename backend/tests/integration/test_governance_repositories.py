import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.application.services.governance_runtime import build_governance_version_bundle
from app.core.errors import GovernanceLeaseLostError
from app.domain.governance_entities import GovernanceJobCompletion
from app.domain.governance_enums import GovernanceJobStatus
from app.infrastructure.db.governance_repositories import (
    acquire_event_assignment_lock,
    claim_governance_job,
    create_governance_attempt,
    create_governance_run_for_acquisition,
    finish_governance_job,
    heartbeat_governance_job,
    synchronize_source_occurrences,
)
from app.infrastructure.db.models import (
    AcquisitionJobModel,
    AcquisitionRunModel,
    ArticleOccurrenceModel,
    EvidenceCandidateModel,
    GovernanceJobModel,
    GovernanceRunModel,
    SourceObservationModel,
    SourceSnapshotModel,
)
from app.infrastructure.db.repositories import seed_sources
from app.infrastructure.ingestion.source_profiles import SOURCE_SEEDS
from sqlalchemy import func, select

from .conftest import IntegrationContext


async def _create_acquisition_fixture(
    context: IntegrationContext, *, candidate_count: int = 2
) -> tuple[UUID, list[UUID]]:
    run_id = uuid4()
    now = datetime.now(UTC)
    selected_seeds = SOURCE_SEEDS[: max(3, candidate_count)]
    async with context.session_factory() as session:
        await session.execute(
            GovernanceJobModel.__table__.update()
            .where(GovernanceJobModel.status.in_(["queued", "running", "retry_scheduled"]))
            .values(status="cancelled", completed_at=now, lease_token=None)
        )
        await session.execute(
            GovernanceRunModel.__table__.update()
            .where(GovernanceRunModel.status.in_(["queued", "running"]))
            .values(status="cancelled", completed_at=now)
        )
        await seed_sources(session)
        session.add(
            AcquisitionRunModel(
                id=run_id,
                trigger="manual",
                timezone="Asia/Shanghai",
                acquisition_version="acquisition-v1",
                manual_idempotency_key=f"governance-fixture-{run_id}",
                status="succeeded",
                total_jobs=len(selected_seeds),
                succeeded_jobs=len(selected_seeds),
                completed_at=now,
            )
        )
        await session.flush()
        acquisition_job_ids: list[UUID] = []
        for seed in selected_seeds:
            job_id = uuid4()
            acquisition_job_ids.append(job_id)
            session.add(
                AcquisitionJobModel(
                    id=job_id,
                    run_id=run_id,
                    source_id=seed.source_id,
                    source_version_id=seed.source_version_id,
                    status="succeeded",
                    outcome="completed",
                    completed_at=now,
                )
            )
        await session.flush()

        candidate_ids: list[UUID] = []
        for index in range(candidate_count):
            seed = selected_seeds[index]
            candidate_id = uuid4()
            candidate_ids.append(candidate_id)
            primary_snapshot_id = uuid4()
            digest = f"{index + 1:064x}"
            session.add(
                SourceSnapshotModel(
                    id=primary_snapshot_id,
                    provenance_key=uuid4().hex + uuid4().hex,
                    source_version_id=seed.source_version_id,
                    kind="detail",
                    original_url=f"https://example.invalid/{candidate_id}",
                    final_url=f"https://example.invalid/{candidate_id}",
                    bucket="fixture",
                    object_key=f"fixture/{candidate_id}",
                    media_type="text/html",
                    byte_size=100,
                    sha256=digest,
                    response_metadata={},
                    fetched_at=now,
                    connector_version=seed.connector_version,
                    parser_version=seed.parser_version,
                )
            )
            await session.flush()
            session.add(
                EvidenceCandidateModel(
                    id=candidate_id,
                    source_id=seed.source_id,
                    source_version_id=seed.source_version_id,
                    source_item_id=f"item-{candidate_id}",
                    original_url=f"https://example.invalid/{candidate_id}",
                    canonical_url=f"https://example.invalid/{candidate_id}",
                    trust_tier=seed.tier.value,
                    title=f"AI fixture {index}",
                    clean_text=f"AI governance fixture content {candidate_id}",
                    published_at=now,
                    first_fetched_at=now,
                    language="zh-CN",
                    content_hash=digest,
                    parser_version=seed.parser_version,
                    relevance_rule_version="ai-title-v1",
                    extraction_metadata={},
                    primary_snapshot_id=primary_snapshot_id,
                )
            )
            await session.flush()
            session.add(
                SourceObservationModel(
                    id=uuid4(),
                    idempotency_key=uuid4().hex + uuid4().hex,
                    run_id=run_id,
                    job_id=acquisition_job_ids[index],
                    source_version_id=seed.source_version_id,
                    source_item_id=f"item-{candidate_id}",
                    outcome="new",
                    snapshot_id=primary_snapshot_id,
                    candidate_id=candidate_id,
                    observed_at=now,
                    observation_metadata={},
                )
            )

        first_candidate_id = candidate_ids[0]
        shared_seed = selected_seeds[-1]
        shared_snapshot_id = uuid4()
        session.add(
            SourceSnapshotModel(
                id=shared_snapshot_id,
                provenance_key=uuid4().hex + uuid4().hex,
                source_version_id=shared_seed.source_version_id,
                kind="detail",
                original_url=f"https://shared.invalid/{first_candidate_id}",
                final_url=f"https://shared.invalid/{first_candidate_id}",
                bucket="fixture",
                object_key=f"fixture/shared-{first_candidate_id}",
                media_type="text/html",
                byte_size=100,
                sha256="f" * 64,
                response_metadata={},
                fetched_at=now,
                connector_version=shared_seed.connector_version,
                parser_version=shared_seed.parser_version,
            )
        )
        await session.flush()
        session.add(
            SourceObservationModel(
                id=uuid4(),
                idempotency_key=uuid4().hex + uuid4().hex,
                run_id=run_id,
                job_id=acquisition_job_ids[-1],
                source_version_id=shared_seed.source_version_id,
                source_item_id=f"shared-{first_candidate_id}",
                outcome="exact_duplicate",
                snapshot_id=shared_snapshot_id,
                candidate_id=first_candidate_id,
                observed_at=now + timedelta(seconds=1),
                observation_metadata={},
            )
        )
        await session.commit()
    return run_id, candidate_ids


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_governance_run_and_occurrences_are_idempotent_and_preserve_sources(
    integration_context: IntegrationContext,
) -> None:
    acquisition_run_id, candidate_ids = await _create_acquisition_fixture(
        integration_context, candidate_count=1
    )
    bundle = build_governance_version_bundle(integration_context.settings)
    async with integration_context.session_factory() as session:
        first, first_created = await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=acquisition_run_id,
            bundle=bundle,
            timezone="Asia/Shanghai",
        )
    async with integration_context.session_factory() as session:
        second, second_created = await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=acquisition_run_id,
            bundle=bundle,
            timezone="Asia/Shanghai",
        )
    async with integration_context.session_factory() as session:
        claimed = await claim_governance_job(
            session, worker_id="governance-occurrences", lease_seconds=60
        )
    assert claimed is not None and claimed.candidate_id == candidate_ids[0]
    async with integration_context.session_factory() as session:
        first_sync = await synchronize_source_occurrences(session, claimed=claimed)
        second_sync = await synchronize_source_occurrences(session, claimed=claimed)
        occurrence_count = await session.scalar(
            select(func.count())
            .select_from(ArticleOccurrenceModel)
            .where(ArticleOccurrenceModel.candidate_id == candidate_ids[0])
        )
        acquisition_observation_count = await session.scalar(
            select(func.count())
            .select_from(SourceObservationModel)
            .where(SourceObservationModel.run_id == acquisition_run_id)
        )

    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert len(first_sync) == len(second_sync) == 2
    assert len({occurrence.source_id for occurrence in first_sync}) == 2
    assert sum(occurrence.published_at is not None for occurrence in first_sync) == 1
    assert sum(occurrence.published_at is None for occurrence in first_sync) == 1
    assert occurrence_count == 2
    assert acquisition_observation_count == 2


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_competing_claims_heartbeat_and_expired_lease_recovery(
    integration_context: IntegrationContext,
) -> None:
    acquisition_run_id, _ = await _create_acquisition_fixture(
        integration_context, candidate_count=2
    )
    bundle = build_governance_version_bundle(integration_context.settings)
    async with integration_context.session_factory() as session:
        await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=acquisition_run_id,
            bundle=bundle,
            timezone="Asia/Shanghai",
        )

    async def claim(worker_id: str):
        async with integration_context.session_factory() as session:
            return await claim_governance_job(session, worker_id=worker_id, lease_seconds=60)

    first, second = await asyncio.gather(claim("governance-one"), claim("governance-two"))
    assert first is not None and second is not None
    assert first.job_id != second.job_id

    async with integration_context.session_factory() as session:
        assert await heartbeat_governance_job(session, claimed=first, lease_seconds=120) is True
        await session.execute(
            GovernanceJobModel.__table__.update()
            .where(GovernanceJobModel.id == second.job_id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    async with integration_context.session_factory() as session:
        reclaimed = await claim_governance_job(
            session, worker_id="governance-recovery", lease_seconds=60
        )
    assert reclaimed is not None
    assert reclaimed.job_id == second.job_id
    assert reclaimed.lease_token != second.lease_token


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_stale_worker_is_fenced_and_terminal_run_is_aggregated(
    integration_context: IntegrationContext,
) -> None:
    acquisition_run_id, _ = await _create_acquisition_fixture(
        integration_context, candidate_count=1
    )
    bundle = build_governance_version_bundle(integration_context.settings)
    async with integration_context.session_factory() as session:
        governance_run, _ = await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=acquisition_run_id,
            bundle=bundle,
            timezone="Asia/Shanghai",
        )
    async with integration_context.session_factory() as session:
        claimed = await claim_governance_job(
            session, worker_id="governance-terminal", lease_seconds=60
        )
    assert claimed is not None
    async with integration_context.session_factory() as session:
        first_attempt_id = await create_governance_attempt(session, claimed, stage="foundation")
    async with integration_context.session_factory() as session:
        repeated_attempt_id = await create_governance_attempt(session, claimed, stage="foundation")
    assert first_attempt_id == repeated_attempt_id
    stale_claim = claimed
    async with integration_context.session_factory() as session:
        session_job = await session.get(GovernanceJobModel, claimed.job_id)
        assert session_job is not None
        session_job.lease_token = uuid4()
        await session.commit()
    async with integration_context.session_factory() as session:
        with pytest.raises(GovernanceLeaseLostError):
            await synchronize_source_occurrences(session, claimed=stale_claim)
    async with integration_context.session_factory() as session:
        assert (
            await finish_governance_job(
                session,
                claimed=stale_claim,
                completion=GovernanceJobCompletion(
                    status=GovernanceJobStatus.SUCCEEDED,
                    outcome="foundation_complete",
                ),
            )
            is False
        )
        session_job = await session.get(GovernanceJobModel, claimed.job_id)
        assert session_job is not None
        session_job.lease_token = claimed.lease_token
        session_job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=60)
        await session.commit()
    async with integration_context.session_factory() as session:
        assert (
            await finish_governance_job(
                session,
                claimed=claimed,
                completion=GovernanceJobCompletion(
                    status=GovernanceJobStatus.SUCCEEDED,
                    outcome="foundation_complete",
                    safe_metadata={"artifact_count": 0},
                ),
            )
            is True
        )
    async with integration_context.session_factory() as session:
        run = await session.get(GovernanceRunModel, governance_run.id)
    assert run is not None
    assert run.status == "succeeded"
    assert run.succeeded_jobs == 1


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_event_assignment_advisory_lock_serializes_final_decision(
    integration_context: IntegrationContext,
) -> None:
    acquisition_run_id, _ = await _create_acquisition_fixture(
        integration_context, candidate_count=1
    )
    bundle = build_governance_version_bundle(integration_context.settings)
    async with integration_context.session_factory() as session:
        await create_governance_run_for_acquisition(
            session,
            acquisition_run_id=acquisition_run_id,
            bundle=bundle,
            timezone="Asia/Shanghai",
        )
    async with integration_context.session_factory() as session:
        claimed = await claim_governance_job(
            session, worker_id="governance-assignment", lease_seconds=60
        )
    assert claimed is not None
    article_id = uuid4()
    first_session = integration_context.session_factory()
    second_session = integration_context.session_factory()
    try:
        async with first_session.begin():
            assert (
                await acquire_event_assignment_lock(
                    first_session,
                    claimed=claimed,
                    normalized_article_id=article_id,
                    policy_version="event-assignment-v1",
                    wait=False,
                )
                is True
            )
            async with second_session.begin():
                assert (
                    await acquire_event_assignment_lock(
                        second_session,
                        claimed=claimed,
                        normalized_article_id=article_id,
                        policy_version="event-assignment-v1",
                        wait=False,
                    )
                    is False
                )
        async with second_session.begin():
            assert (
                await acquire_event_assignment_lock(
                    second_session,
                    claimed=claimed,
                    normalized_article_id=article_id,
                    policy_version="event-assignment-v1",
                    wait=False,
                )
                is True
            )
    finally:
        await first_session.close()
        await second_session.close()
