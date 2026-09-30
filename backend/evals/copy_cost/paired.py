"""Paired comparison of two copy prompt bundles on the same topics, drafts and seeded defects.

Per topic: one draft from each generator version (token cost of generation), then the control and
every seeded mutant of the candidate's draft go through the rules and BOTH auditor versions. The
same drafts and mutants are judged by both auditors, so differences come from the auditor, not
from a new random draft.

Blocks are split by reason: an error code in the defect's expected family counts as the right
reason; any other error code (a schema complaint, say) is a block for another reason. The family
map is a keyword heuristic over the auditor's free-form codes and is stated in the report.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from evals.copy_quality.mutations import build_mutants
from evals.copy_quality.runner import (
    CallBudget,
    GateResult,
    dates_between,
    generate_draft,
    load_accepted_topics,
    run_gates,
)

FAMILIES: dict[str, tuple[str, ...]] = {
    "hook_anxiety_listed": ("anxiety",),
    "hook_anxiety_paraphrase": ("anxiety",),
    "hook_marketing_listed": ("marketing", "promise"),
    "hook_marketing_paraphrase": ("marketing", "promise", "brand_claim"),
    "hook_off_topic": ("relevan", "off_topic", "unrelated", "topic"),
    "hook_fabricated_number": ("fact", "number", "unclaimed"),
    "hook_fabricated_policy": ("fact", "ungrounded", "unverified", "fabricat"),
    "brand_effect_fabricated": ("brand_claim",),
    "brand_as_fact_binding": ("brand_as_fact", "unbound"),
    "claim_number_outside_evidence": ("evidence", "mismatch", "fact"),
    "claim_number_swapped": ("evidence", "mismatch", "fact"),
    "claim_subject_swapped": ("evidence", "mismatch", "fact"),
    "claim_meaning_reversed": ("evidence", "mismatch", "fact"),
}
OUTCOMES = ("right_reason", "other_reason", "warned", "missed")
PROVIDER_ERROR = "provider_error"


def classify(defect: str, gate: GateResult) -> str:
    if gate.outcome.startswith("blocked"):
        codes = (*gate.validator_errors, *gate.auditor_errors)
        family = FAMILIES.get(defect, ())
        return (
            "right_reason" if any(k in code for code in codes for k in family) else "other_reason"
        )
    return "warned" if gate.outcome == "passed_with_new_warnings" else "missed"


@dataclass(slots=True)
class Tokens:
    calls: int = 0
    prompt: int = 0
    completion: int = 0

    def add(self, prompt: int, completion: int) -> None:
        self.calls += 1
        self.prompt += prompt
        self.completion += completion


@dataclass(slots=True)
class Tally:
    control: Counter[str] = field(default_factory=Counter)
    provider_errors: int = 0
    control_codes: Counter[str] = field(default_factory=Counter)
    defects: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    codes: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))


class CountingAuditor:
    """Wraps an auditor so its per-call tokens land in one bucket."""

    def __init__(self, inner: Any, tokens: Tokens) -> None:
        self._inner = inner
        self._tokens = tokens

    async def audit(self, request: Any) -> Any:
        result = await self._inner.audit(request)
        self._tokens.add(result.prompt_tokens, result.completion_tokens)
        return result


async def _gated(tally: Tally, draft: Any, **kwargs: Any) -> GateResult | None:
    """run_gates, but a provider rejection is counted instead of ending the run."""
    from app.core.errors import ProviderError

    try:
        return await run_gates(draft, **kwargs)
    except ProviderError as error:
        tally.provider_errors += 1
        print(f"audit skipped: {type(error).__name__}", file=sys.stderr)
        return None


def render(
    *,
    baseline: str,
    candidate: str,
    topics: int,
    generation: dict[str, Tokens],
    audit: dict[str, Tokens],
    tallies: dict[str, Tally],
) -> str:
    def avg(t: Tokens) -> str:
        return f"{t.prompt / t.calls:,.0f} / {t.completion / t.calls:,.0f}" if t.calls else "–"

    lines = [
        "# 配对对比：同一批选题、初稿和埋雷，两套提示词版本",
        "",
        f"- 选题 {topics} 条（生产上真实通过的）；基线 `{baseline}`，候选 `{candidate}`。",
        "- 生成：每条选题两个生成版本各生成一次，只比 token 与初稿是否过规则。",
        "- 审查：原稿和埋雷稿都用候选生成的初稿，两个审查版本审同一批文案。",
        "- 拦截理由按错误码关键词归类（启发式，见脚本 FAMILIES）；单次运行，没有重复试验。",
        "",
        "## 每次调用平均 token（输入 / 输出）",
        "",
        "| 环节 | 基线 | 候选 | 输入变化 |",
        "|---|---|---|---|",
    ]
    for label, bucket in (("生成", generation), ("审查", audit)):
        base, cand = bucket["baseline"], bucket["candidate"]
        change = (
            f"{(cand.prompt / cand.calls) / (base.prompt / base.calls) - 1:+.0%}"
            if base.calls and cand.calls
            else "–"
        )
        lines.append(f"| {label} | {avg(base)} | {avg(cand)} | {change} |")
    lines.append("")
    lines.append(
        "- 模型服务拒绝的审查调用：基线 "
        f"{tallies['baseline'].provider_errors} 次，候选 {tallies['candidate'].provider_errors} 次"
        "（计为无结果，不算拦截）。"
    )
    lines += [
        "",
        "## 原稿（对照组）",
        "",
        "| 审查版本 | 通过 | 只提醒 | 被拦 | 被拦原因 |",
        "|---|---|---|---|---|",
    ]
    for name in ("baseline", "candidate"):
        tally = tallies[name]
        lines.append(
            f"| {name} | {tally.control['passed']} | {tally.control['passed_with_new_warnings']} | "
            f"{tally.control['blocked']} | "
            f"{', '.join(f'{k}×{v}' for k, v in tally.control_codes.most_common()) or '–'} |"
        )
    lines += [
        "",
        "## 埋雷（同一批埋雷稿）",
        "",
        "| 缺陷 | 适用 | 基线：理由对 / 碰巧拦 / 只提醒 / 漏过 "
        "| 候选：理由对 / 碰巧拦 / 只提醒 / 漏过 |",
        "|---|---|---|---|",
    ]
    for defect in FAMILIES:
        base_counts = tallies["baseline"].defects.get(defect, Counter())
        cand_counts = tallies["candidate"].defects.get(defect, Counter())
        if not base_counts and not cand_counts:
            continue
        total = sum(base_counts.values())
        cells = [
            " / ".join(str(counts[o]) for o in OUTCOMES) for counts in (base_counts, cand_counts)
        ]
        lines.append(f"| {defect} | {total} | {cells[0]} | {cells[1]} |")
    for name in ("baseline", "candidate"):
        totals: Counter[str] = Counter()
        for counter in tallies[name].defects.values():
            totals.update(counter)
        n = sum(totals.values())
        lines.append("")
        lines.append(
            f"- {name}：{n} 个埋雷，理由对 {totals['right_reason']}"
            f"（{totals['right_reason'] / n:.0%}），"
            f"碰巧拦 {totals['other_reason']}，只提醒 {totals['warned']}，漏过 {totals['missed']}。"
            if n
            else f"- {name}：没有可比的埋雷。"
        )
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    import httpx
    from app.application.ports.copy_generation import RecentBrandUsage
    from app.application.services.copy_generation import (
        BRAND_ROTATION_CLAIM_LIMIT,
        BRAND_ROTATION_GENERATOR_PROMPT_VERSIONS,
        BRAND_ROTATION_LOOKBACK_DAYS,
        BrandRagContextRetriever,
        build_copy_version_bundle,
    )
    from app.core.config import get_settings
    from app.core.errors import ProviderError
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
    base_bundle = build_copy_version_bundle(
        settings, scoring_profile=settings.content_scoring_profile
    )
    bundles = {
        "baseline": replace(
            base_bundle,
            generator_prompt_version=args.baseline_generator,
            auditor_prompt_version=args.baseline_auditor,
        ),
        "candidate": replace(
            base_bundle,
            generator_prompt_version=args.candidate_generator,
            auditor_prompt_version=args.candidate_auditor,
        ),
    }
    if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
        raise SystemExit("the copy provider settings are missing")
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    client = httpx.AsyncClient(follow_redirects=False)
    budget = CallBudget(limit=args.max_calls)
    generation = {"baseline": Tokens(), "candidate": Tokens()}
    audit = {"baseline": Tokens(), "candidate": Tokens()}
    tallies = {"baseline": Tally(), "candidate": Tally()}
    cases: list[dict[str, Any]] = []
    try:
        topics = []
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
            await session.rollback()
        topics = topics[: args.limit]
        print(f"{len(topics)} topics; cap {args.max_calls} calls", file=sys.stderr)
        if args.plan:
            return "", {}
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
        auditors = {name: CountingAuditor(auditor, audit[name]) for name in bundles}
        for index, (run_id, topic) in enumerate(topics, start=1):
            recent = history.get(topic.business_date, RecentBrandUsage())
            rotation = (
                bundles["candidate"].generator_prompt_version
                in BRAND_ROTATION_GENERATOR_PROMPT_VERSIONS
            )
            brand = (
                await retriever.retrieve_for_copy(topic, recent_usage=recent)
                if rotation
                else await retriever.retrieve_for_copy(topic)
            )
            drafts = {}
            skipped = False
            for name, bundle in bundles.items():
                if skipped:
                    break
                before = (budget.prompt_tokens, budget.completion_tokens)
                try:
                    drafts[name] = await generate_draft(
                        generator,
                        run_id=run_id,
                        topic=topic,
                        brand_context=brand,
                        bundle=bundle,
                        output_tokens=settings.copy_max_output_tokens,
                        recent_brand_claims=recent.claim_texts if rotation else (),
                        budget=budget,
                    )
                except ProviderError as error:
                    print(f"generation skipped: {type(error).__name__}", file=sys.stderr)
                    skipped = True
                    continue
                generation[name].add(
                    budget.prompt_tokens - before[0], budget.completion_tokens - before[1]
                )
            if skipped:
                cases.append({"headline": topic.title, "skipped": "generation_provider_error"})
                continue
            draft = drafts["candidate"]
            case: dict[str, Any] = {"headline": topic.title, "control": {}, "mutants": []}
            controls = {}
            for name, bundle in bundles.items():
                gate = await _gated(
                    tallies[name],
                    draft,
                    run_id=run_id,
                    topic=topic,
                    brand_context=brand,
                    bundle=bundle,
                    auditor=auditors[name],
                    audit_output_tokens=settings.copy_audit_max_output_tokens,
                    budget=budget,
                )
                if gate is None:
                    break
                controls[name] = gate
                outcome = "blocked" if gate.blocked else gate.outcome
                tallies[name].control[outcome] += 1
                tallies[name].control_codes.update(gate.auditor_errors + gate.validator_errors)
                case["control"][name] = {"outcome": gate.outcome, "errors": gate.auditor_errors}
            if len(controls) < len(bundles) or any(gate.blocked for gate in controls.values()):
                cases.append(case)
                continue
            for defect, mutant in build_mutants(draft, topic=topic, brand_context=brand):
                row: dict[str, Any] = {"defect": defect.code}
                for name, bundle in bundles.items():
                    gate = await _gated(
                        tallies[name],
                        mutant,
                        run_id=run_id,
                        topic=topic,
                        brand_context=brand,
                        bundle=bundle,
                        auditor=auditors[name],
                        audit_output_tokens=settings.copy_audit_max_output_tokens,
                        budget=budget,
                        baseline_warnings=controls[name].warnings,
                    )
                    if gate is None:
                        tallies[name].defects[defect.code][PROVIDER_ERROR] += 1
                        row[name] = {"outcome": PROVIDER_ERROR, "errors": []}
                        continue
                    verdict = classify(defect.code, gate)
                    tallies[name].defects[defect.code][verdict] += 1
                    tallies[name].codes[defect.code].update(
                        gate.validator_errors + gate.auditor_errors
                    )
                    row[name] = {
                        "outcome": verdict,
                        "errors": [*gate.validator_errors, *gate.auditor_errors],
                    }
                case["mutants"].append(row)
            cases.append(case)
            print(f"[{index}/{len(topics)}] {topic.title} ({budget.used} calls)", file=sys.stderr)
    finally:
        await client.aclose()
        await engine.dispose()
    report = render(
        baseline=f"{args.baseline_generator} + {args.baseline_auditor}",
        candidate=f"{args.candidate_generator} + {args.candidate_auditor}",
        topics=len(topics),
        generation=generation,
        audit=audit,
        tallies=tallies,
    )
    raw = {
        "generation": {
            k: {"calls": v.calls, "prompt": v.prompt, "completion": v.completion}
            for k, v in generation.items()
        },
        "audit": {
            k: {"calls": v.calls, "prompt": v.prompt, "completion": v.completion}
            for k, v in audit.items()
        },
        "cases": cases,
    }
    return report, raw


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-calls", type=int, default=220)
    parser.add_argument("--baseline-generator", default="moments-generator-v26-headline-hook")
    parser.add_argument("--baseline-auditor", default="moments-auditor-v20-headline-hook")
    parser.add_argument("--candidate-generator", default="moments-generator-v27-lean-context")
    parser.add_argument("--candidate-auditor", default="moments-auditor-v21-lean-context")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args(argv)
    report, raw = asyncio.run(run(args))
    if args.plan:
        return 0
    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "paired-report.md").write_text(report, encoding="utf-8")
        (out / "paired-results.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
