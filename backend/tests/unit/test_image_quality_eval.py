from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.application.ports.official_account_local import (
    OfficialAccountGeneratedVisualEvalResult,
    StoredOfficialAccountGeneratedVisualEval,
    generated_visual_eval_record_fingerprint,
)
from app.domain.image_quality_eval import (
    IMAGE_EVAL_DECISION_POLICY_VERSION,
    IMAGE_EVAL_RUBRIC_VERSION,
    IMAGE_EVAL_SINGLE_IMAGE_DIMENSIONS,
    ImageEvalContractError,
    ImageEvalDecisionKind,
    ImageEvalDimension,
    ImageEvalEvaluatorKind,
    ImageEvalIssueCode,
    ImageEvalObservation,
    ImageEvalObservationStatus,
    ImageEvalSeverity,
    active_image_eval_rubric,
    build_image_eval_issue,
    build_image_eval_observation,
    decide_image_eval,
    decide_image_eval_batch,
)
from evals.image_quality.dataset import (
    DEFAULT_CASES_PATH,
    DEFAULT_OBSERVATIONS_PATH,
    DEFAULT_RUBRIC_PATH,
    ImageEvalDatasetError,
    load_image_eval_dataset,
)
from evals.image_quality.metrics import build_report
from evals.image_quality.reporting import canonical_json, render_markdown
from evals.image_quality.runner import (
    canonical_drift_diagnostics,
    evaluate_paths,
    main,
)
from pydantic import ValidationError


def test_checked_dataset_has_48_balanced_sanitized_cases() -> None:
    dataset = load_image_eval_dataset()

    assert len(dataset.cases) == 48
    assert len(dataset.observations) == 48
    assert len({case.case_id for case in dataset.cases}) == 48
    assert len({item.observation_id for item in dataset.observations}) == 48
    assert all(
        sum(case.dimension is dimension for case in dataset.cases) == 8
        for dimension in ImageEvalDimension
    )
    assert len(dataset.dataset_sha256) == 64
    assert len(dataset.rubric_sha256) == 64
    assert "private/" not in DEFAULT_CASES_PATH.read_text(encoding="utf-8").casefold()


def test_report_separates_six_dimensions_and_never_emits_a_quality_total() -> None:
    report = evaluate_paths()

    assert report.aggregate.case_count == 48
    assert report.aggregate.passed_count == 48
    assert report.aggregate.critical_gold_case_count == 18
    assert report.aggregate.critical_precision == 1
    assert report.aggregate.critical_recall == 1
    assert report.aggregate.critical_f1 == 1
    assert report.aggregate.false_pass_rate == 0
    assert report.aggregate.manual_review_count == 18
    assert report.aggregate.manual_review_rate == 0.375
    assert report.aggregate.unavailable_count == 6
    assert report.aggregate.unavailable_rate == 0.125
    assert {item.dimension for item in report.dimensions} == set(ImageEvalDimension)
    assert all(item.case_count == 8 for item in report.dimensions)
    assert all(item.observation_coverage == 0.875 for item in report.dimensions)
    payload = report.model_dump(mode="json")
    assert "overall_score" not in payload
    assert "quality_score" not in payload


def test_shared_builder_rejects_known_taxonomy_mismatch_and_maps_unknown_provider_issue() -> None:
    with pytest.raises(ImageEvalContractError):
        build_image_eval_issue(
            code=ImageEvalIssueCode.OCR_REQUIRED_TEXT_MISMATCH,
            dimension=ImageEvalDimension.SEMANTIC_FAITHFULNESS,
            severity=ImageEvalSeverity.CRITICAL,
            evidence_ref="evidence:known-mismatch",
        )

    issue = build_image_eval_issue(
        code="provider_specific_composition_problem",
        dimension=ImageEvalDimension.SEMANTIC_FAITHFULNESS,
        severity=ImageEvalSeverity.CRITICAL,
        evidence_ref="evidence:unknown-provider-code",
        score=0.2,
        confidence=0.7,
    )
    assert issue.code is ImageEvalIssueCode.PROVIDER_AUDIT_UNCLASSIFIED
    assert issue.dimension is ImageEvalDimension.AESTHETICS_ARTIFACTS
    assert issue.severity is ImageEvalSeverity.WARNING

    dataset = load_image_eval_dataset()
    observation = build_image_eval_observation(
        observation_id="obs:provider-adapter-unit",
        subject_ref="generated-visual:unit",
        publication_sha256="a" * 64,
        dimension=ImageEvalDimension.AESTHETICS_ARTIFACTS,
        status=ImageEvalObservationStatus.AVAILABLE,
        evaluator_kind=ImageEvalEvaluatorKind.PROVIDER_AUDIT,
        evaluator_version="provider-audit-adapter-v1",
        provider="fixture-provider",
        model="fixture-model",
        request_fingerprint="b" * 64,
        score=0.2,
        confidence=0.7,
        evidence_refs=("evidence:unknown-provider-code",),
        issues=(issue,),
    )

    decision = decide_image_eval(observation, dataset.rubric)

    assert decision.decision is ImageEvalDecisionKind.MANUAL_REVIEW
    assert decision.hard_gate_passed is True
    assert decision.manual_review_required is True


