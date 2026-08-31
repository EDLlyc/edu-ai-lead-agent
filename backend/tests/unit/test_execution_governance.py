from __future__ import annotations

import asyncio
from dataclasses import replace
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from app.agent_workbench_runtime import (
    build_fixture_agent_workbench,
    build_fixture_tool_registry,
)
from app.application.ports.execution_governance import (
    AllocationSnapshot,
    BudgetReservationSnapshot,
)
from app.application.services.agent_workbench_governance import (
    project_workbench_result,
    workbench_capability_definitions,
)
from app.application.services.execution_governance import (
    CapabilityGateway,
    CapabilityRegistry,
    GovernedCapabilityResult,
)
from app.domain.execution_governance import (
    HARD_MAX_AGENT_DEPTH,
    ArtifactKind,
    ArtifactMetadata,
    BudgetLimits,
    BudgetUsage,
    BudgetVector,
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
    SafeExecutionEvent,
    authorize_capability,
    delegation_usage_percent,
)


def _identity() -> ExecutionIdentity:
    return ExecutionIdentity(run_id=uuid4(), task_id="weekly-2026-w36", agent_id="writer-1")


def _limits(*, children: bool = False) -> BudgetLimits:
    return BudgetLimits(
        elapsed_ms=30_000,
        model_turns=4,
        input_tokens=20_000,
        output_tokens=8_000,
        tool_calls=4,
        tool_result_bytes=64 * 1024,
        artifact_bytes=2 * 1024 * 1024,
        max_children=2 if children else 0,
        max_depth=1,
        allow_child_agents=children,
    )


def test_identity_budget_and_artifact_contracts_are_strict_and_stable() -> None:
    identity = _identity()
    assert tuple(identity.as_dict()) == ("run_id", "task_id", "agent_id")
    default_limits = BudgetLimits(elapsed_ms=1)
    assert default_limits.allow_child_agents is False
    assert default_limits.max_depth == 1
    with pytest.raises(ValueError, match="identity"):
        ExecutionIdentity(run_id=uuid4(), task_id="../../private", agent_id="writer")
    with pytest.raises(ValueError, match="hard limit"):
        replace(_limits(children=True), max_depth=HARD_MAX_AGENT_DEPTH + 1)
    with pytest.raises(ValueError, match="zero child"):
        replace(_limits(), max_children=1)

    artifact = ArtifactMetadata(
        identity=identity,
        artifact_id=uuid4(),
        producer_event_id=uuid4(),
        kind=ArtifactKind.HTML,
        media_type="text/html",
        byte_size=123,
        sha256=sha256(b"safe artifact").hexdigest(),
    )
    assert tuple(artifact.as_dict()) == (
        "run_id",
        "task_id",
        "agent_id",
        "artifact_id",
        "producer_event_id",
        "kind",
        "media_type",
        "byte_size",
        "sha256",
        "lifecycle_status",
    )
    with pytest.raises(ValueError, match="SHA-256"):
        replace(artifact, sha256="not-a-hash")


def test_safe_event_requires_contiguous_root_shape_and_artifact_binding() -> None:
    identity = _identity()
    root = SafeExecutionEvent(
        identity=identity,
        event_id=uuid4(),
        seq_no=0,
        kind=ExecutionEventKind.RUN_STARTED,
        status=ExecutionEventStatus.STARTED,
    )
    node = SafeEventDraft(
        identity=identity,
        event_id=uuid4(),
        kind=ExecutionEventKind.NODE_STARTED,
        status=ExecutionEventStatus.STARTED,
        parent_event_id=root.event_id,
        target_name="writer",
    ).materialize(1)
    assert node.seq_no == 1
    assert node.as_dict()["parent_event_id"] == str(root.event_id)
    with pytest.raises(ValueError, match="parent event"):
        replace(node, parent_event_id=None)
    with pytest.raises(ValueError, match="artifact-produced"):
        replace(node, artifact_id=uuid4())
    with pytest.raises(ValueError, match="stable error"):
        replace(
            node,
            kind=ExecutionEventKind.PERMISSION_DENIED,
            status=ExecutionEventStatus.DENIED,
            error_code=None,
        )


