"""Weekly summary of the online agent work, this week next to the week before.

One place for the numbers that otherwise live in daily reports, the watchdog log, the shadow log
and the database: posts and misses, long images, copy and the repair agent, diagnoses and action
proposals, reference-image reuse, and model tokens. Numbers only; no copy text.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.domain.repair_metrics import FALLBACK_LABELS, RepairStats

STAGE_LABELS = {
    "selection": "选题",
    "copy": "文案",
    "image": "配图",
    "delivery": "发送",
    "unknown": "未确定",
}


@dataclass(slots=True)
class WatchdogStats:
    checks: int = 0
    flagged: int = 0
    diagnosed: int = 0
    stages: Counter[str] = field(default_factory=Counter)
    proposals: int = 0
    diagnosis_tokens: int = 0


@dataclass(slots=True)
class ActionStats:
    proposed: int = 0
    approved: int = 0
    executed: int = 0
    rejected: int = 0
    expired: int = 0


@dataclass(slots=True)
class ShadowStats:
    cases: int = 0
    agent_passed: int = 0
    regeneration_passed: int = 0
    both: int = 0


@dataclass(slots=True)
class WeekStats:
    start: date
    end: date
    posts_selected: int = 0
    posts_delivered: int = 0
    long_images_ready: int = 0
    copy_runs: int = 0
    copy_accepted: int = 0
    copy_first_pass: int = 0
    copy_review_required: int = 0
    copy_failed: int = 0
    action_refs: int = 0
    cooled_reuse: int = 0
    distinct_action_images: int = 0
    image_failures: int = 0
    copy_prompt_tokens: int = 0
    copy_completion_tokens: int = 0
    missed_reasons: Counter[str] = field(default_factory=Counter)
    repair: RepairStats | None = None
    watchdog: WatchdogStats = field(default_factory=WatchdogStats)
    actions: ActionStats = field(default_factory=ActionStats)
    shadow: ShadowStats = field(default_factory=ShadowStats)

    @property
    def missed(self) -> int:
        return max(0, self.posts_selected - self.posts_delivered)


def week_bounds(end: date) -> tuple[date, date]:
    return end - timedelta(days=6), end


MISSED_LABELS = {
    "operator_hold": "运营暂停",
    "copy": "文案未通过",
    "image": "配图失败",
    "delivery": "发送失败",
    "other": "其他",
}


@dataclass(frozen=True, slots=True)
class PostOutcome:
    """One scheduled post: its newest copy run, image and delivery job states."""

    copy_status: str | None
    image_status: str | None
    delivery_status: str | None
    delivery_error: str | None


def missed_reason(post: PostOutcome) -> str | None:
    """Why a scheduled post was not delivered (None when it was)."""

    if post.delivery_status == "delivered":
        return None
    if post.delivery_status == "cancelled" and (post.delivery_error or "").startswith("operator_"):
        return "operator_hold"
    if post.copy_status != "accepted":
        return "copy"
    if post.delivery_status is None and post.image_status not in (None, "succeeded"):
        return "image"
    if post.delivery_status is not None:
        return "delivery"
    return "other"


def missed_reasons(posts: Iterable[PostOutcome]) -> Counter[str]:
    return Counter(reason for post in posts if (reason := missed_reason(post)) is not None)


def _in_window(value: object, start: date, end: date) -> bool:
    try:
        day = date.fromisoformat(str(value)[:10])
    except ValueError:
        return False
    return start <= day <= end


def _jsonl(paths: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def watchdog_stats(directory: Path, start: date, end: date) -> WatchdogStats:
    """One entry per business date and slot (manual re-runs of a slot count once)."""

    stats = WatchdogStats()
    if not directory.is_dir():
        return stats
    slots: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in _jsonl(sorted(directory.glob("watchdog-*.jsonl"))):
        if _in_window(record.get("business_date"), start, end):
            key = (str(record.get("business_date")), str(record.get("slot")))
            slots.setdefault(key, []).append(record)
    for records in slots.values():
        stats.checks += 1
        stats.flagged += any(not record.get("ok", True) for record in records)
        diagnoses = [
            record["diagnosis"]
            for record in records
            if isinstance(record.get("diagnosis"), Mapping)
            and record["diagnosis"].get("stopped") == "reported"
        ]
        if diagnoses:
            stats.diagnosed += 1
            stats.stages[str(diagnoses[-1].get("stage"))] += 1
        stats.diagnosis_tokens += sum(int(d.get("prompt_tokens") or 0) for d in diagnoses)
        stats.proposals += sum(len(record.get("proposals") or []) for record in records)
    return stats


def action_stats(path: Path, start: date, end: date) -> ActionStats:
    stats = ActionStats()
    if not path.is_file():
        return stats
    for event in _jsonl([path]):
        if not _in_window(event.get("at"), start, end):
            continue
        name = event.get("event")
        if name == "proposed":
            stats.proposed += 1
        elif name == "approved":
            stats.approved += 1
        elif name == "executed":
            stats.executed += 1
        elif name == "rejected":
            stats.rejected += 1
        elif name == "expired":
            stats.expired += 1
    return stats


def shadow_stats(
    directory: Path, start: date, end: date, *, agent_version: str | None = None
) -> ShadowStats:
    """Shadow pairs in the window; with `agent_version`, only that agent version's pairs."""

    stats = ShadowStats()
    if not directory.is_dir():
        return stats
    for record in _jsonl(sorted(directory.glob("copy-repair-shadow-*.jsonl"))):
        if not _in_window(record.get("business_date"), start, end):
            continue
        arm = record.get("agent") or {}
        version = arm.get("agent_version") or record.get("agent_version")
        if agent_version is not None and version != agent_version:
            continue
        agent = bool((record.get("agent") or {}).get("passed"))
        regeneration_arm = record.get("regeneration") or {
            "passed": (record.get("production") or {}).get("passed")
        }
        regeneration = bool(regeneration_arm.get("passed"))
        stats.cases += 1
        stats.agent_passed += agent
        stats.regeneration_passed += regeneration
        stats.both += agent and regeneration
    return stats


