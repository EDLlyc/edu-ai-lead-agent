from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from app.api_main import app
from app.application.services import wechat_admin
from app.application.services.wechat_admin import run_publish_loop_once
from app.application.services.wechat_stats import run_stats_loop_once
from app.domain.admin_auth import hash_password
from app.domain.secret_box import new_key
from app.infrastructure.db.admin_auth import add_user
from app.infrastructure.db.models import (
    AdminAuditEventModel,
    AdminSessionModel,
    AdminUserModel,
    WeChatAccountDailyStatsModel,
    WeChatAccountModel,
    WeChatArticleStatsModel,
    WeChatPublishJobModel,
)
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, select, update

from .conftest import IntegrationContext

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

PASSWORD = "owner-pass-2026"
WRITE = {"X-Admin-Request": "1"}
APP_ID = "wx0123456789abcdef"
SECRET = "0123456789abcdef0123456789abcdef"


@dataclass
class FakeWeChat:
    """In-memory api.weixin.qq.com: one account, drafts, publishing."""

    secret: str = SECRET
    drafts: list[dict[str, Any]] = field(default_factory=list)
    submitted: list[str] = field(default_factory=list)
    status: dict[str, dict[str, Any]] = field(default_factory=dict)
    submit_timeout: bool = False
    calls: list[str] = field(default_factory=list)
    article_day: str = ""
    datacube_error: int | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        body = json.loads(request.content or b"{}")
        if path == "/cgi-bin/stable_token":
            if body.get("appid") != APP_ID or body.get("secret") != self.secret:
                return httpx.Response(200, json={"errcode": 40125, "errmsg": "invalid appsecret"})
            return httpx.Response(200, json={"access_token": "T" * 40, "expires_in": 7200})
        if request.url.params.get("access_token") != "T" * 40:
            return httpx.Response(200, json={"errcode": 40001, "errmsg": "invalid credential"})
        if path == "/cgi-bin/draft/batchget":
            return httpx.Response(200, json={"total_count": len(self.drafts), "item": self.drafts})
        if path == "/cgi-bin/freepublish/batchget":
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "item": [
                        {
                            "article_id": "A1",
                            "update_time": 1_759_000_000,
                            "content": {
                                "news_item": [
                                    {"title": "已发布", "url": "https://mp.weixin.qq.com/s/a1"}
                                ]
                            },
                        }
                    ],
                },
            )
        if path == "/cgi-bin/freepublish/submit":
            if self.submit_timeout:
                raise httpx.ReadTimeout("slow", request=request)
            publish_id = f"P{len(self.submitted) + 1}"
            self.submitted.append(body["media_id"])
            self.status[publish_id] = {"publish_status": 1}
            return httpx.Response(200, json={"errcode": 0, "publish_id": publish_id})
        if path.startswith("/datacube/") and self.datacube_error is not None:
            return httpx.Response(200, json={"errcode": self.datacube_error, "errmsg": "no"})
        if path == "/datacube/getarticletotaldetail":
            if body["begin_date"] != self.article_day:
                return httpx.Response(200, json={"list": []})
            sources = [
                {"scene_desc": "公众号消息", "user_count": 30},
                {"scene_desc": "朋友圈", "user_count": 12},
                {"scene_desc": "全部", "user_count": 40},
            ]
            return httpx.Response(
                200,
                json={
                    "list": [
                        {
                            "msgid": "2247483661_1",
                            "title": "科学营开营",
                            "content_url": "https://mp.weixin.qq.com/s/art1",
                            "ref_date": self.article_day,
                            "publish_type": 0,
                            "detail_list": [
                                {
                                    "stat_date": self.article_day,
                                    "read_user_source": sources[:1],
                                    "share_user": 1,
                                },
                                {
                                    "stat_date": "2099-01-01",
                                    "read_user_source": sources,
                                    "share_user": 5,
                                    "collection_user": 2,
                                    "read_subscribe_user": 3,
                                    "read_delivery_rate": 0.25,
                                    "read_avg_activetime": 1.5,
                                },
                            ],
                        }
                    ]
                },
            )
        if path == "/datacube/getbizsummary":
            day = int(body["begin_date"][-2:])
            return httpx.Response(
                200,
                json={
                    "list": [
                        {
                            "ref_date": body["begin_date"],
                            "detail": {
                                "read_user": day,
                                "share_user": 1,
                                "like_user": 2,
                                "zaikan_user": 0,
                                "comment_count": 0,
                                "collection_user": 1,
                                "redirect_ori_page_user": 0,
                                "send_page_count": 0,
                                "read_user_source": [
                                    {"scene_desc": "公众号消息", "user_count": day}
                                ],
                            },
                        }
                    ]
                },
            )
        if path == "/cgi-bin/freepublish/get":
            return httpx.Response(
                200, json={"publish_id": body["publish_id"], **self.status[body["publish_id"]]}
            )
        return httpx.Response(404)


