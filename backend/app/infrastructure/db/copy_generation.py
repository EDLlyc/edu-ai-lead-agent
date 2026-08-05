from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.copy_generation import (
    ClaimedCopyGenerationJob,
    CopyGenerationRepository,
    DraftAuditResult,
    DraftGenerationResult,
    StoredDraft,
)
from app.core.errors import (
    ConflictError,
    CopyGenerationLeaseLostError,
    NotFoundError,
    ProviderValidationIssue,
    provider_validation_issues_metadata,
)
from app.domain.copy_generation import (
    ActiveBrandContext,
    CopyJobStatus,
    CopyRunStatus,
    CopyVersionBundle,
    EligibleEvidence,
    LockedTopicContext,
)
from app.domain.value_objects import stable_key
from app.infrastructure.db.models import (
    ArticleOccurrenceModel,
    BrandChunkModel,
    BrandDocumentModel,
    BrandDocumentVersionModel,
    CandidateAnalysisModel,
    CopyAuditModel,
    CopyClaimBrandBindingModel,
    CopyClaimEvidenceBindingModel,
    CopyDraftClaimModel,
    CopyDraftVersionModel,
    CopyGenerationAttemptModel,
    CopyGenerationCheckpointModel,
    CopyGenerationJobModel,
    CopyGenerationRunModel,
    CopyIssueModel,
    CopyValidationResultModel,
    DailyTopicSelectionModel,
    EventClusterVersionModel,
    EventMembershipModel,
    EvidenceBindingModel,
    NormalizedArticleModel,
)
from app.schemas.copy_generation import AuditVerdict, CopyIssue, DraftClaim, MaterialDraft

_SAFE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,79}")


@dataclass(frozen=True, slots=True)
class CopyRunProjection:
    run: CopyGenerationRunModel
    drafts: tuple[StoredDraft, ...]