def _pct(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "-"


def _row(label: str, current: str, previous: str) -> str:
    return f"| {label} | {current} | {previous} |"


def render(current: WeekStats, previous: WeekStats) -> str:
    def both(fn: Any) -> tuple[str, str]:
        return fn(current), fn(previous)

    def repair_line(stats: WeekStats) -> str:
        repair = stats.repair
        if repair is None or not repair.repaired_runs:
            return "0"
        attempted, accepted = repair.agent_attempted, repair.agent_accepted
        return f"{repair.repaired_runs}（Agent 先修 {attempted}，修好 {accepted}）"

    def agent_rate(stats: WeekStats) -> str:
        repair = stats.repair
        if repair is None or not repair.agent_attempted:
            return "-"
        return _pct(repair.agent_accepted, repair.agent_attempted)

    def agent_tokens(stats: WeekStats) -> str:
        averages = stats.repair.averages() if stats.repair else {}
        return f"{averages['prompt_tokens']:,.0f}" if averages else "-"

    rows = [
        (
            "计划推送 / 送达 / 少发",
            lambda s: f"{s.posts_selected} / {s.posts_delivered} / {s.missed}",
        ),
        (
            "少发原因",
            lambda s: (
                "、".join(
                    f"{MISSED_LABELS.get(reason, reason)} {count}"
                    for reason, count in s.missed_reasons.most_common()
                )
                or "-"
            ),
        ),
        (
            "长图覆盖",
            lambda s: (
                f"{s.long_images_ready}/{s.posts_delivered}"
                f"（{_pct(s.long_images_ready, s.posts_delivered)}）"
            ),
        ),
        (
            "文案：通过 / 一次通过 / 待人工",
            lambda s: f"{s.copy_accepted} / {s.copy_first_pass} / {s.copy_review_required}",
        ),
        ("用掉修复机会", repair_line),
        ("Agent 修好率", agent_rate),
        ("Agent 每条输入 token", agent_tokens),
        (
            "影子对照（当前 Agent 版本）：Agent / 重写 修好",
            lambda s: (
                f"{s.shadow.agent_passed} / {s.shadow.regeneration_passed}（共 {s.shadow.cases}）"
                if s.shadow.cases
                else "-"
            ),
        ),
        (
            "漏发检查：检查 / 发现问题 / 诊断出结论",
            lambda s: f"{s.watchdog.checks} / {s.watchdog.flagged} / {s.watchdog.diagnosed}",
        ),
        (
            "待批准动作：提出 / 批准 / 执行",
            lambda s: f"{s.actions.proposed} / {s.actions.approved} / {s.actions.executed}",
        ),
        (
            "动作图（选图 v3）：次数 / 重复冷却期 / 不同图",
            lambda s: (
                f"{s.action_refs} / {s.cooled_reuse}"
                f"（{_pct(s.cooled_reuse, s.action_refs)}） / {s.distinct_action_images}"
                if s.action_refs
                else "-（选图 v3 前没有冷却期）"
            ),
        ),
        ("配图失败", lambda s: str(s.image_failures)),
        (
            "文案模型 token（输入 / 输出）",
            lambda s: f"{s.copy_prompt_tokens:,} / {s.copy_completion_tokens:,}",
        ),
    ]
    lines = [
        f"# 每周汇总 {current.start.isoformat()} 至 {current.end.isoformat()}",
        "",
        f"对比上周 {previous.start.isoformat()} 至 {previous.end.isoformat()}。"
        "数字来自生产数据库（只读）、"
        "漏发检查日志、待批准动作日志和影子对照日志；审查是模型判断，不是人工标注。",
        "",
        "| 指标 | 本周 | 上周 |",
        "|---|---|---|",
    ]
    for label, fn in rows:
        lines.append(_row(label, *both(fn)))
    notes: list[str] = []
    if current.repair is not None and current.repair.fallbacks:
        reasons = "、".join(
            f"{FALLBACK_LABELS.get(code, code)} {count}"
            for code, count in current.repair.fallbacks.most_common()
        )
        notes.append(f"- 本周 Agent 退回整篇重写：{reasons}。")
    if current.watchdog.stages:
        stages = "、".join(
            f"{STAGE_LABELS.get(stage, stage)} {count}"
            for stage, count in current.watchdog.stages.most_common()
        )
        notes.append(f"- 本周诊断出的出问题环节：{stages}。")
    if current.missed:
        reasons = "、".join(
            f"{MISSED_LABELS.get(reason, reason)} {count}"
            for reason, count in current.missed_reasons.most_common()
        )
        notes.append(f"- 本周少发 {current.missed} 条：{reasons or '原因未分类'}。")
    if notes:
        lines += ["", "**说明**", *notes]
    return "\n".join(lines) + "\n"


def jsonable(stats: WeekStats) -> dict[str, Any]:
    repair = stats.repair
    return {
        "start": stats.start.isoformat(),
        "end": stats.end.isoformat(),
        "posts_selected": stats.posts_selected,
        "posts_delivered": stats.posts_delivered,
        "missed": stats.missed,
        "missed_reasons": dict(stats.missed_reasons),
        "long_images_ready": stats.long_images_ready,
        "copy": {
            "runs": stats.copy_runs,
            "accepted": stats.copy_accepted,
            "first_pass": stats.copy_first_pass,
            "review_required": stats.copy_review_required,
            "failed": stats.copy_failed,
        },
        "repair": None
        if repair is None
        else {
            "repaired_runs": repair.repaired_runs,
            "agent_attempted": repair.agent_attempted,
            "agent_accepted": repair.agent_accepted,
            "fallbacks": dict(repair.fallbacks),
            "regeneration_only": repair.regeneration_only,
            "averages": repair.averages(),
        },
        "visual": {
            "action_refs": stats.action_refs,
            "cooled_reuse": stats.cooled_reuse,
            "distinct": stats.distinct_action_images,
            "image_failures": stats.image_failures,
        },
        "copy_tokens": [stats.copy_prompt_tokens, stats.copy_completion_tokens],
        "watchdog": {
            "checks": stats.watchdog.checks,
            "flagged": stats.watchdog.flagged,
            "diagnosed": stats.watchdog.diagnosed,
            "stages": dict(stats.watchdog.stages),
            "proposals": stats.watchdog.proposals,
            "diagnosis_tokens": stats.watchdog.diagnosis_tokens,
        },
        "actions": vars_of(stats.actions),
        "shadow": vars_of(stats.shadow),
    }


def vars_of(value: object) -> dict[str, int]:
    return {name: getattr(value, name) for name in getattr(value, "__slots__", ())}


def trend_row(stats: WeekStats) -> Sequence[object]:
    repair = stats.repair
    return (
        stats.end.isoformat(),
        stats.posts_selected,
        stats.posts_delivered,
        stats.long_images_ready,
        repair.agent_attempted if repair else 0,
        repair.agent_accepted if repair else 0,
        stats.watchdog.flagged,
        stats.watchdog.diagnosed,
        stats.action_refs,
        stats.cooled_reuse,
        stats.copy_prompt_tokens,
    )
