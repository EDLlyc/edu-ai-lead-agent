"""Reads the 排版模板 an operator chose for an account in the 运营后台."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db.models import WeChatAccountModel


async def layout_template_for_account(
    sessions: async_sessionmaker[AsyncSession], account_fingerprint: str
) -> str | None:
    """None when the account is not bound in the console; the renderer colours then stay."""

    async with sessions() as session:
        chosen: str | None = await session.scalar(
            select(WeChatAccountModel.layout_template_id).where(
                WeChatAccountModel.account_fingerprint == account_fingerprint
            )
        )
    return chosen


__all__ = ["layout_template_for_account"]
