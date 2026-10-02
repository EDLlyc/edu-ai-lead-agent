"""Online outcome of the copy repair: tool-using agent first, full regeneration as fallback.

One row per copy run that used its single repair (or whose agent attempt was recorded). The agent
outcome comes from what the copy executor stores: an accepted agent draft 2 carries
`repair_method=agent` in its generation attempt; a dropped agent draft leaves one `workflow`
attempt with a `repair_agent_*` error code and the agent's stop reason, rounds, calls and tokens.
"""

# ruff: noqa: RUF001

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

FALLBACK_LABELS = {
    "repair_agent_no_fix": "Agent 没有改动或放弃",
    "repair_agent_rules_failed": "改后仍不过规则",
    "repair_agent_audit_blocked": "改后仍被审查拦",
    "repair_agent_gate_error": "审查调用出错",
    "repair_agent_timeout": "超时",
    "repair_agent_error": "Agent 出错",
}


@dataclass(frozen=True, slots=True)
class RepairRunRow:
    run_id: str
    business_date: date
    status: str
    repair_count: int
    # metadata of the generation attempt that produced draft 2 (None: no draft 2)
    draft_two_metadata: Mapping[str, Any] | None
    draft_two_prompt_tokens: int
    # the agent's dropped attempt, if any: error code and safe metadata
    fallback_error_code: str | None
    fallback_metadata: Mapping[str, Any] | None


@dataclass(slots=True)
class RepairStats:
    start: date
    end: date
    repaired_runs: int = 0
    agent_attempted: int = 0
    agent_accepted: int = 0
    fallbacks: Counter[str] = field(default_factory=Counter)
    fallback_then_accepted: int = 0
    regeneration_only: int = 0
    regeneration_only_accepted: int = 0
    final_accepted: int = 0
    final_review_required: int = 0
    agent_rounds: int = 0
    agent_tool_calls: int = 0
    agent_prompt_tokens: int = 0
    stop_reasons: Counter[str] = field(default_factory=Counter)

    @property
    def agent_accept_rate(self) -> float | None:
        return self.agent_accepted / self.agent_attempted if self.agent_attempted else None

    def averages(self) -> dict[str, float]:
        n = self.agent_attempted
        if not n:
            return {}
        return {
            "rounds": self.agent_rounds / n,
            "tool_calls": self.agent_tool_calls / n,
            "prompt_tokens": self.agent_prompt_tokens / n,
        }


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def summarize(rows: Sequence[RepairRunRow], *, start: date, end: date) -> RepairStats:
    stats = RepairStats(start=start, end=end)
    for row in rows:
        by_agent = (row.draft_two_metadata or {}).get("repair_method") == "agent"
        attempted = by_agent or row.fallback_error_code is not None
        if row.repair_count < 1 and not attempted:
            continue
        stats.repaired_runs += 1
        accepted = row.status == "accepted"
        stats.final_accepted += accepted
        stats.final_review_required += row.status == "review_required"
        if not attempted:
            stats.regeneration_only += 1
            stats.regeneration_only_accepted += accepted
            continue
        stats.agent_attempted += 1
        if by_agent:
            meta = row.draft_two_metadata or {}
            stats.agent_accepted += 1
            stats.agent_prompt_tokens += row.draft_two_prompt_tokens
        else:
            meta = row.fallback_metadata or {}
            stats.fallbacks[str(row.fallback_error_code)] += 1
            stats.fallback_then_accepted += accepted
            stats.agent_prompt_tokens += _int(meta.get("agent_prompt_tokens"))
        stats.agent_rounds += _int(meta.get("rounds"))
        stats.agent_tool_calls += _int(meta.get("tool_calls"))
        if meta.get("stopped"):
            stats.stop_reasons[str(meta["stopped"])] += 1
    return stats


def render_lines(stats: RepairStats) -> list[str]:
    """Markdown lines for the daily report (Chinese, numbers only, no copy text)."""

    window = f"{stats.start.isoformat()} 至 {stats.end.isoformat()}"
    lines = [f"- 统计区间：{window}；用掉修复机会的文案 {stats.repaired_runs} 条。"]
    if not stats.repaired_runs:
        return lines
    if stats.agent_attempted:
        rate = stats.agent_accept_rate or 0.0
        averages = stats.averages()
        lines.append(
            f"- 修复 Agent 先修 {stats.agent_attempted} 条：Agent 修好并通过审查 "
            f"{stats.agent_accepted} 条（{rate:.0%}），平均 {averages['rounds']:.1f} 轮、"
            f"{averages['tool_calls']:.1f} 次工具调用、"
            f"输入 {averages['prompt_tokens']:,.0f} token。"
        )
    if stats.fallbacks:
        reasons = "、".join(
            f"{FALLBACK_LABELS.get(code, code)} {count}"
            for code, count in stats.fallbacks.most_common()
        )
        lines.append(
            f"- 退回整篇重写 {sum(stats.fallbacks.values())} 条（{reasons}），"
            f"重写后通过 {stats.fallback_then_accepted} 条。"
        )
    if stats.regeneration_only:
        lines.append(
            f"- 没走 Agent、直接整篇重写 {stats.regeneration_only} 条（上线前或旧规则版本），"
            f"通过 {stats.regeneration_only_accepted} 条。"
        )
    lines.append(
        f"- 最终通过 {stats.final_accepted} 条，需人工审核 {stats.final_review_required} 条。"
    )
    return lines
