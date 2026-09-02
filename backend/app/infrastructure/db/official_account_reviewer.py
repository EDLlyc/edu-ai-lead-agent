from __future__ import annotations

import re
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.official_account_local import (
    ClaimedOfficialAccountRun,
    StoredOfficialAccountArticle,
)
from app.application.ports.official_account_reviewer import (
    OfficialAccountReviewerResult,
    OfficialAccountReviewRepository,
    ReviewArtifactBinding,
    ReviewExecutionBinding,
    StoredReviewIntent,
    StoredReviewRecord,
)
from app.application.services.official_account_reviewer import review_execution_scope
from app.domain.official_account_local import canonical_json
from app.domain.official_account_reviewer import (
    REVIEW_VERDICT_SCHEMA_VERSION,
    ReviewRequest,
    ReviewVerdict,
)
from app.infrastructure.db.models import (
    ExecutionAgentAllocationModel,
    ExecutionArtifactModel,
    ExecutionBudgetReservationModel,
    ExecutionTraceEventModel,
    OfficialAccountArticleRunModel,
    OfficialAccountArticleVersionModel,
    OfficialAccountReviewRecordModel,
    OfficialAccountReviewRequestModel,
)

_SAFE_ERROR = re.compile(r"^[a-z][a-z0-9_.:-]{0,79}$")
_ROOT_AGENT = "official.review.orchestrator"
_REVIEWER_AGENT = "official.reviewer.r1"
_REVIEWER_R2_AGENT = "official.reviewer.r2"
_REVIEWER_CAPABILITY = "official.article.review"


