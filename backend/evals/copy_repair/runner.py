"""Does the tool-using repair agent fix blocked drafts better than a full regeneration?

For real accepted topics: generate a draft, seed the known defects, run the production gates
(rules, then the auditor). Every blocked mutant is repaired twice from the same starting point:

- agent: the copy repair agent with its tool registry (bounded rounds and calls);
- regenerate: today's production repair, one new draft with the issue list and previous draft.

Each repaired draft goes through the same gates again. Reported per defect: repaired and passing,
whether the seeded text is gone, and model calls and tokens per repair. Single run; model scores
are not human labels.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from evals.copy_quality.mutations import build_mutants
from evals.copy_quality.runner import (
    BudgetExhaustedError,
    CallBudget,
    dates_between,
    generate_draft,
    load_accepted_topics,
)


@dataclass(slots=True)
class ArmTally:
    attempted: int = 0
    passed: int = 0
    defect_gone: int = 0
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    errors: int = 0
    stopped: Counter[str] = field(default_factory=Counter)


def seeded_defect(target: str, mutant: Any, base: Any, title: str) -> object:
    """What the mutation put in: the hook sentence, or the changed claims (text and bindings)."""

    from app.schemas.copy_generation import extract_headline_hook

    if target == "hook":
        return str(extract_headline_hook(mutant.copywriting, title=title)).strip()
    before = set(base.claims)
    return tuple(claim for claim in mutant.claims if claim not in before)


def defect_remains(target: str, seeded: object, draft: Any, title: str) -> bool:
    from app.schemas.copy_generation import extract_headline_hook

    if target == "hook":
        return (
            bool(seeded) and extract_headline_hook(draft.copywriting, title=title).strip() == seeded
        )
    assert isinstance(seeded, tuple)
    return any(claim in seeded for claim in draft.claims)


ARMS = ("agent", "regenerate", "hybrid")


def tally_hybrid(arm: ArmTally, row: dict[str, Any]) -> None:
    """Agent first; when its draft still fails the gate, the regeneration result counts."""

    agent, regen = row.get("agent", {}), row.get("regenerate", {})
    arm.attempted += 1
    agent_ok = agent.get("passed") is True
    arm.passed += agent_ok or regen.get("passed") is True
    arm.defect_gone += bool(agent.get("gone")) if agent_ok else bool(regen.get("gone"))
    arm.calls += int(agent.get("calls", 0)) + (0 if agent_ok else 1)
    arm.prompt_tokens += int(agent.get("prompt_tokens", 0)) + (
        0 if agent_ok else int(regen.get("prompt_tokens", 0))
    )
    arm.completion_tokens += int(agent.get("completion_tokens", 0)) + (
        0 if agent_ok else int(regen.get("completion_tokens", 0))
    )
    arm.errors += "error" in agent or ("error" in regen and not agent_ok)


def render(
    tallies: dict[str, dict[str, ArmTally]], *, topics: int, bundle: str, budget: CallBudget
) -> str:
    lines = [
        "# 修复评测：会用工具的修复 Agent vs 整篇重写",
        "",
        f"- 选题 {topics} 条（生产上真实通过的）；{bundle}。",
        "- 每个被拦下的埋雷稿从同一个起点分别修复一次，再过同样的规则和审查。",
        "- 修好 = 修复后规则与审查都不拦；缺陷去掉 = 埋入的那句文本不在修复稿里。",
        f"- 模型调用共 {budget.used} 次，输入 {budget.prompt_tokens:,} token，"
        f"输出 {budget.completion_tokens:,} token；单次运行。",
        "",
        "- 先 Agent 后重写 = Agent 没修好时，从同一份被拦稿再做一次整篇重写（即第二列的结果）。",
        "",
        "| 缺陷 | 被拦 | Agent 修好 | Agent 缺陷去掉 | 重写 修好 | 重写 缺陷去掉 "
        "| 先 Agent 后重写 修好 |",
        "|---|---|---|---|---|---|---|",
    ]
    totals = {name: ArmTally() for name in ARMS}
    for defect, arms in tallies.items():
        agent, regen, hybrid = arms["agent"], arms["regenerate"], arms["hybrid"]
        lines.append(
            f"| {defect} | {agent.attempted} | {agent.passed} | {agent.defect_gone} | "
            f"{regen.passed} | {regen.defect_gone} | {hybrid.passed} |"
        )
        for name, arm in arms.items():
            total = totals[name]
            total.attempted += arm.attempted
            total.passed += arm.passed
            total.defect_gone += arm.defect_gone
            total.calls += arm.calls
            total.prompt_tokens += arm.prompt_tokens
            total.completion_tokens += arm.completion_tokens
            total.errors += arm.errors
            total.stopped.update(arm.stopped)
    lines += [
        "",
        "## 合计",
        "",
        "| 方式 | 修好 | 缺陷去掉 | 每次修复调用 | 每次修复输入 token | 失败 |",
        "|---|---|---|---|---|---|",
    ]
    for name, label in (
        ("agent", "修复 Agent"),
        ("regenerate", "整篇重写"),
        ("hybrid", "先 Agent 后重写"),
    ):
        arm = totals[name]
        n = max(arm.attempted, 1)
        lines.append(
            f"| {label} | {arm.passed}/{arm.attempted}（{arm.passed / n:.0%}） | "
            f"{arm.defect_gone}/{arm.attempted}（{arm.defect_gone / n:.0%}） | "
            f"{arm.calls / n:.1f} | {arm.prompt_tokens / n:,.0f} | {arm.errors} |"
        )
    lines += ["", f"- Agent 结束方式：{dict(totals['agent'].stopped)}"]
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    import httpx
    from app.application.ports.copy_generation import (
        DraftAuditRequest,
        DraftGenerationRequest,
        RecentBrandUsage,
    )
    from app.application.services.copy_generation import (
        BRAND_ROTATION_CLAIM_LIMIT,
        BRAND_ROTATION_GENERATOR_PROMPT_VERSIONS,
        BRAND_ROTATION_LOOKBACK_DAYS,
        BrandRagContextRetriever,
        build_copy_version_bundle,
    )
    from app.application.services.copy_repair_agent import CopyRepairAgent
    from app.application.services.copy_repair_tools import RepairWorkspace
    from app.core.config import get_settings
    from app.core.errors import ProviderError
    from app.domain.copy_generation import apply_copy_audit_policy, validate_material_draft
    from app.infrastructure.ai.copy_generation import create_zhipu_copy_models
    from app.infrastructure.ai.copy_repair import ZhipuRepairChatModel
    from app.infrastructure.ai.factory import (
        create_brand_embedding_model,
        select_brand_embedding_client,
    )
    from app.infrastructure.db.brand_knowledge import PostgresBrandKnowledgeRepository
    from app.infrastructure.db.copy_generation import load_recent_brand_usage_before
    from app.infrastructure.db.session import create_engine, create_session_factory
    from app.schemas.copy_generation import render_headline_hook_copy
    from pydantic import SecretStr
    from sqlalchemy import text

    settings = get_settings()
    bundle = replace(
        build_copy_version_bundle(settings, scoring_profile=settings.content_scoring_profile),
        generator_prompt_version=args.generator,
        auditor_prompt_version=args.auditor,
    )
    if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
        raise SystemExit("the copy provider settings are missing")
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    client = httpx.AsyncClient(follow_redirects=False)
    budget = CallBudget(limit=args.max_calls)
    tallies: dict[str, dict[str, ArmTally]] = defaultdict(
        lambda: {name: ArmTally() for name in ARMS}
    )
    cases: list[dict[str, Any]] = []
    topics: list[tuple[UUID, Any]] = []
    try:
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
        chat = ZhipuRepairChatModel(generator._client)

        class BudgetedChat:
            def __init__(self) -> None:
                self.calls = 0

            async def complete(self, messages: Any, tools: Any) -> Any:
                budget.take("generation")
                self.calls += 1
                turn = await chat.complete(messages, tools)
                budget.spend(
                    prompt_tokens=turn.prompt_tokens, completion_tokens=turn.completion_tokens
                )
                return turn

        async def gate(
            draft: Any, topic: Any, brand: Any, run_id: UUID
        ) -> tuple[bool, tuple[Any, ...]]:
            issues = validate_material_draft(
                draft, topic=topic, brand_context=brand, rule_version=bundle.rule_version
            )
            errors = tuple(issue for issue in issues if issue.severity == "error")
            if errors:
                return False, errors
            budget.take("audit")
            audit = await auditor.audit(
                DraftAuditRequest(
                    run_id=run_id,
                    draft_version_id=run_id,
                    topic=topic,
                    brand_context=brand,
                    draft=draft,
                    version_bundle=bundle,
                    max_output_tokens=settings.copy_audit_max_output_tokens,
                )
            )
            budget.spend(
                prompt_tokens=audit.prompt_tokens, completion_tokens=audit.completion_tokens
            )
            verdict = apply_copy_audit_policy(audit.verdict, rule_version=bundle.rule_version)
            return verdict.accepted, tuple(i for i in verdict.issues if i.severity == "error")

        rotation = bundle.generator_prompt_version in BRAND_ROTATION_GENERATOR_PROMPT_VERSIONS
        deadline = time.monotonic() + args.max_minutes * 60
        for index, (run_id, topic) in enumerate(topics, start=1):
            recent = history.get(topic.business_date, RecentBrandUsage())
            try:
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
                accepted, _ = await gate(draft, topic, brand, run_id)
            except ProviderError as error:
                print(f"topic skipped: {type(error).__name__}", file=sys.stderr)
                continue
            case: dict[str, Any] = {
                "headline": topic.title,
                "control_accepted": accepted,
                "mutants": [],
            }
            if not accepted:
                cases.append(case)
                continue
            title = topic.title or ""
            for defect, mutant in build_mutants(draft, topic=topic, brand_context=brand):
                if time.monotonic() > deadline:
                    raise BudgetExhaustedError("time limit reached")
                try:
                    passed, issues = await gate(mutant, topic, brand, run_id)
                except ProviderError:
                    continue
                if passed:
                    continue
                seeded = seeded_defect(defect.target, mutant, draft, title)
                row: dict[str, Any] = {"defect": defect.code, "issues": [i.code for i in issues]}
                # Arm 1: the tool-using repair agent.
                arm = tallies[defect.code]["agent"]
                arm.attempted += 1
                model = BudgetedChat()
                try:
                    workspace = RepairWorkspace(
                        topic=topic,
                        brand_context=brand,
                        rule_version=bundle.rule_version,
                        draft=mutant,
                    )
                    before = (budget.prompt_tokens, budget.completion_tokens)
                    outcome = await CopyRepairAgent(model, max_rounds=args.max_rounds).repair(
                        workspace, issues
                    )
                    arm.calls += model.calls
                    arm.prompt_tokens += budget.prompt_tokens - before[0]
                    arm.completion_tokens += budget.completion_tokens - before[1]
                    arm.stopped[outcome.stopped] += 1
                    fixed, left = await gate(outcome.draft, topic, brand, run_id)
                    gone = not defect_remains(defect.target, seeded, outcome.draft, title)
                    arm.passed += fixed
                    arm.defect_gone += gone
                    row["agent"] = {
                        "passed": fixed,
                        "gone": gone,
                        "stopped": outcome.stopped,
                        "left": [issue.code for issue in left],
                        "calls": model.calls,
                        "prompt_tokens": budget.prompt_tokens - before[0],
                        "completion_tokens": budget.completion_tokens - before[1],
                        "trace": outcome.trace,
                    }
                except ProviderError as error:
                    arm.errors += 1
                    row["agent"] = {"error": type(error).__name__}
                # Arm 2: today's production repair, a full regeneration.
                arm = tallies[defect.code]["regenerate"]
                arm.attempted += 1
                try:
                    budget.take("generation")
                    regenerated = await generator.generate(
                        DraftGenerationRequest(
                            run_id=run_id,
                            topic=topic,
                            brand_context=brand,
                            version_bundle=bundle,
                            draft_version=2,
                            max_output_tokens=settings.copy_max_output_tokens,
                            recent_brand_claims=recent.claim_texts if rotation else (),
                            repair_issues=issues,
                            previous_draft=mutant,
                        )
                    )
                    budget.spend(
                        prompt_tokens=regenerated.prompt_tokens,
                        completion_tokens=regenerated.completion_tokens,
                    )
                    arm.calls += 1
                    arm.prompt_tokens += regenerated.prompt_tokens
                    arm.completion_tokens += regenerated.completion_tokens
                    evidence = topic.evidence[0]
                    repaired = regenerated.draft.model_copy(
                        update={
                            "copywriting": render_headline_hook_copy(
                                regenerated.draft.copywriting,
                                title=title,
                                source_name=evidence.source_name,
                                source_url=evidence.source_url,
                            )
                        }
                    )
                    fixed, left = await gate(repaired, topic, brand, run_id)
                    gone = not defect_remains(defect.target, seeded, repaired, title)
                    arm.passed += fixed
                    arm.defect_gone += gone
                    row["regenerate"] = {
                        "passed": fixed,
                        "gone": gone,
                        "left": [issue.code for issue in left],
                        "prompt_tokens": regenerated.prompt_tokens,
                        "completion_tokens": regenerated.completion_tokens,
                    }
                except (ProviderError, ValueError) as error:
                    arm.errors += 1
                    row["regenerate"] = {"error": type(error).__name__}
                tally_hybrid(tallies[defect.code]["hybrid"], row)
                case["mutants"].append(row)
            cases.append(case)
            print(f"[{index}/{len(topics)}] {topic.title} ({budget.used} calls)", file=sys.stderr)
    except BudgetExhaustedError as error:
        print(str(error), file=sys.stderr)
    finally:
        await client.aclose()
        await engine.dispose()
    report = render(
        tallies,
        topics=len(topics),
        bundle=f"生成 {args.generator}，审查 {args.auditor}",
        budget=budget,
    )
    return report, {"cases": cases}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-calls", type=int, default=300)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--max-minutes", type=float, default=40)
    parser.add_argument("--generator", default="moments-generator-v27-lean-context")
    parser.add_argument("--auditor", default="moments-auditor-v22-enumerated-codes")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args(argv)
    report, raw = asyncio.run(run(args))
    if args.plan:
        return 0
    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "repair-report.md").write_text(report, encoding="utf-8")
        (out / "repair-results.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
