from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.execution_governance import (
    AllocationSnapshot,
    BudgetReservationSnapshot,
    ExecutionGovernanceRepository,
)
from app.domain.execution_governance import (
    DELEGATION_THRESHOLD_PERCENT,
    EXECUTION_GOVERNANCE_POLICY_VERSION,
    HARD_MAX_AGENT_DEPTH,
    ArtifactLifecycleStatus,
    ArtifactMetadata,
    BudgetLimits,
    BudgetUsage,
    BudgetVector,
    ExecutionEventKind,
    ExecutionEventStatus,
    ExecutionIdentity,
    ExecutionRole,
    ExecutionRunStatus,
    GovernanceDeniedError,
    GovernanceErrorCode,
    SafeEventDraft,
    SafeExecutionEvent,
    delegation_usage_percent,
)
from app.infrastructure.db.models import (
    ExecutionAgentAllocationModel,
    ExecutionArtifactModel,
    ExecutionBudgetReservationModel,
    ExecutionGovernedRunModel,
    ExecutionTraceEventModel,
)

_TERMINAL_STATUSES = {
    ExecutionRunStatus.SUCCEEDED,
    ExecutionRunStatus.FAILED,
    ExecutionRunStatus.CANCELLED,
}

_ALLOWED_PARENT_KINDS: dict[ExecutionEventKind, frozenset[ExecutionEventKind]] = {
    ExecutionEventKind.NODE_STARTED: frozenset(
        {
            ExecutionEventKind.RUN_STARTED,
            ExecutionEventKind.NODE_STARTED,
            ExecutionEventKind.NODE_FINISHED,
            ExecutionEventKind.ARTIFACT_PRODUCED,
        }
    ),
    ExecutionEventKind.MODEL_REQUESTED: frozenset(
        {
            ExecutionEventKind.NODE_STARTED,
            ExecutionEventKind.MODEL_RESULT,
            ExecutionEventKind.TOOL_RESULT,
        }
    ),
    ExecutionEventKind.MODEL_RESULT: frozenset({ExecutionEventKind.MODEL_REQUESTED}),
    ExecutionEventKind.TOOL_REQUESTED: frozenset(
        {
            ExecutionEventKind.NODE_STARTED,
            ExecutionEventKind.MODEL_RESULT,
            ExecutionEventKind.TOOL_RESULT,
        }
    ),
    ExecutionEventKind.TOOL_RESULT: frozenset({ExecutionEventKind.TOOL_REQUESTED}),
    ExecutionEventKind.ARTIFACT_PRODUCED: frozenset(
        {
            ExecutionEventKind.NODE_STARTED,
            ExecutionEventKind.MODEL_RESULT,
            ExecutionEventKind.TOOL_RESULT,
        }
    ),
    ExecutionEventKind.NODE_FINISHED: frozenset(
        {
            ExecutionEventKind.NODE_STARTED,
            ExecutionEventKind.MODEL_RESULT,
            ExecutionEventKind.TOOL_RESULT,
            ExecutionEventKind.ARTIFACT_PRODUCED,
        }
    ),
    ExecutionEventKind.NODE_FAILED: frozenset(
        {
            ExecutionEventKind.NODE_STARTED,
            ExecutionEventKind.MODEL_REQUESTED,
            ExecutionEventKind.TOOL_REQUESTED,
            ExecutionEventKind.MODEL_RESULT,
            ExecutionEventKind.TOOL_RESULT,
            ExecutionEventKind.BUDGET_DENIED,
            ExecutionEventKind.PERMISSION_DENIED,
        }
    ),
    ExecutionEventKind.BUDGET_DENIED: frozenset(
        {
            ExecutionEventKind.NODE_STARTED,
            ExecutionEventKind.MODEL_REQUESTED,
            ExecutionEventKind.TOOL_REQUESTED,
            ExecutionEventKind.MODEL_RESULT,
            ExecutionEventKind.TOOL_RESULT,
        }
    ),
    ExecutionEventKind.PERMISSION_DENIED: frozenset(
        {
            ExecutionEventKind.NODE_STARTED,
            ExecutionEventKind.MODEL_REQUESTED,
            ExecutionEventKind.TOOL_REQUESTED,
            ExecutionEventKind.MODEL_RESULT,
            ExecutionEventKind.TOOL_RESULT,
        }
    ),
    ExecutionEventKind.RUN_FINISHED: frozenset(
        {ExecutionEventKind.NODE_FINISHED, ExecutionEventKind.ARTIFACT_PRODUCED}
    ),
    ExecutionEventKind.RUN_FAILED: frozenset(
        {
            ExecutionEventKind.NODE_FAILED,
            ExecutionEventKind.BUDGET_DENIED,
            ExecutionEventKind.PERMISSION_DENIED,
        }
    ),
}