class PostgresOfficialAccountReviewRepository(OfficialAccountReviewRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_intent(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        article: StoredOfficialAccountArticle,
        contract: ReviewRequest,
        artifacts: ReviewArtifactBinding,
        provider: str,
        model: str,
    ) -> StoredReviewIntent:
        if contract.identity.article_fingerprint != artifacts.article_sha256:
            raise ValueError("review Article contract and artifact SHA differ")
        intent_id = uuid4()
        statement = (
            insert(OfficialAccountReviewRequestModel)
            .values(
                id=intent_id,
                run_id=claimed.run_id,
                article_version_id=article.id,
                attempt_number=claimed.attempt_number,
                status="pending",
                request_fingerprint=contract.request_fingerprint,
                article_sha256=artifacts.article_sha256,
                source_sha256=artifacts.source_sha256,
                brand_sha256=artifacts.brand_sha256,
                request_snapshot=contract.model_dump(mode="json"),
                provider=provider,
                model=model,
                reviewer_version=contract.reviewer_version,
                prompt_version=contract.prompt_version,
                request_schema_version=contract.schema_version,
                verdict_schema_version=REVIEW_VERDICT_SCHEMA_VERSION,
                rubric_version=contract.rubric_version,
                review_policy_version=contract.review_policy_version,
                repair_policy_version=contract.repair_policy_version,
                article_artifact_id=artifacts.article_artifact_id,
                source_artifact_id=artifacts.source_artifact_id,
                brand_artifact_id=artifacts.brand_artifact_id,
            )
            .on_conflict_do_nothing(constraint="uq_official_review_requests_article")
            .returning(OfficialAccountReviewRequestModel.id)
        )
        async with self._session_factory() as session:
            await _assert_claim(session, claimed)
            await _assert_artifact_binding(session, claimed=claimed, artifacts=artifacts)
            inserted = await session.scalar(statement)
            row = await session.get(
                OfficialAccountReviewRequestModel,
                inserted or intent_id,
            )
            if row is None and inserted is None:
                row = await session.scalar(
                    select(OfficialAccountReviewRequestModel).where(
                        OfficialAccountReviewRequestModel.run_id == claimed.run_id,
                        OfficialAccountReviewRequestModel.article_version_id == article.id,
                    )
                )
            if row is None:
                raise RuntimeError("official-account review intent was not persisted")
            _assert_intent_compatible(
                row,
                contract=contract,
                artifacts=artifacts,
                provider=provider,
                model=model,
            )
            await session.commit()
            return _stored_intent(row)

    async def mark_calling(
        self,
        *,
        intent: StoredReviewIntent,
        execution: ReviewExecutionBinding,
    ) -> StoredReviewIntent:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(OfficialAccountReviewRequestModel)
                .where(OfficialAccountReviewRequestModel.id == intent.id)
                .with_for_update()
            )
            if row is None:
                raise RuntimeError("official-account review intent is unavailable")
            await _assert_execution_binding(session, row, execution)
            if row.status == "pending":
                row.status = "calling"
                row.execution_run_id = execution.execution_run_id
                row.execution_task_id = execution.task_id
                row.reviewer_agent_id = execution.reviewer_agent_id
                row.reviewer_parent_event_id = execution.reviewer_parent_event_id
                row.reservation_id = execution.reservation_id
                row.request_event_id = execution.request_event_id
                row.calling_at = datetime.now(UTC)
            elif row.status == "calling":
                if _execution_binding(row) != execution:
                    raise RuntimeError("official-account review calling identity changed")
            else:
                raise RuntimeError("official-account review intent is already terminal")
            await session.commit()
            return _stored_intent(row)

    async def mark_result_unknown(
        self,
        *,
        intent: StoredReviewIntent,
        error_code: str,
    ) -> StoredReviewIntent:
        safe_error = error_code if _SAFE_ERROR.fullmatch(error_code) else "review_result_unknown"
        async with self._session_factory() as session:
            row = await session.scalar(
                select(OfficialAccountReviewRequestModel)
                .where(OfficialAccountReviewRequestModel.id == intent.id)
                .with_for_update()
            )
            if row is None:
                raise RuntimeError("official-account review intent is unavailable")
            if row.status == "calling":
                row.status = "result_unknown"
                row.error_code = safe_error
                row.completed_at = datetime.now(UTC)
            elif row.status == "result_unknown" and row.error_code != safe_error:
                raise RuntimeError("official-account review result-unknown replay changed")
            elif row.status != "result_unknown":
                raise RuntimeError("official-account review intent cannot become unknown")
            await session.commit()
            return _stored_intent(row)

    async def persist_record(
        self,
        *,
        intent: StoredReviewIntent,
        result: OfficialAccountReviewerResult,
        execution_artifact_id: UUID,
        execution_event_id: UUID,
    ) -> StoredReviewRecord:
        verdict = result.verdict
        if (
            result.provider != intent.provider
            or result.model != intent.model
            or verdict.request_fingerprint != intent.contract.request_fingerprint
        ):
            raise ValueError("official-account Reviewer result identity changed")
        record_id = uuid4()
        statement = (
            insert(OfficialAccountReviewRecordModel)
            .values(
                id=record_id,
                request_id=intent.id,
                run_id=intent.run_id,
                article_version_id=intent.article_version_id,
                decision=verdict.decision.value,
                record_fingerprint=verdict.record_fingerprint,
                issue_snapshot=[item.model_dump(mode="json") for item in verdict.issues],
                unavailable_reason=(
                    verdict.unavailable_reason.value
                    if verdict.unavailable_reason is not None
                    else None
                ),
                provider_request_id=result.provider_request_id,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                reasoning_tokens=result.reasoning_tokens,
                latency_ms=result.latency_ms,
                validation_corrections=result.validation_corrections,
                execution_artifact_id=execution_artifact_id,
                execution_event_id=execution_event_id,
            )
            .on_conflict_do_nothing(constraint="uq_official_review_records_request")
            .returning(OfficialAccountReviewRecordModel.id)
        )
        async with self._session_factory() as session:
            request_row = await session.scalar(
                select(OfficialAccountReviewRequestModel)
                .where(OfficialAccountReviewRequestModel.id == intent.id)
                .with_for_update()
            )
            if request_row is None or request_row.status not in {"calling", "completed"}:
                raise RuntimeError("official-account review intent is not recordable")
            if _execution_binding(request_row) != intent.execution_binding:
                raise RuntimeError("official-account review execution binding changed")
            await _assert_result_artifact(
                session,
                intent=intent,
                result=result,
                execution_artifact_id=execution_artifact_id,
                execution_event_id=execution_event_id,
            )
            inserted = await session.scalar(statement)
            row = await session.get(OfficialAccountReviewRecordModel, inserted or record_id)
            if row is None and inserted is None:
                row = await session.scalar(
                    select(OfficialAccountReviewRecordModel).where(
                        OfficialAccountReviewRecordModel.request_id == intent.id
                    )
                )
            if row is None:
                raise RuntimeError("official-account review record was not persisted")
            stored = _stored_record(row, intent.contract)
            if (
                row.run_id != intent.run_id
                or row.article_version_id != intent.article_version_id
                or stored.verdict.record_fingerprint != verdict.record_fingerprint
                or stored.execution_artifact_id != execution_artifact_id
                or stored.execution_event_id != execution_event_id
                or stored.provider_request_id != result.provider_request_id
                or stored.prompt_tokens != result.prompt_tokens
                or stored.completion_tokens != result.completion_tokens
                or stored.reasoning_tokens != result.reasoning_tokens
                or stored.latency_ms != result.latency_ms
                or stored.validation_corrections != result.validation_corrections
            ):
                raise RuntimeError("official-account review record replay changed")
            request_row.status = "completed"
            request_row.completed_at = request_row.completed_at or datetime.now(UTC)
            await session.commit()
            return stored

    async def get_record(self, request_id: UUID) -> StoredReviewRecord | None:
        async with self._session_factory() as session:
            request_row = await session.get(OfficialAccountReviewRequestModel, request_id)
            if request_row is None:
                return None
            row = await session.scalar(
                select(OfficialAccountReviewRecordModel).where(
                    OfficialAccountReviewRecordModel.request_id == request_id
                )
            )
            if row is None:
                return None
            return _stored_record(row, _review_request(request_row))


