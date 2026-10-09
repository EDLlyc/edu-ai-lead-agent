# ruff: noqa: RUF001
"""公众号 数据: daily sync of WeChat reading statistics into the 运营后台.

WeChat facts (production probe 2026-10-09):
- The old datacube article APIs are offline (47009).
- `getarticletotaldetail` takes one publish date per call. It returns the articles sent that day,
  each with a `detail_list` of cumulative numbers per `stat_date`.
- The read sources include a `全部` scene, which is the total; the other scenes overlap it.
- `getbizsummary` gives account-wide numbers for one day.

The sync keeps the latest cumulative snapshot per article and one row per account day:
- a first sync goes back 30 days;
- later syncs refresh the last 7 publish dates and the last 3 account days.
The API loop runs it once per business day after 10:00. An operator can also start it, at
most once every 5 minutes per account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from time import monotonic
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.services.admin_auth import AdminPrincipal
from app.application.services.wechat_admin import (
    WeChatAdminRejected,
    account_client,
    wechat_call_error,
)
from app.core.config import Settings
from app.infrastructure.db.admin_auth import add_audit_event
from app.infrastructure.db.models import (
    WeChatAccountDailyStatsModel,
    WeChatAccountModel,
    WeChatArticleStatsModel,
)
from app.infrastructure.wechat_official_account.admin_client import WeChatAdminError

FIRST_SYNC_DAYS = 30
ARTICLE_REFRESH_DAYS = 7
ACCOUNT_REFRESH_DAYS = 3
SYNC_AFTER_LOCAL_HOUR = 10
MANUAL_SYNC_GAP_SECONDS = 300
_TOTAL_SCENE = "全部"
_LAST_MANUAL: dict[UUID, float] = {}


@dataclass(frozen=True, slots=True)
class SyncReport:
    articles: int
    days: int


def _int(value: Any) -> int:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _sources(entries: Any) -> dict[str, int]:
    sources: dict[str, int] = {}
    for entry in entries or []:
        if isinstance(entry, dict) and isinstance(entry.get("scene_desc"), str):
            sources[entry["scene_desc"]] = _int(entry.get("user_count"))
    return sources


def _total(sources: dict[str, int]) -> int:
    if _TOTAL_SCENE in sources:
        return sources[_TOTAL_SCENE]
    return sum(sources.values())


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


async def sync_account_stats(
    session: AsyncSession,
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    account_id: UUID,
    today: date,
    now: datetime,
) -> SyncReport:
    account, client = await account_client(
        session, settings=settings, http=http, account_id=account_id
    )
    account_key = account.id
    first = account.stats_synced_on is None
    article_days = FIRST_SYNC_DAYS if first else ARTICLE_REFRESH_DAYS
    account_days = FIRST_SYNC_DAYS if first else ACCOUNT_REFRESH_DAYS
    articles = 0
    try:
        for back in range(1, article_days + 1):
            publish_date = today - timedelta(days=back)
            for row in await client.article_day(publish_date):
                details = [d for d in row.get("detail_list") or [] if isinstance(d, dict)]
                if not details or row.get("msgid") is None:
                    continue
                latest = max(details, key=lambda d: str(d.get("stat_date", "")))
                sources = _sources(latest.get("read_user_source"))
                values = {
                    "title": str(row.get("title") or "")[:300],
                    "url": str(row.get("content_url") or "") or None,
                    "publish_date": _day(row.get("ref_date")) or publish_date,
                    "stat_date": _day(latest.get("stat_date")) or publish_date,
                    "read_user": _total(sources),
                    "share_user": _int(latest.get("share_user")),
                    "collection_user": _int(latest.get("collection_user")),
                    "read_subscribe_user": _int(latest.get("read_subscribe_user")),
                    "read_delivery_rate": _float(latest.get("read_delivery_rate")),
                    "read_finish_rate": _float(latest.get("read_finish_rate")),
                    "read_avg_activetime": _float(latest.get("read_avg_activetime")),
                    "read_sources": sources,
                    "fetched_at": now,
                }
                await session.execute(
                    insert(WeChatArticleStatsModel)
                    .values(
                        id=uuid4(), account_id=account.id, msgid=str(row["msgid"])[:64], **values
                    )
                    .on_conflict_do_update(
                        constraint="uq_wechat_article_stats_account_msgid", set_=values
                    )
                )
                articles += 1
        for back in range(1, account_days + 1):
            ref_date = today - timedelta(days=back)
            for row in await client.account_day(ref_date):
                detail = row.get("detail") if isinstance(row, dict) else None
                if not isinstance(detail, dict):
                    continue
                values = {
                    "read_user": _int(detail.get("read_user")),
                    "share_user": _int(detail.get("share_user")),
                    "like_user": _int(detail.get("like_user")),
                    "zaikan_user": _int(detail.get("zaikan_user")),
                    "comment_count": _int(detail.get("comment_count")),
                    "collection_user": _int(detail.get("collection_user")),
                    "redirect_ori_page_user": _int(detail.get("redirect_ori_page_user")),
                    "send_page_count": _int(detail.get("send_page_count")),
                    "read_sources": _sources(detail.get("read_user_source")),
                    "fetched_at": now,
                }
                await session.execute(
                    insert(WeChatAccountDailyStatsModel)
                    .values(
                        id=uuid4(),
                        account_id=account.id,
                        ref_date=_day(row.get("ref_date")) or ref_date,
                        **values,
                    )
                    .on_conflict_do_update(
                        constraint="uq_wechat_account_daily_stats_day", set_=values
                    )
                )
    except WeChatAdminError as error:
        # A rollback expires every loaded row; reload the account by its key.
        await session.rollback()
        failed = await session.get(WeChatAccountModel, account_key)
        if failed is not None:
            failed.stats_sync_error = error.message[:200]
            failed.updated_at = now
            await session.commit()
        raise wechat_call_error(error) from error
    account.stats_synced_on = today
    account.stats_sync_error = None
    await session.commit()
    return SyncReport(articles=articles, days=account_days)


def business_today(settings: Settings, now: datetime) -> date:
    return now.astimezone(ZoneInfo(settings.business_timezone)).date()


async def run_stats_loop_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    now: datetime,
) -> int:
    """Sync every enabled account not yet synced today, once 10:00 business time has passed."""

    local = now.astimezone(ZoneInfo(settings.business_timezone))
    if local.hour < SYNC_AFTER_LOCAL_HOUR:
        return 0
    async with session_factory() as session:
        due = list(
            (
                await session.scalars(
                    select(WeChatAccountModel.id).where(
                        WeChatAccountModel.enabled.is_(True),
                        or_(
                            WeChatAccountModel.stats_synced_on.is_(None),
                            WeChatAccountModel.stats_synced_on < local.date(),
                        ),
                        # A failed sync retries the next business day (or on a manual sync),
                        # not every 20 s.
                        or_(
                            WeChatAccountModel.stats_sync_error.is_(None),
                            WeChatAccountModel.updated_at
                            < local.replace(hour=0, minute=0, second=0, microsecond=0),
                        ),
                    )
                )
            ).all()
        )
    synced = 0
    for account_id in due:
        async with session_factory() as session:
            try:
                await sync_account_stats(
                    session,
                    settings=settings,
                    http=http,
                    account_id=account_id,
                    today=local.date(),
                    now=now,
                )
                synced += 1
            except WeChatAdminRejected:
                continue
    return synced


async def manual_sync(
    session: AsyncSession,
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    principal: AdminPrincipal,
    account_id: UUID,
    now: datetime,
) -> SyncReport:
    last = _LAST_MANUAL.get(account_id)
    if last is not None and monotonic() - last < MANUAL_SYNC_GAP_SECONDS:
        raise WeChatAdminRejected("刚同步过，5 分钟后再试", "wechat_stats_too_soon", 429)
    _LAST_MANUAL[account_id] = monotonic()
    report = await sync_account_stats(
        session,
        settings=settings,
        http=http,
        account_id=account_id,
        today=business_today(settings, now),
        now=now,
    )
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="wechat.stats_synced",
        target_type="wechat_account",
        target_id=str(account_id),
        detail={"articles": report.articles, "days": report.days},
    )
    await session.commit()
    return report


async def account_stats(
    session: AsyncSession, *, account_id: UUID, since: date
) -> tuple[list[WeChatAccountDailyStatsModel], list[WeChatArticleStatsModel]]:
    daily = (
        await session.scalars(
            select(WeChatAccountDailyStatsModel)
            .where(
                WeChatAccountDailyStatsModel.account_id == account_id,
                WeChatAccountDailyStatsModel.ref_date >= since,
            )
            .order_by(WeChatAccountDailyStatsModel.ref_date)
        )
    ).all()
    articles = (
        await session.scalars(
            select(WeChatArticleStatsModel)
            .where(
                WeChatArticleStatsModel.account_id == account_id,
                WeChatArticleStatsModel.publish_date >= since,
            )
            .order_by(WeChatArticleStatsModel.publish_date.desc(), WeChatArticleStatsModel.title)
        )
    ).all()
    return list(daily), list(articles)


__all__ = [
    "SyncReport",
    "account_stats",
    "business_today",
    "manual_sync",
    "run_stats_loop_once",
    "sync_account_stats",
]
