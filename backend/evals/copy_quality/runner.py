# ruff: noqa: RUF001  (Chinese operator-facing report text)
"""Seeded-defect test and hook-quality evaluation for the headline-hook Moments copy.

For real accepted topics, one first draft is generated with the production bundle. The unmodified
draft is the control; each mutant carries exactly one known defect. Every draft goes through the
same gates as production: the deterministic validator first and, only when it finds no error, the
model auditor with the production audit policy. Hooks are also scored against a four-criterion
rubric by a judge model. Nothing is written to the database; every model call is budgeted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from app.application.ports.copy_generation import (
    DraftAuditRequest,
    DraftGenerationRequest,
    MaterialDraftAuditor,
    MaterialDraftGenerator,
    RecentBrandUsage,
)
from app.domain.copy_generation import (
    HEADLINE_HOOK_COPY_RULE_VERSIONS,
    ActiveBrandContext,
    CopyVersionBundle,
    LockedTopicContext,
    apply_copy_audit_policy,
    validate_material_draft,
)
from app.schemas.copy_generation import (
    MaterialDraft,
    extract_headline_hook,
    render_headline_hook_copy,
)

from evals.copy_quality.mutations import Defect, build_mutants
from evals.copy_quality.rubric import (
    CRITERIA,
    CRITERION_KEYS,
    HookJudgment,
    build_judge_prompt,
    measure_agreement,
    parse_judgment,
    render_sheet,
    summarize,
)

REPORT_VERSION = "copy-quality-v1"
Outcome = Literal[
    "blocked_by_validator", "blocked_by_auditor", "passed_with_new_warnings", "passed"
]
_JUDGE_OUTPUT_TOKENS = 256
_EXAMPLES_PER_DEFECT = 3


class BudgetExhaustedError(RuntimeError):
    """The run reached its model-call cap; results so far are kept."""


@dataclass(slots=True)
class CallBudget:
    limit: int
    generation: int = 0
    audit: int = 0
    judge: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def used(self) -> int:
        return self.generation + self.audit + self.judge

    def take(self, kind: Literal["generation", "audit", "judge"]) -> None:
        if self.used >= self.limit:
            raise BudgetExhaustedError(f"model-call cap of {self.limit} reached")
        setattr(self, kind, getattr(self, kind) + 1)

    def spend(self, *, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens


class HookJudge(Protocol):
    async def judge(
        self, *, headline: str, evidence: str, hook: str
    ) -> tuple[HookJudgment, int, int]: ...


@dataclass(frozen=True, slots=True)
class GateResult:
    outcome: Outcome
    validator_errors: tuple[str, ...] = ()
    validator_warnings: tuple[str, ...] = ()
    auditor_errors: tuple[str, ...] = ()
    auditor_warnings: tuple[str, ...] = ()

    @property
    def warnings(self) -> frozenset[str]:
        return frozenset((*self.validator_warnings, *self.auditor_warnings))

    @property
    def blocked(self) -> bool:
        return self.outcome in {"blocked_by_validator", "blocked_by_auditor"}


@dataclass(frozen=True, slots=True)
class MutantResult:
    defect: str
    label: str
    target: str
    detector: str
    gate: GateResult
    changed_text: str
    judgment: HookJudgment | None = None


@dataclass(slots=True)
class CaseResult:
    case_id: str
    business_date: str
    headline: str
    hook: str
    copywriting: str
    control: GateResult | None = None
    hook_judgment: HookJudgment | None = None
    mutants: list[MutantResult] = field(default_factory=list)
    skipped_reason: str | None = None


async def run_gates(
    draft: MaterialDraft,
    *,
    run_id: UUID,
    topic: LockedTopicContext,
    brand_context: tuple[ActiveBrandContext, ...],
    bundle: CopyVersionBundle,
    auditor: MaterialDraftAuditor,
    audit_output_tokens: int,
    budget: CallBudget,
    baseline_warnings: frozenset[str] = frozenset(),
) -> GateResult:
    """The production order: deterministic rules, then the auditor only if no rule blocked."""

    issues = validate_material_draft(
        draft, topic=topic, brand_context=brand_context, rule_version=bundle.rule_version
    )
    validator_errors = tuple(issue.code for issue in issues if issue.severity == "error")
    validator_warnings = tuple(issue.code for issue in issues if issue.severity != "error")
    if validator_errors:
        return GateResult("blocked_by_validator", validator_errors, validator_warnings)
    budget.take("audit")
    audit = await auditor.audit(
        DraftAuditRequest(
            run_id=run_id,
            draft_version_id=run_id,
            topic=topic,
            brand_context=brand_context,
            draft=draft,
            version_bundle=bundle,
            max_output_tokens=audit_output_tokens,
        )
    )
    budget.spend(prompt_tokens=audit.prompt_tokens, completion_tokens=audit.completion_tokens)
    verdict = apply_copy_audit_policy(audit.verdict, rule_version=bundle.rule_version)
    auditor_errors = tuple(issue.code for issue in verdict.issues if issue.severity == "error")
    auditor_warnings = tuple(issue.code for issue in verdict.issues if issue.severity != "error")
    if not verdict.accepted:
        return GateResult(
            "blocked_by_auditor",
            validator_errors,
            validator_warnings,
            auditor_errors,
            auditor_warnings,
        )
    new_warnings = frozenset((*validator_warnings, *auditor_warnings)) - baseline_warnings
    return GateResult(
        "passed_with_new_warnings" if new_warnings else "passed",
        validator_errors,
        validator_warnings,
        auditor_errors,
        auditor_warnings,
    )


def _changed_text(defect: Defect, mutant: MaterialDraft, *, base: MaterialDraft, title: str) -> str:
    if defect.target == "hook":
        return extract_headline_hook(mutant.copywriting, title=title)
    before = {claim.id: claim for claim in base.claims}
    for claim in mutant.claims:
        if before.get(claim.id) != claim:
            return f"[{claim.kind}] {claim.text}"
    return ""


def _evidence_text(topic: LockedTopicContext) -> str:
    return "\n".join(item.exact_quote for item in topic.evidence)


async def evaluate_case(
    *,
    case_id: str,
    run_id: UUID,
    topic: LockedTopicContext,
    brand_context: tuple[ActiveBrandContext, ...],
    draft: MaterialDraft,
    bundle: CopyVersionBundle,
    auditor: MaterialDraftAuditor,
    judge: HookJudge | None,
    audit_output_tokens: int,
    budget: CallBudget,
    with_defects: bool = True,
) -> CaseResult:
    title = topic.title or ""
    result = CaseResult(
        case_id=case_id,
        business_date=topic.business_date.isoformat(),
        headline=title,
        hook=extract_headline_hook(draft.copywriting, title=title),
        copywriting=draft.copywriting,
    )
    result.control = await run_gates(
        draft,
        run_id=run_id,
        topic=topic,
        brand_context=brand_context,
        bundle=bundle,
        auditor=auditor,
        audit_output_tokens=audit_output_tokens,
        budget=budget,
    )
    evidence = _evidence_text(topic)
    if judge is not None and result.hook:
        budget.take("judge")
        result.hook_judgment, prompt_tokens, completion_tokens = await judge.judge(
            headline=title, evidence=evidence, hook=result.hook
        )
        budget.spend(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    if result.control.blocked:
        # Production would repair or stop here; a blocked control cannot host seeded defects.
        result.skipped_reason = "control_blocked"
        return result
    if not with_defects:
        return result
    for defect, mutant in build_mutants(draft, topic=topic, brand_context=brand_context):
        gate = await run_gates(
            mutant,
            run_id=run_id,
            topic=topic,
            brand_context=brand_context,
            bundle=bundle,
            auditor=auditor,
            audit_output_tokens=audit_output_tokens,
            budget=budget,
            baseline_warnings=result.control.warnings,
        )
        changed = _changed_text(defect, mutant, base=draft, title=title)
        judgment = None
        if judge is not None and defect.target == "hook" and changed:
            budget.take("judge")
            judgment, prompt_tokens, completion_tokens = await judge.judge(
                headline=title, evidence=evidence, hook=changed
            )
            budget.spend(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        result.mutants.append(
            MutantResult(
                defect=defect.code,
                label=defect.label,
                target=defect.target,
                detector=defect.detector,
                gate=gate,
                changed_text=changed,
                judgment=judgment,
            )
        )
    return result


def summarize_defects(cases: Sequence[CaseResult]) -> list[dict[str, Any]]:
    order: list[str] = []
    rows: dict[str, dict[str, Any]] = {}
    for case in cases:
        for mutant in case.mutants:
            if mutant.defect not in rows:
                order.append(mutant.defect)
                rows[mutant.defect] = {
                    "defect": mutant.defect,
                    "label": mutant.label,
                    "detector": mutant.detector,
                    "applicable": 0,
                    "blocked_by_validator": 0,
                    "blocked_by_auditor": 0,
                    "passed_with_new_warnings": 0,
                    "passed": 0,
                    "judge_failed": 0,
                    "judged": 0,
                }
            row = rows[mutant.defect]
            row["applicable"] += 1
            row[mutant.gate.outcome] += 1
            if mutant.judgment is not None:
                row["judged"] += 1
                row["judge_failed"] += int(not mutant.judgment.passed)
    return [rows[code] for code in order]


def summarize_run(
    cases: Sequence[CaseResult], *, bundle: CopyVersionBundle, budget: CallBudget, partial: bool
) -> dict[str, Any]:
    controls = [case.control for case in cases if case.control is not None]
    judgments = [case.hook_judgment for case in cases if case.hook_judgment is not None]
    rubric = summarize(judgments)
    return {
        "report_version": REPORT_VERSION,
        "partial": partial,
        "bundle": bundle.as_metadata(),
        "topics": len(cases),
        "calls": {
            "limit": budget.limit,
            "generation": budget.generation,
            "audit": budget.audit,
            "judge": budget.judge,
            "prompt_tokens": budget.prompt_tokens,
            "completion_tokens": budget.completion_tokens,
        },
        "control": {
            "drafts": len(controls),
            "accepted": sum(not control.blocked for control in controls),
            "blocked_by_validator": sum(
                control.outcome == "blocked_by_validator" for control in controls
            ),
            "blocked_by_auditor": sum(
                control.outcome == "blocked_by_auditor" for control in controls
            ),
            "block_codes": dict(
                Counter(
                    code
                    for control in controls
                    if control.blocked
                    for code in (*control.validator_errors, *control.auditor_errors)
                )
            ),
            "warning_codes": dict(
                Counter(code for control in controls for code in sorted(control.warnings))
            ),
        },
        "defects": summarize_defects(cases),
        "hooks": {
            "judged": rubric.judged,
            "passed_all": rubric.passed_all,
            "passed_by_criterion": rubric.passed_by_criterion,
        },
    }


def _share(count: int, total: int) -> str:
    return f"{count}/{total}" + (f"（{count / total * 100:.0f}%）" if total else "")


def _header(summary: dict[str, Any]) -> list[str]:
    bundle, calls = summary["bundle"], summary["calls"]
    lines = [
        f"- 选题 {summary['topics']} 条，都是生产上真实通过的选题；每条重新生成一份初稿，不写库。",
        f"- 版本：{bundle['generator_prompt_version']} / {bundle['auditor_prompt_version']} / "
        f"{bundle['rule_version']}，模型 {bundle['model']}。",
        f"- 模型调用 {calls['generation'] + calls['audit'] + calls['judge']} 次"
        f"（生成 {calls['generation']}、审查 {calls['audit']}、评分 {calls['judge']}），"
        f"输入 {calls['prompt_tokens']:,} token，输出 {calls['completion_tokens']:,} token。",
        "- 每份文案只跑一次，没有重复试验；比例的分母写在每一格里。",
    ]
    if summary["partial"]:
        lines.append("- **本次运行达到调用上限后提前结束，结果不完整。**")
    return lines


def render_defects_markdown(summary: dict[str, Any], cases: Sequence[CaseResult]) -> str:
    control = summary["control"]
    lines = ["# 埋雷测试：校验规则和审查模型能拦住什么", "", *_header(summary), ""]
    lines += [
        "## 对照组：没有改动的文案",
        "",
        f"- 正常通过 {_share(control['accepted'], control['drafts'])}；"
        f"被规则拦下 {control['blocked_by_validator']}，被审查模型拦下 "
        f"{control['blocked_by_auditor']}。对照组被拦不一定是误拦，初稿本来就可能有问题，"
        "生产上会自动修改一次。",
    ]
    if control["block_codes"]:
        codes = "、".join(f"{code}×{count}" for code, count in control["block_codes"].items())
        lines.append(f"- 拦截原因：{codes}")
    lines += [
        "",
        "## 每类缺陷的结果",
        "",
        "“应由谁拦”是设计预期：规则 = 确定性校验，模型 = 审查模型。",
        "",
        "| 缺陷 | 应由谁拦 | 适用 | 规则拦下 | 审查模型拦下 | 只给提醒 | 漏过 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in summary["defects"]:
        total = row["applicable"]
        detector = "规则" if row["detector"] == "validator" else "模型"
        lines.append(
            f"| {row['label']} | {detector} | {total} | "
            f"{row['blocked_by_validator']} | {row['blocked_by_auditor']} | "
            f"{row['passed_with_new_warnings']} | {row['passed']} |"
        )
    defects = summary["defects"]
    seeded = sum(row["applicable"] for row in defects)
    blocked = sum(row["blocked_by_validator"] + row["blocked_by_auditor"] for row in defects)
    warned = sum(row["passed_with_new_warnings"] for row in defects)
    missed = sum(row["passed"] for row in defects)
    lines += [
        "",
        f"合计 {seeded} 个埋雷：拦下 {_share(blocked, seeded)}，只给提醒 {_share(warned, seeded)}，"
        f"漏过 {_share(missed, seeded)}。只给提醒的文案在生产上照样会推送。",
        "",
        "## 没拦住的样例",
        "",
    ]
    shown: Counter[str] = Counter()
    for case in cases:
        for mutant in case.mutants:
            if mutant.gate.blocked or shown[mutant.defect] >= _EXAMPLES_PER_DEFECT:
                continue
            shown[mutant.defect] += 1
            state = "只给提醒" if mutant.gate.outcome == "passed_with_new_warnings" else "漏过"
            warnings = "、".join(sorted(mutant.gate.warnings)) or "无"
            lines.append(
                f"- {mutant.label}（{state}；提醒：{warnings}）｜{case.headline[:30]}｜"
                f"{mutant.changed_text[:80]}"
            )
    if not shown:
        lines.append("- 所有埋雷都被拦下了。")
    lines.append("")
    return "\n".join(lines)


def render_hooks_markdown(summary: dict[str, Any], cases: Sequence[CaseResult]) -> str:
    hooks = summary["hooks"]
    lines = [
        "# 引导语质量评测",
        "",
        *_header(summary),
        "- 评分模型和写作模型是同一个模型，分数是模型判断，不是人工标注；"
        "请用 hooks-sheet.csv 做人工抽查。",
        "",
        "## 生产模板写出的引导语",
        "",
        f"- 四项全部通过：{_share(hooks['passed_all'], hooks['judged'])}",
    ]
    lines += [
        f"- {text}：{_share(hooks['passed_by_criterion'].get(key, 0), hooks['judged'])}"
        for key, text in CRITERIA
    ]
    lines += ["", "## 评分模型能不能认出有问题的引导语", ""]
    rows = [row for row in summary["defects"] if row["judged"]]
    if rows:
        lines += ["| 埋雷类型 | 判为不合格 |", "|---|---|"]
        lines += [
            f"| {row['label']} | {_share(row['judge_failed'], row['judged'])} |" for row in rows
        ]
    else:
        lines.append("- 本次没有对埋雷引导语评分。")
    lines += [
        "",
        "## 引导语与评分",
        "",
        "| 新闻 | 引导语 | 未通过的项 | 说明 |",
        "|---|---|---|---|",
    ]
    for case in cases:
        judgment = case.hook_judgment
        if judgment is None:
            continue
        failed = "、".join(key for key in CRITERION_KEYS if not judgment.value(key)) or "无"
        lines.append(
            f"| {case.headline[:24]} | {case.hook} | {failed} | {judgment.reason or '无'} |"
        )
    lines.append("")
    return "\n".join(lines)


def hooks_sheet(cases: Sequence[CaseResult]) -> str:
    return render_sheet(
        (case.case_id, case.headline, case.hook, case.hook_judgment)
        for case in cases
        if case.hook_judgment is not None
    )


def render_agreement_markdown(sheet: str) -> str:
    rows = measure_agreement(sheet)
    lines = [
        "# 评分模型与人工抽查的一致性",
        "",
        "| 评分项 | 已标注 | 一致 | 模型说合格、人工说不合格 | 模型说不合格、人工说合格 |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {row.criterion} | {row.labelled} | {_share(row.agreed, row.labelled)} | "
        f"{row.judge_yes_human_no} | {row.judge_no_human_yes} |"
        for row in rows
    ]
    if any(row.labelled < 30 for row in rows):
        lines += ["", "标注不足 30 条的评分项，比例仅供参考。"]
    lines.append("")
    return "\n".join(lines)


def dates_between(first: date, last: date) -> list[date]:
    if last < first:
        raise ValueError("--to must not be earlier than --from")
    return [last - timedelta(days=offset) for offset in range((last - first).days + 1)]


async def _run_live(args: argparse.Namespace) -> int:
    # Imported here so that the pure evaluation logic above stays importable without settings.
    import httpx
    from app.application.services.copy_generation import (
        BRAND_ROTATION_CLAIM_LIMIT,
        BRAND_ROTATION_GENERATOR_PROMPT_VERSIONS,
        BRAND_ROTATION_LOOKBACK_DAYS,
        BrandRagContextRetriever,
        build_copy_version_bundle,
    )
    from app.core.config import get_settings
    from app.infrastructure.ai.copy_generation import create_zhipu_copy_models
    from app.infrastructure.ai.factory import (
        create_brand_embedding_model,
        select_brand_embedding_client,
    )
    from app.infrastructure.db.brand_knowledge import PostgresBrandKnowledgeRepository
    from app.infrastructure.db.copy_generation import load_recent_brand_usage_before
    from app.infrastructure.db.session import create_engine, create_session_factory
    from pydantic import SecretStr
    from sqlalchemy import text

    settings = get_settings()
    bundle = build_copy_version_bundle(settings, scoring_profile=settings.content_scoring_profile)
    if bundle.rule_version not in HEADLINE_HOOK_COPY_RULE_VERSIONS:
        print(f"rule version {bundle.rule_version} is not a headline-hook version", file=sys.stderr)
        return 2
    if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
        print("the copy provider settings are missing", file=sys.stderr)
        return 2
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    client = httpx.AsyncClient(follow_redirects=False)
    budget = CallBudget(limit=args.max_calls)
    cases: list[CaseResult] = []
    partial = False
    try:
        topics: list[tuple[UUID, LockedTopicContext]] = []
        history: dict[date, RecentBrandUsage] = {}
        seen: set[UUID] = set()
        async with session_factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            for day in dates_between(args.date_from, args.date_to):
                for run_id, topic in await load_accepted_topics(session, day, args.limit):
                    if topic.selected_event_id is None or topic.selected_event_id in seen:
                        continue
                    seen.add(topic.selected_event_id)
                    topics.append((run_id, topic))
                history[day] = await load_recent_brand_usage_before(
                    session,
                    run_id=UUID(int=0),
                    business_date=day - timedelta(days=1),
                    timezone=settings.business_timezone,
                    lookback_days=BRAND_ROTATION_LOOKBACK_DAYS - 1,
                    claim_limit=BRAND_ROTATION_CLAIM_LIMIT,
                )
                if len(topics) >= args.limit:
                    break
            await session.rollback()
        topics = topics[: args.limit]
        print(
            f"{len(topics)} topics; at most {args.max_calls} model calls "
            f"(about 18 per topic with defects and hook scoring)",
            file=sys.stderr,
        )
        if args.plan:
            for _, topic in topics:
                print(f"- {topic.business_date} {topic.title}", file=sys.stderr)
            return 0
        retriever = BrandRagContextRetriever(
            repository=PostgresBrandKnowledgeRepository(session_factory),
            embeddings=create_brand_embedding_model(
                settings,
                client=select_brand_embedding_client(
                    settings, zhipu_client=client, alibaba_client=client
                ),
            ),
            limit=settings.copy_brand_context_limit,
            retrieval_version=settings.brand_retrieval_version,
        )
        generator, auditor = create_zhipu_copy_models(
            client=client,
            base_url=settings.ai_platform_base_url,
            api_key=SecretStr(settings.ai_platform_api_key.get_secret_value()),
            model=settings.ai_chat_model,
            connect_timeout_seconds=settings.ai_connect_timeout_seconds,
            read_timeout_seconds=settings.ai_read_timeout_seconds,
            total_timeout_seconds=settings.ai_total_timeout_seconds,
            concurrency=settings.ai_provider_concurrency,
            max_attempts=settings.ai_max_attempts,
            max_input_characters=settings.ai_max_input_characters,
            max_output_tokens=settings.copy_max_output_tokens,
            max_validation_corrections=settings.ai_max_validation_corrections,
        )
        judge = None if args.skip_hooks else ZhipuHookJudge(generator)
        rotation = bundle.generator_prompt_version in BRAND_ROTATION_GENERATOR_PROMPT_VERSIONS
        for index, (run_id, topic) in enumerate(topics, start=1):
            try:
                recent = history.get(topic.business_date, RecentBrandUsage())
                brand = (
                    await retriever.retrieve_for_copy(topic, recent_usage=recent)
                    if rotation
                    else await retriever.retrieve_for_copy(topic)
                )
                draft = await generate_draft(
                    generator,
                    run_id=run_id,
                    topic=topic,
                    brand_context=brand,
                    bundle=bundle,
                    output_tokens=settings.copy_max_output_tokens,
                    recent_brand_claims=recent.claim_texts if rotation else (),
                    budget=budget,
                )
                case = await evaluate_case(
                    case_id=f"t{index:02d}-{topic.business_date:%m%d}",
                    run_id=run_id,
                    topic=topic,
                    brand_context=brand,
                    draft=draft,
                    bundle=bundle,
                    auditor=auditor,
                    judge=judge,
                    audit_output_tokens=settings.copy_audit_max_output_tokens,
                    budget=budget,
                    with_defects=not args.skip_defects,
                )
            except BudgetExhaustedError as error:
                print(str(error), file=sys.stderr)
                partial = True
                break
            cases.append(case)
            print(f"[{index}/{len(topics)}] {topic.title} ({budget.used} calls)", file=sys.stderr)
    finally:
        await client.aclose()
        await engine.dispose()
    summary = summarize_run(cases, bundle=bundle, budget=budget, partial=partial)
    write_outputs(args.output_dir, summary=summary, cases=cases)
    print(render_defects_markdown(summary, cases), end="")
    print()
    print(render_hooks_markdown(summary, cases), end="")
    return 0


async def load_accepted_topics(
    session: Any, business_date: date, limit: int
) -> list[tuple[UUID, LockedTopicContext]]:
    """Locked topic and evidence of the day's accepted slot copy, as the copy worker loads them."""

    from app.domain.copy_generation import ENGLISH_EVIDENCE_COPY_PIPELINE_VERSION
    from app.infrastructure.db.copy_generation import (
        load_governed_event_evidence,
        load_locked_topic_origin,
    )
    from app.infrastructure.db.models import CopyGenerationRunModel, EventClusterVersionModel
    from sqlalchemy import select

    runs = (
        await session.scalars(
            select(CopyGenerationRunModel)
            .where(
                CopyGenerationRunModel.business_date == business_date,
                CopyGenerationRunModel.status == "accepted",
                CopyGenerationRunModel.decision_kind == "selected",
                CopyGenerationRunModel.content_slot_selection_id.is_not(None),
            )
            .order_by(CopyGenerationRunModel.created_at)
            .limit(limit)
        )
    ).all()
    topics: list[tuple[UUID, LockedTopicContext]] = []
    for run in runs:
        version = await session.get(EventClusterVersionModel, run.selected_event_version_id)
        if version is None:
            continue
        evidence = await load_governed_event_evidence(
            session,
            version,
            include_governed_statement=run.pipeline_version
            == ENGLISH_EVIDENCE_COPY_PIPELINE_VERSION,
        )
        if not evidence:
            continue
        summary = version.summary_projection.get("summary")
        topics.append(
            (
                run.id,
                LockedTopicContext(
                    origin=await load_locked_topic_origin(session, run),
                    business_date=run.business_date,
                    timezone=run.timezone,
                    scoring_profile=run.scoring_profile,
                    decision_kind=run.decision_kind,
                    selected_event_id=run.selected_event_id,
                    selected_event_version_id=run.selected_event_version_id,
                    no_topic_code=None,
                    title=version.representative_title,
                    summary=summary if isinstance(summary, str) else None,
                    evidence=evidence,
                ),
            )
        )
    return topics