def _draft(media_id: str, title: str) -> dict[str, Any]:
    return {
        "media_id": media_id,
        "update_time": 1_759_100_000,
        "content": {"news_item": [{"title": title, "author": "小赛", "digest": "摘要"}]},
    }


@pytest_asyncio.fixture(loop_scope="session")
async def wechat(integration_context: IntegrationContext) -> AsyncIterator[FakeWeChat]:
    fake = FakeWeChat(drafts=[_draft("M1", "科学营开营"), _draft("M2", "机器人进课堂")])
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    app.state.settings = integration_context.settings.model_copy(
        update={"admin_secret_key": SecretStr(new_key())}
    )
    app.state.session_factory = integration_context.session_factory
    app.state.wechat_http = http
    wechat_admin.forget_token(APP_ID)
    yield fake
    await http.aclose()
    app.state.wechat_http = None
    app.state.settings = integration_context.settings
    async with integration_context.session_factory() as session:
        await session.execute(delete(WeChatArticleStatsModel))
        await session.execute(delete(WeChatAccountDailyStatsModel))
        await session.execute(delete(WeChatPublishJobModel))
        await session.execute(delete(WeChatAccountModel))
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


async def _bind(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/admin/wechat/accounts",
        json={"name": "赛先生", "app_id": APP_ID, "app_secret": SECRET, "topics": ["科学", "教育"]},
        headers=WRITE,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_an_owner_binds_an_account_that_is_verified_and_stored_encrypted(
    integration_context: IntegrationContext, wechat: FakeWeChat
) -> None:
    async with (
        _logged_in(integration_context, "owner") as owner,
        _logged_in(integration_context, "editor") as editor,
    ):
        assert (await owner.get("/api/v1/admin/wechat/status")).json() == {
            "secret_key_configured": True
        }
        wrong = await owner.post(
            "/api/v1/admin/wechat/accounts",
            json={"name": "赛先生", "app_id": APP_ID, "app_secret": "f" * 32},
            headers=WRITE,
        )
        assert wrong.status_code == 422
        assert "AppSecret 不对" in wrong.json()["error"]["message"]

        account_id = await _bind(owner)
        duplicate = await owner.post(
            "/api/v1/admin/wechat/accounts",
            json={"name": "再来", "app_id": APP_ID, "app_secret": SECRET},
            headers=WRITE,
        )
        assert duplicate.status_code == 409

        listed = await owner.get("/api/v1/admin/wechat/accounts")
        account = listed.json()["items"][0]
        assert account["secret_hint"] == "••••cdef"
        assert account["topics"] == ["科学", "教育"]
        assert SECRET not in listed.text
        assert (await editor.get("/api/v1/admin/wechat/accounts")).status_code == 403
        options = await editor.get("/api/v1/admin/wechat/account-options")
        assert options.json()["items"] == [
            {"id": account_id, "name": "赛先生", "topics": ["科学", "教育"]}
        ]

        # Replace the secret: verified first, refused when wrong.
        wechat.secret = "a" * 32
        refused = await owner.patch(
            f"/api/v1/admin/wechat/accounts/{account_id}",
            json={"app_secret": "b" * 32},
            headers=WRITE,
        )
        assert refused.status_code == 422
        replaced = await owner.patch(
            f"/api/v1/admin/wechat/accounts/{account_id}",
            json={"app_secret": "a" * 32, "name": "赛先生科学"},
            headers=WRITE,
        )
        assert replaced.json()["secret_hint"] == "••••aaaa"
        assert replaced.json()["name"] == "赛先生科学"

        # The stored secret no longer matches WeChat: verify records the error.
        wechat.secret = SECRET
        verified = await owner.post(
            f"/api/v1/admin/wechat/accounts/{account_id}/verify", headers=WRITE
        )
        assert "AppSecret 不对" in verified.json()["last_verify_error"]
        wechat.secret = "a" * 32
        verified = await owner.post(
            f"/api/v1/admin/wechat/accounts/{account_id}/verify", headers=WRITE
        )
        assert verified.json()["last_verify_error"] is None

        disabled = await owner.patch(
            f"/api/v1/admin/wechat/accounts/{account_id}", json={"enabled": False}, headers=WRITE
        )
        assert disabled.json()["enabled"] is False
        assert (await editor.get("/api/v1/admin/wechat/account-options")).json()["items"] == []
        drafts = await editor.get(f"/api/v1/admin/wechat/accounts/{account_id}/drafts")
        assert drafts.status_code == 409

    async with integration_context.session_factory() as session:
        row = await session.get(WeChatAccountModel, UUID(account_id))
        assert row is not None
        assert row.app_secret_sealed.startswith("v1:")
        assert "a" * 32 not in row.app_secret_sealed
        details = (await session.scalars(select(AdminAuditEventModel.detail))).all()
    assert SECRET not in str(details)
    assert "a" * 32 not in str(details)


async def test_publishing_now_waits_for_wechat_and_records_the_link(
    integration_context: IntegrationContext, wechat: FakeWeChat
) -> None:
    async with (
        _logged_in(integration_context, "owner") as owner,
        _logged_in(integration_context, "editor") as editor,
    ):
        account_id = await _bind(owner)
        drafts = await editor.get(f"/api/v1/admin/wechat/accounts/{account_id}/drafts")
        assert [d["articles"][0]["title"] for d in drafts.json()["items"]] == [
            "科学营开营",
            "机器人进课堂",
        ]
        published = await editor.get(f"/api/v1/admin/wechat/accounts/{account_id}/published")
        assert published.json()["items"][0]["articles"][0]["url"] == "https://mp.weixin.qq.com/s/a1"

        job = await editor.post(
            "/api/v1/admin/wechat/publish-jobs",
            json={"account_id": account_id, "media_id": "M1", "title": "科学营开营"},
            headers=WRITE,
        )
        assert job.status_code == 201
        assert job.json()["status"] == "publishing"
        assert wechat.submitted == ["M1"]
        again = await editor.post(
            "/api/v1/admin/wechat/publish-jobs",
            json={"account_id": account_id, "media_id": "M1", "title": "科学营开营"},
            headers=WRITE,
        )
        assert again.status_code == 409
        drafts = await editor.get(f"/api/v1/admin/wechat/accounts/{account_id}/drafts")
        assert drafts.json()["items"][0]["open_job_id"] == job.json()["id"]

        now = datetime.now(UTC)
        await run_publish_loop_once(
            integration_context.session_factory,
            settings=app.state.settings,
            http=app.state.wechat_http,
            now=now,
        )
        jobs = await editor.get("/api/v1/admin/wechat/publish-jobs")
        assert jobs.json()["items"][0]["status"] == "publishing"

        wechat.status["P1"] = {
            "publish_status": 0,
            "article_id": "ART1",
            "article_detail": {
                "count": 1,
                "item": [{"idx": 1, "article_url": "https://mp.weixin.qq.com/s/art1"}],
            },
        }
        await run_publish_loop_once(
            integration_context.session_factory,
            settings=app.state.settings,
            http=app.state.wechat_http,
            now=now,
        )
        done = (await editor.get("/api/v1/admin/wechat/publish-jobs")).json()["items"][0]
        assert done["status"] == "succeeded"
        assert done["article_url"] == "https://mp.weixin.qq.com/s/art1"
        assert wechat.submitted == ["M1"]

    async with integration_context.session_factory() as session:
        actions = (
            await session.scalars(
                select(AdminAuditEventModel.action)
                .where(AdminAuditEventModel.action.startswith("wechat.publish"))
                .order_by(AdminAuditEventModel.occurred_at)
            )
        ).all()
    assert actions == [
        "wechat.publish_requested",
        "wechat.publish_submitted",
        "wechat.publish_succeeded",
    ]


async def test_a_scheduled_publish_waits_can_be_cancelled_and_fails_visibly(
    integration_context: IntegrationContext, wechat: FakeWeChat
) -> None:
    async with _logged_in(integration_context, "owner") as owner:
        account_id = await _bind(owner)
        now = datetime.now(UTC)
        too_soon = await owner.post(
            "/api/v1/admin/wechat/publish-jobs",
            json={
                "account_id": account_id,
                "media_id": "M2",
                "scheduled_at": (now + timedelta(seconds=30)).isoformat(),
            },
            headers=WRITE,
        )
        assert too_soon.status_code == 422
        scheduled = await owner.post(
            "/api/v1/admin/wechat/publish-jobs",
            json={
                "account_id": account_id,
                "media_id": "M2",
                "title": "机器人进课堂",
                "scheduled_at": (now + timedelta(minutes=10)).isoformat(),
            },
            headers=WRITE,
        )
        assert scheduled.json()["status"] == "scheduled"
        loop_args = {"settings": app.state.settings, "http": app.state.wechat_http}
        await run_publish_loop_once(integration_context.session_factory, now=now, **loop_args)
        assert wechat.submitted == []

        await run_publish_loop_once(
            integration_context.session_factory, now=now + timedelta(minutes=11), **loop_args
        )
        assert wechat.submitted == ["M2"]
        wechat.status["P1"] = {"publish_status": 3}
        await run_publish_loop_once(
            integration_context.session_factory, now=now + timedelta(minutes=12), **loop_args
        )
        failed = (await owner.get("/api/v1/admin/wechat/publish-jobs")).json()["items"][0]
        assert failed["status"] == "failed"
        assert failed["error"] == "发布失败"

        later = await owner.post(
            "/api/v1/admin/wechat/publish-jobs",
            json={
                "account_id": account_id,
                "media_id": "M2",
                "scheduled_at": (now + timedelta(days=1)).isoformat(),
            },
            headers=WRITE,
        )
        cancelled = await owner.post(
            f"/api/v1/admin/wechat/publish-jobs/{later.json()['id']}/cancel", headers=WRITE
        )
        assert cancelled.json()["status"] == "cancelled"
        again = await owner.post(
            f"/api/v1/admin/wechat/publish-jobs/{later.json()['id']}/cancel", headers=WRITE
        )
        assert again.status_code == 409


async def test_an_unknown_submit_outcome_is_never_retried(
    integration_context: IntegrationContext, wechat: FakeWeChat
) -> None:
    async with _logged_in(integration_context, "owner") as owner:
        account_id = await _bind(owner)
        wechat.submit_timeout = True
        job = await owner.post(
            "/api/v1/admin/wechat/publish-jobs",
            json={"account_id": account_id, "media_id": "M1", "title": "科学营开营"},
            headers=WRITE,
        )
        assert job.json()["status"] == "outcome_unknown"
        assert "结果未知" in job.json()["error"]
        wechat.submit_timeout = False
        await run_publish_loop_once(
            integration_context.session_factory,
            settings=app.state.settings,
            http=app.state.wechat_http,
            now=datetime.now(UTC) + timedelta(hours=1),
        )
        assert wechat.calls.count("/cgi-bin/freepublish/submit") == 1

        # A process that died mid-submit leaves a stale lease: given up as unknown, not resent.
        stuck = await owner.post(
            "/api/v1/admin/wechat/publish-jobs",
            json={
                "account_id": account_id,
                "media_id": "M2",
                "scheduled_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            },
            headers=WRITE,
        )
        async with integration_context.session_factory() as session:
            await session.execute(
                update(WeChatPublishJobModel)
                .where(WeChatPublishJobModel.id == UUID(stuck.json()["id"]))
                .values(
                    status="submitting", lease_expires_at=datetime.now(UTC) - timedelta(minutes=1)
                )
            )
            await session.commit()
        report = await run_publish_loop_once(
            integration_context.session_factory,
            settings=app.state.settings,
            http=app.state.wechat_http,
            now=datetime.now(UTC),
        )
        assert report.recovered == 1
        assert wechat.calls.count("/cgi-bin/freepublish/submit") == 1


async def test_without_the_encryption_key_nothing_is_stored(
    integration_context: IntegrationContext, wechat: FakeWeChat
) -> None:
    app.state.settings = integration_context.settings
    async with _logged_in(integration_context, "owner") as owner:
        assert (await owner.get("/api/v1/admin/wechat/status")).json() == {
            "secret_key_configured": False
        }
        response = await owner.post(
            "/api/v1/admin/wechat/accounts",
            json={"name": "赛先生", "app_id": APP_ID, "app_secret": SECRET},
            headers=WRITE,
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "wechat_secret_key_missing"


async def test_reading_stats_sync_daily_and_keep_the_latest_cumulative_numbers(
    integration_context: IntegrationContext, wechat: FakeWeChat
) -> None:
    from zoneinfo import ZoneInfo

    shanghai = ZoneInfo("Asia/Shanghai")
    now = datetime.now(UTC)
    today = now.astimezone(shanghai).date()
    wechat.article_day = (today - timedelta(days=3)).isoformat()
    async with (
        _logged_in(integration_context, "owner") as owner,
        _logged_in(integration_context, "editor") as editor,
    ):
        account_id = await _bind(owner)
        synced = await editor.post(
            f"/api/v1/admin/wechat/accounts/{account_id}/stats/sync", headers=WRITE
        )
        assert synced.status_code == 200
        assert synced.json() == {"articles": 1, "days": 30}
        too_soon = await editor.post(
            f"/api/v1/admin/wechat/accounts/{account_id}/stats/sync", headers=WRITE
        )
        assert too_soon.status_code == 429

        stats = (await editor.get(f"/api/v1/admin/wechat/accounts/{account_id}/stats")).json()
        assert stats["synced_on"] == today.isoformat()
        assert stats["sync_error"] is None
        assert len(stats["daily"]) == 30
        assert stats["daily"][-1]["date"] == (today - timedelta(days=1)).isoformat()
        article = stats["articles"][0]
        # The 全部 scene is the total; the other scenes overlap it.
        assert article["read_user"] == 40
        assert article["share_user"] == 5
        assert article["read_delivery_rate"] == 0.25
        assert article["stat_date"] == "2099-01-01"
        assert article["read_sources"]["朋友圈"] == 12

        loop = {"settings": app.state.settings, "http": app.state.wechat_http}
        calls_before = len(wechat.calls)
        at_nine = datetime.combine(today, datetime.min.time(), shanghai).replace(hour=9)
        assert (
            await run_stats_loop_once(integration_context.session_factory, now=at_nine, **loop) == 0
        )
        at_eleven = at_nine.replace(hour=11)
        assert (
            await run_stats_loop_once(integration_context.session_factory, now=at_eleven, **loop)
            == 0
        )
        assert len(wechat.calls) == calls_before
        tomorrow = at_eleven + timedelta(days=1)
        assert (
            await run_stats_loop_once(integration_context.session_factory, now=tomorrow, **loop)
            == 1
        )

        # A failing account records the reason and retries the next day, not every loop.
        wechat.datacube_error = 48001
        day_after = tomorrow + timedelta(days=1)
        assert (
            await run_stats_loop_once(integration_context.session_factory, now=day_after, **loop)
            == 0
        )
        stats = (await editor.get(f"/api/v1/admin/wechat/accounts/{account_id}/stats")).json()
        assert "没有这个接口的权限" in stats["sync_error"]
        calls_before = len(wechat.calls)
        assert (
            await run_stats_loop_once(integration_context.session_factory, now=day_after, **loop)
            == 0
        )
        assert len(wechat.calls) == calls_before
        wechat.datacube_error = None


async def test_an_editor_picks_the_layout_template_the_draft_worker_uses(
    integration_context: IntegrationContext, wechat: FakeWeChat
) -> None:
    async with (
        _logged_in(integration_context, "owner") as owner,
        _logged_in(integration_context, "editor") as editor,
    ):
        account_id = await _bind(owner)
        listed = (await editor.get("/api/v1/admin/wechat/layout-templates")).json()
        assert [t["id"] for t in listed["templates"]] == [
            "xiaosai-blue",
            "jade-green",
            "warm-orange",
            "ink",
        ]
        assert listed["templates"][0]["is_default"] is True
        assert all(len(t["swatches"]) == 4 for t in listed["templates"])
        assert listed["accounts"] == [
            {"id": account_id, "name": "赛先生", "layout_template_id": "xiaosai-blue"}
        ]

        preview = await editor.get("/api/v1/admin/wechat/layout-templates/jade-green/preview")
        assert preview.status_code == 200
        assert "#0B7A64" in preview.json()["html"]
        assert "#0D57C8" not in preview.json()["html"]
        missing = await editor.get("/api/v1/admin/wechat/layout-templates/nope/preview")
        assert missing.status_code == 404

        unknown = await editor.put(
            f"/api/v1/admin/wechat/accounts/{account_id}/layout-template",
            json={"template_id": "nope"},
            headers=WRITE,
        )
        assert unknown.status_code == 422
        unguarded = await editor.put(
            f"/api/v1/admin/wechat/accounts/{account_id}/layout-template",
            json={"template_id": "jade-green"},
        )
        assert unguarded.status_code == 403
        chosen = await editor.put(
            f"/api/v1/admin/wechat/accounts/{account_id}/layout-template",
            json={"template_id": "jade-green"},
            headers=WRITE,
        )
        assert chosen.status_code == 200
        assert chosen.json()["layout_template_id"] == "jade-green"

    # The draft worker finds the choice by its account fingerprint.
    from app.domain.wechat_official_account_draft_jobs import wechat_draft_account_fingerprint
    from app.infrastructure.db.wechat_layout_templates import layout_template_for_account

    sessions = integration_context.session_factory
    assert (
        await layout_template_for_account(sessions, wechat_draft_account_fingerprint(APP_ID))
        == "jade-green"
    )
    assert await layout_template_for_account(sessions, "f" * 64) is None
    async with sessions() as session:
        audit = (
            await session.scalars(
                select(AdminAuditEventModel).where(
                    AdminAuditEventModel.action == "wechat_account.layout_template_set"
                )
            )
        ).all()
    assert [event.detail for event in audit] == [
        {"name": "赛先生", "from": "xiaosai-blue", "to": "jade-green", "template": "青绿"}
    ]
