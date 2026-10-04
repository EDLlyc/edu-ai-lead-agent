"""Shadow mode for the copy repair: replay the arm production did not use on blocked drafts.

Nothing here changes a run, a draft or a push. For each selected copy run in the date range that
production repaired (a draft version 2), this job takes draft 1 (the blocked one) with its stored
blocking issues and production's brand context, and runs the other repair arm:

- production used the repair agent (agent_first) -> the full regeneration runs in shadow;
- production regenerated without trying the agent -> the repair agent runs in shadow;
- production tried the agent, dropped it and regenerated -> both outcomes are already known.

The shadow draft goes through the same rules and the run's own auditor version, so every blocked
draft has both arms. One JSON line per run.

Safety: the database is read through OPS_DATABASE_URL, the SELECT-only ops role, and the job
refuses to start if that role can write. Model calls are capped per run of the job. Results are
append-only JSON lines; a run already recorded is skipped, so the job can be re-run safely.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from app.application.ports.copy_generation import (
    DraftAuditRequest,
    DraftAuditResult,
    DraftGenerationRequest,
    DraftGenerationResult,
)
from app.application.services.copy_repair_agent import (
    REPAIR_AGENT_VERSION,
    ChatTurn,
    CopyRepairAgent,
    RepairChatModel,
)
from app.application.services.copy_repair_tools import (
    REPAIR_TOOLSET_VERSION,
    RepairWorkspace,
    UnsupportedRuleVersionError,
)
from app.domain.copy_generation import apply_copy_audit_policy, validate_material_draft
from app.infrastructure.db.copy_repair_workspace import BlockedCase
from app.schemas.copy_generation import (
    MaterialDraft,
    extract_headline_hook,
    render_headline_hook_copy,
)

SHADOW_SCHEMA = "copy-repair-shadow-v2"
BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")


class CallCapReachedError(RuntimeError):
    pass


@dataclass(slots=True)
class CallCap:
    limit: int
    used: int = 0

    def take(self) -> None:
        if self.used >= self.limit:
            raise CallCapReachedError(f"model-call cap of {self.limit} reached")
        self.used += 1


class Auditor(Protocol):
    async def audit(self, request: DraftAuditRequest) -> DraftAuditResult: ...


class Generator(Protocol):
    async def generate(self, request: DraftGenerationRequest) -> DraftGenerationResult: ...


class _CappedChat:
    def __init__(self, model: RepairChatModel, cap: CallCap) -> None:
        self._model = model
        self._cap = cap

    async def complete(self, messages: Any, tools: Any) -> ChatTurn:
        self._cap.take()
        return await self._model.complete(messages, tools)


async def gate(
    draft: MaterialDraft,
    case: BlockedCase,
    auditor: Auditor,
    *,
    cap: CallCap,
    max_output_tokens: int,
) -> tuple[bool, list[str], int, int]:
    """Production's gate: deterministic rules, then the run's own auditor version."""

    workspace = case.workspace
    errors = [
        issue.code
        for issue in validate_material_draft(
            draft,
            topic=workspace.topic,
            brand_context=workspace.brand_context,
            rule_version=workspace.rule_version,
        )
        if issue.severity == "error"
    ]
    if errors:
        return False, errors, 0, 0
    cap.take()
    audit = await auditor.audit(
        DraftAuditRequest(
            run_id=case.run_id,
            draft_version_id=case.run_id,
            topic=workspace.topic,
            brand_context=workspace.brand_context,
            draft=draft,
            version_bundle=case.version_bundle,
            max_output_tokens=max_output_tokens,
        )
    )
    verdict = apply_copy_audit_policy(audit.verdict, rule_version=workspace.rule_version)
    left = [issue.code for issue in verdict.issues if issue.severity == "error"]
    return verdict.accepted, left, audit.prompt_tokens, audit.completion_tokens


def _hook(workspace: RepairWorkspace, draft: MaterialDraft) -> str:
    return extract_headline_hook(draft.copywriting, title=workspace.topic.title or "")


def _has_brand(draft: MaterialDraft) -> bool:
    return any(claim.kind == "brand_statement" for claim in draft.claims)


async def agent_arm(
    case: BlockedCase,
    *,
    model: RepairChatModel,
    auditor: Auditor,
    cap: CallCap,
    max_rounds: int,
    audit_max_output_tokens: int,
) -> dict[str, object]:
    workspace = case.workspace
    before = workspace.draft
    agent_cap_before = cap.used
    outcome = await CopyRepairAgent(_CappedChat(model, cap), max_rounds=max_rounds).repair(
        workspace, case.blocking_issues
    )
    agent_calls = cap.used - agent_cap_before
    ok, left, audit_in, audit_out = await gate(
        outcome.draft, case, auditor, cap=cap, max_output_tokens=audit_max_output_tokens
    )
    return {
        "source": "shadow",
        "passed": ok,
        "left_codes": left,
        "stopped": outcome.stopped,
        "rounds": outcome.rounds,
        "tool_calls": outcome.tool_calls,
        "model_calls": agent_calls,
        "prompt_tokens": outcome.prompt_tokens,
        "completion_tokens": outcome.completion_tokens,
        "gate_audit_prompt_tokens": audit_in,
        "gate_audit_completion_tokens": audit_out,
        "edits": list(outcome.edits),
        "trace": outcome.trace,
        "brand_statement_kept": _has_brand(outcome.draft),
        "hook_before": _hook(workspace, before),
        "hook_after": _hook(workspace, outcome.draft),
    }


async def regeneration_arm(
    case: BlockedCase,
    *,
    generator: Generator,
    auditor: Auditor,
    cap: CallCap,
    max_output_tokens: int,
    audit_max_output_tokens: int,
) -> dict[str, object]:
    """Production's full regeneration (draft 2 with the issues and draft 1), not stored.

    Differences from production: recent brand sentences are not passed to the generator, and the
    repair issues are draft 1's errors only (production may add advisory warnings).
    """

    workspace = case.workspace
    cap.take()
    result = await generator.generate(
        DraftGenerationRequest(
            run_id=case.run_id,
            topic=workspace.topic,
            brand_context=workspace.brand_context,
            version_bundle=case.version_bundle,
            draft_version=2,
            max_output_tokens=max_output_tokens,
            repair_issues=case.blocking_issues,
            previous_draft=workspace.draft,
        )
    )
    evidence = workspace.topic.evidence[0]
    draft = result.draft.model_copy(
        update={
            "copywriting": render_headline_hook_copy(
                result.draft.copywriting,
                title=workspace.topic.title or "",
                source_name=evidence.source_name,
                source_url=evidence.source_url,
            )
        }
    )
    ok, left, audit_in, audit_out = await gate(
        draft, case, auditor, cap=cap, max_output_tokens=audit_max_output_tokens
    )
    return {
        "source": "shadow",
        "passed": ok,
        "left_codes": left,
        "model_calls": 1,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "gate_audit_prompt_tokens": audit_in,
        "gate_audit_completion_tokens": audit_out,
        "brand_statement_kept": _has_brand(draft),
        "hook_after": _hook(workspace, draft),
    }


async def shadow_case(
    case: BlockedCase,
    *,
    model: RepairChatModel,
    auditor: Auditor,
    cap: CallCap,
    max_rounds: int,
    audit_max_output_tokens: int,
    generator: Generator | None = None,
    max_output_tokens: int = 2_048,
) -> dict[str, object]:
    workspace = case.workspace
    production = case.production
    from_production: dict[str, object] = {"source": "production", "passed": production.passed}
    agent: dict[str, object]
    regeneration: dict[str, object]
    if production.method == "agent":
        if generator is None:
            raise RuntimeError("a generator is needed to replay the regeneration")
        agent = from_production
        regeneration = await regeneration_arm(
            case,
            generator=generator,
            auditor=auditor,
            cap=cap,
            max_output_tokens=max_output_tokens,
            audit_max_output_tokens=audit_max_output_tokens,
        )
    elif production.agent_fallback is not None:
        # Production already tried the agent and dropped its draft, then regenerated.
        agent = {"source": "production", "passed": False, "fallback": production.agent_fallback}
        regeneration = from_production
    else:
        agent = await agent_arm(
            case,
            model=model,
            auditor=auditor,
            cap=cap,
            max_rounds=max_rounds,
            audit_max_output_tokens=audit_max_output_tokens,
        )
        regeneration = from_production
    return {
        "schema": SHADOW_SCHEMA,
        "run_id": str(case.run_id),
        "business_date": case.business_date.isoformat(),
        "content_slot": case.content_slot,
        "ordinal": case.ordinal,
        "rule_version": workspace.rule_version,
        "auditor_prompt_version": case.version_bundle.auditor_prompt_version,
        "agent_version": REPAIR_AGENT_VERSION,
        "toolset_version": REPAIR_TOOLSET_VERSION,
        "blocking_codes": [issue.code for issue in case.blocking_issues],
        "agent": agent,
        "regeneration": regeneration,
        "production": {
            "method": production.method,
            "regenerated": production.regenerated,
            "passed": production.passed,
            "run_status": production.run_status,
            "agent_fallback": production.agent_fallback,
        },
        "recorded_at": datetime.now(UTC).isoformat(),
    }


def read_records(output_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(output_dir.glob("copy-repair-shadow-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def _arms(record: Mapping[str, Any]) -> tuple[bool, bool]:
    """(agent passed, regeneration passed); v1 records compared the agent with production."""

    agent = bool(record["agent"]["passed"])
    regeneration = record.get("regeneration") or {"passed": record["production"]["passed"]}
    return agent, bool(regeneration["passed"])


def _shadow_average(records: Sequence[Mapping[str, Any]], arm: str, key: str) -> str:
    values = [
        r[arm][key]
        for r in records
        if isinstance(r.get(arm), dict)
        and r[arm].get("source", "shadow") == "shadow"
        and key in r[arm]
    ]
    return f"{sum(values) / len(values):,.0f}（{len(values)} 份）" if values else "-"


def summarize(records: Sequence[Mapping[str, Any]]) -> str:
    total = len(records)
    if not total:
        return "# 修复影子对照\n\n还没有记录。\n"
    arms = [_arms(r) for r in records]
    agent = sum(a for a, _ in arms)
    regeneration = sum(g for _, g in arms)
    both = sum(1 for a, g in arms if a and g)
    by_agent = sum(1 for r in records if r["production"].get("method") == "agent")
    dates = sorted({r["business_date"] for r in records})
    agent_tokens = _shadow_average(records, "agent", "prompt_tokens")
    regen_tokens = _shadow_average(records, "regeneration", "prompt_tokens")
    return "\n".join(
        [
            "# 修复影子对照（Agent 修 vs 整篇重写）",
            "",
            f"- 业务日期 {dates[0]} 至 {dates[-1]}，被拦下并用掉修复机会的草稿 {total} 份；"
            f"线上用 Agent 修的 {by_agent} 份，后台补跑整篇重写；其余后台补跑 Agent。",
            "- 两种做法都过同样的规则和该任务当时的审查版本。审查是模型判断，不是人工标注。",
            "",
            "| | 份数 |",
            "|---|---|",
            f"| Agent 修好 | {agent}（{agent / total:.0%}） |",
            f"| 整篇重写修好 | {regeneration}（{regeneration / total:.0%}） |",
            f"| 两者都修好 | {both} |",
            f"| 只有 Agent 修好 | {agent - both} |",
            f"| 只有重写修好 | {regeneration - both} |",
            f"| 都没修好 | {total - agent - regeneration + both} |",
            "",
            f"- 后台补跑的 Agent 平均输入 token：{agent_tokens}；"
            f"后台补跑的整篇重写：{regen_tokens}。",
            "",
        ]
    )


def _default_dates(now: datetime) -> tuple[date, date]:
    today = now.astimezone(BUSINESS_TIMEZONE).date()
    return today - timedelta(days=1), today


def _append_line(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


async def run(args: argparse.Namespace, *, output_dir: Path, done: set[str]) -> int:
    import httpx
    from pydantic import SecretStr
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.config import get_settings
    from app.infrastructure.ai.copy_generation import create_zhipu_copy_models
    from app.infrastructure.ai.copy_repair import ZhipuRepairChatModel
    from app.infrastructure.db.copy_repair_workspace import (
        list_regenerated_runs,
        load_blocked_case,
    )
    from app.infrastructure.db.ops_reader import (
        create_ops_engine,
        ops_database_url,
        verify_read_only_role,
    )

    engine = create_ops_engine(ops_database_url(os.environ))
    client = httpx.AsyncClient(follow_redirects=False)
    cap = CallCap(limit=args.max_calls)
    written = 0
    try:
        role = await verify_read_only_role(engine)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        default_from, default_to = _default_dates(datetime.now(UTC))
        date_from = args.date_from or default_from
        date_to = args.date_to or default_to
        run_ids = [
            run_id
            for run_id in await list_regenerated_runs(
                session_factory, date_from=date_from, date_to=date_to, limit=200
            )
            if str(run_id) not in done
        ][: args.max_runs]
        _log(
            event="copy_repair_shadow_start",
            role=role,
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            pending=len(run_ids),
            cap=args.max_calls,
        )
        if args.dry_run or not run_ids:
            return 0
        settings = get_settings()
        if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
            raise RuntimeError("the copy provider settings are missing")
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
        model = ZhipuRepairChatModel(generator._client)
        for run_id in run_ids:
            try:
                case = await load_blocked_case(session_factory, run_id)
                if case is None:
                    continue
                record = await shadow_case(
                    case,
                    model=model,
                    auditor=auditor,
                    cap=cap,
                    max_rounds=args.max_rounds,
                    audit_max_output_tokens=settings.copy_audit_max_output_tokens,
                    generator=generator,
                    max_output_tokens=settings.copy_max_output_tokens,
                )
            except CallCapReachedError:
                _log(event="copy_repair_shadow_cap_reached", used=cap.used)
                break
            except UnsupportedRuleVersionError as error:
                # Not a repair failure: the tools do not apply to this copy template.
                _log(
                    event="copy_repair_shadow_not_applicable",
                    run_id=str(run_id),
                    rule_version=error.rule_version,
                )
                continue
            except Exception as error:  # one bad run must not stop the others
                _log(event="copy_repair_shadow_case_failed", error=type(error).__name__)
                continue
            path = output_dir / f"copy-repair-shadow-{record['business_date']}.jsonl"
            await asyncio.to_thread(_append_line, path, json.dumps(record, ensure_ascii=False))
            written += 1
    finally:
        await client.aclose()
        await engine.dispose()
        _log(event="copy_repair_shadow_done", written=written, model_calls=cap.used)
    return 0


def _log(**fields: object) -> None:
    sys.stderr.write(json.dumps(fields, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat, default=None)
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat, default=None)
    parser.add_argument("--max-runs", type=int, default=12)
    parser.add_argument("--max-calls", type=int, default=120)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dry-run", action="store_true", help="list pending runs only")
    parser.add_argument("--summarize", action="store_true", help="print the summary only")
    args = parser.parse_args(argv)
    if not 1 <= args.max_calls <= 400 or not 1 <= args.max_runs <= 50:
        parser.error("caps are out of range")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.summarize:
        print(summarize(read_records(output_dir)))
        return 0
    done = {str(record["run_id"]) for record in read_records(output_dir)}
    status = asyncio.run(run(args, output_dir=output_dir, done=done))
    (output_dir / "summary.md").write_text(summarize(read_records(output_dir)), encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
