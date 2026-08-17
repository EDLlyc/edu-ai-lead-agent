"""Run the provider-free Agent Workbench baseline and verify checked reports."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.application.services.agent_tools import build_agent_tool_registry
from app.application.services.agent_workbench_graph import BoundedAgentRunner
from app.domain.agent_workbench import AgentRunResult
from app.infrastructure.agent_workbench_fixture import build_fixture_reader
from app.infrastructure.ai.agent_workbench import DeterministicPolicyToolCallingModel

from .dataset import DEFAULT_CASES_PATH, EvalDatasetError, load_eval_cases
from .metrics import (
    CanonicalEvalReport,
    RuntimeDiagnostics,
    build_canonical_report,
    build_runtime_diagnostics,
    score_case,
)
from .models import CASE_SCHEMA_VERSION, AgentEvalCase
from .reporting import canonical_json, render_markdown, runtime_json

FEATURE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = FEATURE_ROOT.parents[2]
CANONICAL_JSON_PATH = FEATURE_ROOT / "canonical-report.json"
CANONICAL_MARKDOWN_PATH = FEATURE_ROOT / "canonical-report.md"
DEFAULT_RUNTIME_PATH = REPOSITORY_ROOT / "output" / "agent-workbench" / "eval-runtime.json"


async def run_offline_evaluation(
    cases: Sequence[AgentEvalCase],
    *,
    dataset_bytes: bytes,
) -> tuple[CanonicalEvalReport, RuntimeDiagnostics]:
    """Run each case with a fresh fixture reader and the fixed non-oracle policy."""

    scores = []
    results: dict[str, AgentRunResult] = {}
    registry_hash: str | None = None
    read_only_tools: frozenset[str] | None = None
    for case in sorted(cases, key=lambda item: item.case_id):
        registry = build_agent_tool_registry(build_fixture_reader(case.fixture_scenario))
        if registry_hash is None:
            registry_hash = registry.schema_hash
            read_only_tools = frozenset(
                definition.name for definition in registry if definition.read_only
            )
        elif registry.schema_hash != registry_hash:
            raise RuntimeError("fixture scenarios produced different registry schemas")
        runner = BoundedAgentRunner(
            registry=registry,
            model=DeterministicPolicyToolCallingModel(),
        )
        result = await runner.run(
            case.query,
            run_id=uuid5(NAMESPACE_URL, f"edu-ai-agent-eval:{case.case_id}"),
        )
        results[case.case_id] = result
        scores.append(
            score_case(
                case,
                result,
                read_only_tools=read_only_tools or frozenset(),
            )
        )
    if registry_hash is None:
        raise RuntimeError("agent eval dataset did not contain any cases")
    dataset_hash = sha256(dataset_bytes).hexdigest()[:16]
    report = build_canonical_report(
        dataset_version=f"{CASE_SCHEMA_VERSION}:{dataset_hash}",
        registry_schema_hash=registry_hash,
        scores=scores,
    )
    return report, build_runtime_diagnostics(results)


async def evaluate_path(
    path: Path = DEFAULT_CASES_PATH,
) -> tuple[CanonicalEvalReport, RuntimeDiagnostics]:
    cases, dataset_bytes = await asyncio.to_thread(_load_cases_and_bytes, path)
    return await run_offline_evaluation(cases, dataset_bytes=dataset_bytes)


def _load_cases_and_bytes(path: Path) -> tuple[tuple[AgentEvalCase, ...], bytes]:
    cases = load_eval_cases(path)
    try:
        dataset_bytes = path.read_bytes()
    except OSError as exc:  # loader already checked; preserve a bounded race-safe failure
        raise EvalDatasetError("agent eval dataset could not be read for hashing") from exc
    return cases, dataset_bytes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="fail if generated canonical JSON or Markdown differs from the checked artifacts",
    )
    mode.add_argument(
        "--write-canonical",
        action="store_true",
        help="replace checked canonical artifacts after a fully passing intentional change",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--runtime-output", type=Path, default=DEFAULT_RUNTIME_PATH)
    args = parser.parse_args(argv)

    try:
        report, runtime = asyncio.run(evaluate_path(args.cases))
    except (EvalDatasetError, RuntimeError, ValueError) as exc:
        print(f"agent eval failed: {exc}", file=sys.stderr)
        return 1

    _write_runtime(args.runtime_output, runtime)
    if report.aggregate.failed_case_ids:
        joined = ",".join(report.aggregate.failed_case_ids)
        print(f"agent eval failed cases: {joined}", file=sys.stderr)
        return 1

    generated_json = canonical_json(report)
    generated_markdown = render_markdown(report)
    if args.write_canonical:
        CANONICAL_JSON_PATH.write_text(generated_json, encoding="utf-8")
        CANONICAL_MARKDOWN_PATH.write_text(generated_markdown, encoding="utf-8")
    elif args.check and not _artifacts_match(generated_json, generated_markdown):
        print(
            "agent eval canonical report drifted; review and run --write-canonical",
            file=sys.stderr,
        )
        return 1

    print(
        "agent eval passed: "
        f"{report.aggregate.passed_count}/{report.aggregate.case_count} cases; "
        f"registry={report.registry_schema_hash}"
    )
    return 0


def _write_runtime(path: Path, runtime: RuntimeDiagnostics) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(runtime_json(runtime), encoding="utf-8")


def _artifacts_match(generated_json: str, generated_markdown: str) -> bool:
    try:
        checked_json = CANONICAL_JSON_PATH.read_text(encoding="utf-8")
        checked_markdown = CANONICAL_MARKDOWN_PATH.read_text(encoding="utf-8")
    except OSError:
        return False
    return checked_json == generated_json and checked_markdown == generated_markdown


if __name__ == "__main__":
    raise SystemExit(main())
