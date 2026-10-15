# ruff: noqa: RUF001
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from app.api_main import app
from app.domain.admin_auth import SESSION_COOKIE_NAME, hash_password
from app.infrastructure.db.admin_auth import add_user
from app.infrastructure.db.models import (
    AdminAuditEventModel,
    AdminSessionModel,
    AdminUserModel,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from .conftest import IntegrationContext

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

PASSWORD = "teacher-pass-2026"
WRITE = {"X-Admin-Request": "1"}


async def _user(context: IntegrationContext, role: str = "owner") -> str:
    username = f"op{uuid4().hex[:10]}"
    async with context.session_factory() as session:
        await add_user(
            session,
            username=username,
            display_name="李老师",
            role=role,
            password_hash=hash_password(PASSWORD),
            now=datetime.now(UTC),
        )
        await session.commit()
    return username


@pytest_asyncio.fixture(loop_scope="session")
async def client(integration_context: IntegrationContext) -> AsyncIterator[AsyncClient]:
    app.state.settings = integration_context.settings
    app.state.session_factory = integration_context.session_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    # Migration tests later in the session downgrade past 0052, which refuses a non-empty audit log.
    async with integration_context.session_factory() as session:
        await session.execute(delete(AdminAuditEventModel))
        await session.execute(delete(AdminSessionModel))
        await session.execute(delete(AdminUserModel))
        await session.commit()


async def _login(client: AsyncClient, username: str, password: str = PASSWORD) -> int:
    response = await client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": password},
        headers=WRITE,
    )
    return response.status_code


async def test_login_sets_a_strict_http_only_cookie_and_logout_ends_it(
    integration_context: IntegrationContext, client: AsyncClient
) -> None:
    username = await _user(integration_context)

    assert (await client.get("/api/v1/admin/auth/me")).status_code == 401

    response = await client.post(
        "/api/v1/admin/auth/login",
        json={"username": username.upper(), "password": PASSWORD},
        headers=WRITE,
    )
    assert response.status_code == 200
    assert response.json()["username"] == username
    assert response.json()["role"] == "owner"
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api/v1/admin" in cookie
    assert "Max-Age=43200" in cookie
    token = response.cookies[SESSION_COOKIE_NAME]

    me = await client.get("/api/v1/admin/auth/me")
    assert me.status_code == 200
    assert me.json()["display_name"] == "李老师"

    async with integration_context.session_factory() as session:
        stored = (await session.scalars(select(AdminSessionModel.token_hash))).all()
    assert token not in stored

    assert (await client.post("/api/v1/admin/auth/logout", headers=WRITE)).status_code == 204
    client.cookies.set(SESSION_COOKIE_NAME, token, path="/api/v1/admin")
    assert (await client.get("/api/v1/admin/auth/me")).status_code == 401
    client.cookies.clear()


async def test_shared_cookie_domain_scopes_login_and_logout_to_the_whole_site(
    integration_context: IntegrationContext, client: AsyncClient
) -> None:
    original = app.state.settings
    app.state.settings = original.model_copy(update={"admin_session_cookie_domain": "example.com"})
    try:
        username = await _user(integration_context)
        login = await client.post(
            "/api/v1/admin/auth/login",
            json={"username": username, "password": PASSWORD},
            headers=WRITE,
        )
        assert login.status_code == 200
        cookie = login.headers["set-cookie"]
        assert "Domain=example.com" in cookie
        assert "Path=/;" in cookie or cookie.rstrip().endswith("Path=/")
        assert "Path=/api/v1/admin" not in cookie
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie
        logout = await client.post("/api/v1/admin/auth/logout", headers=WRITE)
        cleared = logout.headers["set-cookie"]
        assert "Domain=example.com" in cleared and "Max-Age=0" in cleared
    finally:
        app.state.settings = original
        client.cookies.clear()