async def _assert_claim(session: AsyncSession, claimed: ClaimedOfficialAccountRun) -> None:
    row = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
    if (
        row is None
        or row.status != "running"
        or row.lease_token != claimed.lease_token
        or row.attempt_count != claimed.attempt_number
    ):
        raise RuntimeError("official-account review lease was lost")


async def _assert_artifact_binding(
    session: AsyncSession,
    *,
    claimed: ClaimedOfficialAccountRun,
    artifacts: ReviewArtifactBinding,
) -> None:
    expected = (
        (artifacts.article_artifact_id, artifacts.article_sha256, "article"),
        (artifacts.source_artifact_id, artifacts.source_sha256, "other"),
        (artifacts.brand_artifact_id, artifacts.brand_sha256, "other"),
    )
    rows: list[ExecutionArtifactModel] = []
    for artifact_id, artifact_sha256, kind in expected:
        artifact = await session.get(ExecutionArtifactModel, artifact_id)
        if (
            artifact is None
            or artifact.sha256 != artifact_sha256
            or artifact.kind != kind
            or artifact.media_type != "application/json"
            or artifact.lifecycle_status != "active"
            or artifact.agent_id != _ROOT_AGENT
        ):
            raise RuntimeError("official-account review artifact binding is invalid")
        rows.append(artifact)
    expected_scope = review_execution_scope(claimed.run_id)
    scope = {(artifact.run_id, artifact.task_id) for artifact in rows}
    if scope != {expected_scope}:
        raise RuntimeError("official-account review artifacts cross execution scope")


