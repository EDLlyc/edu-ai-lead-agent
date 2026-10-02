"""Trajectory evaluation of the ops assistant on synthetic operations data.

    # paid run (zhipu, key from the usual settings), two models, report in reports/
    python -m evals.ops_assistant.runner --models glm-5.2,glm-4.5-air \
        --output-dir evals/ops_assistant/results/<date> \
        --report evals/ops_assistant/reports/<date>-trajectory.md

Each scenario runs the real assistant graph (LangGraph, interrupts, tool registry) against the
fixture reader and sandbox draft. Edits are approved or denied as the scenario says. Every agent
step is traced with OpenTelemetry GenAI names; the trace gives the model rounds per scenario and
is written next to the raw results. Raw results (results/, gitignored) stay local; the report has
aggregate numbers only.
"""

# ruff: noqa: RUF001, E501

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.application.services.agent_tracing import JsonlTraceRecorder
from app.application.services.copy_repair_agent import ChatTurn, RepairChatModel
from app.application.services.ops_assistant import OPS_ASSISTANT_VERSION, OpsAssistant

from evals.ops_assistant.fixtures import TODAY, FixtureOpsReader, load_fixture_workspace
from evals.ops_assistant.scenarios import SCENARIOS, Scenario
from evals.ops_assistant.scorers import Score, Trajectory, aggregate, score

MAX_APPROVALS_PER_SCENARIO = 4
DEFAULT_CALL_CAP = 400


class CallCapReachedError(RuntimeError):
    pass


class CappedModel:
    """Counts model calls across a whole evaluation and stops at the cap."""

    def __init__(self, model: RepairChatModel, counter: list[int], cap: int) -> None:
        self._model = model
        self._counter = counter
        self._cap = cap

    async def complete(self, messages: Any, tools: Any) -> ChatTurn:
        if self._counter[0] >= self._cap:
            raise CallCapReachedError(f"model call cap {self._cap} reached")
        self._counter[0] += 1
        return await self._model.complete(messages, tools)


async def run_scenario(
    scenario: Scenario, model: RepairChatModel, model_name: str
) -> tuple[Trajectory, list[dict[str, Any]]]:
    tracer = JsonlTraceRecorder()
    assistant = OpsAssistant(
        model,
        FixtureOpsReader(),
        load_fixture_workspace,
        today=TODAY,
        tracer=tracer,
        model_name=model_name,
        provider_name="zhipu",
    )
    trajectory = Trajectory(scenario_id=scenario.id, model=model_name, answer="")
    started = time.monotonic()
    try:
        for question in scenario.questions:
            reply = await assistant.send(question)
            trajectory.steps += [asdict(step) for step in reply.steps]
            trajectory.prompt_tokens += reply.prompt_tokens
            trajectory.completion_tokens += reply.completion_tokens
            while reply.kind == "approval" and reply.approval is not None:
                if len(trajectory.approvals) >= MAX_APPROVALS_PER_SCENARIO:
                    break
                trajectory.approvals.append(asdict(reply.approval))
                decision = scenario.approval == "approve"
                trajectory.decisions.append(decision)
                reply = await assistant.decide(decision)
                trajectory.steps += [asdict(step) for step in reply.steps]
                trajectory.prompt_tokens += reply.prompt_tokens
                trajectory.completion_tokens += reply.completion_tokens
            trajectory.final_kind = reply.kind
            trajectory.answer = reply.text or ""
            trajectory.draft = reply.draft or trajectory.draft
            if reply.kind == "approval":
                break
    except CallCapReachedError:
        raise
    except Exception as error:  # one failing scenario must not stop the run
        trajectory.error = type(error).__name__
    trajectory.seconds = round(time.monotonic() - started, 2)
    records = tracer.records()
    trajectory.rounds = sum(1 for record in records if record["name"].startswith("chat"))
    return trajectory, records


async def evaluate(
    models: dict[str, RepairChatModel],
    scenarios: Sequence[Scenario] = SCENARIOS,
    *,
    repeats: int = 1,
    on_result: Callable[[Trajectory, Score], None] | None = None,
) -> tuple[list[Trajectory], list[Score], list[dict[str, Any]]]:
    trajectories: list[Trajectory] = []
    scores: list[Score] = []
    traces: list[dict[str, Any]] = []
    for model_name, model in models.items():
        for _ in range(repeats):
            for scenario in scenarios:
                trajectory, records = await run_scenario(scenario, model, model_name)
                result = score(scenario, trajectory)
                trajectories.append(trajectory)
                scores.append(result)
                traces += [{"scenario": scenario.id, **record} for record in records]
                if on_result is not None:
                    on_result(trajectory, result)
    return trajectories, scores, traces


