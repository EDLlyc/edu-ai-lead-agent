from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from app import api_main
from app.application.services.wechat_stats import (
    _article_values,
    _daily_values,
    business_today,
    sync_dates,
)
from app.core.config import Settings
from fastapi import FastAPI
from pydantic import SecretStr

TODAY = date(2026, 10, 10)
NOW = datetime(2026, 10, 10, 3, tzinfo=UTC)
YESTERDAY = TODAY - timedelta(days=1)


def test_backfill_recovers_ten_days_and_older_gaps_but_stays_bounded() -> None:
    missing = {TODAY - timedelta(days=20), TODAY - timedelta(days=40), TODAY}
    for overlap in (3, 7):
        planned = sync_dates(
            today=TODAY,
            last_success=TODAY - timedelta(days=10),
            refresh_days=overlap,
            missing=missing,
        )
        assert planned == [TODAY - timedelta(days=i) for i in range(1, 11)] + [
            TODAY - timedelta(days=20)
        ]
    for last in (None, TODAY - timedelta(days=100)):
        planned = sync_dates(today=TODAY, last_success=last, refresh_days=7, missing=set())
        assert len(planned) == 30
        assert planned[0] == YESTERDAY and planned[-1] == TODAY - timedelta(days=30)
    assert len(sync_dates(today=TODAY, last_success=TODAY, refresh_days=3, missing=set())) == 3


def test_business_date_uses_configured_timezone_across_midnight() -> None:
    settings = Settings(_env_file=None, business_timezone="Asia/Shanghai")
    assert business_today(settings, datetime(2026, 10, 9, 15, 59, 59, tzinfo=UTC)) == date(
        2026, 10, 9
    )
    assert business_today(settings, datetime(2026, 10, 9, 16, tzinfo=UTC)) == TODAY


@pytest.mark.parametrize("readers", [None, "0", True, -1, 0.5, float("inf"), float("nan")])
def test_invalid_or_missing_readers_never_become_measured_zero(readers: Any) -> None:
    row = {"ref_date": str(YESTERDAY), "detail": {"read_user": readers}}
    assert _daily_values(row, ref_date=YESTERDAY, now=NOW) is None


def test_sparse_zero_is_valid_but_present_invalid_fields_and_dates_are_not() -> None:
    row: dict[str, Any] = {"ref_date": str(YESTERDAY), "detail": {"read_user": 0}}
    parsed = _daily_values(row, ref_date=YESTERDAY, now=NOW)
    assert parsed is not None and parsed["read_user"] == 0 and parsed["share_user"] == 0
    row["detail"]["share_user"] = "unknown"
    assert _daily_values(row, ref_date=YESTERDAY, now=NOW) is None
    row["detail"] = {"read_user": 10}
    for invalid in (str(TODAY), "not-a-date", None):
        row["ref_date"] = invalid
        assert _daily_values(row, ref_date=YESTERDAY, now=NOW) is None
    assert _daily_values({}, ref_date=YESTERDAY, now=NOW) is None


def test_article_measurements_need_a_valid_date_and_reading_counts() -> None:
    row: dict[str, Any] = {
        "msgid": "article-1",
        "ref_date": str(YESTERDAY),
        "detail_list": [
            {
                "stat_date": str(YESTERDAY),
                "read_user_source": [
                    {"scene_desc": "全部", "user_count": 0},
                ],
            }
        ],
    }
    parsed = _article_values(row, publish_date=YESTERDAY, today=TODAY, now=NOW)
    assert parsed is not None and parsed[1]["read_user"] == 0
    row["detail_list"][0]["stat_date"] = str(TODAY)
    assert _article_values(row, publish_date=YESTERDAY, today=TODAY, now=NOW) is None
    row["detail_list"][0]["stat_date"] = str(YESTERDAY)
    row["detail_list"][0]["read_user_source"] = []
    assert _article_values(row, publish_date=YESTERDAY, today=TODAY, now=NOW) is None


@pytest.mark.asyncio
async def test_slow_stats_do_not_block_publication_and_shutdown_cancels_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.state.settings = SimpleNamespace(admin_secret_key=SecretStr("configured"))
    app.state.session_factory = object()
    started = asyncio.Event()
    publications = asyncio.Event()
    cancelled = asyncio.Event()
    published = 0

    async def stats(*args: Any, **kwargs: Any) -> int:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return 0

    async def publish(*args: Any, **kwargs: Any) -> Any:
        nonlocal published
        published += 1
        if published >= 3:
            publications.set()
        return SimpleNamespace(submitted=0, recovered=0, polled=0)

    monkeypatch.setattr(api_main, "run_stats_loop_once", stats)
    monkeypatch.setattr(api_main, "run_publish_loop_once", publish)
    monkeypatch.setattr(api_main, "WECHAT_ADMIN_LOOP_SECONDS", 0.001)
    async with api_main._wechat_admin_tasks(app):
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.wait_for(publications.wait(), 1)
    assert cancelled.is_set()
    assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("wechat-")]


@pytest.mark.asyncio
async def test_disabled_admin_starts_no_background_work() -> None:
    app = FastAPI()
    app.state.settings = SimpleNamespace(admin_secret_key=None)
    async with api_main._wechat_admin_tasks(app):
        assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("wechat-")]
