"""Compare auditor configurations (prompt version x model) on the same seeded drafts.

For each real accepted topic, one control draft is generated with the production generator and
the known defects are seeded into it. Drafts the deterministic rules already block are dropped
(the auditor never sees them in production). Every remaining draft, and the clean control, is then
audited by each configuration. Reported per configuration: defects blocked, control drafts
wrongly blocked, tokens, latency (p50/p95) and provider failures. Paired: every configuration sees
exactly the same drafts. Single run; verdicts are model judgements, not human labels.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
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


@dataclass(frozen=True, slots=True)
class AuditorConfig:
    name: str
    prompt_version: str
    model: str


@dataclass(slots=True)
class ConfigTally:
    defects: int = 0
    blocked: int = 0
    controls: int = 0
    controls_blocked: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latencies: list[int] = field(default_factory=list)
    # With --repeats > 1: drafts judged, and drafts whose repeated verdicts disagreed.
    judged: int = 0
    inconsistent: int = 0
    by_defect: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))


def parse_configs(values: Sequence[str]) -> list[AuditorConfig]:
    configs = []
    for value in values:
        name, prompt_version, model = value.split(":", 2)
        configs.append(AuditorConfig(name=name, prompt_version=prompt_version, model=model))
    if len({config.name for config in configs}) != len(configs):
        raise ValueError("configuration names must be unique")
    return configs


def _percentile(values: list[int], quantile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(-(-quantile * len(ordered) // 1)) - 1))]


def render(
    configs: Sequence[AuditorConfig],
    tallies: dict[str, ConfigTally],
    *,
    topics: int,
    budget: CallBudget,
    repeats: int = 1,
) -> str:
    lines = [
        "# 审查配置对比：同一批埋雷稿",
        "",
        f"- 选题 {topics} 条（生产上真实通过的），用线上写稿版本生成初稿再埋入已知缺陷。",
        "- 只统计规则没拦下、真正交给审查的稿子；每种配置看的是完全相同的稿子。",
        f"- 模型调用共 {budget.used} 次；每份稿子每种配置审 {repeats} 遍，按多数结论计；"
        "审查结论是模型判断，不是人工标注。",
        "",
        "| 配置 | 提示词 | 模型 | 缺陷拦下 | 干净稿误拦 | 重复审结论不一致 | 每次输入 token "
        "| 每次输出 token | p50 | p95 | 调用失败 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for config in configs:
        tally = tallies[config.name]
        calls = max(len(tally.latencies), 1)
        lines.append(
            f"| {config.name} | {config.prompt_version} | {config.model} | "
            f"{tally.blocked}/{tally.defects} | {tally.controls_blocked}/{tally.controls} | "
            f"{(f'{tally.inconsistent}/{tally.judged}' if repeats > 1 else '—')} | "
            f"{tally.prompt_tokens / calls:,.0f} | {tally.completion_tokens / calls:,.0f} | "
            f"{_percentile(tally.latencies, 0.5) / 1000:.1f}s | "
            f"{_percentile(tally.latencies, 0.95) / 1000:.1f}s | {tally.failures} |"
        )
    defects = sorted({code for tally in tallies.values() for code in tally.by_defect})
    lines += ["", "## 按缺陷", "", "| 缺陷 | " + " | ".join(c.name for c in configs) + " |"]
    lines.append("|---|" + "---|" * len(configs))
    for code in defects:
        cells = []
        for config in configs:
            blocked, total = tallies[config.name].by_defect.get(code, [0, 0])
            cells.append(f"{blocked}/{total}")
        lines.append(f"| {code} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    import httpx
    from app.application.ports.copy_generation import DraftAuditRequest, RecentBrandUsage
    from app.application.services.copy_generation import (
        BRAND_ROTATION_CLAIM_LIMIT,
        BRAND_ROTATION_GENERATOR_PROMPT_VERSIONS,
        BRAND_ROTATION_LOOKBACK_DAYS,
        BrandRagContextRetriever,
        build_copy_version_bundle,
    )
    from app.core.config import get_settings
    from app.core.errors import ProviderError
    from app.domain.copy_generation import apply_copy_audit_policy, validate_material_draft
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

    configs = parse_configs(args.config)
    settings = get_settings()
    bundle = build_copy_version_bundle(settings, scoring_profile=settings.content_scoring_profile)
    if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
        raise SystemExit("the copy provider settings are missing")
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    client = httpx.AsyncClient(follow_redirects=False)
    budget = CallBudget(limit=args.max_calls)
    tallies = {config.name: ConfigTally() for config in configs}
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
        print(
            f"{len(topics)} topics; {len(configs)} configs; cap {args.max_calls}", file=sys.stderr
        )
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

        base_url = settings.ai_platform_base_url
        api_key = SecretStr(settings.ai_platform_api_key.get_secret_value())

        def models_for(model: str) -> tuple[Any, Any]:
            return create_zhipu_copy_models(
                client=client,
                base_url=base_url,
                api_key=api_key,
                model=model,
                connect_timeout_seconds=settings.ai_connect_timeout_seconds,
                read_timeout_seconds=settings.ai_read_timeout_seconds,
                total_timeout_seconds=settings.ai_total_timeout_seconds,
                concurrency=settings.ai_provider_concurrency,
                max_attempts=settings.ai_max_attempts,
                max_input_characters=settings.ai_max_input_characters,
                max_output_tokens=settings.copy_max_output_tokens,
                max_validation_corrections=settings.ai_max_validation_corrections,
            )

        generator, _ = models_for(settings.ai_chat_model)
        auditors = {config.name: models_for(config.model)[1] for config in configs}
        bundles = {
            config.name: replace(
                bundle, auditor_prompt_version=config.prompt_version, model=config.model
            )
            for config in configs
        }
        rotation = bundle.generator_prompt_version in BRAND_ROTATION_GENERATOR_PROMPT_VERSIONS

        async def audit(config: AuditorConfig, draft: Any, topic: Any, brand: Any) -> bool | None:
            tally = tallies[config.name]
            budget.take("audit")
            try:
                result = await auditors[config.name].audit(
                    DraftAuditRequest(
                        run_id=UUID(int=0),
                        draft_version_id=UUID(int=0),
                        topic=topic,
                        brand_context=brand,
                        draft=draft,
                        version_bundle=bundles[config.name],
                        max_output_tokens=settings.copy_audit_max_output_tokens,
                    )
                )
            except ProviderError:
                tally.failures += 1
                return None
            budget.spend(
                prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens
            )
            tally.prompt_tokens += result.prompt_tokens
            tally.completion_tokens += result.completion_tokens
            tally.latencies.append(result.latency_ms)
            verdict = apply_copy_audit_policy(result.verdict, rule_version=bundle.rule_version)
            return not verdict.accepted

        async def judge(config: AuditorConfig, draft: Any, topic: Any, brand: Any) -> bool | None:
            verdicts = [
                verdict
                for _ in range(args.repeats)
                if (verdict := await audit(config, draft, topic, brand)) is not None
            ]
            if not verdicts:
                return None
            tally = tallies[config.name]
            tally.judged += 1
            tally.inconsistent += len(set(verdicts)) > 1
            return sum(verdicts) * 2 > len(verdicts)

        for index, (run_id, topic) in enumerate(topics, start=1):
            recent = history.get(topic.business_date, RecentBrandUsage())
            try:
                brand = (
                    await retriever.retrieve_for_copy(topic, recent_usage=recent)
                    if rotation
                    else await retriever.retrieve_for_copy(topic)
                )
                control = await generate_draft(
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
                print(f"topic skipped: {type(error).__name__}", file=sys.stderr)
                continue
            rule_errors = [
                issue
                for issue in validate_material_draft(
                    control, topic=topic, brand_context=brand, rule_version=bundle.rule_version
                )
                if issue.severity == "error"
            ]
            if rule_errors:
                continue
            case: dict[str, Any] = {"headline": topic.title, "control": {}, "defects": []}
            for config in configs:
                blocked = await judge(config, control, topic, brand)
                if blocked is not None:
                    tallies[config.name].controls += 1
                    tallies[config.name].controls_blocked += blocked
                case["control"][config.name] = blocked
            for defect, mutant in build_mutants(control, topic=topic, brand_context=brand):
                if any(
                    issue.severity == "error"
                    for issue in validate_material_draft(
                        mutant, topic=topic, brand_context=brand, rule_version=bundle.rule_version
                    )
                ):
                    continue
                row: dict[str, Any] = {"defect": defect.code}
                for config in configs:
                    blocked = await judge(config, mutant, topic, brand)
                    if blocked is None:
                        continue
                    tally = tallies[config.name]
                    tally.defects += 1
                    tally.blocked += blocked
                    tally.by_defect[defect.code][0] += blocked
                    tally.by_defect[defect.code][1] += 1
                    row[config.name] = blocked
                case["defects"].append(row)
            cases.append(case)
            print(f"[{index}/{len(topics)}] {topic.title} ({budget.used} calls)", file=sys.stderr)
    except BudgetExhaustedError as error:
        print(str(error), file=sys.stderr)
    finally:
        await client.aclose()
        await engine.dispose()
    report = render(configs, tallies, topics=len(topics), budget=budget, repeats=args.repeats)
    summary = {
        name: {
            "defects_blocked": tally.blocked,
            "defects": tally.defects,
            "controls_blocked": tally.controls_blocked,
            "controls": tally.controls,
            "inconsistent": tally.inconsistent,
            "judged": tally.judged,
            "failures": tally.failures,
        }
        for name, tally in tallies.items()
    }
    return report, {"cases": cases, "summary": summary, "calls": budget.used}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-calls", type=int, default=220)
    parser.add_argument("--repeats", type=int, default=1, help="audits per draft and config")
    parser.add_argument(
        "--config",
        action="append",
        required=True,
        help="name:auditor_prompt_version:model, repeatable",
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args(argv)
    report, raw = asyncio.run(run(args))
    if args.plan:
        return 0
    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "audit-compare-report.md").write_text(report, encoding="utf-8")
        (out / "audit-compare-results.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
