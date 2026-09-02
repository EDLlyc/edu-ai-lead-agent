from __future__ import annotations

import inspect
import json
from collections import Counter
from pathlib import Path

import pytest
from app.domain.official_account_reviewer import (
    ReviewDecision,
    ReviewIssueSource,
    build_review_request,
    build_review_verdict,
)
from evals.official_account_reviewer.dataset import (
    DEFAULT_CASES_PATH,
    DEFAULT_ORACLE_PATH,
    DEFAULT_RUBRIC_PATH,
    ReviewEvalDatasetError,
    load_review_eval_dataset,
)
from evals.official_account_reviewer.metrics import build_report
from evals.official_account_reviewer.policy import (
    FIXTURE_PROMPT_VERSION,
    FIXTURE_REVIEWER_VERSION,
    run_fixture_policy,
)
from evals.official_account_reviewer.reporting import canonical_json, render_markdown
from evals.official_account_reviewer.runner import evaluate_paths, main


def test_checked_dataset_has_48_balanced_cases_and_physical_oracle_isolation() -> None:
    dataset = load_review_eval_dataset()

    assert len(dataset.cases) == 48
    assert len(dataset.oracles) == 48
    assert set(Counter(case.focus_dimension for case in dataset.cases).values()) == {8}
    assert len({case.case_id for case in dataset.cases}) == 48
    case_text = DEFAULT_CASES_PATH.read_text(encoding="utf-8")
    assert "expected_decision" not in case_text
    assert "expected_issues" not in case_text
    assert "article_text" not in case_text
    assert list(inspect.signature(run_fixture_policy).parameters) == ["case"]


def test_canonical_report_is_honest_and_covers_required_metrics() -> None:
    report = evaluate_paths()

    assert report.provider_free is True
    assert report.live_model_calls == 0
    assert report.aggregate.case_count == 48
    assert report.aggregate.passed_count == 48
    assert report.aggregate.critical_precision == 1
    assert report.aggregate.critical_recall == 1
    assert report.aggregate.critical_f1 == 1
    assert report.aggregate.false_accept_count == 0
    assert report.aggregate.false_reject_count == 0
    assert report.aggregate.repairability_accuracy == 1
    assert report.aggregate.location_accuracy == 1
    assert report.aggregate.hard_gate_override_case_count == 3
    assert report.aggregate.hard_gate_override_violation_count == 0
    assert all(item.case_count == 8 for item in report.dimensions)
    assert "does not measure live Reviewer accuracy" in report.disclaimer
    assert "Live model calls: `0`" in render_markdown(report)
    assert canonical_json(report).endswith("\n")


def test_oracle_mutation_cannot_change_policy_output() -> None:
    dataset = load_review_eval_dataset()
    case = dataset.cases[0]
    original = run_fixture_policy(case)
    changed_oracle = dataset.oracles[0].model_copy(
        update={"expected_decision": ReviewDecision.REJECTED}
    )

    assert changed_oracle.expected_decision is ReviewDecision.REJECTED
    assert run_fixture_policy(case) == original


def test_hard_gate_fixture_overrides_unavailable_provider() -> None:
    dataset = load_review_eval_dataset()
    case = next(item for item in dataset.cases if item.fixture_kind.value == "hard_gate_override")

    verdict = run_fixture_policy(case)

    assert verdict.decision is ReviewDecision.REJECTED
    assert verdict.unavailable_reason is None
    assert any(issue.source is ReviewIssueSource.HARD_GATE for issue in verdict.issues)


