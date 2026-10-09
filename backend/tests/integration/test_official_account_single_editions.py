from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from app.domain.official_account_single_edition import edition_window
from app.domain.official_account_weekly_dag import WeeklyDagArtifact
from app.infrastructure.db.models import OfficialAccountSingleEditionModel as Row
from app.infrastructure.db.official_account_single_edition import (
    PostgresSingleEditionRepository,
    _reserve,
)
from app.infrastructure.official_account_runtime import official_account_identity_from_settings
from sqlalchemy import select, text

from .conftest import IntegrationContext

DAY = date(2026, 9, 16)
NOW = datetime(2026, 9, 16, 1, tzinfo=UTC)


async def admit(context, account, *, day=DAY, now=NOW, maximum=3):
    repository = PostgresSingleEditionRepository(context.session_factory)
    await repository.import_history(account, (), now=now)
    return await repository.admit(
        account=account,
        window=edition_window(day),
        identity=official_account_identity_from_settings(
            context.settings, provider="zhipu", model="glm-test"
        ),
        max_attempts=maximum,
        retry_base_seconds=60,
        now=now,
    )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_date_admission_claim_fencing_and_frozen_budget(
    integration_context: IntegrationContext,
):
    ctx = integration_context
    account = sha256(uuid4().bytes).hexdigest()
    repository = PostgresSingleEditionRepository(ctx.session_factory)
    values = await asyncio.gather(*(admit(ctx, account) for _ in range(4)))
    assert len({value.id for value in values}) == 1
    repeated = await admit(ctx, account, maximum=1)
    assert repeated.max_attempts == 3
    claims = await asyncio.gather(
        *(
            repository.claim(account=account, delivery=False, now=NOW, lease_seconds=60)
            for _ in range(4)
        )
    )
    claims = [value for value in claims if value is not None]
    assert len(claims) == 1
    original = claims[0]
    later = NOW + timedelta(seconds=61)
    await repository.import_history(account, (), now=later)
    current = await repository.claim(account=account, delivery=False, now=later, lease_seconds=60)
    assert current.lease_token != original.lease_token
    assert await repository.save(replace(original, status="no_topic"), now=later) is False
    assert await repository.save(replace(current, status="no_topic"), now=later) is True
    assert (
        await repository.claim(account=account, delivery=False, now=later, lease_seconds=60) is None
    )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_history_barrier_missing_invalid_and_stale_block_admit_and_claim(integration_context):
    ctx = integration_context
    account = sha256(uuid4().bytes).hexdigest()
    repository = PostgresSingleEditionRepository(ctx.session_factory)
    kwargs = dict(
        account=account,
        window=edition_window(DAY),
        identity=official_account_identity_from_settings(
            ctx.settings, provider="zhipu", model="glm-test"
        ),
        max_attempts=3,
        retry_base_seconds=60,
        now=NOW,
    )
    assert await repository.admit(**kwargs) is None
    value = await admit(ctx, account)
    assert value is not None
    await repository.invalidate_history(account, now=NOW)
    assert (
        await repository.claim(account=account, delivery=False, now=NOW, lease_seconds=60) is None
    )
    await repository.import_history(account, (), now=NOW)
    assert (
        await repository.claim(
            account=account, delivery=False, now=NOW + timedelta(seconds=61), lease_seconds=60
        )
        is None
    )
    with pytest.raises(ValueError, match="mapping_unresolved"):
        await repository.import_history(account, (("f" * 64, "e" * 64, True),), now=NOW)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_event_owners_concurrently_prevent_rewritten_story_reuse(integration_context):
    ctx = integration_context
    account = sha256(uuid4().bytes).hexdigest()
    event = str(uuid4())

    async def reserve(owner):
        async with ctx.session_factory() as session, session.begin():
            return await _reserve(
                session, account, "event", event, owner, "a" * 64, "reserved", NOW
            )

    assert sum(await asyncio.gather(reserve("first"), reserve("second"))) == 1
    repository = PostgresSingleEditionRepository(ctx.session_factory)
    assert event in {str(value) for value in await repository.excluded_events(account)}


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_failed_date_does_not_block_friday_and_expired_history_is_not_replayed(
    integration_context,
):
    ctx = integration_context
    account = sha256(uuid4().bytes).hexdigest()
    repository = PostgresSingleEditionRepository(ctx.session_factory)
    old = await admit(ctx, account)
    claim = await repository.claim(account=account, delivery=False, now=NOW, lease_seconds=60)
    assert await repository.save(
        replace(claim, status="failed", error_code="single_no_topic"), now=NOW
    )
    friday = NOW + timedelta(days=2)
    new = await admit(ctx, account, day=date(2026, 9, 18), now=friday)
    claim = await repository.claim(account=account, delivery=False, now=friday, lease_seconds=60)
    assert claim.id == new.id and claim.id != old.id
    async with ctx.session_factory() as session:
        previous = await session.get(Row, old.id)
        assert previous.status == "failed"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_delivery_gate_and_post_expiry_ack_reconciliation_claim(integration_context):
    ctx = integration_context
    account = sha256(uuid4().bytes).hexdigest()
    repository = PostgresSingleEditionRepository(ctx.session_factory)
    value = await admit(ctx, account)
    # Minimal real relational fixture: an existing local article row, not SQLite/create_all.
    from app.infrastructure.db.models import OfficialAccountArticleRunModel

    article = uuid4()
    artifact = WeeklyDagArtifact(
        opaque_ref="test-artifact-v1:" + "a" * 64,
        fingerprint="a" * 64,
        media_type="application/json",
        byte_size=1,
    )
    async with ctx.session_factory() as session, session.begin():
        session.add(
            OfficialAccountArticleRunModel(
                id=article,
                fixture_id="single-gate-test",
                generation_mode="fixture",
                source_fingerprint=sha256(article.bytes).hexdigest(),
                request_fingerprint=sha256(article.bytes + b"request").hexdigest(),
                provider="fake",
                model="fake",
                version_bundle={},
                status="ready",
                current_stage="ready",
                error_retryable=False,
            )
        )
        await session.flush()
    claim = await repository.claim(account=account, delivery=False, now=NOW, lease_seconds=60)
    assert await repository.save(
        replace(
            claim,
            status="ready",
            article_run_id=article,
            prepared_artifact=artifact,
            article_fingerprint="b" * 64,
            content_fingerprint="c" * 64,
        ),
        now=NOW,
    )
    assert (
        await repository.claim(
            account=account,
            delivery=True,
            now=NOW + timedelta(minutes=59, seconds=59),
            lease_seconds=60,
        )
        is None
    )
    claim = await repository.claim(
        account=account, delivery=True, now=NOW + timedelta(hours=1), lease_seconds=60
    )
    assert claim.id == value.id
    # Crash after private add ACK: stale delivering is still reconcilable tomorrow.
    recovered = await repository.claim(
        account=account, delivery=True, now=NOW + timedelta(days=1), lease_seconds=60
    )
    assert recovered.id == value.id
    assert await repository.save(
        replace(recovered, status="delivered", receipt_fingerprint="d" * 64),
        now=NOW + timedelta(days=1),
    )
    assert (
        await repository.claim(
            account=account, delivery=True, now=NOW + timedelta(days=1), lease_seconds=60
        )
        is None
    )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_additive_head_and_populated_downgrade_guard(integration_context):
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from sqlalchemy.exc import DBAPIError

    await admit(integration_context, sha256(uuid4().bytes).hexdigest())
    async with integration_context.session_factory() as session:
        assert (
            await session.scalar(text("SELECT version_num FROM alembic_version")) == "20261009_0055"
        )
        assert await session.scalar(select(Row.id).limit(1)) is not None
    revision = ScriptDirectory.from_config(Config("backend/alembic.ini")).get_revision(
        "20260914_0047"
    )

    def downgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.downgrade()

    with pytest.raises(DBAPIError, match="cannot downgrade populated"):
        async with integration_context.engine.begin() as connection:
            await connection.run_sync(downgrade)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_fresh_single_article_execution_budget_is_frozen_without_rewriting_legacy(
    integration_context,
):
    from app.infrastructure.db.official_account_local import PostgresOfficialAccountRepository
    from app.infrastructure.official_account_local import fixture_source_snapshot

    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    identity = official_account_identity_from_settings(
        integration_context.settings, provider="fake", model="fake-" + uuid4().hex
    )
    source = fixture_source_snapshot()
    frozen = {
        "version": "single-edition-article-retry-v1",
        "max_attempts": 1,
        "retry_base_seconds": 10,
        "expires_at": "2099-01-01T08:00:00+00:00",
    }
    run, created = await repository._enqueue(
        material_package_id=None,
        fixture_id="single-budget-test",
        generation_mode="fixture",
        source=source,
        identity=identity,
        execution_retry_policy=frozen,
    )
    assert created
    claim = await repository.claim(worker_id="single-budget-test", lease_seconds=60, max_attempts=6)
    assert claim.run_id == run.id
    assert await repository.fail(
        claimed=claim,
        error_code="provider_unavailable",
        retryable=True,
        retry_base_seconds=1,
        max_attempts=6,
    )
    final = await repository.get_run(run.id)
    assert final.status == "failed" and final.attempt_count == 1
    assert final.version_bundle["execution_retry_policy"] == frozen
    assert identity.provider == "fake"
    from app.core.errors import ConflictError

    with pytest.raises(ConflictError, match="budget"):
        await repository.retry(run_id=run.id, max_attempts=6)
