# ruff: noqa: RUF001
"""Operator accounts managed in the 运营后台, and each operator's own password.

An owner creates accounts, resets passwords, disables, enables and edits them. A created or reset
password is generated here and returned exactly once; only its scrypt hash is stored. The guards
keep the console administrable:
- an owner cannot disable or demote themselves;
- the last active owner can never go.
Every change is audited without the password.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.admin_auth import AdminPrincipal, set_admin_password
from app.core.errors import AppError, ConflictError, NotFoundError
from app.domain.admin_auth import (
    AdminInputError,
    AdminRole,
    check_display_name,
    check_new_password,
    generate_initial_password,
    hash_password,
    is_locked,
    normalize_username,
    register_failed_login,
    verify_password,
)
from app.infrastructure.db.admin_auth import (
    add_audit_event,
    add_user,
    count_active_owners,
    count_live_sessions,
    list_users,
    load_user_by_username,
    revoke_user_sessions,
)
from app.infrastructure.db.models import AdminUserModel


class AccountInputError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("admin_account_invalid", message, 422)


class AccountGuardError(ConflictError):
    """A change that would lock everyone out or remove the caller's own access."""


class CurrentPasswordRejectedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "admin_current_password_wrong",
            "当前密码不对。连续输错 5 次，账号会锁定 15 分钟。",
            422,
        )


@dataclass(frozen=True, slots=True)
class AccountView:
    username: str
    display_name: str
    role: AdminRole
    active: bool
    locked: bool
    last_login_at: datetime | None
    created_at: datetime
    live_sessions: int


def _role(value: str) -> AdminRole:
    return "owner" if value == "owner" else "editor"


async def _view(session: AsyncSession, user: AdminUserModel, now: datetime) -> AccountView:
    return AccountView(
        username=user.username,
        display_name=user.display_name,
        role=_role(user.role),
        active=user.active,
        locked=is_locked(user.locked_until, now),
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        live_sessions=await count_live_sessions(session, user_id=user.id, now=now),
    )


async def list_accounts(session: AsyncSession, *, now: datetime) -> list[AccountView]:
    return [await _view(session, user, now) for user in await list_users(session)]


async def _require(session: AsyncSession, username: str) -> AdminUserModel:
    try:
        name = normalize_username(username)
    except AdminInputError as error:
        raise NotFoundError("admin account") from error
    user = await load_user_by_username(session, name, lock=True)
    if user is None:
        raise NotFoundError("admin account")
    return user


async def create_account(
    session: AsyncSession,
    *,
    principal: AdminPrincipal,
    username: str,
    display_name: str,
    role: AdminRole,
    now: datetime,
    password: str | None = None,
) -> tuple[AccountView, str | None]:
    try:
        name = normalize_username(username)
        shown = check_display_name(display_name)
    except AdminInputError as error:
        raise AccountInputError(_input_message(error)) from error
    if await load_user_by_username(session, name) is not None:
        raise ConflictError("这个用户名已经有了（停用的账号也占用用户名），请换一个")
    generated: str | None = None
    if password is None:
        generated = password = generate_initial_password()
    else:
        try:
            check_new_password(password, username=name)
        except AdminInputError as error:
            raise AccountInputError(_input_message(error)) from error
    user = await add_user(
        session,
        username=name,
        display_name=shown,
        role=role,
        password_hash=await asyncio.to_thread(hash_password, password),
        now=now,
    )
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="user.created",
        target_type="admin_user",
        target_id=user.username,
        detail={"role": user.role, "display_name": user.display_name},
    )
    view = await _view(session, user, now)
    await session.commit()
    return view, generated


async def reset_account_password(
    session: AsyncSession,
    *,
    principal: AdminPrincipal,
    username: str,
    now: datetime,
    password: str | None = None,
) -> str | None:
    """Set a new password: the owner's own choice, or a generated one that is returned once."""

    user = await _require(session, username)
    generated: str | None = None
    if password is None:
        generated = password = generate_initial_password()
    else:
        try:
            check_new_password(password, username=user.username)
        except AdminInputError as error:
            await session.rollback()
            raise AccountInputError(_input_message(error)) from error
    await set_admin_password(
        session,
        user=user,
        password=password,
        now=now,
        actor_id=principal.user_id,
        actor=principal.username,
    )
    await session.commit()
    return generated


