"""The approved-action executor retries a real failed slot delivery once, through the app role."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.application.services.ops_actions import (
    ActionLog,
    ActionRefused,
    FailedDelivery,
    approve,
    propose_resends,
)
from app.infrastructure.db.models import WeComDeliveryJobModel, WeComDeliveryWindowModel
from app.infrastructure.db.ops_actions import delivery_status_reader, retry_delivery_executor
from pydantic import SecretStr
from sqlalchemy import select, update

from .conftest import IntegrationContext
from .test_wecom_slot_delivery_concurrency import _seed_slot_delivery_lane


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_an_approved_resend_requeues_the_failed_slot_delivery_once(
    integration_context: IntegrationContext, tmp_path: Path
) -> None:
    now = datetime.now(UTC)
    window_id, job_ids, business_date, _profile = await _seed_slot_delivery_lane(
        integration_context, target_at=now + timedelta(minutes=10)
    )
    async with integration_context.session_factory() as session:
        window = await session.get(WeComDeliveryWindowModel, window_id)
        assert window is not None
        slot = window.content_slot
        failed = await session.get(WeComDeliveryJobModel, job_ids[1])
        assert failed is not None
        ordinal = failed.sequence_ordinal
        await session.execute(
            update(WeComDeliveryJobModel)
            .where(WeComDeliveryJobModel.id == job_ids[1])
            .values(status="failed", last_error_code="wecom_rate_limited", attempt_count=3)
        )
        await session.commit()
    settings = integration_context.settings.model_copy(
        update={
            "wecom_enabled": True,
            "wecom_delivery_provider": "group_webhook",
            "wecom_group_webhook_key": SecretStr("integration-test-key"),
        }
    )
    log = ActionLog(tmp_path / "actions.jsonl")
    (proposal,) = propose_resends(
        log,
        business_date=business_date,
        slot=slot,
        deliveries=(FailedDelivery(slot, ordinal, "failed", "wecom_rate_limited"),),
        reason="限流失败",
        proposed_by="test",
        now=now,
        window_end=lambda _target: now + timedelta(hours=1),
    )
    execute = retry_delivery_executor(integration_context.session_factory, settings)

    status = await approve(log, proposal.id, by="运营", now=now, enabled=True, execute=execute)

    assert status == "executed"
    async with integration_context.session_factory() as session:
        job = await session.scalar(
            select(WeComDeliveryJobModel).where(WeComDeliveryJobModel.id == job_ids[1])
        )
    assert job is not None
    assert (job.status, job.attempt_count, job.last_error_code) == ("queued", 0, None)
    assert await delivery_status_reader(integration_context.session_factory)(proposal.target) == (
        "queued"
    )
    # Running it again finds nothing to retry: the executor re-checks the live state.
    with pytest.raises(ActionRefused) as again:
        await execute(proposal)
    assert again.value.code == "not_retryable"
