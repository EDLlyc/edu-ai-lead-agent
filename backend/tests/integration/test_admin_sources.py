# ruff: noqa: RUF001
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from app.api_main import app
from app.domain.admin_auth import hash_password
from app.domain.enums import RunTrigger
from app.infrastructure.db.admin_auth import add_user
from app.infrastructure.db.models import (
    AcquisitionJobModel,
    AcquisitionRunModel,
    AdminAuditEventModel,
    AdminSessionModel,
    AdminUserModel,
    SourceModel,
    SourceVersionModel,
)
from app.infrastructure.db.repositories import claim_job, create_run, seed_sources
from app.infrastructure.ingestion.connectors import get_connector
from app.infrastructure.ingestion.fetcher import SafeHttpFetcher
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from .conftest import IntegrationContext

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

PASSWORD = "teacher-pass-2026"
WRITE = {"X-Admin-Request": "1"}
SITE = "https://edu.example.cn"
TODAY = datetime.now(UTC).strftime("%Y-%m-%d")
OLD = (datetime.now(UTC) - timedelta(days=40)).strftime("%Y-%m-%d")

LIST_PAGE = f"""<html><body>
<nav><a href="/about.html">关于我们</a></nav>
<ul class="list">
  <li><a href="/news/{TODAY}/content_101.htm">人工智能教育走进中小学课堂</a> {TODAY}</li>
  <li><a href="/news/{TODAY}/content_102.htm">明星演唱会门票今日开售</a> {TODAY}</li>
  <li><a href="/news/{OLD}/content_090.htm">我国科学家在量子计算领域取得重大突破</a> {OLD}</li>
  <li><a href="https://elsewhere.example.com/{TODAY}/x.html">外站文章</a></li>
</ul></body></html>"""

ARTICLES = {
    f"/news/{TODAY}/content_101.htm": (
        "人工智能教育走进中小学课堂",
        "教育部推动中小学开设人工智能课程，学生在科学课上动手搭建机器人，培养科学素养和创新能力。"
        * 3,
    ),
    f"/news/{TODAY}/content_102.htm": (
        "明星演唱会门票今日开售",
        "某明星全国巡回演唱会门票今日开售，粉丝热情高涨，多个城市场次迅速售罄。" * 3,
    ),
    f"/news/{OLD}/content_090.htm": (
        "我国科学家在量子计算领域取得重大突破",
        "中国科学院研究团队成功研制新型量子计算原型机，实现了关键技术突破，相关成果发表在国际期刊。"
        * 3,
    ),
}


def _site(robots: str | None = "User-agent: *\nAllow: /\n") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "moved.example.cn":
            return httpx.Response(301, headers={"location": "https://other.example.cn/news/"})
        if host != "edu.example.cn":
            return httpx.Response(404)
        if path == "/robots.txt":
            if robots is None:
                return httpx.Response(404)
            return httpx.Response(200, text=robots, headers={"content-type": "text/plain"})
        if path == "/news/":
            return httpx.Response(200, text=LIST_PAGE, headers={"content-type": "text/html"})
        if path in ARTICLES:
            title, body = ARTICLES[path]
            date = path.split("/")[2]
            html = (
                f"<html><head><title>{title}_示例教育网</title></head><body>"
                f"<h1>{title}</h1><p>发布时间：{date} 08:00</p><div class='body'>{body}</div>"
                "</body></html>"
            )
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def _resolver(host: str) -> list[str]:
    return ["10.0.0.8"] if host.startswith("intranet") else ["93.184.216.34"]


def _install(context: IntegrationContext, transport: httpx.MockTransport) -> None:
    app.state.source_admin_fetcher = SafeHttpFetcher(
        context.settings, resolver=_resolver, transport=transport
    )


async def _user(context: IntegrationContext, role: str) -> str:
    username = f"src{uuid4().hex[:10]}"
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
    async with integration_context.session_factory() as session:
        await seed_sources(session)
    app.state.settings = integration_context.settings
    app.state.session_factory = integration_context.session_factory
    _install(integration_context, _site())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        login = await http.post(
            "/api/v1/admin/auth/login",
            json={"username": await _user(integration_context, "editor"), "password": PASSWORD},
            headers=WRITE,
        )
        assert login.status_code == 200
        yield http
    app.state.source_admin_fetcher = None
    # Leave the shared test database as the seeds made it: later migration tests downgrade
    # past 0052/0053, which refuse operator sources and audit rows.
    async with integration_context.session_factory() as session:
        operator_ids = select(SourceModel.id).where(SourceModel.managed_by == "operator")
        run_ids = select(AcquisitionJobModel.run_id).where(
            AcquisitionJobModel.source_id.in_(operator_ids)
        )
        await session.execute(
            delete(AcquisitionJobModel).where(AcquisitionJobModel.run_id.in_(run_ids))
        )
        await session.execute(
            delete(AcquisitionRunModel).where(
                ~AcquisitionRunModel.id.in_(select(AcquisitionJobModel.run_id))
            )
        )
        await session.execute(
            update(SourceModel)
            .where(SourceModel.managed_by == "operator")
            .values(active_version_id=None)
        )
        await session.execute(
            delete(SourceVersionModel).where(SourceVersionModel.source_id.in_(operator_ids))
        )
        await session.execute(delete(SourceModel).where(SourceModel.managed_by == "operator"))
        await session.execute(
            update(SourceModel)
            .where(SourceModel.managed_by == "seed", SourceModel.active_version_id.is_not(None))
            .values(enabled=True, enabled_set_by="seed")
        )
        await session.execute(delete(AdminAuditEventModel))
        await session.execute(delete(AdminSessionModel))
        await session.execute(delete(AdminUserModel))
        await session.commit()