class PostgresCopyGenerationRepository(CopyGenerationRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def enqueue_for_daily_topic(
        self,
        *,
        business_date: date,
        timezone: str,
        scoring_profile: str,
        version_bundle: CopyVersionBundle,
        max_attempts: int = 3,
    ) -> UUID:
        async with self._session_factory() as session:
            selection = await session.scalar(
                select(DailyTopicSelectionModel).where(
                    DailyTopicSelectionModel.business_date == business_date,
                    DailyTopicSelectionModel.timezone == timezone,
                    DailyTopicSelectionModel.scoring_profile == scoring_profile,
                    DailyTopicSelectionModel.superseded_at.is_(None),
                )
            )
            if selection is None:
                raise NotFoundError("daily topic selection")
            return await _enqueue_selection(
                session,
                selection=selection,
                version_bundle=version_bundle,
                max_attempts=max_attempts,
            )

    async def reconcile_ready_topics(
        self,
        *,
        timezone: str,
        scoring_profile: str,
        version_bundle: CopyVersionBundle,
        limit: int = 20,
        max_attempts: int = 3,
    ) -> int:
        async with self._session_factory() as session:
            selections = tuple(
                (
                    await session.scalars(
                        select(DailyTopicSelectionModel)
                        .outerjoin(
                            CopyGenerationRunModel,
                            and_(
                                CopyGenerationRunModel.daily_topic_selection_id
                                == DailyTopicSelectionModel.id,
                                CopyGenerationRunModel.version_fingerprint
                                == version_bundle.fingerprint,
                            ),
                        )
                        .where(
                            DailyTopicSelectionModel.timezone == timezone,
                            DailyTopicSelectionModel.scoring_profile == scoring_profile,
                            DailyTopicSelectionModel.superseded_at.is_(None),
                            CopyGenerationRunModel.id.is_(None),
                        )
                        .order_by(DailyTopicSelectionModel.business_date)
                        .limit(limit)
                    )
                ).all()
            )
        created = 0
        for selection in selections:
            async with self._session_factory() as session:
                try:
                    await _enqueue_selection(
                        session,
                        selection=selection,
                        version_bundle=version_bundle,
                        max_attempts=max_attempts,
                    )
                    created += 1
                except ConflictError:
                    continue
        return created

    async def claim(
        self, *, worker_id: str, lease_seconds: int, max_attempts: int
    ) -> ClaimedCopyGenerationJob | None:
        async with self._session_factory() as session:
            return await _claim(
                session,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
            )

    async def heartbeat(self, *, claimed: ClaimedCopyGenerationJob, lease_seconds: int) -> bool:
        async with self._session_factory() as session:
            now = datetime.now(UTC)
            result = cast(
                CursorResult[object],
                await session.execute(
                    update(CopyGenerationJobModel)
                    .where(
                        CopyGenerationJobModel.id == claimed.job_id,
                        CopyGenerationJobModel.run_id == claimed.run_id,
                        CopyGenerationJobModel.lease_token == claimed.lease_token,
                        CopyGenerationJobModel.status == CopyJobStatus.RUNNING.value,
                        CopyGenerationJobModel.lease_expires_at >= now,
                    )
                    .values(
                        heartbeat_at=now,
                        lease_expires_at=now + timedelta(seconds=lease_seconds),
                    )
                ),
            )
            if not result.rowcount:
                await session.rollback()
                return False
            await session.commit()
            return True

    async def load_topic_context(self, claimed: ClaimedCopyGenerationJob) -> LockedTopicContext:
        async with self._session_factory() as session:
            await _require_fenced_job(session, claimed)
            run = await session.get(CopyGenerationRunModel, claimed.run_id)
            if run is None:
                raise NotFoundError("copy generation run")
            if run.decision_kind == "no_topic":
                return LockedTopicContext(
                    daily_topic_selection_id=run.daily_topic_selection_id,
                    topic_selection_run_id=run.topic_selection_run_id,
                    business_date=run.business_date,
                    timezone=run.timezone,
                    scoring_profile=run.scoring_profile,
                    decision_kind=run.decision_kind,
                    selected_event_id=None,
                    selected_event_version_id=None,
                    no_topic_code=run.no_topic_code,
                    title=None,
                    summary=None,
                    evidence=(),
                )
            if run.selected_event_version_id is None or run.selected_event_id is None:
                raise RuntimeError("selected copy run is missing its locked event/version")
            version = await session.get(EventClusterVersionModel, run.selected_event_version_id)
            if version is None or version.event_id != run.selected_event_id:
                raise RuntimeError("locked event version is unavailable")
            evidence = await _load_evidence(session, version)
            raw_summary = version.summary_projection.get("summary")
            return LockedTopicContext(
                daily_topic_selection_id=run.daily_topic_selection_id,
                topic_selection_run_id=run.topic_selection_run_id,
                business_date=run.business_date,
                timezone=run.timezone,
                scoring_profile=run.scoring_profile,
                decision_kind=run.decision_kind,
                selected_event_id=run.selected_event_id,
                selected_event_version_id=run.selected_event_version_id,
                no_topic_code=None,
                title=version.representative_title,
                summary=raw_summary if isinstance(raw_summary, str) else None,
                evidence=evidence,
            )

    async def load_drafts(self, claimed: ClaimedCopyGenerationJob) -> tuple[StoredDraft, ...]:
        async with self._session_factory() as session:
            await _require_fenced_job(session, claimed)
            return await _load_stored_drafts(session, claimed.run_id)

    async def load_brand_context_for_draft(
        self, *, claimed: ClaimedCopyGenerationJob, draft: StoredDraft
    ) -> tuple[ActiveBrandContext, ...]:
        async with self._session_factory() as session:
            await _require_fenced_job(session, claimed)
            attempt = await session.scalar(
                select(CopyGenerationAttemptModel).where(
                    CopyGenerationAttemptModel.job_id == claimed.job_id,
                    CopyGenerationAttemptModel.draft_version_id == draft.id,
                    CopyGenerationAttemptModel.capability == "generation",
                    CopyGenerationAttemptModel.status == "succeeded",
                )
            )
            if attempt is None:
                return ()
            raw_ids = attempt.safe_metadata.get("brand_chunk_ids")
            if not isinstance(raw_ids, list) or not raw_ids:
                return ()
            try:
                ordered_ids = tuple(UUID(value) for value in raw_ids if isinstance(value, str))
            except ValueError:
                return ()
            if len(ordered_ids) != len(raw_ids) or len(set(ordered_ids)) != len(ordered_ids):
                return ()
            rows = tuple(
                (
                    await session.execute(
                        select(
                            BrandChunkModel,
                            BrandDocumentVersionModel,
                            BrandDocumentModel,
                        )
                        .join(
                            BrandDocumentVersionModel,
                            BrandDocumentVersionModel.id == BrandChunkModel.version_id,
                        )
                        .join(
                            BrandDocumentModel,
                            BrandDocumentModel.id == BrandDocumentVersionModel.document_id,
                        )
                        .where(BrandChunkModel.id.in_(ordered_ids))
                    )
                ).tuples()
            )
            by_id = {
                chunk.id: ActiveBrandContext(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    version_id=version.id,
                    document_title=document.title,
                    document_kind=document.document_kind,
                    text=chunk.text,
                    tone_tags=tuple(version.tone_tags),
                    safety_tags=tuple(version.safety_tags),
                    visual_tags=tuple(version.visual_tags),
                )
                for chunk, version, document in rows
            }
            if set(by_id) != set(ordered_ids):
                return ()
            return tuple(by_id[chunk_id] for chunk_id in ordered_ids)

    async def persist_no_topic(self, claimed: ClaimedCopyGenerationJob) -> bool:
        async with self._session_factory() as session:
            job = await _locked_fenced_job(session, claimed)
            if job is None:
                return False
            run = await session.get(CopyGenerationRunModel, claimed.run_id)
            if run is None or run.decision_kind != "no_topic":
                raise RuntimeError("no-topic completion requires a locked no-topic run")
            now = datetime.now(UTC)
            run.status = CopyRunStatus.NO_TOPIC.value
            run.error_code = run.no_topic_code
            run.completed_at = now
            job.status = CopyJobStatus.SUCCEEDED.value
            job.completed_at = now
            _clear_lease(job)
            await _upsert_checkpoint(
                session,
                run_id=run.id,
                stage="no_topic",
                draft_version_id=None,
                issue_codes=(run.no_topic_code,) if run.no_topic_code else (),
            )
            await session.commit()
            return True

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
    ) -> StoredDraft | None:
        version_bundle = claimed.version_bundle
        async with self._session_factory() as session:
            job = await _locked_fenced_job(session, claimed)
            if job is None:
                return None
            existing = await session.scalar(
                select(CopyDraftVersionModel).where(
                    CopyDraftVersionModel.run_id == claimed.run_id,
                    CopyDraftVersionModel.version == draft_version,
                )
            )
            if existing is not None:
                await session.commit()
                return await _load_stored_draft_with_new_session(
                    self._session_factory, claimed.run_id, draft_version
                )
            draft_id = uuid4()
            validation_passed = not any(issue.severity == "error" for issue in validation_issues)
            allowed_brand_chunk_ids = {item.chunk_id for item in brand_context}
            session.add(
                CopyDraftVersionModel(
                    id=draft_id,
                    run_id=claimed.run_id,
                    version=draft_version,
                    repair_of_version_id=repair_of_version_id,
                    copywriting=result.draft.copywriting,
                    parent_takeaway=result.draft.parent_takeaway,
                    interaction=result.draft.interaction,
                    source_note=result.draft.source_note,
                    image_prompt=result.draft.image_prompt,
                    provider=result.provider,
                    model=result.model,
                    request_fingerprint=result.request_fingerprint,
                    provider_request_id=result.provider_request_id,
                    prompt_version=version_bundle.generator_prompt_version,
                    schema_version=version_bundle.draft_schema_version,
                    rule_version=version_bundle.rule_version,
                    validation_passed=validation_passed,
                    audit_accepted=None,
                )
            )
            await session.flush()
            for ordinal, claim in enumerate(result.draft.claims):
                claim_id = uuid4()
                session.add(
                    CopyDraftClaimModel(
                        id=claim_id,
                        draft_version_id=draft_id,
                        claim_key=claim.id,
                        ordinal=ordinal,
                        kind=claim.kind,
                        text=claim.text,
                    )
                )
                await session.flush()
                for evidence_id in claim.evidence_ids:
                    evidence = evidence_by_id.get(evidence_id)
                    if evidence is None:
                        continue
                    session.add(
                        CopyClaimEvidenceBindingModel(
                            id=uuid4(),
                            claim_id=claim_id,
                            evidence_binding_id=evidence.evidence_id,
                            candidate_id=evidence.candidate_id,
                            passage_id=evidence.passage_id,
                            occurrence_id=evidence.occurrence_id,
                            snapshot_id=evidence.snapshot_id,
                            source_url=evidence.source_url,
                            source_tier=evidence.source_tier,
                            published_at=evidence.published_at,
                            exact_quote=evidence.exact_quote,
                        )
                    )
                for brand_chunk_id in claim.brand_chunk_ids:
                    if brand_chunk_id not in allowed_brand_chunk_ids:
                        continue
                    session.add(
                        CopyClaimBrandBindingModel(
                            id=uuid4(),
                            claim_id=claim_id,
                            brand_chunk_id=brand_chunk_id,
                        )
                    )
            validation_fingerprint = stable_key(
                draft_id,
                version_bundle.rule_version,
                *(f"{issue.code}:{issue.field}:{issue.claim_id}" for issue in validation_issues),
            )
            session.add(
                CopyValidationResultModel(
                    id=uuid4(),
                    draft_version_id=draft_id,
                    passed=validation_passed,
                    rule_version=version_bundle.rule_version,
                    result_fingerprint=validation_fingerprint,
                )
            )
            _add_issues(
                session,
                draft_version_id=draft_id,
                stage="deterministic",
                issues=validation_issues,
            )
            session.add(
                CopyGenerationAttemptModel(
                    id=uuid4(),
                    job_id=job.id,
                    draft_version_id=draft_id,
                    capability="generation",
                    status="succeeded",
                    provider=result.provider,
                    model=result.model,
                    request_fingerprint=result.request_fingerprint,
                    provider_request_id=result.provider_request_id,
                    prompt_version=version_bundle.generator_prompt_version,
                    schema_version=version_bundle.draft_schema_version,
                    rule_version=version_bundle.rule_version,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    reasoning_tokens=result.reasoning_tokens,
                    latency_ms=result.latency_ms,
                    error_code=None,
                    safe_metadata={
                        "draft_version": draft_version,
                        "validation_corrections": result.validation_corrections,
                        "brand_chunk_ids": [str(item.chunk_id) for item in brand_context],
                    },
                    completed_at=datetime.now(UTC),
                )
            )
            await _upsert_checkpoint(
                session,
                run_id=claimed.run_id,
                stage="validated" if validation_passed else "validation_failed",
                draft_version_id=draft_id,
                issue_codes=tuple(issue.code for issue in validation_issues),
            )
            await session.commit()
        return await _load_stored_draft_with_new_session(
            self._session_factory, claimed.run_id, draft_version
        )

    async def persist_audit(
        self,
        *,
        claimed: ClaimedCopyGenerationJob,
        draft: StoredDraft,
        result: DraftAuditResult,
    ) -> StoredDraft | None:
        version_bundle = claimed.version_bundle
        async with self._session_factory() as session:
            job = await _locked_fenced_job(session, claimed)
            if job is None:
                return None
            stored = await session.get(CopyDraftVersionModel, draft.id)
            if stored is None or stored.run_id != claimed.run_id:
                raise RuntimeError("audit draft does not belong to the claimed run")
            existing = await session.scalar(
                select(CopyAuditModel).where(CopyAuditModel.draft_version_id == draft.id)
            )
            if existing is None:
                attempt_id = uuid4()
                session.add(
                    CopyGenerationAttemptModel(
                        id=attempt_id,
                        job_id=job.id,
                        draft_version_id=draft.id,
                        capability="audit",
                        status="succeeded",
                        provider=result.provider,
                        model=result.model,
                        request_fingerprint=result.request_fingerprint,
                        provider_request_id=result.provider_request_id,
                        prompt_version=version_bundle.auditor_prompt_version,
                        schema_version=version_bundle.audit_schema_version,
                        rule_version=version_bundle.rule_version,
                        prompt_tokens=result.prompt_tokens,
                        completion_tokens=result.completion_tokens,
                        reasoning_tokens=result.reasoning_tokens,
                        latency_ms=result.latency_ms,
                        error_code=None,
                        safe_metadata={
                            "accepted": result.verdict.accepted,
                            "validation_corrections": result.validation_corrections,
                        },
                        completed_at=datetime.now(UTC),
                    )
                )
                # Audit rows reference the invocation attempt without an ORM
                # relationship, so persist the parent before the child.
                await session.flush()
                audit_id = uuid4()
                audit_fingerprint = stable_key(
                    result.request_fingerprint,
                    result.verdict.accepted,
                    *(issue.code for issue in result.verdict.issues),
                )
                session.add(
                    CopyAuditModel(
                        id=audit_id,
                        draft_version_id=draft.id,
                        attempt_id=attempt_id,
                        accepted=result.verdict.accepted,
                        prompt_version=version_bundle.auditor_prompt_version,
                        schema_version=version_bundle.audit_schema_version,
                        rule_version=version_bundle.rule_version,
                        result_fingerprint=audit_fingerprint,
                    )
                )
                await session.flush()
                _add_issues(
                    session,
                    draft_version_id=draft.id,
                    stage="audit",
                    issues=result.verdict.issues,
                    audit_id=audit_id,
                )
                stored.audit_accepted = result.verdict.accepted
                await _upsert_checkpoint(
                    session,
                    run_id=claimed.run_id,
                    stage="audit_accepted" if result.verdict.accepted else "audit_rejected",
                    draft_version_id=draft.id,
                    issue_codes=tuple(issue.code for issue in result.verdict.issues),
                )
            await session.commit()
        return await _load_stored_draft_with_new_session(
            self._session_factory, claimed.run_id, draft.version
        )

    async def finish(
        self,
        *,
        claimed: ClaimedCopyGenerationJob,
        status: str,
        active_draft_version_id: UUID | None,
        repair_count: int,
        error_code: str | None = None,
        provider_validation_issues: tuple[ProviderValidationIssue, ...] | None = None,
    ) -> bool:
        if status not in {CopyRunStatus.ACCEPTED.value, CopyRunStatus.REVIEW_REQUIRED.value}:
            raise ValueError("copy finish status must be accepted or review_required")
        async with self._session_factory() as session:
            job = await _locked_fenced_job(session, claimed)
            if job is None:
                return False
            run = await session.get(CopyGenerationRunModel, claimed.run_id)
            if run is None:
                raise RuntimeError("copy generation run is missing")
            if status == CopyRunStatus.ACCEPTED.value:
                if active_draft_version_id is None:
                    raise ConflictError("accepted copy run requires an active draft")
                accepted_draft = await session.get(CopyDraftVersionModel, active_draft_version_id)
                if (
                    accepted_draft is None
                    or accepted_draft.run_id != run.id
                    or not accepted_draft.validation_passed
                    or accepted_draft.audit_accepted is not True
                ):
                    raise ConflictError(
                        "copy run can be accepted only after validation and audit pass"
                    )
            now = datetime.now(UTC)
            run.status = status
            run.active_draft_version_id = active_draft_version_id
            run.repair_count = repair_count
            run.error_code = _safe_error(error_code)
            run.completed_at = now
            job.status = CopyJobStatus.SUCCEEDED.value
            job.error_code = run.error_code
            job.completed_at = now
            _clear_lease(job)
            if provider_validation_issues is not None:
                session.add(
                    CopyGenerationAttemptModel(
                        id=uuid4(),
                        job_id=job.id,
                        # A failed repair produced no draft. The active draft is the earlier
                        # review artifact and must not be attributed to this failed attempt.
                        draft_version_id=None,
                        capability="workflow",
                        status="failed",
                        provider=claimed.version_bundle.provider,
                        model=claimed.version_bundle.model,
                        request_fingerprint=stable_key(
                            claimed.run_id,
                            claimed.attempt_number,
                            "review_required",
                            run.error_code or "copy_generation_failed",
                        ),
                        provider_request_id=None,
                        prompt_version=claimed.version_bundle.generator_prompt_version,
                        schema_version=claimed.version_bundle.draft_schema_version,
                        rule_version=claimed.version_bundle.rule_version,
                        prompt_tokens=0,
                        completion_tokens=0,
                        reasoning_tokens=0,
                        latency_ms=0,
                        error_code=run.error_code,
                        safe_metadata={
                            "provider_validation_issues": provider_validation_issues_metadata(
                                provider_validation_issues
                            )
                        },
                        completed_at=now,
                    )
                )
            await _upsert_checkpoint(
                session,
                run_id=run.id,
                stage=status,
                draft_version_id=active_draft_version_id,
                issue_codes=(run.error_code,) if run.error_code else (),
            )
            await session.commit()
            return True

    async def fail_job(
        self,
        *,
        claimed: ClaimedCopyGenerationJob,
        error_code: str,
        retry_at: datetime | None,
        capability: str,
        provider_validation_issues: tuple[ProviderValidationIssue, ...] = (),
    ) -> bool:
        async with self._session_factory() as session:
            job = await _locked_fenced_job(session, claimed)
            if job is None:
                return False
            run = await session.get(CopyGenerationRunModel, claimed.run_id)
            if run is None:
                raise RuntimeError("copy generation run is missing")
            safe_error = _safe_error(error_code) or "copy_generation_failed"
            now = datetime.now(UTC)
            retrying = retry_at is not None
            job.status = (
                CopyJobStatus.RETRY_SCHEDULED.value if retrying else CopyJobStatus.FAILED.value
            )
            job.available_at = retry_at or now
            job.error_code = safe_error
            job.completed_at = None if retrying else now
            _clear_lease(job)
            run.status = CopyRunStatus.QUEUED.value if retrying else CopyRunStatus.FAILED.value
            run.error_code = safe_error
            run.completed_at = None if retrying else now
            safe_metadata: dict[str, object] = {"retry_scheduled": retrying}
            if provider_validation_issues:
                safe_metadata["provider_validation_issues"] = provider_validation_issues_metadata(
                    provider_validation_issues
                )
            session.add(
                CopyGenerationAttemptModel(
                    id=uuid4(),
                    job_id=job.id,
                    draft_version_id=None,
                    capability="workflow",
                    status="failed",
                    provider=claimed.version_bundle.provider,
                    model=claimed.version_bundle.model,
                    request_fingerprint=stable_key(
                        claimed.run_id,
                        claimed.attempt_number,
                        capability,
                        safe_error,
                    ),
                    provider_request_id=None,
                    prompt_version=claimed.version_bundle.generator_prompt_version,
                    schema_version=claimed.version_bundle.draft_schema_version,
                    rule_version=claimed.version_bundle.rule_version,
                    prompt_tokens=0,
                    completion_tokens=0,
                    reasoning_tokens=0,
                    latency_ms=0,
                    error_code=safe_error,
                    safe_metadata=safe_metadata,
                    completed_at=now,
                )
            )
            await _upsert_checkpoint(
                session,
                run_id=run.id,
                stage="retry_scheduled" if retrying else "failed",
                draft_version_id=run.active_draft_version_id,
                issue_codes=(safe_error,),
            )
            await session.commit()
            return True

    async def update_checkpoint(
        self,
        *,
        claimed: ClaimedCopyGenerationJob,
        stage: str,
        draft_version_id: UUID | None,
        issue_codes: tuple[str, ...] = (),
    ) -> bool:
        async with self._session_factory() as session:
            if await _locked_fenced_job(session, claimed) is None:
                return False
            await _upsert_checkpoint(
                session,
                run_id=claimed.run_id,
                stage=stage,
                draft_version_id=draft_version_id,
                issue_codes=issue_codes,
            )
            await session.commit()
            return True


