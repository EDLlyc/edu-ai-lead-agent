# ruff: noqa: RUF001
"""Log operators in and out of the 运营后台 and resolve a session cookie to an operator.

A failed login is recorded (counter, lockout, audit row) and committed before the error is
raised. Unknown user, wrong password, locked and disabled accounts all get the same answer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.admin_auth import (
    AdminInputError,
    AdminRole,
    burn_password_check,
    hash_password,
    is_locked,
    new_session_token,
    normalize_username,
    register_failed_login,
    verify_password,
)
from app.infrastructure.db.admin_auth import (
    add_audit_event,
    add_session,
    load_live_session,
    load_user_by_username,
    revoke_user_sessions,
)
from app.infrastructure.db.models import AdminUserModel

# Do not write `last_seen_at` on every request.
_LAST_SEEN_RESOLUTION = timedelta(minutes=1)


class AdminLoginRejectedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "admin_login_rejected",
            "用户名或密码不对。连续输错 5 次，账号会锁定 15 分钟。",
            401,
        )


@dataclass(frozen=True, slots=True)
class AdminPrincipal:
    user_id: UUID
    username: str
    display_name: str
    role: AdminRole
    session_id: UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AdminLogin:
    token: str
    principal: AdminPrincipal


def _principal(user: AdminUserModel, session_id: UUID, expires_at: datetime) -> AdminPrincipal:
    role: AdminRole = "owner" if user.role == "owner" else "editor"
    return AdminPrincipal(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=role,
        session_id=session_id,
        expires_at=expires_at,
    )


async def login_admin(
    session: AsyncSession, *, username: str, password: str, now: datetime
) -> AdminLogin:
    try:
        name = normalize_username(username)
    except AdminInputError:
        name = None
    user = None if name is None else await load_user_by_username(session, name, lock=True)

    reason: str | None = None
    if user is None:
        await asyncio.to_thread(burn_password_check, password)
        reason = "unknown_user"
    elif not user.active:
        await asyncio.to_thread(burn_password_check, password)
        reason = "disabled"
    elif is_locked(user.locked_until, now):
        await asyncio.to_thread(burn_password_check, password)
        reason = "locked"
    elif not await asyncio.to_thread(verify_password, password, user.password_hash):
        failed = register_failed_login(user.failed_login_count, now)
        user.failed_login_count = failed.failed_login_count
        if failed.locked_until is not None:
            user.locked_until = failed.locked_until
            reason = "wrong_password_locked"
        else:
            reason = "wrong_password"
        user.updated_at = now

    if reason is not None:
        await add_audit_event(
            session,
            now=now,
            user_id=None if user is None else user.id,
            username=(name or username.strip().lower() or "?")[:40],
            action="auth.login_failed",
            detail={"reason": reason},
        )
        await session.commit()
        raise AdminLoginRejectedError()

    assert user is not None
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    user.updated_at = now
    token = new_session_token()
    row = await add_session(session, user_id=user.id, token=token, now=now)
    await add_audit_event(
        session, now=now, user_id=user.id, username=user.username, action="auth.login"
    )
    principal = _principal(user, row.id, row.expires_at)
    await session.commit()
    return AdminLogin(token=token, principal=principal)


async def resolve_admin_session(
    session: AsyncSession, *, token: str, now: datetime
) -> AdminPrincipal | None:
    found = await load_live_session(session, token, now=now)
    if found is None:
        return None
    row, user = found
    if now - row.last_seen_at >= _LAST_SEEN_RESOLUTION:
        row.last_seen_at = now
        await session.commit()
    return _principal(user, row.id, row.expires_at)


async def logout_admin(session: AsyncSession, *, token: str, now: datetime) -> bool:
    found = await load_live_session(session, token, now=now)
    if found is None:
        return False
    row, user = found
    row.revoked_at = now
    await add_audit_event(
        session, now=now, user_id=user.id, username=user.username, action="auth.logout"
    )
    await session.commit()
    return True


async def set_admin_password(
    session: AsyncSession,
    *,
    user: AdminUserModel,
    password: str,
    now: datetime,
    actor_id: UUID | None,
    actor: str,
) -> int:
    """Replace the password, clear the lockout and end every open session of the user."""

    user.password_hash = await asyncio.to_thread(hash_password, password)
    user.failed_login_count = 0
    user.locked_until = None
    user.updated_at = now
    revoked = await revoke_user_sessions(session, user_id=user.id, now=now)
    await add_audit_event(
        session,
        now=now,
        user_id=actor_id,
        username=actor,
        action="user.password_set",
        target_type="admin_user",
        target_id=user.username,
        detail={"sessions_ended": revoked},
    )
    return revoked


__all__ = [
    "AdminLogin",
    "AdminLoginRejectedError",
    "AdminPrincipal",
    "login_admin",
    "logout_admin",
    "resolve_admin_session",
    "set_admin_password",
]