def _draft(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "display_name": "示例教育网",
        "organization_type": "authoritative_media",
        "tier": "B",
        "entry_url": f"{SITE}/news/",
        "config": {"kind": "html", "list_selectors": [".list"]},
    }
    body.update(changes)
    return body


async def _actions(context: IntegrationContext, target: str) -> list[str]:
    async with context.session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(AdminAuditEventModel.action)
                    .where(AdminAuditEventModel.target_id == target)
                    .order_by(AdminAuditEventModel.occurred_at)
                )
            ).all()
        )


async def test_preview_shows_what_would_be_kept_without_storing_anything(
    integration_context: IntegrationContext, client: AsyncClient
) -> None:
    async with integration_context.session_factory() as session:
        before = len((await session.scalars(select(SourceModel.id))).all())

    response = await client.post(
        "/api/v1/admin/sources/preview",
        json={"entry_url": f"{SITE}/news/", "config": {"kind": "html"}},
        headers=WRITE,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["robots"] == "allowed"
    assert [link["title"] for link in body["links"]] == [
        "人工智能教育走进中小学课堂",
        "明星演唱会门票今日开售",
        "我国科学家在量子计算领域取得重大突破",
    ]
    samples = {sample["title"]: sample for sample in body["samples"]}
    assert samples["人工智能教育走进中小学课堂"]["relevant"] is True
    assert samples["人工智能教育走进中小学课堂"]["topic"] == "education"
    assert samples["人工智能教育走进中小学课堂"]["freshness"] == "fresh"
    assert samples["明星演唱会门票今日开售"]["relevant"] is False
    assert samples["我国科学家在量子计算领域取得重大突破"]["freshness"] == "stale"
    assert all(sample["characters"] > 80 for sample in body["samples"])

    async with integration_context.session_factory() as session:
        after = len((await session.scalars(select(SourceModel.id))).all())
    assert after == before
    assert await _actions(integration_context, "edu.example.cn") == ["source.previewed"]


@pytest.mark.parametrize(
    ("entry_url", "robots", "problem"),
    [
        (f"{SITE}/news/", "User-agent: *\nDisallow: /news/\n", "robots.txt 不允许"),
        ("https://intranet.example.cn/news/", None, "内网"),
        ("https://moved.example.cn/news/", None, "跳转到了别的域名"),
        (f"{SITE}/missing/", None, "返回错误 404"),
    ],
)
async def test_preview_explains_why_a_site_cannot_be_used(
    integration_context: IntegrationContext,
    client: AsyncClient,
    entry_url: str,
    robots: str | None,
    problem: str,
) -> None:
    _install(integration_context, _site(robots))
    try:
        response = await client.post(
            "/api/v1/admin/sources/preview",
            json={"entry_url": entry_url, "config": {"kind": "html"}},
            headers=WRITE,
        )
    finally:
        _install(integration_context, _site())
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert problem in response.json()["problem"]


async def test_preview_refuses_a_private_or_plain_http_address(client: AsyncClient) -> None:
    for url in ["http://edu.example.cn/news/", "https://10.0.0.8/", "https://localhost/news/"]:
        response = await client.post(
            "/api/v1/admin/sources/preview",
            json={"entry_url": url, "config": {"kind": "html"}},
            headers=WRITE,
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "source_config_invalid"


async def test_an_operator_source_is_added_off_edited_as_versions_and_archived(
    integration_context: IntegrationContext, client: AsyncClient
) -> None:
    assert (await client.post("/api/v1/admin/sources", json=_draft())).status_code == 403

    created = await client.post("/api/v1/admin/sources", json=_draft(), headers=WRITE)
    assert created.status_code == 201
    source = created.json()
    assert source["managed_by"] == "operator"
    assert source["enabled"] is False
    assert source["kind"] == "html"
    assert source["version"] == 1
    assert source["robots_status"] == "allowed"
    assert source["config"]["list_selectors"] == [".list"]
    source_id = source["id"]

    renamed = await client.patch(
        f"/api/v1/admin/sources/{source_id}",
        json=_draft(display_name="示例教育网（新闻）"),
        headers=WRITE,
    )
    assert renamed.json()["display_name"] == "示例教育网（新闻）"
    assert renamed.json()["version"] == 1

    narrowed = _draft(
        display_name="示例教育网（新闻）",
        config={"kind": "html", "list_selectors": [".list"], "link_contains": ["content_1"]},
    )
    edited = await client.patch(f"/api/v1/admin/sources/{source_id}", json=narrowed, headers=WRITE)
    assert edited.json()["version"] == 2
    reverted = await client.patch(
        f"/api/v1/admin/sources/{source_id}",
        json=_draft(display_name="示例教育网（新闻）"),
        headers=WRITE,
    )
    # Going back to earlier settings reuses that immutable version.
    assert reverted.json()["version"] == 1
    async with integration_context.session_factory() as session:
        versions = (
            await session.scalars(
                select(SourceVersionModel.version).where(
                    SourceVersionModel.source_id == UUID(source_id)
                )
            )
        ).all()
    assert sorted(versions) == [1, 2]

    enabled = await client.post(f"/api/v1/admin/sources/{source_id}/enable", headers=WRITE)
    assert enabled.json()["enabled"] is True

    assert (
        await client.delete(f"/api/v1/admin/sources/{source_id}", headers=WRITE)
    ).status_code == 204
    listed = await client.get("/api/v1/admin/sources")
    assert source_id not in {item["id"] for item in listed.json()["items"]}
    archived = await client.get("/api/v1/admin/sources", params={"include_archived": "true"})
    item = next(item for item in archived.json()["items"] if item["id"] == source_id)
    assert item["archived_at"] is not None
    assert item["enabled"] is False
    refused = await client.post(f"/api/v1/admin/sources/{source_id}/enable", headers=WRITE)
    assert refused.status_code == 409

    assert await _actions(integration_context, source_id) == [
        "source.created",
        "source.updated",
        "source.updated",
        "source.updated",
        "source.enabled",
        "source.archived",
    ]


async def test_creating_a_source_rechecks_robots(
    integration_context: IntegrationContext, client: AsyncClient
) -> None:
    _install(integration_context, _site("User-agent: *\nDisallow: /\n"))
    try:
        response = await client.post("/api/v1/admin/sources", json=_draft(), headers=WRITE)
    finally:
        _install(integration_context, _site())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "source_robots_disallowed"


async def test_a_seed_source_can_only_be_switched_and_the_switch_survives_seeding(
    integration_context: IntegrationContext, client: AsyncClient
) -> None:
    listed = await client.get("/api/v1/admin/sources")
    assert listed.status_code == 200
    seeds = [item for item in listed.json()["items"] if item["managed_by"] == "seed"]
    assert len(seeds) == 10
    assert {item["kind"] for item in seeds} == {"code"}
    target = seeds[0]["id"]

    assert (
        await client.patch(f"/api/v1/admin/sources/{target}", json=_draft(), headers=WRITE)
    ).status_code == 409
    assert (
        await client.delete(f"/api/v1/admin/sources/{target}", headers=WRITE)
    ).status_code == 409

    disabled = await client.post(f"/api/v1/admin/sources/{target}/disable", headers=WRITE)
    assert disabled.json()["enabled"] is False
    async with integration_context.session_factory() as session:
        await seed_sources(session)
    after_deploy = await client.get("/api/v1/admin/sources")
    item = next(item for item in after_deploy.json()["items"] if item["id"] == target)
    assert item["enabled"] is False

    assert (await client.post(f"/api/v1/admin/sources/{target}/enable", headers=WRITE)).json()[
        "enabled"
    ] is True
    assert await _actions(integration_context, target) == ["source.disabled", "source.enabled"]


async def test_the_worker_fetches_an_operator_source_with_its_own_settings(
    integration_context: IntegrationContext, client: AsyncClient
) -> None:
    rss = {"kind": "rss", "content_selectors": [".body"]}
    created = await client.post(
        "/api/v1/admin/sources",
        json=_draft(display_name="示例 RSS", entry_url=f"{SITE}/feed.xml", config=rss),
        headers=WRITE,
    )
    source_id = UUID(created.json()["id"])
    await client.post(f"/api/v1/admin/sources/{source_id}/enable", headers=WRITE)

    async with integration_context.session_factory() as session:
        run, created_run = await create_run(
            session,
            trigger=RunTrigger.MANUAL,
            timezone="Asia/Shanghai",
            acquisition_version="admin-sources-test",
            manual_idempotency_key=f"admin-sources-{uuid4()}",
            source_ids=[source_id],
        )
        assert created_run
    async with integration_context.session_factory() as session:
        claimed = await claim_job(session, worker_id="test-worker", lease_seconds=60)
    assert claimed is not None
    assert claimed.profile.source_id == source_id
    assert claimed.profile.connector_key == "generic_rss_v1"
    assert claimed.profile.connector_config == {
        "kind": "rss",
        "link_contains": [],
        "content_selectors": [".body"],
        "list_selectors": [],
    }
    assert claimed.profile.allowed_hosts == ("edu.example.cn",)
    get_connector(claimed.profile.connector_key, claimed.profile.connector_config)
    assert run.total_jobs == 1