class PostgresExecutionGovernanceRepository(ExecutionGovernanceRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_run(
        self,
        *,
        identity: ExecutionIdentity,
        role: ExecutionRole,
        limits: BudgetLimits,
        request_fingerprint: str,
        root_event_id: UUID,
    ) -> AllocationSnapshot:
        if len(request_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in request_fingerprint
        ):
            raise ValueError("execution request fingerprint must be lowercase SHA-256")
        async with self._session_factory() as session, session.begin():
            created_run_id = await session.scalar(
                insert(ExecutionGovernedRunModel)
                .values(
                    id=identity.run_id,
                    task_id=identity.task_id,
                    root_agent_id=identity.agent_id,
                    policy_version=EXECUTION_GOVERNANCE_POLICY_VERSION,
                    request_fingerprint=request_fingerprint,
                    status=ExecutionRunStatus.RUNNING.value,
                    **_limit_model_values(limits),
                )
                .on_conflict_do_nothing()
                .returning(ExecutionGovernedRunModel.id)
            )
            if created_run_id is None:
                existing_run = await session.scalar(
                    select(ExecutionGovernedRunModel)
                    .where(ExecutionGovernedRunModel.request_fingerprint == request_fingerprint)
                    .with_for_update()
                )
                if existing_run is None:
                    raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
                allocation = await _load_allocation(
                    session,
                    ExecutionIdentity(
                        run_id=existing_run.id,
                        task_id=existing_run.task_id,
                        agent_id=existing_run.root_agent_id,
                    ),
                    lock=True,
                )
                if (
                    existing_run.task_id != identity.task_id
                    or existing_run.root_agent_id != identity.agent_id
                    or _limits_from_run(existing_run) != limits
                    or allocation.role is not role
                ):
                    raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
                return allocation
            allocation_model = ExecutionAgentAllocationModel(
                run_id=identity.run_id,
                task_id=identity.task_id,
                agent_id=identity.agent_id,
                role=role.value,
                status=ExecutionRunStatus.RUNNING.value,
                parent_agent_id=None,
                parent_event_id=None,
                depth=0,
                next_seq_no=1,
                **_limit_model_values(limits),
            )
            session.add(allocation_model)
            await _flush_or_deny_invalid(session)
            root_event = ExecutionTraceEventModel(
                id=root_event_id,
                run_id=identity.run_id,
                task_id=identity.task_id,
                agent_id=identity.agent_id,
                seq_no=0,
                kind=ExecutionEventKind.RUN_STARTED.value,
                status=ExecutionEventStatus.STARTED.value,
                parent_event_id=None,
                artifact_id=None,
            )
            session.add(root_event)
            await _flush_or_deny_invalid(session)
            return _allocation_snapshot(allocation_model)

    async def get_allocation(self, identity: ExecutionIdentity) -> AllocationSnapshot:
        async with self._session_factory() as session:
            return await _load_allocation(session, identity, lock=False)

    async def allocate_child(
        self,
        *,
        parent: ExecutionIdentity,
        child: ExecutionIdentity,
        role: ExecutionRole,
        limits: BudgetLimits,
        parent_event_id: UUID,
    ) -> AllocationSnapshot:
        if parent.run_id != child.run_id or parent.task_id != child.task_id:
            raise GovernanceDeniedError(GovernanceErrorCode.TASK_SCOPE_FORBIDDEN)
        if parent.agent_id == child.agent_id:
            raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
        async with self._session_factory() as session, session.begin():
            parent_model = await _load_allocation_model(session, parent, lock=True)
            if parent_model.status != ExecutionRunStatus.RUNNING.value:
                raise GovernanceDeniedError(GovernanceErrorCode.ALLOCATION_NOT_ACTIVE)
            parent_event = await session.scalar(
                select(ExecutionTraceEventModel).where(
                    ExecutionTraceEventModel.id == parent_event_id,
                    ExecutionTraceEventModel.run_id == parent.run_id,
                    ExecutionTraceEventModel.task_id == parent.task_id,
                    ExecutionTraceEventModel.agent_id == parent.agent_id,
                )
            )
            if parent_event is None:
                raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
            parent_limits = _limits_from_allocation(parent_model)
            parent_usage = _usage_from_allocation(parent_model)
            parent_reserved = _reserved_from_allocation(parent_model)
            if not parent_limits.allow_child_agents:
                raise GovernanceDeniedError(GovernanceErrorCode.RECURSION_DISABLED)
            child_depth = parent_model.depth + 1
            if (
                child_depth > parent_limits.max_depth
                or child_depth > HARD_MAX_AGENT_DEPTH
                or limits.max_depth > parent_limits.max_depth
            ):
                raise GovernanceDeniedError(GovernanceErrorCode.DEPTH_EXHAUSTED)
            if (
                delegation_usage_percent(
                    limits=parent_limits,
                    usage=parent_usage,
                    reserved=parent_reserved,
                )
                >= DELEGATION_THRESHOLD_PERCENT
            ):
                raise GovernanceDeniedError(GovernanceErrorCode.DELEGATION_THRESHOLD_REACHED)
            if (
                parent_model.used_child_count + parent_model.reserved_child_count
                >= parent_model.limit_children
            ):
                raise GovernanceDeniedError(GovernanceErrorCode.CHILD_LIMIT_EXHAUSTED)
            requested = limits.ceiling_vector()
            if not _fits_allocation(parent_model, requested):
                raise GovernanceDeniedError(GovernanceErrorCode.BUDGET_EXHAUSTED)
            existing = await session.scalar(
                select(ExecutionAgentAllocationModel).where(
                    ExecutionAgentAllocationModel.run_id == child.run_id,
                    ExecutionAgentAllocationModel.task_id == child.task_id,
                    ExecutionAgentAllocationModel.agent_id == child.agent_id,
                )
            )
            if existing is not None:
                raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)

            _add_reserved(parent_model, requested)
            parent_model.reserved_child_count += 1
            child_model = ExecutionAgentAllocationModel(
                run_id=child.run_id,
                task_id=child.task_id,
                agent_id=child.agent_id,
                role=role.value,
                status=ExecutionRunStatus.RUNNING.value,
                parent_agent_id=parent.agent_id,
                parent_event_id=parent_event_id,
                depth=child_depth,
                next_seq_no=0,
                **_limit_model_values(limits),
            )
            session.add(child_model)
            await _flush_or_deny_invalid(session)
            return _allocation_snapshot(child_model)

    async def reserve_budget(
        self,
        *,
        identity: ExecutionIdentity,
        reservation_id: UUID,
        requested: BudgetVector,
    ) -> BudgetReservationSnapshot:
        async with self._session_factory() as session, session.begin():
            allocation = await _load_allocation_model(session, identity, lock=True)
            existing = await session.get(ExecutionBudgetReservationModel, reservation_id)
            if existing is not None:
                if (
                    _reservation_identity(existing) != identity
                    or _reserved_from_reservation(existing) != requested
                ):
                    raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
                return _reservation_snapshot(existing)
            if allocation.status != ExecutionRunStatus.RUNNING.value:
                raise GovernanceDeniedError(GovernanceErrorCode.ALLOCATION_NOT_ACTIVE)
            if not _fits_allocation(allocation, requested):
                raise GovernanceDeniedError(GovernanceErrorCode.BUDGET_EXHAUSTED)
            _add_reserved(allocation, requested)
            reservation = ExecutionBudgetReservationModel(
                id=reservation_id,
                run_id=identity.run_id,
                task_id=identity.task_id,
                agent_id=identity.agent_id,
                status="reserved",
                **_reserved_model_values(requested),
            )
            session.add(reservation)
            await _flush_or_deny_invalid(session)
            return _reservation_snapshot(reservation)

    async def reconcile_budget(
        self,
        *,
        identity: ExecutionIdentity,
        reservation_id: UUID,
        actual: BudgetUsage,
    ) -> BudgetReservationSnapshot:
        if actual.child_count:
            raise ValueError("capability reconciliation cannot change child usage")
        async with self._session_factory() as session, session.begin():
            allocation = await _load_allocation_model(session, identity, lock=True)
            reservation = await session.scalar(
                select(ExecutionBudgetReservationModel)
                .where(ExecutionBudgetReservationModel.id == reservation_id)
                .with_for_update()
            )
            if reservation is None or _reservation_identity(reservation) != identity:
                raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
            if reservation.status == "reconciled":
                if _actual_from_reservation(reservation) != actual:
                    raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
                return _reservation_snapshot(reservation)
            reserved = _reserved_from_reservation(reservation)
            if not _actual_fits_reservation(actual, reserved):
                raise GovernanceDeniedError(GovernanceErrorCode.BUDGET_EXHAUSTED)
            _replace_reserved_usage_with_actual(allocation, reserved=reserved, actual=actual)
            reservation.status = "reconciled"
            reservation.actual_elapsed_ms = actual.elapsed_ms
            reservation.actual_model_turns = actual.model_turns
            reservation.actual_input_tokens = actual.input_tokens
            reservation.actual_output_tokens = actual.output_tokens
            reservation.actual_tool_calls = actual.tool_calls
            reservation.actual_tool_result_bytes = actual.tool_result_bytes
            reservation.actual_artifact_bytes = actual.artifact_bytes
            reservation.reconciled_at = datetime.now(UTC)
            await session.flush()
            return _reservation_snapshot(reservation)

    async def append_event(self, draft: SafeEventDraft) -> SafeExecutionEvent:
        async with self._session_factory() as session, session.begin():
            event = await _append_event(session, draft)
            return event

    async def register_artifact(
        self,
        *,
        event: SafeEventDraft,
        artifact: ArtifactMetadata,
    ) -> tuple[SafeExecutionEvent, ArtifactMetadata]:
        if (
            event.event_id != artifact.producer_event_id
            or event.artifact_id != artifact.artifact_id
            or event.identity != artifact.identity
            or event.kind is not ExecutionEventKind.ARTIFACT_PRODUCED
        ):
            raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
        async with self._session_factory() as session, session.begin():
            allocation = await _load_allocation_model(session, artifact.identity, lock=True)
            if await session.get(ExecutionArtifactModel, artifact.artifact_id) is not None:
                raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
            requested = BudgetVector(artifact_bytes=artifact.byte_size)
            if not _fits_allocation(allocation, requested):
                raise GovernanceDeniedError(GovernanceErrorCode.BUDGET_EXHAUSTED)
            stored_event = await _append_event(session, event, locked_allocation=allocation)
            session.add(
                ExecutionArtifactModel(
                    id=artifact.artifact_id,
                    run_id=artifact.identity.run_id,
                    task_id=artifact.identity.task_id,
                    agent_id=artifact.identity.agent_id,
                    producer_event_id=artifact.producer_event_id,
                    kind=artifact.kind.value,
                    media_type=artifact.media_type,
                    byte_size=artifact.byte_size,
                    sha256=artifact.sha256,
                    lifecycle_status=artifact.lifecycle_status.value,
                )
            )
            allocation.used_artifact_bytes += artifact.byte_size
            await _flush_or_deny_invalid(session)
            return stored_event, artifact

    async def complete_allocation(
        self,
        *,
        identity: ExecutionIdentity,
        status: ExecutionRunStatus,
    ) -> bool:
        if status not in _TERMINAL_STATUSES:
            raise ValueError("execution completion status must be terminal")
        async with self._session_factory() as session, session.begin():
            allocation = await _load_allocation_model(session, identity, lock=True)
            if allocation.status != ExecutionRunStatus.RUNNING.value:
                return False
            active_child = await session.scalar(
                select(ExecutionAgentAllocationModel.agent_id)
                .where(
                    ExecutionAgentAllocationModel.run_id == identity.run_id,
                    ExecutionAgentAllocationModel.task_id == identity.task_id,
                    ExecutionAgentAllocationModel.parent_agent_id == identity.agent_id,
                    ExecutionAgentAllocationModel.status == ExecutionRunStatus.RUNNING.value,
                )
                .limit(1)
            )
            if active_child is not None:
                raise GovernanceDeniedError(GovernanceErrorCode.ALLOCATION_NOT_ACTIVE)
            active_reservation = await session.scalar(
                select(ExecutionBudgetReservationModel.id)
                .where(
                    ExecutionBudgetReservationModel.run_id == identity.run_id,
                    ExecutionBudgetReservationModel.task_id == identity.task_id,
                    ExecutionBudgetReservationModel.agent_id == identity.agent_id,
                    ExecutionBudgetReservationModel.status == "reserved",
                )
                .limit(1)
            )
            if active_reservation is not None:
                raise GovernanceDeniedError(GovernanceErrorCode.ALLOCATION_NOT_ACTIVE)
            allocation.status = status.value
            allocation.completed_at = datetime.now(UTC)
            if allocation.parent_agent_id is None:
                run = await session.get(ExecutionGovernedRunModel, identity.run_id)
                if run is None or run.task_id != identity.task_id:
                    raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
                run.status = status.value
                run.completed_at = allocation.completed_at
            else:
                parent = await _load_allocation_model(
                    session,
                    ExecutionIdentity(
                        run_id=identity.run_id,
                        task_id=identity.task_id,
                        agent_id=allocation.parent_agent_id,
                    ),
                    lock=True,
                )
                child_limits = _limits_from_allocation(allocation).ceiling_vector()
                _subtract_reserved(parent, child_limits)
                parent.reserved_child_count -= 1
                _add_child_actual_usage(parent, _usage_from_allocation(allocation))
            await session.flush()
            return True

    async def validate_artifact_scope(
        self,
        *,
        identity: ExecutionIdentity,
        artifact_ids: tuple[UUID, ...],
    ) -> bool:
        if not artifact_ids:
            return False
        async with self._session_factory() as session:
            rows = tuple(
                await session.scalars(
                    select(ExecutionArtifactModel.id).where(
                        ExecutionArtifactModel.id.in_(artifact_ids),
                        ExecutionArtifactModel.run_id == identity.run_id,
                        ExecutionArtifactModel.task_id == identity.task_id,
                        ExecutionArtifactModel.lifecycle_status
                        == ArtifactLifecycleStatus.ACTIVE.value,
                    )
                )
            )
        return len(rows) == len(artifact_ids)

    async def list_timeline(
        self,
        *,
        run_id: UUID,
        limit: int = 200,
        max_bytes: int = 128 * 1024,
    ) -> tuple[SafeExecutionEvent, ...]:
        if not 1 <= limit <= 200 or not 1 <= max_bytes <= 128 * 1024:
            raise ValueError("execution timeline bounds are invalid")
        async with self._session_factory() as session:
            models = tuple(
                await session.scalars(
                    select(ExecutionTraceEventModel)
                    .where(ExecutionTraceEventModel.run_id == run_id)
                    .order_by(
                        ExecutionTraceEventModel.created_at,
                        ExecutionTraceEventModel.id,
                    )
                    .limit(limit)
                )
            )
        events: list[SafeExecutionEvent] = []
        total_bytes = 2
        for event in _causal_event_order(tuple(_event_from_model(model) for model in models)):
            event_bytes = len(
                json.dumps(
                    event.as_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ).encode("utf-8")
            )
            if total_bytes + event_bytes > max_bytes:
                break
            total_bytes += event_bytes
            events.append(event)
        return tuple(events)


