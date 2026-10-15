"""Read-only daily aggregates for the visitor exhibit's daily and weekly report.

Every query is a bounded ``SELECT … GROUP BY`` over a short Beijing-date window. Timestamps are
bucketed with ``timezone('Asia/Shanghai', …)`` so a day means the operator's calendar day.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import Date, DateTime, String, Uuid, cast, column, func, select, table
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.roles import ExpressionElementRole

from app.infrastructure.db.models import (
    AcquisitionRunModel,
    ContentSlotRunModel,
    CopyGenerationRunModel,
    OfficialAccountArticleRunModel,
    WeChatOfficialAccountDraftItemModel,
    WeComDeliveryJobModel,
)

REPORT_TIMEZONE = "Asia/Shanghai"
REPORT_DAYS = 7
_SLOT_RUN_SCAN_LIMIT = REPORT_DAYS * 3 * 6

# Optional production table outside Base.metadata (see visitor_display.py).
_SINGLE_EDITIONS = table(
    "official_account_single_editions",
    column("id", Uuid),
    column("status", String),
    column("updated_at", DateTime(timezone=True)),
    schema="public",
)


@dataclass(slots=True)
class VisitorReportDay:
    day: date
    fetched_new: int = 0
    filtered: int = 0
    duplicates: int = 0
    scoring_batches: int = 0
    evaluated: int = 0
    eligible: int = 0
    selected: int = 0
    copies_accepted: int = 0
    copies_review_required: int = 0
    copies_failed: int = 0
    copies_no_topic: int = 0
    wecom_delivered: int = 0
    wecom_partial: int = 0
    wecom_failed: int = 0
    wecom_unknown: int = 0
    articles_ready: int = 0
    articles_failed: int = 0
    articles_other: int = 0
    drafts_created: int = 0
    human_reviews: int = 0
    human_disagreements: int = 0


def report_window(today: date) -> tuple[date, ...]:
    return tuple(today - timedelta(days=offset) for offset in range(REPORT_DAYS - 1, -1, -1))


def _local_day(value: ExpressionElementRole[datetime | None]) -> ColumnElement[date]:
    return cast(func.timezone(REPORT_TIMEZONE, value), Date)


async def load_report_days(session: AsyncSession, *, today: date) -> tuple[VisitorReportDay, ...]:
    days = report_window(today)
    first, last = days[0], days[-1]
    by_day = {day: VisitorReportDay(day=day) for day in days}

    acquisition_day = func.coalesce(
        AcquisitionRunModel.business_date, _local_day(AcquisitionRunModel.created_at)
    )
    for day, new, filtered, duplicates in (
        await session.execute(
            select(
                acquisition_day,
                func.sum(AcquisitionRunModel.new_count),
                func.sum(AcquisitionRunModel.filtered_count),
                func.sum(AcquisitionRunModel.duplicate_count),
            )
            .where(
                AcquisitionRunModel.status.in_(("succeeded", "partially_succeeded")),
                acquisition_day.between(first, last),
            )
            .group_by(acquisition_day)
        )
    ).all():
        if day in by_day:
            by_day[day].fetched_new = int(new or 0)
            by_day[day].filtered = int(filtered or 0)
            by_day[day].duplicates = int(duplicates or 0)

    # One scoring result per date+slot: the newest succeeded run, as the news pool shows it.
    seen: set[tuple[date, str]] = set()
    for run in await session.scalars(
        select(ContentSlotRunModel)
        .where(
            ContentSlotRunModel.status == "succeeded",
            ContentSlotRunModel.trigger.in_(("scheduled", "manual")),
            ContentSlotRunModel.business_date.between(first, last),
        )
        .order_by(
            ContentSlotRunModel.target_at.desc(),
            ContentSlotRunModel.completed_at.desc(),
            ContentSlotRunModel.id.desc(),
        )
        .limit(_SLOT_RUN_SCAN_LIMIT)
    ):
        identity = (run.business_date, run.content_slot)
        if identity in seen or run.business_date not in by_day:
            continue
        seen.add(identity)
        report = by_day[run.business_date]
        report.scoring_batches += 1
        report.evaluated += max(run.total_scores, 0)
        report.eligible += max(run.eligible_scores, 0)
        report.selected += max(run.selected_count, 0)

    copy_fields = {
        "accepted": "copies_accepted",
        "review_required": "copies_review_required",
        "failed": "copies_failed",
        "no_topic": "copies_no_topic",
    }
    for day, status, count in (
        await session.execute(
            select(
                CopyGenerationRunModel.business_date,
                CopyGenerationRunModel.status,
                func.count(),
            )
            .where(CopyGenerationRunModel.business_date.between(first, last))
            .group_by(CopyGenerationRunModel.business_date, CopyGenerationRunModel.status)
        )
    ).all():
        name = copy_fields.get(status)
        if name is not None and day in by_day:
            setattr(by_day[day], name, int(count))

    wecom_day = _local_day(WeComDeliveryJobModel.completed_at)
    wecom_fields = {
        "delivered": "wecom_delivered",
        "partial": "wecom_partial",
        "failed": "wecom_failed",
        "cancelled": "wecom_failed",
        "delivery_window_expired": "wecom_failed",
        "delivery_unknown": "wecom_unknown",
    }
    for day, status, count in (
        await session.execute(
            select(wecom_day, WeComDeliveryJobModel.status, func.count())
            .where(
                WeComDeliveryJobModel.mode == "formal",
                WeComDeliveryJobModel.completed_at.is_not(None),
                wecom_day.between(first, last),
            )
            .group_by(wecom_day, WeComDeliveryJobModel.status)
        )
    ).all():
        name = wecom_fields.get(status)
        if name is not None and day in by_day:
            setattr(by_day[day], name, getattr(by_day[day], name) + int(count))

    article_day = _local_day(OfficialAccountArticleRunModel.created_at)
    for day, status, count in (
        await session.execute(
            select(article_day, OfficialAccountArticleRunModel.status, func.count())
            .where(
                OfficialAccountArticleRunModel.generation_mode == "live",
                article_day.between(first, last),
            )
            .group_by(article_day, OfficialAccountArticleRunModel.status)
        )
    ).all():
        if day not in by_day:
            continue
        if status == "ready":
            by_day[day].articles_ready += int(count)
        elif status == "failed":
            by_day[day].articles_failed += int(count)
        else:
            by_day[day].articles_other += int(count)

    drafts: defaultdict[date, int] = defaultdict(int)
    draft_day = _local_day(WeChatOfficialAccountDraftItemModel.completed_at)
    for day, count in (
        await session.execute(
            select(draft_day, func.count())
            .where(
                WeChatOfficialAccountDraftItemModel.status == "succeeded",
                WeChatOfficialAccountDraftItemModel.completed_at.is_not(None),
                draft_day.between(first, last),
            )
            .group_by(draft_day)
        )
    ).all():
        drafts[day] += int(count)
    if (
        await session.scalar(select(func.to_regclass("public.official_account_single_editions")))
        is not None
    ):
        single_day = _local_day(_SINGLE_EDITIONS.c.updated_at)
        for day, count in (
            await session.execute(
                select(single_day, func.count())
                .where(
                    _SINGLE_EDITIONS.c.status == "delivered",
                    single_day.between(first, last),
                )
                .group_by(single_day)
            )
        ).all():
            drafts[day] += int(count)
    for day, count in drafts.items():
        if day in by_day:
            by_day[day].drafts_created = count

    return tuple(by_day[day] for day in days)


__all__ = [
    "REPORT_DAYS",
    "REPORT_TIMEZONE",
    "VisitorReportDay",
    "load_report_days",
    "report_window",
]
