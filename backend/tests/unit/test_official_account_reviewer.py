from __future__ import annotations

import json

import pytest
from app.domain.official_account_reviewer import (
    REPAIR_POLICY_VERSION,
    RepairDirective,
    RepairOperation,
    ReviewContractError,
    ReviewDecision,
    ReviewHardGateCode,
    ReviewHardGateFailure,
    ReviewInputIdentity,
    ReviewIssue,
    ReviewIssueCode,
    ReviewIssueSource,
    ReviewReference,
    ReviewReferenceKind,
    ReviewRubric,
    ReviewSeverity,
    ReviewUnavailableReason,
    ReviewVerdict,
    active_review_rubric,
    build_review_issue,
    build_review_request,
    build_review_verdict,
    project_repair_directives,
    validate_review_verdict_binding,
)
from pydantic import ValidationError


def _identity() -> ReviewInputIdentity:
    return ReviewInputIdentity(
        article_ref="article:unit",
        article_fingerprint="a" * 64,
        section_refs=("section:intro", "section:body"),
        block_refs=("block:intro:1", "block:body:1"),
        claim_refs=("claim:1",),
        evidence_refs=("evidence:1",),
    )


def _request(
    *,
    hard_gate_failures: tuple[ReviewHardGateFailure, ...] = (),
):
    return build_review_request(
        request_id="request:unit",
        identity=_identity(),
        reviewer_version="reviewer:v1",
        prompt_version="prompt:v1",
        hard_gate_failures=hard_gate_failures,
    )


def test_closed_issue_schema_rejects_unknown_code_and_severity_drift() -> None:
    payload = {
        "code": "invented_quality_problem",
        "dimension": "brand_tone",
        "severity": "warning",
        "source": "reviewer",
        "references": [{"kind": "section", "ref": "section:intro"}],
    }
    with pytest.raises(ValidationError):
        ReviewIssue.model_validate(payload)

    payload["code"] = "brand_tone_mismatch"
    payload["severity"] = "critical"
    with pytest.raises(ValidationError, match="code-owned taxonomy"):
        ReviewIssue.model_validate(payload)

    with pytest.raises(ValidationError, match="cannot emit a hard-gate"):
        build_review_issue(
            code=ReviewIssueCode.PRIVACY_RISK,
            source=ReviewIssueSource.REVIEWER,
            references=(ReviewReference(kind=ReviewReferenceKind.BLOCK, ref="block:intro:1"),),
        )


def test_verdict_references_are_bound_to_typed_article_input() -> None:
    request = _request()
    broken = build_review_issue(
        code=ReviewIssueCode.BRAND_TONE_MISMATCH,
        source=ReviewIssueSource.REVIEWER,
        references=(ReviewReference(kind=ReviewReferenceKind.SECTION, ref="section:not-declared"),),
    )

    with pytest.raises(ReviewContractError, match="not declared"):
        build_review_verdict(request, reviewer_issues=(broken,))

    accepted = build_review_verdict(request)
    other_request = build_review_request(
        request_id="request:other",
        identity=_identity(),
        reviewer_version=request.reviewer_version,
        prompt_version=request.prompt_version,
    )
    with pytest.raises(ReviewContractError, match="identity"):
        validate_review_verdict_binding(other_request, accepted)


def test_illegal_accepted_or_rejected_combinations_fail_closed() -> None:
    accepted = build_review_verdict(_request())
    payload = accepted.model_dump(mode="json")
    payload["decision"] = "rejected"
    with pytest.raises(ValidationError, match="closed decision policy"):
        ReviewVerdict.model_validate(payload)

    payload = accepted.model_dump(mode="json")
    payload["unavailable_reason"] = "provider_unavailable"
    with pytest.raises(ValidationError):
        ReviewVerdict.model_validate(payload)


