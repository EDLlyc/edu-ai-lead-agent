"""运营后台 · 排版模板: preview the colour schemes and choose one per account."""

from __future__ import annotations

from datetime import datetime
from functools import cache
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.admin_auth import AdminPrincipal
from app.application.services.wechat_admin import WeChatAdminRejected
from app.core.errors import NotFoundError
from app.domain.official_account_layout_templates import (
    apply_layout_template,
    is_layout_template,
    layout_template,
)
from app.infrastructure.db.admin_auth import add_audit_event
from app.infrastructure.db.models import WeChatAccountModel

# A real article body from the renderer, with its photos replaced by a grey placeholder.
_SAMPLE = Path(__file__).resolve().parents[2] / "assets" / "official_account_layout_sample.html"


@cache
def _sample() -> str:
    return _SAMPLE.read_text(encoding="utf-8")


def layout_preview(template_id: str) -> str:
    if not is_layout_template(template_id):
        raise NotFoundError("layout template")
    return apply_layout_template(_sample(), template_id)


async def list_account_layouts(session: AsyncSession) -> list[WeChatAccountModel]:
    return list(
        (
            await session.scalars(
                select(WeChatAccountModel)
                .where(WeChatAccountModel.enabled.is_(True))
                .order_by(WeChatAccountModel.created_at)
            )
        ).all()
    )


async def set_layout_template(
    session: AsyncSession,
    *,
    principal: AdminPrincipal,
    account_id: UUID,
    template_id: str,
    now: datetime,
) -> WeChatAccountModel:
    if not is_layout_template(template_id):
        raise WeChatAdminRejected("没有这个排版模板", "wechat_layout_template_unknown")
    account = await session.scalar(
        select(WeChatAccountModel).where(WeChatAccountModel.id == account_id).with_for_update()
    )
    if account is None:
        raise NotFoundError("wechat account")
    previous = account.layout_template_id
    if previous == template_id:
        await session.rollback()
        return account
    account.layout_template_id = template_id
    account.updated_at = now
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="wechat_account.layout_template_set",
        target_type="wechat_account",
        target_id=str(account.id),
        detail={
            "name": account.name,
            "from": previous,
            "to": template_id,
            "template": layout_template(template_id).name,
        },
    )
    await session.commit()
    return account


__all__ = ["layout_preview", "list_account_layouts", "set_layout_template"]
