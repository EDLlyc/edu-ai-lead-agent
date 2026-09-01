from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.application.ports.official_account_weekly_dag import (
    WeeklyDagNodeFailure,
    WeeklyDagNodeResult,
    WeeklyDagRepository,
)
from app.domain.official_account_weekly_dag import (
    WEEKLY_DAG_DEFAULT_MAX_ATTEMPTS,
    WEEKLY_DAG_MAX_ACTIVE_BRANCHES,
    WEEKLY_DAG_NODE_BY_KEY,
    WEEKLY_DAG_NODES,
    WEEKLY_DAG_ROOT_AGENT_ID,
    WEEKLY_DAG_VERSION,
    WeeklyDagArtifact,
    WeeklyDagClaim,
    WeeklyDagErrorCode,
    WeeklyDagNodeDefinition,
    WeeklyDagNodeSnapshot,
    WeeklyDagNodeStatus,
    WeeklyDagRunSnapshot,
    WeeklyDagRunStatus,
    WeeklyDagStatusProjection,
    derive_weekly_dag_run_status,
    weekly_dag_attempt_agent_id,
    weekly_dag_graph_fingerprint,
    weekly_dag_node_input_fingerprint,
)
from app.domain.official_account_weekly_edition import (
    WEEKLY_EDITION_SCHEDULE_VERSION,
    WEEKLY_EDITION_SELECTION_VERSION,
    WEEKLY_EDITION_TIMEZONE,
)
from app.infrastructure.db.models import (
    ExecutionArtifactModel,
    ExecutionTraceEventModel,
    OfficialAccountWeeklyDagAttemptModel,
    OfficialAccountWeeklyDagNodeModel,
    OfficialAccountWeeklyDagRunModel,
)

_SAFE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SAFE_ERROR = re.compile(r"[a-z][a-z0-9_.:-]{0,79}")
_CLAIMABLE = (
    WeeklyDagNodeStatus.PENDING.value,
    WeeklyDagNodeStatus.RETRYABLE_FAILED.value,
)