def test_hard_gate_overrides_provider_unavailability_and_cannot_be_averaged() -> None:
    request = _request(
        hard_gate_failures=(
            ReviewHardGateFailure(
                code=ReviewHardGateCode.FACT_NOT_ENTAILED,
                reference=ReviewReference(kind=ReviewReferenceKind.CLAIM, ref="claim:1"),
            ),
        )
    )

    verdict = build_review_verdict(
        request,
        unavailable_reason=ReviewUnavailableReason.PROVIDER_UNAVAILABLE,
    )

    assert verdict.decision is ReviewDecision.REJECTED
    assert verdict.unavailable_reason is None
    assert verdict.issues[0].severity is ReviewSeverity.CRITICAL
    assert verdict.issues[0].source is ReviewIssueSource.HARD_GATE
    assert verdict.issues[0].code is ReviewIssueCode.FACT_NOT_ENTAILED


def test_hard_gate_blocks_repair_and_dominates_same_dimension_observation() -> None:
    request = _request(
        hard_gate_failures=(
            ReviewHardGateFailure(
                code=ReviewHardGateCode.PRIVACY_RISK,
                reference=ReviewReference(
                    kind=ReviewReferenceKind.BLOCK,
                    ref="block:body:1",
                ),
            ),
        )
    )
    same_dimension = build_review_issue(
        code=ReviewIssueCode.BRAND_TONE_MISMATCH,
        source=ReviewIssueSource.REVIEWER,
        references=(ReviewReference(kind=ReviewReferenceKind.SECTION, ref="section:body"),),
    )
    verdict = build_review_verdict(request, reviewer_issues=(same_dimension,))

    assert verdict.decision is ReviewDecision.REJECTED
    assert {issue.code for issue in verdict.issues} == {
        ReviewIssueCode.BRAND_TONE_MISMATCH,
        ReviewIssueCode.PRIVACY_RISK,
    }
    assert project_repair_directives(request, verdict) == ()

    privacy_observation = build_review_issue(
        code=ReviewIssueCode.INSTRUCTION_CONTEXT_AMBIGUOUS,
        source=ReviewIssueSource.REVIEWER,
        references=(ReviewReference(kind=ReviewReferenceKind.BLOCK, ref="block:body:1"),),
    )
    other_request = _request(
        hard_gate_failures=(
            ReviewHardGateFailure(
                code=ReviewHardGateCode.PROMPT_INJECTION_DETECTED,
                reference=ReviewReference(
                    kind=ReviewReferenceKind.BLOCK,
                    ref="block:body:1",
                ),
            ),
        )
    )
    dominated = build_review_verdict(other_request, reviewer_issues=(privacy_observation,))
    assert [issue.code for issue in dominated.issues] == [ReviewIssueCode.PROMPT_INJECTION_DETECTED]


def test_reviewer_channel_cannot_spoof_hard_gate_or_mix_unavailable_issues() -> None:
    request = _request(
        hard_gate_failures=(
            ReviewHardGateFailure(
                code=ReviewHardGateCode.PRIVACY_RISK,
                reference=ReviewReference(
                    kind=ReviewReferenceKind.BLOCK,
                    ref="block:body:1",
                ),
            ),
        )
    )
    spoofed = build_review_issue(
        code=ReviewIssueCode.PRIVACY_RISK,
        source=ReviewIssueSource.HARD_GATE,
        references=(ReviewReference(kind=ReviewReferenceKind.BLOCK, ref="block:body:1"),),
    )
    with pytest.raises(ReviewContractError, match="cannot claim a hard-gate"):
        build_review_verdict(request, reviewer_issues=(spoofed,))

    reviewer_issue = build_review_issue(
        code=ReviewIssueCode.BRAND_TONE_MISMATCH,
        source=ReviewIssueSource.REVIEWER,
        references=(ReviewReference(kind=ReviewReferenceKind.SECTION, ref="section:body"),),
    )
    with pytest.raises(ReviewContractError, match="unavailable Reviewer"):
        build_review_verdict(
            _request(),
            reviewer_issues=(reviewer_issue,),
            unavailable_reason=ReviewUnavailableReason.PROVIDER_UNAVAILABLE,
        )


