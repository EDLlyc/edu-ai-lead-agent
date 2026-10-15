from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.application.services.visitor_display import VisitorDisplayService
from app.infrastructure.db.visitor_report import (
    VisitorReportDay,
    load_report_days,
    report_window,
)
from app.infrastructure.visitor_review_store import NewsReviewSubject, VisitorReviewStore
from app.schemas.visitor_display import VisitorDisplayReport, VisitorDisplayReportDay
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

SECRET = "visitor-display-test-secret-that-is-32-bytes-long"
TODAY = date(2026, 9, 28)


def _result(rows: list[tuple[object, ...]]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


@pytest.mark.asyncio
async def test_report_aggregates_bounded_select_only_beijing_days() -> None:
    session = AsyncMock(spec=AsyncSession)
    slot = SimpleNamespace(
        id=uuid4(),
        business_date=TODAY,
        content_slot="morning",
        total_scores=500,
        eligible_scores=39,
        selected_count=3,
    )
    older_same_slot = SimpleNamespace(**{**vars(slot), "id": uuid4(), "total_scores": 999})
    session.scalars.return_value = [slot, older_same_slot]
    session.scalar.return_value = None  # optional single-edition table absent
    session.execute.side_effect = [
        _result([(TODAY, 120, 80, 7)]),
        _result([(TODAY, "accepted", 2), (TODAY, "failed", 1), (TODAY, "queued", 5)]),
        _result([(TODAY, "delivered", 2), (TODAY, "cancelled", 1), (TODAY, "delivery_unknown", 1)]),
        _result([(TODAY, "ready", 1), (TODAY, "failed", 1), (TODAY, "running", 1)]),
        _result([(TODAY, 1)]),
    ]

    days = await load_report_days(session, today=TODAY)

    assert [item.day for item in days] == list(report_window(TODAY))
    today = days[-1]
    assert (today.fetched_new, today.filtered, today.duplicates) == (120, 80, 7)
    # Only the newest succeeded run per date+slot counts; older duplicates never double count.
    assert (today.evaluated, today.eligible, today.selected) == (500, 39, 3)
    assert today.scoring_batches == 1
    assert (today.copies_accepted, today.copies_failed) == (2, 1)
    assert (today.wecom_delivered, today.wecom_failed, today.wecom_unknown) == (2, 1, 1)
    assert (today.articles_ready, today.articles_failed, today.articles_other) == (1, 1, 1)
    assert today.drafts_created == 1
    assert all(item == VisitorReportDay(day=item.day) for item in days[:-1])
    statements = [
        str(
            call.args[0].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        for call in session.execute.call_args_list
    ]
    assert all(sql.startswith("SELECT") for sql in statements)
    assert all("2026-09-22" in sql and "2026-09-28" in sql for sql in statements)
    assert "timezone('Asia/Shanghai', wecom_delivery_jobs.completed_at)" in statements[2]
    assert "wecom_delivery_jobs.mode = 'formal'" in statements[2]
    assert "generation_mode = 'live'" in statements[3]


@pytest.mark.asyncio
async def test_review_day_counts_use_latest_call_per_item_and_local_day(tmp_path: Path) -> None:
    store = VisitorReviewStore(tmp_path / "reviews.sqlite3")
    store.initialize()
    rejected = NewsReviewSubject(
        title="新闻", source_name=None, ai_verdict="rejected", business_date=TODAY, slot="noon"
    )
    selected = NewsReviewSubject(
        title="新闻", source_name=None, ai_verdict="selected", business_date=TODAY, slot="noon"
    )
    key_a, key_b, key_c = ("vn1_" + c * 24 for c in "abc")
    # 2026-09-27 16:30 UTC is 00:30 on 09-28 in Beijing.
    late = datetime(2026, 9, 27, 16, 30, tzinfo=UTC)
    await store.record(key=key_a, decision="include", note=None, subject=rejected, now=late)
    await store.record(key=key_a, decision="agree", note=None, subject=rejected, now=late)
    await store.record(key=key_b, decision="include", note=None, subject=rejected, now=late)
    await store.record(key=key_c, decision="exclude", note=None, subject=selected, now=late)
    await store.record(
        key=key_c,
        decision="agree",
        note=None,
        subject=selected,
        now=datetime(2026, 9, 27, 15, 0, tzinfo=UTC),
    )

    counts = await store.daily_counts(report_window(TODAY), timezone="Asia/Shanghai")

    assert counts[TODAY] == (3, 2)
    assert counts[date(2026, 9, 27)] == (1, 0)


@pytest.mark.asyncio
async def test_report_failure_keeps_snapshot_and_reviews_merge_into_days(tmp_path: Path) -> None:
    class Repository:
        async def load_latest(self) -> tuple[()]:
            return ()

        async def load_moments(self) -> tuple[()]:
            return ()

        async def load_issue_signals(self, *, today: date) -> tuple[()]:
            return ()

        async def load_news_pool(self) -> tuple[()]:
            return ()

        load_report = AsyncMock(side_effect=OperationalError("SELECT", {}, Exception("down")))

    broken = await VisitorDisplayService(
        repository=Repository(),  # type: ignore[arg-type]
        asset_secret=SECRET,
    ).snapshot(now=datetime(2026, 9, 28, 2, 0, tzinfo=UTC))
    assert broken.report is None
    assert broken.news_pool is not None

    Repository.load_report = AsyncMock(  # type: ignore[method-assign]
        return_value=tuple(VisitorReportDay(day=day) for day in report_window(TODAY))
    )
    store = VisitorReviewStore(tmp_path / "reviews.sqlite3")
    store.initialize()
    await store.record(
        key="vn1_" + "d" * 24,
        decision="include",
        note=None,
        subject=NewsReviewSubject(
            title="新闻", source_name=None, ai_verdict="rejected", business_date=TODAY, slot="noon"
        ),
        now=datetime(2026, 9, 28, 1, 0, tzinfo=UTC),
    )
    report = await VisitorDisplayService(
        repository=Repository(),  # type: ignore[arg-type]
        asset_secret=SECRET,
        reviews=store,
    ).report(now=datetime(2026, 9, 28, 2, 0, tzinfo=UTC))
    assert report.days[-1].day == TODAY
    assert (report.days[-1].human_reviews, report.days[-1].human_disagreements) == (1, 1)
    # 17:30 UTC is already the next Beijing day.
    Repository.load_report.reset_mock()
    await VisitorDisplayService(
        repository=Repository(),  # type: ignore[arg-type]
        asset_secret=SECRET,
    ).report(now=datetime(2026, 9, 28, 17, 30, tzinfo=UTC))
    assert Repository.load_report.await_args.kwargs == {"today": date(2026, 9, 29)}


def test_report_schema_requires_consecutive_bounded_days() -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    with pytest.raises(ValidationError):
        VisitorDisplayReport(
            generated_at=now,
            days=[
                VisitorDisplayReportDay(day=date(2026, 9, 26)),
                VisitorDisplayReportDay(day=date(2026, 9, 28)),
            ],
        )
    with pytest.raises(ValidationError):
        VisitorDisplayReportDay(day=TODAY, evaluated=-1)
    assert "id" not in VisitorDisplayReportDay.model_fields