async def _enqueue_selection(
    session: AsyncSession,
    *,
    selection: DailyTopicSelectionModel,
    version_bundle: CopyVersionBundle,
    max_attempts: int = 3,
) -> UUID:
    selection_id = selection.id
    selection_run_id = selection.run_id
    selection_business_date = selection.business_date
    selection_timezone = selection.timezone
    selection_profile = selection.scoring_profile
    selection_decision_kind = selection.decision_kind
    selected_event_id = selection.selected_event_id
    selected_event_version_id = selection.selected_event_version_id
    no_topic_code = selection.no_topic_code
    existing = await session.scalar(
        select(CopyGenerationRunModel).where(
            CopyGenerationRunModel.daily_topic_selection_id == selection_id,
            CopyGenerationRunModel.version_fingerprint == version_bundle.fingerprint,
        )
    )
    if existing is not None:
        if (
            existing.status == CopyRunStatus.REVIEW_REQUIRED.value
            and existing.error_code == "missing_brand_context"
            and existing.active_draft_version_id is None
        ):
            job = await session.scalar(
                select(CopyGenerationJobModel)
                .where(CopyGenerationJobModel.run_id == existing.id)
                .with_for_update()
            )
            if job is not None and job.attempt_count < max_attempts:
                now = datetime.now(UTC)
                existing.status = CopyRunStatus.QUEUED.value
                existing.error_code = None
                existing.started_at = None
                existing.completed_at = None
                job.status = CopyJobStatus.QUEUED.value
                job.available_at = now
                job.error_code = None
                job.started_at = None
                job.completed_at = None
                _clear_lease(job)
                await _upsert_checkpoint(
                    session,
                    run_id=existing.id,
                    stage="queued",
                    draft_version_id=None,
                    issue_codes=(),
                )
                await session.commit()
        return existing.id
    run_id = uuid4()
    try:
        run = CopyGenerationRunModel(
            id=run_id,
            daily_topic_selection_id=selection_id,
            topic_selection_run_id=selection_run_id,
            business_date=selection_business_date,
            timezone=selection_timezone,
            scoring_profile=selection_profile,
            decision_kind=selection_decision_kind,
            selected_event_id=selected_event_id,
            selected_event_version_id=selected_event_version_id,
            no_topic_code=no_topic_code,
            status=CopyRunStatus.QUEUED.value,
            pipeline_version=version_bundle.pipeline_version,
            version_fingerprint=version_bundle.fingerprint,
            version_bundle=version_bundle.as_metadata(),
            active_draft_version_id=None,
            repair_count=0,
            error_code=None,
        )
        session.add(run)
        # No ORM relationships own insert ordering. Flush the parent before
        # adding the durable job/checkpoint children.
        await session.flush()
        session.add(
            CopyGenerationJobModel(
                id=uuid4(),
                run_id=run_id,
                status=CopyJobStatus.QUEUED.value,
                attempt_count=0,
            )
        )
        session.add(
            CopyGenerationCheckpointModel(
                run_id=run_id,
                stage="queued",
                draft_version_id=None,
                issue_codes=[],
            )
        )
        await session.commit()
        return run_id
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(CopyGenerationRunModel).where(
                CopyGenerationRunModel.daily_topic_selection_id == selection_id,
                CopyGenerationRunModel.version_fingerprint == version_bundle.fingerprint,
            )
        )
        if existing is not None:
            return cast(UUID, existing.id)
        raise ConflictError("copy generation run changed concurrently; retry") from None