async def _assert_execution_binding(
    session: AsyncSession,
    row: OfficialAccountReviewRequestModel,
    execution: ReviewExecutionBinding,
) -> None:
    article = await session.get(OfficialAccountArticleVersionModel, row.article_version_id)
    expected_agent = (
        _REVIEWER_R2_AGENT if article is not None and article.revision_no == 2 else _REVIEWER_AGENT
    )
    if execution.reviewer_agent_id != expected_agent:
        raise RuntimeError("official-account review agent identity changed")
    allocation = await session.get(
        ExecutionAgentAllocationModel,
        (
            execution.execution_run_id,
            execution.task_id,
            execution.reviewer_agent_id,
        ),
    )
    parent_event = await session.get(
        ExecutionTraceEventModel,
        execution.reviewer_parent_event_id,
    )
    request_event = await session.get(ExecutionTraceEventModel, execution.request_event_id)
    reservation = await session.get(
        ExecutionBudgetReservationModel,
        execution.reservation_id,
    )
    identity = (
        execution.execution_run_id,
        execution.task_id,
        execution.reviewer_agent_id,
    )
    if (
        allocation is None
        or (allocation.run_id, allocation.task_id, allocation.agent_id) != identity
        or allocation.role != "reviewer"
        or allocation.status != "running"
        or allocation.parent_agent_id != _ROOT_AGENT
        or parent_event is None
        or (parent_event.run_id, parent_event.task_id, parent_event.agent_id) != identity
        or parent_event.kind != "node_started"
        or parent_event.status != "started"
        or parent_event.target_name != _REVIEWER_CAPABILITY
        or request_event is None
        or (request_event.run_id, request_event.task_id, request_event.agent_id) != identity
        or request_event.kind != "model_requested"
        or request_event.status != "started"
        or request_event.parent_event_id != parent_event.id
        or request_event.target_name != _REVIEWER_CAPABILITY
        or reservation is None
        or (reservation.run_id, reservation.task_id, reservation.agent_id) != identity
        or reservation.status != "reserved"
    ):
        raise RuntimeError("official-account review execution binding is invalid")
    artifacts = [
        await session.get(ExecutionArtifactModel, artifact_id)
        for artifact_id in (
            row.article_artifact_id,
            row.source_artifact_id,
            row.brand_artifact_id,
        )
    ]
    if any(
        artifact is None
        or artifact.run_id != execution.execution_run_id
        or artifact.task_id != execution.task_id
        for artifact in artifacts
    ):
        raise RuntimeError("official-account review execution and artifacts differ")


async def _assert_result_artifact(
    session: AsyncSession,
    *,
    intent: StoredReviewIntent,
    result: OfficialAccountReviewerResult,
    execution_artifact_id: UUID,
    execution_event_id: UUID,
) -> None:
    binding = intent.execution_binding
    if binding is None:
        raise RuntimeError("official-account review result has no execution binding")
    artifact = await session.get(ExecutionArtifactModel, execution_artifact_id)
    event = await session.get(ExecutionTraceEventModel, execution_event_id)
    body = canonical_json(result.verdict).encode("utf-8")
    identity = (binding.execution_run_id, binding.task_id, binding.reviewer_agent_id)
    if (
        artifact is None
        or (artifact.run_id, artifact.task_id, artifact.agent_id) != identity
        or artifact.producer_event_id != execution_event_id
        or artifact.kind != "report"
        or artifact.media_type != "application/json"
        or artifact.byte_size != len(body)
        or artifact.sha256 != sha256(body).hexdigest()
        or artifact.lifecycle_status != "active"
        or event is None
        or (event.run_id, event.task_id, event.agent_id) != identity
        or event.kind != "artifact_produced"
        or event.status != "succeeded"
        or event.artifact_id != execution_artifact_id
    ):
        raise RuntimeError("official-account review result artifact is invalid")


def _assert_intent_compatible(
    row: OfficialAccountReviewRequestModel,
    *,
    contract: ReviewRequest,
    artifacts: ReviewArtifactBinding,
    provider: str,
    model: str,
) -> None:
    exact = (
        row.request_fingerprint == contract.request_fingerprint
        and row.request_snapshot == contract.model_dump(mode="json")
        and row.article_sha256 == artifacts.article_sha256
        and row.source_sha256 == artifacts.source_sha256
        and row.brand_sha256 == artifacts.brand_sha256
        and row.article_artifact_id == artifacts.article_artifact_id
        and row.source_artifact_id == artifacts.source_artifact_id
        and row.brand_artifact_id == artifacts.brand_artifact_id
        and row.provider == provider
        and row.model == model
        and row.reviewer_version == contract.reviewer_version
        and row.prompt_version == contract.prompt_version
        and row.request_schema_version == contract.schema_version
        and row.verdict_schema_version == REVIEW_VERDICT_SCHEMA_VERSION
        and row.rubric_version == contract.rubric_version
        and row.review_policy_version == contract.review_policy_version
        and row.repair_policy_version == contract.repair_policy_version
    )
    if not exact:
        raise RuntimeError("official-account review intent replay changed")