class PostgresOfficialAccountWeeklyDagRepository(WeeklyDagRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def enqueue(
        self,
        *,
        run_id: UUID,
        task_id: str,
        week_start: date,
        input_fingerprint: str,
        request_fingerprint: str,
        now: datetime,
    ) -> tuple[WeeklyDagRunSnapshot, bool]:
        _validate_ref(task_id, "task ID")
        _validate_aware(now)
        graph_fingerprint = weekly_dag_graph_fingerprint()
        async with self._session_factory() as session, session.begin():
            created_id = await session.scalar(
                insert(OfficialAccountWeeklyDagRunModel)
                .values(
                    id=run_id,
                    task_id=task_id,
                    week_start=week_start,
                    timezone=WEEKLY_EDITION_TIMEZONE,
                    schedule_version=WEEKLY_EDITION_SCHEDULE_VERSION,
                    selection_version=WEEKLY_EDITION_SELECTION_VERSION,
                    dag_version=WEEKLY_DAG_VERSION,
                    graph_fingerprint=graph_fingerprint,
                    input_fingerprint=input_fingerprint,
                    request_fingerprint=request_fingerprint,
                    status=WeeklyDagRunStatus.PENDING.value,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing()
                .returning(OfficialAccountWeeklyDagRunModel.id)
            )
            created = created_id is not None
            run = await session.scalar(
                select(OfficialAccountWeeklyDagRunModel)
                .where(OfficialAccountWeeklyDagRunModel.id == run_id)
                .with_for_update()
            )
            if run is None:
                raise WeeklyDagNodeFailure(
                    WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
                    retryable=False,
                )
            if not _run_identity_matches(
                run,
                task_id=task_id,
                week_start=week_start,
                input_fingerprint=input_fingerprint,
                request_fingerprint=request_fingerprint,
                graph_fingerprint=graph_fingerprint,
            ):
                raise WeeklyDagNodeFailure(
                    WeeklyDagErrorCode.ARTIFACT_CONFLICT.value,
                    retryable=False,
                )
            if created:
                session.add_all(
                    [
                        OfficialAccountWeeklyDagNodeModel(
                            run_id=run_id,
                            task_id=task_id,
                            node_key=definition.key,
                            ordinal=definition.ordinal,
                            kind=definition.kind.value,
                            role=definition.role.value if definition.role else None,
                            status=WeeklyDagNodeStatus.PENDING.value,
                            input_fingerprint=None,
                            attempt_count=0,
                            max_attempts=WEEKLY_DAG_DEFAULT_MAX_ATTEMPTS,
                            available_at=now,
                            fencing_token=0,
                            created_at=now,
                            updated_at=now,
                        )
                        for definition in WEEKLY_DAG_NODES
                    ]
                )
                await _flush_or_conflict(session)
            return _run_snapshot(run), created

    async def get_status(self, run_id: UUID) -> WeeklyDagStatusProjection:
        async with self._session_factory() as session:
            return await _load_status(session, run_id)

    async def completed_week_starts(self) -> frozenset[date]:
        async with self._session_factory() as session:
            return frozenset(
                await session.scalars(
                    select(OfficialAccountWeeklyDagRunModel.week_start).where(
                        OfficialAccountWeeklyDagRunModel.schedule_version
                        == WEEKLY_EDITION_SCHEDULE_VERSION,
                        OfficialAccountWeeklyDagRunModel.selection_version
                        == WEEKLY_EDITION_SELECTION_VERSION,
                        OfficialAccountWeeklyDagRunModel.dag_version == WEEKLY_DAG_VERSION,
                        OfficialAccountWeeklyDagRunModel.status == WeeklyDagRunStatus.READY.value,
                    )
                )
            )

    async def claim_ready(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> WeeklyDagClaim | None:
        _validate_ref(worker_id, "worker ID")
        _validate_aware(now)
        if not 3 <= lease_seconds <= 3600:
            raise ValueError("weekly DAG lease must be between 3 and 3600 seconds")
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        async with self._session_factory() as session, session.begin():
            for expected_definition in WEEKLY_DAG_NODES:
                dependency_requirements = []
                for dependency_key in expected_definition.dependencies:
                    dependency = aliased(OfficialAccountWeeklyDagNodeModel)
                    dependency_requirements.append(
                        exists(
                            select(1).where(
                                dependency.run_id == OfficialAccountWeeklyDagNodeModel.run_id,
                                dependency.task_id == OfficialAccountWeeklyDagNodeModel.task_id,
                                dependency.node_key == dependency_key,
                                dependency.status == WeeklyDagNodeStatus.SUCCEEDED.value,
                            )
                        )
                    )
                node = await session.scalar(
                    select(OfficialAccountWeeklyDagNodeModel)
                    .join(
                        OfficialAccountWeeklyDagRunModel,
                        and_(
                            OfficialAccountWeeklyDagRunModel.id
                            == OfficialAccountWeeklyDagNodeModel.run_id,
                            OfficialAccountWeeklyDagRunModel.task_id
                            == OfficialAccountWeeklyDagNodeModel.task_id,
                        ),
                    )
                    .where(
                        OfficialAccountWeeklyDagRunModel.status.notin_(
                            (
                                WeeklyDagRunStatus.READY.value,
                                WeeklyDagRunStatus.TERMINAL_FAILED.value,
                            )
                        ),
                        OfficialAccountWeeklyDagNodeModel.node_key == expected_definition.key,
                        *dependency_requirements,
                        or_(
                            and_(
                                OfficialAccountWeeklyDagNodeModel.status.in_(_CLAIMABLE),
                                OfficialAccountWeeklyDagNodeModel.available_at <= now,
                            ),
                            and_(
                                OfficialAccountWeeklyDagNodeModel.status
                                == WeeklyDagNodeStatus.RUNNING.value,
                                OfficialAccountWeeklyDagNodeModel.lease_expires_at < now,
                            ),
                        ),
                    )
                    .order_by(
                        OfficialAccountWeeklyDagRunModel.week_start,
                    )
                    .with_for_update(skip_locked=True, of=OfficialAccountWeeklyDagNodeModel)
                    .limit(1)
                )
                if node is None:
                    continue
                run = await session.scalar(
                    select(OfficialAccountWeeklyDagRunModel)
                    .where(
                        OfficialAccountWeeklyDagRunModel.id == node.run_id,
                        OfficialAccountWeeklyDagRunModel.task_id == node.task_id,
                    )
                    .with_for_update()
                )
                if run is None:
                    raise WeeklyDagNodeFailure(
                        WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
                        retryable=False,
                    )
                if node.status == WeeklyDagNodeStatus.RUNNING.value:
                    await _expire_attempt(session, node=node, now=now)
                if node.attempt_count >= node.max_attempts:
                    _terminalize_exhausted(node, now=now)
                    await _refresh_run_status(session, run=run, now=now)
                    continue
                definition = _definition_from_model(node)
                dependencies = await _load_dependency_models(
                    session,
                    run_id=node.run_id,
                    task_id=node.task_id,
                    definition=definition,
                )
                if dependencies is None:
                    raise WeeklyDagNodeFailure(
                        WeeklyDagErrorCode.INVALID_DEPENDENCY.value,
                        retryable=False,
                    )
                if (
                    definition.is_branch_node
                    and await _active_branch_count(
                        session,
                        run_id=node.run_id,
                        now=now,
                    )
                    >= WEEKLY_DAG_MAX_ACTIVE_BRANCHES
                ):
                    continue
                dependency_fingerprints = tuple(
                    dependency.output_artifact_fingerprint for dependency in dependencies
                )
                if any(value is None for value in dependency_fingerprints):
                    raise WeeklyDagNodeFailure(
                        WeeklyDagErrorCode.INVALID_DEPENDENCY.value,
                        retryable=False,
                    )
                input_fingerprint = weekly_dag_node_input_fingerprint(
                    run_input_fingerprint=run.input_fingerprint,
                    definition=definition,
                    dependency_fingerprints=tuple(
                        value for value in dependency_fingerprints if value is not None
                    ),
                )
                node.attempt_count += 1
                node.fencing_token += 1
                node.status = WeeklyDagNodeStatus.RUNNING.value
                node.input_fingerprint = input_fingerprint
                node.lease_owner = worker_id
                node.lease_expires_at = lease_expires_at
                node.heartbeat_at = now
                node.started_at = now
                node.completed_at = None
                node.error_code = None
                node.updated_at = now
                attempt = OfficialAccountWeeklyDagAttemptModel(
                    run_id=node.run_id,
                    task_id=node.task_id,
                    node_key=node.node_key,
                    attempt_no=node.attempt_count,
                    fencing_token=node.fencing_token,
                    worker_id=worker_id,
                    input_fingerprint=input_fingerprint,
                    status=WeeklyDagNodeStatus.RUNNING.value,
                    lease_expires_at=lease_expires_at,
                    started_at=now,
                    heartbeat_at=now,
                )
                session.add(attempt)
                run.status = WeeklyDagRunStatus.RUNNING.value
                run.updated_at = now
                await _flush_or_conflict(session)
                return WeeklyDagClaim(
                    run=_run_snapshot(run),
                    node=_node_snapshot(node),
                    dependencies=tuple(_node_snapshot(item) for item in dependencies),
                    worker_id=worker_id,
                    lease_expires_at=lease_expires_at,
                )
        return None

    async def heartbeat(
        self,
        claim: WeeklyDagClaim,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        _validate_aware(now)
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        async with self._session_factory() as session, session.begin():
            node = await _locked_claim_node(session, claim)
            if node is None or node.lease_expires_at is None or node.lease_expires_at < now:
                return False
            attempt = await _locked_attempt(session, claim)
            if attempt is None or attempt.status != WeeklyDagNodeStatus.RUNNING.value:
                return False
            node.heartbeat_at = now
            node.lease_expires_at = lease_expires_at
            node.updated_at = now
            attempt.heartbeat_at = now
            attempt.lease_expires_at = lease_expires_at
            await session.flush()
            return True

    async def complete(
        self,
        claim: WeeklyDagClaim,
        *,
        result: WeeklyDagNodeResult,
        execution_artifact_id: UUID,
        trace_event_id: UUID,
        now: datetime,
    ) -> WeeklyDagStatusProjection:
        _validate_aware(now)
        async with self._session_factory() as session, session.begin():
            node = await _require_owned_claim(session, claim=claim, now=now)
            attempt = await _require_attempt(session, claim)
            run = await _locked_run(session, claim.run.run_id, claim.run.task_id)
            definition = _definition_from_model(node)
            if definition.key == "aggregate" and result.aggregate_artifact is None:
                raise WeeklyDagNodeFailure(
                    WeeklyDagErrorCode.PARTIAL_CHILDREN.value,
                    retryable=False,
                )
            await _validate_execution_lineage(
                session,
                node=node,
                artifact=result.artifact,
                execution_artifact_id=execution_artifact_id,
                trace_event_id=trace_event_id,
            )
            _bind_success(
                node,
                artifact=result.artifact,
                execution_artifact_id=execution_artifact_id,
                trace_event_id=trace_event_id,
                now=now,
            )
            attempt.status = WeeklyDagNodeStatus.SUCCEEDED.value
            attempt.output_artifact_ref = result.artifact.opaque_ref
            attempt.output_artifact_fingerprint = result.artifact.fingerprint
            attempt.completed_at = now
            if result.aggregate_artifact is not None:
                run.aggregate_artifact_ref = result.aggregate_artifact.opaque_ref
                run.aggregate_artifact_fingerprint = result.aggregate_artifact.fingerprint
                run.aggregate_media_type = result.aggregate_artifact.media_type
                run.aggregate_byte_size = result.aggregate_artifact.byte_size
            await _refresh_run_status(session, run=run, now=now)
            await session.flush()
            return await _load_status(session, run.id)

    async def fail(
        self,
        claim: WeeklyDagClaim,
        *,
        error_code: str,
        retryable: bool,
        available_at: datetime,
        now: datetime,
        trace_event_id: UUID | None,
    ) -> WeeklyDagStatusProjection:
        _validate_error(error_code)
        _validate_aware(now)
        _validate_aware(available_at)
        async with self._session_factory() as session, session.begin():
            node = await _require_owned_claim(session, claim=claim, now=now, allow_expired=True)
            attempt = await _require_attempt(session, claim)
            run = await _locked_run(session, claim.run.run_id, claim.run.task_id)
            exhausted = node.attempt_count >= node.max_attempts
            status = (
                WeeklyDagNodeStatus.RETRYABLE_FAILED
                if retryable and not exhausted
                else WeeklyDagNodeStatus.TERMINAL_FAILED
            )
            resolved_error = (
                WeeklyDagErrorCode.ATTEMPTS_EXHAUSTED.value
                if exhausted and retryable
                else error_code
            )
            node.status = status.value
            node.available_at = available_at
            node.lease_owner = None
            node.lease_expires_at = None
            node.heartbeat_at = None
            node.error_code = resolved_error
            node.trace_event_id = trace_event_id
            node.completed_at = now
            node.updated_at = now
            attempt.status = status.value
            attempt.error_code = resolved_error
            attempt.completed_at = now
            await _refresh_run_status(session, run=run, now=now)
            await session.flush()
            return await _load_status(session, run.id)

    async def retry(
        self,
        *,
        run_id: UUID,
        node_key: str,
        now: datetime,
    ) -> WeeklyDagStatusProjection:
        _validate_aware(now)
        definition = WEEKLY_DAG_NODE_BY_KEY.get(node_key)
        if definition is None:
            raise ValueError("weekly DAG retry node is unknown")
        async with self._session_factory() as session, session.begin():
            run = await session.scalar(
                select(OfficialAccountWeeklyDagRunModel)
                .where(OfficialAccountWeeklyDagRunModel.id == run_id)
                .with_for_update()
            )
            if run is None:
                raise LookupError("weekly DAG run does not exist")
            nodes = tuple(
                await session.scalars(
                    select(OfficialAccountWeeklyDagNodeModel)
                    .where(OfficialAccountWeeklyDagNodeModel.run_id == run_id)
                    .order_by(OfficialAccountWeeklyDagNodeModel.ordinal)
                    .with_for_update()
                )
            )
            by_key = {item.node_key: item for item in nodes}
            target = by_key.get(node_key)
            if target is None or target.status != WeeklyDagNodeStatus.RETRYABLE_FAILED.value:
                raise ValueError("weekly DAG retry requires a retryable failed node")
            if target.attempt_count >= target.max_attempts:
                raise ValueError("weekly DAG retry attempt budget is exhausted")
            descendants = _descendant_keys(node_key)
            for key in (node_key, *descendants):
                node = by_key[key]
                if node.status == WeeklyDagNodeStatus.SUCCEEDED.value:
                    continue
                if node.status == WeeklyDagNodeStatus.RUNNING.value:
                    raise ValueError("weekly DAG retry cannot reset an active node")
                node.status = WeeklyDagNodeStatus.PENDING.value
                node.available_at = now
                node.error_code = None
                node.trace_event_id = None
                node.completed_at = None
                node.updated_at = now
            await _refresh_run_status(session, run=run, now=now, nodes=nodes)
            await session.flush()
            return await _load_status(session, run.id)


async def _load_status(session: AsyncSession, run_id: UUID) -> WeeklyDagStatusProjection:
    run = await session.get(OfficialAccountWeeklyDagRunModel, run_id)
    if run is None:
        raise LookupError("weekly DAG run does not exist")
    nodes = tuple(
        await session.scalars(
            select(OfficialAccountWeeklyDagNodeModel)
            .where(OfficialAccountWeeklyDagNodeModel.run_id == run_id)
            .order_by(OfficialAccountWeeklyDagNodeModel.ordinal)
        )
    )
    if len(nodes) != len(WEEKLY_DAG_NODES):
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
            retryable=False,
        )
    return WeeklyDagStatusProjection(
        run=_run_snapshot(run),
        nodes=tuple(_node_snapshot(node) for node in nodes),
    )


async def _load_dependency_models(
    session: AsyncSession,
    *,
    run_id: UUID,
    task_id: str,
    definition: WeeklyDagNodeDefinition,
) -> tuple[OfficialAccountWeeklyDagNodeModel, ...] | None:
    dependency_keys = definition.dependencies
    if not dependency_keys:
        return ()
    rows = tuple(
        await session.scalars(
            select(OfficialAccountWeeklyDagNodeModel).where(
                OfficialAccountWeeklyDagNodeModel.run_id == run_id,
                OfficialAccountWeeklyDagNodeModel.task_id == task_id,
                OfficialAccountWeeklyDagNodeModel.node_key.in_(dependency_keys),
            )
        )
    )
    by_key = {row.node_key: row for row in rows}
    if set(by_key) != set(dependency_keys):
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.INVALID_DEPENDENCY.value,
            retryable=False,
        )
    ordered = tuple(by_key[key] for key in dependency_keys)
    if any(row.status != WeeklyDagNodeStatus.SUCCEEDED.value for row in ordered):
        return None
    for row in ordered:
        artifact = _artifact_from_model(row)
        if row.execution_artifact_id is None or row.trace_event_id is None:
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
                retryable=False,
            )
        await _validate_execution_lineage(
            session,
            node=row,
            artifact=artifact,
            execution_artifact_id=row.execution_artifact_id,
            trace_event_id=row.trace_event_id,
        )
    return ordered


async def _active_branch_count(session: AsyncSession, *, run_id: UUID, now: datetime) -> int:
    return len(
        tuple(
            await session.scalars(
                select(OfficialAccountWeeklyDagNodeModel.node_key).where(
                    OfficialAccountWeeklyDagNodeModel.run_id == run_id,
                    OfficialAccountWeeklyDagNodeModel.role.is_not(None),
                    OfficialAccountWeeklyDagNodeModel.status == WeeklyDagNodeStatus.RUNNING.value,
                    OfficialAccountWeeklyDagNodeModel.lease_expires_at >= now,
                )
            )
        )
    )


async def _expire_attempt(
    session: AsyncSession,
    *,
    node: OfficialAccountWeeklyDagNodeModel,
    now: datetime,
) -> None:
    attempt = await session.scalar(
        select(OfficialAccountWeeklyDagAttemptModel)
        .where(
            OfficialAccountWeeklyDagAttemptModel.run_id == node.run_id,
            OfficialAccountWeeklyDagAttemptModel.task_id == node.task_id,
            OfficialAccountWeeklyDagAttemptModel.node_key == node.node_key,
            OfficialAccountWeeklyDagAttemptModel.attempt_no == node.attempt_count,
        )
        .with_for_update()
    )
    if attempt is None or attempt.status != WeeklyDagNodeStatus.RUNNING.value:
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
            retryable=False,
        )
    attempt.status = "lease_expired"
    attempt.error_code = WeeklyDagErrorCode.LEASE_LOST.value
    attempt.completed_at = now
    node.lease_owner = None
    node.lease_expires_at = None
    node.heartbeat_at = None
    node.status = WeeklyDagNodeStatus.RETRYABLE_FAILED.value
    node.error_code = WeeklyDagErrorCode.LEASE_LOST.value
    node.completed_at = now
    node.updated_at = now


