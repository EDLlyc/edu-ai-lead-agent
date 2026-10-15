# ruff: noqa: RUF001
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from app.api_main import app
from app.domain.admin_auth import hash_password
from app.infrastructure.db.admin_auth import add_user
from app.infrastructure.db.models import (
    AdminAuditEventModel,
    AdminSessionModel,
    AdminUserModel,
    EvidenceCandidateModel,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from .conftest import IntegrationContext
from .test_governance_repositories import _create_acquisition_fixture

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

PASSWORD = "owner-pass-2026"
WRITE = {"X-Admin-Request": "1"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _login(client: AsyncClient, username: str, password: str) -> int:
    response = await client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": password},
        headers=WRITE,
    )
    return response.status_code


@pytest_asyncio.fixture(loop_scope="session")
async def owner(integration_context: IntegrationContext) -> AsyncIterator[str]:
    app.state.settings = integration_context.settings
    app.state.session_factory = integration_context.session_factory
    username = f"own{uuid4().hex[:8]}"
    async with integration_context.session_factory() as session:
        await add_user(
            session,
            username=username,
            display_name="管理员",
            role="owner",
            password_hash=hash_password(PASSWORD),
            now=datetime.now(UTC),
        )
        await session.commit()
    yield username
    # Later migration tests downgrade past 0052, which refuses a non-empty audit log.
    async with integration_context.session_factory() as session:
        await session.execute(delete(AdminAuditEventModel))
        await session.execute(delete(AdminSessionModel))
        await session.execute(delete(AdminUserModel))
        await session.commit()


async def test_an_owner_creates_resets_disables_and_edits_accounts(
    integration_context: IntegrationContext, owner: str
) -> None:
    async with _client() as admin, _client() as teacher:
        assert await _login(admin, owner, PASSWORD) == 200
        name = f"t{uuid4().hex[:8]}"

        created = await admin.post(
            "/api/v1/admin/accounts",
            json={"username": name.upper(), "display_name": "王老师", "role": "editor"},
            headers=WRITE,
        )
        assert created.status_code == 201
        first_password = created.json()["initial_password"]
        assert len(first_password) == 14
        assert created.json()["account"] == {
            "username": name,
            "display_name": "王老师",
            "role": "editor",
            "active": True,
            "locked": False,
            "last_login_at": None,
            "created_at": created.json()["account"]["created_at"],
            "live_sessions": 0,
        }
        duplicate = await admin.post(
            "/api/v1/admin/accounts",
            json={"username": name, "display_name": "重复", "role": "editor"},
            headers=WRITE,
        )
        assert duplicate.status_code == 409
        bad = await admin.post(
            "/api/v1/admin/accounts",
            json={"username": "王老师", "display_name": "x", "role": "editor"},
            headers=WRITE,
        )
        assert bad.status_code == 422
        assert "用户名" in bad.json()["error"]["message"]

        # The teacher logs in with the generated password; editors cannot manage accounts.
        assert await _login(teacher, name, first_password) == 200
        assert (await teacher.get("/api/v1/admin/accounts")).status_code == 403

        listed = await admin.get("/api/v1/admin/accounts")
        row = next(item for item in listed.json()["items"] if item["username"] == name)
        assert row["live_sessions"] == 1
        assert first_password not in listed.text

        reset = await admin.post(f"/api/v1/admin/accounts/{name}/reset-password", headers=WRITE)
        second_password = reset.json()["initial_password"]
        assert second_password != first_password
        assert reset.json()["account"]["live_sessions"] == 0
        assert (await teacher.get("/api/v1/admin/auth/me")).status_code == 401
        teacher.cookies.clear()
        assert await _login(teacher, name, first_password) == 401
        assert await _login(teacher, name, second_password) == 200

        disabled = await admin.post(f"/api/v1/admin/accounts/{name}/disable", headers=WRITE)
        assert disabled.json()["active"] is False
        assert (await teacher.get("/api/v1/admin/auth/me")).status_code == 401
        teacher.cookies.clear()
        assert await _login(teacher, name, second_password) == 401
        enabled = await admin.post(f"/api/v1/admin/accounts/{name}/enable", headers=WRITE)
        assert enabled.json()["active"] is True
        assert await _login(teacher, name, second_password) == 200

        edited = await admin.patch(
            f"/api/v1/admin/accounts/{name}",
            json={"display_name": "王老师（科学）", "role": "owner"},
            headers=WRITE,
        )
        assert edited.json()["display_name"] == "王老师（科学）"
        assert edited.json()["role"] == "owner"
        # With two owners, one owner may demote the other.
        demoted = await admin.patch(
            f"/api/v1/admin/accounts/{name}", json={"role": "editor"}, headers=WRITE
        )
        assert demoted.json()["role"] == "editor"

    async with integration_context.session_factory() as session:
        rows = (
            await session.execute(
                select(AdminAuditEventModel.action, AdminAuditEventModel.detail)
                .where(AdminAuditEventModel.target_id == name)
                .order_by(AdminAuditEventModel.occurred_at)
            )
        ).all()
    assert [action for action, _detail in rows] == [
        "user.created",
        "user.password_set",
        "user.disabled",
        "user.enabled",
        "user.updated",
        "user.updated",
    ]
    assert rows[4][1]["changes"]["role"] == {"from": "editor", "to": "owner"}
    every_detail = str([detail for _action, detail in rows])
    assert first_password not in every_detail
    assert second_password not in every_detail


async def test_an_owner_cannot_lock_themselves_out(owner: str) -> None:
    async with _client() as admin:
        assert await _login(admin, owner, PASSWORD) == 200
        disable = await admin.post(f"/api/v1/admin/accounts/{owner}/disable", headers=WRITE)
        assert disable.status_code == 409
        assert "不能停用自己" in disable.json()["error"]["message"]
        demote = await admin.patch(
            f"/api/v1/admin/accounts/{owner}", json={"role": "editor"}, headers=WRITE
        )
        assert demote.status_code == 409
        assert (await admin.get("/api/v1/admin/auth/me")).json()["role"] == "owner"
        missing = await admin.post("/api/v1/admin/accounts/nobody-here/disable", headers=WRITE)
        assert missing.status_code == 404


async def test_changing_my_password_keeps_this_session_and_ends_the_others(owner: str) -> None:
    async with _client() as here, _client() as elsewhere:
        assert await _login(here, owner, PASSWORD) == 200
        assert await _login(elsewhere, owner, PASSWORD) == 200

        wrong = await here.post(
            "/api/v1/admin/auth/password",
            json={"current_password": "not-it", "new_password": "brand-new-pass-1"},
            headers=WRITE,
        )
        assert wrong.status_code == 422
        assert wrong.json()["error"]["code"] == "admin_current_password_wrong"
        for new_password, message in [("short", "8–128"), (PASSWORD, "不能和当前密码一样")]:
            refused = await here.post(
                "/api/v1/admin/auth/password",
                json={"current_password": PASSWORD, "new_password": new_password},
                headers=WRITE,
            )
            assert refused.status_code == 422
            assert message in refused.json()["error"]["message"]

        changed = await here.post(
            "/api/v1/admin/auth/password",
            json={"current_password": PASSWORD, "new_password": "brand-new-pass-1"},
            headers=WRITE,
        )
        assert changed.status_code == 200
        assert changed.json() == {"other_sessions_ended": 1}
        assert (await here.get("/api/v1/admin/auth/me")).status_code == 200
        assert (await elsewhere.get("/api/v1/admin/auth/me")).status_code == 401
        elsewhere.cookies.clear()
        assert await _login(elsewhere, owner, PASSWORD) == 401
        assert await _login(elsewhere, owner, "brand-new-pass-1") == 200

        # Back to the fixture password so the other tests can log in.
        restored = await here.post(
            "/api/v1/admin/auth/password",
            json={"current_password": "brand-new-pass-1", "new_password": PASSWORD},
            headers=WRITE,
        )
        assert restored.status_code == 200


async def test_the_audit_log_filters_by_kind_and_pages_back(owner: str) -> None:
    async with _client() as admin:
        for _ in range(3):
            assert await _login(admin, owner, PASSWORD) == 200
        everything = await admin.get("/api/v1/admin/audit-events", params={"limit": 200})
        logins = await admin.get(
            "/api/v1/admin/audit-events", params={"kind": "auth", "limit": 200}
        )
        assert logins.status_code == 200
        assert {item["action"].split(".")[0] for item in logins.json()["items"]} == {"auth"}
        assert logins.json()["count"] <= everything.json()["count"]

        first = await admin.get("/api/v1/admin/audit-events", params={"kind": "auth", "limit": 2})
        oldest_shown = first.json()["items"][-1]["occurred_at"]
        older = await admin.get(
            "/api/v1/admin/audit-events",
            params={"kind": "auth", "limit": 2, "before": oldest_shown},
        )
        assert older.status_code == 200
        assert all(item["occurred_at"] < oldest_shown for item in older.json()["items"])
        assert (
            await admin.get("/api/v1/admin/audit-events", params={"kind": "nope"})
        ).status_code == 422


async def test_a_source_lists_its_latest_articles(
    integration_context: IntegrationContext, owner: str
) -> None:
    _acquisition_id, candidate_ids = await _create_acquisition_fixture(integration_context)
    async with integration_context.session_factory() as session:
        candidate = await session.get(EvidenceCandidateModel, candidate_ids[0])
        assert candidate is not None
        source_id, title = candidate.source_id, candidate.title

    async with _client() as admin:
        assert await _login(admin, owner, PASSWORD) == 200
        articles = await admin.get(f"/api/v1/admin/sources/{source_id}/articles")
        assert articles.status_code == 200
        assert title in [item["title"] for item in articles.json()["items"]]
        fetched = [item["fetched_at"] for item in articles.json()["items"]]
        assert fetched == sorted(fetched, reverse=True)
        missing = await admin.get(f"/api/v1/admin/sources/{uuid4()}/articles")
        assert missing.status_code == 404


async def test_an_owner_can_choose_the_password_and_only_common_ones_are_refused(
    owner: str,
) -> None:
    async with _client() as admin, _client() as teacher:
        assert await _login(admin, owner, PASSWORD) == 200
        name = f"c{uuid4().hex[:8]}"
        url = "/api/v1/admin/accounts"

        for refused, message in [
            ("12345678", "太常见"),
            ("short", "8–128"),
            (name, "和用户名一样"),
        ]:
            response = await admin.post(
                url,
                json={
                    "username": name,
                    "display_name": "李",
                    "role": "editor",
                    "password": refused,
                },
                headers=WRITE,
            )
            assert response.status_code == 422, refused
            assert message in response.json()["error"]["message"]
        listed = await admin.get(url)
        assert all(item["username"] != name for item in listed.json()["items"])

        # A weak but uncommon password is the owner's call; it is never echoed back.
        created = await admin.post(
            url,
            json={"username": name, "display_name": "李", "role": "editor", "password": "19900101"},
            headers=WRITE,
        )
        assert created.status_code == 201
        assert created.json()["initial_password"] is None
        assert "19900101" not in created.text
        assert await _login(teacher, name, "19900101") == 200

        refused_reset = await admin.post(
            f"{url}/{name}/reset-password", json={"password": "password"}, headers=WRITE
        )
        assert refused_reset.status_code == 422
        assert await _login(teacher, name, "19900101") == 200

        reset = await admin.post(
            f"{url}/{name}/reset-password", json={"password": "my own words 7"}, headers=WRITE
        )
        assert reset.status_code == 200
        assert reset.json()["initial_password"] is None
        assert (await teacher.get("/api/v1/admin/auth/me")).status_code == 401
        teacher.cookies.clear()
        assert await _login(teacher, name, "19900101") == 401
        assert await _login(teacher, name, "my own words 7") == 200

        generated = await admin.post(f"{url}/{name}/reset-password", headers=WRITE)
        assert len(generated.json()["initial_password"]) == 14