def _review_request(row: OfficialAccountReviewRequestModel) -> ReviewRequest:
    try:
        return ReviewRequest.model_validate(row.request_snapshot)
    except ValidationError:
        raise RuntimeError("stored official-account review request is invalid") from None


def _execution_binding(row: OfficialAccountReviewRequestModel) -> ReviewExecutionBinding | None:
    values = (
        row.execution_run_id,
        row.execution_task_id,
        row.reviewer_agent_id,
        row.reviewer_parent_event_id,
        row.reservation_id,
        row.request_event_id,
    )
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise RuntimeError("stored official-account review execution binding is invalid")
    return ReviewExecutionBinding(
        execution_run_id=row.execution_run_id,  # type: ignore[arg-type]
        task_id=row.execution_task_id,  # type: ignore[arg-type]
        reviewer_agent_id=row.reviewer_agent_id,  # type: ignore[arg-type]
        reviewer_parent_event_id=row.reviewer_parent_event_id,  # type: ignore[arg-type]
        reservation_id=row.reservation_id,  # type: ignore[arg-type]
        request_event_id=row.request_event_id,  # type: ignore[arg-type]
    )


def _stored_intent(row: OfficialAccountReviewRequestModel) -> StoredReviewIntent:
    return StoredReviewIntent(
        id=row.id,
        run_id=row.run_id,
        article_version_id=row.article_version_id,
        attempt_number=row.attempt_number,
        status=row.status,  # type: ignore[arg-type]
        contract=_review_request(row),
        artifact_binding=ReviewArtifactBinding(
            article_artifact_id=row.article_artifact_id,
            source_artifact_id=row.source_artifact_id,
            brand_artifact_id=row.brand_artifact_id,
            article_sha256=row.article_sha256,
            source_sha256=row.source_sha256,
            brand_sha256=row.brand_sha256,
        ),
        execution_binding=_execution_binding(row),
        provider=row.provider,
        model=row.model,
        created_at=row.created_at,
    )


def _stored_record(
    row: OfficialAccountReviewRecordModel,
    contract: ReviewRequest,
) -> StoredReviewRecord:
    payload = {
        "schema_version": "official-account-review-verdict-v1",
        "decision": row.decision,
        "request_id": contract.request_id,
        "request_fingerprint": contract.request_fingerprint,
        "article_ref": contract.identity.article_ref,
        "article_fingerprint": contract.identity.article_fingerprint,
        "reviewer_version": contract.reviewer_version,
        "prompt_version": contract.prompt_version,
        "rubric_version": contract.rubric_version,
        "review_policy_version": contract.review_policy_version,
        "repair_policy_version": contract.repair_policy_version,
        "issues": row.issue_snapshot,
        "unavailable_reason": row.unavailable_reason,
        "record_fingerprint": row.record_fingerprint,
    }
    try:
        verdict = ReviewVerdict.model_validate(payload)
    except ValidationError:
        raise RuntimeError("stored official-account review record is invalid") from None
    return StoredReviewRecord(
        id=row.id,
        request_id=row.request_id,
        verdict=verdict,
        provider_request_id=row.provider_request_id,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        reasoning_tokens=row.reasoning_tokens,
        latency_ms=row.latency_ms,
        validation_corrections=row.validation_corrections,
        execution_artifact_id=row.execution_artifact_id,
        execution_event_id=row.execution_event_id,
        created_at=row.created_at,
        contract=contract,
    )