async def _append_event(
    session: AsyncSession,
    draft: SafeEventDraft,
    *,
    locked_allocation: ExecutionAgentAllocationModel | None = None,
) -> SafeExecutionEvent:
    allocation = locked_allocation or await _load_allocation_model(
        session, draft.identity, lock=True
    )
    if allocation.status != ExecutionRunStatus.RUNNING.value:
        raise GovernanceDeniedError(GovernanceErrorCode.ALLOCATION_NOT_ACTIVE)
    duplicate = await session.get(ExecutionTraceEventModel, draft.event_id)
    if duplicate is not None:
        raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
    seq_no = allocation.next_seq_no
    if draft.kind is ExecutionEventKind.RUN_STARTED:
        raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
    if draft.parent_event_id is None:
        raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
    parent = await session.scalar(
        select(ExecutionTraceEventModel).where(
            ExecutionTraceEventModel.id == draft.parent_event_id,
            ExecutionTraceEventModel.run_id == draft.identity.run_id,
            ExecutionTraceEventModel.task_id == draft.identity.task_id,
        )
    )
    if parent is None or ExecutionEventKind(parent.kind) not in _ALLOWED_PARENT_KINDS.get(
        draft.kind, frozenset()
    ):
        raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
    if seq_no == 0 and (
        allocation.parent_event_id != draft.parent_event_id
        or draft.kind is not ExecutionEventKind.NODE_STARTED
    ):
        raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
    event = draft.materialize(seq_no)
    session.add(
        ExecutionTraceEventModel(
            id=event.event_id,
            run_id=event.identity.run_id,
            task_id=event.identity.task_id,
            agent_id=event.identity.agent_id,
            seq_no=event.seq_no,
            kind=event.kind.value,
            status=event.status.value,
            parent_event_id=event.parent_event_id,
            artifact_id=event.artifact_id,
            target_name=event.target_name,
            provider_name=event.provider_name,
            model_name=event.model_name,
            error_code=event.error_code,
            duration_ms=event.duration_ms,
            model_turns=event.model_turns,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            tool_calls=event.tool_calls,
            result_bytes=event.result_bytes,
        )
    )
    allocation.next_seq_no += 1
    await _flush_or_deny_invalid(session)
    return event