def _terminalize_exhausted(node: OfficialAccountWeeklyDagNodeModel, *, now: datetime) -> None:
    node.status = WeeklyDagNodeStatus.TERMINAL_FAILED.value
    node.error_code = WeeklyDagErrorCode.ATTEMPTS_EXHAUSTED.value
    node.lease_owner = None
    node.lease_expires_at = None
    node.heartbeat_at = None
    node.completed_at = now
    node.updated_at = now


async def _locked_claim_node(
    session: AsyncSession,
    claim: WeeklyDagClaim,
) -> OfficialAccountWeeklyDagNodeModel | None:
    return cast(
        OfficialAccountWeeklyDagNodeModel | None,
        await session.scalar(
            select(OfficialAccountWeeklyDagNodeModel)
            .where(
                OfficialAccountWeeklyDagNodeModel.run_id == claim.run.run_id,
                OfficialAccountWeeklyDagNodeModel.task_id == claim.run.task_id,
                OfficialAccountWeeklyDagNodeModel.node_key == claim.node.definition.key,
                OfficialAccountWeeklyDagNodeModel.status == WeeklyDagNodeStatus.RUNNING.value,
                OfficialAccountWeeklyDagNodeModel.lease_owner == claim.worker_id,
                OfficialAccountWeeklyDagNodeModel.fencing_token == claim.node.fencing_token,
                OfficialAccountWeeklyDagNodeModel.attempt_count == claim.node.attempt_count,
            )
            .with_for_update()
        ),
    )


