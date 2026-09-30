"""Pre-deploy gate: every provider-free evaluation plus the unit and contract tests.

One command answers "is this commit safe to build a production image from?". It needs no database,
model or network. A suite that cannot run here for a documented reason (a private asset manifest)
is reported as skipped, never as passed. Tests are compared with a reviewed known-failure baseline
so that old breakage cannot hide a new regression.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
KNOWN_FAILURES_PATH = BACKEND_ROOT / "tests" / "known-failures.txt"
REPORT_VERSION = "predeploy-gate-v1"
TEST_PATHS = ("backend/tests/unit", "backend/tests/contract")
_SUITE_TIMEOUT_SECONDS = 600
_TEST_TIMEOUT_SECONDS = 3_000
_FAILED_TEST = re.compile(r"^(?:FAILED|ERROR) (\S+)")

Status = Literal["passed", "failed", "skipped"]


@dataclass(frozen=True, slots=True)
class Suite:
    """One provider-free check: a module run with arguments in the backend directory."""

    name: str
    commands: tuple[tuple[str, ...], ...]
    # Output that means "cannot run on this machine", with the reason shown in the report.
    skip_marker: str | None = None
    skip_reason: str | None = None


SUITES: tuple[Suite, ...] = (
    Suite("topic_golden", (("evals.topic_golden.runner", "--check"),)),
    Suite("same_topic_golden", (("evals.same_topic_golden.runner", "--check"),)),
    Suite("topic_rerank", (("evals.topic_rerank.runner", "--check"),)),
    Suite("brand_retrieval", (("evals.brand_retrieval.runner", "--check"),)),
    Suite("agent_workbench", (("evals.agent_workbench.runner", "--check"),)),
    Suite("image_quality", (("evals.image_quality.runner", "--check"),)),
    Suite("ip_asset_retrieval", (("evals.ip_asset_retrieval.runner", "--check"),)),
    Suite("visual_retrieval", (("evals.visual_retrieval.runner", "--check"),)),
    Suite(
        "ip_asset_grounded_seed",
        (
            ("evals.ip_asset_retrieval_grounded.runner", "validate-seed"),
            ("evals.ip_asset_retrieval_grounded.runner", "check-canonical"),
        ),
    ),
    Suite(
        "ip_asset_grounded_authoring",
        (("evals.ip_asset_retrieval_grounded.authoring", "--check"),),
        skip_marker="visual asset manifest is unavailable",
        skip_reason="needs the private visual asset manifest",
    ),
)


@dataclass(frozen=True, slots=True)
class StepResult:
    name: str
    status: Status
    seconds: float
    detail: str = ""


@dataclass(frozen=True, slots=True)
class TestComparison:
    """Current failures against the reviewed baseline."""

    new_failures: tuple[str, ...]
    fixed: tuple[str, ...]
    still_failing: tuple[str, ...]


@dataclass(slots=True)
class GateReport:
    commit: str
    started_at: str
    steps: list[StepResult] = field(default_factory=list)
    tests: TestComparison | None = None

    @property
    def passed(self) -> bool:
        return all(step.status != "failed" for step in self.steps)


Runner = Callable[[Sequence[str], Path, int], "subprocess.CompletedProcess[str]"]


def _run(command: Sequence[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
    return subprocess.run(
        list(command),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _tail(text: str, lines: int = 3) -> str:
    kept = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return " | ".join(kept[-lines:])[:400]


def run_suite(suite: Suite, *, run: Runner = _run) -> StepResult:
    started = time.monotonic()
    for module, *arguments in suite.commands:
        try:
            completed = run(
                (sys.executable, "-m", module, *arguments), BACKEND_ROOT, _SUITE_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired:
            return StepResult(suite.name, "failed", time.monotonic() - started, "timed out")
        if completed.returncode != 0:
            output = f"{completed.stdout}\n{completed.stderr}"
            if suite.skip_marker is not None and suite.skip_marker in output:
                return StepResult(
                    suite.name,
                    "skipped",
                    time.monotonic() - started,
                    suite.skip_reason or suite.skip_marker,
                )
            return StepResult(suite.name, "failed", time.monotonic() - started, _tail(output))
    return StepResult(suite.name, "passed", time.monotonic() - started)


def load_known_failures(path: Path = KNOWN_FAILURES_PATH) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    return frozenset(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def parse_failed_tests(output: str) -> frozenset[str]:
    """Node ids from pytest's short summary, normalised to repository-relative paths."""

    failed = set()
    for line in output.splitlines():
        match = _FAILED_TEST.match(line.strip())
        if match is None:
            continue
        node = match.group(1)
        failed.add(node if node.startswith("backend/") else f"backend/{node}")
    return frozenset(failed)


