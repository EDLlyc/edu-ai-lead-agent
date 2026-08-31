from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.execution_governance import (
    ArtifactMetadata,
    BudgetLimits,
    BudgetUsage,
    BudgetVector,
    ExecutionIdentity,
    ExecutionRole,
    ExecutionRunStatus,
    SafeEventDraft,
    SafeExecutionEvent,
)


@dataclass(frozen=True, slots=True)
class AllocationSnapshot:
    identity: ExecutionIdentity
    role: ExecutionRole
    status: ExecutionRunStatus
    depth: int
    parent_agent_id: str | None
    parent_event_id: UUID | None
    limits: BudgetLimits
    usage: BudgetUsage
    child_reserved: BudgetVector
    reserved_child_count: int
    next_seq_no: int


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    identity: ExecutionIdentity
    status: ExecutionRunStatus
    policy_version: str
    request_fingerprint: str
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class BudgetReservationSnapshot:
    reservation_id: UUID
    identity: ExecutionIdentity
    reserved: BudgetVector
    reconciled: bool


class ExecutionGovernanceRepository(Protocol):
    async def create_run(
        self,
        *,
        identity: ExecutionIdentity,
        role: ExecutionRole,
        limits: BudgetLimits,
        request_fingerprint: str,
        root_event_id: UUID,
    ) -> AllocationSnapshot: ...

    async def get_allocation(self, identity: ExecutionIdentity) -> AllocationSnapshot: ...

    async def allocate_child(
        self,
        *,
        parent: ExecutionIdentity,
        child: ExecutionIdentity,
        role: ExecutionRole,
        limits: BudgetLimits,
        parent_event_id: UUID,
    ) -> AllocationSnapshot: ...

    async def reserve_budget(
        self,
        *,
        identity: ExecutionIdentity,
        reservation_id: UUID,
        requested: BudgetVector,
    ) -> BudgetReservationSnapshot: ...

    async def reconcile_budget(
        self,
        *,
        identity: ExecutionIdentity,
        reservation_id: UUID,
        actual: BudgetUsage,
    ) -> BudgetReservationSnapshot: ...

    async def append_event(self, draft: SafeEventDraft) -> SafeExecutionEvent: ...

    async def register_artifact(
        self,
        *,
        event: SafeEventDraft,
        artifact: ArtifactMetadata,
    ) -> tuple[SafeExecutionEvent, ArtifactMetadata]: ...

    async def complete_allocation(
        self,
        *,
        identity: ExecutionIdentity,
        status: ExecutionRunStatus,
    ) -> bool: ...

    async def validate_artifact_scope(
        self,
        *,
        identity: ExecutionIdentity,
        artifact_ids: tuple[UUID, ...],
    ) -> bool: ...

    async def list_timeline(
        self,
        *,
        run_id: UUID,
        limit: int = 200,
        max_bytes: int = 128 * 1024,
    ) -> tuple[SafeExecutionEvent, ...]: ...
