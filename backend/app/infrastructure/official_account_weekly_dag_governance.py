from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.execution_governance import ExecutionGovernanceRepository
from app.application.ports.official_account_weekly_dag import (
    WeeklyDagGovernance,
    WeeklyDagGovernedResult,
    WeeklyDagNodeFailure,
    WeeklyDagNodeHandler,
    WeeklyDagNodeResult,
)
from app.application.services.execution_governance import (
    CapabilityGateway,
    CapabilityRegistry,
    ExecutionGovernanceService,
    GovernedCapabilityResult,
)
from app.domain.execution_governance import (
    ArtifactKind,
    BudgetLimits,
    BudgetUsage,
    CapabilityAccess,
    CapabilityDefinition,
    CapabilityRequest,
    ExecutionEventKind,
    ExecutionEventStatus,
    ExecutionIdentity,
    ExecutionRole,
    ExecutionRunStatus,
    GovernanceDeniedError,
    GovernanceErrorCode,
    SafeEventDraft,
)
from app.domain.official_account_weekly_dag import (
    WEEKLY_DAG_NODES,
    WEEKLY_DAG_ROOT_AGENT_ID,
    WeeklyDagClaim,
    WeeklyDagErrorCode,
    WeeklyDagNodeKind,
    WeeklyDagRunStatus,
    WeeklyDagStatusProjection,
    weekly_dag_attempt_agent_id,
)
from app.infrastructure.db.models import (
    ExecutionAgentAllocationModel,
    ExecutionBudgetReservationModel,
    ExecutionTraceEventModel,
    OfficialAccountWeeklyDagAttemptModel,
)

_ROOT_AGENT_ID = WEEKLY_DAG_ROOT_AGENT_ID
_ROOT_TARGET = "weekly.dag"
_CAPABILITY_TIMEOUT_MS = 15 * 60 * 1000
_CAPABILITY_RESULT_BYTES = 16 * 1024


def weekly_dag_root_limits() -> BudgetLimits:
    return BudgetLimits(
        elapsed_ms=60 * 60 * 1000,
        model_turns=0,
        input_tokens=0,
        output_tokens=0,
        tool_calls=128,
        tool_result_bytes=64 * 1024 * 1024,
        artifact_bytes=16 * 1024 * 1024 * 1024,
        max_children=64,
        max_depth=1,
        allow_child_agents=True,
    )


def weekly_dag_node_limits() -> BudgetLimits:
    return BudgetLimits(
        elapsed_ms=_CAPABILITY_TIMEOUT_MS,
        model_turns=0,
        input_tokens=0,
        output_tokens=0,
        tool_calls=1,
        tool_result_bytes=_CAPABILITY_RESULT_BYTES,
        artifact_bytes=512 * 1024 * 1024,
        max_children=0,
        max_depth=1,
        allow_child_agents=False,
    )


def weekly_dag_capability_registry() -> CapabilityRegistry:
    names = sorted({node.capability_name for node in WEEKLY_DAG_NODES})
    return CapabilityRegistry(
        CapabilityDefinition(
            name=name,
            access=CapabilityAccess.BUSINESS_WRITE,
            allowed_roles=frozenset({ExecutionRole.WORKER}),
            timeout_ms=_CAPABILITY_TIMEOUT_MS,
            max_argument_bytes=32 * 1024,
            max_result_bytes=_CAPABILITY_RESULT_BYTES,
            task_scoped=True,
            artifact_scoped=name not in {"weekly.schedule"},
        )
        for name in names
    )


@dataclass(frozen=True, slots=True)
class _HandlerOutcome:
    result: WeeklyDagNodeResult | None
    failure: WeeklyDagNodeFailure | None


