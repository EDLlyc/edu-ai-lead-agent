"""Write the weekly summary (this week next to the week before) as Markdown, JSON and a trend row.

    python -m app.weekly_report_main --end 2026-10-04 --reports-dir /reports --output-dir /out

`--end` is the last business date of the week (default: yesterday). `--reports-dir` holds the
watchdog, action-proposal and shadow logs (read only). The database is read in a READ ONLY
transaction.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.domain.weekly_report import (
    WeekStats,
    action_stats,
    jsonable,
    render,
    shadow_stats,
    trend_row,
    watchdog_stats,
    week_bounds,
)

TREND_HEADER = (
    "week_end",
    "posts_selected",
    "posts_delivered",
    "long_images",
    "agent_attempted",
    "agent_accepted",
    "watchdog_flagged",
    "diagnosed",
    "action_refs",
    "cooled_reuse",
    "copy_prompt_tokens",
)


async def _load(end: date, reports: Path) -> tuple[WeekStats, WeekStats]:
    from app.core.config import get_settings
    from app.infrastructure.db.session import create_engine, create_session_factory
    from app.infrastructure.db.weekly_report import load_week

    settings = get_settings()
    engine = create_engine(settings)
    weeks: list[WeekStats] = []
    try:
        for week_end in (end, end - timedelta(days=7)):
            start, stop = week_bounds(week_end)
            async with create_session_factory(engine)() as session:
                await session.execute(text("SET TRANSACTION READ ONLY"))
                stats = await load_week(
                    session, start=start, end=stop, timezone=settings.business_timezone
                )
                await session.rollback()
            stats.watchdog = watchdog_stats(reports / "delivery-watchdog", start, stop)
            stats.actions = action_stats(
                reports / "delivery-watchdog" / "action-proposals.jsonl", start, stop
            )
            stats.shadow = shadow_stats(reports / "copy-repair-shadow", start, stop)
            weeks.append(stats)
    finally:
        await engine.dispose()
    return weeks[0], weeks[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    end = args.end or (
        datetime.now(UTC).astimezone(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
    )
    current, previous = asyncio.run(_load(end, args.reports_dir))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.output_dir / f"week-{current.end.isoformat()}"
    markdown = render(current, previous)
    stem.with_suffix(".md").write_text(markdown, encoding="utf-8")
    stem.with_suffix(".json").write_text(
        json.dumps(
            {"current": jsonable(current), "previous": jsonable(previous)},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    trend = args.output_dir / "trend.csv"
    rows: list[list[str]] = []
    if trend.exists():
        with trend.open(encoding="utf-8") as handle:
            rows = [row for row in csv.reader(handle)][1:]
    rows = [row for row in rows if row and row[0] != current.end.isoformat()]
    rows.append([str(value) for value in trend_row(current)])
    with trend.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(TREND_HEADER)
        writer.writerows(sorted(rows))
    print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
