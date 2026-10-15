from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from app.application.services.visitor_improvement import FIXES, project_improvement
from app.infrastructure.db.visitor_improvement import (
    VisitorIssueSignal,
    improvement_window,
    load_issue_signals,
)
from app.infrastructure.visitor_review_store import NewsReviewSubject, VisitorReviewStore
from app.schemas.visitor_display import VisitorDisplayImprovement
from sqlalchemy.dialects import postgresql

ZONE = ZoneInfo("Asia/Shanghai")
# 10:00 on 2026-10-05: superlative/short-fact/rejected fixes (09-28 23:19) are 7 days live.
NOW = datetime(2026, 10, 5, 10, 0, tzinfo=ZONE)


def _signal(code: str, day: date, count: int = 1) -> VisitorIssueSignal:
    return VisitorIssueSignal(code=code, day=day, count=count)


def test_fixed_problem_shows_before_after_and_open_problem_leads_with_suggestion() -> None:
    signals = [
        # Before the 09-28 23:19 release: blocked superlatives; none after.
        _signal("copy:unverified_superlative", date(2026, 9, 27), 2),
        _signal("copy:unverified_superlative", date(2026, 9, 28), 1),
        # Still happening, with no release against it.
        _signal("wecom:webhook_rate_limited", date(2026, 10, 5), 2),
        _signal("wecom:webhook_rate_limited", date(2026, 10, 1), 1),
        # Rejected copy recurred after its release: keep watching, not "fixed".
        _signal("copy:provider_request_rejected", date(2026, 9, 26), 3),
        _signal("copy:provider_request_rejected", date(2026, 10, 3), 1),
        _signal("human:pick", date(2026, 10, 4), 2),
    ]
    human = {date(2026, 10, 4): {"agree": 3, "include_override": 1, "exclude_override": 0}}

    view = project_improvement(signals, human, now=NOW)

    by_key = {issue.key: issue for issue in view.issues}
    wecom = by_key["wecom:webhook_rate_limited"]
    assert (wecom.status, wecom.source, wecom.today, wecom.this_week) == ("open", "daily", 2, 3)
    assert "webhook_rate_limited" in wecom.cause
    assert wecom.suggestion is not None
    superlative = by_key["copy:unverified_superlative"]
    assert (superlative.status, superlative.fix_key) == ("fixed", "superlative_relaxed")
    assert (superlative.this_week, superlative.last_week) == (0, 3)
    assert by_key["copy:provider_request_rejected"].status == "watching"
    assert by_key["human:include_override"].source == "human"
    assert "human:pick" not in by_key
    # Open problems come first.
    assert view.issues[0].key == "wecom:webhook_rate_limited"
    assert view.next_steps == [wecom.suggestion]

    fixes = {fix.key: fix for fix in view.fixes}
    assert (fixes["superlative_relaxed"].before, fixes["superlative_relaxed"].after) == (3, 0)
    assert fixes["superlative_relaxed"].days_live == 7
    assert (fixes["rejected_copy_repeat"].before, fixes["rejected_copy_repeat"].after) == (3, 1)
    assert fixes["brand_rotation"].before is None
    assert [fix.shipped_at for fix in view.fixes] == sorted(
        (fix.shipped_at for fix in view.fixes), reverse=True
    )
    assert (view.human.reviews, view.human.include_overrides, view.human.picks) == (4, 1, 2)
    VisitorDisplayImprovement.model_validate(view.model_dump())


def test_unreleased_fixes_are_hidden_and_recent_ones_are_only_watching() -> None:
    before_any = datetime(2026, 9, 25, 12, 0, tzinfo=ZONE)
    assert project_improvement([], {}, now=before_any).fixes == []

    just_after = datetime(2026, 9, 29, 9, 0, tzinfo=ZONE)
    view = project_improvement(
        [_signal("copy:unverified_superlative", date(2026, 9, 28))], {}, now=just_after
    )
    assert len(view.fixes) == sum(fix.shipped_at <= just_after for fix in FIXES)
    assert view.issues[0].status == "watching"