def test_dataset_rejects_oracle_leakage_unknown_signal_and_duplicate_ids(tmp_path: Path) -> None:
    lines = DEFAULT_CASES_PATH.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["expected_decision"] = "accepted"
    leaked = tmp_path / "leaked.jsonl"
    _replace_first_record(lines, leaked, first)
    with pytest.raises(ReviewEvalDatasetError, match="evaluator-only fields"):
        load_review_eval_dataset(cases_path=leaked)

    first = json.loads(lines[0])
    first["signals"] = [
        {
            "signal": "invented_signal",
            "reference": {"kind": "section", "ref": first["identity"]["section_refs"][0]},
        }
    ]
    unknown = tmp_path / "unknown.jsonl"
    _replace_first_record(lines, unknown, first)
    with pytest.raises(ReviewEvalDatasetError, match="invalid case record"):
        load_review_eval_dataset(cases_path=unknown)

    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text("\n".join([*lines, lines[0]]) + "\n", encoding="utf-8")
    with pytest.raises(ReviewEvalDatasetError, match="case IDs must be unique"):
        load_review_eval_dataset(cases_path=duplicate)

    duplicate_key = tmp_path / "duplicate-key.jsonl"
    duplicate_key_lines = list(lines)
    duplicate_key_lines[0] = duplicate_key_lines[0].replace(
        '"case_id":',
        '"case_id":"shadowed-case","case_id":',
        1,
    )
    duplicate_key.write_text("\n".join(duplicate_key_lines) + "\n", encoding="utf-8")
    with pytest.raises(ReviewEvalDatasetError, match="invalid case JSON"):
        load_review_eval_dataset(cases_path=duplicate_key)

    non_standard_json = tmp_path / "non-standard.jsonl"
    non_standard_lines = list(lines)
    non_standard_lines[0] = non_standard_lines[0].replace(
        '"provider_status":"available"',
        '"provider_status":NaN',
        1,
    )
    non_standard_json.write_text("\n".join(non_standard_lines) + "\n", encoding="utf-8")
    with pytest.raises(ReviewEvalDatasetError, match="invalid case JSON"):
        load_review_eval_dataset(cases_path=non_standard_json)

    unavailable_with_signal = json.loads(lines[0])
    unavailable_with_signal["provider_status"] = "unavailable"
    unavailable_with_signal["signals"] = [
        {
            "signal": "claim_context_unclear",
            "reference": {
                "kind": "claim",
                "ref": unavailable_with_signal["identity"]["claim_refs"][0],
            },
        }
    ]
    unavailable = tmp_path / "unavailable-with-signal.jsonl"
    _replace_first_record(lines, unavailable, unavailable_with_signal)
    with pytest.raises(ReviewEvalDatasetError, match="invalid case record"):
        load_review_eval_dataset(cases_path=unavailable)


def test_dataset_rejects_broken_oracle_reference_and_rubric_drift(tmp_path: Path) -> None:
    oracle_lines = DEFAULT_ORACLE_PATH.read_text(encoding="utf-8").splitlines()
    target_index = next(
        index for index, line in enumerate(oracle_lines) if json.loads(line)["expected_issues"]
    )
    raw = json.loads(oracle_lines[target_index])
    raw["expected_issues"][0]["references"][0]["ref"] = "section:not-declared"
    broken = tmp_path / "broken-oracle.jsonl"
    changed = list(oracle_lines)
    changed[target_index] = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    broken.write_text("\n".join(changed) + "\n", encoding="utf-8")
    with pytest.raises(ReviewEvalDatasetError, match="oracle/reference binding"):
        load_review_eval_dataset(oracle_path=broken)

    rubric = json.loads(DEFAULT_RUBRIC_PATH.read_text(encoding="utf-8"))
    rubric["issues"][0]["severity"] = "warning"
    drifted = tmp_path / "rubric.json"
    drifted.write_text(json.dumps(rubric), encoding="utf-8")
    with pytest.raises(ReviewEvalDatasetError, match="rubric drifted"):
        load_review_eval_dataset(rubric_path=drifted)


def test_metrics_detect_false_accept_and_critical_recall_regression() -> None:
    dataset = load_review_eval_dataset()
    verdicts = {case.case_id: run_fixture_policy(case) for case in dataset.cases}
    target = next(
        case
        for case in dataset.cases
        if case.provider_status.value == "available"
        and any(item.code.value == "fact_not_entailed" for item in case.hard_gate_failures)
    )
    request = build_review_request(
        request_id=f"request:{target.case_id}",
        identity=target.identity,
        reviewer_version=FIXTURE_REVIEWER_VERSION,
        prompt_version=FIXTURE_PROMPT_VERSION,
        hard_gate_failures=(),
    )
    verdicts[target.case_id] = build_review_verdict(request)
    baseline = evaluate_paths()
    report = build_report(
        cases=dataset.cases,
        oracles=dataset.oracles,
        verdicts=verdicts,
        dataset_version=dataset.dataset_version,
        cases_sha256=dataset.cases_sha256,
        oracle_sha256=dataset.oracle_sha256,
        rubric_sha256=dataset.rubric_sha256,
        policy_sha256=baseline.policy_sha256,
        runner_sha256=baseline.runner_sha256,
    )

    assert report.aggregate.false_accept_count == 1
    assert report.aggregate.critical_recall < 1
    assert target.case_id in report.aggregate.failed_case_ids


def test_runner_checks_canonical_without_network_or_credentials() -> None:
    assert main(["--check"]) == 0


def _replace_first_record(lines: list[str], path: Path, replacement: dict[str, object]) -> None:
    changed = list(lines)
    changed[0] = json.dumps(replacement, ensure_ascii=False, separators=(",", ":"))
    path.write_text("\n".join(changed) + "\n", encoding="utf-8")
