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
- later syncs refresh the last 7 publish dates and the last 3 account days, plus missed dates
  since the last successful sync and account-day gaps within the 30-day window.
The API loop runs it once per business day after 10:00. An operator can also start it, at
most once every 5 minutes per account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import isfinite
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


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if value < 0 or value > 2_147_483_647 or not isfinite(value) or value != int(value):
        return None
    return int(value)


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if 0 <= value <= 1e308 and isfinite(value) else None


def _sources(entries: Any) -> dict[str, int] | None:
    if entries is None:
        return {}
    if not isinstance(entries, list):
        return None
    sources: dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("scene_desc"), str):
            return None
        count = _count(entry.get("user_count"))
        if count is None:
            return None
        sources[entry["scene_desc"]] = count
    return sources


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


_ACCOUNT_COUNTERS = (
    "share_user",
    "like_user",
    "zaikan_user",
    "comment_count",
    "collection_user",
    "redirect_ori_page_user",
    "send_page_count",
)
_ARTICLE_COUNTERS = ("share_user", "collection_user", "read_subscribe_user")


def _optional_counts(detail: dict[str, Any], keys: tuple[str, ...]) -> dict[str, int] | None:
    # Sparse provider responses omit optional counters when there is no activity. Preserve that
    # existing zero semantics, but never coerce a present malformed value into a measured zero.
    counts: dict[str, int] = {}
    for key in keys:
        count = _count(detail.get(key, 0))
        if count is None:
            return None
        counts[key] = count
    return counts


def _daily_values(row: Any, *, ref_date: date, now: datetime) -> dict[str, Any] | None:
    if not isinstance(row, dict) or _day(row.get("ref_date")) != ref_date:
        return None
    detail = row.get("detail")
    if not isinstance(detail, dict):
        return None
    readers = _count(detail.get("read_user"))
    counts = _optional_counts(detail, _ACCOUNT_COUNTERS)
    sources = _sources(detail.get("read_user_source"))
    if readers is None or counts is None or sources is None:
        return None
    return {"read_user": readers, **counts, "read_sources": sources, "fetched_at": now}


def _article_values(
    row: Any, *, publish_date: date, today: date, now: datetime
) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(row, dict) or _day(row.get("ref_date")) != publish_date:
        return None
    msgid = row.get("msgid")
    if not isinstance(msgid, str) or not msgid or len(msgid) > 64:
        return None
    details = row.get("detail_list")
    if not isinstance(details, list):
        return None
    dated = [
        (stat_date, detail)
        for detail in details
        if isinstance(detail, dict)
        and (stat_date := _day(detail.get("stat_date"))) is not None
        and publish_date <= stat_date < today
    ]
    if not dated:
        return None
    stat_date, latest = max(dated, key=lambda pair: pair[0])
    sources = _sources(latest.get("read_user_source"))
    counts = _optional_counts(latest, _ARTICLE_COUNTERS)
    if not sources or counts is None:
        return None
    readers = _count(sources.get(_TOTAL_SCENE, sum(sources.values())))
    if readers is None:
        return None
    return msgid, {
        "title": str(row.get("title") or "")[:300],
        "url": str(row.get("content_url") or "") or None,
        "publish_date": publish_date,
        "stat_date": stat_date,
        "read_user": readers,
        **counts,
        "read_delivery_rate": _float(latest.get("read_delivery_rate")),
        "read_finish_rate": _float(latest.get("read_finish_rate")),
        "read_avg_activetime": _float(latest.get("read_avg_activetime")),
        "read_sources": sources,
        "fetched_at": now,
    }


def sync_dates(
    *, today: date, last_success: date | None, refresh_days: int, missing: set[date]
) -> list[date]:
    """Newest first, capped at the provider's 30-day history; success covers yesterday."""
    earliest = today - timedelta(days=FIRST_SYNC_DAYS)
    start = (
        earliest
        if last_success is None
        else max(earliest, min(last_success, today - timedelta(days=refresh_days)))
    )
    dates = {start + timedelta(days=offset) for offset in range((today - start).days)}
    dates.update(day for day in missing if earliest <= day < today)
    return sorted(dates, reverse=True)


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
    account_key, last_success = account.id, account.stats_synced_on
    first_day = today - timedelta(days=FIRST_SYNC_DAYS)
    present = set(
        await session.scalars(
            select(WeChatAccountDailyStatsModel.ref_date).where(
                WeChatAccountDailyStatsModel.account_id == account_key,
                WeChatAccountDailyStatsModel.ref_date >= first_day,
                WeChatAccountDailyStatsModel.ref_date < today,
            )
        )
    )
    missing = {today - timedelta(days=back) for back in range(1, FIRST_SYNC_DAYS + 1)} - present
    article_dates = sync_dates(
        today=today, last_success=last_success, refresh_days=ARTICLE_REFRESH_DAYS, missing=missing
    )
    account_dates = sync_dates(
        today=today, last_success=last_success, refresh_days=ACCOUNT_REFRESH_DAYS, missing=missing
    )
    # End the auth/account/query transaction before any provider or token request. Keep only
    # immutable identifiers, the client, and collected values across the network phase.
    await session.rollback()
    article_values: dict[str, dict[str, Any]] = {}
    daily_values: dict[date, dict[str, Any]] = {}
    try:
        for publish_date in article_dates:
            for row in await client.article_day(publish_date):
                parsed = _article_values(row, publish_date=publish_date, today=today, now=now)
                if parsed is not None:
                    msgid, values = parsed
                    article_values[msgid] = values
        for ref_date in account_dates:
            for row in await client.account_day(ref_date):
                measured = _daily_values(row, ref_date=ref_date, now=now)
                if measured is not None:
                    daily_values[ref_date] = measured
    except WeChatAdminError as error:
        failed = await session.get(WeChatAccountModel, account_key)
        if failed is not None:
            failed.stats_sync_error = error.message[:200]
            failed.updated_at = now
            await session.commit()
        raise wechat_call_error(error) from error

    # Persist only after every requested date completed; a provider failure keeps the prior
    # successful watermark and previously measured data intact for the next catch-up attempt.
    for msgid, values in article_values.items():
        await session.execute(
            insert(WeChatArticleStatsModel)
            .values(id=uuid4(), account_id=account_key, msgid=msgid, **values)
            .on_conflict_do_update(constraint="uq_wechat_article_stats_account_msgid", set_=values)
        )
    for ref_date, values in daily_values.items():
        await session.execute(
            insert(WeChatAccountDailyStatsModel)
            .values(id=uuid4(), account_id=account_key, ref_date=ref_date, **values)
            .on_conflict_do_update(constraint="uq_wechat_account_daily_stats_day", set_=values)
        )
    updated = await session.get(WeChatAccountModel, account_key)
    if updated is not None:
        updated.stats_synced_on = today
        updated.stats_sync_error = None
        updated.updated_at = now
    await session.commit()
    return SyncReport(articles=len(article_values), days=len(daily_values))


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
    session: AsyncSession, *, account_id: UUID, since: date, until: date
) -> tuple[list[WeChatAccountDailyStatsModel], list[WeChatArticleStatsModel]]:
    daily = (
        await session.scalars(
            select(WeChatAccountDailyStatsModel)
            .where(
                WeChatAccountDailyStatsModel.account_id == account_id,
                WeChatAccountDailyStatsModel.ref_date >= since,
                WeChatAccountDailyStatsModel.ref_date <= until,
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
                WeChatArticleStatsModel.publish_date <= until,
                WeChatArticleStatsModel.stat_date <= until,
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