def compare_with_baseline(current: frozenset[str], baseline: frozenset[str]) -> TestComparison:
    return TestComparison(
        new_failures=tuple(sorted(current - baseline)),
        fixed=tuple(sorted(baseline - current)),
        still_failing=tuple(sorted(current & baseline)),
    )


def run_tests(*, run: Runner = _run) -> tuple[StepResult, TestComparison | None]:
    started = time.monotonic()
    command = (
        sys.executable,
        "-m",
        "pytest",
        *TEST_PATHS,
        "-q",
        "--no-cov",
        "-p",
        "no:cacheprovider",
    )
    try:
        completed = run(command, REPO_ROOT, _TEST_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return StepResult(
            "unit_and_contract_tests", "failed", time.monotonic() - started, "timed out"
        ), None
    output = f"{completed.stdout}\n{completed.stderr}"
    # 0 = all passed, 1 = some tests failed; anything else means pytest itself did not run.
    if completed.returncode not in {0, 1}:
        return (
            StepResult(
                "unit_and_contract_tests", "failed", time.monotonic() - started, _tail(output)
            ),
            None,
        )
    comparison = compare_with_baseline(parse_failed_tests(output), load_known_failures())
    if comparison.new_failures:
        detail = f"{len(comparison.new_failures)} new failure(s): " + ", ".join(
            comparison.new_failures[:5]
        )
        status: Status = "failed"
    else:
        detail = f"{len(comparison.still_failing)} known failure(s), no new failure"
        if comparison.fixed:
            detail += f"; {len(comparison.fixed)} baseline entr(ies) now pass, update the baseline"
        status = "passed"
    return (
        StepResult("unit_and_contract_tests", status, time.monotonic() - started, detail[:400]),
        comparison,
    )


def current_commit(*, run: Runner = _run) -> str:
    try:
        head = run(("git", "rev-parse", "--short", "HEAD"), REPO_ROOT, 30).stdout.strip()
        dirty = run(("git", "status", "--porcelain"), REPO_ROOT, 30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return f"{head}{'+dirty' if dirty else ''}" if head else "unknown"


def run_gate(*, with_tests: bool = True, run: Runner = _run) -> GateReport:
    report = GateReport(
        commit=current_commit(run=run),
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    for suite in SUITES:
        report.steps.append(run_suite(suite, run=run))
    if with_tests:
        step, comparison = run_tests(run=run)
        report.steps.append(step)
        report.tests = comparison
    return report


def verdict_line(report: GateReport) -> str:
    """One line for the rollout note."""

    counts = {status: 0 for status in ("passed", "failed", "skipped")}
    for step in report.steps:
        counts[step.status] += 1
    verdict = "PASS" if report.passed else "FAIL"
    return (
        f"predeploy gate {verdict} @ {report.commit}: {counts['passed']} passed, "
        f"{counts['failed']} failed, {counts['skipped']} skipped ({report.started_at})"
    )


def render_markdown(report: GateReport) -> str:
    lines = [
        f"# Pre-deploy gate: {'PASS' if report.passed else 'FAIL'}",
        "",
        f"- Commit: `{report.commit}`",
        f"- Started: {report.started_at}",
        "",
        "| Step | Result | Seconds | Detail |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| `{step.name}` | {step.status} | {step.seconds:.1f} | {step.detail or '-'} |"
        for step in report.steps
    ]
    if report.tests is not None and report.tests.new_failures:
        lines += ["", "## New test failures", ""]
        lines += [f"- `{node}`" for node in report.tests.new_failures]
    if report.tests is not None and report.tests.fixed:
        lines += ["", "## Baseline entries that now pass (remove them)", ""]
        lines += [f"- `{node}`" for node in report.tests.fixed]
    lines += ["", verdict_line(report), ""]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-tests", action="store_true", help="evaluation suites only (about a minute)"
    )
    parser.add_argument("--output", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)
    report = run_gate(with_tests=not args.skip_tests)
    if args.output == "json":
        payload = {
            "report_version": REPORT_VERSION,
            "passed": report.passed,
            "verdict": verdict_line(report),
            **asdict(report),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
