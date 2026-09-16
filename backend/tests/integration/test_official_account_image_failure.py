from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from app.core.errors import ConflictError, ImageGenerationFailure
from app.infrastructure.db.models import (
    OfficialAccountArticleAttemptModel,
    OfficialAccountArticleRunModel,
    OfficialAccountGeneratedVisualModel,
)
from app.infrastructure.db.official_account_local import PostgresOfficialAccountRepository
from sqlalchemy import select, update

from .test_official_account_strict_visual import _generated, _plan, _prime, integration_context

__all__ = ["integration_context"]
pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


def _proof():
    return ImageGenerationFailure("provider_unavailable", "not_applied_retryable", "connect_failed")


async def _freeze(context, claimed, *, maximum=4, expired=False):
    now = datetime.now(UTC)
    async with context.session_factory() as session:
        row = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
        row.version_bundle = row.version_bundle | {
            "execution_retry_policy": {
                "version": "single-edition-article-retry-v1",
                "max_attempts": maximum,
                "retry_base_seconds": 1,
                "expires_at": (now + timedelta(hours=-1 if expired else 1)).isoformat(),
            }
        }
        await session.commit()


async def _fail_slot(repo, claimed, plan, *, proof=None, unknown=False):
    assert await repo.fail_generated_visual(
        claimed=claimed,
        plan=plan,
        error_code="official_account_generated_visual_result_unknown"
        if unknown
        else "provider_unavailable",
        diagnostic=proof,
        result_unknown=unknown,
    )
    assert await repo.fail(
        claimed=claimed,
        error_code="official_account_generated_visual_result_unknown"
        if unknown
        else "provider_unavailable",
        retryable=not unknown,
        retry_base_seconds=1,
        max_attempts=6,
        result_unknown=unknown,
        safe_metadata=proof.safe_metadata() if proof else None,
    )


