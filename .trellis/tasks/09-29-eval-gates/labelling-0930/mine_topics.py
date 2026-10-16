"""Read-only: real scored headlines (last 30 days) with the AI outcome, for labelling.

Writes /out/topic-candidates.jsonl and /out/delivered-titles.jsonl. No provider call, no write.
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

SCORES = """
WITH scored AS (
    SELECT DISTINCT ON (s.event_id)
           s.event_id, s.event_version_id, r.business_date, r.content_slot, r.trigger,
           s.eligible, s.veto_codes, s.selected_ordinal, s.total, s.threshold, s.rank,
           s.explanation
    FROM content_slot_scores s
    JOIN content_slot_runs r ON r.id = s.run_id
    WHERE r.business_date BETWEEN DATE '2026-08-31' AND DATE '2026-09-29'
      AND r.trigger = 'scheduled'
    ORDER BY s.event_id, (s.selected_ordinal IS NOT NULL) DESC, r.business_date DESC
)
SELECT sc.*, v.representative_title AS title, v.summary_projection AS summary_projection,
       v.category_projection AS categories,
       (SELECT array_agg(DISTINCT o.trust_tier)
          FROM event_memberships m
          JOIN normalized_articles na ON na.id = m.normalized_article_id
          JOIN article_occurrences o ON o.candidate_id = na.candidate_id
         WHERE m.event_id = sc.event_id) AS tiers,
       (SELECT array_agg(DISTINCT src.slug)
          FROM event_memberships m
          JOIN normalized_articles na ON na.id = m.normalized_article_id
          JOIN article_occurrences o ON o.candidate_id = na.candidate_id
          JOIN sources src ON src.id = o.source_id
         WHERE m.event_id = sc.event_id) AS source_slugs,
       (SELECT ec.canonical_url
          FROM normalized_articles na
          JOIN evidence_candidates ec ON ec.id = na.candidate_id
         WHERE na.id = v.representative_article_id) AS source_url,
       EXISTS (
         SELECT 1 FROM content_slot_selections sel
         JOIN copy_generation_runs cr ON cr.content_slot_selection_id = sel.id
         JOIN material_packages mp ON mp.run_id = cr.id
         JOIN wecom_delivery_jobs j ON j.material_package_id = mp.id
        WHERE sel.selected_event_id = sc.event_id AND j.mode = 'formal'
          AND j.status = 'delivered') AS delivered
FROM scored sc
JOIN event_cluster_versions v ON v.id = sc.event_version_id
"""


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    out = Path("/out")
    async with engine.connect() as conn:
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        rows = (await conn.execute(text(SCORES))).mappings().all()
    await engine.dispose()
    with (out / "topic-candidates.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            record = dict(row)
            for key in ("event_id", "event_version_id"):
                record[key] = str(record[key])
            record["business_date"] = record["business_date"].isoformat()
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print("candidates", len(rows), "delivered", sum(1 for row in rows if row["delivered"]))


asyncio.run(main())