async def set_account_active(
    session: AsyncSession,
    *,
    principal: AdminPrincipal,
    username: str,
    active: bool,
    now: datetime,
) -> AccountView:
    user = await _require(session, username)
    if not active:
        if user.id == principal.user_id:
            await session.rollback()
            raise AccountGuardError("不能停用自己的账号")
        if user.role == "owner" and user.active and await count_active_owners(session) <= 1:
            await session.rollback()
            raise AccountGuardError("这是最后一个管理员账号，不能停用")
    if user.active == active:
        view = await _view(session, user, now)
        await session.rollback()
        return view
    user.active = active
    user.updated_at = now
    ended = 0
    if active:
        user.failed_login_count = 0
        user.locked_until = None
    else:
        ended = await revoke_user_sessions(session, user_id=user.id, now=now)
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="user.enabled" if active else "user.disabled",
        target_type="admin_user",
        target_id=user.username,
        detail={} if active else {"sessions_ended": ended},
    )
    view = await _view(session, user, now)
    await session.commit()
    return view


async def update_account(
    session: AsyncSession,
    *,
    principal: AdminPrincipal,
    username: str,
    display_name: str | None,
    role: AdminRole | None,
    now: datetime,
) -> AccountView:
    user = await _require(session, username)
    changes: dict[str, object] = {}
    if display_name is not None:
        try:
            shown = check_display_name(display_name)
        except AdminInputError as error:
            await session.rollback()
            raise AccountInputError(_input_message(error)) from error
        if shown != user.display_name:
            changes["display_name"] = {"from": user.display_name, "to": shown}
            user.display_name = shown
    if role is not None and role != user.role:
        if user.role == "owner":
            if user.id == principal.user_id:
                await session.rollback()
                raise AccountGuardError("不能把自己改成编辑")
            if user.active and await count_active_owners(session) <= 1:
                await session.rollback()
                raise AccountGuardError("这是最后一个管理员账号，不能改成编辑")
        changes["role"] = {"from": user.role, "to": role}
        user.role = role
    if not changes:
        view = await _view(session, user, now)
        await session.rollback()
        return view
    user.updated_at = now
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="user.updated",
        target_type="admin_user",
        target_id=user.username,
        detail={"changes": changes},
    )
    view = await _view(session, user, now)
    await session.commit()
    return view


async def change_own_password(
    session: AsyncSession,
    *,
    principal: AdminPrincipal,
    current_password: str,
    new_password: str,
    now: datetime,
) -> int:
    """Replace the caller's password; ends their other sessions and keeps this one."""

    user = await _require(session, principal.username)
    if not await asyncio.to_thread(verify_password, current_password, user.password_hash):
        failed = register_failed_login(user.failed_login_count, now)
        user.failed_login_count = failed.failed_login_count
        if failed.locked_until is not None:
            user.locked_until = failed.locked_until
            # A lock also ends this session: the account is locked for everyone.
            await revoke_user_sessions(session, user_id=user.id, now=now)
        user.updated_at = now
        await add_audit_event(
            session,
            now=now,
            user_id=user.id,
            username=user.username,
            action="user.password_change_failed",
            target_type="admin_user",
            target_id=user.username,
            detail={"locked": failed.locked_until is not None},
        )
        await session.commit()
        raise CurrentPasswordRejectedError()
    try:
        check_new_password(new_password, username=user.username)
    except AdminInputError as error:
        await session.rollback()
        raise AccountInputError(_input_message(error)) from error
    if new_password == current_password:
        await session.rollback()
        raise AccountInputError("新密码不能和当前密码一样")
    user.password_hash = await asyncio.to_thread(hash_password, new_password)
    user.failed_login_count = 0
    user.locked_until = None
    user.updated_at = now
    ended = await revoke_user_sessions(
        session, user_id=user.id, now=now, keep_session_id=principal.session_id
    )
    await add_audit_event(
        session,
        now=now,
        user_id=user.id,
        username=user.username,
        action="user.password_changed",
        target_type="admin_user",
        target_id=user.username,
        detail={"sessions_ended": ended},
    )
    await session.commit()
    return ended


_INPUT_MESSAGES = {
    # Order matters: the first key found in the message wins
    # ("same as the username" also contains "username").
    "most common passwords": "这个密码太常见了（比如 12345678、password），换一个",
    "same as the username": "密码不能和用户名一样",
    "username": "用户名要 2–40 个字符：第一个是小写字母，后面可以是小写字母、数字、_ . -",
    "display name": "显示名要 1–40 个字",
    "password must be": "新密码要 8–128 个字符",
    "spaces": "密码开头和结尾不能是空格",
}


def _input_message(error: AdminInputError) -> str:
    text = str(error)
    for key, message in _INPUT_MESSAGES.items():
        if key in text:
            return message
    return text


__all__ = [
    "AccountGuardError",
    "AccountInputError",
    "AccountView",
    "CurrentPasswordRejectedError",
    "change_own_password",
    "create_account",
    "list_accounts",
    "reset_account_password",
    "set_account_active",
    "update_account",
]
