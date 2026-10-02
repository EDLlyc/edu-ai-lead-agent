"""Execute approved ops actions with the app's own role, never the agent's read-only one."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.services.ops_actions import (
    RETRYABLE_DELIVERY_STATUSES,
    ActionProposal,
    ActionRefused,
    ActionTarget,
    Executor,
    StatusReader,
)
from app.application.services.wecom_delivery import retry_wecom_delivery
from app.core.config import Settings
from app.infrastructure.db.models import WeComDeliveryJobModel, WeComDeliveryWindowModel


async def _slot_jobs(session: AsyncSession, target: ActionTarget) -> list[tuple[UUID, str]]:
    job, window = WeComDeliveryJobModel, WeComDeliveryWindowModel
    rows = (
        await session.execute(
            select(job.id, job.status)
            .join(window, job.delivery_window_id == window.id)
            .where(
                window.business_date == target.business_date,
                window.content_slot == target.content_slot,
                window.lane_key == "slot",
                window.mode == "formal",
                job.sequence_ordinal == target.sequence_ordinal,
            )
            .order_by(job.created_at)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


def retry_delivery_executor(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> Executor:
    async def execute(proposal: ActionProposal) -> dict[str, Any]:
        if proposal.action != "retry_delivery":
            raise ActionRefused("action_not_allowed", proposal.action)
        async with session_factory() as session:
            jobs = await _slot_jobs(session, proposal.target)
            retryable = [job_id for job_id, status in jobs if status in RETRYABLE_DELIVERY_STATUSES]
            if not jobs:
                raise ActionRefused("target_not_found", "找不到这条发送任务")
            if not retryable:
                raise ActionRefused("not_retryable", "这条发送任务已不是失败状态")
            if len(retryable) > 1:
                raise ActionRefused("ambiguous_target", "同一位置有多条失败的发送任务")
            # The delivery service re-checks the job's state and window under a row lock.
            job = await retry_wecom_delivery(
                session=session, delivery_id=retryable[0], settings=settings
            )
            return {"delivery_status": job.status, "job": str(job.id)[:8]}

    return execute


def delivery_status_reader(session_factory: async_sessionmaker[AsyncSession]) -> StatusReader:
    async def read(target: ActionTarget) -> str | None:
        async with session_factory() as session:
            jobs = await _slot_jobs(session, target)
        return jobs[-1][1] if jobs else None

    return read
