"""Frozen provider-free policy that never receives evaluator oracle fields."""

from __future__ import annotations

from app.domain.official_account_reviewer import (
    ReviewIssueSource,
    ReviewUnavailableReason,
    ReviewVerdict,
    build_review_issue,
    build_review_request,
    build_review_verdict,
)

from .models import FixtureProviderStatus, ReviewEvalCase, fixture_signal_issue_code

FIXTURE_POLICY_VERSION = "official-account-review-fixture-policy-v1"
FIXTURE_REVIEWER_VERSION = "provider-free-reviewer-v1"
FIXTURE_PROMPT_VERSION = "provider-free-review-prompt-v1"


def run_fixture_policy(case: ReviewEvalCase) -> ReviewVerdict:
    """Evaluate only case-side observations; no oracle object enters this function."""

    request = build_review_request(
        request_id=f"request:{case.case_id}",
        identity=case.identity,
        reviewer_version=FIXTURE_REVIEWER_VERSION,
        prompt_version=FIXTURE_PROMPT_VERSION,
        hard_gate_failures=case.hard_gate_failures,
    )
    reviewer_issues = tuple(
        build_review_issue(
            code=fixture_signal_issue_code(item.signal),
            source=ReviewIssueSource.REVIEWER,
            references=(item.reference,),
        )
        for item in case.signals
    )
    unavailable_reason = {
        FixtureProviderStatus.AVAILABLE: None,
        FixtureProviderStatus.UNAVAILABLE: ReviewUnavailableReason.PROVIDER_UNAVAILABLE,
        FixtureProviderStatus.INVALID_OUTPUT: ReviewUnavailableReason.INVALID_OUTPUT,
    }[case.provider_status]
    return build_review_verdict(
        request,
        reviewer_issues=reviewer_issues,
        unavailable_reason=unavailable_reason,
    )