def test_batch_decision_keeps_cross_dimension_issues_separate() -> None:
    semantic = build_image_eval_observation(
        observation_id="provider-audit:semantic_faithfulness",
        subject_ref="generated-visual:batch-unit",
        publication_sha256="a" * 64,
        dimension=ImageEvalDimension.SEMANTIC_FAITHFULNESS,
        status=ImageEvalObservationStatus.AVAILABLE,
        evaluator_kind=ImageEvalEvaluatorKind.PROVIDER_AUDIT,
        evaluator_version="provider-audit-v1",
        provider="fixture-provider",
        model="fixture-model",
        request_fingerprint="b" * 64,
    )
    identity_issue = build_image_eval_issue(
        code=ImageEvalIssueCode.IP_CHARACTER_IDENTITY_MISMATCH,
        dimension=ImageEvalDimension.IP_IDENTITY,
        severity=ImageEvalSeverity.CRITICAL,
        evidence_ref="provider-audit-issue:1",
    )
    identity = build_image_eval_observation(
        observation_id="provider-audit:ip_identity",
        subject_ref=semantic.subject_ref,
        publication_sha256=semantic.publication_sha256,
        dimension=ImageEvalDimension.IP_IDENTITY,
        status=ImageEvalObservationStatus.AVAILABLE,
        evaluator_kind=ImageEvalEvaluatorKind.PROVIDER_AUDIT,
        evaluator_version=semantic.evaluator_version,
        provider=semantic.provider,
        model=semantic.model,
        request_fingerprint=semantic.request_fingerprint,
        evidence_refs=(identity_issue.evidence_ref,),
        issues=(identity_issue,),
    )

    decision = decide_image_eval_batch((semantic, identity), active_image_eval_rubric())

    assert decision.decision is ImageEvalDecisionKind.REJECTED
    assert tuple(item.dimension for item in decision.dimensions) == (
        ImageEvalDimension.IP_IDENTITY,
        ImageEvalDimension.SEMANTIC_FAITHFULNESS,
    )
    assert decision.dimensions[0].reason_codes == (
        ImageEvalIssueCode.IP_CHARACTER_IDENTITY_MISMATCH,
    )
    with pytest.raises(ImageEvalContractError, match="dimensions must be unique"):
        decide_image_eval_batch((semantic, semantic), active_image_eval_rubric())


def test_generated_visual_eval_recomputes_decision_and_record_identity() -> None:
    request_fingerprint = "c" * 64
    observations = tuple(
        build_image_eval_observation(
            observation_id=f"provider-audit:{dimension.value}",
            subject_ref="generated-visual:record-unit",
            publication_sha256="d" * 64,
            dimension=dimension,
            status=ImageEvalObservationStatus.AVAILABLE,
            evaluator_kind=ImageEvalEvaluatorKind.PROVIDER_AUDIT,
            evaluator_version="provider-audit-v1",
            provider="fixture-provider",
            model="fixture-model",
            request_fingerprint=request_fingerprint,
        )
        for dimension in IMAGE_EVAL_SINGLE_IMAGE_DIMENSIONS
    )
    decision = decide_image_eval_batch(observations, active_image_eval_rubric())
    result = OfficialAccountGeneratedVisualEvalResult(
        publication_sha256="d" * 64,
        evaluator_version="provider-audit-v1",
        audit_prompt_version="audit-prompt-v1",
        rubric_version=IMAGE_EVAL_RUBRIC_VERSION,
        decision_policy_version=IMAGE_EVAL_DECISION_POLICY_VERSION,
        request_fingerprint=request_fingerprint,
        observations=observations,
        decision=decision,
        provider="fixture-provider",
        model="fixture-model",
    )
    generated_visual_id = uuid4()
    run_id = uuid4()
    record_fingerprint = generated_visual_eval_record_fingerprint(
        generated_visual_id=generated_visual_id,
        run_id=run_id,
        result=result,
    )

    stored = StoredOfficialAccountGeneratedVisualEval(
        id=uuid4(),
        generated_visual_id=generated_visual_id,
        run_id=run_id,
        record_fingerprint=record_fingerprint,
        result=result,
        completed_at=datetime.now(UTC),
    )

    assert stored.record_fingerprint == record_fingerprint
    historical_observations = tuple(
        observation.model_copy(update={"rubric_version": "image-quality-rubric-v0"})
        for observation in observations
    )
    historical = replace(
        result,
        rubric_version="image-quality-rubric-v0",
        decision_policy_version="image-quality-decision-policy-v0",
        observations=historical_observations,
        decision=decision.model_copy(
            update={"decision_policy_version": "image-quality-decision-policy-v0"}
        ),
    )
    assert historical.decision.decision is ImageEvalDecisionKind.ACCEPTED
    with pytest.raises(ValueError, match="decision does not match observations"):
        OfficialAccountGeneratedVisualEvalResult(
            publication_sha256=result.publication_sha256,
            evaluator_version=result.evaluator_version,
            audit_prompt_version=result.audit_prompt_version,
            rubric_version=result.rubric_version,
            decision_policy_version=result.decision_policy_version,
            request_fingerprint=result.request_fingerprint,
            observations=result.observations,
            decision=decision.model_copy(
                update={
                    "decision": ImageEvalDecisionKind.MANUAL_REVIEW,
                    "manual_review_required": True,
                }
            ),
            provider=result.provider,
            model=result.model,
        )
    with pytest.raises(ValueError, match="record fingerprint changed"):
        replace(stored, record_fingerprint="e" * 64)