def test_authorization_is_default_deny_by_role_task_and_artifact_scope() -> None:
    identity = _identity()
    write = CapabilityDefinition(
        name="write-article",
        access=CapabilityAccess.BUSINESS_WRITE,
        allowed_roles=frozenset({ExecutionRole.WORKER, ExecutionRole.REVIEWER}),
        timeout_ms=1_000,
        max_argument_bytes=1024,
        max_result_bytes=2048,
        artifact_scoped=True,
    )
    request = CapabilityRequest(
        identity=identity,
        role=ExecutionRole.WORKER,
        capability_name=write.name,
        target_task_id=identity.task_id,
        parent_event_id=uuid4(),
        argument_bytes=100,
        artifact_ids=(uuid4(),),
    )
    authorize_capability(write, request)
    with pytest.raises(GovernanceDeniedError) as reviewer:
        authorize_capability(write, replace(request, role=ExecutionRole.REVIEWER))
    assert reviewer.value.code is GovernanceErrorCode.WRITE_FORBIDDEN
    with pytest.raises(GovernanceDeniedError) as cross_task:
        authorize_capability(write, replace(request, target_task_id="another-task"))
    assert cross_task.value.code is GovernanceErrorCode.TASK_SCOPE_FORBIDDEN
    with pytest.raises(GovernanceDeniedError) as no_artifact:
        authorize_capability(write, replace(request, artifact_ids=()))
    assert no_artifact.value.code is GovernanceErrorCode.ARTIFACT_SCOPE_FORBIDDEN


def test_delegation_threshold_uses_the_most_consumed_dimension() -> None:
    limits = _limits(children=True)
    assert (
        delegation_usage_percent(
            limits=limits,
            usage=BudgetUsage(tool_calls=2),
            reserved=BudgetVector(tool_calls=1),
        )
        == 75
    )
    assert (
        delegation_usage_percent(
            limits=replace(limits, elapsed_ms=100),
            usage=BudgetUsage(elapsed_ms=70),
            reserved=BudgetVector(),
        )
        == 70
    )


@pytest.mark.asyncio
async def test_workbench_projection_preserves_legacy_result_and_safe_closed_world_tools() -> None:
    result = await build_fixture_agent_workbench().run(
        "这条人工智能教育事件有哪些可靠证据? secret-do-not-store",
        scenario_id="evidence",
    )
    projection = project_workbench_result(result)

    assert projection.identity.run_id == result.run_id
    assert projection.usage.model_turns == result.metrics.model_turns
    assert projection.usage.tool_calls == result.metrics.tool_calls
    assert projection.events[0].kind is ExecutionEventKind.RUN_STARTED
    assert projection.events[-1].kind is ExecutionEventKind.RUN_FINISHED
    assert [event.seq_no for event in projection.events] == list(range(len(projection.events)))
    serialized = str([event.as_dict() for event in projection.events])
    assert "secret-do-not-store" not in serialized

    definitions = workbench_capability_definitions(build_fixture_tool_registry())
    assert tuple(definition.name for definition in definitions) == (
        "get_event",
        "retrieve_brand_context",
        "search_evidence",
        "validate_copy",
    )
    assert all(definition.access is CapabilityAccess.READ for definition in definitions)
    assert all(ExecutionRole.REVIEWER in definition.allowed_roles for definition in definitions)


class _MemoryRepository:
    def __init__(self, allocation: AllocationSnapshot) -> None:
        self.allocation = allocation
        self.events: list[SafeExecutionEvent] = []
        self.reservations: dict[UUID, BudgetVector] = {}
        self.deny_budget = False
        self.artifacts_valid = True
        self.reconciled: list[BudgetUsage] = []

    async def get_allocation(self, identity: ExecutionIdentity) -> AllocationSnapshot:
        assert identity == self.allocation.identity
        return self.allocation

    async def reserve_budget(
        self, *, identity: ExecutionIdentity, reservation_id: UUID, requested: BudgetVector
    ) -> BudgetReservationSnapshot:
        assert identity == self.allocation.identity
        if self.deny_budget:
            raise GovernanceDeniedError(GovernanceErrorCode.BUDGET_EXHAUSTED)
        self.reservations[reservation_id] = requested
        return BudgetReservationSnapshot(reservation_id, identity, requested, False)

    async def reconcile_budget(
        self, *, identity: ExecutionIdentity, reservation_id: UUID, actual: BudgetUsage
    ) -> BudgetReservationSnapshot:
        self.reconciled.append(actual)
        return BudgetReservationSnapshot(
            reservation_id, identity, self.reservations[reservation_id], True
        )

    async def append_event(self, draft: SafeEventDraft) -> SafeExecutionEvent:
        event = draft.materialize(self.allocation.next_seq_no + len(self.events))
        self.events.append(event)
        return event

    async def validate_artifact_scope(
        self, *, identity: ExecutionIdentity, artifact_ids: tuple[UUID, ...]
    ) -> bool:
        del identity, artifact_ids
        return self.artifacts_valid