def test_every_release_and_problem_copy_fits_the_contract() -> None:
    view = project_improvement(
        [
            _signal(code, date(2026, 10, 5))
            for code in (
                "copy:unverified_superlative",
                "copy:provider_request_rejected",
                "copy:missing_eligible_evidence",
                "copy:something_new",
                "infographic:moments_preflight_failed",
                "infographic:other",
                "wecom:delivery_unknown",
                "acquisition:timeout",
                "slot:empty",
                "slot:failed",
                "unknown_stage:x",
            )
        ],
        {date(2026, 10, 5): {"agree": 0, "include_override": 1, "exclude_override": 1}},
        now=NOW,
    )
    assert len(view.fixes) == len(FIXES)
    assert len(view.issues) == 13
    VisitorDisplayImprovement.model_validate(view.model_dump())


@pytest.mark.asyncio
async def test_signal_reader_is_bounded_select_only() -> None:
    statements: list[str] = []

    class _Result:
        def all(self) -> list[object]:
            return []

    class _Session:
        async def execute(self, statement: object) -> _Result:
            statements.append(str(statement.compile(dialect=postgresql.dialect())))  # type: ignore[attr-defined]
            return _Result()

        async def scalars(self, statement: object) -> list[object]:
            statements.append(str(statement.compile(dialect=postgresql.dialect())))  # type: ignore[attr-defined]
            return []

    signals = await load_issue_signals(
        _Session(),  # type: ignore[arg-type]
        today=date(2026, 10, 5),
    )
    assert signals == ()
    assert len(statements) == 6
    for sql in statements:
        assert sql.lstrip().upper().startswith("SELECT")
        assert "INSERT" not in sql.upper() and "UPDATE" not in sql.upper()
    assert len(improvement_window(date(2026, 10, 5))) == 14


@pytest.mark.asyncio
async def test_review_store_splits_daily_decisions_by_direction(tmp_path: Path) -> None:
    store = VisitorReviewStore(tmp_path / "reviews.sqlite3")
    store.initialize()
    subject = NewsReviewSubject(
        title="t",
        source_name=None,
        ai_verdict="rejected",
        business_date=date(2026, 10, 5),
        slot="morning",
    )
    at = datetime(2026, 10, 5, 9, 0, tzinfo=ZONE)
    await store.record(
        key="vn1_" + "a" * 24, decision="exclude", note=None, subject=subject, now=at
    )
    # The later call on the same item and day wins.
    await store.record(
        key="vn1_" + "a" * 24,
        decision="include",
        note=None,
        subject=subject,
        now=at.replace(hour=10),
    )
    await store.record(
        key="vn1_" + "b" * 24,
        decision="exclude",
        note=None,
        subject=NewsReviewSubject(
            title="t",
            source_name=None,
            ai_verdict="selected",
            business_date=date(2026, 10, 5),
            slot="noon",
        ),
        now=at,
    )
    await store.record(key="vn1_" + "c" * 24, decision="agree", note=None, subject=subject, now=at)
    decisions = await store.daily_decisions((date(2026, 10, 5),), timezone="Asia/Shanghai")
    assert decisions[date(2026, 10, 5)] == {
        "agree": 1,
        "include_override": 1,
        "exclude_override": 1,
    }
    assert await store.daily_counts((date(2026, 10, 5),), timezone="Asia/Shanghai") == {
        date(2026, 10, 5): (3, 2)
    }


@pytest.mark.asyncio
async def test_copy_signals_prefer_the_review_rule_over_a_generic_error_code() -> None:
    day = date(2026, 10, 5)
    copy_rows = [
        (day, "review_required", "repair_validation_failed", ["unverified_superlative"]),
        (day, "failed", "provider_request_rejected", None),
        (day, "review_required", None, []),
    ]

    class _Result:
        def __init__(self, rows: list[object]) -> None:
            self._rows = rows

        def all(self) -> list[object]:
            return self._rows

    class _Session:
        calls = 0

        async def execute(self, _statement: object) -> _Result:
            _Session.calls += 1
            return _Result(copy_rows if _Session.calls == 1 else [])

        async def scalars(self, _statement: object) -> list[object]:
            return []

    signals = await load_issue_signals(_Session(), today=day)  # type: ignore[arg-type]
    assert {(signal.code, signal.count) for signal in signals} == {
        ("copy:unverified_superlative", 1),
        ("copy:provider_request_rejected", 1),
        ("copy:review_required", 1),
    }