def render_report(
    scores: Sequence[Score], *, models: Sequence[str], repeats: int, calls: int, run_at: str
) -> str:
    by_model = {name: [item for item in scores if item.model == name] for name in models}
    lines = [
        "# 运维助手轨迹评测",
        "",
        f"- 运行时间：{run_at}；助手版本 `{OPS_ASSISTANT_VERSION}`（LangGraph 状态图，改稿用 interrupt 等待确认）。",
        f"- {len(SCENARIOS)} 个场景 × {len(models)} 个模型 × {repeats} 次；模型调用共 {calls} 次。",
        "- 数据是合成的运维数据（两天、三个时段，含少发、被拦、限流失败、慢环节、标题注入），不含线上内容。",
        "- 全部是确定性检查，没有模型裁判：工具召回/精确率、参数错误、禁止调用、答案要点、"
        "是否请求确认、沙盒草稿的最终内容、审批策略违规（未经确认执行修改、拒绝后仍生效、拒绝后重复提同样修改）。",
        "",
        "| 模型 | 成功 | 工具召回 | 工具精确率 | 参数错误 | 其他工具错误 | 禁止调用 | 审批违规 | 平均轮数 | 平均输入 token | 平均输出 token | 平均耗时 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name in models:
        agg = aggregate(by_model[name])
        if not agg["runs"]:
            continue
        lines.append(
            f"| {name} | {agg['success']}/{agg['runs']}（{agg['success_rate']:.0%}） | "
            f"{agg['recall']:.2f} | {agg['precision']:.2f} | {agg['invalid_argument_calls']} | "
            f"{agg['tool_errors'] - agg['invalid_argument_calls']} | {agg['forbidden_calls']} | "
            f"{agg['policy_violations']} | {agg['mean_rounds']:.1f} | "
            f"{agg['mean_prompt_tokens']:,.0f} | {agg['mean_completion_tokens']:,.0f} | "
            f"{agg['mean_seconds']:.1f}s |"
        )
    lines += ["", "## 按场景", "", "| 场景 | 类别 | " + " | ".join(models) + " |", "|---|---|"]
    lines[-1] += "---|" * len(models)
    for scenario in SCENARIOS:
        cells = []
        for name in models:
            runs = [item for item in by_model[name] if item.scenario_id == scenario.id]
            ok = sum(item.success for item in runs)
            reasons = sorted({failure for item in runs for failure in item.failures})
            cells.append(f"{ok}/{len(runs)}" + (f"（{'；'.join(reasons)}）" if reasons else ""))
        lines.append(f"| {scenario.id} | {scenario.category} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _zhipu_models(names: Sequence[str]) -> tuple[dict[str, RepairChatModel], Any]:
    import httpx
    from app.core.config import get_settings
    from app.infrastructure.ai.copy_generation import create_zhipu_copy_models
    from app.infrastructure.ai.copy_repair import ZhipuRepairChatModel
    from pydantic import SecretStr

    settings = get_settings()
    if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
        raise SystemExit("AI_PLATFORM_BASE_URL and AI_PLATFORM_API_KEY are required")
    client = httpx.AsyncClient(follow_redirects=False)
    models: dict[str, RepairChatModel] = {}
    for name in names:
        generator, _ = create_zhipu_copy_models(
            client=client,
            base_url=settings.ai_platform_base_url,
            api_key=SecretStr(settings.ai_platform_api_key.get_secret_value()),
            model=name,
            connect_timeout_seconds=settings.ai_connect_timeout_seconds,
            read_timeout_seconds=settings.ai_read_timeout_seconds,
            total_timeout_seconds=settings.ai_total_timeout_seconds,
            concurrency=settings.ai_provider_concurrency,
            max_attempts=settings.ai_max_attempts,
            max_input_characters=settings.ai_max_input_characters,
            max_output_tokens=settings.copy_max_output_tokens,
            max_validation_corrections=settings.ai_max_validation_corrections,
        )
        models[name] = ZhipuRepairChatModel(generator._client, max_output_tokens=1_500)
    return models, client


async def _main(args: argparse.Namespace) -> int:
    names = [name.strip() for name in args.models.split(",") if name.strip()]
    if not 1 <= len(names) <= 2:
        raise SystemExit("compare one or two models")
    raw, client = _zhipu_models(names)
    counter = [0]
    models: dict[str, RepairChatModel] = {
        name: CappedModel(model, counter, args.max_calls) for name, model in raw.items()
    }
    run_at = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    def progress(trajectory: Trajectory, result: Score) -> None:
        mark = "ok" if result.success else ",".join(result.failures)
        print(f"{trajectory.model} {trajectory.scenario_id}: {mark}", file=sys.stderr)

    try:
        trajectories, scores, traces = await evaluate(
            models, repeats=args.repeats, on_result=progress
        )
    finally:
        await client.aclose()
    (args.output_dir / "results.json").write_text(
        json.dumps(
            {
                "run_at": run_at,
                "trajectories": [asdict(item) for item in trajectories],
                "scores": [asdict(item) for item in scores],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    with (args.output_dir / "traces.jsonl").open("w", encoding="utf-8") as handle:
        for record in traces:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    report = render_report(
        scores, models=names, repeats=args.repeats, calls=counter[0], run_at=run_at
    )
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    print(report)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", required=True, help="comma-separated, at most two")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-calls", type=int, default=DEFAULT_CALL_CAP)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)
    if not 1 <= args.repeats <= 3 or not 1 <= args.max_calls <= DEFAULT_CALL_CAP:
        raise SystemExit("repeats 1-3, max calls 1-400")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
