"""Print the read-only daily production quality report."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.application.services.quality_report import assess, render_json, render_markdown
from app.core.config import get_settings
from app.infrastructure.db.quality_report import load_quality_snapshot
from app.infrastructure.db.session import create_engine, create_session_factory


async def _run(business_date: date | None, lookback_days: int, output: str) -> str:
    settings = get_settings()
    timezone = settings.business_timezone
    resolved_date = business_date or datetime.now(ZoneInfo(timezone)).date()
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            # The report never writes; the transaction is read-only at the database level too.
            await session.execute(text("SET TRANSACTION READ ONLY"))
            snapshot = await load_quality_snapshot(
                session,
                business_date=resolved_date,
                timezone=timezone,
                lookback_days=lookback_days,
            )
            await session.rollback()
    finally:
        await engine.dispose()
    findings = assess(snapshot)
    return (
        render_json(snapshot, findings) if output == "json" else render_markdown(snapshot, findings)
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--output", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)
    print(asyncio.run(_run(args.date, args.lookback_days, args.output)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
