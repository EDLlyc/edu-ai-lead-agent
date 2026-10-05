# ruff: noqa: RUF001
"""Weekly summary: log readers, rendering and the trend file."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from app.domain.repair_metrics import RepairRunRow, summarize
from app.domain.weekly_report import (
    WeekStats,
    action_stats,
    jsonable,
    render,
    shadow_stats,
    watchdog_stats,
    week_bounds,
)

END = date(2026, 10, 4)
START = date(2026, 9, 28)


def _write(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def test_week_bounds_cover_seven_business_days() -> None:
    assert week_bounds(END) == (START, END)


def test_log_readers_count_only_the_window(tmp_path: Path) -> None:
    watchdog = tmp_path / "delivery-watchdog"
    _write(
        watchdog / "watchdog-2026-10-03.jsonl",
        [
            {"business_date": "2026-10-03", "slot": "noon", "ok": True, "proposals": []},
            {"business_date": "2026-10-03", "slot": "evening", "ok": True, "proposals": []},
            {  # a manual re-run of the same slot counts once
                "business_date": "2026-10-03",
                "slot": "evening",
                "ok": False,
                "diagnosis": {"stopped": "reported", "stage": "image", "prompt_tokens": 15_020},
                "proposals": [],
            },
        ],
    )
    _write(watchdog / "watchdog-2026-09-20.jsonl", [{"business_date": "2026-09-20", "ok": False}])
    _write(
        watchdog / "action-proposals.jsonl",
        [
            {"event": "proposed", "at": "2026-10-02T10:42:00+00:00", "proposal": {}},
            {"event": "approved", "id": "a", "at": "2026-10-02T10:50:00+00:00"},
            {"event": "executed", "id": "a", "at": "2026-10-02T10:50:01+00:00"},
            {"event": "proposed", "at": "2026-09-01T10:42:00+00:00", "proposal": {}},
        ],
    )
    shadow = tmp_path / "copy-repair-shadow"
    _write(
        shadow / "copy-repair-shadow-2026-10-03.jsonl",
        [
            {  # v2: production used the agent, the shadow regenerated
                "business_date": "2026-10-03",
                "agent": {"source": "production", "passed": True},
                "regeneration": {"source": "shadow", "passed": False},
            },
            {  # v1: shadow agent vs production regeneration
                "business_date": "2026-10-01",
                "agent": {"passed": True},
                "production": {"passed": True},
            },
        ],
    )

    w = watchdog_stats(watchdog, START, END)
    a = action_stats(watchdog / "action-proposals.jsonl", START, END)
    s = shadow_stats(shadow, START, END)

    assert (w.checks, w.flagged, w.diagnosed, dict(w.stages)) == (2, 1, 1, {"image": 1})
    assert w.diagnosis_tokens == 15_020
    assert (a.proposed, a.approved, a.executed) == (1, 1, 1)
    assert (s.cases, s.agent_passed, s.regeneration_passed, s.both) == (2, 2, 1, 1)


def test_missing_logs_give_zeros(tmp_path: Path) -> None:
    assert watchdog_stats(tmp_path / "none", START, END).checks == 0
    assert action_stats(tmp_path / "none.jsonl", START, END).proposed == 0
    assert shadow_stats(tmp_path / "none", START, END).cases == 0


def _week(**values: object) -> WeekStats:
    stats = WeekStats(start=START, end=END)
    for name, value in values.items():
        setattr(stats, name, value)
    return stats


def test_render_compares_with_the_previous_week_and_explains() -> None:
    repair_rows = [
        RepairRunRow(
            "a", END, "accepted", 1, {"repair_method": "agent", "rounds": 5}, 11_000, None, None
        ),
        RepairRunRow(
            "b", END, "accepted", 1, {"draft_version": 2}, 6_000, "repair_agent_no_fix", {}
        ),
    ]
    current = _week(
        posts_selected=21,
        posts_delivered=19,
        long_images_ready=18,
        copy_accepted=21,
        copy_first_pass=15,
        action_refs=32,
        cooled_reuse=0,
        distinct_action_images=19,
        repair=summarize(repair_rows, start=START, end=END),
    )
    current.watchdog.checks, current.watchdog.flagged, current.watchdog.diagnosed = 21, 1, 1
    current.watchdog.stages["image"] = 1
    previous = _week(posts_selected=27, posts_delivered=27, action_refs=36, cooled_reuse=16)

    text = render(current, previous)

    assert "| 计划推送 / 送达 / 少发 | 21 / 19 / 2 | 27 / 27 / 0 |" in text
    assert "| 长图覆盖 | 18/19（95%） |" in text
    assert "| Agent 修好率 | 50% | - |" in text
    assert "32 / 0（0%） / 19" in text and "36 / 16（44%）" in text
    assert "Agent 没有改动或放弃 1" in text and "配图 1" in text and "少发 2 条" in text
    payload = jsonable(current)
    assert payload["missed"] == 2 and payload["repair"]["agent_accepted"] == 1  # type: ignore[index]


@pytest.mark.parametrize("missing", [0, 3])
def test_missed_is_never_negative(missing: int) -> None:
    stats = _week(posts_selected=5, posts_delivered=5 - missing)
    assert stats.missed == missing


def test_missed_posts_are_classified_by_where_they_stopped() -> None:
    from app.domain.weekly_report import PostOutcome, missed_reasons

    posts = [
        PostOutcome("accepted", "succeeded", "delivered", None),
        PostOutcome("accepted", "succeeded", "cancelled", "operator_noon_maintenance_hold"),
        PostOutcome("review_required", None, None, None),
        PostOutcome(None, None, None, None),
        PostOutcome("accepted", "review_required", None, None),
        PostOutcome("accepted", "succeeded", "failed", "wecom_rate_limited"),
        PostOutcome("accepted", "succeeded", None, None),
    ]

    assert missed_reasons(posts) == {
        "operator_hold": 1,
        "copy": 2,
        "image": 1,
        "delivery": 1,
        "other": 1,
    }


def test_shadow_stats_can_keep_only_the_current_agent_version(tmp_path: Path) -> None:
    shadow = tmp_path / "copy-repair-shadow"
    _write(
        shadow / "copy-repair-shadow-2026-10-03.jsonl",
        [
            {
                "business_date": "2026-10-01",
                "agent_version": "v3",
                "agent": {"passed": False},
                "production": {"passed": True},
            },
            {
                "business_date": "2026-10-04",
                "agent": {"agent_version": "v4", "passed": True},
                "regeneration": {"passed": False},
            },
        ],
    )

    every = shadow_stats(shadow, START, END)
    current = shadow_stats(shadow, START, END, agent_version="v4")

    assert (every.cases, every.agent_passed) == (2, 1)
    assert (current.cases, current.agent_passed, current.regeneration_passed) == (1, 1, 0)


def test_render_lists_missed_reasons() -> None:
    from collections import Counter

    current = _week(posts_selected=21, posts_delivered=18)
    current.missed_reasons = Counter({"image": 2, "operator_hold": 1})

    text = render(current, _week())

    assert "| 少发原因 | 配图失败 2、运营暂停 1 | - |" in text
    assert "本周少发 3 条：配图失败 2、运营暂停 1。" in text
