from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from app.application.ports.official_account_weekly_dag import (
    WeeklyDagNodeFailure,
    WeeklyDagNodeHandler,
    WeeklyDagNodeResult,
)
from app.application.services.official_account_weekly_dag import (
    OfficialAccountWeeklyDagService,
    StaticWeeklyDagHandlerRegistry,
)
from app.application.services.official_account_weekly_dag_fixture import (
    LocalWeeklyDagFixtureHandlers,
)
from app.domain.execution_governance import (
    ExecutionIdentity,
    ExecutionRunStatus,
)
from app.domain.official_account_weekly_dag import (
    WEEKLY_DAG_NODES,
    WeeklyDagArtifact,
    WeeklyDagClaim,
    WeeklyDagErrorCode,
    WeeklyDagNodeStatus,
    WeeklyDagRunStatus,
    WeeklyDagStatusProjection,
    weekly_dag_run_id,
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
    OfficialAccountWeeklyDagAttemptModel,
    OfficialAccountWeeklyDagNodeModel,
    OfficialAccountWeeklyDagRunModel,
)
from app.infrastructure.db.official_account_weekly_dag import (
    PostgresOfficialAccountWeeklyDagRepository,
)
from app.infrastructure.official_account_weekly_dag_governance import (
    PostgresOfficialAccountWeeklyDagGovernance,
)
from app.official_account_weekly_edition_demo import (
    build_fixture_weekly_edition_artifact,
)
from sqlalchemy import delete, select

from .conftest import IntegrationContext

_NOW = datetime(2099, 1, 5, 1, tzinfo=UTC)


@contextmanager
def _temporary_output() -> Iterator[Path]:
    with TemporaryDirectory(prefix="weekly-dag-test-") as value:
        yield Path(value)