async def _flush_or_deny_invalid(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError:
        raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT) from None


async def _load_allocation(
    session: AsyncSession,
    identity: ExecutionIdentity,
    *,
    lock: bool,
) -> AllocationSnapshot:
    return _allocation_snapshot(await _load_allocation_model(session, identity, lock=lock))


async def _load_allocation_model(
    session: AsyncSession,
    identity: ExecutionIdentity,
    *,
    lock: bool,
) -> ExecutionAgentAllocationModel:
    statement = select(ExecutionAgentAllocationModel).where(
        ExecutionAgentAllocationModel.run_id == identity.run_id,
        ExecutionAgentAllocationModel.task_id == identity.task_id,
        ExecutionAgentAllocationModel.agent_id == identity.agent_id,
    )
    if lock:
        statement = statement.with_for_update()
    model = await session.scalar(statement)
    if model is None:
        raise GovernanceDeniedError(GovernanceErrorCode.ALLOCATION_NOT_ACTIVE)
    return model


def _allocation_snapshot(model: ExecutionAgentAllocationModel) -> AllocationSnapshot:
    return AllocationSnapshot(
        identity=ExecutionIdentity(
            run_id=model.run_id,
            task_id=model.task_id,
            agent_id=model.agent_id,
        ),
        role=ExecutionRole(model.role),
        status=ExecutionRunStatus(model.status),
        depth=model.depth,
        parent_agent_id=model.parent_agent_id,
        parent_event_id=model.parent_event_id,
        limits=_limits_from_allocation(model),
        usage=_usage_from_allocation(model),
        child_reserved=_reserved_from_allocation(model),
        reserved_child_count=model.reserved_child_count,
        next_seq_no=model.next_seq_no,
    )


