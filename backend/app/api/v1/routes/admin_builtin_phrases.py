"""运营后台 · 系统内置词: maintain the editorial phrase lists the copy gate refuses."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_dependencies import admin_guard, require_admin
from app.api.dependencies import get_session
from app.application.services.admin_auth import AdminPrincipal
from app.application.services.keyword_admin import KeywordListRejectedError
from app.core.errors import ConflictError
from app.domain.builtin_phrases import (
    DEFAULT_ANXIETY,
    DEFAULT_MARKETING,
    LOCKED_PHRASE_LISTS,
    parse_builtin_phrases,
)
from app.domain.operator_keywords import KeywordListError
from app.infrastructure.db.admin_auth import add_audit_event
from app.infrastructure.db.builtin_phrases import (
    add_builtin_phrase_version,
    list_builtin_phrase_rows,
    phrases_from_row,
)
from app.schemas.admin_builtin_phrases import (
    BuiltinPhraseLockedList,
    BuiltinPhrasesResponse,
    BuiltinPhrasesSaveRequest,
)

router = APIRouter(
    prefix="/admin/builtin-phrases", tags=["admin"], dependencies=[Depends(admin_guard)]
)


def _locked() -> list[BuiltinPhraseLockedList]:
    return [
        BuiltinPhraseLockedList(name=name, terms=list(terms)) for name, terms in LOCKED_PHRASE_LISTS
    ]


def _response_from_defaults() -> BuiltinPhrasesResponse:
    return BuiltinPhrasesResponse(
        version=None,
        marketing=list(DEFAULT_MARKETING),
        anxiety=list(DEFAULT_ANXIETY),
        defaults_marketing=list(DEFAULT_MARKETING),
        defaults_anxiety=list(DEFAULT_ANXIETY),
        locked=_locked(),
    )


@router.get("", response_model=BuiltinPhrasesResponse)
async def get_admin_builtin_phrases(
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BuiltinPhrasesResponse:
    rows = await list_builtin_phrase_rows(session)
    if not rows:
        return _response_from_defaults()
    current = phrases_from_row(rows[0])
    return BuiltinPhrasesResponse(
        version=current.version,
        marketing=list(current.marketing),
        anxiety=list(current.anxiety),
        defaults_marketing=list(DEFAULT_MARKETING),
        defaults_anxiety=list(DEFAULT_ANXIETY),
        locked=_locked(),
        note=rows[0].note,
        created_by=rows[0].created_by,
        created_at=rows[0].created_at,
    )


@router.post("", response_model=BuiltinPhrasesResponse)
async def post_admin_builtin_phrases(
    body: BuiltinPhrasesSaveRequest,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BuiltinPhrasesResponse:
    try:
        marketing, anxiety = parse_builtin_phrases(marketing=body.marketing, anxiety=body.anxiety)
    except KeywordListError as error:
        raise KeywordListRejectedError(str(error)) from error
    rows = await list_builtin_phrase_rows(session)
    current = None if not rows else phrases_from_row(rows[0])
    before = (
        (DEFAULT_MARKETING, DEFAULT_ANXIETY)
        if current is None
        else (current.marketing, current.anxiety)
    )
    if before == (marketing, anxiety):
        raise ConflictError("和当前生效的词一样, 没有改动")
    now = datetime.now(UTC)
    note = " ".join((body.note or "").split())[:200] or None
    row = await add_builtin_phrase_version(
        session,
        marketing=marketing,
        anxiety=anxiety,
        note=note,
        created_by=principal.username,
        now=now,
    )
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="builtin_phrases.saved",
        target_type="builtin_phrases",
        target_id=f"builtin-phrases-{row.version}",
        detail={
            "version": row.version,
            "marketing_added": sorted(set(marketing) - set(before[0])),
            "marketing_removed": sorted(set(before[0]) - set(marketing)),
            "anxiety_added": sorted(set(anxiety) - set(before[1])),
            "anxiety_removed": sorted(set(before[1]) - set(anxiety)),
            "note": note,
        },
    )
    await session.commit()
    saved = phrases_from_row(row)
    return BuiltinPhrasesResponse(
        version=saved.version,
        marketing=list(saved.marketing),
        anxiety=list(saved.anxiety),
        defaults_marketing=list(DEFAULT_MARKETING),
        defaults_anxiety=list(DEFAULT_ANXIETY),
        locked=_locked(),
        note=row.note,
        created_by=row.created_by,
        created_at=row.created_at,
    )