def _allocation(identity: ExecutionIdentity, root_event_id: UUID) -> AllocationSnapshot:
    return AllocationSnapshot(
        identity=identity,
        role=ExecutionRole.WORKER,
        status=ExecutionRunStatus.RUNNING,
        depth=0,
        parent_agent_id=None,
        parent_event_id=None,
        limits=_limits(),
        usage=BudgetUsage(),
        child_reserved=BudgetVector(),
        reserved_child_count=0,
        next_seq_no=1,
    )


@pytest.mark.asyncio
async def test_gateway_denies_unknown_role_scope_and_budget_before_handler() -> None:
    identity = _identity()
    root_event_id = uuid4()
    repository = _MemoryRepository(_allocation(identity, root_event_id))
    definition = CapabilityDefinition(
        name="read-evidence",
        access=CapabilityAccess.READ,
        allowed_roles=frozenset({ExecutionRole.WORKER}),
        timeout_ms=500,
        max_argument_bytes=1024,
        max_result_bytes=2048,
    )
    gateway = CapabilityGateway(
        repository=repository,  # type: ignore[arg-type]
        registry=CapabilityRegistry((definition,)),
    )
    calls = 0

    async def handler() -> GovernedCapabilityResult[str]:
        nonlocal calls
        calls += 1
        return GovernedCapabilityResult("ok", result_bytes=2)

    base = CapabilityRequest(
        identity=identity,
        role=ExecutionRole.WORKER,
        capability_name=definition.name,
        target_task_id=identity.task_id,
        parent_event_id=root_event_id,
        argument_bytes=10,
    )
    with pytest.raises(GovernanceDeniedError) as unknown:
        await gateway.invoke(replace(base, capability_name="unknown-tool"), handler)
    assert unknown.value.code is GovernanceErrorCode.CAPABILITY_UNKNOWN
    with pytest.raises(GovernanceDeniedError) as role:
        await gateway.invoke(replace(base, role=ExecutionRole.REVIEWER), handler)
    assert role.value.code is GovernanceErrorCode.ROLE_FORBIDDEN
    repository.deny_budget = True
    with pytest.raises(GovernanceDeniedError) as budget:
        await gateway.invoke(base, handler)
    assert budget.value.code is GovernanceErrorCode.BUDGET_EXHAUSTED
    assert calls == 0
    assert [event.kind for event in repository.events] == [
        ExecutionEventKind.PERMISSION_DENIED,
        ExecutionEventKind.PERMISSION_DENIED,
        ExecutionEventKind.BUDGET_DENIED,
    ]


