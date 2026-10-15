# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional exhibit copy.
"""「复盘提升」: turn live problem signals and human review into a problem → fix → effect view.

Problems come from three places: stages that stopped or failed (today = 日报, this week = 周报)
and operator review in the exhibit (人工). Optimizations are the real releases recorded in the
Trellis rollout notes; each lists when it went live and, where a live signal exists, how often
the problem appeared on days up to its release versus the days after.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.infrastructure.db.visitor_improvement import VisitorIssueSignal
from app.schemas.visitor_display import (
    VisitorDisplayImprovement,
    VisitorImprovementFix,
    VisitorImprovementHuman,
    VisitorImprovementIssue,
    VisitorImprovementSource,
)

_ZONE = ZoneInfo("Asia/Shanghai")
_WEEK = 7
_SETTLE_DAYS = 3
_ISSUE_LIMIT = 16


@dataclass(frozen=True, slots=True)
class _Fix:
    key: str
    shipped_at: datetime
    source: VisitorImprovementSource
    problem: str
    change: str
    version: str | None = None
    measured: tuple[str, ...] = ()


def _at(month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=_ZONE)


# Real releases (see .trellis/tasks/09-28-* result notes). Newest last.
FIXES: tuple[_Fix, ...] = (
    _Fix(
        "startup_replay_guard",
        _at(9, 25, 22, 44),
        "human",
        "发版重启时补跑了已处理过的选题，出现重复文案",
        "重启时只补跑从没处理过的选题；多出的重复文案被拦下，没有推送",
        measured=("copy:release_duplicate_suppressed",),
    ),
    _Fix(
        "education_policy_signal",
        _at(9, 28, 16, 43),
        "human",
        "漏掉了重要的教育政策风向",
        "国家和省级教育政策新闻设为最高优先级，可以占多个名额",
        "选题规则 .13",
    ),
    _Fix(
        "source_disabled",
        _at(9, 28, 18, 3),
        "human",
        "运营反馈个别企业信源不适合推送",
        "停用该信源，其余信源照常抓取",
    ),
    _Fix(
        "negative_incident_veto",
        _at(9, 28, 22, 45),
        "daily",
        "负面事件新闻因为提到 AI 被选中",
        "负面事件一票否决；过于专业的科研新闻降权",
        "选题规则 .14",
    ),
    _Fix(
        "same_topic_dedup",
        _at(9, 28, 23, 2),
        "daily",
        "同一天两条新闻讲的是同一件事",
        "同一话题一天只推一条（语义相近或标题重合即去重）",
        "排序 v2",
    ),
    _Fix(
        "long_image_banner",
        _at(9, 28, 23, 2),
        "human",
        "长图顶部的「AI 生成未核实」红色横幅影响观感",
        "去掉横幅，事实核对照常在后台进行",
    ),
    _Fix(
        "superlative_relaxed",
        _at(9, 28, 23, 19),
        "daily",
        "官方原话里的「世界最大」被当成夸大宣传拦截",
        "新闻本身的最高级只提示不拦截；说品牌自己的夸大仍然拦截",
        "文案规则 v12",
        ("copy:unverified_superlative",),
    ),
    _Fix(
        "infographic_short_fact",
        _at(9, 28, 23, 19),
        "daily",
        "长图卡片放不下原文事实，生成失败",
        "放不下时换用同一新闻里更短的原文事实，并记录是哪条规则没过",
        "长图 v6",
        ("infographic:moments_preflight_failed",),
    ),
    _Fix(
        "rejected_copy_repeat",
        _at(9, 28, 23, 19),
        "weekly",
        "被模型拒绝的新闻连续几天被重复选中",
        "被拒绝过的新闻算作近期已用，不再反复入选",
        "选题规则 .14",
        ("copy:provider_request_rejected",),
    ),
    _Fix(
        "brand_rotation",
        _at(9, 28, 23, 48),
        "weekly",
        "文案反复使用同一句品牌话术",
        "品牌卖点按最近使用情况轮换，回放 6 条新闻用了 6 个不同角度",
        "文案生成 v25",
    ),
    _Fix(
        "human_pick",
        _at(9, 29, 0, 22),
        "human",
        "AI 落选、但运营认为值得推的新闻没法推送",
        "新增人工加推：审核通过后自动走完文案、配图、企微推送和长图",
    ),
    _Fix(
        "gov_yaowen_gate",
        _at(9, 29, 0, 36),
        "daily",
        "政府网要闻里与教育无关的新闻也被优先",
        "要闻优先只给科技教育类标题；重复判断窗口延长到 14 天",
        "选题规则 .15",
    ),
    _Fix(
        "acquisition_conflict",
        _at(9, 29, 10, 20),
        "weekly",
        "北师大新闻、中科院科研、科技日报等信源自 09-24 起反复抓取失败",
        "重新抓取且页面有改动时不再重复识别文中图片，抓取不再被冲突中断",
        measured=("acquisition:conflict",),
    ),
    _Fix(
        "moments_headline_hook",
        _at(9, 29, 11, 5),
        "human",
        "运营要求朋友圈文案改用「标题 + 一句引导语」的固定模板",
        "标题照抄新闻原文，大模型只写一句 8–50 字的亲子引导语；事实和品牌要点放进长图",
        "文案生成 v26",
    ),
    _Fix(
        "long_image_no_link",
        _at(9, 29, 11, 42),
        "human",
        "长图底部的原文链接、新闻日期和来源被要求去掉",
        "长图底部不再放任何文字，新闻来源和原文链接只留在文字消息里",
        "长图页脚 v6",
    ),
)


@dataclass(frozen=True, slots=True)
class _IssueSpec:
    title: str
    cause: str
    fix: str | None = None
    suggestion: str | None = None


# Exact codes first, then a per-stage fallback that names the stage's own safe code.
_ISSUES: Mapping[str, _IssueSpec] = {
    "copy:unverified_superlative": _IssueSpec(
        "文案里的「最」字被拦截",
        "官方原话里的最高级说法被当成夸大宣传，文案停在待复核。",
        fix="superlative_relaxed",
    ),
    "copy:provider_request_rejected": _IssueSpec(
        "新闻被大模型拒绝生成",
        "个别话题触发了模型的安全拒绝，同一条新闻还被连续几天重复选中。",
        fix="rejected_copy_repeat",
    ),
    "copy:missing_eligible_evidence": _IssueSpec(
        "来源不够权威，文案没法写",
        "入选新闻缺少可核实的权威来源，按规定停在待复核。",
        suggestion="选题时更看重来源等级；人工加推前先看来源是否权威。",
    ),
    "copy:release_duplicate_suppressed": _IssueSpec(
        "发版时重复生成的文案被拦下",
        "一次发版重启时补跑了已处理过的选题，多出的重复文案被自动拦下，没有重复推送。",
        fix="startup_replay_guard",
    ),
    "copy:repair_validation_failed": _IssueSpec(
        "文案自动修复后仍没通过",
        "文案校验没过，自动修复一次后仍不合格，停在待复核。",
        suggestion="看具体没过的规则：能放宽的放宽，必须拦的在提示词里写清楚。",
    ),
    "copy:provider_input_limit": _IssueSpec(
        "新闻原文太长",
        "原文超过了大模型一次能读的长度，文案没能生成。",
        suggestion="超长原文先压缩成要点再写文案。",
    ),
    "acquisition:conflict": _IssueSpec(
        "抓取入库时发生冲突",
        "重新抓到的页面内容变了，再次识别文中图片时与已存记录冲突，整个抓取任务被中断。",
        fix="acquisition_conflict",
    ),
    "acquisition:parse_failure": _IssueSpec(
        "信源页面解析失败",
        "信源网站改版或页面结构特殊，抓到的页面读不出正文。",
        suggestion="给解析失败最多的信源更新解析规则，长期失败的暂停。",
    ),
    "infographic:moments_preflight_failed": _IssueSpec(
        "长图排版放不下",
        "原文事实太长，塞不进长图卡片，生成前的检查没过。",
        fix="infographic_short_fact",
    ),
    "slot:empty": _IssueSpec(
        "有一场没有选出新闻",
        "这一场没有达到及格线的新闻；系统宁缺毋滥，不会降低标准凑数。",
        suggestion="在新闻池里看看落选新闻，值得推的可以人工加推。",
    ),
    "slot:failed": _IssueSpec(
        "有一场选题失败",
        "选题任务执行出错，这一场没有结果。",
        suggestion="查看选题日志，修复后手动重跑这一场。",
    ),
    "human:include_override": _IssueSpec(
        "AI 落选、人工认为该推",
        "运营审核时把 AI 落选的新闻改判为入选，说明选题规则漏掉了这类新闻。",
        fix="human_pick",
        suggestion="把改判理由整理成选题规则，减少以后的人工改判。",
    ),
    "human:exclude_override": _IssueSpec(
        "AI 入选、人工认为不该推",
        "运营审核时把 AI 入选的新闻改判为落选，说明有该拦的没拦住。",
        suggestion="把改判理由整理成否决规则（例如负面事件否决）。",
    ),
}
_STAGE_FALLBACK: Mapping[str, _IssueSpec] = {
    "copy": _IssueSpec(
        "文案没有通过校验",
        "文案生成或事实校验没通过（代码 {code}）。",
        suggestion="按失败代码逐类处理：能放宽的放宽，必须拦的补充说明。",
    ),
    "infographic": _IssueSpec(
        "长图生成失败",
        "长图生成或检查没通过（代码 {code}）。",
        suggestion="按失败代码检查长图模板和字数上限。",
    ),
    "wecom": _IssueSpec(
        "企微推送没有送达",
        "推送失败或结果未知（代码 {code}）；结果未知的不会自动重发，避免重复推送。",
        suggestion="核对企微机器人配置和发送频率，失败的由人工确认后重试。",
    ),
    "acquisition": _IssueSpec(
        "部分信源抓取失败",
        "信源网站超时、改版或拒绝访问（代码 {code}）。",
        suggestion="连续失败的信源检查页面结构，必要时暂停。",
    ),
}
# Interventions that are not problems in themselves.
_NOT_ISSUES = frozenset({"human:pick"})


def project_improvement(
    signals: Iterable[VisitorIssueSignal],
    human_days: Mapping[date, Mapping[str, int]],
    *,
    now: datetime,
) -> VisitorDisplayImprovement:
    today = now.astimezone(_ZONE).date()
    this_week = {today - timedelta(days=offset) for offset in range(_WEEK)}
    last_week = {today - timedelta(days=offset) for offset in range(_WEEK, 2 * _WEEK)}

    by_code: defaultdict[str, defaultdict[date, int]] = defaultdict(lambda: defaultdict(int))
    for signal in signals:
        by_code[signal.code][signal.day] += signal.count
    for day, decisions in human_days.items():
        for kind in ("include_override", "exclude_override"):
            if decisions.get(kind, 0) > 0:
                by_code[f"human:{kind}"][day] += decisions[kind]

    fixes = {fix.key: fix for fix in FIXES if fix.shipped_at <= now}
    projected_fixes = [_project_fix(fix, by_code, today) for fix in fixes.values()]
    after_by_fix = {fix.key: fix.after for fix in projected_fixes}

    issues: list[VisitorImprovementIssue] = []
    for code, days in by_code.items():
        if code in _NOT_ISSUES:
            continue
        week_count = sum(count for day, count in days.items() if day in this_week)
        last_count = sum(count for day, count in days.items() if day in last_week)
        if week_count == 0 and last_count == 0:
            continue
        spec = _issue_spec(code)
        fix = fixes.get(spec.fix) if spec.fix is not None else None
        today_count = days.get(today, 0)
        issues.append(
            VisitorImprovementIssue(
                key=code[:80],
                source="human"
                if code.startswith("human:")
                else ("daily" if today_count else "weekly"),
                title=spec.title,
                cause=spec.cause.format(code=code.split(":", 1)[-1])[:140],
                this_week=week_count,
                last_week=last_count,
                today=today_count,
                status=_issue_status(fix, after_by_fix, today),
                fix_key=fix.key if fix is not None else None,
                suggestion=spec.suggestion if fix is None else None,
            )
        )
    order = {"open": 0, "watching": 1, "fixed": 2}
    issues.sort(key=lambda item: (order[item.status], -item.this_week, item.key))
    issues = issues[:_ISSUE_LIMIT]

    human_week = [decisions for day, decisions in human_days.items() if day in this_week]
    picks = sum(count for day, count in by_code.get("human:pick", {}).items() if day in this_week)
    next_steps = list(
        dict.fromkeys(
            issue.suggestion
            for issue in issues
            if issue.status == "open" and issue.suggestion is not None
        )
    )[:3]
    return VisitorDisplayImprovement(
        generated_at=now,
        issues=issues,
        fixes=sorted(projected_fixes, key=lambda item: item.shipped_at, reverse=True)[
            :_ISSUE_LIMIT
        ],
        human=VisitorImprovementHuman(
            reviews=sum(sum(decisions.values()) for decisions in human_week),
            include_overrides=sum(item.get("include_override", 0) for item in human_week),
            exclude_overrides=sum(item.get("exclude_override", 0) for item in human_week),
            picks=picks,
        ),
        next_steps=next_steps,
    )


def _issue_spec(code: str) -> _IssueSpec:
    known = _ISSUES.get(code)
    if known is not None:
        return known
    stage = code.split(":", 1)[0]
    return _STAGE_FALLBACK.get(
        stage,
        _IssueSpec(
            "流程出现异常", "某个环节没有按预期完成（代码 {code}）。", suggestion="待排查。"
        ),
    )


def _project_fix(
    fix: _Fix, by_code: Mapping[str, Mapping[date, int]], today: date
) -> VisitorImprovementFix:
    shipped_day = fix.shipped_at.astimezone(_ZONE).date()
    before: int | None = None
    after: int | None = None
    if fix.measured:
        before = sum(
            count
            for code in fix.measured
            for day, count in by_code.get(code, {}).items()
            if day <= shipped_day
        )
        after = sum(
            count
            for code in fix.measured
            for day, count in by_code.get(code, {}).items()
            if day > shipped_day
        )
    return VisitorImprovementFix(
        key=fix.key,
        shipped_at=fix.shipped_at,
        source=fix.source,
        problem=fix.problem,
        change=fix.change,
        version=fix.version,
        before=before,
        after=after,
        days_live=max((today - shipped_day).days, 0),
    )


def _issue_status(
    fix: _Fix | None, after_by_fix: Mapping[str, int | None], today: date
) -> Literal["fixed", "watching", "open"]:
    if fix is None:
        return "open"
    days_live = (today - fix.shipped_at.astimezone(_ZONE).date()).days
    after = after_by_fix.get(fix.key)
    if days_live >= _SETTLE_DAYS and after == 0:
        return "fixed"
    return "watching"


__all__ = ["FIXES", "project_improvement"]
