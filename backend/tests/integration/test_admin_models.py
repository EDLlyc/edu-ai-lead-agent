# ruff: noqa: RUF001
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from app.api_main import app
from app.application.services import model_api_keys
from app.domain.admin_auth import hash_password
from app.domain.secret_box import new_key
from app.infrastructure import model_api_keys_overlay as overlay
from app.infrastructure.db.admin_auth import add_user
from app.infrastructure.db.models import (
    AdminAuditEventModel,
    AdminSessionModel,
    AdminUserModel,
    ModelApiKeyModel,
    ModelKeyConsumerModel,
)
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, select

from .conftest import IntegrationContext

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

PASSWORD = "owner-pass-2026"
WRITE = {"X-Admin-Request": "1"}
GOOD = "good-zhipu-key-1111"
GOOD_2 = "good-zhipu-key-2222"
ENV_KEY = "good-env-key-0000"


def _provider_handler(request: httpx.Request) -> httpx.Response:
    if request.headers["Authorization"].startswith("Bearer good-"):
        return httpx.Response(200, json={"choices": []})
    return httpx.Response(401, json={"error": {"message": "API key 无效"}})


@pytest_asyncio.fixture(loop_scope="session")
async def models(integration_context: IntegrationContext, monkeypatch) -> AsyncIterator[str]:
    key = new_key()
    http = httpx.AsyncClient(transport=httpx.MockTransport(_provider_handler))
    app.state.settings = integration_context.settings.model_copy(
        update={
            "model_secret_key": SecretStr(key),
            "ai_platform_base_url": "https://open.bigmodel.cn/api/paas/v4",
        }
    )
    app.state.session_factory = integration_context.session_factory
    app.state.model_probe_http = http
    app.state.environment_model_keys = {
        "zhipu": SecretStr(ENV_KEY),
        "comfly": None,
        "alibaba-visual": None,
    }
    monkeypatch.setattr(model_api_keys, "TEST_GAP_SECONDS", 0.0)
    yield key
    await http.aclose()
    app.state.model_probe_http = None
    app.state.environment_model_keys = None
    app.state.settings = integration_context.settings
    async with integration_context.session_factory() as session:
        await session.execute(delete(ModelApiKeyModel))
        await session.execute(delete(ModelKeyConsumerModel))
        await session.execute(delete(AdminAuditEventModel))
        await session.execute(delete(AdminSessionModel))
        await session.execute(delete(AdminUserModel))
        await session.commit()


@asynccontextmanager
async def _logged_in(context: IntegrationContext, role: str) -> AsyncIterator[AsyncClient]:
    username = f"{role[:3]}{uuid4().hex[:8]}"
    async with context.session_factory() as session:
        await add_user(
            session,
            username=username,
            display_name="老师",
            role=role,
            password_hash=hash_password(PASSWORD),
            now=datetime.now(UTC),
        )
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = await client.post(
            "/api/v1/admin/auth/login",
            json={"username": username, "password": PASSWORD},
            headers=WRITE,
        )
        assert login.status_code == 200
        yield client


async def test_an_owner_rotates_a_key_only_after_it_passes_a_test(
    integration_context: IntegrationContext, models: str, monkeypatch
) -> None:
    base = "/api/v1/admin/models"
    async with (
        _logged_in(integration_context, "owner") as owner,
        _logged_in(integration_context, "editor") as editor,
    ):
        assert (await editor.get(base)).status_code == 403
        listed = (await owner.get(base)).json()
        assert listed["secret_key_configured"] is True
        zhipu = next(p for p in listed["providers"] if p["id"] == "zhipu")
        assert zhipu["source"] == "env"
        assert zhipu["key_hint"] == "••••0000"
        assert zhipu["version"] is None
        assert "glm-5.2" in zhipu["models"]
        assert next(p for p in listed["providers"] if p["id"] == "comfly")["source"] == "none"

        tested = await owner.post(
            f"{base}/zhipu/test", json={"api_key": "bad-key-9999"}, headers=WRITE
        )
        assert tested.json() == {
            "ok": False,
            "latency_ms": tested.json()["latency_ms"],
            "message": "key 不对，或者没有这个模型的权限：API key 无效",
        }
        refused = await owner.post(
            f"{base}/zhipu/keys", json={"api_key": "bad-key-9999"}, headers=WRITE
        )
        assert refused.status_code == 422
        assert "测试没通过" in refused.json()["error"]["message"]
        unguarded = await owner.post(f"{base}/zhipu/keys", json={"api_key": GOOD})
        assert unguarded.status_code == 403
        assert (
            await owner.post(f"{base}/nope/test", json={"api_key": GOOD}, headers=WRITE)
        ).status_code == 404

        saved = await owner.post(
            f"{base}/zhipu/keys", json={"api_key": GOOD, "note": "换新账号"}, headers=WRITE
        )
        assert saved.status_code == 201, saved.text
        assert saved.json()["source"] == "console"
        assert saved.json()["key_hint"] == "••••1111"
        assert saved.json()["version"] == 1
        assert GOOD not in saved.text
        second = await owner.post(f"{base}/zhipu/keys", json={"api_key": GOOD_2}, headers=WRITE)
        assert second.json()["version"] == 2

        current = await owner.post(f"{base}/zhipu/restore", json={"version": 2}, headers=WRITE)
        assert current.status_code == 409
        restored = await owner.post(f"{base}/zhipu/restore", json={"version": 1}, headers=WRITE)
        assert restored.json()["version"] == 3
        assert restored.json()["key_hint"] == "••••1111"

        to_env = await owner.post(f"{base}/zhipu/use-env", headers=WRITE)
        assert to_env.json()["source"] == "env"
        assert to_env.json()["version"] == 4
        again = await owner.post(f"{base}/zhipu/use-env", headers=WRITE)
        assert again.status_code == 409

        history = (await owner.get(f"{base}/zhipu/history")).json()["items"]
        assert [(i["version"], i["source"], i["key_hint"], i["current"]) for i in history] == [
            (4, "env", None, True),
            (3, "console", "••••1111", False),
            (2, "console", "••••2222", False),
            (1, "console", "••••1111", False),
        ]
        assert history[1]["restored_from"] == 1
        assert history[3]["note"] == "换新账号"

    async with integration_context.session_factory() as session:
        audit = (
            await session.scalars(
                select(AdminAuditEventModel)
                .where(AdminAuditEventModel.action.like("model_key.%"))
                .order_by(AdminAuditEventModel.occurred_at)
            )
        ).all()
    assert [event.action for event in audit] == [
        "model_key.rotated",
        "model_key.rotated",
        "model_key.restored",
        "model_key.env_restored",
    ]
    assert GOOD not in str([event.detail for event in audit])

    # A worker starting now reads the newest version: env again (version 4).
    settings = integration_context.settings.model_copy(
        update={"model_secret_key": SecretStr(models), "ai_platform_api_key": SecretStr(ENV_KEY)}
    )
    monkeypatch.setattr(overlay, "_loaded_versions", None)
    assert overlay.read_latest_versions(settings)["zhipu"][0] == 4
    assert (
        overlay.with_console_model_keys(settings).ai_platform_api_key.get_secret_value() == ENV_KEY
    )