async def _claim_due(context, repo, run_id):
    async with context.session_factory() as session:
        await session.execute(
            update(OfficialAccountArticleRunModel)
            .where(OfficialAccountArticleRunModel.id == run_id)
            .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    claimed = await repo.claim(worker_id="image-retry", lease_seconds=600, max_attempts=6)
    assert claimed is not None and claimed.run_id == run_id
    return claimed


async def test_safe_failed_slot_reclaims_once_after_restart_and_preserves_ready_content(
    integration_context,
):
    context = integration_context
    repo, claimed, article, rendered = await _prime(context)
    await _freeze(context, claimed)
    ready = await _generated(repo, claimed, article, rendered, ordinal=0)
    plan = _plan(claimed, article, rendered, ordinal=1)
    first = await repo.claim_strict_generated_visual(claimed=claimed, plan=plan)
    assert first.outcome == "newly_claimed"
    proof = _proof()
    assert await repo.fail_generated_visual(
        claimed=claimed, plan=plan, error_code=proof.error_code, diagnostic=proof
    )
    # The same run attempt cannot retry even though it still has a live lease.
    assert (
        await repo.claim_strict_generated_visual(claimed=claimed, plan=plan)
    ).outcome == "completed"
    assert await repo.fail(
        claimed=claimed,
        error_code=proof.error_code,
        retryable=True,
        retry_base_seconds=1,
        max_attempts=6,
        safe_metadata=proof.safe_metadata(),
    )
    state = await repo.get_run(claimed.run_id)
    assert state.status == "queued" and state.error_retryable
    assert state.active_article_version_id == article.id
    assert state.active_render_version_id == rendered.id
    restarted = PostgresOfficialAccountRepository(context.session_factory)
    successor = await _claim_due(context, restarted, claimed.run_id)
    claims = await asyncio.gather(
        *(restarted.claim_strict_generated_visual(claimed=successor, plan=plan) for _ in range(3))
    )
    assert sorted(item.outcome for item in claims) == ["in_flight", "in_flight", "newly_claimed"]
    retried = next(item for item in claims if item.outcome == "newly_claimed")
    assert retried.visual.id == first.visual.id
    assert retried.provider_request_fingerprint is None
    sibling = await restarted.claim_strict_generated_visual(claimed=successor, plan=ready.plan)
    assert sibling.outcome == "completed" and sibling.visual == ready
    assert (await restarted.get_article(claimed.run_id)) == article
    assert (await restarted.get_render(claimed.run_id)) == rendered
    # A stale worker cannot write another failure over the new intent.
    assert not await repo.fail_generated_visual(
        claimed=claimed, plan=plan, error_code=proof.error_code, diagnostic=proof
    )
    async with context.session_factory() as session:
        attempts = list(
            await session.scalars(
                select(OfficialAccountArticleAttemptModel).where(
                    OfficialAccountArticleAttemptModel.run_id == claimed.run_id,
                    OfficialAccountArticleAttemptModel.error_code == proof.error_code,
                )
            )
        )
    assert {item.capability for item in attempts} == {"visual_generation", "workflow"}
    assert all(
        item.safe_metadata["image_failure"] == proof.safe_metadata()["image_failure"]
        for item in attempts
    )
    # Complete the isolated test's run without leaving an eligible pending fixture.
    await _fail_slot(restarted, successor, plan, unknown=True)


@pytest.mark.parametrize("mode", ["exhausted", "expired", "legacy"])
async def test_run_retry_budget_cannot_be_reset_or_extended(integration_context, mode):
    context = integration_context
    repo, claimed, article, rendered = await _prime(context)
    if mode != "legacy":
        await _freeze(context, claimed, maximum=claimed.attempt_number, expired=mode == "expired")
    plan = _plan(claimed, article, rendered)
    assert (
        await repo.claim_strict_generated_visual(claimed=claimed, plan=plan)
    ).outcome == "newly_claimed"
    await _fail_slot(repo, claimed, plan, proof=_proof())
    state = await repo.get_run(claimed.run_id)
    assert state.status == "failed"
    assert state.attempt_count == claimed.attempt_number
    with pytest.raises(ConflictError):
        await PostgresOfficialAccountRepository(context.session_factory).retry(
            run_id=claimed.run_id, max_attempts=100
        )


@pytest.mark.parametrize("mode", ["legacy_failed", "unknown", "orphan", "tampered"])
async def test_ambiguous_or_unproven_slot_never_replays(integration_context, mode):
    context = integration_context
    repo, claimed, article, rendered = await _prime(context)
    await _freeze(context, claimed)
    plan = _plan(claimed, article, rendered)
    first = await repo.claim_strict_generated_visual(claimed=claimed, plan=plan)
    assert first.outcome == "newly_claimed"
    if mode == "orphan":
        async with context.session_factory() as session:
            await session.execute(
                update(OfficialAccountArticleRunModel)
                .where(OfficialAccountArticleRunModel.id == claimed.run_id)
                .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await session.commit()
    else:
        await _fail_slot(
            repo,
            claimed,
            plan,
            proof=_proof() if mode == "tampered" else None,
            unknown=mode == "unknown",
        )
        if mode == "unknown":
            with pytest.raises(ConflictError):
                await repo.retry(run_id=claimed.run_id, max_attempts=6)
            # Exercise defense in depth against a generic stale/operator queue reset.
            async with context.session_factory() as session:
                await session.execute(
                    update(OfficialAccountArticleRunModel)
                    .where(OfficialAccountArticleRunModel.id == claimed.run_id)
                    .values(status="queued", current_stage="generating_body_visuals")
                )
                await session.commit()
        if mode == "tampered":
            async with context.session_factory() as session:
                attempt = await session.scalar(
                    select(OfficialAccountArticleAttemptModel).where(
                        OfficialAccountArticleAttemptModel.run_id == claimed.run_id,
                        OfficialAccountArticleAttemptModel.capability == "visual_generation",
                    )
                )
                bad_proof = _proof().safe_metadata()["image_failure"] | {"http_status": 500}
                attempt.safe_metadata = attempt.safe_metadata | {"image_failure": bad_proof}
                await session.commit()
    successor = await _claim_due(context, repo, claimed.run_id)
    blocked = await repo.claim_strict_generated_visual(claimed=successor, plan=plan)
    assert blocked.outcome == ("result_unknown" if mode in {"unknown", "orphan"} else "completed")
    assert blocked.visual.id == first.visual.id
    assert blocked.visual.status != "generating"
    async with context.session_factory() as session:
        row = await session.get(OfficialAccountGeneratedVisualModel, first.visual.id)
        assert row.intent_attempt_number == claimed.attempt_number
    assert await repo.fail(
        claimed=successor,
        error_code="official_account_generated_visual_result_unknown",
        retryable=False,
        retry_base_seconds=1,
        max_attempts=6,
        result_unknown=True,
    )