async def _require_owned_claim(
    session: AsyncSession,
    *,
    claim: WeeklyDagClaim,
    now: datetime,
    allow_expired: bool = False,
) -> OfficialAccountWeeklyDagNodeModel:
    node = await _locked_claim_node(session, claim)
    if node is None or node.lease_expires_at is None:
        raise WeeklyDagNodeFailure(WeeklyDagErrorCode.LEASE_LOST.value, retryable=True)
    if not allow_expired and node.lease_expires_at < now:
        raise WeeklyDagNodeFailure(WeeklyDagErrorCode.LEASE_LOST.value, retryable=True)
    return node


async def _locked_attempt(
    session: AsyncSession,
    claim: WeeklyDagClaim,
) -> OfficialAccountWeeklyDagAttemptModel | None:
    return cast(
        OfficialAccountWeeklyDagAttemptModel | None,
        await session.scalar(
            select(OfficialAccountWeeklyDagAttemptModel)
            .where(
                OfficialAccountWeeklyDagAttemptModel.run_id == claim.run.run_id,
                OfficialAccountWeeklyDagAttemptModel.task_id == claim.run.task_id,
                OfficialAccountWeeklyDagAttemptModel.node_key == claim.node.definition.key,
                OfficialAccountWeeklyDagAttemptModel.attempt_no == claim.node.attempt_count,
                OfficialAccountWeeklyDagAttemptModel.fencing_token == claim.node.fencing_token,
                OfficialAccountWeeklyDagAttemptModel.worker_id == claim.worker_id,
            )
            .with_for_update()
        ),
    )


