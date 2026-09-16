from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from app.application.services.official_account_single_edition import SingleEditionProducer
from app.core.errors import ConflictError, ImageGenerationFailure
from app.domain.official_account_local import fingerprint
from app.domain.official_account_single_edition import edition_window
from app.infrastructure.db.models import EventClusterModel
from app.infrastructure.db.models import OfficialAccountArticleAttemptModel as Attempt
from app.infrastructure.db.models import OfficialAccountArticleRunModel as Run
from app.infrastructure.db.models import OfficialAccountArticleVersionModel as Article
from app.infrastructure.db.models import OfficialAccountDraftOwnerModel as Owner
from app.infrastructure.db.models import OfficialAccountGeneratedVisualModel as Visual
from app.infrastructure.db.models import OfficialAccountSingleEditionModel as Edition
from app.infrastructure.db.official_account_single_edition import PostgresSingleEditionRepository
from app.infrastructure.db.official_account_visual_compensation import (
    AUTH_STAGE,
    CONSUMED_STAGE,
    SHANGHAI,
    CompensationTarget,
    authorize_visual_compensation,
    resolve_visual_provider_request_fingerprint,
)
from sqlalchemy import select

from .test_official_account_strict_visual import _plan, _prime

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]
NOW = datetime(2026, 9, 16, 9, tzinfo=UTC)


class Journal:
    def __init__(self):
        self.records = {}

    def read(self, name):
        return self.records.get(name)

    def write(self, name, payload):
        assert name not in self.records
        self.records[name] = payload


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    for module in (
        "app.infrastructure.db.official_account_local",
        "app.infrastructure.db.official_account_strict_visual",
        "app.infrastructure.db.official_account_visual_compensation",
    ):
        monkeypatch.setattr(module + ".datetime", Clock)


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def integration_context():
    from .conftest import integration_context as context_fixture

    iterator = context_fixture.__wrapped__()
    context = await anext(iterator)
    try:
        yield context
    finally:
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)


