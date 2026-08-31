from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from app.application.services.agent_tools import TypedToolRegistry
from app.domain.agent_workbench import (
    AgentRunLimits,
    AgentRunResult,
    AgentRunStatus,
    AgentTraceKind,
    AgentTraceStatus,
)
from app.domain.execution_governance import (
    EXECUTION_GOVERNANCE_POLICY_VERSION,
    BudgetLimits,
    BudgetUsage,
    CapabilityAccess,
    CapabilityDefinition,
    ExecutionEventKind,
    ExecutionEventStatus,
    ExecutionIdentity,
    ExecutionRole,
    SafeExecutionEvent,
)

_UNSAFE_SAFE_NAME = re.compile(r"[^a-z0-9_.:-]+")


@dataclass(frozen=True, slots=True)
class WorkbenchGovernanceProjection:
    identity: ExecutionIdentity
    policy_version: str
    limits: BudgetLimits
    usage: BudgetUsage
    events: tuple[SafeExecutionEvent, ...]

    def __post_init__(self) -> None:
        if any(event.identity != self.identity for event in self.events):
            raise ValueError("workbench governance events must share one identity")
        if any(event.seq_no != index for index, event in enumerate(self.events)):
            raise ValueError("workbench governance event sequence must be contiguous")


def workbench_budget_limits(limits: AgentRunLimits) -> BudgetLimits:
    return BudgetLimits(
        elapsed_ms=max(1, int(limits.total_timeout_seconds * 1_000)),
        model_turns=limits.max_model_turns,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        tool_calls=limits.max_tool_calls,
        tool_result_bytes=limits.max_tool_calls * limits.max_tool_result_bytes,
        artifact_bytes=0,
        max_children=0,
        max_depth=1,
        allow_child_agents=False,
    )


def workbench_capability_definitions(
    registry: TypedToolRegistry,
) -> tuple[CapabilityDefinition, ...]:
    return tuple(
        CapabilityDefinition(
            name=definition.name,
            access=CapabilityAccess.READ,
            allowed_roles=frozenset({ExecutionRole.WORKER, ExecutionRole.REVIEWER}),
            timeout_ms=max(1, int(definition.timeout_seconds * 1_000)),
            max_argument_bytes=definition.max_argument_bytes,
            max_result_bytes=definition.max_result_bytes,
            task_scoped=True,
            artifact_scoped=False,
        )
        for definition in registry.definitions
    )


