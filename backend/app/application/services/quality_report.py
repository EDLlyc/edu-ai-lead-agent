# ruff: noqa: RUF001  (Chinese operator-facing report text)
"""Turn one day of production outcomes into findings and a short operator report."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import StrEnum

from app.domain.quality_report import (
    SAME_EVENT,
    SIMILAR_ARTICLE,
    STRONG_TOPIC_MATCHES,
    BrandStatementRow,
    QualitySnapshot,
    SelectedTopicRow,
)
from app.domain.topic_safety_signals import (
    evaluate_government_yaowen_topic,
    evaluate_negative_incident,
    evaluate_specialized_research,
)

QUALITY_REPORT_VERSION = "production-quality-daily-v3"
COPY_FAILURE_WARN_RATE = 0.2
BRAND_REPEAT_WARN_SHARE = 0.5
BRAND_REPEAT_MIN_RUNS = 4
BRAND_PHRASE_WARN_SHARE = 0.3
BRAND_PHRASE_WINDOW = 8
_BRAND_BOILERPLATE = re.compile(r"赛先生科学|赛先生|小赛|我们|咱们")
_NON_WORD = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
_DELIVERY_BAD_STATUSES = frozenset({"failed", "result_unknown", "expired", "partial"})
_SLOT_NAMES = {"morning": "早间", "noon": "午间", "evening": "晚间"}


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    code: str
    message: str


def _top(counter: Counter[str], limit: int = 3) -> str:
    return "、".join(f"{code}×{count}" for code, count in counter.most_common(limit)) or "无"


@dataclass(frozen=True, slots=True)
class RepeatedPhrase:
    phrase: str
    runs: int


def _phrase_segments(text: str) -> list[str]:
    """Wording between brand names, with punctuation removed so a sentence stays whole."""

    parts = _BRAND_BOILERPLATE.split(unicodedata.normalize("NFKC", text).lower())
    return [segment for segment in (_NON_WORD.sub("", part) for part in parts) if segment]


def most_repeated_brand_phrase(statements: Sequence[BrandStatementRow]) -> RepeatedPhrase | None:
    """The brand wording shared by the most accepted copies (brand names are not counted)."""

    segments_by_run: dict[str, list[str]] = defaultdict(list)
    for row in statements:
        segments_by_run[row.run_id].extend(_phrase_segments(row.text))
    counts: Counter[str] = Counter()
    for segments in segments_by_run.values():
        counts.update(
            {
                segment[start : start + BRAND_PHRASE_WINDOW]
                for segment in segments
                for start in range(len(segment) - BRAND_PHRASE_WINDOW + 1)
            }
        )
    if not counts:
        return None
    window, runs = max(counts.items(), key=lambda item: (item[1], item[0]))
    holders = [
        segments
        for segments in segments_by_run.values()
        if any(window in segment for segment in segments)
    ]

    def shared(candidate: str) -> bool:
        return all(any(candidate in segment for segment in segments) for segments in holders)

    seed = next(segment for segment in holders[0] if window in segment)
    start = seed.index(window)
    end = start + BRAND_PHRASE_WINDOW
    while end < len(seed) and shared(seed[start : end + 1]):
        end += 1
    while start > 0 and shared(seed[start - 1 : end]):
        start -= 1
    return RepeatedPhrase(phrase=seed[start:end], runs=runs)


def _slot_label(label: str) -> str:
    if label == "human":
        return "人工加推"
    slot, _, ordinal = label.partition("#")
    return f"{_SLOT_NAMES.get(slot, slot)}#{ordinal}"


def _topic_label(topic: SelectedTopicRow) -> str:
    if topic.human_pick:
        return "人工加推"
    return f"{_SLOT_NAMES.get(topic.content_slot, topic.content_slot)}#{topic.ordinal}"


def _topic_flags(topic: SelectedTopicRow) -> list[str]:
    flags = []
    if evaluate_negative_incident(topic.title, topic.summary).matched:
        flags.append("负面事件")
    if evaluate_specialized_research(topic.title).matched:
        flags.append("专业科研")
    return flags


def _topic_kind(priority_reason: str | None, level: str | None, cohort: str | None) -> str:
    if level == "national":
        return "国家教育风向"
    if level == "provincial":
        return "省级教育风向"
    if priority_reason and priority_reason.startswith("ministry_"):
        return "教育部科学教育"
    if priority_reason == "qualified_government_yaowen_priority":
        return "政府网要闻"
    if cohort == "science_technology_education_priority":
        return "科学教育"
    if cohort == "frontier_science_technology":
        return "前沿科技"
    return "其他"


def assess(snapshot: QualitySnapshot) -> list[Finding]:
    findings: list[Finding] = []
    if not snapshot.slot_runs:
        findings.append(Finding(Severity.CRITICAL, "no_slot_runs", "当天没有任何时段的选题记录。"))
    for run in snapshot.slot_runs:
        name = _SLOT_NAMES.get(run.content_slot, run.content_slot)
        if run.status == "failed":
            findings.append(
                Finding(
                    Severity.CRITICAL,
                    "slot_failed",
                    f"{name}选题失败（{run.error_code or '无错误码'}）。",
                )
            )
        elif run.status == "succeeded" and run.selected_count == 0:
            findings.append(
                Finding(
                    Severity.WARNING,
                    "slot_empty",
                    f"{name}没有选出新闻（{'、'.join(run.unfilled_reason_codes) or '原因未知'}）。",
                )
            )
    for topic in snapshot.selected_topics:
        if evaluate_negative_incident(topic.title, topic.summary).matched:
            findings.append(
                Finding(
                    Severity.CRITICAL,
                    "selected_negative_incident",
                    f"选中了不适合家长的负面事件新闻：{_topic_label(topic)}「{topic.title}」。",
                )
            )
    strong_pairs = [pair for pair in snapshot.same_topic_pairs if pair.kind in STRONG_TOPIC_MATCHES]
    if strong_pairs:
        findings.append(
            Finding(
                Severity.WARNING,
                "selected_same_topic",
                "同一天选中了同一件事："
                + "；".join(
                    f"{_slot_label(pair.left)} 与 {_slot_label(pair.right)}"
                    for pair in strong_pairs
                )
                + "。",
            )
        )
    # Only a re-picked event is certain; similar articles are often the same theme but a new
    # story, so they are listed in the body for review instead of raised.
    strong_repeats = [row for row in snapshot.repeated_stories if row.kind == SAME_EVENT]
    if strong_repeats:
        findings.append(
            Finding(
                Severity.WARNING,
                "repeated_delivered_story",
                "今天又选中了近 14 天已推送过的同一条新闻："
                + "；".join(
                    f"{_slot_label(row.today)}「{row.today_title}」≈ "
                    f"{row.earlier_date:%m-%d}「{row.earlier_title}」"
                    for row in strong_repeats
                )
                + "。",
            )
        )
    off_topic_gov = [
        topic
        for topic in snapshot.selected_topics
        if topic.priority_reason == "qualified_government_yaowen_priority"
        and not evaluate_government_yaowen_topic(topic.title).matched
    ]
    if off_topic_gov:
        findings.append(
            Finding(
                Severity.WARNING,
                "gov_priority_off_topic",
                "政府网要闻以优先级插队，但标题不是科技/教育类："
                + "；".join(f"{_topic_label(topic)}「{topic.title}」" for topic in off_topic_gov)
                + "。",
            )
        )
    delivery_bad = sum(
        count
        for status, count in snapshot.delivery_status.items()
        if status in _DELIVERY_BAD_STATUSES
    )
    if delivery_bad:
        findings.append(
            Finding(
                Severity.CRITICAL,
                "delivery_not_delivered",
                f"企微正式推送有 {delivery_bad} 条未成功送达"
                f"（{_top(snapshot.delivery_error_codes)}）。",
            )
        )
    copy_total = sum(snapshot.copy_status.values())
    copy_failed = snapshot.copy_status.get("failed", 0)
    if copy_total and copy_failed / copy_total > COPY_FAILURE_WARN_RATE:
        findings.append(
            Finding(
                Severity.WARNING,
                "copy_failure_rate",
                f"文案失败 {copy_failed}/{copy_total}（{_top(snapshot.copy_error_codes)}）。",
            )
        )
    if snapshot.copy_status.get("review_required", 0):
        findings.append(
            Finding(
                Severity.WARNING,
                "copy_review_required",
                f"{snapshot.copy_status['review_required']} 条文案等待人工复核。",
            )
        )
    infographic_failed = snapshot.infographic_status.get("failed", 0)
    if infographic_failed:
        findings.append(
            Finding(
                Severity.WARNING,
                "infographic_failed",
                f"长图失败 {infographic_failed} 条（{_top(snapshot.infographic_error_codes)}）。",
            )
        )
    if snapshot.acquisition_failed_jobs:
        findings.append(
            Finding(
                Severity.WARNING,
                "acquisition_failed_jobs",
                f"抓取失败 {snapshot.acquisition_failed_jobs} 个信源任务"
                f"（{_top(snapshot.acquisition_error_codes)}）。",
            )
        )
    if (
        snapshot.brand_usage
        and snapshot.brand_window_accepted_runs >= BRAND_REPEAT_MIN_RUNS
        and snapshot.brand_usage[0].runs / snapshot.brand_window_accepted_runs
        >= BRAND_REPEAT_WARN_SHARE
    ):
        top = snapshot.brand_usage[0]
        findings.append(
            Finding(
                Severity.WARNING,
                "brand_claim_repetition",
                f"近 {snapshot.lookback_days} 天 {top.runs}/{snapshot.brand_window_accepted_runs} "
                f"篇文案引用同一品牌片段「{top.label}」，卖点可能重复。",
            )
        )
    phrase = most_repeated_brand_phrase(snapshot.brand_statements)
    if (
        phrase is not None
        and phrase.runs >= BRAND_REPEAT_MIN_RUNS
        and snapshot.brand_window_accepted_runs
        and phrase.runs / snapshot.brand_window_accepted_runs >= BRAND_PHRASE_WARN_SHARE
    ):
        findings.append(
            Finding(
                Severity.WARNING,
                "brand_phrase_repetition",
                f"近 {snapshot.lookback_days} 天 "
                f"{phrase.runs}/{snapshot.brand_window_accepted_runs} "
                f"篇文案重复使用品牌话术「{phrase.phrase}」。",
            )
        )
    failed_drafts = sum(
        count
        for status, count in snapshot.official_account_draft_status.items()
        if status not in {"succeeded", "completed", "queued", "running"}
    )
    if failed_drafts:
        findings.append(
            Finding(
                Severity.WARNING,
                "official_account_draft_failed",
                f"公众号草稿任务异常 {failed_drafts} 个。",
            )
        )
    return findings


def overall_status(findings: list[Finding]) -> str:
    if any(finding.severity is Severity.CRITICAL for finding in findings):
        return "异常"
    if any(finding.severity is Severity.WARNING for finding in findings):
        return "需关注"
    return "正常"


def render_markdown(snapshot: QualitySnapshot, findings: list[Finding]) -> str:
    lines = [
        f"# 线上质量日报 {snapshot.business_date.isoformat()}（{overall_status(findings)}）",
        "",
    ]
    if findings:
        lines.append("**需要关注**")
        icon = {Severity.CRITICAL: "🔴", Severity.WARNING: "🟡", Severity.INFO: "ℹ️"}
        lines += [f"- {icon[finding.severity]} {finding.message}" for finding in findings]
        lines.append("")

    lines.append("**选题**")
    for run in snapshot.slot_runs:
        name = _SLOT_NAMES.get(run.content_slot, run.content_slot)
        version = (run.scoring_version or "").removeprefix("scoring-v1-preview.")
        lines.append(f"- {name}：{run.status}，选出 {run.selected_count} 条（规则 {version}）")
    kinds = Counter(
        _topic_kind(topic.priority_reason, topic.education_policy_level, topic.cohort)
        for topic in snapshot.selected_topics
    )
    if kinds:
        lines.append(
            "- 类型：" + "、".join(f"{kind} {count}" for kind, count in kinds.most_common())
        )
    for topic in snapshot.selected_topics:
        kind = _topic_kind(topic.priority_reason, topic.education_policy_level, topic.cohort)
        flags = "".join(f" ⚠{flag}" for flag in _topic_flags(topic))
        lines.append(f"  - {_topic_label(topic)} [{kind}] {topic.title}{flags}")
    for pair in snapshot.same_topic_pairs:
        weak = "" if pair.kind in STRONG_TOPIC_MATCHES else "（仅标题相似，可能误判）"
        lines.append(f"- 同题：{_slot_label(pair.left)} 与 {_slot_label(pair.right)}{weak}")
    for row in snapshot.repeated_stories:
        weak = {SAME_EVENT: "", SIMILAR_ARTICLE: "（主题相近，请人工判断）"}.get(
            row.kind, "（仅标题相似，可能误判）"
        )
        lines.append(
            f"- 与已推重复：{_slot_label(row.today)} ≈ {row.earlier_date:%m-%d}"
            f"「{row.earlier_title}」{weak}"
        )
    lines.append("")

    copy_total = sum(snapshot.copy_status.values())
    accepted = snapshot.copy_status.get("accepted", 0)
    lines += [
        "**文案**",
        f"- 共 {copy_total} 篇：通过 {accepted}（一次通过 {snapshot.copy_first_pass_accepted}，"
        f"修复后通过 {accepted - snapshot.copy_first_pass_accepted}），"
        f"失败 {snapshot.copy_status.get('failed', 0)}，"
        f"待复核 {snapshot.copy_status.get('review_required', 0)}",
        f"- 文案版本：{_top(snapshot.copy_prompt_versions)}",
        f"- 未通过原因：{_top(snapshot.copy_error_codes)}",
        f"- 常见问题：{_top(snapshot.copy_issue_codes)}",
        *_brand_angle_lines(snapshot),
        f"- 近 {snapshot.lookback_days} 天品牌片段引用"
        f"（共 {snapshot.brand_window_accepted_runs} 篇）："
        + (
            "；".join(f"{row.label} {row.runs}" for row in snapshot.brand_usage[:3])
            if snapshot.brand_usage
            else "无"
        ),
        "",
        "**配图与推送**",
        f"- 配图：{dict(snapshot.image_status) or '无'}，修复 {snapshot.image_repairs} 次",
        f"- 企微正式推送：{dict(snapshot.delivery_status) or '无'}",
        f"- 长图：{dict(snapshot.infographic_status) or '无'}；"
        f"补发：{dict(snapshot.supplement_status) or '无'}",
        f"- 公众号草稿：{dict(snapshot.official_account_draft_status) or '当天无任务'}",
        "",
        "**抓取与模型用量**",
        f"- 抓取批次 {snapshot.acquisition_runs}，新增 {snapshot.acquisition_new_items} 条，"
        f"失败信源任务 {snapshot.acquisition_failed_jobs}",
        f"- 失败信源：{_top(snapshot.acquisition_failed_sources, 5)}",
        f"- 文案模型调用 {snapshot.copy_model_usage.calls} 次"
        f"（失败 {snapshot.copy_model_usage.failed_calls}），"
        f"Token {snapshot.copy_model_usage.total_tokens:,}",
        f"- 事实治理模型调用 {snapshot.governance_model_usage.calls} 次"
        f"（失败 {snapshot.governance_model_usage.failed_calls}），"
        f"Token {snapshot.governance_model_usage.total_tokens:,}",
        "",
    ]
    if snapshot.daily_trend:
        lines += [
            f"**近 {len(snapshot.daily_trend)} 天趋势**",
            "",
            "| 日期 | 选题 | 文案通过 | 文案未通过 | 企微送达 | 长图失败 |",
            "|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {row.business_date:%m-%d} | {row.selected} | {row.copy_accepted} | "
            f"{row.copy_not_accepted} | {row.delivered} | {row.infographic_failed} |"
            for row in snapshot.daily_trend
        ]
        lines.append("")
    return "\n".join(lines)


def _brand_angle_lines(snapshot: QualitySnapshot) -> list[str]:
    lines: list[str] = []
    today = [
        row for row in snapshot.brand_statements if row.business_date == snapshot.business_date
    ]
    first_by_run: dict[str, BrandStatementRow] = {}
    for row in today:
        first_by_run.setdefault(row.run_id, row)
    if first_by_run:
        lines.append("- 今日品牌角度：")
        lines += [
            f"  - {_slot_label(row.label) if row.label else '文案'}：{row.text[:40]}"
            for row in first_by_run.values()
        ]
    phrase = most_repeated_brand_phrase(snapshot.brand_statements)
    if phrase is not None and phrase.runs >= 2:
        lines.append(
            f"- 近 {snapshot.lookback_days} 天最常重复的品牌话术：「{phrase.phrase}」"
            f" {phrase.runs}/{snapshot.brand_window_accepted_runs} 篇"
        )
    return lines


def _jsonable(value: object) -> object:
    # dataclasses.asdict rebuilds a Counter from (key, value) pairs, which recounts the pairs;
    # convert explicitly instead.
    if isinstance(value, Counter):
        return dict(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _snapshot_payload(snapshot: QualitySnapshot) -> object:
    return _jsonable(snapshot)


def render_json(snapshot: QualitySnapshot, findings: list[Finding]) -> str:
    payload = {
        "report_version": QUALITY_REPORT_VERSION,
        "overall_status": overall_status(findings),
        "findings": [asdict(finding) for finding in findings],
        "snapshot": _snapshot_payload(snapshot),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
