from __future__ import annotations

import asyncio
from hashlib import sha256
from uuid import uuid4

import pytest
from app.application.services.execution_governance import ExecutionGovernanceService
from app.domain.execution_governance import (
    ArtifactKind,
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
)
from app.infrastructure.db.execution_governance import (
    PostgresExecutionGovernanceRepository,
)
from app.infrastructure.db.models import (
    ExecutionAgentAllocationModel,
    ExecutionArtifactModel,
    ExecutionBudgetReservationModel,
    ExecutionGovernedRunModel,
    ExecutionTraceEventModel,
)
from sqlalchemy import delete

from .conftest import IntegrationContext


def _root_limits() -> BudgetLimits:
    return BudgetLimits(
        elapsed_ms=10_000,
        model_turns=10,
        input_tokens=10_000,
        output_tokens=5_000,
        tool_calls=10,
        tool_result_bytes=10_000,
        artifact_bytes=10_000,
        max_children=5,
        max_depth=1,
        allow_child_agents=True,
    )


def _child_limits() -> BudgetLimits:
    return BudgetLimits(
        elapsed_ms=3_000,
        model_turns=3,
        input_tokens=3_000,
        output_tokens=1_500,
        tool_calls=3,
        tool_result_bytes=3_000,
        artifact_bytes=3_000,
        max_children=0,
        max_depth=1,
        allow_child_agents=False,
    )


