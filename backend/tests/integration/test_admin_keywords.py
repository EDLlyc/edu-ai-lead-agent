from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.api_main import app
from app.application.ports.content_slots import GovernedSlotLineage
from app.application.services import keyword_admin
from app.domain.admin_auth import hash_password
from app.domain.content_slots import ContentSlot, ContentSlotSchedule, SlotRankingPolicy
from app.domain.topic_selection import TopicScoringConfig
from app.infrastructure.db.admin_auth import add_user
from app.infrastructure.db.content_slot_human_picks import create_human_pick
from app.infrastructure.db.content_slots import (
    enqueue_content_slot_run,
    load_content_slot_candidates,
)
from app.infrastructure.db.models import (
    AdminAuditEventModel,
    AdminSessionModel,
    AdminUserModel,
    ContentSlotJobModel,
    ContentSlotRunModel,
    ContentSlotSelectionModel,
    CopyGenerationRunModel,
    EventClusterVersionModel,
    OperatorKeywordVersionModel,
)
from app.infrastructure.db.operator_keywords import (
    RecentCandidate,
    copy_banned_terms_for_copy_run,
    load_active_keyword_row,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from .conftest import IntegrationContext
from .test_content_slot_human_picks import _add_rejected_candidate, _scheduled_run_id
from .test_wecom_slot_delivery_concurrency import _seed_slot_delivery_lane

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

PASSWORD = "teacher-pass-2026"
WRITE = {"X-Admin-Request": "1"}


@pytest_asyncio.fixture(loop_scope="session")
async def client(integration_context: IntegrationContext) -> AsyncIterator[AsyncClient]:
    username = f"kw{uuid4().hex[:10]}"
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
    # Later migration tests downgrade past 0052/0054, which refuse keyword versions and audit rows.
    async with integration_context.session_factory() as session:
        await session.execute(
            update(ContentSlotRunModel)
            .where(ContentSlotRunModel.operator_keyword_version_id.is_not(None))
            .values(operator_keyword_version_id=None)
        )
        await session.execute(delete(OperatorKeywordVersionModel))
        await session.execute(delete(AdminAuditEventModel))
        await session.execute(delete(AdminSessionModel))
        await session.execute(delete(AdminUserModel))
        await session.commit()


async def _save(client: AsyncClient, **body: object) -> object:
    return await client.post("/api/v1/admin/keywords", json=body, headers=WRITE)


async def test_each_save_is_a_new_audited_version_and_old_ones_can_be_read(
    integration_context: IntegrationContext, client: AsyncClient
) -> None:
    empty = await client.get("/api/v1/admin/keywords")
    assert empty.status_code == 200
    assert empty.json() == {"current": None, "history": []}
    assert (await client.post("/api/v1/admin/keywords", json={})).status_code == 403

    first = await client.post(
        "/api/v1/admin/keywords",
        json={
            "focus": ["人工智能", " 机器人 "],
            "block": ["彩票"],
            "copy_banned": ["保证提分"],
            "note": "第一版",
        },
        headers=WRITE,
    )
    assert first.status_code == 200
    current = first.json()["current"]
    assert current["version"] == 1
    assert current["focus"] == ["人工智能", "机器人"]
    assert current["created_by"].startswith("kw")

    same = await client.post(
        "/api/v1/admin/keywords",
        json={"focus": ["人工智能", "机器人"], "block": ["彩票"], "copy_banned": ["保证提分"]},
        headers=WRITE,
    )
    assert same.status_code == 409
    conflict = await client.post(
        "/api/v1/admin/keywords",
        json={"focus": ["彩票"], "block": ["彩票"]},
        headers=WRITE,
    )
    assert conflict.status_code == 422
    assert conflict.json()["error"]["code"] == "keyword_list_invalid"

    second = await client.post(
        "/api/v1/admin/keywords",
        json={"focus": ["人工智能", "科学营"], "block": [], "copy_banned": ["保证提分"]},
        headers=WRITE,
    )
    assert [item["version"] for item in second.json()["history"]] == [2, 1]
    assert second.json()["history"][1]["note"] == "第一版"
    old = await client.get("/api/v1/admin/keywords/versions/1")
    assert old.json()["block"] == ["彩票"]
    assert (await client.get("/api/v1/admin/keywords/versions/9")).status_code == 404

    async with integration_context.session_factory() as session:
        details = (
            await session.scalars(
                select(AdminAuditEventModel.detail)
                .where(AdminAuditEventModel.action == "keywords.saved")
                .order_by(AdminAuditEventModel.occurred_at)
            )
        ).all()
    assert details[-1]["changes"] == {
        "focus": {"added": ["科学营"], "removed": ["机器人"]},
        "block": {"added": [], "removed": ["彩票"]},
    }


async def test_blocking_a_large_share_of_recent_candidates_needs_confirmation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    recent = [
        RecentCandidate(UUID(int=1), "彩票中奖新规", "", selected=True),
        RecentCandidate(UUID(int=2), "体育彩票销售", "", selected=False),
        RecentCandidate(UUID(int=3), "机器人进课堂", "", selected=False),
        RecentCandidate(UUID(int=4), "量子计算突破", "", selected=False),
    ]

    async def fake_recent(_session: object, *, now: datetime, days: int) -> list[RecentCandidate]:
        del now, days
        return recent

    monkeypatch.setattr(keyword_admin, "recent_slot_candidates", fake_recent)

    impact = await client.post(
        "/api/v1/admin/keywords/impact",
        json={"focus": ["机器人"], "block": ["彩票"]},
        headers=WRITE,
    )
    assert impact.status_code == 200
    body = impact.json()
    assert body["candidate_count"] == 4
    assert body["blocked_count"] == 2
    assert body["blocked_selected_count"] == 1
    assert body["wide"] is True
    assert body["blocked"][0] == {"title": "彩票中奖新规", "terms": ["彩票"], "selected": True}
    assert body["focused"] == [{"title": "机器人进课堂", "terms": ["机器人"]}]

    refused = await client.post("/api/v1/admin/keywords", json={"block": ["彩票"]}, headers=WRITE)
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "keyword_block_too_wide"
    assert "50%" in refused.json()["error"]["message"]
    confirmed = await client.post(
        "/api/v1/admin/keywords",
        json={"block": ["彩票"], "confirm_wide_block": True},
        headers=WRITE,
    )
    assert confirmed.status_code == 200


async def test_slot_runs_use_the_keyword_version_in_force_when_they_were_created(
    integration_context: IntegrationContext, client: AsyncClient
) -> None:
    target_at = datetime(2097, 5, 6, 23, 30, tzinfo=UTC)
    _window, _jobs, business_date, profile = await _seed_slot_delivery_lane(
        integration_context, target_at=target_at
    )
    base_run_id = await _scheduled_run_id(integration_context, business_date)

    saved = await client.post(
        "/api/v1/admin/keywords",
        json={
            "focus": ["fixture 2"],
            "block": ["Fixture 3"],
            "copy_banned": ["保证提分"],
            "confirm_wide_block": True,
        },
        headers=WRITE,
    )
    assert saved.status_code == 200

    async with integration_context.session_factory() as session:
        active = await load_active_keyword_row(session)
        assert active is not None
        base = await session.get(ContentSlotRunModel, base_run_id)
        assert base is not None
        # The lane fixture writes its run directly; record the version as the scheduler would.
        base.operator_keyword_version_id = active.id
        await session.commit()

        candidates = await load_content_slot_candidates(session, base_run_id)
        titles = {
            version.id: version.representative_title
            for version in (
                await session.scalars(
                    select(EventClusterVersionModel).where(
                        EventClusterVersionModel.id.in_(
                            [candidate.event_version_id for candidate in candidates]
                        )
                    )
                )
            ).all()
        }
        hits = {
            titles[candidate.event_version_id]: (
                candidate.operator_focus_terms,
                candidate.operator_block_terms,
            )
            for candidate in candidates
            if titles.get(candidate.event_version_id, "").startswith("Slot delivery fixture")
        }
        assert hits["Slot delivery fixture 2"] == (("fixture 2",), ())
        assert hits["Slot delivery fixture 3"] == ((), ("Fixture 3",))
        assert hits["Slot delivery fixture 1"] == ((), ())

        copy_run = await session.scalar(
            select(CopyGenerationRunModel)
            .join(
                ContentSlotSelectionModel,
                ContentSlotSelectionModel.id == CopyGenerationRunModel.content_slot_selection_id,
            )
            .where(ContentSlotSelectionModel.run_id == base_run_id)
            .limit(1)
        )
        assert copy_run is not None
        assert await copy_banned_terms_for_copy_run(session, copy_run) == ("保证提分",)

    # A human pick inherits the version of the run it was picked from.
    event_id = await _add_rejected_candidate(
        integration_context, run_id=base_run_id, rank=4, veto=True
    )
    async with integration_context.session_factory() as session:
        pick = await create_human_pick(
            session,
            source_run_id=base_run_id,
            event_id=event_id,
            note="关键词测试",
            now=target_at + timedelta(hours=1),
            timezone="Asia/Shanghai",
            scoring_profile=profile,
        )
        assert pick.run.operator_keyword_version_id == active.id

    # The scheduler path: a new run records the active version once; later edits do not touch it.
    async with integration_context.session_factory() as session:
        base = await session.get(ContentSlotRunModel, base_run_id)
        assert base is not None
        lineage = GovernedSlotLineage(
            acquisition_run_id=base.acquisition_run_id,
            governance_run_id=base.governance_run_id,
            governed_event_cutoff=base.governed_event_cutoff,
        )
        arguments = {
            "business_date": business_date,
            "timezone": "Asia/Shanghai",
            "schedule": ContentSlotSchedule(
                slot=ContentSlot.MORNING,
                enabled=True,
                target_hour=7,
                target_minute=30,
                max_items=2,
            ),
            "config": TopicScoringConfig(
                profile=f"keywords-{uuid4().hex[:10]}",
                version="scoring-v1-preview.6-tiered-science-tech-priority",
            ),
            "policy": SlotRankingPolicy(),
            "lineage": lineage,
            "trigger": "manual",
        }
        run, created = await enqueue_content_slot_run(session, **arguments)  # type: ignore[arg-type]
        assert created
        assert run.operator_keyword_version_id == active.id
        run_id = run.id

    later = await client.post(
        "/api/v1/admin/keywords",
        json={"focus": ["fixture 1"], "confirm_wide_block": True},
        headers=WRITE,
    )
    assert later.status_code == 200
    async with integration_context.session_factory() as session:
        again, created_again = await enqueue_content_slot_run(session, **arguments)  # type: ignore[arg-type]
        assert not created_again
        assert again.id == run_id
        assert again.operator_keyword_version_id == active.id
        # Leave no queued job behind for other tests' slot workers to claim.
        await session.execute(
            delete(ContentSlotJobModel).where(ContentSlotJobModel.run_id == run_id)
        )
        await session.execute(delete(ContentSlotRunModel).where(ContentSlotRunModel.id == run_id))
        await session.commit()

    # The impact check reads real recent slot candidates.
    impact = await client.post(
        "/api/v1/admin/keywords/impact",
        json={"focus": [], "block": ["delivery fixture"]},
        headers=WRITE,
    )
    assert impact.json()["blocked_count"] >= 3
