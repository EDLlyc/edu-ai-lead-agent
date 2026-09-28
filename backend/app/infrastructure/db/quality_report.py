"""Read-only projections of one business day of production activity for the quality report."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.content_slots import is_same_topic
from app.domain.quality_report import (
    BrandStatementRow,
    BrandUsageRow,
    ModelUsage,
    QualitySnapshot,
    SameTopicPair,
    SelectedTopicRow,
    SlotRunRow,
)
from app.infrastructure.db.content_slots import _fingerprints_for_versions


def business_day_bounds(business_date: date, timezone: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone)
    start = datetime.combine(business_date, time.min, tzinfo=zone)
    return start, start + timedelta(days=1)


async def _rows(session: AsyncSession, sql: str, **params: Any) -> list[Any]:
    return list((await session.execute(text(sql), params)).all())


def _count(rows: list[Any]) -> Counter[str]:
    return Counter({str(row[0] or "none"): int(row[1]) for row in rows})


async def _model_usage(
    session: AsyncSession, table: str, start: datetime, end: datetime
) -> ModelUsage:
    # `table` is one of two fixed internal names, never user input.
    row = (
        await session.execute(
            text(
                f"""
                SELECT count(*),
                       count(*) FILTER (WHERE status NOT IN ('succeeded', 'completed')),
                       coalesce(sum(prompt_tokens), 0),
                       coalesce(sum(completion_tokens), 0),
                       avg(latency_ms)
                FROM {table}
                WHERE created_at >= :start AND created_at < :end
                """
            ),
            {"start": start, "end": end},
        )
    ).one()
    return ModelUsage(
        calls=int(row[0]),
        failed_calls=int(row[1]),
        prompt_tokens=int(row[2]),
        completion_tokens=int(row[3]),
        average_latency_ms=int(row[4]) if row[4] is not None else None,
    )


async def _same_topic_pairs(
    session: AsyncSession, selection_rows: list[Any]
) -> list[SameTopicPair]:
    """Same-day selections that the v2 same-topic rule would treat as one story."""

    labels = {
        UUID(str(row[7])): "human" if row[8] else f"{row[0]}#{row[1]}" for row in selection_rows
    }
    fingerprints = await _fingerprints_for_versions(session, list(labels))
    ordered = [(labels[version_id], fingerprints.get(version_id)) for version_id in labels]
    pairs: list[SameTopicPair] = []
    for index, (left_label, left) in enumerate(ordered):
        for right_label, right in ordered[index + 1 :]:
            if left is not None and right is not None and is_same_topic(left, right):
                pairs.append(SameTopicPair(left=left_label, right=right_label))
    return pairs


async def load_quality_snapshot(
    session: AsyncSession,
    *,
    business_date: date,
    timezone: str,
    lookback_days: int = 7,
) -> QualitySnapshot:
    """Collect one business day of pipeline outcomes. Every statement is a plain SELECT."""

    if lookback_days < 1:
        raise ValueError("lookback days must be positive")
    snapshot = QualitySnapshot(
        business_date=business_date, timezone=timezone, lookback_days=lookback_days
    )
    start, end = business_day_bounds(business_date, timezone)
    params = {"business_date": business_date, "timezone": timezone}

    acquisition = (
        await session.execute(
            text(
                """
                SELECT count(*), coalesce(sum(new_count), 0), coalesce(sum(failed_jobs), 0)
                FROM acquisition_runs
                WHERE business_date = :business_date AND timezone = :timezone
                """
            ),
            params,
        )
    ).one()
    snapshot.acquisition_runs = int(acquisition[0])
    snapshot.acquisition_new_items = int(acquisition[1])
    snapshot.acquisition_failed_jobs = int(acquisition[2])
    snapshot.acquisition_error_codes = _count(
        await _rows(
            session,
            """
            SELECT j.error_code, count(*)
            FROM acquisition_jobs j JOIN acquisition_runs r ON r.id = j.run_id
            WHERE r.business_date = :business_date AND r.timezone = :timezone
              AND j.status = 'failed'
            GROUP BY j.error_code
            """,
            **params,
        )
    )
    snapshot.acquisition_failed_sources = _count(
        await _rows(
            session,
            """
            SELECT concat(s.slug, ':', coalesce(j.error_code, 'none')), count(*)
            FROM acquisition_jobs j
            JOIN acquisition_runs r ON r.id = j.run_id
            JOIN sources s ON s.id = j.source_id
            WHERE r.business_date = :business_date AND r.timezone = :timezone
              AND j.status = 'failed'
            GROUP BY 1
            """,
            **params,
        )
    )

    # The newest run per slot is the one that owns the day's decision.
    snapshot.slot_runs = [
        SlotRunRow(
            content_slot=row[0],
            status=row[1],
            scoring_version=row[2],
            selected_count=int(row[3]),
            unfilled_count=int(row[4]),
            unfilled_reason_codes=tuple(str(code) for code in (row[5] or [])),
            error_code=row[6],
        )
        for row in await _rows(
            session,
            """
            SELECT DISTINCT ON (content_slot)
                   content_slot, status, config_snapshot ->> 'version', selected_count,
                   unfilled_count, unfilled_reason_codes, error_code
            FROM content_slot_runs
            WHERE business_date = :business_date AND timezone = :timezone
              AND trigger <> 'human'
            ORDER BY content_slot, created_at DESC
            """,
            **params,
        )
    ]
    selection_rows = await _rows(
        session,
        """
        SELECT s.content_slot, s.ordinal, v.representative_title,
               sc.explanation ->> 'priority_reason',
               sc.explanation ->> 'education_policy_level',
               sc.explanation ->> 'science_tech_editorial_cohort',
               left(v.summary_projection ->> 'summary', 600),
               s.selected_event_version_id,
               r.trigger = 'human'
        FROM content_slot_selections s
        JOIN content_slot_runs r ON r.id = s.run_id
        JOIN content_slot_scores sc ON sc.id = s.score_id
        JOIN event_cluster_versions v ON v.id = s.selected_event_version_id
        WHERE s.business_date = :business_date AND s.timezone = :timezone
        ORDER BY r.trigger = 'human', s.content_slot, s.ordinal, r.created_at
        """,
        **params,
    )
    snapshot.selected_topics = [
        SelectedTopicRow(
            content_slot=row[0],
            ordinal=int(row[1]),
            title=row[2],
            priority_reason=row[3],
            education_policy_level=row[4],
            cohort=row[5],
            summary=row[6],
            human_pick=bool(row[8]),
        )
        for row in selection_rows
    ]
    snapshot.same_topic_pairs = await _same_topic_pairs(session, selection_rows)

    copy_filter = """
        FROM copy_generation_runs r
        WHERE r.business_date = :business_date AND r.timezone = :timezone
          AND r.content_slot_selection_id IS NOT NULL
    """
    snapshot.copy_status = _count(
        await _rows(session, f"SELECT r.status, count(*) {copy_filter} GROUP BY r.status", **params)
    )
    snapshot.copy_prompt_versions = _count(
        await _rows(
            session,
            f"SELECT r.version_bundle ->> 'generator_prompt_version', count(*) {copy_filter} "
            "GROUP BY 1",
            **params,
        )
    )
    snapshot.copy_first_pass_accepted = int(
        (
            await session.execute(
                text(
                    f"SELECT count(*) {copy_filter} AND r.status = 'accepted' "
                    "AND r.repair_count = 0"
                ),
                params,
            )
        ).scalar_one()
    )
    snapshot.copy_error_codes = _count(
        await _rows(
            session,
            f"SELECT r.error_code, count(*) {copy_filter} AND r.error_code IS NOT NULL "
            "GROUP BY r.error_code",
            **params,
        )
    )
    snapshot.copy_issue_codes = _count(
        await _rows(
            session,
            """
            SELECT i.code, count(*)
            FROM copy_issues i
            JOIN copy_draft_versions d ON d.id = i.draft_version_id
            JOIN copy_generation_runs r ON r.id = d.run_id
            WHERE r.business_date = :business_date AND r.timezone = :timezone
            GROUP BY i.code
            """,
            **params,
        )
    )

    window_start = business_date - timedelta(days=lookback_days - 1)
    window_params = {**params, "window_start": window_start}
    snapshot.brand_window_accepted_runs = int(
        (
            await session.execute(
                text(
                    """
                    SELECT count(*) FROM copy_generation_runs
                    WHERE business_date BETWEEN :window_start AND :business_date
                      AND timezone = :timezone AND status = 'accepted'
                      AND active_draft_version_id IS NOT NULL
                    """
                ),
                window_params,
            )
        ).scalar_one()
    )
    snapshot.brand_usage = [
        BrandUsageRow(label=str(row[0]), runs=int(row[1]))
        for row in await _rows(
            session,
            """
            SELECT concat_ws(
                       ' / ',
                       doc.title,
                       coalesce(
                           nullif(sec.title, ''),
                           left(regexp_replace(ch.text, '\s+', ' ', 'g'), 24) || '…'
                       )
                   ) AS label,
                   count(DISTINCT r.id) AS runs
            FROM copy_generation_runs r
            JOIN copy_draft_claims c ON c.draft_version_id = r.active_draft_version_id
            JOIN copy_claim_brand_bindings b ON b.claim_id = c.id
            JOIN brand_chunks ch ON ch.id = b.brand_chunk_id
            LEFT JOIN brand_sections sec ON sec.id = ch.section_id
            JOIN brand_document_versions dv ON dv.id = ch.version_id
            JOIN brand_documents doc ON doc.id = dv.document_id
            WHERE r.business_date BETWEEN :window_start AND :business_date
              AND r.timezone = :timezone AND r.status = 'accepted'
            GROUP BY ch.id, doc.title, sec.title, ch.text
            ORDER BY runs DESC, label
            LIMIT 5
            """,
            **window_params,
        )
    ]

    snapshot.brand_statements = [
        BrandStatementRow(
            run_id=str(row[0]),
            business_date=row[1],
            label=f"{row[2]}#{row[3]}" if row[2] is not None else None,
            text=row[4],
        )
        for row in await _rows(
            session,
            """
            SELECT r.id, r.business_date, s.content_slot, s.ordinal, c.text
            FROM copy_generation_runs r
            JOIN copy_draft_claims c
              ON c.draft_version_id = r.active_draft_version_id AND c.kind = 'brand_statement'
            LEFT JOIN content_slot_selections s ON s.id = r.content_slot_selection_id
            WHERE r.business_date BETWEEN :window_start AND :business_date
              AND r.timezone = :timezone AND r.status = 'accepted'
            ORDER BY r.business_date, s.content_slot, s.ordinal, r.id, c.ordinal
            """,
            **window_params,
        )
    ]

    image_rows = await _rows(
        session,
        """
        SELECT a.status, count(*), coalesce(sum(a.repair_count), 0)
        FROM image_artifacts a JOIN copy_generation_runs r ON r.id = a.run_id
        WHERE r.business_date = :business_date AND r.timezone = :timezone
        GROUP BY a.status
        """,
        **params,
    )
    snapshot.image_status = Counter({str(row[0]): int(row[1]) for row in image_rows})
    snapshot.image_repairs = sum(int(row[2]) for row in image_rows)

    delivery_filter = """
        FROM wecom_delivery_jobs j JOIN wecom_delivery_windows w ON w.id = j.delivery_window_id
        WHERE w.business_date = :business_date AND w.timezone = :timezone AND j.mode = 'formal'
    """
    snapshot.delivery_status = _count(
        await _rows(
            session, f"SELECT j.status, count(*) {delivery_filter} GROUP BY j.status", **params
        )
    )
    snapshot.delivery_error_codes = _count(
        await _rows(
            session,
            f"SELECT j.last_error_code, count(*) {delivery_filter} "
            "AND j.last_error_code IS NOT NULL GROUP BY j.last_error_code",
            **params,
        )
    )

    snapshot.infographic_status = _count(
        await _rows(
            session,
            """
            SELECT status, count(*) FROM news_infographic_jobs
            WHERE business_date = :business_date GROUP BY status
            """,
            business_date=business_date,
        )
    )
    snapshot.infographic_error_codes = _count(
        await _rows(
            session,
            """
            SELECT safe_error_code, count(*) FROM news_infographic_jobs
            WHERE business_date = :business_date AND safe_error_code IS NOT NULL
            GROUP BY safe_error_code
            """,
            business_date=business_date,
        )
    )
    snapshot.supplement_status = _count(
        await _rows(
            session,
            """
            SELECT s.status, count(*)
            FROM wecom_infographic_supplements s
            JOIN news_infographic_jobs n ON n.id = s.infographic_job_id
            WHERE n.business_date = :business_date
            GROUP BY s.status
            """,
            business_date=business_date,
        )
    )
    snapshot.official_account_draft_status = _count(
        await _rows(
            session,
            """
            SELECT status, count(*) FROM wechat_mp_draft_jobs
            WHERE created_at >= :start AND created_at < :end GROUP BY status
            """,
            start=start,
            end=end,
        )
    )
    snapshot.copy_model_usage = await _model_usage(session, "copy_generation_attempts", start, end)
    snapshot.governance_model_usage = await _model_usage(session, "model_invocations", start, end)
    return snapshot
