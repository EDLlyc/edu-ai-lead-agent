# ruff: noqa: RUF001  (Chinese operator-facing report text)
"""Replay real content-slot candidate pools under alternative selection rules (read-only).

For every scheduled slot run in a date range, the governed candidate pool is re-loaded as it was
at that run's cutoff and re-ranked with each rule variant. Selections are deterministic: the LLM
rerank is not called. Repeat and same-day history inside the range comes from the variant's own
picks (treated as delivered), so a variant that re-picks yesterday's story is caught; history
before the range still comes from production.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from app.application.services.topic_selection import build_topic_scoring_config
from app.core.config import Settings, get_settings
from app.domain.content_slots import (
    ContentSlot,
    SlotRankingPolicy,
    TopicFingerprint,
    select_slot_topics,
)
from app.domain.topic_selection import TopicCandidate
from app.infrastructure.db.content_slots import (
    _fingerprints_for_versions,
    load_content_slot_topic_fingerprints,
)
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.topic_selection import load_governed_topic_candidates
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from evals.selection_replay.metrics import (
    MATCH_KINDS,
    SLOT_ORDER,
    ReplayPick,
    pick_order,
    slot_changes,
    summarize,
)

REPORT_VERSION = "selection-replay-v1"


@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    scoring_version: str
    slot_ranking_version: str


@dataclass(frozen=True, slots=True)
class SlotRun:
    run_id: str
    business_date: date
    timezone: str
    slot: str
    scoring_profile: str
    governed_event_cutoff: Any
    item_limit: int


def parse_variant(value: str) -> Variant:
    name, _, rest = value.partition("=")
    scoring, _, ranking = rest.partition("+")
    if not name or not scoring or not ranking:
        raise argparse.ArgumentTypeError("variant must be NAME=SCORING_VERSION+SLOT_RANKING")
    return Variant(name=name, scoring_version=scoring, slot_ranking_version=ranking)


async def load_slot_runs(
    session: AsyncSession, *, start: date, end: date, timezone: str
) -> list[SlotRun]:
    rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT ON (business_date, content_slot)
                       id, business_date, timezone, content_slot, scoring_profile,
                       governed_event_cutoff, item_limit
                FROM content_slot_runs
                WHERE business_date BETWEEN :start AND :end AND timezone = :timezone
                  AND status = 'succeeded' AND trigger <> 'human'
                ORDER BY business_date, content_slot, created_at DESC
                """
            ),
            {"start": start, "end": end, "timezone": timezone},
        )
    ).all()
    runs = [
        SlotRun(str(row[0]), row[1], row[2], row[3], row[4], row[5], int(row[6])) for row in rows
    ]
    return sorted(runs, key=lambda run: (run.business_date, SLOT_ORDER.index(run.slot)))


async def production_picks(session: AsyncSession, runs: Sequence[SlotRun]) -> list[ReplayPick]:
    if not runs:
        return []
    rows = (
        await session.execute(
            text(
                """
                SELECT s.business_date, s.content_slot, s.ordinal, s.selected_event_id,
                       s.selected_event_version_id, v.representative_title,
                       v.summary_projection ->> 'summary', sc.total, sc.passes_threshold,
                       sc.explanation ->> 'priority_reason'
                FROM content_slot_selections s
                JOIN content_slot_scores sc ON sc.id = s.score_id
                JOIN event_cluster_versions v ON v.id = s.selected_event_version_id
                WHERE s.run_id = ANY(CAST(:run_ids AS uuid[]))
                """
            ),
            {"run_ids": [run.run_id for run in runs]},
        )
    ).all()
    fingerprints = await _fingerprints_for_versions(session, [row[4] for row in rows])
    return sorted(
        (
            ReplayPick(
                business_date=row[0],
                slot=row[1],
                ordinal=int(row[2]),
                event_id=row[3],
                title=row[5],
                summary=row[6],
                total=float(row[7]),
                passes_threshold=bool(row[8]),
                priority_reason=row[9],
                embedding=fingerprints[row[4]].embedding if row[4] in fingerprints else None,
            )
            for row in rows
        ),
        key=pick_order,
    )


