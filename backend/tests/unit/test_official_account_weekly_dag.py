from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from app.application.ports.official_account_weekly_dag import WeeklyDagNodeResult
from app.application.services.official_account_weekly_dag import (
    StaticWeeklyDagHandlerRegistry,
)
from app.domain.official_account_weekly_dag import (
    WEEKLY_DAG_NODES,
    WEEKLY_DAG_VERSION,
    WeeklyDagArtifact,
    WeeklyDagNodeDefinition,
    WeeklyDagNodeKind,
    WeeklyDagNodeSnapshot,
    WeeklyDagNodeStatus,
    WeeklyDagRunSnapshot,
    WeeklyDagRunStatus,
    WeeklyDagStatusProjection,
    derive_weekly_dag_run_status,
    validate_weekly_dag,
    weekly_dag_graph_fingerprint,
    weekly_dag_node_input_fingerprint,
    weekly_dag_request_fingerprint,
    weekly_dag_run_id,
    weekly_dag_task_id,
)
from app.domain.official_account_weekly_edition import (
    WEEKLY_EDITION_ROLE_ORDER,
    WEEKLY_EDITION_SCHEDULE_VERSION,
    WEEKLY_EDITION_SELECTION_VERSION,
)

_NOW = datetime(2026, 8, 31, 1, tzinfo=UTC)
_INPUT = sha256(b"weekly-dag-unit-input").hexdigest()


def _artifact(ordinal: int) -> WeeklyDagArtifact:
    return WeeklyDagArtifact(
        opaque_ref=f"weekly.test.{ordinal}",
        fingerprint=sha256(f"artifact:{ordinal}".encode()).hexdigest(),
        media_type="application/json",
        byte_size=ordinal + 1,
    )


def _node(
    ordinal: int,
    status: WeeklyDagNodeStatus,
) -> WeeklyDagNodeSnapshot:
    definition = WEEKLY_DAG_NODES[ordinal]
    successful = status is WeeklyDagNodeStatus.SUCCEEDED
    return WeeklyDagNodeSnapshot(
        run_id=weekly_dag_run_id(date(2026, 8, 31)),
        definition=definition,
        status=status,
        input_fingerprint=sha256(f"input:{ordinal}".encode()).hexdigest(),
        attempt_count=1 if status is not WeeklyDagNodeStatus.PENDING else 0,
        max_attempts=3,
        fencing_token=1 if status is not WeeklyDagNodeStatus.PENDING else 0,
        output_artifact=_artifact(ordinal) if successful else None,
        execution_artifact_id=uuid4() if successful else None,
        trace_event_id=uuid4() if successful else None,
        error_code=("provider_terminal" if status is WeeklyDagNodeStatus.TERMINAL_FAILED else None),
        available_at=_NOW,
        started_at=_NOW if status is not WeeklyDagNodeStatus.PENDING else None,
        completed_at=_NOW
        if status
        in {
            WeeklyDagNodeStatus.SUCCEEDED,
            WeeklyDagNodeStatus.RETRYABLE_FAILED,
            WeeklyDagNodeStatus.TERMINAL_FAILED,
        }
        else None,
    )


def _run(status: WeeklyDagRunStatus) -> WeeklyDagRunSnapshot:
    week_start = date(2026, 8, 31)
    return WeeklyDagRunSnapshot(
        run_id=weekly_dag_run_id(week_start),
        task_id=weekly_dag_task_id(week_start),
        week_start=week_start,
        schedule_version=WEEKLY_EDITION_SCHEDULE_VERSION,
        selection_version=WEEKLY_EDITION_SELECTION_VERSION,
        dag_version=WEEKLY_DAG_VERSION,
        graph_fingerprint=weekly_dag_graph_fingerprint(),
        input_fingerprint=_INPUT,
        request_fingerprint=weekly_dag_request_fingerprint(
            week_start=week_start,
            input_fingerprint=_INPUT,
        ),
        status=status,
        aggregate_artifact=None,
        created_at=_NOW,
        updated_at=_NOW,
        completed_at=None,
    )


