# ruff: noqa: RUF001
"""Edit the operator keyword lists from the 运营后台.

Each save is a new immutable version and becomes the active set; content-slot runs created after
it record and use it, earlier runs keep theirs. Before saving, the 屏蔽词 are tried on the last
seven days of slot candidates; blocking more than `WIDE_BLOCK_SHARE` of them needs an explicit
confirmation. Every save is audited with the added and removed terms.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.admin_auth import AdminPrincipal
from app.core.errors import AppError, ConflictError
from app.domain.operator_keywords import (
    WIDE_BLOCK_SHARE,
    KeywordListError,
    OperatorKeywords,
    build_keyword_lists,
    keyword_diff,
)
from app.infrastructure.db.admin_auth import add_audit_event
from app.infrastructure.db.models import OperatorKeywordVersionModel
from app.infrastructure.db.operator_keywords import (
    KeywordImpact,
    add_keyword_version,
    keyword_impact,
    keywords_from_row,
    load_active_keyword_row,
    recent_slot_candidates,
)

IMPACT_DAYS = 7


class KeywordListRejectedError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("keyword_list_invalid", message, 422)


class KeywordBlockTooWideError(AppError):
    def __init__(self, impact: KeywordImpact) -> None:
        super().__init__(
            "keyword_block_too_wide",
            f"屏蔽词会拦下最近 {IMPACT_DAYS} 天 {impact.candidate_count} 条候选里的 "
            f"{len(impact.blocked)} 条（{impact.blocked_share:.0%}），请确认后再保存",
            422,
        )


def _lists(
    focus: list[str], block: list[str], copy_banned: list[str]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    try:
        return build_keyword_lists(focus=focus, block=block, copy_banned=copy_banned)
    except KeywordListError as error:
        raise KeywordListRejectedError(str(error)) from error


async def preview_keyword_impact(
    session: AsyncSession, *, focus: list[str], block: list[str], now: datetime
) -> KeywordImpact:
    focus_terms, block_terms, _ = _lists(focus, block, [])
    candidates = await recent_slot_candidates(session, now=now, days=IMPACT_DAYS)
    return keyword_impact(candidates, focus=focus_terms, block=block_terms)


async def save_keywords(
    session: AsyncSession,
    *,
    focus: list[str],
    block: list[str],
    copy_banned: list[str],
    note: str | None,
    confirm_wide_block: bool,
    principal: AdminPrincipal,
    now: datetime,
) -> OperatorKeywordVersionModel:
    focus_terms, block_terms, banned_terms = _lists(focus, block, copy_banned)
    active = await load_active_keyword_row(session)
    before = None if active is None else keywords_from_row(active)
    if before is not None and (before.focus, before.block, before.copy_banned) == (
        focus_terms,
        block_terms,
        banned_terms,
    ):
        raise ConflictError("和当前版本一样，没有改动")
    if block_terms and not confirm_wide_block:
        candidates = await recent_slot_candidates(session, now=now, days=IMPACT_DAYS)
        impact = keyword_impact(candidates, focus=focus_terms, block=block_terms)
        if impact.blocked_share > WIDE_BLOCK_SHARE:
            raise KeywordBlockTooWideError(impact)
    cleaned_note = " ".join((note or "").split())[:200] or None
    row = await add_keyword_version(
        session,
        focus=focus_terms,
        block=block_terms,
        copy_banned=banned_terms,
        note=cleaned_note,
        created_by=principal.username,
        now=now,
    )
    after = OperatorKeywords(
        version=row.version, focus=focus_terms, block=block_terms, copy_banned=banned_terms
    )
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="keywords.saved",
        target_type="keywords",
        target_id=after.label,
        detail={
            "version": row.version,
            "changes": keyword_diff(before, after),
            "note": cleaned_note,
            "confirmed_wide_block": confirm_wide_block,
        },
    )
    await session.commit()
    return row


__all__ = [
    "IMPACT_DAYS",
    "KeywordBlockTooWideError",
    "KeywordListRejectedError",
    "preview_keyword_impact",
    "save_keywords",
]