async def test_a_worker_starts_with_the_console_key(
    integration_context: IntegrationContext, models: str, monkeypatch
) -> None:
    async with _logged_in(integration_context, "owner") as owner:
        saved = await owner.post(
            "/api/v1/admin/models/zhipu/keys", json={"api_key": GOOD_2}, headers=WRITE
        )
        assert saved.status_code == 201
    monkeypatch.setattr(overlay, "_loaded_versions", None)
    settings = integration_context.settings.model_copy(
        update={"model_secret_key": SecretStr(models), "ai_platform_api_key": SecretStr(ENV_KEY)}
    )
    applied = overlay.with_console_model_keys(settings)
    assert applied.ai_platform_api_key.get_secret_value() == GOOD_2
    assert overlay.loaded_versions() == {"zhipu": 1}

    # It reports what it loaded; the page shows which services have switched.
    assert overlay.beat_and_read(settings, "content-worker", "host-a") == {"zhipu": 1}
    assert overlay.beat_and_read(settings, "content-worker", "host-a") == {"zhipu": 1}
    async with _logged_in(integration_context, "owner") as owner:
        consumers = (await owner.get("/api/v1/admin/models")).json()["consumers"]
    by_service = {item["service"]: item for item in consumers}
    assert len(consumers) == 6
    assert by_service["content-worker"]["reporting"] is True
    assert by_service["content-worker"]["versions"] == {"zhipu": 1}
    assert by_service["content-worker"]["load_errors"] == {}
    assert by_service["content-worker"]["label"] == "选题与文案"
    assert by_service["governance-worker"]["reporting"] is False
    assert by_service["governance-worker"]["versions"] is None
    assert by_service["governance-worker"]["load_errors"] is None
    # Another MODEL_SECRET_KEY cannot open it: the environment key stays.
    other = settings.model_copy(update={"model_secret_key": SecretStr(new_key())})
    assert overlay.with_console_model_keys(other).ai_platform_api_key.get_secret_value() == ENV_KEY
    assert overlay.loaded_versions() == {}
    assert overlay.beat_and_read(other, "content-worker", "host-a") == {"zhipu": 1}
    async with integration_context.session_factory() as session:
        now = datetime.now(UTC)
        session.add(
            ModelKeyConsumerModel(
                service="governance-worker",
                host="legacy-host",
                versions={"zhipu": 1},
                started_at=now,
                seen_at=now,
            )
        )
        await session.commit()
    async with _logged_in(integration_context, "owner") as owner:
        response = await owner.get("/api/v1/admin/models")
        assert response.status_code == 200
        consumers = response.json()["consumers"]
    by_service = {item["service"]: item for item in consumers}
    assert by_service["content-worker"]["versions"] == {}
    assert by_service["content-worker"]["load_errors"] == {"zhipu": "key_unreadable"}
    assert by_service["governance-worker"]["reporting"] is True
    assert by_service["governance-worker"]["load_errors"] is None
    assert GOOD_2 not in response.text and models not in response.text


async def test_without_the_model_secret_key_nothing_is_stored(
    integration_context: IntegrationContext, models: str
) -> None:
    app.state.settings = integration_context.settings.model_copy(update={"model_secret_key": None})
    async with _logged_in(integration_context, "owner") as owner:
        listed = (await owner.get("/api/v1/admin/models")).json()
        assert listed["secret_key_configured"] is False
        refused = await owner.post(
            "/api/v1/admin/models/zhipu/keys", json={"api_key": GOOD}, headers=WRITE
        )
        assert refused.status_code == 503
    async with integration_context.session_factory() as session:
        assert (await session.scalar(select(ModelApiKeyModel.id))) is None