async def _require_attempt(
    session: AsyncSession,
    claim: WeeklyDagClaim,
) -> OfficialAccountWeeklyDagAttemptModel:
    attempt = await _locked_attempt(session, claim)
    if attempt is None or attempt.status != WeeklyDagNodeStatus.RUNNING.value:
        raise WeeklyDagNodeFailure(WeeklyDagErrorCode.LEASE_LOST.value, retryable=True)
    return attempt


async def _locked_run(
    session: AsyncSession,
    run_id: UUID,
    task_id: str,
) -> OfficialAccountWeeklyDagRunModel:
    run = await session.scalar(
        select(OfficialAccountWeeklyDagRunModel)
        .where(
            OfficialAccountWeeklyDagRunModel.id == run_id,
            OfficialAccountWeeklyDagRunModel.task_id == task_id,
        )
        .with_for_update()
    )
    if run is None:
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
            retryable=False,
        )
    return run


def _bind_success(
    node: OfficialAccountWeeklyDagNodeModel,
    *,
    artifact: WeeklyDagArtifact,
    execution_artifact_id: UUID,
    trace_event_id: UUID,
    now: datetime,
) -> None:
    node.status = WeeklyDagNodeStatus.SUCCEEDED.value
    node.output_artifact_ref = artifact.opaque_ref
    node.output_artifact_fingerprint = artifact.fingerprint
    node.output_media_type = artifact.media_type
    node.output_byte_size = artifact.byte_size
    node.execution_artifact_id = execution_artifact_id
    node.trace_event_id = trace_event_id
    node.error_code = None
    node.lease_owner = None
    node.lease_expires_at = None
    node.heartbeat_at = None
    node.completed_at = now
    node.updated_at = now