async def generate_draft(
    generator: MaterialDraftGenerator,
    *,
    run_id: UUID,
    topic: LockedTopicContext,
    brand_context: tuple[ActiveBrandContext, ...],
    bundle: CopyVersionBundle,
    output_tokens: int,
    recent_brand_claims: tuple[str, ...],
    budget: CallBudget,
) -> MaterialDraft:
    """One first draft rendered into the operator template, like production before validation."""

    budget.take("generation")
    generated = await generator.generate(
        DraftGenerationRequest(
            run_id=run_id,
            topic=topic,
            brand_context=brand_context,
            version_bundle=bundle,
            draft_version=1,
            max_output_tokens=output_tokens,
            recent_brand_claims=recent_brand_claims,
        )
    )
    budget.spend(
        prompt_tokens=generated.prompt_tokens, completion_tokens=generated.completion_tokens
    )
    evidence = topic.evidence[0]
    return generated.draft.model_copy(
        update={
            "copywriting": render_headline_hook_copy(
                generated.draft.copywriting,
                title=topic.title or "",
                source_name=evidence.source_name,
                source_url=evidence.source_url,
            )
        }
    )


class ZhipuHookJudge:
    """Scores one hook with the provider client the copy generator already uses."""

    def __init__(self, generator: Any) -> None:
        self._client = generator._client

    async def judge(
        self, *, headline: str, evidence: str, hook: str
    ) -> tuple[HookJudgment, int, int]:
        content, completion, _latency = await self._client.complete(
            prompt=build_judge_prompt(headline=headline, evidence=evidence, hook=hook),
            output_tokens=_JUDGE_OUTPUT_TOKENS,
        )
        usage = completion.usage
        return parse_judgment(content), usage.prompt_tokens, usage.completion_tokens


