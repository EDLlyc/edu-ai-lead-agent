from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from app.application.ports.official_account_weekly_dag import (
    WeeklyDagGovernance,
    WeeklyDagGovernedResult,
    WeeklyDagHandlerRegistry,
    WeeklyDagNodeFailure,
    WeeklyDagNodeHandler,
    WeeklyDagRepository,
)
from app.domain.official_account_weekly_dag import (
    WEEKLY_DAG_NODE_BY_KEY,
    WeeklyDagClaim,
    WeeklyDagErrorCode,
    WeeklyDagRunSnapshot,
    WeeklyDagStatusProjection,
    weekly_dag_request_fingerprint,
    weekly_dag_run_id,
    weekly_dag_task_id,
)
from app.domain.official_account_weekly_edition import (
    WeeklyEditionSchedule,
    due_weekly_edition_week_start,
)


class StaticWeeklyDagHandlerRegistry(WeeklyDagHandlerRegistry):
    def __init__(self, handlers: Mapping[str, WeeklyDagNodeHandler]) -> None:
        expected = frozenset(WEEKLY_DAG_NODE_BY_KEY)
        if frozenset(handlers) != expected:
            raise ValueError("weekly DAG handler registry must exactly match the static graph")
        self._handlers = dict(handlers)

    def get(self, node: object) -> WeeklyDagNodeHandler:
        definition = getattr(node, "definition", None)
        key = getattr(definition, "key", None)
        if not isinstance(key, str) or key not in self._handlers:
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.PERMISSION_DENIED.value,
                retryable=False,
            )
        return self._handlers[key]


