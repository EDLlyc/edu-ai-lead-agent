"""Load the copy repair outcome rows (plain SELECTs; works for the app role and the ops role)."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.repair_metrics import RepairRunRow, RepairStats, summarize

_ROWS = """
WITH runs AS (
    SELECT r.id, r.business_date, r.status, r.repair_count
    FROM copy_generation_runs r
    WHERE r.business_date BETWEEN :start AND :end AND r.timezone = :timezone
),
draft_two AS (
    SELECT DISTINCT ON (d.run_id) d.run_id, a.safe_metadata, a.prompt_tokens
    FROM copy_draft_versions d
    JOIN copy_generation_attempts a ON a.draft_version_id = d.id
    WHERE d.run_id IN (SELECT id FROM runs) AND d.version = 2
      AND a.capability = 'generation' AND a.status = 'succeeded'
    ORDER BY d.run_id, a.created_at DESC
),
fallback AS (
    SELECT DISTINCT ON (j.run_id) j.run_id, a.error_code, a.safe_metadata
    FROM copy_generation_attempts a
    JOIN copy_generation_jobs j ON j.id = a.job_id
    WHERE j.run_id IN (SELECT id FROM runs)
      AND a.capability = 'workflow' AND a.error_code LIKE 'repair\\_agent\\_%'
    ORDER BY j.run_id, a.created_at DESC
)
SELECT runs.id, runs.business_date, runs.status, runs.repair_count,
       draft_two.safe_metadata, coalesce(draft_two.prompt_tokens, 0),
       fallback.error_code, fallback.safe_metadata
FROM runs
LEFT JOIN draft_two ON draft_two.run_id = runs.id
LEFT JOIN fallback ON fallback.run_id = runs.id
WHERE runs.repair_count >= 1 OR fallback.run_id IS NOT NULL
ORDER BY runs.business_date, runs.id
"""


def _mapping(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


async def load_repair_rows(
    session: AsyncSession, *, start: date, end: date, timezone: str
) -> list[RepairRunRow]:
    if end < start:
        raise ValueError("the window ends before it starts")
    result = await session.execute(text(_ROWS), {"start": start, "end": end, "timezone": timezone})
    return [
        RepairRunRow(
            run_id=str(row[0]),
            business_date=row[1],
            status=str(row[2]),
            repair_count=int(row[3] or 0),
            draft_two_metadata=_mapping(row[4]),
            draft_two_prompt_tokens=int(row[5] or 0),
            fallback_error_code=row[6],
            fallback_metadata=_mapping(row[7]),
        )
        for row in result.all()
    ]


async def load_repair_stats(
    session: AsyncSession, *, start: date, end: date, timezone: str
) -> RepairStats:
    rows = await load_repair_rows(session, start=start, end=end, timezone=timezone)
    return summarize(rows, start=start, end=end)
