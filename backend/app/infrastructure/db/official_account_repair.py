from __future__ import annotations

import re
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.official_account_local import (
    ClaimedOfficialAccountRun,
    StoredOfficialAccountArticle,
)
from app.application.ports.official_account_reviewer import (
    OfficialAccountRepairRepository,
    RepairExecutionBinding,
    StoredRepairIntent,
    StoredReviewRecord,
)
from app.application.services.official_account_reviewer import review_execution_scope
from app.domain.official_account_local import canonical_json
from app.domain.official_account_reviewer import (
    REPAIR_POLICY_VERSION,
    RepairDirective,
    ReviewDecision,
)
from app.infrastructure.db.models import (
    ExecutionAgentAllocationModel,
    ExecutionBudgetReservationModel,
    ExecutionTraceEventModel,
    OfficialAccountArticleRunModel,
    OfficialAccountArticleVersionModel,
    OfficialAccountRepairRequestModel,
    OfficialAccountReviewRequestModel,
)

_SAFE_ERROR = re.compile(r"^[a-z][a-z0-9_.:-]{0,79}$")
_ROOT_AGENT = "official.review.orchestrator"
_REPAIR_AGENT = "official.writer.repair"
_REPAIR_CAPABILITY = "official.article.repair"
_DIRECTIVES = TypeAdapter(tuple[RepairDirective, ...])


class PostgresOfficialAccountRepairRepository(OfficialAccountRepairRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_intent(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        source_article: StoredOfficialAccountArticle,
        source_review: StoredReviewRecord,
        directives: tuple[RepairDirective, ...],
        request_fingerprint: str,
        provider: str,
        model: str,
    ) -> StoredRepairIntent:
        if (
            claimed.identity.reviewer_mode != "enforce"
            or source_article.revision_no != 1
            or source_article.repair_of_article_version_id is not None
            or source_review.verdict.decision is not ReviewDecision.REJECTED
            or not directives
            or len(directives) > 16
        ):
            raise ValueError("official-account repair source is not eligible")
        directive_snapshot = [item.model_dump(mode="json") for item in directives]
        directive_fingerprint = sha256(canonical_json(directive_snapshot).encode()).hexdigest()
        intent_id = uuid4()
        statement = (
            insert(OfficialAccountRepairRequestModel)
            .values(
                id=intent_id,
                run_id=claimed.run_id,
                source_article_version_id=source_article.id,
                repaired_article_version_id=None,
                source_review_request_id=source_review.request_id,
                attempt_number=claimed.attempt_number,
                status="pending",
                request_fingerprint=request_fingerprint,
                directive_fingerprint=directive_fingerprint,
                directive_snapshot=directive_snapshot,
                provider=provider,
                model=model,
                repair_policy_version=REPAIR_POLICY_VERSION,
            )
            .on_conflict_do_nothing(constraint="uq_official_account_repair_requests_run")
            .returning(OfficialAccountRepairRequestModel.id)
        )
        async with self._session_factory() as session:
            await _assert_claim(session, claimed)
            review_request = await session.get(
                OfficialAccountReviewRequestModel, source_review.request_id
            )
            if (
                review_request is None
                or review_request.run_id != claimed.run_id
                or review_request.article_version_id != source_article.id
                or review_request.status != "completed"
            ):
                raise RuntimeError("official-account repair review lineage is invalid")
            inserted = await session.scalar(statement)
            row = await session.get(OfficialAccountRepairRequestModel, inserted or intent_id)
            if row is None and inserted is None:
                row = await session.scalar(
                    select(OfficialAccountRepairRequestModel).where(
                        OfficialAccountRepairRequestModel.run_id == claimed.run_id
                    )
                )
            if row is None:
                raise RuntimeError("official-account repair intent was not persisted")
            if (
                row.source_article_version_id != source_article.id
                or row.source_review_request_id != source_review.request_id
                or row.request_fingerprint != request_fingerprint
                or row.directive_fingerprint != directive_fingerprint
                or row.directive_snapshot != directive_snapshot
                or row.provider != provider
                or row.model != model
                or row.repair_policy_version != REPAIR_POLICY_VERSION
            ):
                raise RuntimeError("official-account repair intent replay changed")
            await session.commit()
            return _stored_intent(row)

    async def mark_calling(
        self,
        *,
        intent: StoredRepairIntent,
        execution: RepairExecutionBinding,
    ) -> StoredRepairIntent:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(OfficialAccountRepairRequestModel)
                .where(OfficialAccountRepairRequestModel.id == intent.id)
                .with_for_update()
            )
            if row is None:
                raise RuntimeError("official-account repair intent is unavailable")
            await _assert_execution_binding(session, row, execution)
            if row.status == "pending":
                row.status = "calling"
                row.execution_run_id = execution.execution_run_id
                row.execution_task_id = execution.task_id
                row.writer_agent_id = execution.writer_agent_id
                row.writer_parent_event_id = execution.writer_parent_event_id
                row.reservation_id = execution.reservation_id
                row.request_event_id = execution.request_event_id
                row.calling_at = datetime.now(UTC)
            elif row.status == "calling" and _execution_binding(row) != execution:
                raise RuntimeError("official-account repair calling identity changed")
            elif row.status != "calling":
                raise RuntimeError("official-account repair intent is already terminal")
            await session.commit()
            return _stored_intent(row)

    async def mark_completed(
        self,
        *,
        intent: StoredRepairIntent,
        repaired_article: StoredOfficialAccountArticle,
    ) -> StoredRepairIntent:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(OfficialAccountRepairRequestModel)
                .where(OfficialAccountRepairRequestModel.id == intent.id)
                .with_for_update()
            )
            article = await session.get(OfficialAccountArticleVersionModel, repaired_article.id)
            if (
                row is None
                or article is None
                or article.run_id != row.run_id
                or article.revision_no != 2
                or article.repair_of_article_version_id != row.source_article_version_id
            ):
                raise RuntimeError("official-account repaired Article lineage is invalid")
            if row.status == "calling":
                row.status = "completed"
                row.repaired_article_version_id = article.id
                row.completed_at = datetime.now(UTC)
            elif row.status == "completed" and row.repaired_article_version_id != article.id:
                raise RuntimeError("official-account repair completion replay changed")
            elif row.status != "completed":
                raise RuntimeError("official-account repair intent cannot complete")
            await session.commit()
            return _stored_intent(row)

    async def mark_result_unknown(
        self,
        *,
        intent: StoredRepairIntent,
        error_code: str,
    ) -> StoredRepairIntent:
        safe_error = error_code if _SAFE_ERROR.fullmatch(error_code) else "repair_result_unknown"
        async with self._session_factory() as session:
            row = await session.scalar(
                select(OfficialAccountRepairRequestModel)
                .where(OfficialAccountRepairRequestModel.id == intent.id)
                .with_for_update()
            )
            if row is None:
                raise RuntimeError("official-account repair intent is unavailable")
            if row.status == "calling":
                row.status = "result_unknown"
                row.error_code = safe_error
                row.completed_at = datetime.now(UTC)
            elif row.status == "result_unknown" and row.error_code != safe_error:
                raise RuntimeError("official-account repair result-unknown replay changed")
            elif row.status != "result_unknown":
                raise RuntimeError("official-account repair intent cannot become unknown")
            await session.commit()
            return _stored_intent(row)