async def _refresh_run_status(
    session: AsyncSession,
    *,
    run: OfficialAccountWeeklyDagRunModel,
    now: datetime,
    nodes: tuple[OfficialAccountWeeklyDagNodeModel, ...] | None = None,
) -> None:
    resolved = nodes or tuple(
        await session.scalars(
            select(OfficialAccountWeeklyDagNodeModel)
            .where(OfficialAccountWeeklyDagNodeModel.run_id == run.id)
            .order_by(OfficialAccountWeeklyDagNodeModel.ordinal)
        )
    )
    status = derive_weekly_dag_run_status(tuple(_node_snapshot(item) for item in resolved))
    run.status = status.value
    run.updated_at = now
    run.completed_at = (
        now if status in {WeeklyDagRunStatus.READY, WeeklyDagRunStatus.TERMINAL_FAILED} else None
    )


def _definition_from_model(model: OfficialAccountWeeklyDagNodeModel):  # type: ignore[no-untyped-def]
    definition = WEEKLY_DAG_NODE_BY_KEY.get(model.node_key)
    if definition is None or (
        definition.ordinal != model.ordinal
        or definition.kind.value != model.kind
        or (definition.role.value if definition.role else None) != model.role
    ):
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
            retryable=False,
        )
    return definition


def _run_snapshot(model: OfficialAccountWeeklyDagRunModel) -> WeeklyDagRunSnapshot:
    aggregate = None
    if model.aggregate_artifact_ref is not None:
        if (
            model.aggregate_artifact_fingerprint is None
            or model.aggregate_media_type is None
            or model.aggregate_byte_size is None
        ):
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
                retryable=False,
            )
        aggregate = WeeklyDagArtifact(
            opaque_ref=model.aggregate_artifact_ref,
            fingerprint=model.aggregate_artifact_fingerprint,
            media_type=model.aggregate_media_type,
            byte_size=model.aggregate_byte_size,
        )
    return WeeklyDagRunSnapshot(
        run_id=model.id,
        task_id=model.task_id,
        week_start=model.week_start,
        schedule_version=model.schedule_version,
        selection_version=model.selection_version,
        dag_version=model.dag_version,
        graph_fingerprint=model.graph_fingerprint,
        input_fingerprint=model.input_fingerprint,
        request_fingerprint=model.request_fingerprint,
        status=WeeklyDagRunStatus(model.status),
        aggregate_artifact=aggregate,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )


def _node_snapshot(model: OfficialAccountWeeklyDagNodeModel) -> WeeklyDagNodeSnapshot:
    artifact = _artifact_from_model(model) if model.output_artifact_ref is not None else None
    return WeeklyDagNodeSnapshot(
        run_id=model.run_id,
        definition=_definition_from_model(model),
        status=WeeklyDagNodeStatus(model.status),
        input_fingerprint=model.input_fingerprint,
        attempt_count=model.attempt_count,
        max_attempts=model.max_attempts,
        fencing_token=model.fencing_token,
        output_artifact=artifact,
        execution_artifact_id=model.execution_artifact_id,
        trace_event_id=model.trace_event_id,
        error_code=model.error_code,
        available_at=model.available_at,
        started_at=model.started_at,
        completed_at=model.completed_at,
    )


def _artifact_from_model(model: OfficialAccountWeeklyDagNodeModel) -> WeeklyDagArtifact:
    if (
        model.output_artifact_ref is None
        or model.output_artifact_fingerprint is None
        or model.output_media_type is None
        or model.output_byte_size is None
    ):
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
            retryable=False,
        )
    return WeeklyDagArtifact(
        opaque_ref=model.output_artifact_ref,
        fingerprint=model.output_artifact_fingerprint,
        media_type=model.output_media_type,
        byte_size=model.output_byte_size,
    )