def _with_replay_history(
    candidates: tuple[TopicCandidate, ...],
    *,
    business_date: date,
    start: date,
    last_picked: dict[Any, date],
) -> tuple[TopicCandidate, ...]:
    """Keep production repeat history before the range; inside it use the variant's picks."""

    adjusted = []
    for candidate in candidates:
        dates = []
        if candidate.days_since_last_selection is not None:
            production_date = business_date - timedelta(days=candidate.days_since_last_selection)
            if production_date < start:
                dates.append(production_date)
        # Same-day picks are handled by the same-day exclusion, as in production.
        if candidate.event_id in last_picked and last_picked[candidate.event_id] < business_date:
            dates.append(last_picked[candidate.event_id])
        days = (business_date - max(dates)).days if dates else None
        adjusted.append(replace(candidate, days_since_last_selection=days))
    return tuple(adjusted)


async def replay_variant(
    session: AsyncSession, runs: Sequence[SlotRun], variant: Variant, *, start: date
) -> list[ReplayPick]:
    picks: list[ReplayPick] = []
    last_picked: dict[Any, date] = {}
    policy = SlotRankingPolicy(version=variant.slot_ranking_version)
    for run in runs:
        config = build_topic_scoring_config(
            Settings(
                _env_file=None,
                content_scoring_version=variant.scoring_version,
                content_scoring_profile=run.scoring_profile,
            )
        )
        candidates = await load_governed_topic_candidates(
            session,
            business_date=run.business_date,
            timezone=run.timezone,
            scoring_profile=run.scoring_profile,
            governed_event_cutoff=run.governed_event_cutoff,
            config_snapshot=config.as_metadata(),
            include_content_slot_history=True,
        )
        candidates = _with_replay_history(
            candidates, business_date=run.business_date, start=start, last_picked=last_picked
        )
        fingerprints: dict[Any, TopicFingerprint] = (
            await load_content_slot_topic_fingerprints(session, candidates)
            if policy.dedups_same_topic
            else {}
        )
        today = [pick for pick in picks if pick.business_date == run.business_date]
        decision = select_slot_topics(
            candidates,
            as_of=run.governed_event_cutoff,
            config=config,
            slot=ContentSlot(run.slot),
            policy=policy,
            max_items=run.item_limit,
            same_day_selected_event_ids=frozenset(pick.event_id for pick in today),
            topic_fingerprints=fingerprints,
            same_day_selected_topics=tuple(pick.fingerprint for pick in today),
        )
        by_id = {candidate.event_id: candidate for candidate in candidates}
        scores = {score.base.event_id: score.base for score in decision.scores}
        for ordinal, event_id in enumerate(decision.selected_event_ids, start=1):
            candidate, score = by_id[event_id], scores[event_id]
            fingerprint = fingerprints.get(event_id)
            picks.append(
                ReplayPick(
                    business_date=run.business_date,
                    slot=run.slot,
                    ordinal=ordinal,
                    event_id=event_id,
                    title=candidate.priority_title
                    or (fingerprint.title if fingerprint else str(event_id)),
                    summary=candidate.priority_summary or None,
                    total=score.total,
                    passes_threshold=score.passes_threshold,
                    priority_reason=score.priority_reason,
                    embedding=fingerprint.embedding if fingerprint else None,
                )
            )
            last_picked[event_id] = run.business_date
    return picks