def _serializable(case: CaseResult) -> dict[str, Any]:
    payload = asdict(case)
    payload["hook_judgment"] = case.hook_judgment.model_dump() if case.hook_judgment else None
    for raw, mutant in zip(payload["mutants"], case.mutants, strict=True):
        raw["judgment"] = mutant.judgment.model_dump() if mutant.judgment else None
    return payload


def write_outputs(
    output_dir: Path | None, *, summary: dict[str, Any], cases: Sequence[CaseResult]
) -> None:
    if output_dir is None:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(
        json.dumps(
            {"summary": summary, "cases": [_serializable(case) for case in cases]},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    (output_dir / "defects-report.md").write_text(
        render_defects_markdown(summary, cases), encoding="utf-8"
    )
    (output_dir / "hooks-report.md").write_text(
        render_hooks_markdown(summary, cases), encoding="utf-8"
    )
    (output_dir / "hooks-sheet.csv").write_text(hooks_sheet(cases), encoding="utf-8-sig")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="generate, seed defects, audit and score (paid calls)")
    run.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True)
    run.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True)
    run.add_argument("--limit", type=int, default=10, help="topics")
    run.add_argument("--max-calls", type=int, default=220, help="hard cap on model calls")
    run.add_argument("--output-dir", type=Path, default=None)
    run.add_argument("--plan", action="store_true", help="list the topics and stop (no calls)")
    run.add_argument("--skip-defects", action="store_true")
    run.add_argument("--skip-hooks", action="store_true")
    agreement = commands.add_parser("agreement", help="judge-versus-human agreement from a sheet")
    agreement.add_argument("--sheet", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "agreement":
        print(render_agreement_markdown(args.sheet.read_text(encoding="utf-8-sig")), end="")
        return 0
    if args.limit < 1 or args.max_calls < 1:
        parser.error("--limit and --max-calls must be positive")
    return asyncio.run(_run_live(args))


if __name__ == "__main__":
    raise SystemExit(main())