def test_critical_issue_cannot_be_offset_by_high_ranking_score() -> None:
    dataset = load_image_eval_dataset()
    issue = build_image_eval_issue(
        code=ImageEvalIssueCode.SEMANTIC_CORE_ENTITY_MISSING,
        dimension=ImageEvalDimension.SEMANTIC_FAITHFULNESS,
        severity=ImageEvalSeverity.CRITICAL,
        evidence_ref="evidence:critical-semantic",
        score=0.99,
        confidence=0.99,
    )
    observation = build_image_eval_observation(
        observation_id="obs:critical-score-unit",
        subject_ref="generated-visual:critical-score-unit",
        publication_sha256="c" * 64,
        dimension=ImageEvalDimension.SEMANTIC_FAITHFULNESS,
        status=ImageEvalObservationStatus.AVAILABLE,
        evaluator_kind=ImageEvalEvaluatorKind.DETERMINISTIC,
        evaluator_version="deterministic-unit-v1",
        score=0.99,
        confidence=0.99,
        evidence_refs=("evidence:critical-semantic",),
        issues=(issue,),
    )

    decision = decide_image_eval(observation, dataset.rubric)

    assert decision.decision is ImageEvalDecisionKind.REJECTED
    assert decision.hard_gate_passed is False
    assert decision.ranking_score == 0.99


def test_false_pass_metric_uses_gold_critical_cases() -> None:
    dataset = load_image_eval_dataset()
    target = next(
        case for case in dataset.cases if case.case_id == "semantic-faithfulness-hard-negative-01"
    )
    changed = []
    for observation in dataset.observations:
        if observation.subject_ref == target.case_id:
            changed.append(
                observation.model_copy(
                    update={
                        "issues": (),
                        "score": 0.99,
                        "confidence": 0.99,
                    }
                )
            )
        else:
            changed.append(observation)

    report = build_report(
        cases=dataset.cases,
        observations=tuple(changed),
        rubric=dataset.rubric,
        dataset_sha256=dataset.dataset_sha256,
        rubric_sha256=dataset.rubric_sha256,
    )

    assert report.aggregate.false_pass_count == 1
    assert report.aggregate.false_pass_rate == round(1 / 18, 6)
    assert report.aggregate.critical_recall == round(17 / 18, 6)
    failed = next(item for item in report.cases if item.case_id == target.case_id)
    assert failed.passed is False
    assert "decision_mismatch:expected=rejected:actual=accepted" in failed.failure_codes