async def test_writes_without_the_guard_header_are_refused(
    integration_context: IntegrationContext, client: AsyncClient
) -> None:
    username = await _user(integration_context)
    response = await client.post(
        "/api/v1/admin/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "admin_write_guard_missing"
    assert SESSION_COOKIE_NAME not in response.cookies


async def test_unknown_user_wrong_password_and_lockout_look_the_same(
    integration_context: IntegrationContext, client: AsyncClient
) -> None:
    username = await _user(integration_context)

    unknown = await client.post(
        "/api/v1/admin/auth/login",
        json={"username": "nobody-here", "password": PASSWORD},
        headers=WRITE,
    )
    wrong = await client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": "not-the-password"},
        headers=WRITE,
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]

    for _ in range(4):
        assert await _login(client, username, "still-wrong-password") == 401
    # Five wrong in a row: even the right password is refused for 15 minutes.
    assert await _login(client, username) == 401

    async with integration_context.session_factory() as session:
        user = await session.scalar(
            select(AdminUserModel).where(AdminUserModel.username == username)
        )
        assert user is not None
        assert user.locked_until is not None
        reasons = (
            await session.scalars(
                select(AdminAuditEventModel.detail)
                .where(AdminAuditEventModel.username == username)
                .order_by(AdminAuditEventModel.occurred_at)
            )
        ).all()
        assert [item["reason"] for item in reasons] == [
            "wrong_password",
            "wrong_password",
            "wrong_password",
            "wrong_password",
            "wrong_password_locked",
            "locked",
        ]
        await session.execute(
            update(AdminUserModel)
            .where(AdminUserModel.id == user.id)
            .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    assert await _login(client, username) == 200
    client.cookies.clear()


async def test_an_expired_or_disabled_session_is_refused(
    integration_context: IntegrationContext, client: AsyncClient
) -> None:
    username = await _user(integration_context)
    assert await _login(client, username) == 200
    async with integration_context.session_factory() as session:
        user_id = await session.scalar(
            select(AdminUserModel.id).where(AdminUserModel.username == username)
        )
        await session.execute(
            update(AdminSessionModel)
            .where(AdminSessionModel.user_id == user_id)
            .values(
                created_at=datetime.now(UTC) - timedelta(hours=13),
                expires_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        await session.commit()
    assert (await client.get("/api/v1/admin/auth/me")).status_code == 401

    assert await _login(client, username) == 200
    async with integration_context.session_factory() as session:
        await session.execute(
            update(AdminUserModel).where(AdminUserModel.id == user_id).values(active=False)
        )
        await session.commit()
    response = await client.get("/api/v1/admin/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "admin_login_required"
    client.cookies.clear()


async def test_only_an_owner_reads_the_audit_log_and_it_holds_no_secrets(
    integration_context: IntegrationContext, client: AsyncClient
) -> None:
    editor = await _user(integration_context, role="editor")
    owner = await _user(integration_context)

    assert await _login(client, editor) == 200
    refused = await client.get("/api/v1/admin/audit-events")
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "admin_forbidden"
    client.cookies.clear()

    assert await _login(client, owner, "wrong-password-1") == 401
    assert await _login(client, owner) == 200
    response = await client.get("/api/v1/admin/audit-events", params={"limit": 200})
    assert response.status_code == 200
    mine = [item for item in response.json()["items"] if item["username"] == owner]
    assert [item["action"] for item in mine] == ["auth.login", "auth.login_failed"]
    body = response.text
    assert PASSWORD not in body
    assert "wrong-password-1" not in body
    assert response.cookies.get(SESSION_COOKIE_NAME) is None
    client.cookies.clear()


async def test_the_account_command_line_creates_resets_and_disables(
    integration_context: IntegrationContext, client: AsyncClient
) -> None:
    from io import StringIO

    from app.admin_users_main import CommandError, build_parser, run_command

    async def run(*argv: str, stdin: str = "") -> list[str]:
        async with integration_context.session_factory() as session:
            return await run_command(
                session,
                build_parser().parse_args(argv),
                now=datetime.now(UTC),
                stdin=StringIO(stdin),
                prompt=lambda _label: "never-used",
            )

    name = f"cli{uuid4().hex[:8]}"
    assert await run(
        "create",
        name,
        "--name",
        "王老师",
        "--role",
        "editor",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    ) == [f"已创建 {name}（editor）"]
    with pytest.raises(CommandError, match="已存在"):
        await run("create", name, "--name", "x", "--role", "owner", "--password-stdin", stdin="y\n")
    with pytest.raises(CommandError, match="8-128"):
        await run("set-password", name, "--password-stdin", stdin="short\n")
    # A typed password must be confirmed.
    with pytest.raises(CommandError, match="不一样"):
        async with integration_context.session_factory() as session:
            answers = iter(["first-password-1", "second-password-2"])
            await run_command(
                session,
                build_parser().parse_args(["set-password", name]),
                now=datetime.now(UTC),
                stdin=StringIO(),
                prompt=lambda _label: next(answers),
            )

    assert await _login(client, name) == 200
    assert any(
        line.startswith(f"{name}\t王老师\teditor\t启用\t在线会话 1") for line in await run("list")
    )
    assert await run("set-password", name, "--password-stdin", stdin="a-new-password-9\n") == [
        f"已重设 {name} 的密码，结束了 1 个在线会话"
    ]
    assert (await client.get("/api/v1/admin/auth/me")).status_code == 401
    assert await _login(client, name, "a-new-password-9") == 200

    assert await run("disable", name) == [f"已停用 {name}"]
    assert (await client.get("/api/v1/admin/auth/me")).status_code == 401
    assert await _login(client, name, "a-new-password-9") == 401
    assert await run("enable", name) == [f"已启用 {name}"]
    assert await _login(client, name, "a-new-password-9") == 200
    client.cookies.clear()

    async with integration_context.session_factory() as session:
        actions = (
            await session.scalars(
                select(AdminAuditEventModel.action)
                .where(AdminAuditEventModel.target_id == name)
                .order_by(AdminAuditEventModel.occurred_at)
            )
        ).all()
        hashes = (
            await session.scalars(
                select(AdminUserModel.password_hash).where(AdminUserModel.username == name)
            )
        ).all()
    assert actions == ["user.created", "user.password_set", "user.disabled", "user.enabled"]
    assert all("a-new-password-9" not in value for value in hashes)
