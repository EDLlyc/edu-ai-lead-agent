from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from app.application.ports.official_account_local import (
    ClaimedOfficialAccountRun,
    OfficialAccountArticleGenerator,
    OfficialAccountGenerationRequest,
    OfficialAccountGenerationResult,
    StoredOfficialAccountArticle,
)
from app.domain.official_account_local import ArticlePackage, OfficialAccountSourceSnapshot
from app.domain.official_account_reviewer import ReviewRequest, ReviewVerdict

ReviewerMode = Literal["off", "observe", "enforce"]
_SAFE_PROVIDER = re.compile(r"^[a-z][a-z0-9._:-]{0,39}$")
_SAFE_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")
_SAFE_PROVIDER_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


@dataclass(frozen=True, slots=True)
class OfficialAccountReviewerRequest:
    contract: ReviewRequest
    source: OfficialAccountSourceSnapshot
    article: ArticlePackage
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class OfficialAccountReviewerResult:
    verdict: ReviewVerdict
    provider: str
    model: str
    provider_request_id: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None
    latency_ms: int
    validation_corrections: int = 0

    def __post_init__(self) -> None:
        if _SAFE_PROVIDER.fullmatch(self.provider) is None:
            raise ValueError("Reviewer provider identity is invalid")
        if _SAFE_MODEL.fullmatch(self.model) is None:
            raise ValueError("Reviewer model identity is invalid")
        if (
            self.provider_request_id is not None
            and _SAFE_PROVIDER_REQUEST_ID.fullmatch(self.provider_request_id) is None
        ):
            raise ValueError("Reviewer provider request identity is invalid")
        token_values = (self.prompt_tokens, self.completion_tokens, self.reasoning_tokens)
        if any(value is not None and value < 0 for value in token_values):
            raise ValueError("Reviewer token usage cannot be negative")
        if self.latency_ms < 0 or self.validation_corrections < 0:
            raise ValueError("Reviewer local usage cannot be negative")


@dataclass(frozen=True, slots=True)
class ReviewArtifactBinding:
    article_artifact_id: UUID
    source_artifact_id: UUID
    brand_artifact_id: UUID
    article_sha256: str
    source_sha256: str
    brand_sha256: str


@dataclass(frozen=True, slots=True)
class ReviewExecutionBinding:
    execution_run_id: UUID
    task_id: str
    reviewer_agent_id: str
    reviewer_parent_event_id: UUID
    reservation_id: UUID
    request_event_id: UUID


@dataclass(frozen=True, slots=True)
class StoredReviewIntent:
    id: UUID
    run_id: UUID
    article_version_id: UUID
    attempt_number: int
    status: Literal["pending", "calling", "completed", "result_unknown"]
    contract: ReviewRequest
    artifact_binding: ReviewArtifactBinding
    execution_binding: ReviewExecutionBinding | None
    provider: str
    model: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StoredReviewRecord:
    id: UUID
    request_id: UUID
    verdict: ReviewVerdict
    provider_request_id: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None
    latency_ms: int
    validation_corrections: int
    execution_artifact_id: UUID
    execution_event_id: UUID
    created_at: datetime


class OfficialAccountReviewer(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def review(
        self,
        request: OfficialAccountReviewerRequest,
    ) -> OfficialAccountReviewerResult: ...


class OfficialAccountReviewRepository(Protocol):
    async def create_intent(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        article: StoredOfficialAccountArticle,
        contract: ReviewRequest,
        artifacts: ReviewArtifactBinding,
        provider: str,
        model: str,
    ) -> StoredReviewIntent: ...

    async def mark_calling(
        self,
        *,
        intent: StoredReviewIntent,
        execution: ReviewExecutionBinding,
    ) -> StoredReviewIntent: ...

    async def mark_result_unknown(
        self,
        *,
        intent: StoredReviewIntent,
        error_code: str,
    ) -> StoredReviewIntent: ...

    async def persist_record(
        self,
        *,
        intent: StoredReviewIntent,
        result: OfficialAccountReviewerResult,
        execution_artifact_id: UUID,
        execution_event_id: UUID,
    ) -> StoredReviewRecord: ...

    async def get_record(self, request_id: UUID) -> StoredReviewRecord | None: ...


class OfficialAccountReviewGovernance(Protocol):
    async def govern_generation(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        request: OfficialAccountGenerationRequest,
        generator: OfficialAccountArticleGenerator,
    ) -> OfficialAccountGenerationResult: ...

    async def observe(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        source: OfficialAccountSourceSnapshot,
        article: StoredOfficialAccountArticle,
        reviewer: OfficialAccountReviewer,
    ) -> StoredReviewRecord | None: ...

    async def close_without_review(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        source: OfficialAccountSourceSnapshot,
    ) -> None: ...
