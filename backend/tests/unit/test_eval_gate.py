from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from evals.gate import runner as gate
from evals.gate.runner import (
    Suite,
    compare_with_baseline,
    load_known_failures,
    parse_failed_tests,
    render_markdown,
    run_gate,
    run_suite,
    run_tests,
    verdict_line,
)


def _completed(code: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=stderr)


def test_failed_tests_are_parsed_and_normalised() -> None:
    output = "\n".join(
        (
            "....F",
            "FAILED tests/unit/test_a.py::test_one - AssertionError: boom",
            "FAILED backend/tests/unit/test_b.py::test_two[case-1]",
            "ERROR tests/contract/test_c.py - ImportError",
            "1 failed, 4 passed",
        )
    )
    assert parse_failed_tests(output) == frozenset(
        {
            "backend/tests/unit/test_a.py::test_one",
            "backend/tests/unit/test_b.py::test_two[case-1]",
            "backend/tests/contract/test_c.py",
        }
    )


def test_baseline_comparison_separates_new_fixed_and_known() -> None:
    comparison = compare_with_baseline(
        frozenset({"backend/tests/unit/a.py::old", "backend/tests/unit/a.py::new"}),
        frozenset({"backend/tests/unit/a.py::old", "backend/tests/unit/a.py::gone"}),
    )
    assert comparison.new_failures == ("backend/tests/unit/a.py::new",)
    assert comparison.fixed == ("backend/tests/unit/a.py::gone",)
    assert comparison.still_failing == ("backend/tests/unit/a.py::old",)


def test_known_failures_file_ignores_comments_and_is_repository_relative(tmp_path: Path) -> None:
    path = tmp_path / "known.txt"
    path.write_text("# why\n\nbackend/tests/unit/a.py::old\n", encoding="utf-8")
    assert load_known_failures(path) == frozenset({"backend/tests/unit/a.py::old"})
    assert load_known_failures(tmp_path / "missing.txt") == frozenset()
    # The committed baseline may be empty once every old failure is fixed (2026-10-01); any entry
    # it still lists must be a repository-relative node id.
    committed = load_known_failures()
    assert all(node.startswith("backend/tests/") for node in committed)


def test_suite_is_skipped_only_for_its_documented_reason() -> None:
    suite = Suite(
        "needs_assets",
        (("evals.x", "--check"),),
        skip_marker="manifest is unavailable",
        skip_reason="needs the private manifest",
    )

    def missing(_c: Sequence[str], _cwd: Path, _t: int) -> subprocess.CompletedProcess[str]:
        return _completed(1, stderr="VisualAssetError: visual asset manifest is unavailable")

    def broken(_c: Sequence[str], _cwd: Path, _t: int) -> subprocess.CompletedProcess[str]:
        return _completed(1, stdout="canonical report drifted")

    def timeout(
        command: Sequence[str], _cwd: Path, seconds: int
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=list(command), timeout=seconds)

    skipped = run_suite(suite, run=missing)
    assert (skipped.status, skipped.detail) == ("skipped", "needs the private manifest")
    failed = run_suite(suite, run=broken)
    assert failed.status == "failed"
    assert "drifted" in failed.detail
    assert run_suite(suite, run=timeout).status == "failed"
    assert run_suite(suite, run=lambda *_: _completed(0)).status == "passed"


def test_second_command_of_a_suite_still_fails_it() -> None:
    suite = Suite("two", (("evals.a", "one"), ("evals.a", "two")))
    calls: list[Sequence[str]] = []

    def run(command: Sequence[str], _cwd: Path, _t: int) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return _completed(0 if len(calls) == 1 else 1, stdout="second failed")

    assert run_suite(suite, run=run).status == "failed"
    assert len(calls) == 2


def test_new_test_failure_fails_the_gate_and_known_failure_does_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline = tmp_path / "known.txt"
    baseline.write_text("backend/tests/unit/a.py::old\n", encoding="utf-8")
    monkeypatch.setattr(gate, "KNOWN_FAILURES_PATH", baseline)
    monkeypatch.setattr(
        gate, "load_known_failures", lambda path=baseline: load_known_failures(path)
    )

    def only_known(_c: Sequence[str], _cwd: Path, _t: int) -> subprocess.CompletedProcess[str]:
        return _completed(1, stdout="FAILED tests/unit/a.py::old - x\n1 failed")

    def regression(_c: Sequence[str], _cwd: Path, _t: int) -> subprocess.CompletedProcess[str]:
        return _completed(
            1, stdout="FAILED tests/unit/a.py::old - x\nFAILED tests/unit/b.py::new - y\n2 failed"
        )

    def crashed(_c: Sequence[str], _cwd: Path, _t: int) -> subprocess.CompletedProcess[str]:
        return _completed(4, stderr="ERROR: usage: pytest")

    step, comparison = run_tests(run=only_known)
    assert step.status == "passed"
    assert comparison is not None and comparison.new_failures == ()
    step, comparison = run_tests(run=regression)
    assert step.status == "failed"
    assert comparison is not None
    assert comparison.new_failures == ("backend/tests/unit/b.py::new",)
    step, comparison = run_tests(run=crashed)
    assert (step.status, comparison) == ("failed", None)


def test_report_verdict_counts_and_lists_regressions() -> None:
    def run(command: Sequence[str], _cwd: Path, _t: int) -> subprocess.CompletedProcess[str]:
        if command[0] == "git":
            return _completed(0, stdout="abc1234\n" if "rev-parse" in command else "")
        if "evals.topic_rerank.runner" in command:
            return _completed(1, stdout="topic rerank eval failed cases: ['priority-barrier']")
        if "evals.ip_asset_retrieval_grounded.authoring" in command:
            return _completed(1, stderr="visual asset manifest is unavailable")
        return _completed(0)

    report = run_gate(with_tests=False, run=run)
    assert not report.passed
    line = verdict_line(report)
    assert line.startswith("predeploy gate FAIL @ abc1234: 8 passed, 1 failed, 1 skipped")
    rendered = render_markdown(report)
    assert "| `topic_rerank` | failed |" in rendered
    assert "priority-barrier" in rendered
    assert "| `ip_asset_grounded_authoring` | skipped |" in rendered
    assert rendered.rstrip().endswith(line)