async def _delete_run(context: IntegrationContext, run_id: object) -> None:
    async with context.session_factory() as session:
        await session.execute(
            delete(ExecutionBudgetReservationModel).where(
                ExecutionBudgetReservationModel.run_id == run_id
            )
        )
        await session.execute(
            delete(ExecutionArtifactModel).where(ExecutionArtifactModel.run_id == run_id)
        )
        await session.execute(
            delete(ExecutionTraceEventModel).where(ExecutionTraceEventModel.run_id == run_id)
        )
        await session.execute(
            delete(ExecutionAgentAllocationModel).where(
                ExecutionAgentAllocationModel.run_id == run_id
            )
        )
        await session.execute(
            delete(ExecutionGovernedRunModel).where(ExecutionGovernedRunModel.id == run_id)
        )
        await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_child_allocations_do_not_oversell_and_completion_charges_actual_usage(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresExecutionGovernanceRepository(integration_context.session_factory)
    service = ExecutionGovernanceService(repository)
    fingerprint = sha256(f"concurrency:{uuid4()}".encode()).hexdigest()
    allocation, root_event = await service.create_run(
        task_id="weekly-2099-w36",
        root_agent_id="orchestrator",
        role=ExecutionRole.ORCHESTRATOR,
        limits=_root_limits(),
        request_fingerprint=fingerprint,
    )
    run_id = allocation.identity.run_id
    try:
        replay, replay_root = await service.create_run(
            task_id="weekly-2099-w36",
            root_agent_id="orchestrator",
            role=ExecutionRole.ORCHESTRATOR,
            limits=_root_limits(),
            request_fingerprint=fingerprint,
        )
        assert replay.identity == allocation.identity
        assert replay_root.event_id == root_event.event_id
        node_event = await service.append_event(
            SafeEventDraft(
                identity=allocation.identity,
                event_id=uuid4(),
                kind=ExecutionEventKind.NODE_STARTED,
                status=ExecutionEventStatus.STARTED,
                parent_event_id=root_event.event_id,
                target_name="weekly-batch",
            )
        )
        outcomes = await asyncio.gather(
            *(
                service.allocate_child(
                    parent=allocation.identity,
                    child_agent_id=f"writer-{index}",
                    role=ExecutionRole.WORKER,
                    limits=_child_limits(),
                    parent_event_id=node_event.event_id,
                )
                for index in range(8)
            ),
            return_exceptions=True,
        )
        children = tuple(item for item in outcomes if not isinstance(item, BaseException))
        failures = tuple(item for item in outcomes if isinstance(item, GovernanceDeniedError))
        assert len(children) == 3, outcomes
        assert len(failures) == 5
        assert {error.code for error in failures} == {
            GovernanceErrorCode.DELEGATION_THRESHOLD_REACHED
        }
        locked_parent = await repository.get_allocation(allocation.identity)
        assert locked_parent.child_reserved == BudgetVector(
            elapsed_ms=9_000,
            model_turns=9,
            input_tokens=9_000,
            output_tokens=4_500,
            tool_calls=9,
            tool_result_bytes=9_000,
            artifact_bytes=9_000,
        )
        assert locked_parent.reserved_child_count == 3

        first_child = children[0]
        child_start = await repository.append_event(
            SafeEventDraft(
                identity=first_child.identity,
                event_id=uuid4(),
                kind=ExecutionEventKind.NODE_STARTED,
                status=ExecutionEventStatus.STARTED,
                parent_event_id=node_event.event_id,
                target_name="writer",
            )
        )
        with pytest.raises(GovernanceDeniedError) as duplicate_event:
            await repository.append_event(
                SafeEventDraft(
                    identity=first_child.identity,
                    event_id=child_start.event_id,
                    kind=ExecutionEventKind.NODE_FINISHED,
                    status=ExecutionEventStatus.SUCCEEDED,
                    parent_event_id=child_start.event_id,
                    target_name="writer",
                )
            )
        assert duplicate_event.value.code is GovernanceErrorCode.INVALID_EVENT
        reservation_id = uuid4()
        requested = BudgetVector(
            elapsed_ms=1_000,
            model_turns=1,
            input_tokens=500,
            output_tokens=250,
            tool_calls=1,
            tool_result_bytes=500,
            artifact_bytes=500,
        )
        first = await repository.reserve_budget(
            identity=first_child.identity,
            reservation_id=reservation_id,
            requested=requested,
        )
        replay = await repository.reserve_budget(
            identity=first_child.identity,
            reservation_id=reservation_id,
            requested=requested,
        )
        assert replay == first
        reserved_child = await repository.get_allocation(first_child.identity)
        assert reserved_child.usage == BudgetUsage()
        assert reserved_child.child_reserved == requested
        with pytest.raises(GovernanceDeniedError) as reservation_active:
            await repository.complete_allocation(
                identity=first_child.identity,
                status=ExecutionRunStatus.SUCCEEDED,
            )
        assert reservation_active.value.code is GovernanceErrorCode.ALLOCATION_NOT_ACTIVE
        actual = BudgetUsage(
            elapsed_ms=400,
            model_turns=1,
            input_tokens=None,
            output_tokens=None,
            tool_calls=1,
            tool_result_bytes=120,
            artifact_bytes=100,
        )
        await repository.reconcile_budget(
            identity=first_child.identity,
            reservation_id=reservation_id,
            actual=actual,
        )
        reconciled_child = await repository.get_allocation(first_child.identity)
        assert reconciled_child.child_reserved == BudgetVector()
        assert reconciled_child.usage == actual
        await repository.append_event(
            SafeEventDraft(
                identity=first_child.identity,
                event_id=uuid4(),
                kind=ExecutionEventKind.NODE_FINISHED,
                status=ExecutionEventStatus.SUCCEEDED,
                parent_event_id=child_start.event_id,
                target_name="writer",
            )
        )
        assert await repository.complete_allocation(
            identity=first_child.identity,
            status=ExecutionRunStatus.SUCCEEDED,
        )
        assert not await repository.complete_allocation(
            identity=first_child.identity,
            status=ExecutionRunStatus.SUCCEEDED,
        )
        for child in children[1:]:
            await repository.complete_allocation(
                identity=child.identity,
                status=ExecutionRunStatus.SUCCEEDED,
            )

        completed_parent = await repository.get_allocation(allocation.identity)
        assert completed_parent.child_reserved == BudgetVector()
        assert completed_parent.reserved_child_count == 0
        assert completed_parent.usage.child_count == 3
        assert completed_parent.usage.elapsed_ms == 400
        assert completed_parent.usage.tool_calls == 1
        assert completed_parent.usage.input_tokens is None
        assert completed_parent.usage.output_tokens is None
    finally:
        await _delete_run(integration_context, run_id)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_run_replays_resolve_to_one_frozen_root(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresExecutionGovernanceRepository(integration_context.session_factory)
    service = ExecutionGovernanceService(repository)
    fingerprint = sha256(f"run-replay:{uuid4()}".encode()).hexdigest()
    run_id: object | None = None
    try:
        outcomes = await asyncio.gather(
            *(
                service.create_run(
                    task_id="weekly-2099-w39",
                    root_agent_id="orchestrator",
                    role=ExecutionRole.ORCHESTRATOR,
                    limits=_root_limits(),
                    request_fingerprint=fingerprint,
                )
                for _ in range(8)
            )
        )
        identities = {allocation.identity for allocation, _root in outcomes}
        root_events = {root.event_id for _allocation, root in outcomes}
        assert len(identities) == 1
        assert len(root_events) == 1
        run_id = outcomes[0][0].identity.run_id

        with pytest.raises(GovernanceDeniedError) as conflicting_replay:
            await service.create_run(
                task_id="weekly-2099-w39",
                root_agent_id="orchestrator",
                role=ExecutionRole.ORCHESTRATOR,
                limits=BudgetLimits(elapsed_ms=1),
                request_fingerprint=fingerprint,
            )
        assert conflicting_replay.value.code is GovernanceErrorCode.INVALID_EVENT
    finally:
        if run_id is not None:
            await _delete_run(integration_context, run_id)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_trace_parent_artifact_scope_and_timeline_fail_closed_across_runs(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresExecutionGovernanceRepository(integration_context.session_factory)
    service = ExecutionGovernanceService(repository)
    created: list[ExecutionIdentity] = []
    try:
        first, first_root = await service.create_run(
            task_id="weekly-2099-w37",
            root_agent_id="writer",
            role=ExecutionRole.WORKER,
            limits=BudgetLimits(
                elapsed_ms=5_000,
                model_turns=1,
                input_tokens=1_000,
                output_tokens=1_000,
                tool_calls=1,
                tool_result_bytes=1_000,
                artifact_bytes=1_000,
            ),
            request_fingerprint=sha256(f"first:{uuid4()}".encode()).hexdigest(),
        )
        second, second_root = await service.create_run(
            task_id="weekly-2099-w38",
            root_agent_id="writer",
            role=ExecutionRole.WORKER,
            limits=BudgetLimits(elapsed_ms=5_000, artifact_bytes=1_000),
            request_fingerprint=sha256(f"second:{uuid4()}".encode()).hexdigest(),
        )
        created.extend((first.identity, second.identity))
        first_node = await repository.append_event(
            SafeEventDraft(
                identity=first.identity,
                event_id=uuid4(),
                kind=ExecutionEventKind.NODE_STARTED,
                status=ExecutionEventStatus.STARTED,
                parent_event_id=first_root.event_id,
                target_name="writer",
            )
        )
        with pytest.raises(GovernanceDeniedError) as cross_run:
            await repository.append_event(
                SafeEventDraft(
                    identity=first.identity,
                    event_id=uuid4(),
                    kind=ExecutionEventKind.NODE_FINISHED,
                    status=ExecutionEventStatus.SUCCEEDED,
                    parent_event_id=second_root.event_id,
                    target_name="writer",
                )
            )
        assert cross_run.value.code is GovernanceErrorCode.INVALID_EVENT

        artifact_event, artifact = await service.produce_artifact(
            identity=first.identity,
            parent_event_id=first_node.event_id,
            kind=ArtifactKind.HTML,
            media_type="text/html",
            byte_size=200,
            sha256=sha256(b"rendered html").hexdigest(),
        )
        assert artifact_event.artifact_id == artifact.artifact_id
        assert await repository.validate_artifact_scope(
            identity=first.identity,
            artifact_ids=(artifact.artifact_id,),
        )
        assert not await repository.validate_artifact_scope(
            identity=second.identity,
            artifact_ids=(artifact.artifact_id,),
        )
        with pytest.raises(GovernanceDeniedError) as duplicate_artifact:
            await service.produce_artifact(
                identity=first.identity,
                parent_event_id=first_node.event_id,
                kind=ArtifactKind.HTML,
                media_type="text/html",
                byte_size=200,
                sha256=sha256(b"rendered html").hexdigest(),
                artifact_id=artifact.artifact_id,
            )
        assert duplicate_artifact.value.code is GovernanceErrorCode.INVALID_EVENT
        timeline = await repository.list_timeline(run_id=first.identity.run_id, limit=3)
        assert [event.seq_no for event in timeline] == [0, 1, 2]
        assert all("prompt" not in event.as_dict() for event in timeline)
        with pytest.raises(ValueError, match="bounds"):
            await repository.list_timeline(run_id=first.identity.run_id, limit=201)
    finally:
        for identity in reversed(created):
            await _delete_run(integration_context, identity.run_id)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_each_budget_dimension_and_recursive_default_fail_closed(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresExecutionGovernanceRepository(integration_context.session_factory)
    service = ExecutionGovernanceService(repository)
    limits = BudgetLimits(
        elapsed_ms=100,
        model_turns=2,
        input_tokens=100,
        output_tokens=100,
        tool_calls=2,
        tool_result_bytes=100,
        artifact_bytes=100,
    )
    allocation, root = await service.create_run(
        task_id="budget-dimensions",
        root_agent_id="worker",
        role=ExecutionRole.WORKER,
        limits=limits,
        request_fingerprint=sha256(f"dimensions:{uuid4()}".encode()).hexdigest(),
    )
    try:
        node = await repository.append_event(
            SafeEventDraft(
                identity=allocation.identity,
                event_id=uuid4(),
                kind=ExecutionEventKind.NODE_STARTED,
                status=ExecutionEventStatus.STARTED,
                parent_event_id=root.event_id,
                target_name="worker",
            )
        )
        del node
        oversized = (
            BudgetVector(elapsed_ms=101),
            BudgetVector(model_turns=3),
            BudgetVector(input_tokens=101),
            BudgetVector(output_tokens=101),
            BudgetVector(tool_calls=3),
            BudgetVector(tool_result_bytes=101),
            BudgetVector(artifact_bytes=101),
        )
        for requested in oversized:
            with pytest.raises(GovernanceDeniedError) as exhausted:
                await repository.reserve_budget(
                    identity=allocation.identity,
                    reservation_id=uuid4(),
                    requested=requested,
                )
            assert exhausted.value.code is GovernanceErrorCode.BUDGET_EXHAUSTED

        with pytest.raises(GovernanceDeniedError) as recursion:
            await service.allocate_child(
                parent=allocation.identity,
                child_agent_id="forbidden-child",
                role=ExecutionRole.WORKER,
                limits=BudgetLimits(elapsed_ms=10),
                parent_event_id=root.event_id,
            )
        assert recursion.value.code is GovernanceErrorCode.RECURSION_DISABLED
        with pytest.raises(GovernanceDeniedError) as artifact:
            await service.produce_artifact(
                identity=allocation.identity,
                parent_event_id=root.event_id,
                kind=ArtifactKind.HTML,
                media_type="text/html",
                byte_size=101,
                sha256=sha256(b"oversized").hexdigest(),
            )
        assert artifact.value.code is GovernanceErrorCode.BUDGET_EXHAUSTED
    finally:
        await _delete_run(integration_context, allocation.identity.run_id)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_explicit_recursion_stops_at_the_system_depth_two_hard_limit(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresExecutionGovernanceRepository(integration_context.session_factory)
    service = ExecutionGovernanceService(repository)
    root, root_event = await service.create_run(
        task_id="depth-hard-limit",
        root_agent_id="orchestrator",
        role=ExecutionRole.ORCHESTRATOR,
        limits=BudgetLimits(
            elapsed_ms=10_000,
            max_children=1,
            max_depth=2,
            allow_child_agents=True,
        ),
        request_fingerprint=sha256(f"depth:{uuid4()}".encode()).hexdigest(),
    )
    child_limits = BudgetLimits(
        elapsed_ms=1_000,
        max_children=1,
        max_depth=2,
        allow_child_agents=True,
    )
    grandchild_limits = BudgetLimits(
        elapsed_ms=100,
        max_children=1,
        max_depth=2,
        allow_child_agents=True,
    )
    try:
        child = await service.allocate_child(
            parent=root.identity,
            child_agent_id="child",
            role=ExecutionRole.WORKER,
            limits=child_limits,
            parent_event_id=root_event.event_id,
        )
        child_start = await repository.append_event(
            SafeEventDraft(
                identity=child.identity,
                event_id=uuid4(),
                kind=ExecutionEventKind.NODE_STARTED,
                status=ExecutionEventStatus.STARTED,
                parent_event_id=root_event.event_id,
                target_name="child",
            )
        )
        grandchild = await service.allocate_child(
            parent=child.identity,
            child_agent_id="grandchild",
            role=ExecutionRole.WORKER,
            limits=grandchild_limits,
            parent_event_id=child_start.event_id,
        )
        grandchild_start = await repository.append_event(
            SafeEventDraft(
                identity=grandchild.identity,
                event_id=uuid4(),
                kind=ExecutionEventKind.NODE_STARTED,
                status=ExecutionEventStatus.STARTED,
                parent_event_id=child_start.event_id,
                target_name="grandchild",
            )
        )
        assert grandchild.depth == 2
        with pytest.raises(GovernanceDeniedError) as depth:
            await service.allocate_child(
                parent=grandchild.identity,
                child_agent_id="forbidden-depth-three",
                role=ExecutionRole.WORKER,
                limits=BudgetLimits(elapsed_ms=10, max_depth=2),
                parent_event_id=grandchild_start.event_id,
            )
        assert depth.value.code is GovernanceErrorCode.DEPTH_EXHAUSTED

        await repository.complete_allocation(
            identity=grandchild.identity,
            status=ExecutionRunStatus.SUCCEEDED,
        )
        await repository.complete_allocation(
            identity=child.identity,
            status=ExecutionRunStatus.SUCCEEDED,
        )
    finally:
        await _delete_run(integration_context, root.identity.run_id)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_child_count_is_a_non_refundable_hard_budget(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresExecutionGovernanceRepository(integration_context.session_factory)
    service = ExecutionGovernanceService(repository)
    parent, root = await service.create_run(
        task_id="child-count-budget",
        root_agent_id="orchestrator",
        role=ExecutionRole.ORCHESTRATOR,
        limits=BudgetLimits(
            elapsed_ms=1_000,
            model_turns=10,
            input_tokens=1_000,
            output_tokens=1_000,
            tool_calls=10,
            tool_result_bytes=1_000,
            artifact_bytes=1_000,
            max_children=1,
            max_depth=1,
            allow_child_agents=True,
        ),
        request_fingerprint=sha256(f"child-count:{uuid4()}".encode()).hexdigest(),
    )
    child_limits = BudgetLimits(elapsed_ms=100, max_depth=1)
    try:
        child = await service.allocate_child(
            parent=parent.identity,
            child_agent_id="only-child",
            role=ExecutionRole.WORKER,
            limits=child_limits,
            parent_event_id=root.event_id,
        )
        with pytest.raises(GovernanceDeniedError) as exhausted:
            await service.allocate_child(
                parent=parent.identity,
                child_agent_id="second-child",
                role=ExecutionRole.WORKER,
                limits=child_limits,
                parent_event_id=root.event_id,
            )
        assert exhausted.value.code is GovernanceErrorCode.CHILD_LIMIT_EXHAUSTED
        await repository.complete_allocation(
            identity=child.identity,
            status=ExecutionRunStatus.SUCCEEDED,
        )
        completed = await repository.get_allocation(parent.identity)
        assert completed.usage.child_count == 1
        assert completed.reserved_child_count == 0
        with pytest.raises(GovernanceDeniedError) as still_exhausted:
            await service.allocate_child(
                parent=parent.identity,
                child_agent_id="retry-child",
                role=ExecutionRole.WORKER,
                limits=child_limits,
                parent_event_id=root.event_id,
            )
        assert still_exhausted.value.code is GovernanceErrorCode.CHILD_LIMIT_EXHAUSTED
    finally:
        await _delete_run(integration_context, parent.identity.run_id)
