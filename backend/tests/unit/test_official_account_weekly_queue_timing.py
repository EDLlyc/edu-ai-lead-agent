"""Synthetic three-build-node timing, not provider latency or a full draft/SQL test.

Use real production handlers, weekly governance, gateway accounting and service backoff.
Only storage and a single Article producer are in memory. The local asyncio facade is
necessary because the existing Article handler has no injectable clock; global asyncio
and its timeout/cancellation implementation remain untouched.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, replace
from datetime import timedelta
from heapq import heappop, heappush
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.application.ports.execution_governance import BudgetReservationSnapshot
from app.application.ports.official_account_weekly_dag import WeeklyDagNodeFailure
from app.application.ports.official_account_weekly_production import (
    WEEKLY_PRODUCTION_FROZEN_INPUT_VERSION,
)
from app.application.services import execution_governance as gateway_module
from app.application.services import official_account_weekly_production as handler_module
from app.application.services.official_account_weekly_dag import OfficialAccountWeeklyDagService
from app.application.services.official_account_weekly_production import ProductionWeeklyDagHandlers
from app.domain.execution_governance import (
    ArtifactKind,
    ArtifactMetadata,
    BudgetUsage,
    BudgetVector,
    ExecutionEventKind,
    ExecutionEventStatus,
    ExecutionRole,
    ExecutionRunStatus,
    GovernanceDeniedError,
    GovernanceErrorCode,
    SafeEventDraft,
)
from app.domain.official_account_weekly_dag import (
    WEEKLY_DAG_NODES,
    WEEKLY_DAG_ROOT_AGENT_ID,
    WeeklyDagNodeKind,
    WeeklyDagNodeStatus,
)
from app.infrastructure.db import execution_governance as ledger_module
from app.infrastructure.db.models import ExecutionAgentAllocationModel
from app.infrastructure.official_account_runtime import official_account_identity_from_settings
from app.infrastructure.official_account_weekly_dag_governance import (
    PostgresOfficialAccountWeeklyDagGovernance,
    weekly_dag_node_limits,
    weekly_dag_root_limits,
)
from app.infrastructure.official_account_weekly_production import LocalWeeklyProductionArtifactOwner
from test_official_account_strict_visual_policy import _settings
from test_official_account_weekly_production import (
    _claim,
    _production_input,
    _UnusedPreparedArtifacts,
)


class _Clock:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.timers = []
        self.sequence = count()

    def time(self) -> float:
        return self.seconds

    async def sleep(self, seconds: float) -> None:
        future = asyncio.get_running_loop().create_future()
        heappush(self.timers, (self.seconds + seconds, next(self.sequence), future))
        await future

    async def until(self, predicate) -> None:
        for _ in range(10_000):
            # Drain task creation, gateway completion and the serial producer's next claim.
            for _ in range(12):
                await asyncio.sleep(0)
            if predicate():
                return
            while self.timers and self.timers[0][2].done():
                heappop(self.timers)
            assert self.timers, "synthetic queue deadlocked"
            self.seconds = self.timers[0][0]
            while self.timers and self.timers[0][0] <= self.seconds:
                _, _, future = heappop(self.timers)
                if not future.done():
                    future.set_result(None)
        pytest.fail("synthetic queue exceeded its bounded step count")


@dataclass
class _Article:
    id: UUID
    status: str = "queued"


class _SerialArticles:
    """An actual single coroutine consumes each newly enqueued identity once."""

    def __init__(self, clock: _Clock, duration: float, unknown_role: int | None) -> None:
        self.clock = clock
        self.duration = duration
        self.unknown_role = unknown_role
        self.queue = asyncio.Queue()
        self.by_identity = {}
        self.runs = {}
        self.enqueue_calls = []
        self.executions = Counter()
        self.completed_at = {}
        self.active = 0
        self.peak_active = 0

    async def enqueue_material_package(self, *, material_package_id, identity):
        key = (material_package_id, identity)
        self.enqueue_calls.append(key)
        created = key not in self.by_identity
        if created:
            run = _Article(uuid4())
            self.by_identity[key] = run
            self.runs[run.id] = run
            self.queue.put_nowait(run)
        return self.by_identity[key], created

    async def get_run(self, run_id):
        return self.runs[run_id]

    async def execute(self) -> None:
        for ordinal in range(3):
            run = await self.queue.get()
            self.executions[run.id] += 1
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
            run.status = "generating"
            await self.clock.sleep(self.duration)
            run.status = "result_unknown" if ordinal == self.unknown_role else "ready"
            self.completed_at[run.id] = self.clock.time()
            self.active -= 1
            self.queue.task_done()


def _initialize_counters(model) -> None:
    # SQLAlchemy insert defaults do not run for unpersisted test records.
    for name in BudgetUsage().as_dict():
        setattr(model, f"used_{name}", 0)
    for name in BudgetVector().as_dict():
        setattr(model, f"reserved_{name}", 0)
    model.reserved_child_count = 0


class _BudgetLedger(ledger_module.PostgresExecutionGovernanceRepository):
    """Memory storage around real root-child allocation and budget arithmetic.

    Inherited allocate_child executes the production 70%-delegation and complete-ceiling
    checks. Only its three SQL reads/insert are stubbed; this tests no SQL locking claim.
    Gateway reservations/reconciliation use the same production arithmetic helpers.
    """

    def __init__(self, claim) -> None:
        self.models = {}
        self.reservations = {}
        self.events = []
        self.artifacts = {}
        self.root = ExecutionAgentAllocationModel(
            run_id=claim.run.run_id,
            task_id=claim.run.task_id,
            agent_id=WEEKLY_DAG_ROOT_AGENT_ID,
            role=ExecutionRole.ORCHESTRATOR.value,
            status=ExecutionRunStatus.RUNNING.value,
            depth=0,
            next_seq_no=1,
            **ledger_module._limit_model_values(weekly_dag_root_limits()),
        )
        _initialize_counters(self.root)
        self.models[self.root.agent_id] = self.root
        root_identity = ledger_module._allocation_snapshot(self.root).identity
        self.parent_event = SafeEventDraft(
            identity=root_identity,
            event_id=uuid4(),
            kind=ExecutionEventKind.RUN_STARTED,
            status=ExecutionEventStatus.STARTED,
        ).materialize(0)
        self.events.append(self.parent_event)
        super().__init__(self._allocation_session)

    def _allocation_session(self):
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.begin.return_value.__aenter__ = AsyncMock()
        session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
        session.scalar = AsyncMock(side_effect=[self.root, self.parent_event, None])
        session.flush = AsyncMock()

        def insert(model):
            _initialize_counters(model)
            assert model.agent_id not in self.models
            self.models[model.agent_id] = model

        session.add.side_effect = insert
        return session

    async def get_allocation(self, identity):
        return ledger_module._allocation_snapshot(self.models[identity.agent_id])

    async def reserve_budget(self, *, identity, reservation_id, requested):
        model = self.models[identity.agent_id]
        if not ledger_module._fits_allocation(model, requested):
            raise GovernanceDeniedError(GovernanceErrorCode.BUDGET_EXHAUSTED)
        ledger_module._add_reserved(model, requested)
        self.reservations[reservation_id] = (identity, requested)
        return BudgetReservationSnapshot(reservation_id, identity, requested, False)

    async def reconcile_budget(self, *, identity, reservation_id, actual):
        owner, reserved = self.reservations.pop(reservation_id)
        assert owner == identity
        assert ledger_module._actual_fits_reservation(actual, reserved)
        ledger_module._replace_reserved_usage_with_actual(
            self.models[identity.agent_id], reserved=reserved, actual=actual
        )
        return BudgetReservationSnapshot(reservation_id, identity, reserved, True)

    async def append_event(self, draft):
        model = self.models[draft.identity.agent_id]
        event = draft.materialize(model.next_seq_no)
        model.next_seq_no += 1
        self.events.append(event)
        return event

    async def register_artifact(self, *, event, artifact):
        self.artifacts[artifact.artifact_id] = artifact
        return await self.append_event(event), artifact

    async def validate_artifact_scope(self, *, identity, artifact_ids):
        return all(
            item in self.artifacts and self.artifacts[item].identity.run_id == identity.run_id
            for item in artifact_ids
        )

    async def complete_allocation(self, *, identity, status):
        model = self.models[identity.agent_id]
        assert not any(owner == identity for owner, _ in self.reservations.values())
        model.status = status.value
        ledger_module._subtract_reserved(
            self.root, ledger_module._limits_from_allocation(model).ceiling_vector()
        )
        self.root.reserved_child_count -= 1
        ledger_module._add_child_actual_usage(
            self.root, ledger_module._usage_from_allocation(model)
        )
        return True


class _WeeklyGovernance(PostgresOfficialAccountWeeklyDagGovernance):
    async def _recover_stale_children(self, run_id, task_id):
        # No crashed process or database in this simulation; covered by integration tests.
        return None

    async def _parent_event_id(self, claim):
        return self._repository.parent_event.event_id

    async def abandon_node(self, claim):
        # Real execute_node already reconciles and closes these settled attempts.
        return None


class _FailureRecorder:
    """Observe the real service's persisted failure/backoff arguments, not invent them."""

    def __init__(self) -> None:
        self.failures = []

    async def fail(self, claim, **fields):
        self.failures.append((claim, fields))
        return SimpleNamespace(run=SimpleNamespace(status=SimpleNamespace(value="partial")))


