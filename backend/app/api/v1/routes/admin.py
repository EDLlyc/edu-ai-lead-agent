"""运营后台 API: login, logout, the current operator and the audit log.

Every route here except login needs the session cookie. Every write (POST/PUT/PATCH/DELETE)
also needs `X-Admin-Request: 1`. Together with the `SameSite=Strict` cookie this stops a request
started by another site. Items 1-8 (news sources, keywords, WeChat, models) add their routes to
this prefix and use `require_admin` / `require_owner`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_dependencies import admin_guard, require_admin, require_owner
from app.api.dependencies import get_session
from app.application.services.admin_accounts import change_own_password
from app.application.services.admin_auth import AdminPrincipal, login_admin, logout_admin
from app.core.config import Settings
from app.domain.admin_auth import SESSION_COOKIE_NAME, SESSION_LIFETIME
from app.infrastructure.db.admin_auth import list_audit_events
from app.schemas.admin import (
    AdminAuditEventListResponse,
    AdminAuditEventResponse,
    AdminLoginRequest,
    AdminMeResponse,
    AdminPasswordChangedResponse,
    AdminPasswordChangeRequest,
)

# 操作记录 filter: one kind of action at a time.
AUDIT_KINDS = {
    "auth": "auth.",
    "user": "user.",
    "source": "source.",
    "keywords": "keywords.",
    "wechat": "wechat",
    "model": "model_key.",
}

COOKIE_PATH = "/api/v1/admin"

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_guard)])


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _cookie_secure(settings: Settings) -> bool:
    configured = settings.admin_session_cookie_secure
    return settings.app_env != "development" if configured is None else configured


def _me(principal: AdminPrincipal) -> AdminMeResponse:
    return AdminMeResponse(
        username=principal.username,
        display_name=principal.display_name,
        role=principal.role,
        expires_at=principal.expires_at,
    )


@router.post("/auth/login", response_model=AdminMeResponse)
async def post_admin_login(
    body: AdminLoginRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminMeResponse:
    login = await login_admin(
        session, username=body.username, password=body.password, now=datetime.now(UTC)
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        login.token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        path=COOKIE_PATH,
        httponly=True,
        samesite="strict",
        secure=_cookie_secure(_settings(request)),
    )
    return _me(login.principal)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def post_admin_logout(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> Response:
    if token:
        await logout_admin(session, token=token, now=datetime.now(UTC))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=True,
        samesite="strict",
        secure=_cookie_secure(_settings(request)),
    )
    return response


@router.get("/auth/me", response_model=AdminMeResponse)
async def get_admin_me(
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
) -> AdminMeResponse:
    return _me(principal)


@router.get("/audit-events", response_model=AdminAuditEventListResponse)
async def get_admin_audit_events(
    _principal: Annotated[AdminPrincipal, Depends(require_owner)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: datetime | None = None,
    kind: Literal["auth", "user", "source", "keywords", "wechat", "model"] | None = None,
) -> AdminAuditEventListResponse:
    rows = await list_audit_events(
        session,
        limit=limit,
        before=before,
        action_prefix=None if kind is None else AUDIT_KINDS[kind],
    )
    items = [
        AdminAuditEventResponse(
            id=row.id,
            occurred_at=row.occurred_at,
            username=row.username,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            detail=row.detail,
        )
        for row in rows
    ]
    return AdminAuditEventListResponse(items=items, count=len(items))


@router.post("/auth/password", response_model=AdminPasswordChangedResponse)
async def post_admin_password(
    body: AdminPasswordChangeRequest,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminPasswordChangedResponse:
    ended = await change_own_password(
        session,
        principal=principal,
        current_password=body.current_password,
        new_password=body.new_password,
        now=datetime.now(UTC),
    )
    return AdminPasswordChangedResponse(other_sessions_ended=ended)