def _limits_from_run(model: ExecutionGovernedRunModel) -> BudgetLimits:
    return BudgetLimits(
        elapsed_ms=model.limit_elapsed_ms,
        model_turns=model.limit_model_turns,
        input_tokens=model.limit_input_tokens,
        output_tokens=model.limit_output_tokens,
        tool_calls=model.limit_tool_calls,
        tool_result_bytes=model.limit_tool_result_bytes,
        artifact_bytes=model.limit_artifact_bytes,
        max_children=model.limit_children,
        max_depth=model.max_depth,
        allow_child_agents=model.allow_child_agents,
    )


def _limits_from_allocation(model: ExecutionAgentAllocationModel) -> BudgetLimits:
    return BudgetLimits(
        elapsed_ms=model.limit_elapsed_ms,
        model_turns=model.limit_model_turns,
        input_tokens=model.limit_input_tokens,
        output_tokens=model.limit_output_tokens,
        tool_calls=model.limit_tool_calls,
        tool_result_bytes=model.limit_tool_result_bytes,
        artifact_bytes=model.limit_artifact_bytes,
        max_children=model.limit_children,
        max_depth=model.max_depth,
        allow_child_agents=model.allow_child_agents,
    )


def _limit_model_values(limits: BudgetLimits) -> dict[str, int | bool]:
    return {
        "limit_elapsed_ms": limits.elapsed_ms,
        "limit_model_turns": limits.model_turns,
        "limit_input_tokens": limits.input_tokens,
        "limit_output_tokens": limits.output_tokens,
        "limit_tool_calls": limits.tool_calls,
        "limit_tool_result_bytes": limits.tool_result_bytes,
        "limit_artifact_bytes": limits.artifact_bytes,
        "limit_children": limits.max_children,
        "max_depth": limits.max_depth,
        "allow_child_agents": limits.allow_child_agents,
    }


