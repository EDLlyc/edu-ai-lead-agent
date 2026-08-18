from __future__ import annotations

from dataclasses import replace

from evals.digital_ip.dataset import load_eval_cases
from evals.digital_ip.metrics import score_case
from evals.digital_ip.reporting import canonical_json, render_markdown
from evals.digital_ip.runner import _profile_for_case, evaluate_path


def test_digital_ip_fixture_report_covers_five_contracts_without_fact_violation() -> None:
    cases = load_eval_cases()
    report = evaluate_path()

    assert len(cases) == 5
    assert {case.category.value for case in cases} == {
        "positioning",
        "tone",
        "prohibited_language",
        "safety",
        "visual",
    }
    assert report.aggregate.passed_count == report.aggregate.case_count == 5
    assert report.aggregate.expected_type_coverage == 1.0
    assert report.aggregate.expected_tag_coverage == 1.0
    assert report.aggregate.prohibited_rule_hit_rate == 1.0
    assert report.aggregate.brand_as_fact_count == 0


def test_digital_ip_report_is_stable_and_disclaims_real_model_accuracy() -> None:
    report = evaluate_path()

    assert canonical_json(report) == canonical_json(evaluate_path())
    markdown = render_markdown(report)
    assert "fixture contract conformance" in markdown
    assert "not a live embedding" in markdown
    assert "Brand-as-fact violations: 0" in markdown


def test_evaluator_fails_a_profile_marked_as_external_fact_evidence() -> None:
    case = load_eval_cases()[0]
    unsafe_profile = replace(_profile_for_case(case), evidence_eligible=True)

    score = score_case(case, unsafe_profile)

    assert score.passed is False
    assert score.brand_as_fact_count == 1
    assert "brand_marked_as_fact_evidence" in score.failure_codes


def test_evaluator_does_not_use_expected_tags_to_construct_the_profile() -> None:
    case = next(case for case in load_eval_cases() if case.category.value == "tone")
    profile = _profile_for_case(case)
    mismatched_oracle = case.model_copy(update={"expected_tone_tags": ("不存在的语气标签",)})

    score = score_case(mismatched_oracle, profile)

    assert score.passed is False
    assert "expected_tag_missing" in score.failure_codes
