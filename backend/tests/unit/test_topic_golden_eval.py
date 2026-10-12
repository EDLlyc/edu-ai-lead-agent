from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from evals.topic_golden.runner import build_report, load_cases, main


def test_canonical_report_is_current() -> None:
    assert main(["--check"]) == 0


def test_education_policy_version_recovers_operator_labelled_policy_news() -> None:
    report = build_report(load_cases())
    by_version = {version["scoring_version"]: version for version in report["versions"]}
    baseline = by_version["scoring-v1-preview.11-qualified-authoritative-priority"]
    current = by_version["scoring-v1-preview.13-education-policy-signal"]

    for case_id in (
        "g01-higher-education-classified-reform",
        "g02-five-year-education-priorities",
        "r01-provincial-exam-reform",
    ):
        assert case_id in baseline["failed_case_ids"]
        assert case_id not in current["failed_case_ids"]
    # Rejections stay rejected: the new lane does not admit marketing, ceremonies or notices.
    for case_id in ("n01-admissions-marketing", "n02-campus-ceremony", "n03-personnel-notice"):
        assert case_id not in current["failed_case_ids"]


def test_gov_yaowen_gate_stops_diplomacy_and_economy_jumping_the_queue() -> None:
    report = build_report(load_cases())
    by_version = {version["scoring_version"]: version for version in report["versions"]}
    previous = by_version["scoring-v1-preview.14-negative-incident-industrial-tech"]
    current = by_version["scoring-v1-preview.15-gov-yaowen-topic-gate"]

    for case_id in (
        "n06-gov-yaowen-diplomatic-meeting",
        "n07-gov-yaowen-water-investment",
        "n08-gov-yaowen-trade-talks",
    ):
        assert case_id in previous["failed_case_ids"]
        assert case_id not in current["failed_case_ids"]
    # Science/industry gov.cn headlines keep their priority.
    for case_id in ("g05-new-industrialisation-yaowen", "g08-gov-yaowen-advanced-manufacturing"):
        assert case_id not in current["failed_case_ids"]
    assert current["must_select_priority"] == previous["must_select_priority"]


def test_national_tech_policy_rule_selects_the_central_document_without_loosening_meetings() -> (
    None
):
    report = build_report(load_cases())
    by_version = {
        version["scoring_version"]: version
        for version in cast("list[dict[str, Any]]", report["versions"])
    }
    previous = by_version["scoring-v1-preview.15-gov-yaowen-topic-gate"]
    current = by_version["scoring-v1-preview.17-national-tech-policy"]
    case_id = "g09-central-new-quality-productive-forces-opinion"

    assert case_id in previous["failed_case_ids"]
    assert case_id not in current["failed_case_ids"]
    # No other case changes outcome: the rule only adds the central policy document.
    assert set(current["failed_case_ids"]) == set(previous["failed_case_ids"]) - {case_id}
    assert (previous["must_select_priority"], current["must_select_priority"]) == ("7/8", "8/8")


def _write(tmp_path: Path, **overrides: object) -> Path:
    case = {
        "case_id": "x",
        "label": "must_select",
        "expect_priority": False,
        "category": "c",
        "label_source": "s",
        "synthetic": True,
        "source_tiers": ["A"],
        "topic_priority_policy": None,
        "title": "t",
        "summary": "s",
        "source_url": None,
        **overrides,
    }
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(case, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"label": "maybe"}, "unsupported label"),
        ({"source_tiers": ["C"]}, "source tiers"),
        ({"label": "should_not_select", "expect_priority": True}, "cannot expect priority"),
        ({"reject_scope": "priority"}, "reject scope"),
    ),
)
def test_invalid_cases_are_rejected(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        load_cases(_write(tmp_path, **overrides))