def _usage_from_allocation(model: ExecutionAgentAllocationModel) -> BudgetUsage:
    return BudgetUsage(
        elapsed_ms=model.used_elapsed_ms,
        model_turns=model.used_model_turns,
        input_tokens=model.used_input_tokens,
        output_tokens=model.used_output_tokens,
        tool_calls=model.used_tool_calls,
        tool_result_bytes=model.used_tool_result_bytes,
        artifact_bytes=model.used_artifact_bytes,
        child_count=model.used_child_count,
    )


def _reserved_from_allocation(model: ExecutionAgentAllocationModel) -> BudgetVector:
    return BudgetVector(
        elapsed_ms=model.reserved_elapsed_ms,
        model_turns=model.reserved_model_turns,
        input_tokens=model.reserved_input_tokens,
        output_tokens=model.reserved_output_tokens,
        tool_calls=model.reserved_tool_calls,
        tool_result_bytes=model.reserved_tool_result_bytes,
        artifact_bytes=model.reserved_artifact_bytes,
    )


def _fits_allocation(model: ExecutionAgentAllocationModel, requested: BudgetVector) -> bool:
    if model.used_input_tokens is None and requested.input_tokens:
        return False
    if model.used_output_tokens is None and requested.output_tokens:
        return False
    return all(
        used + reserved + wanted <= ceiling
        for used, reserved, wanted, ceiling in (
            (
                model.used_elapsed_ms,
                model.reserved_elapsed_ms,
                requested.elapsed_ms,
                model.limit_elapsed_ms,
            ),
            (
                model.used_model_turns,
                model.reserved_model_turns,
                requested.model_turns,
                model.limit_model_turns,
            ),
            (
                model.used_input_tokens or 0,
                model.reserved_input_tokens,
                requested.input_tokens,
                model.limit_input_tokens,
            ),
            (
                model.used_output_tokens or 0,
                model.reserved_output_tokens,
                requested.output_tokens,
                model.limit_output_tokens,
            ),
            (
                model.used_tool_calls,
                model.reserved_tool_calls,
                requested.tool_calls,
                model.limit_tool_calls,
            ),
            (
                model.used_tool_result_bytes,
                model.reserved_tool_result_bytes,
                requested.tool_result_bytes,
                model.limit_tool_result_bytes,
            ),
            (
                model.used_artifact_bytes,
                model.reserved_artifact_bytes,
                requested.artifact_bytes,
                model.limit_artifact_bytes,
            ),
        )
    )