def test_repairability_and_directives_are_code_owned_without_free_text() -> None:
    request = _request()
    issue = build_review_issue(
        code=ReviewIssueCode.PARAGRAPH_DENSITY_HIGH,
        source=ReviewIssueSource.REVIEWER,
        references=(ReviewReference(kind=ReviewReferenceKind.BLOCK, ref="block:body:1"),),
    )
    verdict = build_review_verdict(request, reviewer_issues=(issue,))

    directives = project_repair_directives(request, verdict)

    assert verdict.decision is ReviewDecision.REJECTED
    assert len(directives) == 1
    assert directives[0].operation.value == "split_dense_paragraph"
    assert directives[0].repair_policy_version == REPAIR_POLICY_VERSION
    assert set(directives[0].model_dump()) == {
        "directive_id",
        "issue_code",
        "target",
        "operation",
        "repair_policy_version",
    }
    with pytest.raises(ValidationError, match="actionable article target"):
        build_review_issue(
            code=ReviewIssueCode.MARKETING_CLAIM_EXAGGERATED,
            source=ReviewIssueSource.REVIEWER,
            references=(ReviewReference(kind=ReviewReferenceKind.CLAIM, ref="claim:1"),),
        )
    with pytest.raises(ValidationError, match="actionable article target"):
        RepairDirective(
            directive_id="repair:01:brand-tone",
            issue_code=ReviewIssueCode.BRAND_TONE_MISMATCH,
            target=ReviewReference(kind=ReviewReferenceKind.CLAIM, ref="claim:1"),
            operation=RepairOperation.ALIGN_BRAND_TONE,
            repair_policy_version=REPAIR_POLICY_VERSION,
        )


def test_nonrepairable_warning_routes_to_manual_review() -> None:
    request = _request()
    issue = build_review_issue(
        code=ReviewIssueCode.FACTUAL_CONTEXT_AMBIGUOUS,
        source=ReviewIssueSource.REVIEWER,
        references=(ReviewReference(kind=ReviewReferenceKind.CLAIM, ref="claim:1"),),
    )

    verdict = build_review_verdict(request, reviewer_issues=(issue,))

    assert verdict.decision is ReviewDecision.MANUAL_REVIEW
    assert project_repair_directives(request, verdict) == ()


def test_request_and_record_fingerprints_are_deterministic_and_tamper_evident() -> None:
    first = _request()
    second = _request()
    first_verdict = build_review_verdict(first)
    assert first.request_fingerprint == second.request_fingerprint
    assert first_verdict.record_fingerprint == build_review_verdict(second).record_fingerprint

    payload = first.model_dump(mode="json")
    payload["identity"]["article_fingerprint"] = "b" * 64
    with pytest.raises(ValidationError, match="fingerprint changed"):
        type(first).model_validate(payload)

    verdict_payload = first_verdict.model_dump(mode="json")
    verdict_payload["reviewer_version"] = "reviewer:v2"
    with pytest.raises(ValidationError, match="record fingerprint changed"):
        ReviewVerdict.model_validate(verdict_payload)


def test_rubric_rejects_duplicate_dimensions_and_taxonomy_drift() -> None:
    rubric = active_review_rubric()
    payload = rubric.model_dump(mode="json")
    payload["dimensions"][1] = payload["dimensions"][0]
    with pytest.raises(ValidationError, match="dimensions must be unique"):
        ReviewRubric.model_validate(payload)

    payload = rubric.model_dump(mode="json")
    payload["issues"][0]["repairable"] = True
    with pytest.raises(ValidationError, match="code-owned taxonomy"):
        ReviewRubric.model_validate(payload)


def test_verdict_rejects_multiple_reviewer_issues_for_one_dimension() -> None:
    request = _request()
    first = build_review_issue(
        code=ReviewIssueCode.HEADING_HIERARCHY_INVALID,
        source=ReviewIssueSource.REVIEWER,
        references=(ReviewReference(kind=ReviewReferenceKind.SECTION, ref="section:body"),),
    )
    second = build_review_issue(
        code=ReviewIssueCode.PARAGRAPH_DENSITY_HIGH,
        source=ReviewIssueSource.REVIEWER,
        references=(ReviewReference(kind=ReviewReferenceKind.BLOCK, ref="block:body:1"),),
    )

    with pytest.raises(ValidationError, match="dimensions must be unique"):
        build_review_verdict(request, reviewer_issues=(first, second))


def test_strict_models_forbid_reasoning_and_free_text_instruction_fields() -> None:
    verdict = build_review_verdict(_request())
    payload = json.loads(verdict.model_dump_json())
    payload["chain_of_thought"] = "hidden reasoning must never be stored"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ReviewVerdict.model_validate(payload)