def _artifact_result(claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
    node = claim.node
    run = claim.run
    fingerprint = sha256(
        f"{run.request_fingerprint}:{node.definition.key}:{node.input_fingerprint}".encode()
    ).hexdigest()
    artifact = WeeklyDagArtifact(
        opaque_ref=f"weekly.{run.run_id.hex}.{node.definition.ordinal:02d}",
        fingerprint=fingerprint,
        media_type="application/json",
        byte_size=128 + node.definition.ordinal,
    )
    return WeeklyDagNodeResult(
        artifact=artifact,
        aggregate_artifact=artifact if node.definition.key in {"aggregate", "finalize"} else None,
    )


async def _handler(claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
    return _artifact_result(claim)


def _service(
    context: IntegrationContext,
    *,
    handler: WeeklyDagNodeHandler = _handler,
    now: datetime = _NOW,
) -> tuple[OfficialAccountWeeklyDagService, PostgresOfficialAccountWeeklyDagRepository]:
    repository = PostgresOfficialAccountWeeklyDagRepository(context.session_factory)
    governance_repository = PostgresExecutionGovernanceRepository(context.session_factory)
    governance = PostgresOfficialAccountWeeklyDagGovernance(
        repository=governance_repository,
        session_factory=context.session_factory,
    )
    registry = StaticWeeklyDagHandlerRegistry(
        {definition.key: handler for definition in WEEKLY_DAG_NODES}
    )
    return (
        OfficialAccountWeeklyDagService(
            repository=repository,
            governance=governance,
            handlers=registry,
            clock=lambda: now,
        ),
        repository,
    )


async def _delete_run(context: IntegrationContext, run_id: object) -> None:
    async with context.session_factory() as session:
        for model in (
            OfficialAccountWeeklyDagAttemptModel,
            OfficialAccountWeeklyDagNodeModel,
            OfficialAccountWeeklyDagRunModel,
            ExecutionBudgetReservationModel,
            ExecutionArtifactModel,
            ExecutionTraceEventModel,
            ExecutionAgentAllocationModel,
            ExecutionGovernedRunModel,
        ):
            column = model.run_id if hasattr(model, "run_id") else model.id
            await session.execute(delete(model).where(column == run_id))
        await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_weekly_dag_runs_three_branches_with_governed_metadata_only_checkpoints(
    integration_context: IntegrationContext,
) -> None:
    week_start = date(2099, 1, 5)
    run_id = weekly_dag_run_id(week_start)
    service, _repository = _service(integration_context)
    try:
        run, created = await service.enqueue(
            week_start=week_start,
            input_fingerprint=sha256(b"weekly-e2e").hexdigest(),
            now=_NOW,
        )
        assert created
        replay, replay_created = await service.enqueue(
            week_start=week_start,
            input_fingerprint=sha256(b"weekly-e2e").hexdigest(),
            now=_NOW,
        )
        assert not replay_created
        assert replay == run

        first_status = await service.process_once(worker_id="worker.schedule", lease_seconds=30)
        assert first_status is not None
        assert first_status.nodes[0].status is WeeklyDagNodeStatus.SUCCEEDED, (
            first_status.nodes[0].status,
            first_status.nodes[0].error_code,
        )
        assert await service.process_once(worker_id="worker.selection", lease_seconds=30)
        branch_results = await asyncio.gather(
            *(
                service.process_once(worker_id=f"worker.branch.{index}", lease_seconds=30)
                for index in range(3)
            )
        )
        assert all(result is not None for result in branch_results)
        branch_status = await service.status(run_id)
        assert {
            node.definition.role.value
            for node in branch_status.nodes
            if node.definition.kind.value == "build_article"
            and node.status is WeeklyDagNodeStatus.SUCCEEDED
            and node.definition.role is not None
        } == {"official_anchor", "industry_trend", "application_case"}

        for cycle in range(20):
            outcomes = await asyncio.gather(
                *(
                    service.process_once(
                        worker_id=f"worker.drain.{cycle}.{index}",
                        lease_seconds=30,
                    )
                    for index in range(3)
                )
            )
            status = await service.status(run_id)
            if status.run.status is WeeklyDagRunStatus.READY:
                break
            assert any(outcome is not None for outcome in outcomes)
        else:
            pytest.fail("weekly DAG did not drain to ready")

        status = await service.status(run_id)
        assert status.run.status is WeeklyDagRunStatus.READY
        assert status.run.aggregate_artifact is not None
        assert all(node.status is WeeklyDagNodeStatus.SUCCEEDED for node in status.nodes)
        assert all(node.attempt_count == 1 for node in status.nodes)
        serialized = str(status.as_dict()).lower()
        assert "prompt" not in serialized
        assert "lease_owner" not in serialized
        assert "provider_body" not in serialized

        async with integration_context.session_factory() as session:
            attempts = tuple(
                await session.scalars(
                    select(OfficialAccountWeeklyDagAttemptModel).where(
                        OfficialAccountWeeklyDagAttemptModel.run_id == run_id
                    )
                )
            )
            governed_run = await session.get(ExecutionGovernedRunModel, run_id)
            trace = tuple(
                await session.scalars(
                    select(ExecutionTraceEventModel).where(
                        ExecutionTraceEventModel.run_id == run_id
                    )
                )
            )
        assert len(attempts) == 16
        assert all(attempt.status == "succeeded" for attempt in attempts)
        assert governed_run is not None
        assert governed_run.status == ExecutionRunStatus.SUCCEEDED.value
        assert all(event.model_turns == 0 for event in trace)
        assert all(event.input_tokens in {0, None} for event in trace)
        assert all(event.output_tokens in {0, None} for event in trace)
    finally:
        await _delete_run(integration_context, run_id)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_retry_is_branch_local_and_never_rebuilds_successful_sibling(
    integration_context: IntegrationContext,
) -> None:
    week_start = date(2099, 1, 12)
    run_id = weekly_dag_run_id(week_start)

    async def fail_once(claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        node = claim.node
        if node.definition.key == "industry_trend:build_article" and node.attempt_count == 1:
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.CAPABILITY_FAILED.value,
                retryable=True,
            )
        return _artifact_result(claim)

    service, _repository = _service(
        integration_context,
        handler=fail_once,
        now=_NOW + timedelta(days=7),
    )
    try:
        await service.enqueue(
            week_start=week_start,
            input_fingerprint=sha256(b"weekly-retry").hexdigest(),
            now=_NOW + timedelta(days=7),
        )
        for index in range(10):
            status = await service.process_once(
                worker_id=f"worker.retry.before.{index}",
                lease_seconds=30,
            )
            assert status is not None
            if status.run.status is WeeklyDagRunStatus.RETRYABLE_FAILED:
                break
        else:
            pytest.fail("weekly DAG did not expose the retryable branch failure")
        failed = await service.status(run_id)
        assert failed.run.aggregate_artifact is None
        official_before = {
            node.definition.key: node.attempt_count
            for node in failed.nodes
            if node.definition.role is not None
            and node.definition.role.value == "official_anchor"
            and node.status is WeeklyDagNodeStatus.SUCCEEDED
        }
        assert official_before

        retried = await service.retry(
            run_id=run_id,
            node_key="industry_trend:build_article",
            now=_NOW + timedelta(days=7),
        )
        assert retried.run.status is WeeklyDagRunStatus.PARTIAL
        for index in range(20):
            status = await service.process_once(
                worker_id=f"worker.retry.after.{index}",
                lease_seconds=30,
            )
            assert status is not None
            if status.run.status is WeeklyDagRunStatus.READY:
                break
        else:
            pytest.fail("weekly DAG did not recover after branch-local retry")
        ready = await service.status(run_id)
        assert ready.run.status is WeeklyDagRunStatus.READY
        assert {
            node.definition.key: node.attempt_count
            for node in ready.nodes
            if node.definition.key in official_before
        } == official_before
        assert (
            next(
                node
                for node in ready.nodes
                if node.definition.key == "industry_trend:build_article"
            ).attempt_count
            == 2
        )
    finally:
        await _delete_run(integration_context, run_id)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_claim_is_once_only_and_expiry_fences_stale_worker(
    integration_context: IntegrationContext,
) -> None:
    week_start = date(2099, 1, 19)
    run_id = weekly_dag_run_id(week_start)
    service, repository = _service(
        integration_context,
        now=_NOW + timedelta(days=14),
    )
    current = _NOW + timedelta(days=14)
    try:
        input_fingerprint = sha256(b"weekly-fencing").hexdigest()
        await service.enqueue(
            week_start=week_start,
            input_fingerprint=input_fingerprint,
            now=current,
        )
        claims = await asyncio.gather(
            *(
                repository.claim_ready(
                    worker_id=f"fence.worker.{index}",
                    now=current,
                    lease_seconds=3,
                )
                for index in range(6)
            )
        )
        first = next(claim for claim in claims if claim is not None)
        assert sum(claim is not None for claim in claims) == 1
        second = await repository.claim_ready(
            worker_id="fence.worker.replacement",
            now=current + timedelta(seconds=4),
            lease_seconds=3,
        )
        assert second is not None
        assert second.node.definition.key == "schedule"
        assert second.node.attempt_count == 2
        assert second.node.fencing_token == first.node.fencing_token + 1
        with pytest.raises(WeeklyDagNodeFailure) as stale:
            await repository.fail(
                first,
                error_code=WeeklyDagErrorCode.CAPABILITY_FAILED.value,
                retryable=True,
                available_at=current + timedelta(seconds=5),
                now=current + timedelta(seconds=4),
                trace_event_id=None,
            )
        assert stale.value.error_code == WeeklyDagErrorCode.LEASE_LOST.value

        async with integration_context.session_factory() as session:
            attempts = tuple(
                await session.scalars(
                    select(OfficialAccountWeeklyDagAttemptModel)
                    .where(OfficialAccountWeeklyDagAttemptModel.run_id == run_id)
                    .order_by(OfficialAccountWeeklyDagAttemptModel.attempt_no)
                )
            )
        assert [attempt.status for attempt in attempts] == ["lease_expired", "running"]
        assert attempts[0].error_code == WeeklyDagErrorCode.LEASE_LOST.value
    finally:
        await _delete_run(integration_context, run_id)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_fixture_dag_matches_one_shot_bytes_and_records_zero_social_calls(
    integration_context: IntegrationContext,
) -> None:
    week_start = date(2026, 8, 31)
    run_id = weekly_dag_run_id(week_start)
    with _temporary_output() as output_root:
        repository = PostgresOfficialAccountWeeklyDagRepository(integration_context.session_factory)
        governance_repository = PostgresExecutionGovernanceRepository(
            integration_context.session_factory
        )
        governance = PostgresOfficialAccountWeeklyDagGovernance(
            repository=governance_repository,
            session_factory=integration_context.session_factory,
        )
        service = OfficialAccountWeeklyDagService(
            repository=repository,
            governance=governance,
            handlers=LocalWeeklyDagFixtureHandlers(output_root).registry(),
            clock=lambda: datetime(2026, 8, 31, 1, tzinfo=UTC),
        )
        try:
            await service.enqueue(
                week_start=week_start,
                input_fingerprint=sha256(b"weekly-fixture-exact-bytes").hexdigest(),
                now=datetime(2026, 8, 31, 1, tzinfo=UTC),
            )
            for index in range(len(WEEKLY_DAG_NODES)):
                reconstructed_governance = PostgresOfficialAccountWeeklyDagGovernance(
                    repository=governance_repository,
                    session_factory=integration_context.session_factory,
                )
                service = OfficialAccountWeeklyDagService(
                    repository=repository,
                    governance=reconstructed_governance,
                    handlers=LocalWeeklyDagFixtureHandlers(output_root).registry(),
                    clock=lambda: datetime(2026, 8, 31, 1, tzinfo=UTC),
                )
                status = await service.process_once(
                    worker_id=f"worker.fixture.{index}",
                    lease_seconds=60,
                )
                assert status is not None

            ready = await service.status(run_id)
            expected = await build_fixture_weekly_edition_artifact()
            assert ready.run.status is WeeklyDagRunStatus.READY
            assert ready.run.aggregate_artifact is not None
            assert ready.run.aggregate_artifact.fingerprint == expected.batch_fingerprint
            assert ready.run.aggregate_artifact.byte_size == len(expected.zip_bytes)

            target = (
                output_root
                / "weekly"
                / f"official-account-weekly-edition-{expected.batch_fingerprint[:16]}"
            )
            actual_paths = {
                path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()
            }
            expected_paths = {*expected.files, expected.bundle_filename}
            assert actual_paths == expected_paths
            assert all(
                (target / relative).read_bytes() == body
                for relative, body in expected.files.items()
            )
            assert (target / expected.bundle_filename).read_bytes() == expected.zip_bytes
            manifest = json.loads((target / "manifest.json").read_bytes())
            assert manifest["social_delivery_calls"] == 0
            assert manifest["published"] is False
            assert manifest["local_only"] is True
        finally:
            await _delete_run(integration_context, run_id)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_budget_permission_and_terminal_provider_fail_closed_before_aggregate(
    integration_context: IntegrationContext,
) -> None:
    def handler_for(mode: str) -> WeeklyDagNodeHandler:
        async def fail_closed_handler(claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
            if mode == "budget":
                result = _artifact_result(claim)
                return WeeklyDagNodeResult(
                    artifact=result.artifact,
                    model_turns=1,
                    input_tokens=1,
                    output_tokens=1,
                )
            if mode == "provider":
                raise WeeklyDagNodeFailure(
                    WeeklyDagErrorCode.PROVIDER_TERMINAL.value,
                    retryable=False,
                )
            pytest.fail("permission denial must happen before handler execution")

        return fail_closed_handler

    cases = (
        (date(2099, 1, 26), "budget", WeeklyDagErrorCode.BUDGET_EXHAUSTED.value),
        (date(2099, 2, 2), "permission", WeeklyDagErrorCode.PERMISSION_DENIED.value),
        (date(2099, 2, 9), "provider", WeeklyDagErrorCode.PROVIDER_TERMINAL.value),
    )
    for week_start, mode, expected_error in cases:
        run_id = weekly_dag_run_id(week_start)
        service, _repository = _service(
            integration_context,
            handler=handler_for(mode),
            now=_NOW + timedelta(days=21),
        )
        governance_repository = PostgresExecutionGovernanceRepository(
            integration_context.session_factory
        )
        try:
            run, _created = await service.enqueue(
                week_start=week_start,
                input_fingerprint=sha256(f"weekly-{mode}".encode()).hexdigest(),
                now=_NOW + timedelta(days=21),
            )
            if mode == "permission":
                await governance_repository.complete_allocation(
                    identity=ExecutionIdentity(
                        run_id=run.run_id,
                        task_id=run.task_id,
                        agent_id="weekly.orchestrator",
                    ),
                    status=ExecutionRunStatus.FAILED,
                )

            failed = await service.process_once(
                worker_id=f"worker.fail-closed.{mode}",
                lease_seconds=30,
            )
            assert failed is not None
            assert failed.run.status is WeeklyDagRunStatus.TERMINAL_FAILED
            assert failed.run.aggregate_artifact is None
            assert failed.nodes[0].status is WeeklyDagNodeStatus.TERMINAL_FAILED
            assert failed.nodes[0].error_code == expected_error
            assert all(node.status is WeeklyDagNodeStatus.PENDING for node in failed.nodes[1:])
            with pytest.raises(ValueError, match="retryable failed"):
                await service.retry(
                    run_id=run_id,
                    node_key="schedule",
                    now=_NOW + timedelta(days=21),
                )
            if mode != "permission":
                async with integration_context.session_factory() as session:
                    governed_run = await session.get(ExecutionGovernedRunModel, run_id)
                    root_failure = await session.scalar(
                        select(ExecutionTraceEventModel)
                        .where(
                            ExecutionTraceEventModel.run_id == run_id,
                            ExecutionTraceEventModel.agent_id == "weekly.orchestrator",
                            ExecutionTraceEventModel.kind == "run_failed",
                        )
                        .order_by(ExecutionTraceEventModel.created_at.desc())
                        .limit(1)
                    )
                assert governed_run is not None
                assert governed_run.status == ExecutionRunStatus.FAILED.value
                assert root_failure is not None
                assert root_failure.error_code == expected_error
        finally:
            await _delete_run(integration_context, run_id)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_every_checkpoint_resumes_after_service_reconstruction(
    integration_context: IntegrationContext,
) -> None:
    week_start = date(2099, 2, 16)
    run_id = weekly_dag_run_id(week_start)
    service, _repository = _service(
        integration_context,
        now=_NOW + timedelta(days=42),
    )
    try:
        await service.enqueue(
            week_start=week_start,
            input_fingerprint=sha256(b"weekly-restart-every-node").hexdigest(),
            now=_NOW + timedelta(days=42),
        )
        for ordinal in range(len(WEEKLY_DAG_NODES)):
            reconstructed, _repository = _service(
                integration_context,
                now=_NOW + timedelta(days=42),
            )
            status = await reconstructed.process_once(
                worker_id=f"worker.reconstructed.{ordinal}",
                lease_seconds=30,
            )
            assert status is not None
            assert (
                sum(node.status is WeeklyDagNodeStatus.SUCCEEDED for node in status.nodes)
                == ordinal + 1
            )
            assert all(
                node.attempt_count == 1
                for node in status.nodes
                if node.status is WeeklyDagNodeStatus.SUCCEEDED
            )
        final = await reconstructed.status(run_id)
        assert final.run.status is WeeklyDagRunStatus.READY
    finally:
        await _delete_run(integration_context, run_id)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_cancelled_worker_reconciles_governance_and_releases_claim(
    integration_context: IntegrationContext,
) -> None:
    week_start = date(2099, 2, 23)
    run_id = weekly_dag_run_id(week_start)
    started = asyncio.Event()

    async def blocked_handler(claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        started.set()
        await asyncio.Event().wait()
        return _artifact_result(claim)  # pragma: no cover - cancellation is the assertion.

    service, _repository = _service(
        integration_context,
        handler=blocked_handler,
        now=_NOW + timedelta(days=49),
    )
    try:
        await service.enqueue(
            week_start=week_start,
            input_fingerprint=sha256(b"weekly-cancelled-worker").hexdigest(),
            now=_NOW + timedelta(days=49),
        )
        execution = asyncio.create_task(
            service.process_once(worker_id="worker.cancelled", lease_seconds=30)
        )
        await asyncio.wait_for(started.wait(), timeout=5)
        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await execution

        status = await service.status(run_id)
        assert status.nodes[0].status is WeeklyDagNodeStatus.RETRYABLE_FAILED
        assert status.nodes[0].error_code == WeeklyDagErrorCode.LEASE_LOST.value
        async with integration_context.session_factory() as session:
            running_allocations = tuple(
                await session.scalars(
                    select(ExecutionAgentAllocationModel.agent_id).where(
                        ExecutionAgentAllocationModel.run_id == run_id,
                        ExecutionAgentAllocationModel.status == ExecutionRunStatus.RUNNING.value,
                        ExecutionAgentAllocationModel.parent_agent_id.is_not(None),
                    )
                )
            )
            open_reservations = tuple(
                await session.scalars(
                    select(ExecutionBudgetReservationModel.id).where(
                        ExecutionBudgetReservationModel.run_id == run_id,
                        ExecutionBudgetReservationModel.status == "reserved",
                    )
                )
            )
        assert running_allocations == ()
        assert open_reservations == ()
    finally:
        await _delete_run(integration_context, run_id)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_repository_rejects_cross_node_artifact_and_trace_lineage(
    integration_context: IntegrationContext,
) -> None:
    week_start = date(2099, 3, 2)
    run_id = weekly_dag_run_id(week_start)
    current = _NOW + timedelta(days=56)
    service, repository = _service(integration_context, now=current)
    try:
        await service.enqueue(
            week_start=week_start,
            input_fingerprint=sha256(b"weekly-cross-node-lineage").hexdigest(),
            now=current,
        )
        assert await service.process_once(worker_id="worker.lineage.schedule", lease_seconds=30)
        completed = await service.status(run_id)
        schedule = completed.nodes[0]
        assert schedule.execution_artifact_id is not None
        assert schedule.trace_event_id is not None

        claim = await repository.claim_ready(
            worker_id="worker.lineage.selection",
            now=current,
            lease_seconds=30,
        )
        assert claim is not None
        assert claim.node.definition.key == "select_roles"
        with pytest.raises(WeeklyDagNodeFailure) as rejected:
            await repository.complete(
                claim,
                result=_artifact_result(claim),
                execution_artifact_id=schedule.execution_artifact_id,
                trace_event_id=schedule.trace_event_id,
                now=current,
            )
        assert rejected.value.error_code == WeeklyDagErrorCode.ARTIFACT_CONFLICT.value
        await repository.fail(
            claim,
            error_code=WeeklyDagErrorCode.ARTIFACT_CONFLICT.value,
            retryable=False,
            available_at=current,
            now=current,
            trace_event_id=None,
        )
    finally:
        await _delete_run(integration_context, run_id)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_terminal_branch_waits_for_active_siblings_before_root_cleanup(
    integration_context: IntegrationContext,
) -> None:
    week_start = date(2099, 3, 9)
    run_id = weekly_dag_run_id(week_start)
    current = _NOW + timedelta(days=63)
    official_started = asyncio.Event()
    industry_started = asyncio.Event()
    application_started = asyncio.Event()
    release_failure = asyncio.Event()
    release_siblings = asyncio.Event()

    async def concurrent_branch_handler(claim: WeeklyDagClaim) -> WeeklyDagNodeResult:
        if claim.node.definition.key == "official_anchor:build_article":
            official_started.set()
            await release_failure.wait()
            raise WeeklyDagNodeFailure(
                WeeklyDagErrorCode.PROVIDER_TERMINAL.value,
                retryable=False,
            )
        if claim.node.definition.key == "industry_trend:build_article":
            industry_started.set()
            await release_siblings.wait()
        if claim.node.definition.key == "application_case:build_article":
            application_started.set()
            await release_siblings.wait()
        return _artifact_result(claim)

    service, _repository = _service(
        integration_context,
        handler=concurrent_branch_handler,
        now=current,
    )
    branches: tuple[asyncio.Task[WeeklyDagStatusProjection | None], ...] = ()
    try:
        await service.enqueue(
            week_start=week_start,
            input_fingerprint=sha256(b"weekly-terminal-active-siblings").hexdigest(),
            now=current,
        )
        assert await service.process_once(worker_id="worker.terminal.schedule", lease_seconds=30)
        assert await service.process_once(worker_id="worker.terminal.select", lease_seconds=30)
        branches = tuple(
            asyncio.create_task(
                service.process_once(
                    worker_id=f"worker.terminal.branch.{index}",
                    lease_seconds=30,
                )
            )
            for index in range(3)
        )
        await asyncio.wait_for(
            asyncio.gather(
                official_started.wait(),
                industry_started.wait(),
                application_started.wait(),
            ),
            timeout=5,
        )
        release_failure.set()
        done, pending = await asyncio.wait(
            branches,
            timeout=5,
            return_when=asyncio.FIRST_COMPLETED,
        )
        assert len(done) == 1
        assert len(pending) == 2
        terminal_status = next(iter(done)).result()
        assert terminal_status is not None
        assert terminal_status.run.status is WeeklyDagRunStatus.TERMINAL_FAILED

        async with integration_context.session_factory() as session:
            root = await session.scalar(
                select(ExecutionAgentAllocationModel).where(
                    ExecutionAgentAllocationModel.run_id == run_id,
                    ExecutionAgentAllocationModel.agent_id == "weekly.orchestrator",
                )
            )
            active_children = tuple(
                await session.scalars(
                    select(ExecutionAgentAllocationModel.agent_id).where(
                        ExecutionAgentAllocationModel.run_id == run_id,
                        ExecutionAgentAllocationModel.parent_agent_id == "weekly.orchestrator",
                        ExecutionAgentAllocationModel.status == ExecutionRunStatus.RUNNING.value,
                    )
                )
            )
        assert root is not None
        assert root.status == ExecutionRunStatus.RUNNING.value
        assert len(active_children) == 2

        release_siblings.set()
        await asyncio.gather(*branches)
        async with integration_context.session_factory() as session:
            root = await session.scalar(
                select(ExecutionAgentAllocationModel).where(
                    ExecutionAgentAllocationModel.run_id == run_id,
                    ExecutionAgentAllocationModel.agent_id == "weekly.orchestrator",
                )
            )
            active_children = tuple(
                await session.scalars(
                    select(ExecutionAgentAllocationModel.agent_id).where(
                        ExecutionAgentAllocationModel.run_id == run_id,
                        ExecutionAgentAllocationModel.parent_agent_id == "weekly.orchestrator",
                        ExecutionAgentAllocationModel.status == ExecutionRunStatus.RUNNING.value,
                    )
                )
            )
            open_reservations = tuple(
                await session.scalars(
                    select(ExecutionBudgetReservationModel.id).where(
                        ExecutionBudgetReservationModel.run_id == run_id,
                        ExecutionBudgetReservationModel.status == "reserved",
                    )
                )
            )
        assert root is not None
        assert root.status == ExecutionRunStatus.FAILED.value
        assert active_children == ()
        assert open_reservations == ()
    finally:
        release_failure.set()
        release_siblings.set()
        if branches:
            await asyncio.gather(*branches, return_exceptions=True)
        await _delete_run(integration_context, run_id)
