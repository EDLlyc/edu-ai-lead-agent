from __future__ import annotations

from app.application.ports.official_account_reviewer import (
    OfficialAccountReviewerRequest,
    OfficialAccountReviewerResult,
)
from app.domain.official_account_reviewer import (
    ReviewIssue,
    ReviewUnavailableReason,
    build_review_verdict,
)


class DeterministicFakeOfficialAccountReviewer:
    def __init__(
        self,
        *,
        issues: tuple[ReviewIssue, ...] = (),
        unavailable_reason: ReviewUnavailableReason | None = None,
        model: str = "official-account-fixture-v1",
    ) -> None:
        self._issues = issues
        self._unavailable_reason = unavailable_reason
        self._model = model
        self.call_count = 0

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return self._model

    async def review(
        self,
        request: OfficialAccountReviewerRequest,
    ) -> OfficialAccountReviewerResult:
        self.call_count += 1
        verdict = build_review_verdict(
            request.contract,
            reviewer_issues=self._issues,
            unavailable_reason=self._unavailable_reason,
        )
        return OfficialAccountReviewerResult(
            verdict=verdict,
            provider=self.provider,
            model=self.model,
            provider_request_id=f"fixture-review-{self.call_count}",
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            latency_ms=0,
        )
