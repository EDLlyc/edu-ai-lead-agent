"""Manage 运营后台 operator accounts from the server.

    python -m app.admin_users_main list
    python -m app.admin_users_main create <username> --name 李老师 --role owner|editor
    python -m app.admin_users_main set-password <username>
    python -m app.admin_users_main disable <username>
    python -m app.admin_users_main enable <username>

A password is typed twice at a hidden prompt, or read from one stdin line with
`--password-stdin`. It is never taken from argv or the environment and never printed. Setting a
password or disabling an account ends that account's open sessions.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import TextIO

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.admin_auth import set_admin_password
from app.domain.admin_auth import (
    ADMIN_ROLES,
    AdminInputError,
    check_display_name,
    check_new_password,
    hash_password,
    normalize_username,
)
from app.infrastructure.db.admin_auth import (
    add_audit_event,
    add_user,
    count_live_sessions,
    list_users,
    load_user_by_username,
    revoke_user_sessions,
)
from app.infrastructure.db.models import AdminUserModel

CLI_ACTOR = "cli"


class CommandError(Exception):
    """A refusal the operator can fix; printed without a traceback."""


def read_password(
    *,
    from_stdin: bool,
    stdin: TextIO,
    prompt: Callable[[str], str] = getpass.getpass,
) -> str:
    if from_stdin:
        password = stdin.readline().rstrip("\r\n")
    else:
        password = prompt("新密码: ")
        if prompt("再输一次: ") != password:
            raise CommandError("两次输入的密码不一样")
    try:
        check_new_password(password)
    except AdminInputError as error:
        raise CommandError(str(error)) from error
    return password


async def _require_user(session: AsyncSession, username: str) -> AdminUserModel:
    user = await load_user_by_username(session, normalize_username(username), lock=True)
    if user is None:
        raise CommandError(f"没有这个账号: {username}")
    return user


async def run_command(
    session: AsyncSession,
    args: argparse.Namespace,
    *,
    now: datetime,
    stdin: TextIO,
    prompt: Callable[[str], str] = getpass.getpass,
) -> list[str]:
    """Run one command in its own transaction and return the lines to print."""

    try:
        if args.command == "list":
            lines = []
            for user in await list_users(session):
                live = await count_live_sessions(session, user_id=user.id, now=now)
                state = "启用" if user.active else "停用"
                lines.append(
                    f"{user.username}\t{user.display_name}\t{user.role}\t{state}\t在线会话 {live}"
                )
            return lines or ["还没有账号"]

        if args.command == "create":
            username = normalize_username(args.username)
            if await load_user_by_username(session, username) is not None:
                raise CommandError(f"账号已存在: {username}")
            display_name = check_display_name(args.name)
            password = read_password(from_stdin=args.password_stdin, stdin=stdin, prompt=prompt)
            user = await add_user(
                session,
                username=username,
                display_name=display_name,
                role=args.role,
                password_hash=await asyncio.to_thread(hash_password, password),
                now=now,
            )
            await add_audit_event(
                session,
                now=now,
                user_id=None,
                username=CLI_ACTOR,
                action="user.created",
                target_type="admin_user",
                target_id=user.username,
                detail={"role": user.role, "display_name": user.display_name},
            )
            await session.commit()
            return [f"已创建 {user.username}（{user.role}）"]

        user = await _require_user(session, args.username)
        if args.command == "set-password":
            password = read_password(from_stdin=args.password_stdin, stdin=stdin, prompt=prompt)
            ended = await set_admin_password(
                session, user=user, password=password, now=now, actor_id=None, actor=CLI_ACTOR
            )
            await session.commit()
            return [f"已重设 {user.username} 的密码，结束了 {ended} 个在线会话"]

        if args.command in {"disable", "enable"}:
            active = args.command == "enable"
            user.active = active
            user.updated_at = now
            if active:
                user.failed_login_count = 0
                user.locked_until = None
            ended = 0 if active else await revoke_user_sessions(session, user_id=user.id, now=now)
            await add_audit_event(
                session,
                now=now,
                user_id=None,
                username=CLI_ACTOR,
                action="user.enabled" if active else "user.disabled",
                target_type="admin_user",
                target_id=user.username,
                detail={} if active else {"sessions_ended": ended},
            )
            await session.commit()
            return [f"已{'启用' if active else '停用'} {user.username}"]
    except AdminInputError as error:
        await session.rollback()
        raise CommandError(str(error)) from error
    except CommandError:
        await session.rollback()
        raise
    raise CommandError(f"unknown command: {args.command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.admin_users_main")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="列出账号")
    create = commands.add_parser("create", help="新建账号")
    create.add_argument("username")
    create.add_argument("--name", required=True, help="显示名，例如 李老师")
    create.add_argument("--role", choices=ADMIN_ROLES, required=True)
    create.add_argument("--password-stdin", action="store_true")
    password = commands.add_parser("set-password", help="重设密码")
    password.add_argument("username")
    password.add_argument("--password-stdin", action="store_true")
    for name, help_text in (("disable", "停用账号"), ("enable", "启用账号")):
        commands.add_parser(name, help=help_text).add_argument("username")
    return parser


async def _main(argv: Sequence[str]) -> int:
    from app.core.config import get_settings
    from app.infrastructure.db.session import create_engine, create_session_factory

    args = build_parser().parse_args(argv)
    engine = create_engine(get_settings())
    try:
        async with create_session_factory(engine)() as session:
            lines = await run_command(session, args, now=datetime.now(UTC), stdin=sys.stdin)
    except CommandError as error:
        print(f"没有完成: {error}", file=sys.stderr)
        return 2
    finally:
        await engine.dispose()
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
