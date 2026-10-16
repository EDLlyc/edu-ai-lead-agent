from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from app.api_main import app
from app.domain.admin_auth import hash_password
from app.domain.builtin_phrases import DEFAULT_MARKETING
from app.infrastructure.db.admin_auth import add_user
from app.infrastructure.db.models import (
    AdminAuditEventModel,
    AdminSessionModel,
    AdminUserModel,
    BuiltinPhraseVersionModel,
    ContentSlotRunModel,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, update

from .conftest import IntegrationContext

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

PASSWORD = "teacher-pass-2026"
WRITE = {"X-Admin-Request": "1"}


@pytest_asyncio.fixture(loop_scope="session")
async def client(integration_context: IntegrationContext) -> AsyncIterator[AsyncClient]:
    username = f"bp{uuid4().hex[:10]}"
    async with integration_context.session_factory() as session:
        await add_user(
            session,
            username=username,
            display_name="李老师",
            role="editor",
            password_hash=hash_password(PASSWORD),
            now=datetime.now(UTC),
        )
        await session.commit()
    app.state.settings = integration_context.settings
    app.state.session_factory = integration_context.session_factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        login = await http.post(
            "/api/v1/admin/auth/login",
            json={"username": username, "password": PASSWORD},
            headers=WRITE,
        )
        assert login.status_code == 200
        yield http
    async with integration_context.session_factory() as session:
        await session.execute(
            update(ContentSlotRunModel)
            .where(ContentSlotRunModel.builtin_phrase_version_id.is_not(None))
            .values(builtin_phrase_version_id=None)
        )
        await session.execute(delete(BuiltinPhraseVersionModel))
        await session.execute(delete(AdminAuditEventModel))
        await session.execute(delete(AdminSessionModel))
        await session.execute(delete(AdminUserModel))
        await session.commit()


async def test_an_editor_can_replace_the_builtin_lists(
    client: AsyncClient,
) -> None:
    current = await client.get("/api/v1/admin/builtin-phrases")
    assert current.status_code == 200
    body = current.json()
    assert body["version"] is None
    assert body["marketing"] == list(DEFAULT_MARKETING)
    assert body["locked"]
    assert (await client.post("/api/v1/admin/builtin-phrases", json={})).status_code == 403

    unchanged = await client.post(
        "/api/v1/admin/builtin-phrases",
        json={"marketing": list(DEFAULT_MARKETING), "anxiety": body["anxiety"]},
        headers=WRITE,
    )
    assert unchanged.status_code == 409

    saved = await client.post(
        "/api/v1/admin/builtin-phrases",
        json={"marketing": ["包过"], "anxiety": []},
        headers=WRITE,
    )
    assert saved.status_code == 200
    assert saved.json()["version"] == 1
    assert saved.json()["marketing"] == ["包过"]
    assert saved.json()["anxiety"] == []
    assert saved.json()["defaults_marketing"] == list(DEFAULT_MARKETING)
    again = await client.get("/api/v1/admin/builtin-phrases")
    assert again.json()["marketing"] == ["包过"]