def project_workbench_result(
    result: AgentRunResult,
    *,
    limits: AgentRunLimits | None = None,
) -> WorkbenchGovernanceProjection:
    resolved_limits = limits or AgentRunLimits()
    identity = ExecutionIdentity(
        run_id=result.run_id,
        task_id="agent-workbench",
        agent_id="agent-workbench",
    )
    events: list[SafeExecutionEvent] = []
    root_id = _event_id(result.run_id, "root")
    events.append(
        SafeExecutionEvent(
            identity=identity,
            event_id=root_id,
            seq_no=0,
            kind=ExecutionEventKind.RUN_STARTED,
            status=ExecutionEventStatus.STARTED,
        )
    )
    parent_id = root_id
    events.append(
        SafeExecutionEvent(
            identity=identity,
            event_id=_event_id(result.run_id, "node-started"),
            seq_no=1,
            kind=ExecutionEventKind.NODE_STARTED,
            status=ExecutionEventStatus.STARTED,
            parent_event_id=parent_id,
            target_name="workbench",
        )
    )
    parent_id = events[-1].event_id

    for step in result.steps:
        if step.kind is AgentTraceKind.MODEL_DECISION:
            request_id = _event_id(result.run_id, f"step-{step.ordinal}-model-request")
            events.append(
                SafeExecutionEvent(
                    identity=identity,
                    event_id=request_id,
                    seq_no=len(events),
                    kind=ExecutionEventKind.MODEL_REQUESTED,
                    status=ExecutionEventStatus.STARTED,
                    parent_event_id=parent_id,
                    target_name="model-decision",
                    provider_name=_safe_name(step.provider),
                    model_name=_safe_name(step.model),
                    model_turns=1,
                )
            )
            events.append(
                SafeExecutionEvent(
                    identity=identity,
                    event_id=_event_id(result.run_id, f"step-{step.ordinal}-model-result"),
                    seq_no=len(events),
                    kind=ExecutionEventKind.MODEL_RESULT,
                    status=_event_status(step.status),
                    parent_event_id=request_id,
                    target_name="model-decision",
                    provider_name=_safe_name(step.provider),
                    model_name=_safe_name(step.model),
                    error_code=_safe_name(step.code),
                    duration_ms=step.duration_ms,
                    model_turns=1,
                    input_tokens=step.prompt_tokens,
                    output_tokens=step.completion_tokens + step.reasoning_tokens,
                )
            )
        elif step.kind is AgentTraceKind.TOOL_CALL:
            events.append(
                SafeExecutionEvent(
                    identity=identity,
                    event_id=_event_id(result.run_id, f"step-{step.ordinal}-tool-request"),
                    seq_no=len(events),
                    kind=ExecutionEventKind.TOOL_REQUESTED,
                    status=_event_status(step.status),
                    parent_event_id=parent_id,
                    target_name=_safe_name(step.tool_name),
                    error_code=_safe_name(step.code),
                    tool_calls=1,
                )
            )
        elif step.kind is AgentTraceKind.TOOL_RESULT:
            events.append(
                SafeExecutionEvent(
                    identity=identity,
                    event_id=_event_id(result.run_id, f"step-{step.ordinal}-tool-result"),
                    seq_no=len(events),
                    kind=ExecutionEventKind.TOOL_RESULT,
                    status=_event_status(step.status),
                    parent_event_id=parent_id,
                    target_name=_safe_name(step.tool_name),
                    error_code=_safe_name(step.code),
                    duration_ms=step.duration_ms,
                )
            )
        elif step.kind is AgentTraceKind.FINAL:
            events.append(
                SafeExecutionEvent(
                    identity=identity,
                    event_id=_event_id(result.run_id, f"step-{step.ordinal}-final"),
                    seq_no=len(events),
                    kind=ExecutionEventKind.NODE_FINISHED,
                    status=_event_status(step.status),
                    parent_event_id=parent_id,
                    target_name="workbench",
                    error_code=_safe_name(step.code),
                )
            )
        else:
            denied = step.code == "budget_exhausted"
            events.append(
                SafeExecutionEvent(
                    identity=identity,
                    event_id=_event_id(result.run_id, f"step-{step.ordinal}-error"),
                    seq_no=len(events),
                    kind=(
                        ExecutionEventKind.BUDGET_DENIED
                        if denied
                        else ExecutionEventKind.NODE_FAILED
                    ),
                    status=(ExecutionEventStatus.DENIED if denied else ExecutionEventStatus.FAILED),
                    parent_event_id=parent_id,
                    target_name="workbench",
                    error_code=_safe_name(step.code) or "agent-failed",
                )
            )
        parent_id = events[-1].event_id

    succeeded = result.status in {AgentRunStatus.COMPLETED, AgentRunStatus.REFUSED}
    events.append(
        SafeExecutionEvent(
            identity=identity,
            event_id=_event_id(result.run_id, "run-terminal"),
            seq_no=len(events),
            kind=(ExecutionEventKind.RUN_FINISHED if succeeded else ExecutionEventKind.RUN_FAILED),
            status=(ExecutionEventStatus.SUCCEEDED if succeeded else ExecutionEventStatus.FAILED),
            parent_event_id=parent_id,
            target_name="workbench",
            error_code=_safe_name(result.error_code),
            duration_ms=result.metrics.duration_ms,
        )
    )
    return WorkbenchGovernanceProjection(
        identity=identity,
        policy_version=EXECUTION_GOVERNANCE_POLICY_VERSION,
        limits=workbench_budget_limits(resolved_limits),
        usage=BudgetUsage(
            elapsed_ms=result.metrics.duration_ms,
            model_turns=result.metrics.model_turns,
            input_tokens=result.metrics.prompt_tokens,
            output_tokens=result.metrics.completion_tokens + result.metrics.reasoning_tokens,
            tool_calls=result.metrics.tool_calls,
            tool_result_bytes=0,
            artifact_bytes=0,
            child_count=0,
        ),
        events=tuple(events),
    )


def _event_id(run_id: UUID, suffix: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"execution-governance:{run_id}:{suffix}")


def _event_status(status: AgentTraceStatus) -> ExecutionEventStatus:
    return (
        ExecutionEventStatus.SUCCEEDED
        if status is AgentTraceStatus.SUCCEEDED
        else ExecutionEventStatus.FAILED
    )


def _safe_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _UNSAFE_SAFE_NAME.sub("-", value.strip().lower()).strip("-_.:")
    if not normalized:
        return None
    if not normalized[0].isalpha():
        normalized = f"x-{normalized}"
    return normalized[:80]