def test_static_graph_is_acyclic_closed_and_gates_aggregate_on_three_validations() -> None:
    validate_weekly_dag()
    assert len(WEEKLY_DAG_NODES) == 16
    assert tuple(node.ordinal for node in WEEKLY_DAG_NODES) == tuple(range(16))
    assert (
        tuple(
            node.role.value
            for node in WEEKLY_DAG_NODES
            if node.kind is WeeklyDagNodeKind.BUILD_ARTICLE and node.role is not None
        )
        == WEEKLY_EDITION_ROLE_ORDER
    )
    assert WEEKLY_DAG_NODES[-2].key == "aggregate"
    assert WEEKLY_DAG_NODES[-2].dependencies == tuple(
        f"{role}:validate_child" for role in WEEKLY_EDITION_ROLE_ORDER
    )
    assert WEEKLY_DAG_NODES[-1].dependencies == ("aggregate",)
    assert weekly_dag_graph_fingerprint() == (
        "ff3200181f5545d238e7de2c6c616d46f63a0b23222304c7191455946307d23a"
    )


def test_graph_validation_rejects_forward_edge_and_handler_registry_is_closed() -> None:
    invalid = (
        replace(WEEKLY_DAG_NODES[0], dependencies=("finalize",)),
        *WEEKLY_DAG_NODES[1:],
    )
    with pytest.raises(ValueError, match="cycle or forward"):
        validate_weekly_dag(invalid)

    async def handler(_claim: object) -> WeeklyDagNodeResult:
        return WeeklyDagNodeResult(artifact=_artifact(0))

    with pytest.raises(ValueError, match="exactly match"):
        StaticWeeklyDagHandlerRegistry({"schedule": handler})


def test_node_input_fingerprint_binds_dependency_order_and_run_input() -> None:
    definition = WeeklyDagNodeDefinition(
        key="test",
        ordinal=0,
        kind=WeeklyDagNodeKind.AGGREGATE,
        role=None,
        dependencies=("first", "second"),
        capability_name="weekly.aggregate",
    )
    first = sha256(b"first").hexdigest()
    second = sha256(b"second").hexdigest()
    fingerprint = weekly_dag_node_input_fingerprint(
        run_input_fingerprint=_INPUT,
        definition=definition,
        dependency_fingerprints=(first, second),
    )
    assert fingerprint != weekly_dag_node_input_fingerprint(
        run_input_fingerprint=_INPUT,
        definition=definition,
        dependency_fingerprints=(second, first),
    )
    with pytest.raises(ValueError, match="count"):
        weekly_dag_node_input_fingerprint(
            run_input_fingerprint=_INPUT,
            definition=definition,
            dependency_fingerprints=(first,),
        )


def test_run_status_and_projection_are_bounded_metadata_only() -> None:
    pending = tuple(_node(index, WeeklyDagNodeStatus.PENDING) for index in range(16))
    assert derive_weekly_dag_run_status(pending) is WeeklyDagRunStatus.PENDING
    partial = (_node(0, WeeklyDagNodeStatus.SUCCEEDED), *pending[1:])
    assert derive_weekly_dag_run_status(partial) is WeeklyDagRunStatus.PARTIAL
    terminal = (*partial[:-1], _node(15, WeeklyDagNodeStatus.TERMINAL_FAILED))
    assert derive_weekly_dag_run_status(terminal) is WeeklyDagRunStatus.TERMINAL_FAILED
    ready = tuple(_node(index, WeeklyDagNodeStatus.SUCCEEDED) for index in range(16))
    assert derive_weekly_dag_run_status(ready) is WeeklyDagRunStatus.READY

    payload = WeeklyDagStatusProjection(
        run=_run(WeeklyDagRunStatus.PARTIAL),
        nodes=partial,
    ).as_dict()
    serialized = str(payload).lower()
    assert len(payload["nodes"]) == 16  # type: ignore[arg-type]
    for forbidden in (
        "prompt",
        "provider_body",
        "message",
        "private_path",
        "object_key",
        "lease_owner",
        "media_url",
        "article_body",
    ):
        assert forbidden not in serialized
