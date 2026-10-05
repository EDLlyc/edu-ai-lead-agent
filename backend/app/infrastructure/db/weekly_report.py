"""Database part of the weekly summary (plain SELECTs in a READ ONLY transaction)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.weekly_report import PostOutcome, WeekStats, missed_reasons
from app.infrastructure.db.repair_metrics import load_repair_stats

_POSTS = """
SELECT
  (SELECT coalesce(sum(selected_count), 0) FROM content_slot_runs
    WHERE business_date BETWEEN :start AND :end AND timezone = :timezone),
  (SELECT count(*) FROM wecom_delivery_jobs j
     JOIN wecom_delivery_windows w ON w.id = j.delivery_window_id
    WHERE w.business_date BETWEEN :start AND :end AND w.lane_key = 'slot'
      AND j.status = 'delivered'),
  (SELECT count(*) FROM news_infographic_jobs i
     JOIN wecom_delivery_jobs j ON j.id = i.base_job_id
     JOIN wecom_delivery_windows w ON w.id = j.delivery_window_id
    WHERE w.business_date BETWEEN :start AND :end AND w.lane_key = 'slot'
      AND j.status = 'delivered' AND i.status = 'ready')
"""

_POST_OUTCOMES = """
SELECT
  (SELECT r.status FROM copy_generation_runs r
    WHERE r.content_slot_selection_id = cs.id ORDER BY r.created_at DESC LIMIT 1),
  (SELECT a.status FROM image_artifacts a
     JOIN copy_generation_runs r ON r.id = a.run_id
    WHERE r.content_slot_selection_id = cs.id ORDER BY a.created_at DESC LIMIT 1),
  (SELECT j.status FROM wecom_delivery_jobs j
    WHERE j.content_slot_selection_id = cs.id ORDER BY j.created_at DESC LIMIT 1),
  (SELECT j.last_error_code FROM wecom_delivery_jobs j
    WHERE j.content_slot_selection_id = cs.id ORDER BY j.created_at DESC LIMIT 1)
FROM content_slot_selections cs
JOIN content_slot_runs sr ON sr.id = cs.run_id
WHERE cs.business_date BETWEEN :start AND :end AND cs.timezone = :timezone
  AND sr.trigger <> 'human'
"""

_COPY = """
SELECT count(*),
       count(*) FILTER (WHERE status = 'accepted'),
       count(*) FILTER (WHERE status = 'accepted' AND repair_count = 0),
       count(*) FILTER (WHERE status = 'review_required'),
       count(*) FILTER (WHERE status = 'failed')
FROM copy_generation_runs
WHERE business_date BETWEEN :start AND :end AND timezone = :timezone
  AND content_slot_selection_id IS NOT NULL
"""

_TOKENS = """
SELECT coalesce(sum(a.prompt_tokens), 0), coalesce(sum(a.completion_tokens), 0)
FROM copy_generation_attempts a
JOIN copy_generation_jobs j ON j.id = a.job_id
JOIN copy_generation_runs r ON r.id = j.run_id
WHERE r.business_date BETWEEN :start AND :end AND r.timezone = :timezone
"""

_VISUAL = """
SELECT count(*),
       count(*) FILTER (WHERE ref.selection_reason LIKE '%cooldown exhausted%'),
       count(DISTINCT ref.filename)
FROM image_artifacts a
JOIN image_artifact_references ref ON ref.image_artifact_id = a.id
JOIN copy_generation_runs r ON r.id = a.run_id
WHERE r.business_date BETWEEN :start AND :end AND r.timezone = :timezone
  AND ref.reference_role = 'action_reference' AND a.status = 'succeeded'
  AND ref.selector_version LIKE '%v3%'
"""

_IMAGE_FAILURES = """
SELECT count(*)
FROM image_artifacts a
JOIN copy_generation_runs r ON r.id = a.run_id
WHERE r.business_date BETWEEN :start AND :end AND r.timezone = :timezone
  AND a.status IN ('failed', 'review_required')
"""


async def load_week(session: AsyncSession, *, start: date, end: date, timezone: str) -> WeekStats:
    params = {"start": start, "end": end, "timezone": timezone}
    stats = WeekStats(start=start, end=end)
    posts = (await session.execute(text(_POSTS), params)).one()
    stats.posts_selected, stats.posts_delivered, stats.long_images_ready = (
        int(posts[0]),
        int(posts[1]),
        int(posts[2]),
    )
    copy = (await session.execute(text(_COPY), params)).one()
    (
        stats.copy_runs,
        stats.copy_accepted,
        stats.copy_first_pass,
        stats.copy_review_required,
        stats.copy_failed,
    ) = (int(value) for value in copy)
    tokens = (await session.execute(text(_TOKENS), params)).one()
    stats.copy_prompt_tokens, stats.copy_completion_tokens = int(tokens[0]), int(tokens[1])
    visual = (await session.execute(text(_VISUAL), params)).one()
    stats.action_refs, stats.cooled_reuse, stats.distinct_action_images = (
        int(visual[0]),
        int(visual[1]),
        int(visual[2]),
    )
    stats.image_failures = int((await session.execute(text(_IMAGE_FAILURES), params)).scalar_one())
    outcomes = [
        PostOutcome(
            copy_status=row[0], image_status=row[1], delivery_status=row[2], delivery_error=row[3]
        )
        for row in (await session.execute(text(_POST_OUTCOMES), params)).all()
    ]
    stats.missed_reasons = missed_reasons(outcomes)
    gap = stats.missed - sum(stats.missed_reasons.values())
    if gap > 0:  # selections the per-post query could not see
        stats.missed_reasons["other"] += gap
    stats.repair = await load_repair_stats(session, start=start, end=end, timezone=timezone)
    return stats