def _add_reserved(model: ExecutionAgentAllocationModel, values: BudgetVector) -> None:
    model.reserved_elapsed_ms += values.elapsed_ms
    model.reserved_model_turns += values.model_turns
    model.reserved_input_tokens += values.input_tokens
    model.reserved_output_tokens += values.output_tokens
    model.reserved_tool_calls += values.tool_calls
    model.reserved_tool_result_bytes += values.tool_result_bytes
    model.reserved_artifact_bytes += values.artifact_bytes


def _subtract_reserved(model: ExecutionAgentAllocationModel, values: BudgetVector) -> None:
    model.reserved_elapsed_ms -= values.elapsed_ms
    model.reserved_model_turns -= values.model_turns
    model.reserved_input_tokens -= values.input_tokens
    model.reserved_output_tokens -= values.output_tokens
    model.reserved_tool_calls -= values.tool_calls
    model.reserved_tool_result_bytes -= values.tool_result_bytes
    model.reserved_artifact_bytes -= values.artifact_bytes


def _replace_reserved_usage_with_actual(
    model: ExecutionAgentAllocationModel,
    *,
    reserved: BudgetVector,
    actual: BudgetUsage,
) -> None:
    _subtract_reserved(model, reserved)
    model.used_elapsed_ms += actual.elapsed_ms
    model.used_model_turns += actual.model_turns
    model.used_input_tokens = _sum_known_tokens(model.used_input_tokens, actual.input_tokens)
    model.used_output_tokens = _sum_known_tokens(model.used_output_tokens, actual.output_tokens)
    model.used_tool_calls += actual.tool_calls
    model.used_tool_result_bytes += actual.tool_result_bytes
    model.used_artifact_bytes += actual.artifact_bytes


def _add_child_actual_usage(
    parent: ExecutionAgentAllocationModel,
    actual: BudgetUsage,
) -> None:
    parent.used_elapsed_ms += actual.elapsed_ms
    parent.used_model_turns += actual.model_turns
    parent.used_input_tokens = _sum_known_tokens(parent.used_input_tokens, actual.input_tokens)
    parent.used_output_tokens = _sum_known_tokens(parent.used_output_tokens, actual.output_tokens)
    parent.used_tool_calls += actual.tool_calls
    parent.used_tool_result_bytes += actual.tool_result_bytes
    parent.used_artifact_bytes += actual.artifact_bytes
    parent.used_child_count += 1


