"""Would a new auditor configuration block drafts production already accepted?

Takes the newest drafts production accepted under the headline-hook rules, re-audits each one with
the configurations given, and lists every draft a configuration would block, with its error
codes and the hook, so a person can judge whether each block is a real problem (caught by the
new configuration) or a false alarm. Reads the database through the read-only ops role
(OPS_DATABASE_URL). Single run; verdicts are model judgements, not human labels.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from evals.copy_audit_compare.runner import AuditorConfig, parse_configs


def render(configs: Sequence[AuditorConfig], rows: list[dict[str, Any]], calls: int) -> str:
    lines = [
        "# 线上已通过的稿子，用新审查配置重审",
        "",
        f"- 稿子 {len(rows)} 份：生产上已通过（规则 v13 引导语模板）的最新稿，"
        f"模型调用 {calls} 次。",
        "- 被拦 = 新配置会判为不通过；需要人看每一份，判断是真问题还是误拦。",
        "- 审查结论是模型判断，不是人工标注。",
        "",
        "| 配置 | 会被拦的稿子 |",
        "|---|---|",
    ]
    for config in configs:
        blocked = sum(1 for row in rows if row["verdicts"].get(config.name, {}).get("blocked"))
        lines.append(
            f"| {config.name}（{config.prompt_version} · {config.model}） | {blocked}/{len(rows)} |"
        )
    lines += ["", "## 会被拦的稿子", ""]
    for row in rows:
        for config in configs:
            verdict = row["verdicts"].get(config.name, {})
            if verdict.get("blocked"):
                lines.append(
                    f"- {row['business_date']} {row['content_slot'] or ''} · {config.name} · "
                    f"{'、'.join(verdict['codes'])} · 引导语：{row['hook']}"
                )
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> tuple[str, list[dict[str, Any]]]:
    import httpx
    from app.application.ports.copy_generation import DraftAuditRequest
    from app.application.services.copy_generation import build_copy_version_bundle
    from app.core.config import get_settings
    from app.core.errors import ProviderError
    from app.domain.copy_generation import HEADLINE_HOOK_COPY_RULE_VERSIONS, apply_copy_audit_policy
    from app.infrastructure.ai.copy_generation import create_zhipu_copy_models
    from app.infrastructure.db.copy_repair_workspace import load_repair_workspace
    from app.infrastructure.db.models import ContentSlotSelectionModel, CopyGenerationRunModel
    from app.infrastructure.db.ops_reader import (
        create_ops_engine,
        ops_database_url,
        verify_read_only_role,
    )
    from app.schemas.copy_generation import extract_headline_hook
    from pydantic import SecretStr
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    configs = parse_configs(args.config)
    settings = get_settings()
    if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
        raise SystemExit("the copy provider settings are missing")
    engine = create_ops_engine(ops_database_url(os.environ))
    client = httpx.AsyncClient(follow_redirects=False)
    rows: list[dict[str, Any]] = []
    calls = 0
    try:
        await verify_read_only_role(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        run, selection = CopyGenerationRunModel, ContentSlotSelectionModel
        async with factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            candidates = (
                await session.execute(
                    select(run.id, run.business_date, run.version_bundle, selection.content_slot)
                    .outerjoin(selection, run.content_slot_selection_id == selection.id)
                    .where(
                        run.status == "accepted",
                        run.decision_kind == "selected",
                        run.business_date >= args.date_from,
                        run.business_date <= args.date_to,
                    )
                    .order_by(run.created_at.desc())
                    .limit(args.limit * 3)
                )
            ).all()
            await session.rollback()
        picked = [
            row
            for row in candidates
            if isinstance(row.version_bundle, dict)
            and row.version_bundle.get("rule_version") in HEADLINE_HOOK_COPY_RULE_VERSIONS
        ][: args.limit]
        base_url = settings.ai_platform_base_url
        api_key = SecretStr(settings.ai_platform_api_key.get_secret_value())
        bundle = build_copy_version_bundle(
            settings, scoring_profile=settings.content_scoring_profile
        )
        auditors = {
            config.name: create_zhipu_copy_models(
                client=client,
                base_url=base_url,
                api_key=api_key,
                model=config.model,
                connect_timeout_seconds=settings.ai_connect_timeout_seconds,
                read_timeout_seconds=settings.ai_read_timeout_seconds,
                total_timeout_seconds=settings.ai_total_timeout_seconds,
                concurrency=settings.ai_provider_concurrency,
                max_attempts=settings.ai_max_attempts,
                max_input_characters=settings.ai_max_input_characters,
                max_output_tokens=settings.copy_max_output_tokens,
                max_validation_corrections=settings.ai_max_validation_corrections,
            )[1]
            for config in configs
        }
        for candidate in picked:
            try:
                workspace = await load_repair_workspace(factory, candidate.id)
            except Exception as error:  # an inactive brand chunk etc.; skip the run
                print(f"skipped {candidate.id}: {type(error).__name__}", file=sys.stderr)
                continue
            row: dict[str, Any] = {
                "run_id": str(candidate.id),
                "business_date": candidate.business_date.isoformat(),
                "content_slot": candidate.content_slot,
                "hook": extract_headline_hook(
                    workspace.draft.copywriting, title=workspace.topic.title or ""
                ),
                "verdicts": {},
            }
            for config in configs:
                if calls >= args.max_calls:
                    break
                calls += 1
                try:
                    result = await auditors[config.name].audit(
                        DraftAuditRequest(
                            run_id=candidate.id,
                            draft_version_id=candidate.id,
                            topic=workspace.topic,
                            brand_context=workspace.brand_context,
                            draft=workspace.draft,
                            version_bundle=replace(
                                bundle,
                                auditor_prompt_version=config.prompt_version,
                                model=config.model,
                                rule_version=workspace.rule_version,
                            ),
                            max_output_tokens=settings.copy_audit_max_output_tokens,
                        )
                    )
                except ProviderError as error:
                    row["verdicts"][config.name] = {"error": type(error).__name__}
                    continue
                verdict = apply_copy_audit_policy(
                    result.verdict, rule_version=workspace.rule_version
                )
                row["verdicts"][config.name] = {
                    "blocked": not verdict.accepted,
                    "codes": [issue.code for issue in verdict.issues if issue.severity == "error"],
                }
            rows.append(row)
    finally:
        await client.aclose()
        await engine.dispose()
    return render(configs, rows, calls), rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--max-calls", type=int, default=40)
    parser.add_argument("--config", action="append", required=True)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args(argv)
    report, rows = asyncio.run(run(args))
    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "accepted-replay-report.md").write_text(report, encoding="utf-8")
        (out / "accepted-replay-results.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