class _Scenario:
    def __init__(self, tmp_path, monkeypatch, *, duration, unknown_role=None) -> None:
        self.clock = _Clock()
        monkeypatch.setattr(
            handler_module,
            "asyncio",
            SimpleNamespace(get_running_loop=lambda: self.clock, sleep=self.clock.sleep),
        )
        monkeypatch.setattr(gateway_module, "monotonic", self.clock.time)
        self.identity = official_account_identity_from_settings(
            _settings(), provider="zhipu", model="glm-5.2"
        )
        planned = replace(
            _production_input(),
            version=WEEKLY_PRODUCTION_FROZEN_INPUT_VERSION,
            article_identity=self.identity,
        )
        self.checkpoints = LocalWeeklyProductionArtifactOwner(tmp_path / "checkpoints")
        source = self.checkpoints.put_json(planned.as_dict())
        schedule_claim = _claim(planned=planned, ordinal=0)
        self.ledger = _BudgetLedger(schedule_claim)
        selection_artifact_id = uuid4()
        selection = replace(
            schedule_claim.node,
            definition=WEEKLY_DAG_NODES[1],
            status=WeeklyDagNodeStatus.SUCCEEDED,
            output_artifact=source,
            execution_artifact_id=selection_artifact_id,
            trace_event_id=self.ledger.parent_event.event_id,
        )
        self.ledger.artifacts[selection_artifact_id] = ArtifactMetadata(
            identity=self.ledger.parent_event.identity,
            artifact_id=selection_artifact_id,
            producer_event_id=self.ledger.parent_event.event_id,
            kind=ArtifactKind.CHECKPOINT,
            media_type=source.media_type,
            byte_size=source.byte_size,
            sha256=source.fingerprint,
        )
        self.claims = tuple(
            _claim(planned=planned, ordinal=node.ordinal, dependencies=(selection,))
            for node in WEEKLY_DAG_NODES
            if node.kind is WeeklyDagNodeKind.BUILD_ARTICLE
        )
        self.articles = _SerialArticles(self.clock, duration, unknown_role)
        self.handlers = ProductionWeeklyDagHandlers(
            checkpoints=self.checkpoints,
            article_repository=self.articles,
            prepared_artifacts=_UnusedPreparedArtifacts(),
            # A settings drift must not change the identity frozen in the weekly input.
            article_identity=replace(self.identity, model="changed-current-model"),
            article_wait_seconds=720,
        )
        self.governance = _WeeklyGovernance(repository=self.ledger, session_factory=None)
        self.failures = _FailureRecorder()
        self.service = OfficialAccountWeeklyDagService(
            repository=self.failures,
            governance=self.governance,
            handlers=self.handlers.registry(),
            clock=lambda: self.claims[0].run.created_at + timedelta(seconds=self.clock.time()),
        )
        self.attempts = Counter()
        self.tasks = []

    async def _build_with_retry(self, original):
        for attempt in range(1, original.node.max_attempts + 1):
            claim = replace(original, node=replace(original.node, attempt_count=attempt))
            self.attempts[claim.node.definition.role] += 1
            try:
                result = await self.governance.execute_node(
                    claim=claim, handler=self.handlers.execute
                )
            except WeeklyDagNodeFailure as error:
                await self.service._fail_claim(claim, error=error)
                if not error.retryable:
                    return error
                # Use actual service-produced available_at, not a test-chosen delay.
                _, fields = self.failures.failures[-1]
                await self.clock.sleep((fields["available_at"] - fields["now"]).total_seconds())
            else:
                return result
        pytest.fail("representative case unexpectedly exhausted all node attempts")

    async def start(self):
        self.producer = asyncio.create_task(self.articles.execute())
        self.tasks = [asyncio.create_task(self._build_with_retry(claim)) for claim in self.claims]
        await self.clock.until(lambda: all(task.done() for task in self.tasks))
        return [task.result() for task in self.tasks]

    async def close(self) -> None:
        for task in [*self.tasks, self.producer]:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, self.producer, return_exceptions=True)

    def assert_single_execution_and_closed_budget(self) -> None:
        assert self.articles.peak_active == 1
        assert len(self.articles.runs) == 3
        assert list(self.articles.executions.values()) == [1, 1, 1]
        assert all(identity == self.identity for _, identity in self.articles.enqueue_calls)
        assert self.ledger.root.reserved_child_count == 0
        assert self.ledger.root.reserved_elapsed_ms == 0
        assert self.ledger.reservations == {}
        assert self.ledger.root.used_elapsed_ms < weekly_dag_root_limits().elapsed_ms


