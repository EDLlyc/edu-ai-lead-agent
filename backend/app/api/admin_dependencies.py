"""Shared guards of every 运营后台 router (`/api/v1/admin/...`).

`admin_guard` (router dependency): no caching, and every write needs `X-Admin-Request: 1`, which a
cross-site form cannot send. `require_admin` / `require_owner` resolve the session cookie.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.application.services.admin_auth import AdminPrincipal, resolve_admin_session
from app.core.errors import AppError
from app.domain.admin_auth import (
    SESSION_COOKIE_NAME,
    WRITE_GUARD_HEADER,
    AdminRole,
    role_allows,
)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def admin_guard(request: Request, response: Response) -> None:
    # Operator data and session state must not be cached by the browser or a proxy.
    response.headers["Cache-Control"] = "no-store"
    if request.method not in _SAFE_METHODS and request.headers.get(WRITE_GUARD_HEADER) != "1":
        raise AppError(
            "admin_write_guard_missing", f"admin writes need the {WRITE_GUARD_HEADER} header", 403
        )


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

__all__ = ["admin_guard", "require_admin", "require_owner", "require_role"]
