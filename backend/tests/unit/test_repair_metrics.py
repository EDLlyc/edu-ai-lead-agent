# ruff: noqa: RUF001
"""Online repair statistics: agent first, regeneration as fallback."""

from __future__ import annotations

from datetime import date

from app.application.services.ops_tools import repair_stats_result
from app.domain.quality_report import QualitySnapshot
from app.domain.repair_metrics import RepairRunRow, render_lines, summarize

DAY = date(2026, 10, 2)


def _row(
    status: str,
    *,
    repair_count: int = 1,
    agent: bool = False,
    fallback: str | None = None,
) -> RepairRunRow:
    return RepairRunRow(
        run_id=f"run-{status}-{agent}-{fallback}",
        business_date=DAY,
        status=status,
        repair_count=repair_count,
        draft_two_metadata=(
            {"repair_method": "agent", "stopped": "checked", "rounds": 2, "tool_calls": 3}
            if agent
            else ({"draft_version": 2} if repair_count else None)
        ),
        draft_two_prompt_tokens=5_000 if agent else 7_000,
        fallback_error_code=fallback,
        fallback_metadata=(
            {"stopped": "finished", "rounds": 3, "tool_calls": 4, "agent_prompt_tokens": 6_000}
            if fallback
            else None
        ),
    )


def test_summary_separates_agent_fixes_fallbacks_and_regeneration_only() -> None:
    rows = [
        _row("accepted", agent=True),
        _row("accepted", agent=True),
        _row("accepted", fallback="repair_agent_audit_blocked"),
        _row("review_required", fallback="repair_agent_rules_failed"),
        _row("accepted"),  # before agent_first, or an older rule version
        _row("accepted", repair_count=0),  # first pass: not a repair at all
    ]

    stats = summarize(rows, start=DAY, end=DAY)

    assert stats.repaired_runs == 5
    assert (stats.agent_attempted, stats.agent_accepted) == (4, 2)
    assert stats.agent_accept_rate == 0.5
    assert dict(stats.fallbacks) == {
        "repair_agent_audit_blocked": 1,
        "repair_agent_rules_failed": 1,
    }
    assert stats.fallback_then_accepted == 1
    assert (stats.regeneration_only, stats.regeneration_only_accepted) == (1, 1)
    assert (stats.final_accepted, stats.final_review_required) == (4, 1)
    # Agent tokens: 5,000 x 2 accepted drafts + 6,000 x 2 dropped attempts.
    assert stats.averages() == {"rounds": 2.5, "tool_calls": 3.5, "prompt_tokens": 5_500.0}
    assert dict(stats.stop_reasons) == {"checked": 2, "finished": 2}

    text = "\n".join(render_lines(stats))
    assert "Agent 修好并通过审查 2 条（50%）" in text
    assert "改后仍被审查拦 1" in text and "改后仍不过规则 1" in text
    assert "直接整篇重写 1 条" in text and "需人工审核 1 条" in text


def test_a_quiet_window_says_so_and_the_tool_result_has_no_averages() -> None:
    stats = summarize([], start=DAY, end=DAY)

    assert render_lines(stats) == [
        "- 统计区间：2026-10-02 至 2026-10-02；用掉修复机会的文案 0 条。"
    ]
    result = repair_stats_result(stats)
    assert result.agent_accept_rate is None and result.avg_rounds is None


def test_the_quality_snapshot_carries_the_repair_section() -> None:
    from app.application.services.quality_report import render_markdown

    snapshot = QualitySnapshot(business_date=DAY, timezone="Asia/Shanghai", lookback_days=7)
    snapshot.repair_stats = summarize([_row("accepted", agent=True)], start=DAY, end=DAY)

    markdown = render_markdown(snapshot, [])

    assert "**修复 Agent（近 7 天）**" in markdown
    assert "修复 Agent 先修 1 条" in markdown
