"""Run and verify the provider-free official-account Reviewer contract evaluation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path

from .dataset import (
    DEFAULT_CASES_PATH,
    DEFAULT_ORACLE_PATH,
    DEFAULT_RUBRIC_PATH,
    ReviewEvalDatasetError,
    load_review_eval_dataset,
)
from .metrics import OfficialAccountReviewEvalReport, build_report
from .policy import run_fixture_policy
from .reporting import canonical_json, render_markdown

FEATURE_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = FEATURE_ROOT.parents[1]
CANONICAL_JSON_PATH = FEATURE_ROOT / "canonical-report.json"
CANONICAL_MARKDOWN_PATH = FEATURE_ROOT / "canonical-report.md"
POLICY_PATH = FEATURE_ROOT / "policy.py"
RUNNER_PATH = FEATURE_ROOT / "runner.py"
EVALUATOR_BUNDLE_PATHS = (
    BACKEND_ROOT / "app" / "domain" / "official_account_reviewer.py",
    FEATURE_ROOT / "dataset.py",
    FEATURE_ROOT / "metrics.py",
    FEATURE_ROOT / "models.py",
    POLICY_PATH,
    FEATURE_ROOT / "reporting.py",
    RUNNER_PATH,
)


def evaluate_paths(
    *,
    cases_path: Path = DEFAULT_CASES_PATH,
    oracle_path: Path = DEFAULT_ORACLE_PATH,
    rubric_path: Path = DEFAULT_RUBRIC_PATH,
) -> OfficialAccountReviewEvalReport:
    dataset = load_review_eval_dataset(
        cases_path=cases_path,
        oracle_path=oracle_path,
        rubric_path=rubric_path,
    )
    verdicts = {case.case_id: run_fixture_policy(case) for case in dataset.cases}
    return build_report(
        cases=dataset.cases,
        oracles=dataset.oracles,
        verdicts=verdicts,
        dataset_version=dataset.dataset_version,
        cases_sha256=dataset.cases_sha256,
        oracle_sha256=dataset.oracle_sha256,
        rubric_sha256=dataset.rubric_sha256,
        policy_sha256=_file_sha256(POLICY_PATH),
        runner_sha256=_bundle_sha256(EVALUATOR_BUNDLE_PATHS),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write-canonical", action="store_true")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--oracle", type=Path, default=DEFAULT_ORACLE_PATH)
    parser.add_argument("--rubric", type=Path, default=DEFAULT_RUBRIC_PATH)
    args = parser.parse_args(argv)
    try:
        report = evaluate_paths(
            cases_path=args.cases,
            oracle_path=args.oracle,
            rubric_path=args.rubric,
        )
    except (ReviewEvalDatasetError, OSError, RuntimeError, ValueError) as exc:
        print(f"official-account Reviewer eval failed: {exc}", file=sys.stderr)
        return 1
    if report.aggregate.failed_case_ids:
        joined = ",".join(report.aggregate.failed_case_ids)
        print(f"official-account Reviewer eval failed cases: {joined}", file=sys.stderr)
        return 1
    generated_json = canonical_json(report)
    generated_markdown = render_markdown(report)
    if args.write_canonical:
        CANONICAL_JSON_PATH.write_text(generated_json, encoding="utf-8")
        CANONICAL_MARKDOWN_PATH.write_text(generated_markdown, encoding="utf-8")
    elif args.check and not _artifacts_match(generated_json, generated_markdown):
        print(
            "official-account Reviewer canonical report drifted; review and regenerate",
            file=sys.stderr,
        )
        return 1
    print(
        "official-account Reviewer provider-free eval passed: "
        f"{report.aggregate.passed_count}/{report.aggregate.case_count}; "
        f"live_model_calls={report.live_model_calls}"
    )
    return 0


def _artifacts_match(generated_json: str, generated_markdown: str) -> bool:
    try:
        checked_json = CANONICAL_JSON_PATH.read_text(encoding="utf-8")
        checked_markdown = CANONICAL_MARKDOWN_PATH.read_text(encoding="utf-8")
    except OSError:
        return False
    return checked_json == generated_json and checked_markdown == generated_markdown


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _bundle_sha256(paths: Sequence[Path]) -> str:
    digest = sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(BACKEND_ROOT).as_posix()):
        relative_path = path.relative_to(BACKEND_ROOT).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative_path).to_bytes(4, "big"))
        digest.update(relative_path)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
