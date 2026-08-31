from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from time import monotonic
from typing import Generic, TypeVar
from uuid import UUID, uuid4

from app.application.ports.execution_governance import (
    AllocationSnapshot,
    ExecutionGovernanceRepository,
)
from app.domain.execution_governance import (
    EXECUTION_GOVERNANCE_POLICY_VERSION,
    ArtifactKind,
    ArtifactMetadata,
    BudgetLimits,
    BudgetUsage,
    BudgetVector,
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
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class GovernedCapabilityResult(Generic[T]):
    value: T
    result_bytes: int
    artifact_bytes: int = 0
    input_tokens: int | None = 0
    output_tokens: int | None = 0
    model_turns: int = 0

    def __post_init__(self) -> None:
        if min(self.result_bytes, self.artifact_bytes, self.model_turns) < 0:
            raise ValueError("governed capability usage must be non-negative")
        if self.input_tokens is not None and self.input_tokens < 0:
            raise ValueError("capability input tokens must be non-negative or unknown")
        if self.output_tokens is not None and self.output_tokens < 0:
            raise ValueError("capability output tokens must be non-negative or unknown")


GovernedHandler = Callable[[], Awaitable[GovernedCapabilityResult[T]]]


class CapabilityRegistry:
    def __init__(self, definitions: Iterable[CapabilityDefinition]) -> None:
        ordered = tuple(definitions)
        names = tuple(definition.name for definition in ordered)
        if not ordered:
            raise ValueError("capability registry cannot be empty")
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("capability registry names must be unique and sorted")
        self._definitions = ordered
        self._by_name = {definition.name: definition for definition in ordered}

    @property
    def definitions(self) -> tuple[CapabilityDefinition, ...]:
        return self._definitions

    def get(self, name: str) -> CapabilityDefinition:
        definition = self._by_name.get(name)
        if definition is None:
            raise GovernanceDeniedError(GovernanceErrorCode.CAPABILITY_UNKNOWN)
        return definition


class ExecutionGovernanceService:
    def __init__(self, repository: ExecutionGovernanceRepository) -> None:
        self._repository = repository

    async def create_run(
        self,
        *,
        task_id: str,
        root_agent_id: str,
        role: ExecutionRole,
        limits: BudgetLimits,
        request_fingerprint: str,
        run_id: UUID | None = None,
    ) -> tuple[AllocationSnapshot, SafeExecutionEvent]:
        identity = ExecutionIdentity(
            run_id=run_id or uuid4(),
            task_id=task_id,
            agent_id=root_agent_id,
        )
        root_event_id = uuid4()
        allocation = await self._repository.create_run(
            identity=identity,
            role=role,
            limits=limits,
            request_fingerprint=request_fingerprint,
            root_event_id=root_event_id,
        )
        timeline = await self._repository.list_timeline(run_id=allocation.identity.run_id, limit=1)
        if not timeline:
            raise RuntimeError("governed run did not create its root event")
        return allocation, timeline[0]

    async def allocate_child(
        self,
        *,
        parent: ExecutionIdentity,
        child_agent_id: str,
        role: ExecutionRole,
        limits: BudgetLimits,
        parent_event_id: UUID,
    ) -> AllocationSnapshot:
        child = ExecutionIdentity(
            run_id=parent.run_id,
            task_id=parent.task_id,
            agent_id=child_agent_id,
        )
        return await self._repository.allocate_child(
            parent=parent,
            child=child,
            role=role,
            limits=limits,
            parent_event_id=parent_event_id,
        )

    async def append_event(self, draft: SafeEventDraft) -> SafeExecutionEvent:
        return await self._repository.append_event(draft)

    async def produce_artifact(
        self,
        *,
        identity: ExecutionIdentity,
        parent_event_id: UUID,
        kind: ArtifactKind,
        media_type: str,
        byte_size: int,
        sha256: str,
        artifact_id: UUID | None = None,
    ) -> tuple[SafeExecutionEvent, ArtifactMetadata]:
        resolved_artifact_id = artifact_id or uuid4()
        event_id = uuid4()
        artifact = ArtifactMetadata(
            identity=identity,
            artifact_id=resolved_artifact_id,
            producer_event_id=event_id,
            kind=kind,
            media_type=media_type,
            byte_size=byte_size,
            sha256=sha256,
        )
        event = SafeEventDraft(
            identity=identity,
            event_id=event_id,
            kind=ExecutionEventKind.ARTIFACT_PRODUCED,
            status=ExecutionEventStatus.SUCCEEDED,
            parent_event_id=parent_event_id,
            artifact_id=resolved_artifact_id,
            result_bytes=byte_size,
        )
        return await self._repository.register_artifact(event=event, artifact=artifact)


class CapabilityGateway:
    def __init__(
        self,
        *,
        repository: ExecutionGovernanceRepository,
        registry: CapabilityRegistry,
    ) -> None:
        self._repository = repository
        self._registry = registry

    async def invoke(
        self,
        request: CapabilityRequest,
        handler: GovernedHandler[T],
    ) -> GovernedCapabilityResult[T]:
        try:
            definition = self._registry.get(request.capability_name)
            allocation = await self._repository.get_allocation(request.identity)
            if allocation.status is not ExecutionRunStatus.RUNNING:
                raise GovernanceDeniedError(GovernanceErrorCode.ALLOCATION_NOT_ACTIVE)
            if allocation.role is not request.role:
                raise GovernanceDeniedError(GovernanceErrorCode.ROLE_FORBIDDEN)
            authorize_capability(definition, request)
            if definition.artifact_scoped and not await self._repository.validate_artifact_scope(
                identity=request.identity,
                artifact_ids=request.artifact_ids,
            ):
                raise GovernanceDeniedError(GovernanceErrorCode.ARTIFACT_SCOPE_FORBIDDEN)
        except GovernanceDeniedError as error:
            await self._append_denial(request, error.code, permission=True)
            raise

        reservation_id = uuid4()
        requested = BudgetVector(
            elapsed_ms=definition.timeout_ms,
            model_turns=request.model_turns,
            input_tokens=request.expected_input_tokens,
            output_tokens=request.expected_output_tokens,
            tool_calls=request.tool_calls,
            tool_result_bytes=definition.max_result_bytes,
            artifact_bytes=request.expected_artifact_bytes,
        )
        try:
            await self._repository.reserve_budget(
                identity=request.identity,
                reservation_id=reservation_id,
                requested=requested,
            )
        except GovernanceDeniedError as error:
            await self._append_denial(request, error.code, permission=False)
            raise

        try:
            request_event = await self._repository.append_event(
                SafeEventDraft(
                    identity=request.identity,
                    event_id=uuid4(),
                    kind=(
                        ExecutionEventKind.MODEL_REQUESTED
                        if request.model_turns
                        else ExecutionEventKind.TOOL_REQUESTED
                    ),
                    status=ExecutionEventStatus.STARTED,
                    parent_event_id=request.parent_event_id,
                    target_name=definition.name,
                    model_turns=request.model_turns,
                    tool_calls=request.tool_calls,
                )
            )
        except Exception:
            await self._repository.reconcile_budget(
                identity=request.identity,
                reservation_id=reservation_id,
                actual=BudgetUsage(),
            )
            raise GovernanceDeniedError(GovernanceErrorCode.CAPABILITY_FAILED) from None
        started_at = monotonic()
        try:
            async with asyncio.timeout(definition.timeout_ms / 1_000):
                result = await handler()
        except asyncio.CancelledError:
            duration_ms = min(
                definition.timeout_ms,
                max(0, int((monotonic() - started_at) * 1_000)),
            )
            await self._reconcile_failed_call(
                request=request,
                reservation_id=reservation_id,
                duration_ms=duration_ms,
            )
            await self._append_failed_event(
                request=request,
                parent_event_id=request_event.event_id,
                target_name=definition.name,
                code=GovernanceErrorCode.CAPABILITY_CANCELLED,
                duration_ms=duration_ms,
            )
            raise
        except TimeoutError:
            duration_ms = min(
                definition.timeout_ms,
                max(0, int((monotonic() - started_at) * 1_000)),
            )
            await self._reconcile_failed_call(
                request=request,
                reservation_id=reservation_id,
                duration_ms=duration_ms,
            )
            await self._append_failed_event(
                request=request,
                parent_event_id=request_event.event_id,
                target_name=definition.name,
                code=GovernanceErrorCode.CAPABILITY_TIMEOUT,
                duration_ms=duration_ms,
            )
            raise GovernanceDeniedError(GovernanceErrorCode.CAPABILITY_TIMEOUT) from None
        except Exception:
            duration_ms = min(
                definition.timeout_ms,
                max(0, int((monotonic() - started_at) * 1_000)),
            )
            await self._reconcile_failed_call(
                request=request,
                reservation_id=reservation_id,
                duration_ms=duration_ms,
            )
            await self._append_failed_event(
                request=request,
                parent_event_id=request_event.event_id,
                target_name=definition.name,
                code=GovernanceErrorCode.CAPABILITY_FAILED,
                duration_ms=duration_ms,
            )
            raise GovernanceDeniedError(GovernanceErrorCode.CAPABILITY_FAILED) from None

        duration_ms = min(
            definition.timeout_ms,
            max(0, int((monotonic() - started_at) * 1_000)),
        )
        result_too_large = result.result_bytes > definition.max_result_bytes
        budget_result_too_large = (
            result.artifact_bytes > request.expected_artifact_bytes
            or result.model_turns > request.model_turns
            or (
                result.input_tokens is not None
                and result.input_tokens > request.expected_input_tokens
            )
            or (
                result.output_tokens is not None
                and result.output_tokens > request.expected_output_tokens
            )
        )
        actual = BudgetUsage(
            elapsed_ms=duration_ms,
            model_turns=min(result.model_turns, request.model_turns),
            input_tokens=(
                None
                if result.input_tokens is None
                else min(result.input_tokens, request.expected_input_tokens)
            ),
            output_tokens=(
                None
                if result.output_tokens is None
                else min(result.output_tokens, request.expected_output_tokens)
            ),
            tool_calls=request.tool_calls,
            tool_result_bytes=min(result.result_bytes, definition.max_result_bytes),
            artifact_bytes=min(result.artifact_bytes, request.expected_artifact_bytes),
        )
        await self._repository.reconcile_budget(
            identity=request.identity,
            reservation_id=reservation_id,
            actual=actual,
        )
        if result_too_large or budget_result_too_large:
            code = (
                GovernanceErrorCode.RESULT_TOO_LARGE
                if result_too_large
                else GovernanceErrorCode.BUDGET_EXHAUSTED
            )
            await self._append_denial(
                request,
                code,
                permission=result_too_large,
                parent_event_id=request_event.event_id,
            )
            raise GovernanceDeniedError(code)
        await self._repository.append_event(
            SafeEventDraft(
                identity=request.identity,
                event_id=uuid4(),
                kind=(
                    ExecutionEventKind.MODEL_RESULT
                    if request.model_turns
                    else ExecutionEventKind.TOOL_RESULT
                ),
                status=ExecutionEventStatus.SUCCEEDED,
                parent_event_id=request_event.event_id,
                target_name=definition.name,
                duration_ms=duration_ms,
                model_turns=result.model_turns,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                tool_calls=request.tool_calls,
                result_bytes=result.result_bytes,
            )
        )
        return result

    async def _reconcile_failed_call(
        self,
        *,
        request: CapabilityRequest,
        reservation_id: UUID,
        duration_ms: int,
    ) -> None:
        await self._repository.reconcile_budget(
            identity=request.identity,
            reservation_id=reservation_id,
            actual=BudgetUsage(
                elapsed_ms=duration_ms,
                model_turns=request.model_turns,
                input_tokens=None if request.model_turns else 0,
                output_tokens=None if request.model_turns else 0,
                tool_calls=request.tool_calls,
            ),
        )

    async def _append_failed_event(
        self,
        *,
        request: CapabilityRequest,
        parent_event_id: UUID,
        target_name: str,
        code: GovernanceErrorCode,
        duration_ms: int,
    ) -> None:
        await self._repository.append_event(
            SafeEventDraft(
                identity=request.identity,
                event_id=uuid4(),
                kind=ExecutionEventKind.NODE_FAILED,
                status=ExecutionEventStatus.FAILED,
                parent_event_id=parent_event_id,
                target_name=target_name,
                error_code=code.value,
                duration_ms=duration_ms,
            )
        )

    async def _append_denial(
        self,
        request: CapabilityRequest,
        code: GovernanceErrorCode,
        *,
        permission: bool,
        parent_event_id: UUID | None = None,
    ) -> None:
        try:
            await self._repository.append_event(
                SafeEventDraft(
                    identity=request.identity,
                    event_id=uuid4(),
                    kind=(
                        ExecutionEventKind.PERMISSION_DENIED
                        if permission
                        else ExecutionEventKind.BUDGET_DENIED
                    ),
                    status=ExecutionEventStatus.DENIED,
                    parent_event_id=parent_event_id or request.parent_event_id,
                    target_name=request.capability_name,
                    error_code=code.value,
                )
            )
        except (GovernanceDeniedError, RuntimeError, ValueError):
            # The denial still fails closed when the bounded event budget or identity is invalid.
            return


def execution_policy_version() -> str:
    return EXECUTION_GOVERNANCE_POLICY_VERSION
