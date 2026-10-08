"""Replay the current repair agent on the blocked drafts production gave to the agent.

For every copy run where production tried the repair agent (its draft became draft 2, or its
attempt was dropped and the run regenerated), load draft 1 with its blocking issues and the brand
context production used (read-only ops role), run the current agent, gate the result with the
same rules and the run's own auditor, and compare with what production's agent did.

    OPS_DATABASE_URL=... python -m evals.copy_repair.replay_production \\
        --report evals/copy_repair/reports/2026-10-08-brand-by-id.md --output /tmp/replay.json

Aggregates only in the report; no copy text.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from app.application.services.copy_repair_agent import REPAIR_AGENT_VERSION
from app.copy_repair_shadow_main import CallCap, CallCapReachedError, agent_arm
from sqlalchemy import text

_AGENT_RUNS = """
SELECT DISTINCT j.run_id,
       bool_or(a.safe_metadata->>'repair_method' = 'agent') AS agent_fixed,
       max(a.safe_metadata->>'repair_agent_version') AS version,
       max(r.created_at) AS created
FROM copy_generation_attempts a
JOIN copy_generation_jobs j ON j.id = a.job_id
JOIN copy_generation_runs r ON r.id = j.run_id
WHERE (a.capability = 'generation' AND a.safe_metadata->>'repair_method' = 'agent')
   OR (a.capability = 'workflow' AND a.error_code LIKE 'repair\\_agent\\_%')
GROUP BY j.run_id
ORDER BY created
"""


async def _run(args: argparse.Namespace) -> list[dict[str, Any]]:
    import httpx
    from app.core.config import get_settings
    from app.infrastructure.ai.copy_generation import create_zhipu_copy_models
    from app.infrastructure.ai.copy_repair import ZhipuRepairChatModel
    from app.infrastructure.db.copy_repair_workspace import load_blocked_case
    from app.infrastructure.db.ops_reader import (
        create_ops_engine,
        ops_database_url,
        verify_read_only_role,
    )
    from pydantic import SecretStr
    from sqlalchemy.ext.asyncio import async_sessionmaker

    settings = get_settings()
    if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
        raise SystemExit("AI_PLATFORM_BASE_URL and AI_PLATFORM_API_KEY are required")
    engine = create_ops_engine(ops_database_url(os.environ))
    client = httpx.AsyncClient(follow_redirects=False)
    cap = CallCap(limit=args.max_calls)
    results: list[dict[str, Any]] = []
    try:
        await verify_read_only_role(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            rows = (await session.execute(text(_AGENT_RUNS))).all()
            await session.rollback()
        generator, auditor = create_zhipu_copy_models(
            client=client,
            base_url=settings.ai_platform_base_url,
            api_key=SecretStr(settings.ai_platform_api_key.get_secret_value()),
            model=settings.ai_chat_model,
            connect_timeout_seconds=settings.ai_connect_timeout_seconds,
            read_timeout_seconds=settings.ai_read_timeout_seconds,
            total_timeout_seconds=settings.ai_total_timeout_seconds,
            concurrency=1,
            max_attempts=settings.ai_max_attempts,
            max_input_characters=settings.ai_max_input_characters,
            max_output_tokens=settings.copy_max_output_tokens,
            max_validation_corrections=settings.ai_max_validation_corrections,
        )
        model = ZhipuRepairChatModel(generator._client)
        for run_id, production_fixed, production_version, _ in rows:
            case = await load_blocked_case(factory, UUID(str(run_id)))
            if case is None:
                continue
            for repeat in range(args.repeats):
                try:
                    arm = await agent_arm(
                        case,
                        model=model,
                        auditor=auditor,
                        cap=cap,
                        max_rounds=6,
                        audit_max_output_tokens=settings.copy_audit_max_output_tokens,
                    )
                except CallCapReachedError:
                    return results
                results.append(
                    {
                        "run_id": str(run_id)[:8],
                        "repeat": repeat + 1,
                        "blocking_codes": [issue.code for issue in case.blocking_issues],
                        "production_version": production_version,
                        "production_agent_fixed": bool(production_fixed),
                        "passed": arm["passed"],
                        "stopped": arm["stopped"],
                        "rounds": arm["rounds"],
                        "tool_calls": arm["tool_calls"],
                        "prompt_tokens": arm["prompt_tokens"],
                        "edits": arm["edits"],
                        "tool_errors": _tool_errors(arm["trace"]),
                        "brand_statement_kept": arm["brand_statement_kept"],
                        "left_codes": arm["left_codes"],
                    }
                )
    finally:
        await client.aclose()
        await engine.dispose()
    return results


def _tool_errors(trace: object) -> list[str]:
    steps = trace if isinstance(trace, list) else []
    return sorted(
        {str(s["error_code"]) for s in steps if isinstance(s, dict) and s.get("error_code")}
    )


def render(results: Sequence[dict[str, Any]]) -> str:
    total = len(results)
    passed = sum(r["passed"] for r in results)
    runs = sorted({r["run_id"] for r in results})
    production = {r["run_id"]: r["production_agent_fixed"] for r in results}
    prod_fixed = sum(production.values())
    stops = Counter(r["stopped"] for r in results)
    tokens = sum(r["prompt_tokens"] for r in results) / max(total, 1)
    lines = [
        f"# 修复 Agent 生产回放（{REPAIR_AGENT_VERSION}）",
        "",
        "- 生产上交给修复 Agent 的被拦稿，用线上同一份初稿、拦截问题和品牌资料，"
        "在本地重跑当前 Agent，再过同样的规则和该任务当时的审查版本。"
        "审查是模型判断，不是人工标注。",
        f"- {len(runs)} 份被拦稿 × 每份 {total // max(len(runs), 1)} 次。",
        "",
        "| | 结果 |",
        "|---|---|",
        f"| 线上旧版 Agent 修好 | {prod_fixed}/{len(runs)} |",
        f"| 当前版本修好（按次） | {passed}/{total}（{passed / max(total, 1):.0%}） |",
        f"| 品牌句保留 | {sum(r['brand_statement_kept'] for r in results)}/{total} |",
        f"| 停止原因 | {'、'.join(f'{k} {v}' for k, v in stops.most_common())} |",
        f"| 平均输入 token | {tokens:,.0f} |",
        "",
        "| 任务 | 拦截原因 | 线上旧版 | 当前版本 | 停止 / 工具错误 |",
        "|---|---|---|---|---|",
    ]
    for run_id in runs:
        items = [r for r in results if r["run_id"] == run_id]
        ok = sum(r["passed"] for r in items)
        codes = "、".join(items[0]["blocking_codes"])
        stopped = "；".join(
            f"{r['stopped']}" + (f"（{','.join(r['tool_errors'])}）" if r["tool_errors"] else "")
            for r in items
        )
        old = "修好" if production[run_id] else "退回重写"
        lines.append(f"| {run_id} | {codes} | {old} | {ok}/{len(items)} | {stopped} |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-calls", type=int, default=120)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    results = asyncio.run(_run(args))
    report = render(results)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    if args.output:
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