def test_dataset_rejects_malformed_unknown_and_illegal_score_records(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("{not-json}\n", encoding="utf-8")
    with pytest.raises(ImageEvalDatasetError, match="invalid case JSON at line 1"):
        load_image_eval_dataset(cases_path=malformed)

    raw = json.loads(DEFAULT_CASES_PATH.read_text(encoding="utf-8").splitlines()[0])
    raw["dimension"] = "invented_dimension"
    invalid_dimension = tmp_path / "invalid-dimension.jsonl"
    _replace_first_jsonl_record(DEFAULT_CASES_PATH, invalid_dimension, raw)
    with pytest.raises(ImageEvalDatasetError, match="invalid case record at line 1"):
        load_image_eval_dataset(cases_path=invalid_dimension)

    observation = json.loads(DEFAULT_OBSERVATIONS_PATH.read_text(encoding="utf-8").splitlines()[0])
    observation["score"] = 1.1
    invalid_score = tmp_path / "invalid-score.jsonl"
    _replace_first_jsonl_record(DEFAULT_OBSERVATIONS_PATH, invalid_score, observation)
    with pytest.raises(ImageEvalDatasetError, match="invalid observation record at line 1"):
        load_image_eval_dataset(observations_path=invalid_score)


def test_strict_schema_forbids_unreviewed_observation_fields() -> None:
    raw = json.loads(DEFAULT_OBSERVATIONS_PATH.read_text(encoding="utf-8").splitlines()[0])
    raw["raw_prompt"] = "must never be stored"

    with pytest.raises(ValidationError):
        ImageEvalObservation.model_validate(raw)

    issue_record = next(
        json.loads(line)
        for line in DEFAULT_OBSERVATIONS_PATH.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["issues"]
    )
    issue_record["evidence_refs"] = []
    with pytest.raises(ValidationError, match="declared evidence"):
        ImageEvalObservation.model_validate(issue_record)


def test_dataset_rejects_duplicate_case_and_observation_ids(tmp_path: Path) -> None:
    cases_text = DEFAULT_CASES_PATH.read_text(encoding="utf-8")
    duplicate_cases = tmp_path / "duplicate-cases.jsonl"
    duplicate_cases.write_text(cases_text + cases_text.splitlines()[0] + "\n", encoding="utf-8")
    with pytest.raises(ImageEvalDatasetError, match="case IDs must be unique"):
        load_image_eval_dataset(cases_path=duplicate_cases)

    observations_text = DEFAULT_OBSERVATIONS_PATH.read_text(encoding="utf-8")
    duplicate_observations = tmp_path / "duplicate-observations.jsonl"
    duplicate_observations.write_text(
        observations_text + observations_text.splitlines()[0] + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ImageEvalDatasetError, match="observation IDs must be unique"):
        load_image_eval_dataset(observations_path=duplicate_observations)


def test_dataset_rejects_publication_hash_mismatch(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_OBSERVATIONS_PATH.read_text(encoding="utf-8").splitlines()[0])
    raw["publication_sha256"] = "f" * 64
    mismatched = tmp_path / "hash-mismatch.jsonl"
    _replace_first_jsonl_record(DEFAULT_OBSERVATIONS_PATH, mismatched, raw)

    with pytest.raises(ImageEvalDatasetError, match="publication hash mismatch"):
        load_image_eval_dataset(observations_path=mismatched)


def test_dataset_hash_changes_for_semantically_identical_byte_drift(tmp_path: Path) -> None:
    original = load_image_eval_dataset()
    drifted_cases = tmp_path / "byte-drift.jsonl"
    lines = DEFAULT_CASES_PATH.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    lines[0] = json.dumps(first, ensure_ascii=False, sort_keys=True, separators=(", ", ": "))
    drifted_cases.write_text("\n".join(lines) + "\n", encoding="utf-8")

    drifted = load_image_eval_dataset(cases_path=drifted_cases)

    assert drifted.dataset_sha256 != original.dataset_sha256
    assert drifted.cases == original.cases


def test_canonical_drift_diagnostic_includes_expected_and_actual_paths() -> None:
    report = evaluate_paths()
    actual_json = canonical_json(report)
    expected_payload = report.model_dump(mode="json")
    expected_payload["dataset_sha256"] = "0" * 64
    expected_json = (
        json.dumps(expected_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    actual_markdown = render_markdown(report)

    diagnostics = canonical_drift_diagnostics(
        expected_json=expected_json,
        actual_json=actual_json,
        expected_markdown=actual_markdown + "drift\n",
        actual_markdown=actual_markdown,
    )

    assert any(
        diagnostic.startswith("$.dataset_sha256:expected='0000") and ":actual=" in diagnostic
        for diagnostic in diagnostics
    )
    assert "canonical_markdown_mismatch:expected=checked_artifact:actual=rendered_report" in (
        diagnostics
    )

    invalid_expected = canonical_drift_diagnostics(
        expected_json="{not-json}\n",
        actual_json=actual_json,
        expected_markdown=actual_markdown,
        actual_markdown=actual_markdown,
    )
    assert invalid_expected == (
        "canonical_json_invalid:expected=valid_json:actual=checked_artifact",
    )


def test_checked_canonical_artifacts_match() -> None:
    assert main(["--check"]) == 0


def test_rubric_hash_and_version_are_in_canonical_report() -> None:
    report = evaluate_paths(rubric_path=DEFAULT_RUBRIC_PATH)

    assert report.rubric_version == IMAGE_EVAL_RUBRIC_VERSION
    assert len(report.rubric_sha256) == 64
    assert report.decision_policy_version == "image-quality-decision-policy-v1"
    assert "live model quality" in report.disclaimer


def _replace_first_jsonl_record(source: Path, target: Path, replacement: object) -> None:
    lines = source.read_text(encoding="utf-8").splitlines()
    lines[0] = json.dumps(replacement, ensure_ascii=False, separators=(",", ":"))
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