@pytest.mark.asyncio
async def test_gateway_denies_write_task_artifact_and_argument_scope_before_handler() -> None:
    identity = _identity()
    root_event_id = uuid4()
    artifact_id = uuid4()
    definition = CapabilityDefinition(
        name="write-article",
        access=CapabilityAccess.BUSINESS_WRITE,
        allowed_roles=frozenset({ExecutionRole.WORKER, ExecutionRole.REVIEWER}),
        timeout_ms=500,
        max_argument_bytes=10,
        max_result_bytes=2048,
        artifact_scoped=True,
    )
    repository = _MemoryRepository(_allocation(identity, root_event_id))
    gateway = CapabilityGateway(
        repository=repository,  # type: ignore[arg-type]
        registry=CapabilityRegistry((definition,)),
    )
    calls = 0

    async def handler() -> GovernedCapabilityResult[str]:
        nonlocal calls
        calls += 1
        return GovernedCapabilityResult("unexpected", result_bytes=10)

    base = CapabilityRequest(
        identity=identity,
        role=ExecutionRole.WORKER,
        capability_name=definition.name,
        target_task_id=identity.task_id,
        parent_event_id=root_event_id,
        argument_bytes=10,
        artifact_ids=(artifact_id,),
    )
    with pytest.raises(GovernanceDeniedError) as task_scope:
        await gateway.invoke(replace(base, target_task_id="another-task"), handler)
    assert task_scope.value.code is GovernanceErrorCode.TASK_SCOPE_FORBIDDEN
    with pytest.raises(GovernanceDeniedError) as missing_artifact:
        await gateway.invoke(replace(base, artifact_ids=()), handler)
    assert missing_artifact.value.code is GovernanceErrorCode.ARTIFACT_SCOPE_FORBIDDEN
    repository.artifacts_valid = False
    with pytest.raises(GovernanceDeniedError) as invalid_artifact:
        await gateway.invoke(base, handler)
    assert invalid_artifact.value.code is GovernanceErrorCode.ARTIFACT_SCOPE_FORBIDDEN
    repository.artifacts_valid = True
    with pytest.raises(GovernanceDeniedError) as argument:
        await gateway.invoke(replace(base, argument_bytes=11), handler)
    assert argument.value.code is GovernanceErrorCode.ARGUMENT_TOO_LARGE

    reviewer_repository = _MemoryRepository(
        replace(repository.allocation, role=ExecutionRole.REVIEWER)
    )
    reviewer_gateway = CapabilityGateway(
        repository=reviewer_repository,  # type: ignore[arg-type]
        registry=CapabilityRegistry((definition,)),
    )
    with pytest.raises(GovernanceDeniedError) as reviewer_write:
        await reviewer_gateway.invoke(replace(base, role=ExecutionRole.REVIEWER), handler)
    assert reviewer_write.value.code is GovernanceErrorCode.WRITE_FORBIDDEN
    assert calls == 0


@pytest.mark.asyncio
async def test_gateway_runs_allowed_handler_once_and_records_safe_request_result() -> None:
    identity = _identity()
    root_event_id = uuid4()
    repository = _MemoryRepository(_allocation(identity, root_event_id))
    definition = CapabilityDefinition(
        name="read-evidence",
        access=CapabilityAccess.READ,
        allowed_roles=frozenset({ExecutionRole.WORKER}),
        timeout_ms=500,
        max_argument_bytes=1024,
        max_result_bytes=2048,
    )
    gateway = CapabilityGateway(
        repository=repository,  # type: ignore[arg-type]
        registry=CapabilityRegistry((definition,)),
    )
    calls = 0

    async def handler() -> GovernedCapabilityResult[str]:
        nonlocal calls
        calls += 1
        return GovernedCapabilityResult("safe", result_bytes=4)

    result = await gateway.invoke(
        CapabilityRequest(
            identity=identity,
            role=ExecutionRole.WORKER,
            capability_name=definition.name,
            target_task_id=identity.task_id,
            parent_event_id=root_event_id,
            argument_bytes=10,
        ),
        handler,
    )
    assert result.value == "safe"
    assert calls == 1
    assert [event.kind for event in repository.events] == [
        ExecutionEventKind.TOOL_REQUESTED,
        ExecutionEventKind.TOOL_RESULT,
    ]
    assert all("evidence" not in event.as_dict() for event in repository.events)