async def _assert_claim(session: AsyncSession, claimed: ClaimedOfficialAccountRun) -> None:
    run = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
    if (
        run is None
        or run.status != "running"
        or run.lease_token != claimed.lease_token
        or run.attempt_count != claimed.attempt_number
        or run.version_bundle.get("reviewer_mode") != "enforce"
    ):
        raise RuntimeError("official-account repair business lease is stale")


async def _assert_execution_binding(
    session: AsyncSession,
    row: OfficialAccountRepairRequestModel,
    execution: RepairExecutionBinding,
) -> None:
    if execution.writer_agent_id != _REPAIR_AGENT:
        raise RuntimeError("official-account repair Writer identity changed")
    expected_run_id, expected_task_id = review_execution_scope(row.run_id)
    identity = (execution.execution_run_id, execution.task_id, execution.writer_agent_id)
    allocation = await session.get(ExecutionAgentAllocationModel, identity)
    parent = await session.get(ExecutionTraceEventModel, execution.writer_parent_event_id)
    requested = await session.get(ExecutionTraceEventModel, execution.request_event_id)
    reservation = await session.get(ExecutionBudgetReservationModel, execution.reservation_id)
    if (
        (execution.execution_run_id, execution.task_id) != (expected_run_id, expected_task_id)
        or allocation is None
        or allocation.role != "worker"
        or allocation.status != "running"
        or allocation.parent_agent_id != _ROOT_AGENT
        or parent is None
        or (parent.run_id, parent.task_id, parent.agent_id) != identity
        or parent.kind != "node_started"
        or parent.status != "started"
        or parent.target_name != _REPAIR_CAPABILITY
        or requested is None
        or (requested.run_id, requested.task_id, requested.agent_id) != identity
        or requested.kind != "model_requested"
        or requested.status != "started"
        or requested.parent_event_id != parent.id
        or requested.target_name != _REPAIR_CAPABILITY
        or reservation is None
        or (reservation.run_id, reservation.task_id, reservation.agent_id) != identity
        or reservation.status != "reserved"
    ):
        raise RuntimeError("official-account repair execution binding is invalid")


def _execution_binding(row: OfficialAccountRepairRequestModel) -> RepairExecutionBinding | None:
    values = (
        row.execution_run_id,
        row.execution_task_id,
        row.writer_agent_id,
        row.writer_parent_event_id,
        row.reservation_id,
        row.request_event_id,
    )
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise RuntimeError("stored official-account repair execution binding is invalid")
    return RepairExecutionBinding(
        execution_run_id=row.execution_run_id,  # type: ignore[arg-type]
        task_id=row.execution_task_id,  # type: ignore[arg-type]
        writer_agent_id=row.writer_agent_id,  # type: ignore[arg-type]
        writer_parent_event_id=row.writer_parent_event_id,  # type: ignore[arg-type]
        reservation_id=row.reservation_id,  # type: ignore[arg-type]
        request_event_id=row.request_event_id,  # type: ignore[arg-type]
    )


def _stored_intent(row: OfficialAccountRepairRequestModel) -> StoredRepairIntent:
    try:
        directives = _DIRECTIVES.validate_python(row.directive_snapshot)
    except ValidationError:
        raise RuntimeError("stored official-account repair directives are invalid") from None
    expected = sha256(canonical_json(row.directive_snapshot).encode()).hexdigest()
    if row.directive_fingerprint != expected:
        raise RuntimeError("stored official-account repair directive fingerprint changed")
    return StoredRepairIntent(
        id=row.id,
        run_id=row.run_id,
        source_article_version_id=row.source_article_version_id,
        repaired_article_version_id=row.repaired_article_version_id,
        source_review_request_id=row.source_review_request_id,
        attempt_number=row.attempt_number,
        status=row.status,  # type: ignore[arg-type]
        request_fingerprint=row.request_fingerprint,
        directive_fingerprint=row.directive_fingerprint,
        directives=directives,
        execution_binding=_execution_binding(row),
        provider=row.provider,
        model=row.model,
        created_at=row.created_at,
    )