class OfficialAccountWeeklyDagService:
    def __init__(
        self,
        *,
        repository: WeeklyDagRepository,
        governance: WeeklyDagGovernance,
        handlers: WeeklyDagHandlerRegistry,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._governance = governance
        self._handlers = handlers
        self._clock = clock or (lambda: datetime.now(UTC))

    async def enqueue(
        self,
        *,
        week_start: date,
        input_fingerprint: str,
        now: datetime | None = None,
    ) -> tuple[WeeklyDagRunSnapshot, bool]:
        current = now or self._clock()
        _validate_aware(current)
        run_id = weekly_dag_run_id(week_start)
        task_id = weekly_dag_task_id(week_start)
        request_fingerprint = weekly_dag_request_fingerprint(
            week_start=week_start,
            input_fingerprint=input_fingerprint,
        )
        await self._governance.ensure_run(
            run_id=run_id,
            task_id=task_id,
            request_fingerprint=request_fingerprint,
        )
        return await self._repository.enqueue(
            run_id=run_id,
            task_id=task_id,
            week_start=week_start,
            input_fingerprint=input_fingerprint,
            request_fingerprint=request_fingerprint,
            now=current,
        )

    async def enqueue_due(
        self,
        *,
        input_fingerprint: str,
        now: datetime | None = None,
        schedule: WeeklyEditionSchedule | None = None,
    ) -> tuple[WeeklyDagRunSnapshot, bool] | None:
        current = now or self._clock()
        _validate_aware(current)
        completed = await self._repository.completed_week_starts()
        week_start = due_weekly_edition_week_start(
            current,
            schedule=schedule or WeeklyEditionSchedule(),
            completed_week_starts=completed,
        )
        if week_start is None:
            return None
        return await self.enqueue(
            week_start=week_start,
            input_fingerprint=input_fingerprint,
            now=current,
        )

    async def status(self, run_id: UUID) -> WeeklyDagStatusProjection:
        status = await self._repository.get_status(run_id)
        if status.run.status.value in {"ready", "terminal_failed"}:
            await self._governance.complete_run(status)
        return status

    async def retry(
        self,
        *,
        run_id: UUID,
        node_key: str,
        now: datetime | None = None,
    ) -> WeeklyDagStatusProjection:
        if node_key not in WEEKLY_DAG_NODE_BY_KEY:
            raise ValueError("weekly DAG retry node is unknown")
        current = now or self._clock()
        _validate_aware(current)
        return await self._repository.retry(run_id=run_id, node_key=node_key, now=current)

    async def process_once(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> WeeklyDagStatusProjection | None:
        if not 3 <= lease_seconds <= 3600:
            raise ValueError("weekly DAG lease must be between 3 and 3600 seconds")
        claim = await self._repository.claim_ready(
            worker_id=worker_id,
            now=self._clock(),
            lease_seconds=lease_seconds,
        )
        if claim is None:
            return None
        handler = self._handlers.get(claim.node)
        governed: WeeklyDagGovernedResult
        try:
            governed = await self._execute_with_heartbeat(
                claim=claim,
                handler=handler,
                lease_seconds=lease_seconds,
            )
        except WeeklyDagNodeFailure as error:
            return await self._fail_claim(
                claim,
                error=error,
            )
        except asyncio.CancelledError:
            await self._governance.abandon_node(claim)
            current = self._clock()
            status = await self._repository.fail(
                claim,
                error_code=WeeklyDagErrorCode.LEASE_LOST.value,
                retryable=True,
                available_at=current + _retry_delay(claim.node.attempt_count),
                now=current,
                trace_event_id=None,
            )
            await self._complete_if_terminal(status)
            raise
        except Exception:
            return await self._fail_claim(
                claim,
                error=WeeklyDagNodeFailure(
                    WeeklyDagErrorCode.CAPABILITY_FAILED.value,
                    retryable=True,
                ),
            )
        try:
            status = await self._repository.complete(
                claim,
                result=governed.result,
                execution_artifact_id=governed.execution_artifact_id,
                trace_event_id=governed.trace_event_id,
                now=self._clock(),
            )
        except WeeklyDagNodeFailure as error:
            return await self._fail_claim(claim, error=error)
        await self._complete_if_terminal(status)
        return status

    async def _fail_claim(
        self,
        claim: WeeklyDagClaim,
        *,
        error: WeeklyDagNodeFailure,
    ) -> WeeklyDagStatusProjection:
        await self._governance.abandon_node(claim)
        current = self._clock()
        status = await self._repository.fail(
            claim,
            error_code=error.error_code,
            retryable=error.retryable,
            available_at=current + _retry_delay(claim.node.attempt_count),
            now=current,
            trace_event_id=error.trace_event_id,
        )
        await self._complete_if_terminal(status)
        return status

    async def _complete_if_terminal(self, status: WeeklyDagStatusProjection) -> None:
        if status.run.status.value in {"ready", "terminal_failed"}:
            await self._governance.complete_run(status)

    async def _execute_with_heartbeat(
        self,
        *,
        claim: WeeklyDagClaim,
        handler: WeeklyDagNodeHandler,
        lease_seconds: int,
    ) -> WeeklyDagGovernedResult:
        execution = asyncio.create_task(self._governance.execute_node(claim=claim, handler=handler))
        heartbeat = asyncio.create_task(
            self._heartbeat_until_done(
                claim=claim,
                execution=execution,
                lease_seconds=lease_seconds,
            )
        )
        try:
            done, _pending = await asyncio.wait(
                {execution, heartbeat},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if execution in done:
                return await execution
            if heartbeat in done:
                if not execution.done():
                    execution.cancel()
                    await asyncio.gather(execution, return_exceptions=True)
                try:
                    heartbeat.result()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    raise WeeklyDagNodeFailure(
                        WeeklyDagErrorCode.LEASE_LOST.value,
                        retryable=True,
                    ) from None
                raise WeeklyDagNodeFailure(
                    WeeklyDagErrorCode.LEASE_LOST.value,
                    retryable=True,
                )
            raise AssertionError("weekly DAG heartbeat wait returned without a completed task")
        finally:
            if not execution.done():
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat_until_done(
        self,
        *,
        claim: WeeklyDagClaim,
        execution: asyncio.Task[WeeklyDagGovernedResult],
        lease_seconds: int,
    ) -> None:
        interval = max(1.0, min(20.0, lease_seconds / 3))
        while not execution.done():
            await asyncio.sleep(interval)
            if execution.done():
                return
            alive = await self._repository.heartbeat(
                claim,
                now=self._clock(),
                lease_seconds=lease_seconds,
            )
            if not alive:
                return


def _retry_delay(attempt_count: int) -> timedelta:
    return timedelta(seconds=min(300, 2 ** max(0, min(attempt_count, 8))))


def _validate_aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise ValueError("weekly DAG service time must be timezone-aware")
