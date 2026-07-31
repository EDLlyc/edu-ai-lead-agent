from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.core.errors import ProviderValidationIssue
from app.domain.copy_generation import (
    ActiveBrandContext,
    CopyVersionBundle,
    EligibleEvidence,
    LockedTopicContext,
)
from app.schemas.copy_generation import AuditVerdict, CopyIssue, MaterialDraft


@dataclass(frozen=True, slots=True)
class ClaimedCopyGenerationJob:
    job_id: UUID
    run_id: UUID
    attempt_number: int
    lease_token: UUID
    version_bundle: CopyVersionBundle


@dataclass(frozen=True, slots=True)
class DraftGenerationRequest:
    run_id: UUID
    topic: LockedTopicContext
    brand_context: tuple[ActiveBrandContext, ...]
    version_bundle: CopyVersionBundle
    draft_version: int
    max_output_tokens: int
    repair_issues: tuple[CopyIssue, ...] = ()
    previous_draft: MaterialDraft | None = None


@dataclass(frozen=True, slots=True)
class DraftGenerationResult:
    draft: MaterialDraft
    provider: str
    model: str
    request_fingerprint: str
    provider_request_id: str | None
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    latency_ms: int
    validation_corrections: int = 0


@dataclass(frozen=True, slots=True)
class DraftAuditRequest:
    run_id: UUID
    draft_version_id: UUID
    topic: LockedTopicContext
    brand_context: tuple[ActiveBrandContext, ...]
    draft: MaterialDraft
    version_bundle: CopyVersionBundle
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class DraftAuditResult:
    verdict: AuditVerdict
    provider: str
    model: str
    request_fingerprint: str
    provider_request_id: str | None
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    latency_ms: int
    validation_corrections: int = 0


@dataclass(frozen=True, slots=True)
class StoredDraft:
    id: UUID
    version: int
    repair_of_version_id: UUID | None
    draft: MaterialDraft
    validation_issues: tuple[CopyIssue, ...]
    audit: AuditVerdict | None
    created_at: datetime

    @property
    def validation_passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.validation_issues)


class MaterialDraftGenerator(Protocol):
    async def generate(self, request: DraftGenerationRequest) -> DraftGenerationResult: ...


class MaterialDraftAuditor(Protocol):
    async def audit(self, request: DraftAuditRequest) -> DraftAuditResult: ...


class BrandContextRetriever(Protocol):
    async def retrieve_for_copy(
        self, topic: LockedTopicContext
    ) -> tuple[ActiveBrandContext, ...]: ...


class CopyGenerationRepository(Protocol):
    async def enqueue_for_daily_topic(
        self,
        *,
        business_date: date,
        timezone: str,
        scoring_profile: str,
        version_bundle: CopyVersionBundle,
    ) -> UUID: ...

    async def reconcile_ready_topics(
        self,
        *,
        timezone: str,
        scoring_profile: str,
        version_bundle: CopyVersionBundle,
        limit: int = 20,
    ) -> int: ...

    async def claim(
        self, *, worker_id: str, lease_seconds: int, max_attempts: int
    ) -> ClaimedCopyGenerationJob | None: ...

    async def heartbeat(self, *, claimed: ClaimedCopyGenerationJob, lease_seconds: int) -> bool: ...

    async def load_topic_context(self, claimed: ClaimedCopyGenerationJob) -> LockedTopicContext: ...

    async def load_drafts(self, claimed: ClaimedCopyGenerationJob) -> tuple[StoredDraft, ...]: ...

    async def load_brand_context_for_draft(
        self, *, claimed: ClaimedCopyGenerationJob, draft: StoredDraft
    ) -> tuple[ActiveBrandContext, ...]: ...

    async def persist_no_topic(self, claimed: ClaimedCopyGenerationJob) -> bool: ...

    async def persist_draft(
        self,
        *,
        claimed: ClaimedCopyGenerationJob,
        result: DraftGenerationResult,
        draft_version: int,
        repair_of_version_id: UUID | None,
        validation_issues: tuple[CopyIssue, ...],
        evidence_by_id: dict[UUID, EligibleEvidence],
        brand_context: tuple[ActiveBrandContext, ...],
    ) -> StoredDraft | None: ...

    async def persist_audit(
        self,
        *,
        claimed: ClaimedCopyGenerationJob,
        draft: StoredDraft,
        result: DraftAuditResult,
    ) -> StoredDraft | None: ...

    async def finish(
        self,
        *,
        claimed: ClaimedCopyGenerationJob,
        status: str,
        active_draft_version_id: UUID | None,
        repair_count: int,
        error_code: str | None = None,
    ) -> bool: ...

    async def fail_job(
        self,
        *,
        claimed: ClaimedCopyGenerationJob,
        error_code: str,
        retry_at: datetime | None,
        capability: str,
        provider_validation_issues: tuple[ProviderValidationIssue, ...] = (),
    ) -> bool: ...

    async def update_checkpoint(
        self,
        *,
        claimed: ClaimedCopyGenerationJob,
        stage: str,
        draft_version_id: UUID | None,
        issue_codes: tuple[str, ...] = (),
    ) -> bool: ...
