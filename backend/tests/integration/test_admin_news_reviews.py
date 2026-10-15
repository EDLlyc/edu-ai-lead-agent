from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from app.api_main import app
from app.application.services.visitor_display import news_key
from app.domain.admin_auth import hash_password
from app.infrastructure.db.admin_auth import add_user
from app.infrastructure.db.models import (
    AdminAuditEventModel,
    AdminSessionModel,
    AdminUserModel,
    NewsReviewModel,
)
from app.infrastructure.db.news_reviews import PostgresNewsReviewStore
from app.infrastructure.db.visitor_display import (
    PostgresVisitorDisplayRepository,
    VisitorNewsPoolBatch,
    VisitorNewsPoolCandidate,
)
from app.infrastructure.visitor_review_store import NewsReviewSubject
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from .conftest import IntegrationContext

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

PASSWORD = "editor-pass-2026"
WRITE = {"X-Admin-Request": "1"}
NOW = datetime(2026, 10, 15, 1, 0, tzinfo=UTC)


def _candidate(*, selected: bool) -> VisitorNewsPoolCandidate:
    return VisitorNewsPoolCandidate(
        event_id=uuid4(),
        title="教育部部署人工智能通识教育" if selected else "某地举办科技嘉年华",
        source_name="教育部",
        source_url="https://www.moe.gov.cn/news/1.html",
        trust_tier="A",
        published_at=NOW,
        snippet="教育部近日印发通知。",
        total=0.71 if selected else 0.41,
        threshold=0.59,
        passes_threshold=selected,
        eligible=True,
        veto_codes=(),
        same_day_excluded=False,
        same_day_exclusion_reason=None,
        rank=1 if selected else 5,
        selected_ordinal=1 if selected else None,
        normalized_features={"science_education_relevance": 0.9},
        weights={"science_education_relevance": 0.3},
        penalty_weights={},
    )


@pytest_asyncio.fixture(loop_scope="session")
async def editor(
    integration_context: IntegrationContext, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[str, tuple[VisitorNewsPoolCandidate, VisitorNewsPoolCandidate]]]:
    app.state.settings = integration_context.settings
    app.state.session_factory = integration_context.session_factory
    picked, dropped = _candidate(selected=True), _candidate(selected=False)
    batch = VisitorNewsPoolBatch(
        business_date=date(2026, 10, 15),
        content_slot="morning",
        target_at=NOW,
        total_scores=2,
        eligible_scores=2,
        selected_count=1,
        unfilled_reason_codes=(),
        candidates=(picked, dropped),
    )

    async def load_news_pool(_self: PostgresVisitorDisplayRepository):  # type: ignore[no-untyped-def]
        return (batch,)

    monkeypatch.setattr(PostgresVisitorDisplayRepository, "load_news_pool", load_news_pool)
    username = f"edt{uuid4().hex[:8]}"
    async with integration_context.session_factory() as session:
        await add_user(
            session,
            username=username,
            display_name="编辑",
            role="editor",
            password_hash=hash_password(PASSWORD),
            now=datetime.now(UTC),
        )
        await session.commit()
    yield username, (picked, dropped)
    async with integration_context.session_factory() as session:
        await session.execute(delete(NewsReviewModel))
        await session.execute(delete(AdminAuditEventModel))
        await session.execute(delete(AdminSessionModel))
        await session.execute(delete(AdminUserModel))
        await session.commit()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_an_editor_reviews_the_ai_picks_and_the_pool_shows_the_latest_call(
    integration_context: IntegrationContext,
    editor: tuple[str, tuple[VisitorNewsPoolCandidate, VisitorNewsPoolCandidate]],
) -> None:
    username, (picked, dropped) = editor
    async with _client() as anonymous, _client() as client:
        assert (await anonymous.get("/api/v1/admin/news-reviews")).status_code == 401
        login = await client.post(
            "/api/v1/admin/auth/login",
            json={"username": username, "password": PASSWORD},
            headers=WRITE,
        )
        assert login.status_code == 200

        pool = await client.get("/api/v1/admin/news-reviews")
        assert pool.status_code == 200
        assert pool.json()["review_enabled"] is True
        assert pool.json()["human_pick_enabled"] is False
        keys = [item["key"] for item in pool.json()["batches"][0]["candidates"]]
        assert keys == [news_key(picked.event_id), news_key(dropped.event_id)]

        body = {"key": news_key(dropped.event_id), "decision": "include", "note": "对家长有用"}
        assert (await client.post("/api/v1/admin/news-reviews", json=body)).status_code == 403
        first = await client.post("/api/v1/admin/news-reviews", json=body, headers=WRITE)
        assert first.status_code == 200
        assert first.json()["decision"] == "include"
        # The latest call per item wins.
        second = await client.post(
            "/api/v1/admin/news-reviews",
            json={"key": news_key(dropped.event_id), "decision": "exclude"},
            headers=WRITE,
        )
        assert second.json()["decision"] == "exclude"

        unknown = await client.post(
            "/api/v1/admin/news-reviews",
            json={"key": "vn1_" + "0" * 24, "decision": "agree"},
            headers=WRITE,
        )
        assert unknown.status_code == 404
        bad = await client.post(
            "/api/v1/admin/news-reviews",
            json={"key": news_key(picked.event_id), "decision": "maybe"},
            headers=WRITE,
        )
        assert bad.status_code == 422

        pool = await client.get("/api/v1/admin/news-reviews")
        by_key = {c["key"]: c for b in pool.json()["batches"] for c in b["candidates"]}
        assert by_key[news_key(dropped.event_id)]["human_review"]["decision"] == "exclude"
        assert by_key[news_key(picked.event_id)]["human_review"] is None

    async with integration_context.session_factory() as session:
        rows = (await session.scalars(select(NewsReviewModel).order_by(NewsReviewModel.id))).all()
    assert [(r.decision, r.reviewer, r.ai_verdict) for r in rows] == [
        ("include", username, "rejected"),
        ("exclude", username, "rejected"),
    ]
    assert rows[0].note == "对家长有用"
    assert rows[0].title == dropped.title and rows[0].ai_score == pytest.approx(0.41)


async def test_the_store_counts_agreement_and_overrides_per_local_day(
    integration_context: IntegrationContext,
) -> None:
    store = PostgresNewsReviewStore(integration_context.session_factory)
    day = date(2026, 10, 15)

    def subject(verdict: str) -> NewsReviewSubject:
        return NewsReviewSubject(
            title="t", source_name=None, ai_verdict=verdict, business_date=day, slot="morning"
        )

    try:
        for key, decision, verdict in (
            ("vn1_" + "a" * 24, "agree", "selected"),
            ("vn1_" + "b" * 24, "include", "rejected"),
            ("vn1_" + "c" * 24, "exclude", "selected"),
            ("vn1_" + "c" * 24, "agree", "selected"),  # the day's last call on c wins
        ):
            await store.record(
                key=key,
                decision=decision,
                note=None,
                subject=subject(verdict),
                now=NOW,
                reviewer="someone",
            )
        assert await store.daily_decisions((day,), timezone="Asia/Shanghai") == {
            day: {"agree": 2, "include_override": 1, "exclude_override": 0}
        }
        assert await store.daily_counts((day,), timezone="Asia/Shanghai") == {day: (3, 1)}
        with pytest.raises(ValueError, match="reviewer"):
            await store.record(
                key="vn1_" + "d" * 24, decision="agree", note=None, subject=subject("selected")
            )
    finally:
        async with integration_context.session_factory() as session:
            await session.execute(delete(NewsReviewModel))
            await session.commit()