async def seed(context):
    repo, claimed, article, render = await _prime(context, available_at=NOW)
    now = NOW
    day = now.astimezone(SHANGHAI).date()
    expiry = now - timedelta(minutes=10)
    account = fingerprint(uuid4())
    event_id = uuid4()
    edition_id = uuid4()
    # _prime needed a setup retry. This synthetic original image is its first call.
    claimed = replace(claimed, attempt_number=1)
    async with context.session_factory() as session, session.begin():
        run = await session.get(Run, claimed.run_id)
        run.attempt_count = 1
        run.version_bundle = {
            **run.version_bundle,
            "execution_retry_policy": {
                "version": "single-edition-article-retry-v1",
                "max_attempts": 3,
                "retry_base_seconds": 1,
                "expires_at": expiry.isoformat(),
            },
        }
    plan = _plan(claimed, article, render)
    initial = await repo.claim_strict_generated_visual(claimed=claimed, plan=plan)
    assert initial.outcome == "newly_claimed"
    assert await repo.fail_generated_visual(
        claimed=claimed,
        plan=plan,
        error_code="official_account_generated_visual_result_unknown",
        result_unknown=True,
    )
    assert await repo.fail(
        claimed=claimed,
        error_code="official_account_generated_visual_result_unknown",
        result_unknown=True,
        retryable=False,
        retry_base_seconds=1,
        max_attempts=3,
    )
    async with context.session_factory() as session, session.begin():
        session.add(EventClusterModel(id=event_id, status="active"))
        await session.flush()
        window = edition_window(day)
        session.add(
            Edition(
                id=edition_id,
                account_fingerprint=account,
                business_date=day,
                timezone="Asia/Shanghai",
                version="official-account-single-edition-v1",
                prepare_at=window.prepare_at,
                deliver_at=window.deliver_at,
                expires_at=expiry,
                article_identity=asdict(claimed.identity),
                retry_policy={"max_attempts": 3, "retry_base_seconds": 1},
                status="outcome_unknown",
                stage_attempts={},
                available_at=now,
                selection_artifact={
                    "opaque_ref": "selection-test",
                    "fingerprint": "b" * 64,
                    "media_type": "application/json",
                    "byte_size": 10,
                },
                event_id=event_id,
                article_run_id=claimed.run_id,
                role="official_anchor",
                error_code="single_article_result_unknown",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            Owner(
                account_fingerprint=account,
                key_kind="event",
                key_value=str(event_id),
                owner=str(edition_id),
                status="outcome_unknown",
                provenance_fingerprint="c" * 64,
                created_at=now,
                updated_at=now,
            )
        )
    target = CompensationTarget(
        edition_id=edition_id,
        run_id=claimed.run_id,
        article_version_id=article.id,
        visual_id=initial.visual.id,
        business_date=day,
    )
    return repo, target, plan, Journal(), now


async def authorize(context, target, journal, now, apply=True):
    async with context.session_factory() as session, session.begin():
        return await authorize_visual_compensation(
            session,
            target=target,
            journal=journal,
            journal_names=list(journal.records),
            now=now,
            apply=apply,
        )


async def test_exact_authorization_preserves_original_and_concurrent_single_consumption(
    integration_context,
):
    ctx = integration_context
    repo, target, plan, journal, now = await seed(ctx)
    before_article = await repo.get_article(target.run_id)
    before_render = await repo.get_render(target.run_id)
    async with ctx.session_factory() as session:
        old_attempts = (
            await session.scalars(select(Attempt).where(Attempt.run_id == target.run_id))
        ).all()
        originals = {
            r.id: (r.status, r.safe_metadata, r.request_fingerprint, r.error_code)
            for r in old_attempts
        }
    preview = await authorize(ctx, target, journal, now, apply=False)
    assert journal.records == {}
    assert (await repo.get_run(target.run_id)).status == "result_unknown"
    auth = await authorize(ctx, target, journal, now)
    assert preview == auth
    repeat = await authorize(ctx, target, journal, now + timedelta(minutes=20))
    assert repeat == auth
    assert len(journal.records) == 1
    assert (await repo.get_run(target.run_id)).attempt_count == 1
    claimed = await repo.claim(worker_id="compensation", lease_seconds=600, max_attempts=3)
    assert claimed.run_id == target.run_id and claimed.attempt_number == 2
    claims = await asyncio.gather(
        *(repo.claim_strict_generated_visual(claimed=claimed, plan=plan) for _ in range(4))
    )
    assert sorted(c.outcome for c in claims) == ["in_flight"] * 3 + ["newly_claimed"]
    paid_claim = next(c for c in claims if c.outcome == "newly_claimed")
    assert (
        paid_claim.provider_request_fingerprint
        == auth.provider_request_fingerprint
        != plan.request_fingerprint
    )
    assert await repo.get_article(target.run_id) == before_article
    assert await repo.get_render(target.run_id) == before_render
    async with ctx.session_factory() as session:
        records = (
            await session.scalars(select(Attempt).where(Attempt.run_id == target.run_id))
        ).all()
        assert {
            r.id: (r.status, r.safe_metadata, r.request_fingerprint, r.error_code)
            for r in records
            if r.id in originals
        } == originals
        assert (
            sum(r.stage == AUTH_STAGE for r in records)
            == sum(r.stage == CONSUMED_STAGE for r in records)
            == 1
        )
        assert (
            await resolve_visual_provider_request_fingerprint(
                session, run_id=target.run_id, visual_id=target.visual_id
            )
            == auth.provider_request_fingerprint
        )
        assert (
            await resolve_visual_provider_request_fingerprint(
                session, run_id=target.run_id, visual_id=uuid4()
            )
            is None
        )
    assert await repo.fail_generated_visual(
        claimed=claimed,
        plan=plan,
        error_code="official_account_generated_visual_result_unknown",
        result_unknown=True,
    )
    assert await repo.fail(
        claimed=claimed,
        error_code="official_account_generated_visual_result_unknown",
        result_unknown=True,
        retryable=False,
        retry_base_seconds=1,
        max_attempts=3,
    )
    assert await authorize(ctx, target, journal, now + timedelta(minutes=30)) == auth
    assert (await repo.get_run(target.run_id)).status == "result_unknown"
    assert await repo.claim(worker_id="no-replay", lease_seconds=600, max_attempts=3) is None


@pytest.mark.parametrize(
    "mutation", ["lease", "receipt", "wrong_article", "budget", "owner", "journal"]
)
async def test_operator_exact_guards_never_mutate_or_authorize(integration_context, mutation):
    ctx = integration_context
    repo, target, _plan_value, journal, now = await seed(ctx)
    async with ctx.session_factory() as session, session.begin():
        run = await session.get(Run, target.run_id)
        edition = await session.get(Edition, target.edition_id)
        if mutation == "lease":
            edition.lease_token, edition.lease_expires_at = uuid4(), now + timedelta(minutes=5)
        elif mutation == "receipt":
            edition.receipt_fingerprint = "e" * 64
        elif mutation == "budget":
            run.version_bundle = {
                **run.version_bundle,
                "execution_retry_policy": {
                    **run.version_bundle["execution_retry_policy"],
                    "max_attempts": 1,
                },
            }
        elif mutation == "owner":
            owner = await session.get(
                Owner, (edition.account_fingerprint, "event", str(edition.event_id))
            )
            owner.status = "acknowledged"
    if mutation == "wrong_article":
        target = target.model_copy(update={"article_version_id": uuid4()})
    if mutation == "journal":
        journal.write(f"single-{target.edition_id.hex}-add-1-intent.json", {})
    with pytest.raises(ValueError, match="precondition"):
        await authorize(ctx, target, journal, now)
    assert (await repo.get_run(target.run_id)).status == "result_unknown"
    async with ctx.session_factory() as session:
        assert (
            await session.scalar(
                select(Attempt.id).where(
                    Attempt.run_id == target.run_id, Attempt.stage == AUTH_STAGE
                )
            )
            is None
        )


async def test_producer_observes_rearmed_same_edition_without_expiry_or_new_text(
    integration_context,
):
    ctx = integration_context
    repo, target, _plan_value, journal, now = await seed(ctx)
    auth = await authorize(ctx, target, journal, now)
    single = PostgresSingleEditionRepository(ctx.session_factory)
    await single.import_history(auth.account_fingerprint, (), now=now)
    producer = SingleEditionProducer(
        repository=single,
        planner=None,
        article_repository=repo,
        artifacts=None,
        checkpoints=None,
        account=auth.account_fingerprint,
        clock=lambda: now,
    )
    assert await producer.process_once()
    async with ctx.session_factory() as session:
        edition = await session.get(Edition, target.edition_id)
        assert edition.status == "generating"
        assert edition.article_run_id == target.run_id
        assert edition.expires_at == auth.recovery_expires_at
        assert edition.lease_token is None
        article = await session.get(Article, target.article_version_id)
        assert article.audit_snapshot["accepted"] is True
        assert (
            await session.scalars(select(Article.id).where(Article.run_id == target.run_id))
        ).all() == [target.article_version_id]
    # The test only observes the producer; do not leave work for the next test's executor.
    async with ctx.session_factory() as session, session.begin():
        run = await session.get(Run, target.run_id)
        run.status = "result_unknown"


async def test_safe_failure_after_compensation_reuses_new_key_and_frozen_budget(
    integration_context,
):
    ctx = integration_context
    repo, target, plan, journal, now = await seed(ctx)
    auth = await authorize(ctx, target, journal, now)
    claim = await repo.claim(worker_id="compensation", lease_seconds=600, max_attempts=3)
    first = await repo.claim_strict_generated_visual(claimed=claim, plan=plan)
    assert first.provider_request_fingerprint == auth.provider_request_fingerprint
    proof = ImageGenerationFailure(
        "provider_unavailable", "not_applied_retryable", "connect_failed"
    )
    for expected_attempt in (2, 3):
        assert claim.attempt_number == expected_attempt
        assert await repo.fail_generated_visual(
            claimed=claim, plan=plan, error_code=proof.error_code, diagnostic=proof
        )
        assert await repo.fail(
            claimed=claim,
            error_code=proof.error_code,
            retryable=True,
            retry_base_seconds=1,
            max_attempts=99,
            safe_metadata=proof.safe_metadata(),
        )
        if expected_attempt == 2:
            async with ctx.session_factory() as session, session.begin():
                run = await session.get(Run, target.run_id)
                run.available_at = now
            claim = await repo.claim(worker_id="safe-retry", lease_seconds=600, max_attempts=99)
            next_visual = await repo.claim_strict_generated_visual(claimed=claim, plan=plan)
            assert next_visual.outcome == "newly_claimed"
            assert next_visual.provider_request_fingerprint == first.provider_request_fingerprint
    assert (await repo.get_run(target.run_id)).status == "failed"
    with pytest.raises(ConflictError):
        await repo.retry(run_id=target.run_id, max_attempts=99)
    assert await authorize(ctx, target, journal, now + timedelta(minutes=1)) == auth
    assert (await repo.get_run(target.run_id)).attempt_count == 3


@pytest.mark.parametrize("consume_before_crash", [False, True])
async def test_orphaned_successor_never_gets_second_compensation(
    integration_context, consume_before_crash
):
    ctx = integration_context
    repo, target, plan, journal, now = await seed(ctx)
    await authorize(ctx, target, journal, now)
    claim = await repo.claim(worker_id="crashed", lease_seconds=600, max_attempts=3)
    if consume_before_crash:
        assert (
            await repo.claim_strict_generated_visual(claimed=claim, plan=plan)
        ).outcome == "newly_claimed"
    async with ctx.session_factory() as session, session.begin():
        run = await session.get(Run, target.run_id)
        run.lease_expires_at = now - timedelta(seconds=1)
    successor = await repo.claim(worker_id="lease-recovery", lease_seconds=600, max_attempts=3)
    assert successor.attempt_number == 3
    value = await repo.claim_strict_generated_visual(claimed=successor, plan=plan)
    assert value.outcome == "result_unknown"
    async with ctx.session_factory() as session:
        consumed = (
            await session.scalars(
                select(Attempt).where(
                    Attempt.run_id == target.run_id, Attempt.stage == CONSUMED_STAGE
                )
            )
        ).all()
        assert len(consumed) == int(consume_before_crash)
    await repo.fail(
        claimed=successor,
        error_code="official_account_generated_visual_result_unknown",
        result_unknown=True,
        retryable=False,
        retry_base_seconds=1,
        max_attempts=3,
    )


@pytest.mark.parametrize("mutation", ["bundle", "article", "old_attempt"])
async def test_consumption_rechecks_immutable_inputs(integration_context, mutation):
    ctx = integration_context
    repo, target, plan, journal, now = await seed(ctx)
    auth = await authorize(ctx, target, journal, now)
    claim = await repo.claim(worker_id="mutated", lease_seconds=600, max_attempts=3)
    async with ctx.session_factory() as session, session.begin():
        if mutation == "bundle":
            run = await session.get(Run, target.run_id)
            run.version_bundle = {**run.version_bundle, "default_author": "changed"}
        elif mutation == "article":
            article = await session.get(Article, target.article_version_id)
            article.audit_snapshot = {**article.audit_snapshot, "accepted": False}
        else:
            attempt = await session.get(Attempt, auth.original_attempt_id)
            attempt.request_fingerprint = "f" * 64
    with pytest.raises(ValueError, match="precondition"):
        await repo.claim_strict_generated_visual(claimed=claim, plan=plan)
    async with ctx.session_factory() as session:
        visual = await session.get(Visual, target.visual_id)
        assert visual.status == "result_unknown"
        assert (
            await session.scalar(
                select(Attempt.id).where(
                    Attempt.run_id == target.run_id, Attempt.stage == CONSUMED_STAGE
                )
            )
            is None
        )
    await repo.fail(
        claimed=claim,
        error_code="official_account_generated_visual_result_unknown",
        result_unknown=True,
        retryable=False,
        retry_base_seconds=1,
        max_attempts=3,
    )


async def test_expired_authority_does_not_release_paid_claim(integration_context):
    ctx = integration_context
    repo, target, _plan_value, journal, now = await seed(ctx)
    async with ctx.session_factory() as session, session.begin():
        run = await session.get(Run, target.run_id)
        edition = await session.get(Edition, target.edition_id)
        earlier = now - timedelta(hours=4)
        edition.expires_at = earlier
        run.version_bundle = {
            **run.version_bundle,
            "execution_retry_policy": {
                **run.version_bundle["execution_retry_policy"],
                "expires_at": earlier.isoformat(),
            },
        }
    auth = await authorize(ctx, target, journal, now - timedelta(hours=3))
    assert auth.recovery_expires_at < now
    assert await repo.claim(worker_id="too-late", lease_seconds=600, max_attempts=3) is None
    assert (await repo.get_run(target.run_id)).attempt_count == 1
    assert await authorize(ctx, target, journal, now) == auth
    assert (await repo.get_run(target.run_id)).status == "failed"
