from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.domain.official_account_weekly_dag import (
    WeeklyDagArtifact,
    WeeklyDagClaim,
    WeeklyDagNodeSnapshot,
    WeeklyDagRunSnapshot,
    WeeklyDagStatusProjection,
)


@dataclass(frozen=True, slots=True)
class WeeklyDagNodeResult:
    artifact: WeeklyDagArtifact
    aggregate_artifact: WeeklyDagArtifact | None = None
    model_turns: int = 0
    input_tokens: int | None = 0
    output_tokens: int | None = 0

    def __post_init__(self) -> None:
        if self.model_turns < 0:
            raise ValueError("weekly DAG model-turn usage must be non-negative")
        if self.input_tokens is not None and self.input_tokens < 0:
            raise ValueError("weekly DAG input-token usage must be non-negative or unknown")
        if self.output_tokens is not None and self.output_tokens < 0:
            raise ValueError("weekly DAG output-token usage must be non-negative or unknown")


class WeeklyDagNodeFailure(Exception):
    def __init__(
        self,
        error_code: str,
        *,
        retryable: bool,
        trace_event_id: UUID | None = None,
    ) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable
        self.trace_event_id = trace_event_id


WeeklyDagNodeHandler = Callable[[WeeklyDagClaim], Awaitable[WeeklyDagNodeResult]]


class WeeklyDagRepository(Protocol):
    async def enqueue(
        self,
        *,
        run_id: UUID,
        task_id: str,
        week_start: date,
        input_fingerprint: str,
        request_fingerprint: str,
        now: datetime,
    ) -> tuple[WeeklyDagRunSnapshot, bool]: ...

    async def get_status(self, run_id: UUID) -> WeeklyDagStatusProjection: ...

    async def completed_week_starts(self) -> frozenset[date]: ...

    async def claim_ready(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> WeeklyDagClaim | None: ...

    async def heartbeat(
        self,
        claim: WeeklyDagClaim,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> bool: ...

    async def complete(
        self,
        claim: WeeklyDagClaim,
        *,
        result: WeeklyDagNodeResult,
        execution_artifact_id: UUID,
        trace_event_id: UUID,
        now: datetime,
    ) -> WeeklyDagStatusProjection: ...

    async def fail(
        self,
        claim: WeeklyDagClaim,
        *,
        error_code: str,
        retryable: bool,
        available_at: datetime,
        now: datetime,
        trace_event_id: UUID | None,
    ) -> WeeklyDagStatusProjection: ...

    async def retry(
        self,
        *,
        run_id: UUID,
        node_key: str,
        now: datetime,
    ) -> WeeklyDagStatusProjection: ...


@dataclass(frozen=True, slots=True)
class WeeklyDagGovernedResult:
    result: WeeklyDagNodeResult
    execution_artifact_id: UUID
    trace_event_id: UUID


class WeeklyDagGovernance(Protocol):
    async def ensure_run(
        self,
        *,
        run_id: UUID,
        task_id: str,
        request_fingerprint: str,
    ) -> None: ...

    async def execute_node(
        self,
        *,
        claim: WeeklyDagClaim,
        handler: WeeklyDagNodeHandler,
    ) -> WeeklyDagGovernedResult: ...

    async def abandon_node(self, claim: WeeklyDagClaim) -> None: ...

    async def complete_run(self, status: WeeklyDagStatusProjection) -> None: ...


class WeeklyDagHandlerRegistry(Protocol):
    def get(self, node: WeeklyDagNodeSnapshot) -> WeeklyDagNodeHandler: ...
