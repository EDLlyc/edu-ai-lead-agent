from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
import pytest_asyncio
from app.core.errors import ImageGenerationFailure
from app.domain.official_account_single_edition import edition_window
from app.domain.official_account_visual_pipeline import (
    RESILIENT_VISUAL_PIPELINE_VERSION,
    TOLERANT_VISUAL_PIPELINE_VERSION,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleAttemptModel as Attempt,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleRunModel as Run,
)
from app.infrastructure.db.models import (
    OfficialAccountSingleEditionModel as Edition,
)
from app.infrastructure.db.models import (
    WeComDeliveryJobModel,
)
from app.infrastructure.db.official_account_catalog_fallback import load_catalog_fallback_source
from app.infrastructure.db.official_account_single_edition import PostgresSingleEditionRepository
from app.infrastructure.db.official_account_single_status import single_edition_status
from sqlalchemy import func, select, update

from .test_official_account_strict_visual import _plan, _prime
from .test_wecom_slot_delivery_concurrency import _seed_slot_delivery_lane

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


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


@pytest_asyncio.fixture(loop_scope="session")
async def eligible_fallback(
    integration_context,
):
    ctx = integration_context
    async with ctx.session_factory() as session:
        prior_editions = await session.scalar(select(func.count()).select_from(Edition))
    # Each fixture owns a distinct future Monday and scheduled acquisition business key.
    now = datetime(2099, 1, 5, 2, tzinfo=UTC) + timedelta(weeks=prior_editions)
    window = edition_window(now.date())
    _, jobs, _, _ = await _seed_slot_delivery_lane(ctx, target_at=now)
    async with ctx.session_factory() as session:
        job = await session.get(WeComDeliveryJobModel, jobs[0])
        package_id = job.material_package_id
    repo, claimed, article, rendered = await _prime(ctx)
    identity = replace(claimed.identity, visual_pipeline_version=TOLERANT_VISUAL_PIPELINE_VERSION)
    claimed = replace(claimed, identity=identity)
    async with ctx.session_factory() as session, session.begin():
        await session.execute(
            update(Run)
            .where(Run.id == claimed.run_id)
            .values(
                generation_mode="live",
                fixture_id=None,
                provider="zhipu",
                material_package_id=package_id,
                version_bundle={
                    **asdict(identity),
                    "execution_retry_policy": {
                        "version": "single-edition-article-retry-v1",
                        "max_attempts": 3,
                        "retry_base_seconds": 1,
                        "expires_at": window.expires_at.isoformat(),
                    },
                },
            )
        )
    plan = _plan(claimed, article, rendered)
    plan = replace(plan, reference_catalog_version=article.article.media_selection.catalog_version)
    for number in range(1, 4):
        claim = await repo.claim_strict_generated_visual(claimed=claimed, plan=plan)
        assert claim.outcome == "newly_claimed" and claim.physical_attempt_number == number
        failure = ImageGenerationFailure(
            error_code="image_provider_timeout",
            disposition="unknown",
            reason="post_outcome_unknown",
        )
        assert await repo.fail_generated_visual(
            claimed=claimed,
            plan=plan,
            error_code="official_account_generated_visual_result_unknown",
            result_unknown=True,
            diagnostic=failure,
            provider_request_fingerprint=claim.provider_request_fingerprint,
            physical_attempt_number=number,
        )
    assert (
        await repo.claim_strict_generated_visual(claimed=claimed, plan=plan)
    ).outcome == "result_unknown"
    async with ctx.session_factory() as session, session.begin():
        await session.execute(
            update(Run)
            .where(Run.id == claimed.run_id)
            .values(
                status="failed",
                error_code="strict_visual_generation_attempts_exhausted",
                lease_token=None,
                lease_expires_at=None,
                lease_owner=None,
            )
        )
    account = sha256(uuid4().bytes).hexdigest()
    singles = PostgresSingleEditionRepository(ctx.session_factory)
    await singles.import_history(account, (), now=now)
    admitted = await singles.admit(
        account=account,
        window=window,
        identity=identity,
        max_attempts=3,
        retry_base_seconds=1,
        now=now,
    )
    async with ctx.session_factory() as session, session.begin():
        await session.execute(
            update(Edition)
            .where(Edition.id == admitted.id)
            .values(
                status="generating",
                article_run_id=claimed.run_id,
                material_package_id=package_id,
                role="official_anchor",
            )
        )
    edition = await singles.claim(account=account, delivery=False, now=now, lease_seconds=900)
    return ctx, now, window, claimed, article, rendered, account, edition