async def _validate_execution_lineage(
    session: AsyncSession,
    *,
    node: OfficialAccountWeeklyDagNodeModel,
    artifact: WeeklyDagArtifact,
    execution_artifact_id: UUID,
    trace_event_id: UUID,
) -> None:
    expected_agent_id = weekly_dag_attempt_agent_id(node.node_key, node.attempt_count)
    stored_artifact = await session.scalar(
        select(ExecutionArtifactModel).where(
            ExecutionArtifactModel.id == execution_artifact_id,
            ExecutionArtifactModel.run_id == node.run_id,
            ExecutionArtifactModel.task_id == node.task_id,
            ExecutionArtifactModel.agent_id == expected_agent_id,
        )
    )
    if stored_artifact is None or (
        stored_artifact.sha256 != artifact.fingerprint
        or stored_artifact.media_type != artifact.media_type
        or stored_artifact.byte_size != artifact.byte_size
    ):
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.ARTIFACT_CONFLICT.value,
            retryable=False,
        )
    producer = await session.scalar(
        select(ExecutionTraceEventModel).where(
            ExecutionTraceEventModel.id == stored_artifact.producer_event_id,
            ExecutionTraceEventModel.run_id == node.run_id,
            ExecutionTraceEventModel.task_id == node.task_id,
            ExecutionTraceEventModel.agent_id == expected_agent_id,
            ExecutionTraceEventModel.kind == "artifact_produced",
            ExecutionTraceEventModel.status == "succeeded",
            ExecutionTraceEventModel.artifact_id == execution_artifact_id,
        )
    )
    root_finish = await session.scalar(
        select(ExecutionTraceEventModel).where(
            ExecutionTraceEventModel.id == trace_event_id,
            ExecutionTraceEventModel.run_id == node.run_id,
            ExecutionTraceEventModel.task_id == node.task_id,
            ExecutionTraceEventModel.agent_id == WEEKLY_DAG_ROOT_AGENT_ID,
            ExecutionTraceEventModel.kind == "node_finished",
            ExecutionTraceEventModel.status == "succeeded",
            ExecutionTraceEventModel.target_name == _definition_from_model(node).capability_name,
        )
    )
    if producer is None or root_finish is None or root_finish.parent_event_id is None:
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
            retryable=False,
        )
    root_start = await session.scalar(
        select(ExecutionTraceEventModel).where(
            ExecutionTraceEventModel.id == root_finish.parent_event_id,
            ExecutionTraceEventModel.run_id == node.run_id,
            ExecutionTraceEventModel.task_id == node.task_id,
            ExecutionTraceEventModel.agent_id == WEEKLY_DAG_ROOT_AGENT_ID,
            ExecutionTraceEventModel.kind == "node_started",
            ExecutionTraceEventModel.target_name == _definition_from_model(node).capability_name,
        )
    )
    if root_start is None or root_start.parent_event_id is None:
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
            retryable=False,
        )
    child_finish = await session.scalar(
        select(ExecutionTraceEventModel).where(
            ExecutionTraceEventModel.id == root_start.parent_event_id,
            ExecutionTraceEventModel.run_id == node.run_id,
            ExecutionTraceEventModel.task_id == node.task_id,
            ExecutionTraceEventModel.agent_id == expected_agent_id,
            ExecutionTraceEventModel.kind == "node_finished",
            ExecutionTraceEventModel.status == "succeeded",
            ExecutionTraceEventModel.parent_event_id == stored_artifact.producer_event_id,
            ExecutionTraceEventModel.target_name == _definition_from_model(node).capability_name,
        )
    )
    if child_finish is None:
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
            retryable=False,
        )


def _run_identity_matches(
    model: OfficialAccountWeeklyDagRunModel,
    *,
    task_id: str,
    week_start: date,
    input_fingerprint: str,
    request_fingerprint: str,
    graph_fingerprint: str,
) -> bool:
    return (
        model.task_id == task_id
        and model.week_start == week_start
        and model.timezone == WEEKLY_EDITION_TIMEZONE
        and model.schedule_version == WEEKLY_EDITION_SCHEDULE_VERSION
        and model.selection_version == WEEKLY_EDITION_SELECTION_VERSION
        and model.dag_version == WEEKLY_DAG_VERSION
        and model.graph_fingerprint == graph_fingerprint
        and model.input_fingerprint == input_fingerprint
        and model.request_fingerprint == request_fingerprint
    )


def _descendant_keys(node_key: str) -> tuple[str, ...]:
    descendants: list[str] = []
    frontier = {node_key}
    for definition in WEEKLY_DAG_NODES:
        if definition.key == node_key:
            continue
        if any(dependency in frontier for dependency in definition.dependencies):
            descendants.append(definition.key)
            frontier.add(definition.key)
    return tuple(descendants)


async def _flush_or_conflict(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError:
        raise WeeklyDagNodeFailure(
            WeeklyDagErrorCode.ARTIFACT_CONFLICT.value,
            retryable=False,
        ) from None


def _validate_ref(value: str, label: str) -> None:
    if _SAFE_REF.fullmatch(value) is None:
        raise ValueError(f"weekly DAG {label} is invalid")


def _validate_error(value: str) -> None:
    if _SAFE_ERROR.fullmatch(value) is None:
        raise ValueError("weekly DAG error code is invalid")


def _validate_aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise ValueError("weekly DAG repository time must be timezone-aware")
