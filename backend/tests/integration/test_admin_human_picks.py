"""人工加推 in the admin console: the signed-in account reviews, edits and pushes a held pick."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.api.v1.routes import admin_human_picks
from app.api_main import app
from app.application.services.human_pick_review import HumanPickCopyResult
from app.application.services.visitor_display import news_key
from app.domain.admin_auth import hash_password
from app.domain.human_pick_review import CopyRevision
from app.infrastructure.db.admin_auth import add_user
from app.infrastructure.db.models import (
    AdminAuditEventModel,
    AdminSessionModel,
    AdminUserModel,
    ContentSlotSelectionModel,
    MaterialPackageModel,
    MaterialReviewModel,
    WeComDeliveryJobModel,
)
from app.infrastructure.db.visitor_display import (
    PostgresVisitorDisplayRepository,
    VisitorNewsPoolBatch,
    VisitorNewsPoolCandidate,
)
from app.schemas.copy_generation import CopyIssue
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from .conftest import IntegrationContext
from .test_human_pick_review import EDITED, _held_pick, _purge_held_picks, _wecom_settings

__all__ = ["_purge_held_picks"]

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

PASSWORD = "editor-pass-2026"
WRITE = {"X-Admin-Request": "1"}


def _candidate(event_id: UUID) -> VisitorNewsPoolCandidate:
    return VisitorNewsPoolCandidate(
        event_id=event_id,
        title="夹具新闻",
        source_name="夹具",
        source_url="https://example.org/a",
        trust_tier="A",
        published_at=datetime(2026, 10, 15, tzinfo=UTC),
        snippet="夹具摘要。",
        total=0.41,
        threshold=0.59,
        passes_threshold=False,
        eligible=True,
        veto_codes=(),
        same_day_excluded=False,
        same_day_exclusion_reason=None,
        rank=4,
        selected_ordinal=None,
        normalized_features={"science_education_relevance": 0.9},
        weights={"science_education_relevance": 0.3},
        penalty_weights={},
    )


@pytest_asyncio.fixture(loop_scope="session")
async def editor(
    integration_context: IntegrationContext, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[str]:
    app.state.settings = _wecom_settings(integration_context)
    app.state.session_factory = integration_context.session_factory
    username = f"pck{uuid4().hex[:8]}"
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
    yield username
    async with integration_context.session_factory() as session:
        await session.execute(delete(AdminAuditEventModel))
        await session.execute(delete(AdminSessionModel))
        await session.execute(delete(AdminUserModel))
        await session.commit()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _login(client: AsyncClient, username: str) -> None:
    login = await client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": PASSWORD},
        headers=WRITE,
    )
    assert login.status_code == 200


async def test_an_editor_reviews_edits_and_pushes_a_held_pick(
    integration_context: IntegrationContext,
    editor: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The pick's deadline (22:30 on the day) is far in the future, so "now" is always before it.
    run_id, package_id, _, picked_at = await _held_pick(
        integration_context, target_at=datetime(2097, 4, 6, 23, 30, tzinfo=UTC)
    )
    async with integration_context.session_factory() as session:
        event_id = await session.scalar(
            select(ContentSlotSelectionModel.selected_event_id).where(
                ContentSlotSelectionModel.run_id == run_id
            )
        )
    assert event_id is not None
    key = news_key(event_id)
    batch = VisitorNewsPoolBatch(
        business_date=picked_at.date(),
        content_slot="morning",
        target_at=picked_at,
        total_scores=1,
        eligible_scores=1,
        selected_count=0,
        unfilled_reason_codes=(),
        candidates=(_candidate(event_id),),
        run_id=uuid4(),
    )

    async def load_news_pool(_self: PostgresVisitorDisplayRepository):  # type: ignore[no-untyped-def]
        return (batch,)

    monkeypatch.setattr(PostgresVisitorDisplayRepository, "load_news_pool", load_news_pool)

    seen: dict[str, Any] = {}

    async def fake_revise(session: Any, **kwargs: Any) -> HumanPickCopyResult:
        seen.update(kwargs)
        return HumanPickCopyResult(
            revision=CopyRevision(
                copywriting=EDITED,
                hook=kwargs["hook"],
                hashtags=kwargs["hashtags"],
                issues=(
                    CopyIssue(
                        code="copy_length",
                        message="引导句应为一句8到50个汉字的话",
                        severity="warning",
                        field="copywriting",
                    ),
                ),
            ),
            saved=not kwargs["dry_run"],
            push_deadline=picked_at + timedelta(days=1),
        )

    monkeypatch.setattr(admin_human_picks, "revise_human_pick_copy", fake_revise)

    base = f"/api/v1/admin/human-picks/{key}"
    async with _client() as anonymous, _client() as client:
        assert (await anonymous.get(f"{base}/review")).status_code == 401
        await _login(client, editor)

        review = await client.get(f"{base}/review")
        assert review.status_code == 200
        body = review.json()
        assert body["stage"] == "awaiting_review" and body["editable"] is True
        assert body["hook"] == "AI 写的引导语✨"
        assert body["heading"] == "🔎【小赛洞察】"

        pool = await client.get("/api/v1/admin/news-reviews")
        assert pool.json()["human_pick_enabled"] is True
        assert pool.json()["human_pick_review_enabled"] is True
        picks = [c["human_pick"] for b in pool.json()["batches"] for c in b["candidates"]]
        assert [p["stage"] for p in picks] == ["awaiting_review"]

        edit = {"hook": "运营改过的引导语🔧", "hashtags": ["#科学思维"], "dry_run": True}
        assert (await client.post(f"{base}/copy", json=edit)).status_code == 403
        checked = await client.post(f"{base}/copy", json=edit, headers=WRITE)
        assert checked.status_code == 200
        assert (checked.json()["passed"], checked.json()["saved"]) == (True, False)
        assert checked.json()["issues"][0]["code"] == "copy_length"
        # The signed-in account is the reviewer; nothing else is trusted from the request.
        assert seen["reviewer"] == editor and seen["run_id"] == run_id
        saved = await client.post(f"{base}/copy", json={**edit, "dry_run": False}, headers=WRITE)
        assert saved.json()["saved"] is True

        unknown = await client.post(f"/api/v1/admin/human-picks/vn1_{'0' * 24}/push", headers=WRITE)
        assert unknown.status_code == 404
        assert (await client.post(f"{base}/push")).status_code == 403

        pushed = await client.post(f"{base}/push", headers=WRITE)
        assert pushed.status_code == 200, pushed.text
        assert pushed.json()["stage"] == "sending"
        # A second press does not send twice.
        again = await client.post(f"{base}/push", headers=WRITE)
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "human_pick_already_pushed"

    async with integration_context.session_factory() as session:
        package = await session.get(MaterialPackageModel, package_id)
        assert package is not None
        assert (package.review_status, package.status) == ("approved", "completed")
        assert package.copy_snapshot["operator_push"]["reviewer"] == editor
        review_row = await session.scalar(
            select(MaterialReviewModel).where(MaterialReviewModel.package_id == package_id)
        )
        assert review_row is not None and review_row.reviewer == editor
        jobs = (
            await session.scalars(
                select(WeComDeliveryJobModel).where(
                    WeComDeliveryJobModel.material_package_id == package_id
                )
            )
        ).all()
        assert [(job.mode, job.include_copy, job.include_image) for job in jobs] == [
            ("formal", True, True)
        ]


async def test_creating_a_pick_needs_a_known_candidate_and_slot_mode(
    integration_context: IntegrationContext,
    editor: str,
) -> None:
    async with _client() as client:
        await _login(client, editor)
        body = {"key": f"vn1_{'1' * 24}"}
        assert (await client.post("/api/v1/admin/human-picks", json=body)).status_code == 403
        missing = await client.post("/api/v1/admin/human-picks", json=body, headers=WRITE)
        assert missing.status_code == 404
        app.state.settings = integration_context.settings.model_copy(
            update={"content_slot_mode_enabled": False}
        )
        disabled = await client.post("/api/v1/admin/human-picks", json=body, headers=WRITE)
        assert disabled.status_code == 422
        assert disabled.json()["error"]["code"] == "content_slot_disabled"