async def test_three_unknown_calls_fallback_proof_is_readonly_fenced_and_no_fourth(
    eligible_fallback,
):
    ctx, now, window, claimed, article, rendered, account, edition = eligible_fallback
    source = await load_catalog_fallback_source(ctx.session_factory, edition, now=now)
    assert source.evidence["physical_attempt_count"] == 3
    assert source.article.id == article.id and source.render.id == rendered.id
    assert await load_catalog_fallback_source(ctx.session_factory, edition, now=now) == source
    with pytest.raises(ValueError, match="ineligible"):
        await load_catalog_fallback_source(
            ctx.session_factory, replace(edition, lease_token=uuid4()), now=now
        )
    with pytest.raises(ValueError, match="ineligible"):
        await load_catalog_fallback_source(ctx.session_factory, edition, now=window.expires_at)
    settings = ctx.settings.model_copy(
        update={
            "official_account_single_enabled": True,
            "official_account_single_account_fingerprint": account,
            "official_account_single_min_date": date(2099, 1, 5),
            "official_account_local_visual_pipeline_version": TOLERANT_VISUAL_PIPELINE_VERSION,
        }
    )
    result = await single_edition_status(ctx.session_factory, settings, now=now)
    assert result["leases"] == {"active": 1, "stale": 0}
    assert result["next_window"]["business_date"] == "2099-01-07"
    assert result["readonly"] is True and result["legacy_mutual_exclusion"] is True
    assert result["publication_state"] == "not_checked"
    assert result["publishing_capability"] is False and "published" not in result
    legacy = await single_edition_status(
        ctx.session_factory,
        settings.model_copy(
            update={
                "official_account_local_visual_pipeline_version": RESILIENT_VISUAL_PIPELINE_VERSION,
            }
        ),
        now=now,
    )
    assert legacy["visual_pipeline_version"] == RESILIENT_VISUAL_PIPELINE_VERSION
    assert legacy["configured_visual_pipeline_version"] == RESILIENT_VISUAL_PIPELINE_VERSION
    async with ctx.session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Attempt)
                .where(Attempt.run_id == claimed.run_id, Attempt.ordinal.between(101, 103))
            )
            == 3
        )
        old = await session.get(Run, claimed.run_id)
        assert (
            old.status == "failed"
            and old.error_code == "strict_visual_generation_attempts_exhausted"
        )
    # A diagnostic changed to auth/config/decode is never transformed into fallback.
    async with ctx.session_factory() as session, session.begin():
        item = await session.scalar(
            select(Attempt).where(Attempt.run_id == claimed.run_id, Attempt.ordinal == 103)
        )
        item.safe_metadata = {
            **item.safe_metadata,
            **ImageGenerationFailure(
                error_code="provider_authentication_failed",
                disposition="terminal",
                reason="provider_failure",
            ).safe_metadata(),
        }
    with pytest.raises(ValueError, match="attempt_proof"):
        await load_catalog_fallback_source(ctx.session_factory, edition, now=now)


@pytest.mark.parametrize(
    "change",
    [
        "snapshot_date",
        "prepared",
        "receipt",
        "run_lease",
        "attempt_stage",
        "attempt_provider",
        "attempt_incomplete",
        "extra_attempt",
        "extra_incomplete_attempt",
        "legacy_policy",
    ],
)
async def test_fallback_rejects_noncanonical_state_without_rewriting_evidence(
    eligible_fallback, change
):
    ctx, now, _, claimed, article, _, _, edition = eligible_fallback
    async with ctx.session_factory() as session, session.begin():
        row = await session.get(Edition, edition.id)
        run = await session.get(Run, claimed.run_id)
        attempt = await session.scalar(
            select(Attempt).where(Attempt.run_id == claimed.run_id, Attempt.ordinal == 103)
        )
        if change == "snapshot_date":
            edition = replace(edition, business_date=row.business_date - timedelta(days=2))
        elif change == "prepared":
            row.prepared_artifact = {"version": "existing"}
        elif change == "receipt":
            row.receipt_fingerprint = "b" * 64
        elif change == "run_lease":
            run.lease_expires_at = now + timedelta(minutes=1)
        elif change == "legacy_policy":
            row.article_identity = {
                **row.article_identity,
                "visual_pipeline_version": RESILIENT_VISUAL_PIPELINE_VERSION,
            }
            run.version_bundle = {
                **run.version_bundle,
                "visual_pipeline_version": RESILIENT_VISUAL_PIPELINE_VERSION,
            }
            edition = replace(
                edition,
                identity=replace(
                    edition.identity, visual_pipeline_version=RESILIENT_VISUAL_PIPELINE_VERSION
                ),
            )
        elif change == "attempt_stage":
            attempt.stage = "not_visual_generation"
        elif change == "attempt_provider":
            attempt.provider = "different-provider"
        elif change == "attempt_incomplete":
            attempt.completed_at = None
        else:
            session.add(
                Attempt(
                    id=uuid4(),
                    run_id=claimed.run_id,
                    article_version_id=article.id,
                    stage="generating_body_visuals",
                    capability="visual_generation",
                    ordinal=104,
                    status="failed",
                    request_fingerprint="e" * 64,
                    provider=attempt.provider,
                    model=attempt.model,
                    safe_metadata={**attempt.safe_metadata, "physical_attempt_number": 4},
                    completed_at=None if change == "extra_incomplete_attempt" else now,
                )
            )
    with pytest.raises(ValueError, match="single_catalog_fallback"):
        await load_catalog_fallback_source(ctx.session_factory, edition, now=now)
    async with ctx.session_factory() as session:
        run = await session.get(Run, claimed.run_id)
        assert run.status == "failed"
        assert run.error_code == "strict_visual_generation_attempts_exhausted"
