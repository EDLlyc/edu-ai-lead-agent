"""Run the provider-free image-quality schema and decision-policy evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .dataset import (
    DEFAULT_CASES_PATH,
    DEFAULT_OBSERVATIONS_PATH,
    DEFAULT_RUBRIC_PATH,
    ImageEvalDatasetError,
    load_image_eval_dataset,
)
from .metrics import ImageQualityEvalReport, build_report
from .reporting import canonical_json, render_markdown

FEATURE_ROOT = Path(__file__).resolve().parent
CANONICAL_JSON_PATH = FEATURE_ROOT / "canonical-report.json"
CANONICAL_MARKDOWN_PATH = FEATURE_ROOT / "canonical-report.md"


def evaluate_paths(
    *,
    cases_path: Path = DEFAULT_CASES_PATH,
    observations_path: Path = DEFAULT_OBSERVATIONS_PATH,
    rubric_path: Path = DEFAULT_RUBRIC_PATH,
) -> ImageQualityEvalReport:
    dataset = load_image_eval_dataset(
        cases_path=cases_path,
        observations_path=observations_path,
        rubric_path=rubric_path,
    )
    return build_report(
        cases=dataset.cases,
        observations=dataset.observations,
        rubric=dataset.rubric,
        dataset_sha256=dataset.dataset_sha256,
        rubric_sha256=dataset.rubric_sha256,
    )


def canonical_drift_diagnostics(
    *,
    expected_json: str,
    actual_json: str,
    expected_markdown: str,
    actual_markdown: str,
) -> tuple[str, ...]:
    """Return bounded expected/actual diagnostics instead of a bare drift message."""

    diagnostics: list[str] = []
    try:
        expected: Any = json.loads(expected_json)
    except json.JSONDecodeError:
        diagnostics.append("canonical_json_invalid:expected=valid_json:actual=checked_artifact")
    try:
        actual: Any = json.loads(actual_json)
    except json.JSONDecodeError:
        diagnostics.append("canonical_json_invalid:expected=valid_json:actual=rendered_report")
    if not diagnostics:
        diagnostics.extend(_json_differences(expected, actual, path="$", limit=12))
    if expected_markdown != actual_markdown:
        diagnostics.append(
            "canonical_markdown_mismatch:expected=checked_artifact:actual=rendered_report"
        )
    return tuple(diagnostics)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write-canonical", action="store_true")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS_PATH)
    parser.add_argument("--rubric", type=Path, default=DEFAULT_RUBRIC_PATH)
    args = parser.parse_args(argv)
    try:
        report = evaluate_paths(
            cases_path=args.cases,
            observations_path=args.observations,
            rubric_path=args.rubric,
        )
    except (ImageEvalDatasetError, RuntimeError, ValueError) as exc:
        print(f"image quality eval failed: {exc}", file=sys.stderr)
        return 1

    aggregate = report.aggregate
    if aggregate.failed_case_ids or aggregate.passed_count != aggregate.case_count:
        print("image quality eval policy gates failed", file=sys.stderr)
        for case in report.cases:
            if not case.passed:
                print(f"- {case.case_id}: {';'.join(case.failure_codes)}", file=sys.stderr)
        return 1

    rendered_json = canonical_json(report)
    rendered_markdown = render_markdown(report)
    if args.write_canonical:
        CANONICAL_JSON_PATH.write_text(rendered_json, encoding="utf-8")
        CANONICAL_MARKDOWN_PATH.write_text(rendered_markdown, encoding="utf-8")
    elif args.check:
        try:
            expected_json = CANONICAL_JSON_PATH.read_text(encoding="utf-8")
            expected_markdown = CANONICAL_MARKDOWN_PATH.read_text(encoding="utf-8")
        except OSError:
            print("image quality eval canonical artifacts are missing", file=sys.stderr)
            return 1
        diagnostics = canonical_drift_diagnostics(
            expected_json=expected_json,
            actual_json=rendered_json,
            expected_markdown=expected_markdown,
            actual_markdown=rendered_markdown,
        )
        if diagnostics:
            print("image quality eval canonical report drifted", file=sys.stderr)
            for diagnostic in diagnostics:
                print(f"- {diagnostic}", file=sys.stderr)
            return 1
    print(
        "image quality eval passed: "
        f"{aggregate.passed_count}/{aggregate.case_count}; "
        f"critical P/R/F1={aggregate.critical_precision:.6f}/"
        f"{aggregate.critical_recall:.6f}/{aggregate.critical_f1:.6f}; "
        f"false-pass={aggregate.false_pass_rate:.6f}; "
        f"manual-review={aggregate.manual_review_rate:.6f}"
    )
    return 0


def _json_differences(
    expected: object,
    actual: object,
    *,
    path: str,
    limit: int,
) -> list[str]:
    if limit <= 0:
        return []
    if type(expected) is not type(actual):
        return [
            f"{path}:expected_type={type(expected).__name__}:actual_type={type(actual).__name__}"
        ]
    if isinstance(expected, dict) and isinstance(actual, dict):
        differences: list[str] = []
        expected_mapping: Mapping[str, object] = expected
        actual_mapping: Mapping[str, object] = actual
        for key in sorted(set(expected_mapping).union(actual_mapping)):
            child_path = f"{path}.{key}"
            if key not in expected_mapping:
                differences.append(f"{child_path}:expected=missing:actual=present")
            elif key not in actual_mapping:
                differences.append(f"{child_path}:expected=present:actual=missing")
            else:
                differences.extend(
                    _json_differences(
                        expected_mapping[key],
                        actual_mapping[key],
                        path=child_path,
                        limit=limit - len(differences),
                    )
                )
            if len(differences) >= limit:
                break
        return differences
    if isinstance(expected, list) and isinstance(actual, list):
        differences = []
        for index in range(max(len(expected), len(actual))):
            child_path = f"{path}[{index}]"
            if index >= len(expected):
                differences.append(f"{child_path}:expected=missing:actual=present")
            elif index >= len(actual):
                differences.append(f"{child_path}:expected=present:actual=missing")
            else:
                differences.extend(
                    _json_differences(
                        expected[index],
                        actual[index],
                        path=child_path,
                        limit=limit - len(differences),
                    )
                )
            if len(differences) >= limit:
                break
        return differences
    if expected != actual:
        return [f"{path}:expected={expected!r}:actual={actual!r}"]
    return []


if __name__ == "__main__":
    raise SystemExit(main())