@pytest.mark.asyncio
async def test_three_serial_articles_reuse_third_identity_after_queue_inclusive_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = _Scenario(tmp_path, monkeypatch, duration=288.249)
    try:
        results = await scenario.start()
        assert all(not isinstance(result, WeeklyDagNodeFailure) for result in results)
        assert list(scenario.attempts.values()) == [1, 1, 2]
        assert list(scenario.articles.completed_at.values()) == pytest.approx(
            [288.249, 576.498, 864.747]
        )
        assert scenario.clock.time() == 866
        assert len(scenario.failures.failures) == 1
        claim, failure = scenario.failures.failures[0]
        assert claim.node.definition.role.value == "application_case"
        assert failure["error_code"] == "capability_timeout"
        assert failure["retryable"] is True
        assert (failure["now"] - claim.run.created_at).total_seconds() == 720
        assert (failure["available_at"] - claim.run.created_at).total_seconds() == 722
        assert len(scenario.articles.enqueue_calls) == 4
        assert scenario.articles.enqueue_calls[2] == scenario.articles.enqueue_calls[3]
        assert {
            scenario.checkpoints.get_json(result.result.artifact)["official_account_run_id"]
            for result in results
        } == {str(run_id) for run_id in scenario.articles.runs}
        # Root accounting sums concurrent waits: 290 + 578 + 720 + 144, not wall time 866.
        assert scenario.ledger.root.used_elapsed_ms == 1_732_000
        assert weekly_dag_node_limits().elapsed_ms == 900_000
        scenario.assert_single_execution_and_closed_budget()
    finally:
        await scenario.close()


