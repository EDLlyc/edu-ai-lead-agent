"""Statistics regressions use fake WeChat only, with real PostgreSQL persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.api_main import app
from app.application.services.wechat_admin import WeChatAdminRejected
from app.application.services.wechat_stats import business_today, sync_account_stats
from app.infrastructure.db.models import WeChatAccountDailyStatsModel, WeChatAccountModel
from sqlalchemy import delete, select

from .conftest import IntegrationContext
from .test_admin_wechat import FakeWeChat, _bind, _logged_in
from .test_admin_wechat import wechat as wechat

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


async def test_ten_day_outage_and_older_gap_are_recovered_without_network_transactions(
    integration_context: IntegrationContext, wechat: FakeWeChat
) -> None:
    now = datetime.now(UTC)
    today = business_today(app.state.settings, now)
    last_success = today - timedelta(days=10)
    async with _logged_in(integration_context, "owner") as owner:
        account_id = UUID(await _bind(owner))
    sessions = integration_context.session_factory
    async with sessions() as session:
        await sync_account_stats(
            session,
            settings=app.state.settings,
            http=app.state.wechat_http,
            account_id=account_id,
            today=last_success,
            now=now - timedelta(days=10),
        )
        missing = today - timedelta(days=20)
        await session.execute(
            delete(WeChatAccountDailyStatsModel).where(
                WeChatAccountDailyStatsModel.account_id == account_id,
                WeChatAccountDailyStatsModel.ref_date == missing,
            )
        )
        await session.commit()
        calls: dict[str, list[str]] = {"article": [], "account": []}

        def handler(request: httpx.Request) -> httpx.Response:
            assert not session.in_transaction(), "Provider I/O must not hold a database transaction"
            body = json.loads(request.content)
            if request.url.path.startswith("/datacube/"):
                kind = "article" if "article" in request.url.path else "account"
                calls[kind].append(body["begin_date"])
            return wechat.handler(request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            report = await sync_account_stats(
                session,
                settings=app.state.settings,
                http=http,
                account_id=account_id,
                today=today,
                now=now,
            )
        expected = {str(today - timedelta(days=back)) for back in range(1, 11)} | {str(missing)}
        assert set(calls["account"]) == expected and set(calls["article"]) == expected
        assert report.days == 11
        dates = set(
            await session.scalars(
                select(WeChatAccountDailyStatsModel.ref_date).where(
                    WeChatAccountDailyStatsModel.account_id == account_id,
                    WeChatAccountDailyStatsModel.ref_date >= today - timedelta(days=30),
                )
            )
        )
        assert dates == {today - timedelta(days=back) for back in range(1, 31)}
        account = await session.get(WeChatAccountModel, account_id)
        assert account is not None and account.stats_synced_on == today


async def test_failed_catchup_keeps_success_watermark_and_prior_rows_for_retry(
    integration_context: IntegrationContext, wechat: FakeWeChat
) -> None:
    now = datetime.now(UTC)
    today = business_today(app.state.settings, now)
    previous = today - timedelta(days=10)
    async with _logged_in(integration_context, "owner") as owner:
        account_id = UUID(await _bind(owner))
    async with integration_context.session_factory() as session:
        await sync_account_stats(
            session,
            settings=app.state.settings,
            http=app.state.wechat_http,
            account_id=account_id,
            today=previous,
            now=now - timedelta(days=10),
        )
        should_fail = True

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            if (
                should_fail
                and request.url.path == "/datacube/getbizsummary"
                and body["begin_date"] == str(today - timedelta(days=3))
            ):
                return httpx.Response(200, json={"errcode": 48001, "errmsg": "not permitted"})
            return wechat.handler(request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(WeChatAdminRejected):
                await sync_account_stats(
                    session,
                    settings=app.state.settings,
                    http=http,
                    account_id=account_id,
                    today=today,
                    now=now,
                )
            account = await session.get(WeChatAccountModel, account_id)
            assert account is not None and account.stats_synced_on == previous
            assert account.stats_sync_error is not None
            saved = list(
                await session.scalars(
                    select(WeChatAccountDailyStatsModel.ref_date).where(
                        WeChatAccountDailyStatsModel.account_id == account_id,
                    )
                )
            )
            assert max(saved) == previous - timedelta(days=1)
            should_fail = False
            report = await sync_account_stats(
                session,
                settings=app.state.settings,
                http=http,
                account_id=account_id,
                today=today,
                now=now + timedelta(minutes=1),
            )
            assert report.days == 10
            refreshed = await session.get(WeChatAccountModel, account_id)
            assert refreshed is not None and refreshed.stats_synced_on == today
            assert refreshed.stats_sync_error is None


async def test_stats_response_distinguishes_missing_and_zero_and_excludes_future_dates(
    integration_context: IntegrationContext, wechat: FakeWeChat
) -> None:
    now = datetime.now(UTC)
    today = business_today(app.state.settings, now)
    yesterday = today - timedelta(days=1)
    missing = today - timedelta(days=2)
    malformed = today - timedelta(days=3)
    async with _logged_in(integration_context, "owner") as owner:
        account_id = UUID(await _bind(owner))

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            if request.url.path == "/datacube/getbizsummary":
                day = body["begin_date"]
                if day == str(missing):
                    return httpx.Response(200, json={"list": []})
                if day in {str(yesterday), str(malformed)}:
                    return httpx.Response(
                        200,
                        json={
                            "list": [
                                {
                                    "ref_date": day,
                                    "detail": {
                                        "read_user": 0 if day == str(yesterday) else "unknown"
                                    },
                                }
                            ]
                        },
                    )
            return wechat.handler(request)

        async with integration_context.session_factory() as session:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                report = await sync_account_stats(
                    session,
                    settings=app.state.settings,
                    http=http,
                    account_id=account_id,
                    today=today,
                    now=now,
                )
                assert report.days == 28
            # Today/future artifacts must never leak into yesterday's calendar interval.
            for future in (today, today + timedelta(days=1)):
                session.add(
                    WeChatAccountDailyStatsModel(
                        id=uuid4(),
                        account_id=account_id,
                        ref_date=future,
                        read_user=9999,
                        share_user=0,
                        like_user=0,
                        zaikan_user=0,
                        comment_count=0,
                        collection_user=0,
                        redirect_ori_page_user=0,
                        send_page_count=0,
                        read_sources={},
                        fetched_at=now,
                    )
                )
            await session.commit()
        response = await owner.get(f"/api/v1/admin/wechat/accounts/{account_id}/stats")
        assert response.status_code == 200
        stats: dict[str, Any] = response.json()
        assert stats["range_start"] == str(today - timedelta(days=30))
        assert stats["range_end"] == str(yesterday)
        assert stats["missing_dates"] == [str(malformed), str(missing)]
        assert all(stats["range_start"] <= row["date"] <= str(yesterday) for row in stats["daily"])
        assert (
            next(row for row in stats["daily"] if row["date"] == str(yesterday))["read_user"] == 0
        )