@pytest.mark.asyncio
async def test_gateway_reconciles_handler_failure_and_oversized_outputs_without_raw_error() -> None:
    identity = _identity()
    root_event_id = uuid4()
    repository = _MemoryRepository(_allocation(identity, root_event_id))
    definition = CapabilityDefinition(
        name="render-article",
        access=CapabilityAccess.BUSINESS_WRITE,
        allowed_roles=frozenset({ExecutionRole.WORKER}),
        timeout_ms=500,
        max_argument_bytes=1024,
        max_result_bytes=20,
    )
    gateway = CapabilityGateway(
        repository=repository,  # type: ignore[arg-type]
        registry=CapabilityRegistry((definition,)),
    )
    request = CapabilityRequest(
        identity=identity,
        role=ExecutionRole.WORKER,
        capability_name=definition.name,
        target_task_id=identity.task_id,
        parent_event_id=root_event_id,
        argument_bytes=10,
        expected_artifact_bytes=5,
    )

    async def failing() -> GovernedCapabilityResult[str]:
        raise RuntimeError("provider body secret-do-not-trace")

    with pytest.raises(GovernanceDeniedError) as failed:
        await gateway.invoke(request, failing)
    assert failed.value.code is GovernanceErrorCode.CAPABILITY_FAILED
    assert repository.reconciled[-1].tool_calls == 1
    assert repository.events[-1].error_code == "capability_failed"
    assert "secret-do-not-trace" not in str(repository.events[-1].as_dict())

    async def oversized() -> GovernedCapabilityResult[str]:
        return GovernedCapabilityResult("hidden", result_bytes=21, artifact_bytes=6)

    with pytest.raises(GovernanceDeniedError) as too_large:
        await gateway.invoke(request, oversized)
    assert too_large.value.code is GovernanceErrorCode.RESULT_TOO_LARGE
    assert repository.reconciled[-1].tool_result_bytes == 20
    assert repository.reconciled[-1].artifact_bytes == 5
    assert repository.events[-1].kind is ExecutionEventKind.PERMISSION_DENIED

    token_request = replace(
        request,
        expected_input_tokens=2,
        expected_output_tokens=2,
        model_turns=1,
        tool_calls=0,
    )

    async def oversized_tokens() -> GovernedCapabilityResult[str]:
        return GovernedCapabilityResult(
            "hidden",
            result_bytes=1,
            input_tokens=3,
            output_tokens=2,
            model_turns=1,
        )

    with pytest.raises(GovernanceDeniedError) as token_budget:
        await gateway.invoke(token_request, oversized_tokens)
    assert token_budget.value.code is GovernanceErrorCode.BUDGET_EXHAUSTED
    assert repository.reconciled[-1].input_tokens == 2
    assert repository.events[-1].kind is ExecutionEventKind.BUDGET_DENIED


@pytest.mark.asyncio
async def test_gateway_reconciles_timeout_and_cancellation_once() -> None:
    identity = _identity()
    root_event_id = uuid4()
    repository = _MemoryRepository(_allocation(identity, root_event_id))
    definition = CapabilityDefinition(
        name="read-evidence",
        access=CapabilityAccess.READ,
        allowed_roles=frozenset({ExecutionRole.WORKER}),
        timeout_ms=5,
        max_argument_bytes=1024,
        max_result_bytes=2048,
    )
    gateway = CapabilityGateway(
        repository=repository,  # type: ignore[arg-type]
        registry=CapabilityRegistry((definition,)),
    )
    request = CapabilityRequest(
        identity=identity,
        role=ExecutionRole.WORKER,
        capability_name=definition.name,
        target_task_id=identity.task_id,
        parent_event_id=root_event_id,
        argument_bytes=10,
    )

    async def too_slow() -> GovernedCapabilityResult[str]:
        await asyncio.sleep(1)
        return GovernedCapabilityResult("late", result_bytes=4)

    with pytest.raises(GovernanceDeniedError) as timeout:
        await gateway.invoke(request, too_slow)
    assert timeout.value.code is GovernanceErrorCode.CAPABILITY_TIMEOUT
    assert len(repository.reconciled) == 1
    assert repository.reconciled[-1].tool_calls == 1
    assert repository.events[-1].error_code == GovernanceErrorCode.CAPABILITY_TIMEOUT.value

    handler_started = asyncio.Event()

    async def cancelled() -> GovernedCapabilityResult[str]:
        handler_started.set()
        await asyncio.Event().wait()
        return GovernedCapabilityResult("never", result_bytes=5)

    invocation = asyncio.create_task(gateway.invoke(request, cancelled))
    await handler_started.wait()
    invocation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await invocation
    assert len(repository.reconciled) == 2
    assert repository.reconciled[-1].tool_calls == 1
    assert repository.events[-1].error_code == GovernanceErrorCode.CAPABILITY_CANCELLED.value
