"""Operator accounts, login sessions and the audit log of the 运营后台.

Callers own the transaction: these functions add and flush, they never commit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admin_auth import SESSION_LIFETIME, hash_session_token
from app.infrastructure.db.models import (
    AdminAuditEventModel,
    AdminSessionModel,
    AdminUserModel,
)

# Keys that must never reach the audit log, at any depth (matched as substrings).
_SECRET_KEY_PARTS = ("password", "secret", "token", "api_key", "apikey", "cookie")


def _check_no_secrets(value: Any, path: str = "detail") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in _SECRET_KEY_PARTS):
                raise ValueError(f"{path}.{key} looks like a secret; keep it out of the audit log")
            _check_no_secrets(item, f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _check_no_secrets(item, f"{path}[{index}]")


async def add_audit_event(
    session: AsyncSession,
    *,
    now: datetime,
    user_id: UUID | None,
    username: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: Mapping[str, Any] | None = None,
) -> AdminAuditEventModel:
    payload = dict(detail or {})
    _check_no_secrets(payload)
    row = AdminAuditEventModel(
        id=uuid4(),
        occurred_at=now,
        user_id=user_id,
        username=username[:40],
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=payload,
    )
    session.add(row)
    await session.flush()
    return row


async def list_audit_events(
    session: AsyncSession, *, limit: int, before: datetime | None = None
) -> Sequence[AdminAuditEventModel]:
    statement = select(AdminAuditEventModel)
    if before is not None:
        statement = statement.where(AdminAuditEventModel.occurred_at < before)
    statement = statement.order_by(
        AdminAuditEventModel.occurred_at.desc(), AdminAuditEventModel.id.desc()
    ).limit(limit)
    return (await session.scalars(statement)).all()


async def load_user_by_username(
    session: AsyncSession, username: str, *, lock: bool = False
) -> AdminUserModel | None:
    statement = select(AdminUserModel).where(AdminUserModel.username == username)
    if lock:
        statement = statement.with_for_update()
    user: AdminUserModel | None = await session.scalar(statement)
    return user


async def list_users(session: AsyncSession) -> Sequence[AdminUserModel]:
    return (await session.scalars(select(AdminUserModel).order_by(AdminUserModel.username))).all()


async def add_user(
    session: AsyncSession,
    *,
    username: str,
    display_name: str,
    role: str,
    password_hash: str,
    now: datetime,
) -> AdminUserModel:
    row = AdminUserModel(
        id=uuid4(),
        username=username,
        display_name=display_name,
        role=role,
        password_hash=password_hash,
        active=True,
        failed_login_count=0,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def add_session(
    session: AsyncSession, *, user_id: UUID, token: str, now: datetime
) -> AdminSessionModel:
    row = AdminSessionModel(
        id=uuid4(),
        token_hash=hash_session_token(token),
        user_id=user_id,
        created_at=now,
        expires_at=now + SESSION_LIFETIME,
        last_seen_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def load_live_session(
    session: AsyncSession, token: str, *, now: datetime
) -> tuple[AdminSessionModel, AdminUserModel] | None:
    """The session for a cookie token if it is unexpired, unrevoked and its user is active."""

    row = (
        await session.execute(
            select(AdminSessionModel, AdminUserModel)
            .join(AdminUserModel, AdminUserModel.id == AdminSessionModel.user_id)
            .where(
                AdminSessionModel.token_hash == hash_session_token(token),
                AdminSessionModel.revoked_at.is_(None),
                AdminSessionModel.expires_at > now,
                AdminUserModel.active.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return row[0], row[1]


async def revoke_user_sessions(session: AsyncSession, *, user_id: UUID, now: datetime) -> int:
    result = await session.execute(
        update(AdminSessionModel)
        .where(
            AdminSessionModel.user_id == user_id,
            AdminSessionModel.revoked_at.is_(None),
            AdminSessionModel.expires_at > now,
        )
        .values(revoked_at=now)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def count_live_sessions(session: AsyncSession, *, user_id: UUID, now: datetime) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(AdminSessionModel)
            .where(
                AdminSessionModel.user_id == user_id,
                AdminSessionModel.revoked_at.is_(None),
                AdminSessionModel.expires_at > now,
            )
        )
        or 0
    )


__all__ = [
    "add_audit_event",
    "add_session",
    "add_user",
    "count_live_sessions",
    "list_audit_events",
    "list_users",
    "load_live_session",
    "load_user_by_username",
    "revoke_user_sessions",
]