async def _claim(
    session: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: int,
    max_attempts: int,
) -> ClaimedCopyGenerationJob | None:
    now = datetime.now(UTC)
    stale_jobs = tuple(
        (
            await session.scalars(
                select(CopyGenerationJobModel)
                .where(
                    CopyGenerationJobModel.status == CopyJobStatus.RUNNING.value,
                    CopyGenerationJobModel.lease_expires_at < now,
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for stale in stale_jobs:
        terminal = stale.attempt_count >= max_attempts
        stale.status = (
            CopyJobStatus.FAILED.value if terminal else CopyJobStatus.RETRY_SCHEDULED.value
        )
        stale.available_at = now
        stale.error_code = "lease_expired"
        stale.completed_at = now if terminal else None
        _clear_lease(stale)
        run = await session.get(CopyGenerationRunModel, stale.run_id)
        if run is not None:
            run.status = CopyRunStatus.FAILED.value if terminal else CopyRunStatus.QUEUED.value
            run.error_code = "lease_expired"
            run.completed_at = now if terminal else None
    job = await session.scalar(
        select(CopyGenerationJobModel)
        .where(
            CopyGenerationJobModel.status.in_(
                [CopyJobStatus.QUEUED.value, CopyJobStatus.RETRY_SCHEDULED.value]
            ),
            CopyGenerationJobModel.available_at <= now,
            CopyGenerationJobModel.attempt_count < max_attempts,
        )
        .order_by(CopyGenerationJobModel.available_at, CopyGenerationJobModel.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        await session.commit()
        return None
    lease_token = uuid4()
    job.status = CopyJobStatus.RUNNING.value
    job.attempt_count += 1
    job.lease_owner = worker_id
    job.lease_token = lease_token
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.heartbeat_at = now
    job.started_at = job.started_at or now
    job.error_code = None
    run = await session.get(CopyGenerationRunModel, job.run_id)
    if run is None:
        raise RuntimeError("copy generation job run is missing")
    try:
        version_bundle = CopyVersionBundle.from_metadata(
            run.version_bundle,
            expected_fingerprint=run.version_fingerprint,
        )
    except ValueError as error:
        raise RuntimeError("copy generation run version bundle is invalid") from error
    if version_bundle.pipeline_version != run.pipeline_version:
        raise RuntimeError("copy generation run pipeline version is inconsistent")
    run.status = CopyRunStatus.RUNNING.value
    run.started_at = run.started_at or now
    run.error_code = None
    claimed = ClaimedCopyGenerationJob(
        job_id=job.id,
        run_id=job.run_id,
        attempt_number=job.attempt_count,
        lease_token=lease_token,
        version_bundle=version_bundle,
    )
    await session.commit()
    return claimed


async def _load_evidence(
    session: AsyncSession, version: EventClusterVersionModel
) -> tuple[EligibleEvidence, ...]:
    rows = tuple(
        (
            await session.execute(
                select(
                    EvidenceBindingModel,
                    ArticleOccurrenceModel,
                )
                .select_from(EventMembershipModel)
                .join(
                    NormalizedArticleModel,
                    NormalizedArticleModel.id == EventMembershipModel.normalized_article_id,
                )
                .join(
                    CandidateAnalysisModel,
                    CandidateAnalysisModel.normalized_article_id == NormalizedArticleModel.id,
                )
                .join(
                    EvidenceBindingModel,
                    EvidenceBindingModel.analysis_id == CandidateAnalysisModel.id,
                )
                .join(
                    ArticleOccurrenceModel,
                    ArticleOccurrenceModel.id == EvidenceBindingModel.occurrence_id,
                )
                .where(
                    EventMembershipModel.event_id == version.event_id,
                    EventMembershipModel.created_at <= version.created_at,
                    or_(
                        EventMembershipModel.active.is_(True),
                        EventMembershipModel.superseded_at > version.created_at,
                    ),
                    CandidateAnalysisModel.status == "accepted",
                    CandidateAnalysisModel.created_at <= version.created_at,
                    EvidenceBindingModel.validated.is_(True),
                    ArticleOccurrenceModel.trust_tier.in_(["A", "B"]),
                    ArticleOccurrenceModel.created_at <= version.created_at,
                )
                .order_by(
                    EvidenceBindingModel.statement_kind.desc(),
                    ArticleOccurrenceModel.source_display_name,
                    EvidenceBindingModel.id,
                )
                .limit(24)
            )
        ).tuples()
    )
    return tuple(
        EligibleEvidence(
            evidence_id=binding.id,
            candidate_id=binding.candidate_id,
            passage_id=binding.passage_id,
            occurrence_id=binding.occurrence_id,
            snapshot_id=binding.snapshot_id,
            source_name=occurrence.source_display_name,
            source_url=occurrence.final_url,
            source_tier=occurrence.trust_tier,
            published_at=occurrence.published_at,
            exact_quote=binding.exact_quote,
        )
        for binding, occurrence in rows
    )


async def _load_stored_draft_with_new_session(
    session_factory: async_sessionmaker[AsyncSession], run_id: UUID, version: int
) -> StoredDraft:
    async with session_factory() as session:
        drafts = await _load_stored_drafts(session, run_id)
    draft = next((item for item in drafts if item.version == version), None)
    if draft is None:
        raise RuntimeError("persisted copy draft could not be reloaded")
    return draft


async def _load_stored_drafts(session: AsyncSession, run_id: UUID) -> tuple[StoredDraft, ...]:
    versions = tuple(
        (
            await session.scalars(
                select(CopyDraftVersionModel)
                .where(CopyDraftVersionModel.run_id == run_id)
                .order_by(CopyDraftVersionModel.version)
            )
        ).all()
    )
    result: list[StoredDraft] = []
    for version in versions:
        claims = tuple(
            (
                await session.scalars(
                    select(CopyDraftClaimModel)
                    .where(CopyDraftClaimModel.draft_version_id == version.id)
                    .order_by(CopyDraftClaimModel.ordinal)
                )
            ).all()
        )
        draft_claims: list[DraftClaim] = []
        for claim in claims:
            evidence_ids = tuple(
                (
                    await session.scalars(
                        select(CopyClaimEvidenceBindingModel.evidence_binding_id)
                        .where(CopyClaimEvidenceBindingModel.claim_id == claim.id)
                        .order_by(CopyClaimEvidenceBindingModel.evidence_binding_id)
                    )
                ).all()
            )
            brand_ids = tuple(
                (
                    await session.scalars(
                        select(CopyClaimBrandBindingModel.brand_chunk_id)
                        .where(CopyClaimBrandBindingModel.claim_id == claim.id)
                        .order_by(CopyClaimBrandBindingModel.brand_chunk_id)
                    )
                ).all()
            )
            draft_claims.append(
                DraftClaim(
                    id=claim.claim_key,
                    text=claim.text,
                    kind=cast(Literal["external_fact", "brand_statement", "opinion"], claim.kind),
                    evidence_ids=evidence_ids,
                    brand_chunk_ids=brand_ids,
                )
            )
        deterministic_issues = await _load_issues(session, version.id, "deterministic")
        audit_model = await session.scalar(
            select(CopyAuditModel).where(CopyAuditModel.draft_version_id == version.id)
        )
        audit = None
        if audit_model is not None:
            audit = AuditVerdict(
                accepted=audit_model.accepted,
                issues=await _load_issues(session, version.id, "audit"),
            )
        result.append(
            StoredDraft(
                id=version.id,
                version=version.version,
                repair_of_version_id=version.repair_of_version_id,
                draft=MaterialDraft(
                    copywriting=version.copywriting,
                    parent_takeaway=version.parent_takeaway,
                    interaction=version.interaction,
                    source_note=version.source_note,
                    image_prompt=version.image_prompt,
                    claims=tuple(draft_claims),
                ),
                validation_issues=deterministic_issues,
                audit=audit,
                created_at=version.created_at,
            )
        )
    return tuple(result)


async def _load_issues(
    session: AsyncSession, draft_version_id: UUID, stage: str
) -> tuple[CopyIssue, ...]:
    rows = tuple(
        (
            await session.scalars(
                select(CopyIssueModel)
                .where(
                    CopyIssueModel.draft_version_id == draft_version_id,
                    CopyIssueModel.stage == stage,
                )
                .order_by(CopyIssueModel.ordinal)
            )
        ).all()
    )
    return tuple(
        CopyIssue(
            code=row.code,
            message=row.safe_message,
            severity=cast(Literal["warning", "error"], row.severity),
            field=row.field_name,
            claim_id=row.claim_key,
        )
        for row in rows
    )


def _add_issues(
    session: AsyncSession,
    *,
    draft_version_id: UUID,
    stage: str,
    issues: tuple[CopyIssue, ...],
    audit_id: UUID | None = None,
) -> None:
    for ordinal, issue in enumerate(issues):
        session.add(
            CopyIssueModel(
                id=uuid4(),
                draft_version_id=draft_version_id,
                stage=stage,
                audit_id=audit_id,
                ordinal=ordinal,
                code=issue.code,
                severity=issue.severity,
                field_name=issue.field,
                claim_key=issue.claim_id,
                safe_message=issue.message,
            )
        )


async def _require_fenced_job(
    session: AsyncSession, claimed: ClaimedCopyGenerationJob
) -> CopyGenerationJobModel:
    job = await _locked_fenced_job(session, claimed, lock=False)
    if job is None:
        raise CopyGenerationLeaseLostError()
    return job


async def _locked_fenced_job(
    session: AsyncSession,
    claimed: ClaimedCopyGenerationJob,
    *,
    lock: bool = True,
) -> CopyGenerationJobModel | None:
    now = datetime.now(UTC)
    statement = select(CopyGenerationJobModel).where(
        CopyGenerationJobModel.id == claimed.job_id,
        CopyGenerationJobModel.run_id == claimed.run_id,
        CopyGenerationJobModel.lease_token == claimed.lease_token,
        CopyGenerationJobModel.status == CopyJobStatus.RUNNING.value,
        CopyGenerationJobModel.lease_expires_at >= now,
    )
    if lock:
        statement = statement.with_for_update()
    return cast(CopyGenerationJobModel | None, await session.scalar(statement))


async def _upsert_checkpoint(
    session: AsyncSession,
    *,
    run_id: UUID,
    stage: str,
    draft_version_id: UUID | None,
    issue_codes: tuple[str, ...],
) -> None:
    statement = insert(CopyGenerationCheckpointModel).values(
        run_id=run_id,
        stage=stage[:40],
        draft_version_id=draft_version_id,
        issue_codes=list(issue_codes[:24]),
        updated_at=datetime.now(UTC),
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[CopyGenerationCheckpointModel.run_id],
            set_={
                "stage": statement.excluded.stage,
                "draft_version_id": statement.excluded.draft_version_id,
                "issue_codes": statement.excluded.issue_codes,
                "updated_at": statement.excluded.updated_at,
            },
        )
    )


def _clear_lease(job: CopyGenerationJobModel) -> None:
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    job.heartbeat_at = None


def _safe_error(value: str | None) -> str | None:
    if value is None:
        return None
    return value if _SAFE_ERROR_CODE.fullmatch(value) else "copy_generation_failed"


async def get_copy_generation_run(session: AsyncSession, run_id: UUID) -> CopyGenerationRunModel:
    run = await session.get(CopyGenerationRunModel, run_id)
    if run is None:
        raise NotFoundError("copy generation run")
    return run


async def get_copy_generation_projection(session: AsyncSession, run_id: UUID) -> CopyRunProjection:
    run = await get_copy_generation_run(session, run_id)
    return CopyRunProjection(run=run, drafts=await _load_stored_drafts(session, run_id))
