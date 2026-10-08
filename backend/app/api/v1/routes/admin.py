"""运营后台 API: login, logout, the current operator and the audit log.

Every route here except login needs the session cookie. Every write (POST/PUT/PATCH/DELETE)
also needs `X-Admin-Request: 1`. Together with the `SameSite=Strict` cookie this stops a request
started by another site. Items 1-8 (news sources, keywords, WeChat, models) add their routes to
this prefix and use `require_admin` / `require_owner`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.application.services.admin_auth import (
    AdminPrincipal,
    login_admin,
    logout_admin,
    resolve_admin_session,
)
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.admin_auth import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    WRITE_GUARD_HEADER,
    AdminRole,
    role_allows,
)
from app.infrastructure.db.admin_auth import list_audit_events
from app.schemas.admin import (
    AdminAuditEventListResponse,
    AdminAuditEventResponse,
    AdminLoginRequest,
    AdminMeResponse,
)

COOKIE_PATH = "/api/v1/admin"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def _guard(request: Request, response: Response) -> None:
    # Operator data and session state must not be cached by the browser or a proxy.
    response.headers["Cache-Control"] = "no-store"
    if request.method not in _SAFE_METHODS and request.headers.get(WRITE_GUARD_HEADER) != "1":
        raise AppError(
            "admin_write_guard_missing", f"admin writes need the {WRITE_GUARD_HEADER} header", 403
        )


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(_guard)])


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _cookie_secure(settings: Settings) -> bool:
    configured = settings.admin_session_cookie_secure
    return settings.app_env != "development" if configured is None else configured


async def require_admin(
    session: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> AdminPrincipal:
    principal = None
    if token:
        principal = await resolve_admin_session(session, token=token, now=datetime.now(UTC))
    if principal is None:
        raise AppError("admin_login_required", "请先登录运营后台", 401)
    return principal


def require_role(role: AdminRole) -> Callable[[AdminPrincipal], Awaitable[AdminPrincipal]]:
    async def dependency(
        principal: Annotated[AdminPrincipal, Depends(require_admin)],
    ) -> AdminPrincipal:
        if not role_allows(principal.role, role):
            raise AppError("admin_forbidden", "当前账号没有这个权限", 403)
        return principal

    return dependency


require_owner = require_role("owner")


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
) -> AdminAuditEventListResponse:
    rows = await list_audit_events(session, limit=limit, before=before)
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
