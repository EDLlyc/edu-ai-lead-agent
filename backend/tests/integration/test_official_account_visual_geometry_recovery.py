from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from app.application.ports.official_account_local import OfficialAccountGeneratedVisualResult
from app.application.ports.official_account_strict_visual import (
    RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS,
    resilient_visual_attempt_ordinal,
)
from app.core.errors import ImageGenerationFailure
from app.domain.official_account_local import fingerprint
from app.domain.official_account_single_edition import edition_window
from app.infrastructure.db.models import EventClusterModel
from app.infrastructure.db.models import OfficialAccountArticleAttemptModel as Attempt
from app.infrastructure.db.models import OfficialAccountArticleRunModel as Run
from app.infrastructure.db.models import OfficialAccountGeneratedVisualModel as Visual
from app.infrastructure.db.models import OfficialAccountSingleEditionModel as Edition
from app.infrastructure.db.official_account_visual_geometry_recovery import (
    AUTH_STAGE,
    CONSUMED_STAGE,
    RECOVERY_PHYSICAL_ATTEMPT_NUMBER,
    GeometryRecoveryTarget,
    authorize_visual_geometry_recovery,
    geometry_recovery_attempt_ordinal,
)
from sqlalchemy import select

from .test_official_account_strict_visual import _enable_resilient_policy, _plan, _prime

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]
NOW = datetime(2026, 9, 18, 6, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    for module in (
        "app.infrastructure.db.official_account_local",
        "app.infrastructure.db.official_account_strict_visual",
        "app.infrastructure.db.official_account_visual_geometry_recovery",
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


async def _seed(context):
    repo, claimed, article, rendered = await _prime(context, available_at=NOW)
    claimed = await _enable_resilient_policy(context, claimed)
    window = edition_window(NOW.date())
    async with context.session_factory() as session, session.begin():
        run = await session.get(Run, claimed.run_id)
        assert run is not None
        run.version_bundle = {
            **run.version_bundle,
            "execution_retry_policy": {
                **run.version_bundle["execution_retry_policy"],
                "expires_at": window.expires_at.isoformat(),
            },
        }
    plan = _plan(claimed, article, rendered)
    proof = ImageGenerationFailure(
        error_code="image_output_invalid",
        disposition="terminal",
        reason="image_dimensions_invalid",
    )
    for physical_attempt in range(1, RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS + 1):
        visual_claim = await repo.claim_strict_generated_visual(claimed=claimed, plan=plan)
        assert visual_claim.outcome == "newly_claimed"
        assert visual_claim.physical_attempt_number == physical_attempt
        assert await repo.fail_generated_visual(
            claimed=claimed,
            plan=plan,
            error_code=proof.error_code,
            diagnostic=proof,
            provider_request_fingerprint=visual_claim.provider_request_fingerprint,
            physical_attempt_number=visual_claim.physical_attempt_number,
        )
    assert await repo.fail(
        claimed=claimed,
        error_code="image_output_invalid",
        retryable=False,
        retry_base_seconds=1,
        max_attempts=3,
        safe_metadata=proof.safe_metadata(),
    )
    visual = await repo.get_generated_visual(run_id=claimed.run_id, ordinal=plan.ordinal)
    assert visual is not None and visual.status == "failed"
    account = fingerprint("geometry-recovery", uuid4())
    event_id, edition_id = uuid4(), uuid4()
    async with context.session_factory() as session, session.begin():
        run = await session.get(Run, claimed.run_id)
        assert run is not None and run.status == "failed"
        session.add(EventClusterModel(id=event_id, status="active"))
        session.add(
            Edition(
                id=edition_id,
                account_fingerprint=account,
                business_date=NOW.date(),
                timezone="Asia/Shanghai",
                version="official-account-single-edition-v1",
                prepare_at=window.prepare_at,
                deliver_at=window.deliver_at,
                expires_at=window.expires_at,
                article_identity=asdict(claimed.identity),
                retry_policy={"max_attempts": 3, "retry_base_seconds": 1},
                status="failed",
                stage_attempts={},
                available_at=NOW,
                selection_artifact={"version": "test", "fingerprint": "b" * 64},
                event_id=event_id,
                article_run_id=run.id,
                role="official_anchor",
                error_code="single_article_failed",
                created_at=NOW,
                updated_at=NOW,
            )
        )
    target = GeometryRecoveryTarget(
        edition_id=edition_id,
        run_id=claimed.run_id,
        article_version_id=article.id,
        visual_id=visual.id,
        business_date=NOW.date(),
    )
    return repo, claimed, article, rendered, plan, target


async def _authorize(context, target, *, apply=True):
    async with context.session_factory() as session, session.begin():
        return await authorize_visual_geometry_recovery(
            session, target=target, now=NOW, apply=apply
        )


async def test_one_dimension_recovery_preserves_three_attempts_and_fences_a_fourth(
    integration_context,
):
    repo, claimed, _article, _rendered, plan, target = await _seed(integration_context)
    before_article, before_render = (
        await repo.get_article(target.run_id),
        await repo.get_render(target.run_id),
    )
    preview = await _authorize(integration_context, target, apply=False)
    assert (await repo.get_run(target.run_id)).status == "failed"
    auth = await _authorize(integration_context, target)
    assert auth == preview
    assert (await repo.get_article(target.run_id), await repo.get_render(target.run_id)) == (
        before_article,
        before_render,
    )
    recovery_claim = await repo.claim(
        worker_id="geometry-recovery", lease_seconds=600, max_attempts=3
    )
    assert recovery_claim is not None
    claimed = recovery_claim
    claims = await asyncio.gather(
        *(repo.claim_strict_generated_visual(claimed=claimed, plan=plan) for _ in range(3))
    )
    recovered = next(item for item in claims if item.outcome == "newly_claimed")
    assert sorted(item.outcome for item in claims) == ["in_flight", "in_flight", "newly_claimed"]
    assert recovered.physical_attempt_number == RECOVERY_PHYSICAL_ATTEMPT_NUMBER
    assert recovered.output_geometry_policy == "native-tolerant-v1"
    assert recovered.provider_request_fingerprint == auth.provider_request_fingerprint
    stored = await repo.persist_generated_visual(
        claimed=claimed,
        plan=plan,
        result=OfficialAccountGeneratedVisualResult(
            media_type="image/jpeg",
            byte_size=100,
            sha256=fingerprint("geometry-recovery-publication", target.run_id),
            width=1536,
            height=1024,
        ),
        provider_request_fingerprint=recovered.provider_request_fingerprint,
        physical_attempt_number=recovered.physical_attempt_number,
    )
    assert stored is not None and stored.status == "ready"
    async with integration_context.session_factory() as session:
        attempts = tuple(
            (
                await session.scalars(
                    select(Attempt)
                    .where(Attempt.run_id == target.run_id)
                    .order_by(Attempt.stage, Attempt.ordinal)
                )
            ).all()
        )
        assert sum(item.stage == AUTH_STAGE for item in attempts) == 1
        assert sum(item.stage == CONSUMED_STAGE for item in attempts) == 1
        visual_attempts = [
            item
            for item in attempts
            if item.stage == "generating_body_visuals" and item.capability == "visual_generation"
        ]
        assert [item.ordinal for item in visual_attempts] == [
            *(resilient_visual_attempt_ordinal(plan.ordinal, number) for number in range(1, 4)),
            geometry_recovery_attempt_ordinal(plan.ordinal),
        ]
        assert [item.status for item in visual_attempts] == [
            "failed",
            "failed",
            "failed",
            "succeeded",
        ]
        assert visual_attempts[-1].safe_metadata["output_geometry_policy"] == "native-tolerant-v1"
    run = await repo.get_run(target.run_id)
    assert (
        run is not None
        and run.current_stage == "staging_body_media"
        and run.active_draft_id is None
    )
    assert await repo.get_draft(target.run_id) is None


@pytest.mark.parametrize("mutation", ["unknown", "draft", "expired", "repeat"])
async def test_geometry_recovery_rejects_nonterminal_or_already_owned_boundaries(
    integration_context, mutation: str
):
    repo, _claimed, _article, _rendered, _plan_value, target = await _seed(integration_context)
    if mutation == "unknown":
        async with integration_context.session_factory() as session, session.begin():
            visual = await session.get(Visual, target.visual_id)
            assert visual is not None
            visual.status, visual.error_code = (
                "result_unknown",
                "official_account_generated_visual_result_unknown",
            )
    elif mutation == "draft":
        async with integration_context.session_factory() as session, session.begin():
            edition = await session.get(Edition, target.edition_id)
            assert edition is not None
            edition.receipt_fingerprint = "e" * 64
    elif mutation == "expired":
        async with integration_context.session_factory() as session, session.begin():
            run = await session.get(Run, target.run_id)
            assert run is not None
            run.version_bundle = {
                **run.version_bundle,
                "execution_retry_policy": {
                    **run.version_bundle["execution_retry_policy"],
                    "expires_at": (NOW - timedelta(seconds=1)).isoformat(),
                },
            }
    elif mutation == "repeat":
        await _authorize(integration_context, target)
        # A repeat authorization is an idempotent receipt, never another provider call.
        assert await _authorize(integration_context, target) == await _authorize(
            integration_context, target, apply=False
        )
        return
    with pytest.raises(ValueError, match="precondition"):
        await _authorize(integration_context, target)
    assert (await repo.get_run(target.run_id)).status == "failed"