@pytest.mark.asyncio
async def test_slow_three_role_queue_hits_real_root_budget_before_independent_articles_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = _Scenario(tmp_path, monkeypatch, duration=1000)
    try:
        results = await scenario.start()
        assert not isinstance(results[0], WeeklyDagNodeFailure)
        for result in results[1:]:
            assert isinstance(result, WeeklyDagNodeFailure)
            # Existing weekly mapping folds delegation-threshold denial into this code;
            # the real governance event still identifies the budget-denied category.
            assert result.error_code == "permission_denied"
            assert result.retryable is False
        assert scenario.clock.time() == 1000
        assert list(scenario.attempts.values()) == [2, 2, 2]
        timeouts = [fields for _, fields in scenario.failures.failures if fields["retryable"]]
        assert len(timeouts) == 3
        assert all(fields["error_code"] == "capability_timeout" for fields in timeouts)
        assert [
            event.error_code
            for event in scenario.ledger.events
            if event.kind is ExecutionEventKind.BUDGET_DENIED
        ] == ["delegation_threshold_reached"] * 2
        # Three 720s waits consume 2160s; the first retry reserves 900s. The next
        # child is denied by the real 70% delegation gate (3060/3600), before enqueue.
        assert len(scenario.articles.enqueue_calls) == 4
        assert scenario.ledger.root.used_elapsed_ms == 2_438_000
        await scenario.clock.until(scenario.producer.done)
        assert scenario.clock.time() == 3000
        assert all(run.status == "ready" for run in scenario.articles.runs.values())
        # Late independent success does not turn failed weekly nodes into success.
        assert [result.error_code for result in results[1:]] == ["permission_denied"] * 2
        scenario.assert_single_execution_and_closed_budget()
    finally:
        await scenario.close()


@pytest.mark.asyncio
async def test_queued_unknown_result_is_terminal_without_another_producer_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = _Scenario(tmp_path, monkeypatch, duration=288.249, unknown_role=2)
    try:
        results = await scenario.start()
        assert all(not isinstance(result, WeeklyDagNodeFailure) for result in results[:2])
        failure = results[2]
        assert isinstance(failure, WeeklyDagNodeFailure)
        assert failure.error_code == "provider_terminal"
        assert failure.retryable is False
        assert list(scenario.attempts.values()) == [1, 1, 2]
        assert len(scenario.articles.enqueue_calls) == 4
        assert [fields["error_code"] for _, fields in scenario.failures.failures] == [
            "capability_timeout",
            "provider_terminal",
        ]
        scenario.assert_single_execution_and_closed_budget()
        # Even an external duplicate enqueue preserves unknown state and never queues it.
        package_id, identity = scenario.articles.enqueue_calls[-1]
        run, created = await scenario.articles.enqueue_material_package(
            material_package_id=package_id, identity=identity
        )
        assert created is False
        assert run.status == "result_unknown"
        assert scenario.articles.queue.empty()
        assert scenario.articles.executions[run.id] == 1
    finally:
        await scenario.close()