def _sum_known_tokens(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    return left + right


def _reserved_model_values(values: BudgetVector) -> dict[str, int]:
    return {
        "reserved_elapsed_ms": values.elapsed_ms,
        "reserved_model_turns": values.model_turns,
        "reserved_input_tokens": values.input_tokens,
        "reserved_output_tokens": values.output_tokens,
        "reserved_tool_calls": values.tool_calls,
        "reserved_tool_result_bytes": values.tool_result_bytes,
        "reserved_artifact_bytes": values.artifact_bytes,
    }


def _reserved_from_reservation(model: ExecutionBudgetReservationModel) -> BudgetVector:
    return BudgetVector(
        elapsed_ms=model.reserved_elapsed_ms,
        model_turns=model.reserved_model_turns,
        input_tokens=model.reserved_input_tokens,
        output_tokens=model.reserved_output_tokens,
        tool_calls=model.reserved_tool_calls,
        tool_result_bytes=model.reserved_tool_result_bytes,
        artifact_bytes=model.reserved_artifact_bytes,
    )


def _reservation_identity(model: ExecutionBudgetReservationModel) -> ExecutionIdentity:
    return ExecutionIdentity(run_id=model.run_id, task_id=model.task_id, agent_id=model.agent_id)


def _reservation_snapshot(model: ExecutionBudgetReservationModel) -> BudgetReservationSnapshot:
    return BudgetReservationSnapshot(
        reservation_id=model.id,
        identity=_reservation_identity(model),
        reserved=_reserved_from_reservation(model),
        reconciled=model.status == "reconciled",
    )


def _actual_from_reservation(model: ExecutionBudgetReservationModel) -> BudgetUsage:
    if (
        model.actual_elapsed_ms is None
        or model.actual_model_turns is None
        or model.actual_tool_calls is None
        or model.actual_tool_result_bytes is None
        or model.actual_artifact_bytes is None
    ):
        raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
    return BudgetUsage(
        elapsed_ms=model.actual_elapsed_ms,
        model_turns=model.actual_model_turns,
        input_tokens=model.actual_input_tokens,
        output_tokens=model.actual_output_tokens,
        tool_calls=model.actual_tool_calls,
        tool_result_bytes=model.actual_tool_result_bytes,
        artifact_bytes=model.actual_artifact_bytes,
    )


def _actual_fits_reservation(actual: BudgetUsage, reserved: BudgetVector) -> bool:
    return (
        actual.elapsed_ms <= reserved.elapsed_ms
        and actual.model_turns <= reserved.model_turns
        and (actual.input_tokens is None or actual.input_tokens <= reserved.input_tokens)
        and (actual.output_tokens is None or actual.output_tokens <= reserved.output_tokens)
        and actual.tool_calls <= reserved.tool_calls
        and actual.tool_result_bytes <= reserved.tool_result_bytes
        and actual.artifact_bytes <= reserved.artifact_bytes
    )


def _event_from_model(model: ExecutionTraceEventModel) -> SafeExecutionEvent:
    return SafeExecutionEvent(
        identity=ExecutionIdentity(
            run_id=model.run_id,
            task_id=model.task_id,
            agent_id=model.agent_id,
        ),
        event_id=model.id,
        seq_no=model.seq_no,
        kind=ExecutionEventKind(model.kind),
        status=ExecutionEventStatus(model.status),
        parent_event_id=model.parent_event_id,
        artifact_id=model.artifact_id,
        target_name=model.target_name,
        provider_name=model.provider_name,
        model_name=model.model_name,
        error_code=model.error_code,
        duration_ms=model.duration_ms,
        model_turns=model.model_turns,
        input_tokens=model.input_tokens,
        output_tokens=model.output_tokens,
        tool_calls=model.tool_calls,
        result_bytes=model.result_bytes,
    )


def _causal_event_order(
    events: tuple[SafeExecutionEvent, ...],
) -> tuple[SafeExecutionEvent, ...]:
    remaining = {event.event_id: event for event in events}
    ordered: list[SafeExecutionEvent] = []
    emitted: set[UUID] = set()
    while remaining:
        ready = sorted(
            (
                event
                for event in remaining.values()
                if event.parent_event_id is None or event.parent_event_id in emitted
            ),
            key=lambda event: (event.identity.agent_id, event.seq_no, str(event.event_id)),
        )
        if not ready:
            raise GovernanceDeniedError(GovernanceErrorCode.INVALID_EVENT)
        for event in ready:
            ordered.append(event)
            emitted.add(event.event_id)
            remaining.pop(event.event_id)
    return tuple(ordered)
