import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from app.core.errors import LeaseLostError
from app.domain.entities import ExtractedDocument, FetchedResponse, SnapshotDescriptor
from app.domain.enums import JobStatus, ObservationOutcome, RunStatus, RunTrigger
from app.infrastructure.db.models import (
    AcquisitionJobModel,
    AcquisitionRunModel,
    SourceFetchLeaseModel,
    SourceModel,
    SourceSnapshotModel,
    SourceVersionModel,
)
from app.infrastructure.db.repositories import (
    acquire_source_fetch_lease,
    claim_job,
    complete_run_if_terminal,
    create_run,
    finish_job,
    heartbeat_job,
    persist_candidate,
    persist_snapshot,
    release_source_fetch_lease,
    seed_sources,
)
from app.infrastructure.ingestion.source_profiles import SOURCE_SEEDS
from sqlalchemy import func, select

from .conftest import IntegrationContext


async def _cancel_nonterminal(context: IntegrationContext) -> None:
    async with context.session_factory() as session:
        await session.execute(
            AcquisitionJobModel.__table__.update()
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


async def _claim_sources(context: IntegrationContext, source_indexes: list[int]):
    await _cancel_nonterminal(context)
    async with context.session_factory() as session:
        await seed_sources(session)
        await create_run(
            session,
            trigger=RunTrigger.MANUAL,
            timezone="Asia/Shanghai",
            acquisition_version="acquisition-v1",
            manual_idempotency_key=f"lease-{uuid4()}",
            source_ids=[SOURCE_SEEDS[index].source_id for index in source_indexes],
        )
    claims = []
    for index in source_indexes:
        async with context.session_factory() as session:
            claimed = await claim_job(session, worker_id=f"worker-{index}", lease_seconds=120)
        assert claimed is not None
        async with context.session_factory() as session:
            acquired = await acquire_source_fetch_lease(
                session,
                source_id=claimed.profile.source_id,
                owner=f"worker-{index}",
                lease_token=claimed.lease_token,
                lease_seconds=120,
            )
        assert acquired is True
        claims.append(claimed)
    return claims


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_source_seed_is_idempotent_and_exposes_eight_active_versions(
    integration_context: IntegrationContext,
) -> None:
    async with integration_context.session_factory() as session:
        first = await seed_sources(session)
        second = await seed_sources(session)
        source_count = await session.scalar(select(func.count()).select_from(SourceModel))
        versions = list((await session.scalars(select(SourceVersionModel))).all())
    assert first in {0, 8}
    assert second == 0
    assert source_count == 8
    assert len(versions) == 8
    assert {version.relevance_rule_version for version in versions} == {"ai-title-v1"}


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_source_seed_reactivates_current_rule_without_deleting_legacy_version(
    integration_context: IntegrationContext,
) -> None:
    seed = SOURCE_SEEDS[0]
    legacy_id = uuid4()
    async with integration_context.session_factory() as session:
        current = await session.get(SourceVersionModel, seed.source_version_id)
        source = await session.get(SourceModel, seed.source_id)
        assert current is not None and source is not None
        legacy = SourceVersionModel(
            id=legacy_id,
            source_id=current.source_id,
            version=current.version + 1000,
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
            relevance_rule_version=None,
            config_fingerprint=uuid4().hex,
        )
        session.add(legacy)
        await session.flush()
        source.active_version_id = legacy.id
        await session.commit()

    async with integration_context.session_factory() as session:
        await seed_sources(session)
        source = await session.get(SourceModel, seed.source_id)
        legacy = await session.get(SourceVersionModel, legacy_id)

    assert source is not None and source.active_version_id == seed.source_version_id
    assert legacy is not None and legacy.relevance_rule_version is None


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_manual_and_scheduled_run_uniqueness(
    integration_context: IntegrationContext,
) -> None:
    key = f"integration-{uuid4()}"
    async with integration_context.session_factory() as session:
        manual_one, created_one = await create_run(
            session,
            trigger=RunTrigger.MANUAL,
            timezone="Asia/Shanghai",
            acquisition_version="acquisition-v1",
            manual_idempotency_key=key,
            source_ids=[SOURCE_SEEDS[0].source_id],
        )
    async with integration_context.session_factory() as session:
        manual_two, created_two = await create_run(
            session,
            trigger=RunTrigger.MANUAL,
            timezone="Asia/Shanghai",
            acquisition_version="acquisition-v1",
            manual_idempotency_key=key,
            source_ids=[SOURCE_SEEDS[0].source_id],
        )
    assert created_one is True
    assert created_two is False
    assert manual_one.id == manual_two.id

    schedule_date = date(2031, 1, 1)
    async with integration_context.session_factory() as session:
        scheduled_one, scheduled_created = await create_run(
            session,
            trigger=RunTrigger.SCHEDULED,
            timezone="Asia/Shanghai",
            acquisition_version="acquisition-v1",
            business_date=schedule_date,
            source_ids=[SOURCE_SEEDS[0].source_id],
        )
    async with integration_context.session_factory() as session:
        scheduled_two, duplicate_created = await create_run(
            session,
            trigger=RunTrigger.SCHEDULED,
            timezone="Asia/Shanghai",
            acquisition_version="acquisition-v1",
            business_date=schedule_date,
            source_ids=[SOURCE_SEEDS[0].source_id],
        )
    assert scheduled_created is True
    assert duplicate_created is False
    assert scheduled_one.id == scheduled_two.id


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_competing_workers_claim_distinct_jobs_and_expired_lease_is_reclaimed(
    integration_context: IntegrationContext,
) -> None:
    async with integration_context.session_factory() as session:
        await create_run(
            session,
            trigger=RunTrigger.MANUAL,
            timezone="Asia/Shanghai",
            acquisition_version="acquisition-v1",
            manual_idempotency_key=f"claim-{uuid4()}",
            source_ids=[SOURCE_SEEDS[1].source_id, SOURCE_SEEDS[2].source_id],
        )
    now = datetime(2032, 1, 1, tzinfo=UTC)
    async with integration_context.session_factory() as first_session:
        first = await claim_job(first_session, worker_id="worker-one", lease_seconds=30, now=now)
    async with integration_context.session_factory() as second_session:
        second = await claim_job(second_session, worker_id="worker-two", lease_seconds=30, now=now)
    assert first is not None and second is not None
    assert first.job_id != second.job_id

    async with integration_context.session_factory() as reclaim_session:
        reclaimed = await claim_job(
            reclaim_session,
            worker_id="worker-recovery",
            lease_seconds=30,
            now=now + timedelta(seconds=31),
        )
    assert reclaimed is not None
    assert reclaimed.job_id in {first.job_id, second.job_id}


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_heartbeat_renews_job_and_source_fetch_lease_together(
    integration_context: IntegrationContext,
) -> None:
    claimed = (await _claim_sources(integration_context, [3]))[0]
    async with integration_context.session_factory() as session:
        before = await session.get(SourceFetchLeaseModel, claimed.profile.source_id)
        assert before is not None
        before_expiry = before.expires_at
    async with integration_context.session_factory() as session:
        assert await heartbeat_job(session, claimed=claimed, lease_seconds=240) is True
    async with integration_context.session_factory() as session:
        renewed = await session.get(SourceFetchLeaseModel, claimed.profile.source_id)
        assert renewed is not None
        assert renewed.expires_at > before_expiry
    async with integration_context.session_factory() as session:
        await release_source_fetch_lease(
            session,
            source_id=claimed.profile.source_id,
            lease_token=claimed.lease_token,
        )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_stale_worker_is_fenced_before_snapshot_persistence(
    integration_context: IntegrationContext,
) -> None:
    claimed = (await _claim_sources(integration_context, [4]))[0]
    async with integration_context.session_factory() as session:
        await session.execute(
            AcquisitionJobModel.__table__.update()
            .where(AcquisitionJobModel.id == claimed.job_id)
            .values(lease_token=uuid4())
        )
        await session.commit()
    response = FetchedResponse(
        requested_url=claimed.profile.entry_url,
        final_url=claimed.profile.entry_url,
        status_code=200,
        media_type="text/html",
        body=b"stale",
        sha256="stale-hash",
        fetched_at=datetime.now(UTC),
    )
    stored = SnapshotDescriptor("snapshots", "stale-object", "text/html", 5, "stale-hash")
    async with integration_context.session_factory() as session:
        with pytest.raises(LeaseLostError):
            await persist_snapshot(
                session,
                claimed=claimed,
                profile=claimed.profile,
                kind="detail",
                response=response,
                stored=stored,
            )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_shared_object_keeps_distinct_source_provenance_and_snapshot_upsert_is_race_safe(
    integration_context: IntegrationContext,
) -> None:
    first, second = await _claim_sources(integration_context, [5, 6])
    digest = uuid4().hex * 2
    stored = SnapshotDescriptor(
        "snapshots",
        f"source-snapshots/sha256/{digest[:2]}/{digest}",
        "text/html",
        4,
        digest,
    )

    async def save(claimed, suffix: str):
        response = FetchedResponse(
            requested_url=f"{claimed.profile.entry_url.rstrip('/')}/{suffix}",
            final_url=f"{claimed.profile.entry_url.rstrip('/')}/{suffix}",
            status_code=200,
            media_type="text/html",
            body=b"same",
            sha256=digest,
            fetched_at=datetime.now(UTC),
        )
        async with integration_context.session_factory() as session:
            return await persist_snapshot(
                session,
                claimed=claimed,
                profile=claimed.profile,
                kind="detail",
                response=response,
                stored=stored,
            )

    first_snapshot, second_snapshot = await asyncio.gather(
        save(first, "shared"), save(second, "shared")
    )
    assert first_snapshot.id != second_snapshot.id
    assert first_snapshot.object_key == second_snapshot.object_key
    assert first_snapshot.source_version_id == first.profile.source_version_id
    assert second_snapshot.source_version_id == second.profile.source_version_id
    assert first_snapshot.original_url != second_snapshot.original_url

    race_digest = uuid4().hex * 2
    race_store = SnapshotDescriptor(
        "snapshots",
        f"source-snapshots/sha256/{race_digest[:2]}/{race_digest}",
        "text/html",
        4,
        race_digest,
    )
    race_response = FetchedResponse(
        requested_url=f"{first.profile.entry_url.rstrip('/')}/race-{uuid4()}",
        final_url=f"{first.profile.entry_url.rstrip('/')}/race-{uuid4()}",
        status_code=200,
        media_type="text/html",
        body=b"race",
        sha256=race_digest,
        fetched_at=datetime.now(UTC),
    )

    async def save_same_snapshot():
        async with integration_context.session_factory() as session:
            return await persist_snapshot(
                session,
                claimed=first,
                profile=first.profile,
                kind="detail",
                response=race_response,
                stored=race_store,
            )

    race_one, race_two = await asyncio.gather(save_same_snapshot(), save_same_snapshot())
    assert race_one.id == race_two.id
    async with integration_context.session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(SourceSnapshotModel)
            .where(SourceSnapshotModel.provenance_key == race_one.provenance_key)
        )
    assert count == 1


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_candidate_upsert_recovers_from_concurrent_unique_conflict(
    integration_context: IntegrationContext,
) -> None:
    claimed = (await _claim_sources(integration_context, [7]))[0]
    digest = uuid4().hex * 2
    response = FetchedResponse(
        requested_url=f"{claimed.profile.entry_url.rstrip('/')}/candidate",
        final_url=f"{claimed.profile.entry_url.rstrip('/')}/candidate",
        status_code=200,
        media_type="text/html",
        body=b"body",
        sha256=digest,
        fetched_at=datetime.now(UTC),
    )
    stored = SnapshotDescriptor("snapshots", f"object-{digest}", "text/html", 4, digest)
    async with integration_context.session_factory() as session:
        snapshot = await persist_snapshot(
            session,
            claimed=claimed,
            profile=claimed.profile,
            kind="detail",
            response=response,
            stored=stored,
        )
    document = ExtractedDocument(
        source_item_id=f"candidate-{uuid4()}",
        original_url=response.requested_url,
        canonical_url=response.final_url,
        title="Concurrent candidate",
        clean_text=f"unique concurrent body {uuid4()}",
        published_at=datetime.now(UTC),
        language="zh-CN",
        parser_version=claimed.profile.parser_version,
    )

    async def save_candidate():
        async with integration_context.session_factory() as session:
            return await persist_candidate(
                session,
                claimed=claimed,
                profile=claimed.profile,
                document=document,
                snapshot_id=snapshot.id,
                fetched_at=datetime.now(UTC),
            )

    first, second = await asyncio.gather(save_candidate(), save_candidate())
    assert first[0].id == second[0].id
    assert {first[1], second[1]} == {
        ObservationOutcome.NEW,
        ObservationOutcome.UNCHANGED,
    }


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_new_parser_version_can_correct_metadata_for_same_source_item(
    integration_context: IntegrationContext,
) -> None:
    claimed = (await _claim_sources(integration_context, [5]))[0]
    original_version_id = claimed.profile.source_version_id
    corrected_version_id = uuid4()
    async with integration_context.session_factory() as session:
        original_version = await session.get(SourceVersionModel, original_version_id)
        assert original_version is not None
        session.add(
            SourceVersionModel(
                id=corrected_version_id,
                source_id=original_version.source_id,
                version=original_version.version + 1000,
                trust_tier=original_version.trust_tier,
                connector_key=original_version.connector_key,
                entry_url=original_version.entry_url,
                allowed_hosts=original_version.allowed_hosts,
                allowed_path_prefixes=original_version.allowed_path_prefixes,
                cadence=original_version.cadence,
                timezone=original_version.timezone,
                language=original_version.language,
                robots_status=original_version.robots_status,
                terms_reviewed_at=original_version.terms_reviewed_at,
                rate_limit_seconds=original_version.rate_limit_seconds,
                connector_version="corrected-connector",
                parser_version="corrected-parser",
                config_fingerprint=uuid4().hex,
            )
        )
        await session.commit()

    digest = uuid4().hex * 2
    source_item_id = f"corrected-{uuid4()}"
    response = FetchedResponse(
        requested_url=f"{claimed.profile.entry_url.rstrip('/')}/{source_item_id}",
        final_url=f"{claimed.profile.entry_url.rstrip('/')}/{source_item_id}",
        status_code=200,
        media_type="text/html",
        body=b"same article body",
        sha256=digest,
        fetched_at=datetime.now(UTC),
    )
    stored = SnapshotDescriptor("snapshots", f"object-{digest}", "text/html", 17, digest)
    async with integration_context.session_factory() as session:
        original_snapshot = await persist_snapshot(
            session,
            claimed=claimed,
            profile=claimed.profile,
            kind="detail",
            response=response,
            stored=stored,
        )
    clean_text = f"same normalized content {uuid4()}"
    original_document = ExtractedDocument(
        source_item_id=source_item_id,
        original_url=response.requested_url,
        canonical_url=response.final_url,
        title="全部导航",
        clean_text=clean_text,
        published_at=datetime.now(UTC),
        language="zh-CN",
        parser_version=claimed.profile.parser_version,
    )
    async with integration_context.session_factory() as session:
        original_candidate, original_outcome = await persist_candidate(
            session,
            claimed=claimed,
            profile=claimed.profile,
            document=original_document,
            snapshot_id=original_snapshot.id,
            fetched_at=datetime.now(UTC),
        )
    assert original_outcome is ObservationOutcome.NEW

    corrected_profile = replace(
        claimed.profile,
        source_version_id=corrected_version_id,
        connector_version="corrected-connector",
        parser_version="corrected-parser",
    )
    async with integration_context.session_factory() as session:
        corrected_snapshot = await persist_snapshot(
            session,
            claimed=claimed,
            profile=corrected_profile,
            kind="detail",
            response=response,
            stored=stored,
        )
    corrected_document = replace(
        original_document,
        title="步履丈量乡土文脉 做文化传承守艺人",
        parser_version="corrected-parser",
    )
    async with integration_context.session_factory() as session:
        corrected_candidate, corrected_outcome = await persist_candidate(
            session,
            claimed=claimed,
            profile=corrected_profile,
            document=corrected_document,
            snapshot_id=corrected_snapshot.id,
            fetched_at=datetime.now(UTC),
        )

    assert corrected_outcome is ObservationOutcome.NEW
    assert corrected_candidate.id != original_candidate.id
    assert corrected_candidate.source_version_id == corrected_version_id
    assert corrected_candidate.title == corrected_document.title


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_filtered_count_is_terminal_scan_value_not_retry_accumulator(
    integration_context: IntegrationContext,
) -> None:
    first_claim = (await _claim_sources(integration_context, [2]))[0]
    async with integration_context.session_factory() as session:
        assert await finish_job(
            session,
            claimed=first_claim,
            status=JobStatus.RETRY_SCHEDULED,
            outcome=ObservationOutcome.TRANSIENT_FETCH_FAILURE.value,
            error_code="network_failure",
            filtered_count=5,
            retry_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    async with integration_context.session_factory() as session:
        await release_source_fetch_lease(
            session,
            source_id=first_claim.profile.source_id,
            lease_token=first_claim.lease_token,
        )
    async with integration_context.session_factory() as session:
        second_claim = await claim_job(
            session,
            worker_id="worker-retry",
            lease_seconds=120,
            now=datetime.now(UTC),
        )
    assert second_claim is not None and second_claim.job_id == first_claim.job_id
    async with integration_context.session_factory() as session:
        assert await acquire_source_fetch_lease(
            session,
            source_id=second_claim.profile.source_id,
            owner="worker-retry",
            lease_token=second_claim.lease_token,
            lease_seconds=120,
        )
    async with integration_context.session_factory() as session:
        assert await finish_job(
            session,
            claimed=second_claim,
            status=JobStatus.SUCCEEDED,
            outcome="succeeded",
            error_code=None,
            filtered_count=3,
        )
    async with integration_context.session_factory() as session:
        job = await session.get(AcquisitionJobModel, second_claim.job_id)
        run = await session.get(AcquisitionRunModel, second_claim.run_id)

    assert job is not None and job.filtered_count == 3
    assert run is not None and run.filtered_count == 3


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_all_cancelled_jobs_preserve_cancelled_run_state(
    integration_context: IntegrationContext,
) -> None:
    await _cancel_nonterminal(integration_context)
    async with integration_context.session_factory() as session:
        run, _ = await create_run(
            session,
            trigger=RunTrigger.MANUAL,
            timezone="Asia/Shanghai",
            acquisition_version="acquisition-v1",
            manual_idempotency_key=f"cancelled-{uuid4()}",
            source_ids=[SOURCE_SEEDS[0].source_id, SOURCE_SEEDS[1].source_id],
        )
        await session.execute(
            AcquisitionJobModel.__table__.update()
            .where(AcquisitionJobModel.run_id == run.id)
            .values(status=JobStatus.CANCELLED.value, completed_at=datetime.now(UTC))
        )
        await session.commit()
        await complete_run_if_terminal(session, run.id)
        await session.refresh(run)

    assert run.status == RunStatus.CANCELLED.value