async def build_report(
    session: AsyncSession,
    *,
    start: date,
    end: date,
    timezone: str,
    variants: Sequence[Variant],
) -> dict[str, object]:
    runs = await load_slot_runs(session, start=start, end=end, timezone=timezone)
    results = {"production": await production_picks(session, runs)}
    for variant in variants:
        results[variant.name] = await replay_variant(session, runs, variant, start=start)
    names = list(results)
    changes = slot_changes(results[names[-2]], results[names[-1]]) if len(names) >= 3 else []
    return {
        "report_version": REPORT_VERSION,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "slot_runs": len(runs),
        "variants": [
            {"name": "production", "scoring_version": "as recorded", "slot_ranking": "as recorded"}
        ]
        + [
            {
                "name": variant.name,
                "scoring_version": variant.scoring_version,
                "slot_ranking": variant.slot_ranking_version,
            }
            for variant in variants
        ],
        "summary": {name: summarize(picks) for name, picks in results.items()},
        "changes": {
            "from": names[-2] if len(names) >= 3 else None,
            "to": names[-1] if len(names) >= 3 else None,
            "slots": [
                {"slot": label, "removed": removed, "added": added}
                for label, removed, added in changes
            ],
        },
        "picks": {
            name: [
                {
                    "label": pick.label,
                    "title": pick.title,
                    "total": round(pick.total, 3),
                    "priority_reason": pick.priority_reason,
                }
                for pick in picks
            ]
            for name, picks in results.items()
        },
    }


_ROWS = (
    ("picks", "选出条数"),
    ("gov_yaowen_priority", "政府网要闻插队"),
    ("gov_yaowen_priority_off_topic", "　其中非科技/教育"),
    ("education_policy", "教育风向"),
    ("negative_incident", "负面事件"),
    ("specialised_research", "过专科研"),
    ("below_threshold", "低于分数线"),
    ("same_day_same_topic", "同日同题（对）"),
    ("cross_day_repeats", "14 天内重复"),
    ("cross_day_repeats_by_kind", "　按判定：同一事件/语义相似/仅标题"),
    ("mean_total", "平均分"),
)


def render_markdown(report: dict[str, Any]) -> str:
    names = [variant["name"] for variant in report["variants"]]
    summary = report["summary"]
    lines = [
        f"# 选题回放评测 {report['start']} ~ {report['end']}",
        "",
        f"- 时段数：{report['slot_runs']}；回放为确定性排序（不调用 LLM 重排），"
        "区间内的已推历史按各方案自己的选择计算。",
        "- 方案："
        + "；".join(
            f"{variant['name']} = {variant['scoring_version']} + {variant['slot_ranking']}"
            for variant in report["variants"]
        ),
        "",
        "| 指标 | " + " | ".join(names) + " |",
        "|---" * (len(names) + 1) + "|",
    ]
    for key, label in _ROWS:
        values = []
        for name in names:
            value = summary[name][key]
            if isinstance(value, dict):
                values.append("/".join(str(value.get(kind, 0)) for kind in MATCH_KINDS))
            else:
                values.append(str(len(value)) if isinstance(value, list) else str(value))
        lines.append(f"| {label} | " + " | ".join(values) + " |")
    for name in names:
        details = [
            (label, summary[name][key])
            for key, label in _ROWS
            if isinstance(summary[name][key], list) and summary[name][key]
        ]
        if details:
            lines += ["", f"## {name} 的问题明细", ""]
            for label, items in details:
                lines.append(f"- {label.strip('　')}：")
                lines += [f"  - {item}" for item in items]
    changes = report["changes"]
    if changes["from"]:
        lines += ["", f"## {changes['to']} 相对 {changes['from']} 的逐时段变化", ""]
        if not changes["slots"]:
            lines.append("无变化。")
        for row in changes["slots"]:
            lines.append(f"- {row['slot']}")
            lines += [f"  - − {title}" for title in row["removed"]]
            lines += [f"  - + {title}" for title in row["added"]]
    lines.append("")
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> dict[str, object]:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            report = await build_report(
                session,
                start=args.start,
                end=args.end,
                timezone=settings.business_timezone,
                variants=args.variant,
            )
            await session.rollback()
    finally:
        await engine.dispose()
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--variant",
        type=parse_variant,
        action="append",
        help="NAME=SCORING_VERSION+SLOT_RANKING, e.g. "
        "v15=scoring-v1-preview.15-gov-yaowen-topic-gate+slot-ranking-v2-same-topic-dedup",
    )
    parser.add_argument("--output", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)
    if not args.variant:
        parser.error("at least one --variant is required")
    report = asyncio.run(_run(args))
    if args.output == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