class PostgresOfficialAccountWeeklyDagGovernance(WeeklyDagGovernance):
    def __init__(
        self,
        *,
        repository: ExecutionGovernanceRepository,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._repository = repository
        self._session_factory = session_factory
        self._service = ExecutionGovernanceService(repository)
        self._gateway = CapabilityGateway(
            repository=repository,
            registry=weekly_dag_capability_registry(),
        )

    async def ensure_run(
        self,
        *,
        run_id: UUID,
        task_id: str,
        request_fingerprint: str,
    ) -> None:
        allocation, root = await self._service.create_run(
            task_id=task_id,
            root_agent_id=_ROOT_AGENT_ID,
            role=ExecutionRole.ORCHESTRATOR,
            limits=weekly_dag_root_limits(),
            request_fingerprint=request_fingerprint,
            run_id=run_id,
        )
        timeline = await self._repository.list_timeline(run_id=run_id, limit=200)
        if any(
            event.identity == allocation.identity
            and event.kind is ExecutionEventKind.NODE_STARTED
            and event.target_name == _ROOT_TARGET
            for event in timeline
        ):
            return
        try:
            await self._repository.append_event(
                SafeEventDraft(
                    identity=allocation.identity,
                    event_id=uuid4(),
                    kind=ExecutionEventKind.NODE_STARTED,
                    status=ExecutionEventStatus.STARTED,
                    parent_event_id=root.event_id,
                    target_name=_ROOT_TARGET,
                )
            )
        except GovernanceDeniedError as error:
            if error.code is not GovernanceErrorCode.ALLOCATION_NOT_ACTIVE:
                raise

    async def execute_node(
        self,
        *,
        claim: WeeklyDagClaim,
        handler: WeeklyDagNodeHandler,
    ) -> WeeklyDagGovernedResult:
        await self._recover_stale_children(claim.run.run_id, claim.run.task_id)
        root_identity = ExecutionIdentity(
            run_id=claim.run.run_id,
            task_id=claim.run.task_id,
            agent_id=_ROOT_AGENT_ID,
        )
        parent_event_id = await self._parent_event_id(claim)
        agent_id = weekly_dag_attempt_agent_id(
            claim.node.definition.key,
            claim.node.attempt_count,
        )
        try:
            allocation = await self._service.allocate_child(
                parent=root_identity,
                child_agent_id=agent_id,
                role=ExecutionRole.WORKER,
                limits=weekly_dag_node_limits(),
                parent_event_id=parent_event_id,
            )
        except GovernanceDeniedError as error:
            trace_event_id = await self._append_root_denial(
                identity=root_identity,
                parent_event_id=parent_event_id,
                target_name=claim.node.definition.capability_name,
                error=error,
            )
            raise WeeklyDagNodeFailure(
                _weekly_error_code(error.code),
                retryable=False,
                trace_event_id=trace_event_id,
            ) from None
        child_start = await self._repository.append_event(
            SafeEventDraft(
                identity=allocation.identity,
                event_id=uuid4(),
                kind=ExecutionEventKind.NODE_STARTED,
                status=ExecutionEventStatus.STARTED,
                parent_event_id=parent_event_id,
                target_name=claim.node.definition.capability_name,
            )
        )

        async def bounded_handler() -> GovernedCapabilityResult[_HandlerOutcome]:
            try:
                result = await handler(claim)
            except WeeklyDagNodeFailure as error:
                outcome = _HandlerOutcome(result=None, failure=error)
            except Exception:
                outcome = _HandlerOutcome(
                    result=None,
                    failure=WeeklyDagNodeFailure(
                        WeeklyDagErrorCode.CAPABILITY_FAILED.value,
                        retryable=True,
                    ),
                )
            else:
                if (
                    result.model_turns
                    or result.input_tokens not in {0, None}
                    or (result.output_tokens not in {0, None})
                ):
                    outcome = _HandlerOutcome(
                        result=None,
                        failure=WeeklyDagNodeFailure(
                            WeeklyDagErrorCode.BUDGET_EXHAUSTED.value,
                            retryable=False,
                        ),
                    )
                else:
                    outcome = _HandlerOutcome(result=result, failure=None)
            result_bytes = len(_outcome_fingerprint_bytes(outcome))
            return GovernedCapabilityResult(
                value=outcome,
                result_bytes=result_bytes,
                artifact_bytes=0,
                input_tokens=0,
                output_tokens=0,
                model_turns=0,
            )

        request = CapabilityRequest(
            identity=allocation.identity,
            role=ExecutionRole.WORKER,
            capability_name=claim.node.definition.capability_name,
            target_task_id=claim.run.task_id,
            parent_event_id=child_start.event_id,
            argument_bytes=_claim_argument_bytes(claim),
            artifact_ids=tuple(
                artifact_id
                for dependency in claim.dependencies
                if (artifact_id := dependency.execution_artifact_id) is not None
            ),
            expected_input_tokens=0,
            expected_output_tokens=0,
            model_turns=0,
            tool_calls=1,
            expected_artifact_bytes=0,
        )
        try:
            governed = await self._gateway.invoke(request, bounded_handler)
        except GovernanceDeniedError as error:
            trace_event_id = await self._fail_child(
                identity=allocation.identity,
                parent_event_id=child_start.event_id,
                target_name=claim.node.definition.capability_name,
                error_code=_weekly_error_code(error.code),
            )
            raise WeeklyDagNodeFailure(
                _weekly_error_code(error.code),
                retryable=error.code
                in {
                    GovernanceErrorCode.CAPABILITY_FAILED,
                    GovernanceErrorCode.CAPABILITY_TIMEOUT,
                },
                trace_event_id=trace_event_id,
            ) from None
        outcome = governed.value
        if outcome.failure is not None:
            trace_event_id = await self._fail_child(
                identity=allocation.identity,
                parent_event_id=child_start.event_id,
                target_name=claim.node.definition.capability_name,
                error_code=outcome.failure.error_code,
            )
            raise WeeklyDagNodeFailure(
                outcome.failure.error_code,
                retryable=outcome.failure.retryable,
                trace_event_id=trace_event_id,
            )
        if outcome.result is None:
            raise AssertionError("weekly DAG governed outcome is incomplete")
        result = outcome.result
        try:
            artifact_event, artifact = await self._service.produce_artifact(
                identity=allocation.identity,
                parent_event_id=child_start.event_id,
                kind=_artifact_kind(claim.node.definition.kind),
                media_type=result.artifact.media_type,
                byte_size=result.artifact.byte_size,
                sha256=result.artifact.fingerprint,
            )
        except GovernanceDeniedError as error:
            trace_event_id = await self._fail_child(
                identity=allocation.identity,
                parent_event_id=child_start.event_id,
                target_name=claim.node.definition.capability_name,
                error_code=_weekly_error_code(error.code),
            )
            raise WeeklyDagNodeFailure(
                _weekly_error_code(error.code),
                retryable=False,
                trace_event_id=trace_event_id,
            ) from None
        child_finish = await self._repository.append_event(
            SafeEventDraft(
                identity=allocation.identity,
                event_id=uuid4(),
                kind=ExecutionEventKind.NODE_FINISHED,
                status=ExecutionEventStatus.SUCCEEDED,
                parent_event_id=artifact_event.event_id,
                target_name=claim.node.definition.capability_name,
                model_turns=0,
                input_tokens=0,
                output_tokens=0,
                tool_calls=1,
                result_bytes=min(result.artifact.byte_size, _CAPABILITY_RESULT_BYTES),
            )
        )
        await self._repository.complete_allocation(
            identity=allocation.identity,
            status=ExecutionRunStatus.SUCCEEDED,
        )
        root_bridge_start = await self._repository.append_event(
            SafeEventDraft(
                identity=root_identity,
                event_id=uuid4(),
                kind=ExecutionEventKind.NODE_STARTED,
                status=ExecutionEventStatus.SUCCEEDED,
                parent_event_id=child_finish.event_id,
                target_name=claim.node.definition.capability_name,
            )
        )
        root_bridge = await self._repository.append_event(
            SafeEventDraft(
                identity=root_identity,
                event_id=uuid4(),
                kind=ExecutionEventKind.NODE_FINISHED,
                status=ExecutionEventStatus.SUCCEEDED,
                parent_event_id=root_bridge_start.event_id,
                target_name=claim.node.definition.capability_name,
                result_bytes=min(result.artifact.byte_size, _CAPABILITY_RESULT_BYTES),
            )
        )
        return WeeklyDagGovernedResult(
            result=result,
            execution_artifact_id=artifact.artifact_id,
            trace_event_id=root_bridge.event_id,
        )

    async def complete_run(self, status: WeeklyDagStatusProjection) -> None:
        if status.run.status not in {
            WeeklyDagRunStatus.READY,
            WeeklyDagRunStatus.TERMINAL_FAILED,
        }:
            return
        async with self._session_factory() as session, session.begin():
            await session.execute(
                select(func.pg_advisory_xact_lock(_advisory_lock_key(status.run.run_id)))
            )
            await self._complete_run_locked(status)

    async def _complete_run_locked(self, status: WeeklyDagStatusProjection) -> None:
        await self._recover_stale_children(
            status.run.run_id,
            status.run.task_id,
        )
        identity = ExecutionIdentity(
            run_id=status.run.run_id,
            task_id=status.run.task_id,
            agent_id=_ROOT_AGENT_ID,
        )
        allocation = await self._repository.get_allocation(identity)
        if allocation.status is not ExecutionRunStatus.RUNNING or allocation.reserved_child_count:
            return
        succeeded = status.run.status is WeeklyDagRunStatus.READY
        terminal = next(
            (
                node
                for node in reversed(status.nodes)
                if node.trace_event_id is not None
                and node.status.value == ("succeeded" if succeeded else "terminal_failed")
            ),
            None,
        )
        if terminal is None or terminal.trace_event_id is None:
            parent_event_id = await self._root_node_start(identity)
            terminal_event = await self._repository.append_event(
                SafeEventDraft(
                    identity=identity,
                    event_id=uuid4(),
                    kind=ExecutionEventKind.NODE_FAILED,
                    status=ExecutionEventStatus.FAILED,
                    parent_event_id=parent_event_id,
                    target_name=_ROOT_TARGET,
                    error_code=WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
                )
            )
            parent_event_id = terminal_event.event_id
        else:
            parent_event_id = terminal.trace_event_id
        await self._repository.append_event(
            SafeEventDraft(
                identity=identity,
                event_id=uuid4(),
                kind=(
                    ExecutionEventKind.RUN_FINISHED if succeeded else ExecutionEventKind.RUN_FAILED
                ),
                status=(
                    ExecutionEventStatus.SUCCEEDED if succeeded else ExecutionEventStatus.FAILED
                ),
                parent_event_id=parent_event_id,
                target_name=_ROOT_TARGET,
                error_code=(
                    None
                    if succeeded
                    else (
                        terminal.error_code
                        if terminal is not None and terminal.error_code is not None
                        else WeeklyDagErrorCode.INVALID_CHECKPOINT.value
                    )
                ),
            )
        )
        try:
            await self._repository.complete_allocation(
                identity=identity,
                status=(ExecutionRunStatus.SUCCEEDED if succeeded else ExecutionRunStatus.FAILED),
            )
        except GovernanceDeniedError as error:
            if error.code is not GovernanceErrorCode.ALLOCATION_NOT_ACTIVE:
                raise

    async def abandon_node(self, claim: WeeklyDagClaim) -> None:
        identity = ExecutionIdentity(
            run_id=claim.run.run_id,
            task_id=claim.run.task_id,
            agent_id=weekly_dag_attempt_agent_id(
                claim.node.definition.key,
                claim.node.attempt_count,
            ),
        )
        try:
            allocation = await self._repository.get_allocation(identity)
        except GovernanceDeniedError:
            return
        if allocation.status is not ExecutionRunStatus.RUNNING:
            return
        await self._reconcile_open_reservations(identity)
        async with self._session_factory() as session:
            child_start_id = await session.scalar(
                select(ExecutionTraceEventModel.id)
                .where(
                    ExecutionTraceEventModel.run_id == identity.run_id,
                    ExecutionTraceEventModel.task_id == identity.task_id,
                    ExecutionTraceEventModel.agent_id == identity.agent_id,
                    ExecutionTraceEventModel.kind == ExecutionEventKind.NODE_STARTED.value,
                )
                .order_by(ExecutionTraceEventModel.seq_no)
                .limit(1)
            )
        if child_start_id is None and allocation.parent_event_id is not None:
            try:
                child_start = await self._repository.append_event(
                    SafeEventDraft(
                        identity=identity,
                        event_id=uuid4(),
                        kind=ExecutionEventKind.NODE_STARTED,
                        status=ExecutionEventStatus.STARTED,
                        parent_event_id=allocation.parent_event_id,
                        target_name=claim.node.definition.capability_name,
                    )
                )
                child_start_id = child_start.event_id
            except GovernanceDeniedError:
                child_start_id = None
        if child_start_id is not None:
            await self._fail_child(
                identity=identity,
                parent_event_id=child_start_id,
                target_name=claim.node.definition.capability_name,
                error_code=WeeklyDagErrorCode.LEASE_LOST.value,
            )
            return
        try:
            await self._repository.complete_allocation(
                identity=identity,
                status=ExecutionRunStatus.CANCELLED,
            )
        except GovernanceDeniedError:
            return

    async def _parent_event_id(self, claim: WeeklyDagClaim) -> UUID:
        if not claim.dependencies:
            return await self._root_node_start(
                ExecutionIdentity(
                    run_id=claim.run.run_id,
                    task_id=claim.run.task_id,
                    agent_id=_ROOT_AGENT_ID,
                )
            )
        parent = claim.dependencies[-1].trace_event_id
        if parent is None:
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.INVALID_DEPENDENCY.value,
                retryable=False,
            )
        return parent

    async def _root_node_start(self, identity: ExecutionIdentity) -> UUID:
        timeline = await self._repository.list_timeline(run_id=identity.run_id, limit=200)
        event = next(
            (
                item
                for item in timeline
                if item.identity == identity
                and item.kind is ExecutionEventKind.NODE_STARTED
                and item.target_name == _ROOT_TARGET
            ),
            None,
        )
        if event is None:
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.INVALID_CHECKPOINT.value,
                retryable=False,
            )
        return event.event_id

    async def _append_root_denial(
        self,
        *,
        identity: ExecutionIdentity,
        parent_event_id: UUID,
        target_name: str,
        error: GovernanceDeniedError,
    ) -> UUID | None:
        try:
            event = await self._repository.append_event(
                SafeEventDraft(
                    identity=identity,
                    event_id=uuid4(),
                    kind=(
                        ExecutionEventKind.BUDGET_DENIED
                        if error.code
                        in {
                            GovernanceErrorCode.BUDGET_EXHAUSTED,
                            GovernanceErrorCode.DELEGATION_THRESHOLD_REACHED,
                            GovernanceErrorCode.CHILD_LIMIT_EXHAUSTED,
                        }
                        else ExecutionEventKind.PERMISSION_DENIED
                    ),
                    status=ExecutionEventStatus.DENIED,
                    parent_event_id=parent_event_id,
                    target_name=target_name,
                    error_code=error.code.value,
                )
            )
            return event.event_id
        except GovernanceDeniedError:
            return None

    async def _fail_child(
        self,
        *,
        identity: ExecutionIdentity,
        parent_event_id: UUID,
        target_name: str,
        error_code: str,
    ) -> UUID | None:
        event_id: UUID | None = None
        try:
            event = await self._repository.append_event(
                SafeEventDraft(
                    identity=identity,
                    event_id=uuid4(),
                    kind=ExecutionEventKind.NODE_FAILED,
                    status=ExecutionEventStatus.FAILED,
                    parent_event_id=parent_event_id,
                    target_name=target_name,
                    error_code=error_code,
                )
            )
            event_id = event.event_id
        except GovernanceDeniedError:
            pass
        try:
            await self._repository.complete_allocation(
                identity=identity,
                status=ExecutionRunStatus.FAILED,
            )
        except GovernanceDeniedError:
            pass
        return event_id

    async def _recover_stale_children(
        self,
        run_id: UUID,
        task_id: str,
        *,
        force: bool = False,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            allocations = tuple(
                await session.scalars(
                    select(ExecutionAgentAllocationModel).where(
                        ExecutionAgentAllocationModel.run_id == run_id,
                        ExecutionAgentAllocationModel.task_id == task_id,
                        ExecutionAgentAllocationModel.parent_agent_id == _ROOT_AGENT_ID,
                        ExecutionAgentAllocationModel.status == ExecutionRunStatus.RUNNING.value,
                    )
                )
            )
            attempts = tuple(
                await session.scalars(
                    select(OfficialAccountWeeklyDagAttemptModel).where(
                        OfficialAccountWeeklyDagAttemptModel.run_id == run_id,
                        OfficialAccountWeeklyDagAttemptModel.task_id == task_id,
                    )
                )
            )
        attempt_by_agent = {
            weekly_dag_attempt_agent_id(item.node_key, item.attempt_no): item for item in attempts
        }
        for allocation in allocations:
            attempt = attempt_by_agent.get(allocation.agent_id)
            if (
                not force
                and attempt is not None
                and (attempt.status == "running" and attempt.lease_expires_at >= now)
            ):
                continue
            identity = ExecutionIdentity(
                run_id=allocation.run_id,
                task_id=allocation.task_id,
                agent_id=allocation.agent_id,
            )
            await self._reconcile_open_reservations(identity)
            try:
                await self._repository.complete_allocation(
                    identity=identity,
                    status=ExecutionRunStatus.FAILED,
                )
            except GovernanceDeniedError:
                continue

    async def _reconcile_open_reservations(self, identity: ExecutionIdentity) -> None:
        async with self._session_factory() as session:
            reservations = tuple(
                await session.scalars(
                    select(ExecutionBudgetReservationModel).where(
                        ExecutionBudgetReservationModel.run_id == identity.run_id,
                        ExecutionBudgetReservationModel.task_id == identity.task_id,
                        ExecutionBudgetReservationModel.agent_id == identity.agent_id,
                        ExecutionBudgetReservationModel.status == "reserved",
                    )
                )
            )
        for reservation in reservations:
            await self._repository.reconcile_budget(
                identity=identity,
                reservation_id=reservation.id,
                actual=BudgetUsage(
                    elapsed_ms=reservation.reserved_elapsed_ms,
                    model_turns=reservation.reserved_model_turns,
                    input_tokens=reservation.reserved_input_tokens,
                    output_tokens=reservation.reserved_output_tokens,
                    tool_calls=reservation.reserved_tool_calls,
                    tool_result_bytes=reservation.reserved_tool_result_bytes,
                    artifact_bytes=reservation.reserved_artifact_bytes,
                ),
            )


def _artifact_kind(kind: WeeklyDagNodeKind) -> ArtifactKind:
    if kind in {WeeklyDagNodeKind.RENDER_HANDOFF, WeeklyDagNodeKind.VALIDATE_CHILD}:
        return ArtifactKind.ARTICLE
    if kind in {WeeklyDagNodeKind.AGGREGATE, WeeklyDagNodeKind.FINALIZE}:
        return ArtifactKind.REPORT
    return ArtifactKind.CHECKPOINT


def _advisory_lock_key(run_id: UUID) -> int:
    return run_id.int & ((1 << 63) - 1)


def _weekly_error_code(code: GovernanceErrorCode) -> str:
    if code is GovernanceErrorCode.BUDGET_EXHAUSTED:
        return WeeklyDagErrorCode.BUDGET_EXHAUSTED.value
    if code is GovernanceErrorCode.CAPABILITY_TIMEOUT:
        return WeeklyDagErrorCode.CAPABILITY_TIMEOUT.value
    if code is GovernanceErrorCode.CAPABILITY_FAILED:
        return WeeklyDagErrorCode.CAPABILITY_FAILED.value
    return WeeklyDagErrorCode.PERMISSION_DENIED.value


def _claim_argument_bytes(claim: WeeklyDagClaim) -> int:
    return len(
        (
            claim.run.request_fingerprint
            + claim.node.definition.key
            + (claim.node.input_fingerprint or "")
            + "".join(
                dependency.output_artifact.fingerprint
                for dependency in claim.dependencies
                if dependency.output_artifact is not None
            )
        ).encode()
    )


def _outcome_fingerprint_bytes(outcome: _HandlerOutcome) -> bytes:
    if outcome.result is not None:
        value = (
            outcome.result.artifact.opaque_ref
            + outcome.result.artifact.fingerprint
            + str(outcome.result.artifact.byte_size)
        )
    elif outcome.failure is not None:
        value = outcome.failure.error_code
    else:
        value = "invalid"
    return sha256(value.encode()).digest()
