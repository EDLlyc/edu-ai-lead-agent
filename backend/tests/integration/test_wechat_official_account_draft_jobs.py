from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from app.domain.official_account_weekly_edition import (
    WEEKLY_EDITION_ROLE_ORDER,
    WeeklyArticleRole,
)
from app.domain.wechat_official_account_draft_jobs import (
    WeChatDraftAttemptStatus,
    WeChatDraftItemStatus,
    WeChatDraftJobEnqueue,
    WeChatDraftJobFailure,
    WeChatDraftJobItemInput,
    WeChatDraftJobStatus,
    draft_media_fingerprint,
    wechat_draft_account_fingerprint,
    wechat_draft_policy_fingerprint,
)
from app.infrastructure.db.models import (
    WeChatOfficialAccountDraftAttemptModel,
    WeChatOfficialAccountDraftItemModel,
    WeChatOfficialAccountDraftJobModel,
)
from app.infrastructure.db.wechat_official_account_draft_jobs import (
    PostgresWeChatOfficialAccountDraftJobRepository,
)
from sqlalchemy import delete, select

from .conftest import IntegrationContext

_NOW = datetime(2099, 1, 5, 1, tzinfo=UTC)


def _sha(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _command(identity: str, *, max_attempts: int = 3) -> WeChatDraftJobEnqueue:
    items = tuple(
        WeChatDraftJobItemInput(
            role=WeeklyArticleRole(role),
            ordinal=ordinal,
            source_ref=f"wechat-draft-v1:{_sha(identity)}:{role}",
            source_fingerprint=_sha(f"{identity}:source:{role}"),
            article_fingerprint=_sha(f"{identity}:article:{role}"),
            content_fingerprint=_sha(f"{identity}:content:{role}"),
            policy_fingerprint=wechat_draft_policy_fingerprint(
                content_source_url=None,
                need_open_comment=False,
                only_fans_can_comment=False,
            ),
        )
        for ordinal, role in enumerate(WEEKLY_EDITION_ROLE_ORDER, start=1)
    )
    return WeChatDraftJobEnqueue(
        account_fingerprint=wechat_draft_account_fingerprint("wx-test-account"),
        aggregate_fingerprint=_sha(f"{identity}:aggregate"),
        batch_fingerprint=_sha(f"{identity}:batch"),
        items=items,
        max_attempts=max_attempts,
    )


async def _cleanup(context: IntegrationContext, *commands: WeChatDraftJobEnqueue) -> None:
    job_ids = tuple(command.job_id for command in commands)
    async with context.session_factory() as session, session.begin():
        await session.execute(
            delete(WeChatOfficialAccountDraftAttemptModel).where(
                WeChatOfficialAccountDraftAttemptModel.job_id.in_(job_ids)
            )
        )
        await session.execute(
            delete(WeChatOfficialAccountDraftItemModel).where(
                WeChatOfficialAccountDraftItemModel.job_id.in_(job_ids)
            )
        )
        await session.execute(
            delete(WeChatOfficialAccountDraftJobModel).where(
                WeChatOfficialAccountDraftJobModel.id.in_(job_ids)
            )
        )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_wechat_draft_job_is_idempotent_and_resumes_three_ordered_items(
    integration_context: IntegrationContext,
) -> None:
    command = _command("idempotent-resume")
    repository = PostgresWeChatOfficialAccountDraftJobRepository(
        integration_context.session_factory
    )
    try:
        concurrent_results = await asyncio.gather(
            repository.enqueue(command, now=_NOW),
            repository.enqueue(command, now=_NOW),
        )
        assert sorted(created for _status, created in concurrent_results) == [False, True]
        first = concurrent_results[0][0]
        replay, replay_created = await repository.enqueue(
            command,
            now=_NOW + timedelta(seconds=1),
        )
        assert not replay_created
        assert first.job.job_id == replay.job.job_id == command.job_id
        assert tuple(item.role.value for item in first.items) == WEEKLY_EDITION_ROLE_ORDER

        first_claim = await repository.claim_next(
            worker_id="wechat.worker.one",
            now=_NOW,
            lease_seconds=30,
        )
        assert first_claim is not None
        assert first_claim.item.ordinal == 1
        assert await repository.mark_side_effect_started(
            first_claim,
            endpoint="upload_inline_image",
            now=_NOW + timedelta(seconds=1),
        )
        partial = await repository.succeed(
            first_claim,
            endpoint="draft_add",
            uploaded_image_count=5,
            draft_media_fingerprint=draft_media_fingerprint("provider-media-id-1"),
            now=_NOW + timedelta(seconds=2),
        )
        assert partial.job.status is WeChatDraftJobStatus.QUEUED
        assert partial.items[0].status is WeChatDraftItemStatus.SUCCEEDED

        second_claim = await repository.claim_next(
            worker_id="wechat.worker.two",
            now=_NOW + timedelta(seconds=3),
            lease_seconds=30,
        )
        assert second_claim is not None
        assert second_claim.item.ordinal == 2
        retry = await repository.fail_known(
            second_claim,
            error_code="provider_rate_limited",
            endpoint="upload_inline_image",
            retryable=True,
            uploaded_image_count=0,
            available_at=_NOW + timedelta(seconds=10),
            now=_NOW + timedelta(seconds=4),
        )
        assert retry.job.status is WeChatDraftJobStatus.RETRYABLE_FAILED
        assert (
            await repository.claim_next(
                worker_id="wechat.worker.early",
                now=_NOW + timedelta(seconds=9),
                lease_seconds=30,
            )
            is None
        )

        for ordinal, offset in ((2, 10), (3, 20)):
            claim = await repository.claim_next(
                worker_id=f"wechat.worker.{ordinal}",
                now=_NOW + timedelta(seconds=offset),
                lease_seconds=30,
            )
            assert claim is not None
            assert claim.item.ordinal == ordinal
            assert await repository.mark_side_effect_started(
                claim,
                endpoint="upload_inline_image",
                now=_NOW + timedelta(seconds=offset + 1),
            )
            status = await repository.succeed(
                claim,
                endpoint="draft_add",
                uploaded_image_count=ordinal + 3,
                draft_media_fingerprint=draft_media_fingerprint(f"provider-media-id-{ordinal}"),
                now=_NOW + timedelta(seconds=offset + 2),
            )

        assert status.job.status is WeChatDraftJobStatus.READY
        assert all(item.status is WeChatDraftItemStatus.SUCCEEDED for item in status.items)
        assert tuple(item.attempt_count for item in status.items) == (1, 2, 1)
        safe = str(status.as_dict()).lower()
        assert "provider-media-id" not in safe
        assert "source_ref" not in safe
        assert "/root/" not in safe

        async with integration_context.session_factory() as session:
            attempts = tuple(
                await session.scalars(
                    select(WeChatOfficialAccountDraftAttemptModel)
                    .where(WeChatOfficialAccountDraftAttemptModel.job_id == command.job_id)
                    .order_by(
                        WeChatOfficialAccountDraftAttemptModel.item_ordinal,
                        WeChatOfficialAccountDraftAttemptModel.attempt_no,
                    )
                )
            )
        assert tuple(attempt.status for attempt in attempts) == (
            WeChatDraftAttemptStatus.SUCCEEDED.value,
            WeChatDraftAttemptStatus.RETRYABLE_FAILED.value,
            WeChatDraftAttemptStatus.SUCCEEDED.value,
            WeChatDraftAttemptStatus.SUCCEEDED.value,
        )
    finally:
        await _cleanup(integration_context, command)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_wechat_draft_stale_lease_reclaims_only_before_side_effect(
    integration_context: IntegrationContext,
) -> None:
    command = _command("stale-fencing")
    repository = PostgresWeChatOfficialAccountDraftJobRepository(
        integration_context.session_factory
    )
    try:
        await repository.enqueue(command, now=_NOW)
        stale = await repository.claim_next(
            worker_id="wechat.worker.stale",
            now=_NOW,
            lease_seconds=3,
        )
        assert stale is not None
        with pytest.raises(WeChatDraftJobFailure, match="invalid_checkpoint"):
            await repository.mark_outcome_unknown(
                stale,
                error_code="wechat_mp_outcome_unknown",
                endpoint="draft_add",
                uploaded_image_count=0,
                now=_NOW + timedelta(seconds=1),
            )
        reclaimed = await repository.claim_next(
            worker_id="wechat.worker.reclaimed",
            now=_NOW + timedelta(seconds=4),
            lease_seconds=3,
        )
        assert reclaimed is not None
        assert reclaimed.item.ordinal == stale.item.ordinal == 1
        assert reclaimed.item.attempt_count == stale.item.attempt_count + 1
        assert reclaimed.job.fencing_token == stale.job.fencing_token + 1
        assert not await repository.heartbeat(
            stale,
            now=_NOW + timedelta(seconds=4),
            lease_seconds=3,
        )
        with pytest.raises(WeChatDraftJobFailure, match="lease_lost"):
            await repository.succeed(
                stale,
                endpoint="draft_add",
                uploaded_image_count=1,
                draft_media_fingerprint=draft_media_fingerprint("stale-result"),
                now=_NOW + timedelta(seconds=4),
            )

        assert await repository.mark_side_effect_started(
            reclaimed,
            endpoint="upload_inline_image",
            now=_NOW + timedelta(seconds=5),
        )
        assert (
            await repository.claim_next(
                worker_id="wechat.worker.must-not-replay",
                now=_NOW + timedelta(seconds=8),
                lease_seconds=3,
            )
            is None
        )
        status = await repository.get_status(command.job_id)
        assert status.job.status is WeChatDraftJobStatus.OUTCOME_UNKNOWN
        assert status.items[0].status is WeChatDraftItemStatus.OUTCOME_UNKNOWN
        assert status.items[0].error_code == "lease_lost_after_side_effect"

        async with integration_context.session_factory() as session:
            attempts = tuple(
                await session.scalars(
                    select(WeChatOfficialAccountDraftAttemptModel)
                    .where(WeChatOfficialAccountDraftAttemptModel.job_id == command.job_id)
                    .order_by(WeChatOfficialAccountDraftAttemptModel.attempt_no)
                )
            )
        assert tuple(attempt.status for attempt in attempts) == (
            WeChatDraftAttemptStatus.LEASE_EXPIRED.value,
            WeChatDraftAttemptStatus.OUTCOME_UNKNOWN.value,
        )
    finally:
        await _cleanup(integration_context, command)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_wechat_draft_concurrent_claims_are_distinct(
    integration_context: IntegrationContext,
) -> None:
    first = _command("concurrent-first")
    second = _command("concurrent-second")
    repository = PostgresWeChatOfficialAccountDraftJobRepository(
        integration_context.session_factory
    )
    try:
        await asyncio.gather(
            repository.enqueue(first, now=_NOW),
            repository.enqueue(second, now=_NOW),
        )
        claims = await asyncio.gather(
            repository.claim_next(
                worker_id="wechat.worker.concurrent.one",
                now=_NOW,
                lease_seconds=30,
            ),
            repository.claim_next(
                worker_id="wechat.worker.concurrent.two",
                now=_NOW,
                lease_seconds=30,
            ),
        )
        assert all(claim is not None for claim in claims)
        assert len({claim.job.job_id for claim in claims if claim is not None}) == 2
    finally:
        await _cleanup(integration_context, first, second)
