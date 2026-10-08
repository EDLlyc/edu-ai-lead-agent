"""运营后台 · 关键词: the operator's 关注词 / 屏蔽词 / 文案禁用词, their history and impact."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_dependencies import admin_guard, require_admin
from app.api.dependencies import get_session
from app.application.services.admin_auth import AdminPrincipal
from app.application.services.keyword_admin import (
    IMPACT_DAYS,
    preview_keyword_impact,
    save_keywords,
)
from app.core.errors import NotFoundError
from app.domain.operator_keywords import WIDE_BLOCK_SHARE
from app.infrastructure.db.models import OperatorKeywordVersionModel
from app.infrastructure.db.operator_keywords import list_keyword_rows, load_keyword_row
from app.schemas.admin_keywords import (
    AdminKeywordBlockedItem,
    AdminKeywordFocusedItem,
    AdminKeywordHistoryItem,
    AdminKeywordImpactRequest,
    AdminKeywordImpactResponse,
    AdminKeywordSaveRequest,
    AdminKeywordsResponse,
    AdminKeywordTermCount,
    AdminKeywordVersionResponse,
)

router = APIRouter(prefix="/admin/keywords", tags=["admin"], dependencies=[Depends(admin_guard)])

_IMPACT_LIST_LIMIT = 30


def _version(row: OperatorKeywordVersionModel) -> AdminKeywordVersionResponse:
    return AdminKeywordVersionResponse(
        version=row.version,
        focus=list(row.focus_terms),
        block=list(row.block_terms),
        copy_banned=list(row.copy_banned_terms),
        note=row.note,
        created_by=row.created_by,
        created_at=row.created_at,
    )


async def _overview(session: AsyncSession) -> AdminKeywordsResponse:
    rows = await list_keyword_rows(session)
    return AdminKeywordsResponse(
        current=_version(rows[0]) if rows else None,
        history=[
            AdminKeywordHistoryItem(
                version=row.version,
                note=row.note,
                created_by=row.created_by,
                created_at=row.created_at,
                focus_count=len(row.focus_terms),
                block_count=len(row.block_terms),
                copy_banned_count=len(row.copy_banned_terms),
            )
            for row in rows
        ],
    )


@router.get("", response_model=AdminKeywordsResponse)
async def get_admin_keywords(
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminKeywordsResponse:
    return await _overview(session)


@router.get("/versions/{version}", response_model=AdminKeywordVersionResponse)
async def get_admin_keyword_version(
    version: int,
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminKeywordVersionResponse:
    row = await load_keyword_row(session, version=version)
    if row is None:
        raise NotFoundError("keyword version")
    return _version(row)


@router.post("/impact", response_model=AdminKeywordImpactResponse)
async def post_admin_keyword_impact(
    body: AdminKeywordImpactRequest,
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminKeywordImpactResponse:
    impact = await preview_keyword_impact(
        session, focus=body.focus, block=body.block, now=datetime.now(UTC)
    )
    return AdminKeywordImpactResponse(
        days=IMPACT_DAYS,
        candidate_count=impact.candidate_count,
        blocked_count=len(impact.blocked),
        blocked_selected_count=sum(1 for _title, _terms, selected in impact.blocked if selected),
        blocked_share=round(impact.blocked_share, 4),
        wide=impact.blocked_share > WIDE_BLOCK_SHARE,
        blocked=[
            AdminKeywordBlockedItem(title=title, terms=list(terms), selected=selected)
            for title, terms, selected in impact.blocked[:_IMPACT_LIST_LIMIT]
        ],
        per_block_term=[
            AdminKeywordTermCount(term=term, count=count)
            for term, count in impact.per_block_term.items()
        ],
        focused_count=len(impact.focused),
        focused=[
            AdminKeywordFocusedItem(title=title, terms=list(terms))
            for title, terms in impact.focused[:_IMPACT_LIST_LIMIT]
        ],
    )


@router.post("", response_model=AdminKeywordsResponse)
async def post_admin_keywords(
    body: AdminKeywordSaveRequest,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminKeywordsResponse:
    await save_keywords(
        session,
        focus=body.focus,
        block=body.block,
        copy_banned=body.copy_banned,
        note=body.note,
        confirm_wide_block=body.confirm_wide_block,
        principal=principal,
        now=datetime.now(UTC),
    )
    return await _overview(session)
