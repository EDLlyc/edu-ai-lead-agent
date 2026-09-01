"""Code-owned durable DAG contracts for the weekly three-article edition."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid5

from app.domain.official_account_weekly_edition import (
    WEEKLY_EDITION_ROLE_ORDER,
    WEEKLY_EDITION_SCHEDULE_VERSION,
    WEEKLY_EDITION_SELECTION_VERSION,
    WEEKLY_EDITION_TIMEZONE,
    WeeklyArticleRole,
)

WEEKLY_DAG_VERSION: Final = "official-account-weekly-three-article-dag-v1"
WEEKLY_DAG_TASK_PREFIX: Final = "official-account-weekly-dag"
WEEKLY_DAG_MAX_ACTIVE_BRANCHES: Final = 3
WEEKLY_DAG_DEFAULT_MAX_ATTEMPTS: Final = 3
WEEKLY_DAG_RUN_NAMESPACE: Final = UUID("5ea8a13e-ebf2-4ef5-a005-94ffb9f12c1b")
WEEKLY_DAG_ROOT_AGENT_ID: Final = "weekly.orchestrator"

_SAFE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SAFE_ERROR = re.compile(r"[a-z][a-z0-9_.:-]{0,79}")
_SAFE_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9.+-]{0,63}/[a-z0-9][a-z0-9.+-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _validate_ref(value: str, label: str) -> None:
    if _SAFE_REF.fullmatch(value) is None:
        raise ValueError(f"weekly DAG {label} is invalid")


class WeeklyDagNodeKind(StrEnum):
    SCHEDULE = "schedule"
    SELECT_ROLES = "select_roles"
    BUILD_ARTICLE = "build_article"
    PLAN_MEDIA = "plan_media"
    RENDER_HANDOFF = "render_handoff"
    VALIDATE_CHILD = "validate_child"
    AGGREGATE = "aggregate"
    FINALIZE = "finalize"


class WeeklyDagNodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYABLE_FAILED = "retryable_failed"
    TERMINAL_FAILED = "terminal_failed"


class WeeklyDagRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    RETRYABLE_FAILED = "retryable_failed"
    TERMINAL_FAILED = "terminal_failed"
    READY = "ready"


class WeeklyDagErrorCode(StrEnum):
    CAPABILITY_FAILED = "capability_failed"
    CAPABILITY_TIMEOUT = "capability_timeout"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PERMISSION_DENIED = "permission_denied"
    LEASE_LOST = "lease_lost"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    INVALID_CHECKPOINT = "invalid_checkpoint"
    INVALID_DEPENDENCY = "invalid_dependency"
    INVALID_SELECTION = "invalid_selection"
    INVALID_CHILD = "invalid_child"
    PARTIAL_CHILDREN = "partial_children"
    ARTIFACT_CONFLICT = "artifact_conflict"
    PROVIDER_TERMINAL = "provider_terminal"


@dataclass(frozen=True, slots=True)
class WeeklyDagNodeDefinition:
    key: str
    ordinal: int
    kind: WeeklyDagNodeKind
    role: WeeklyArticleRole | None
    dependencies: tuple[str, ...]
    capability_name: str

    def __post_init__(self) -> None:
        _validate_ref(self.key, "node key")
        if self.ordinal < 0:
            raise ValueError("weekly DAG node ordinal must be non-negative")
        if _SAFE_ERROR.fullmatch(self.capability_name) is None:
            raise ValueError("weekly DAG capability name is invalid")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("weekly DAG dependencies must be unique")
        for dependency in self.dependencies:
            _validate_ref(dependency, "dependency")

    @property
    def is_branch_node(self) -> bool:
        return self.role is not None


def _definitions() -> tuple[WeeklyDagNodeDefinition, ...]:
    definitions: list[WeeklyDagNodeDefinition] = [
        WeeklyDagNodeDefinition(
            key="schedule",
            ordinal=0,
            kind=WeeklyDagNodeKind.SCHEDULE,
            role=None,
            dependencies=(),
            capability_name="weekly.schedule",
        ),
        WeeklyDagNodeDefinition(
            key="select_roles",
            ordinal=1,
            kind=WeeklyDagNodeKind.SELECT_ROLES,
            role=None,
            dependencies=("schedule",),
            capability_name="weekly.select_roles",
        ),
    ]
    ordinal = 2
    for role_value in WEEKLY_EDITION_ROLE_ORDER:
        role = WeeklyArticleRole(role_value)
        previous = "select_roles"
        for kind in (
            WeeklyDagNodeKind.BUILD_ARTICLE,
            WeeklyDagNodeKind.PLAN_MEDIA,
            WeeklyDagNodeKind.RENDER_HANDOFF,
            WeeklyDagNodeKind.VALIDATE_CHILD,
        ):
            key = f"{role.value}:{kind.value}"
            definitions.append(
                WeeklyDagNodeDefinition(
                    key=key,
                    ordinal=ordinal,
                    kind=kind,
                    role=role,
                    dependencies=(previous,),
                    capability_name=f"weekly.{kind.value}",
                )
            )
            previous = key
            ordinal += 1
    validation_dependencies = tuple(f"{role}:validate_child" for role in WEEKLY_EDITION_ROLE_ORDER)
    definitions.extend(
        (
            WeeklyDagNodeDefinition(
                key="aggregate",
                ordinal=ordinal,
                kind=WeeklyDagNodeKind.AGGREGATE,
                role=None,
                dependencies=validation_dependencies,
                capability_name="weekly.aggregate",
            ),
            WeeklyDagNodeDefinition(
                key="finalize",
                ordinal=ordinal + 1,
                kind=WeeklyDagNodeKind.FINALIZE,
                role=None,
                dependencies=("aggregate",),
                capability_name="weekly.finalize",
            ),
        )
    )
    return tuple(definitions)


WEEKLY_DAG_NODES: Final = _definitions()
WEEKLY_DAG_NODE_BY_KEY: Final = {node.key: node for node in WEEKLY_DAG_NODES}


def validate_weekly_dag(
    definitions: tuple[WeeklyDagNodeDefinition, ...] = WEEKLY_DAG_NODES,
) -> None:
    keys = tuple(node.key for node in definitions)
    ordinals = tuple(node.ordinal for node in definitions)
    if len(keys) != len(set(keys)) or len(ordinals) != len(set(ordinals)):
        raise ValueError("weekly DAG node keys and ordinals must be unique")
    if ordinals != tuple(range(len(definitions))):
        raise ValueError("weekly DAG ordinals must be contiguous and code-owned")
    by_key = {node.key: node for node in definitions}
    if any(dependency not in by_key for node in definitions for dependency in node.dependencies):
        raise ValueError("weekly DAG contains an unknown dependency")
    if any(
        by_key[dependency].ordinal >= node.ordinal
        for node in definitions
        for dependency in node.dependencies
    ):
        raise ValueError("weekly DAG contains a cycle or forward dependency")
    roles = tuple(
        node.role.value
        for node in definitions
        if node.kind is WeeklyDagNodeKind.BUILD_ARTICLE and node.role is not None
    )
    if roles != WEEKLY_EDITION_ROLE_ORDER:
        raise ValueError("weekly DAG role branches changed")
    if by_key["aggregate"].dependencies != tuple(
        f"{role}:validate_child" for role in WEEKLY_EDITION_ROLE_ORDER
    ):
        raise ValueError("weekly DAG aggregate dependency gate changed")
    for node in definitions:
        is_role_kind = node.kind in {
            WeeklyDagNodeKind.BUILD_ARTICLE,
            WeeklyDagNodeKind.PLAN_MEDIA,
            WeeklyDagNodeKind.RENDER_HANDOFF,
            WeeklyDagNodeKind.VALIDATE_CHILD,
        }
        if is_role_kind != (node.role is not None):
            raise ValueError("weekly DAG role and node-kind shape changed")


validate_weekly_dag()


def weekly_dag_graph_fingerprint() -> str:
    return _fingerprint(
        WEEKLY_DAG_VERSION,
        tuple(
            (
                node.key,
                node.ordinal,
                node.kind.value,
                node.role.value if node.role is not None else None,
                node.dependencies,
                node.capability_name,
            )
            for node in WEEKLY_DAG_NODES
        ),
    )


def weekly_dag_task_id(week_start: date) -> str:
    if week_start.weekday() != 0:
        raise ValueError("weekly DAG week_start must be a Monday")
    return f"{WEEKLY_DAG_TASK_PREFIX}:{week_start.isoformat()}"


def weekly_dag_run_id(week_start: date) -> UUID:
    business_identity = ":".join(
        (
            week_start.isoformat(),
            WEEKLY_EDITION_SCHEDULE_VERSION,
            WEEKLY_EDITION_SELECTION_VERSION,
            WEEKLY_DAG_VERSION,
        )
    )
    return uuid5(WEEKLY_DAG_RUN_NAMESPACE, business_identity)


def weekly_dag_attempt_agent_id(node_key: str, attempt_no: int) -> str:
    _validate_ref(node_key, "node key")
    if attempt_no <= 0:
        raise ValueError("weekly DAG attempt number must be positive")
    return f"weekly.{node_key}.a{attempt_no}"


def weekly_dag_request_fingerprint(*, week_start: date, input_fingerprint: str) -> str:
    _validate_sha256(input_fingerprint, "input fingerprint")
    return _fingerprint(
        "official-account-weekly-dag-request-v1",
        week_start.isoformat(),
        WEEKLY_EDITION_SCHEDULE_VERSION,
        WEEKLY_EDITION_SELECTION_VERSION,
        WEEKLY_DAG_VERSION,
        weekly_dag_graph_fingerprint(),
        input_fingerprint,
    )


def weekly_dag_node_input_fingerprint(
    *,
    run_input_fingerprint: str,
    definition: WeeklyDagNodeDefinition,
    dependency_fingerprints: tuple[str, ...],
) -> str:
    _validate_sha256(run_input_fingerprint, "run input fingerprint")
    if len(dependency_fingerprints) != len(definition.dependencies):
        raise ValueError("weekly DAG dependency fingerprint count changed")
    for fingerprint in dependency_fingerprints:
        _validate_sha256(fingerprint, "dependency fingerprint")
    return _fingerprint(
        "official-account-weekly-dag-node-input-v1",
        WEEKLY_DAG_VERSION,
        weekly_dag_graph_fingerprint(),
        run_input_fingerprint,
        definition.key,
        tuple(zip(definition.dependencies, dependency_fingerprints, strict=True)),
    )


@dataclass(frozen=True, slots=True)
class WeeklyDagArtifact:
    opaque_ref: str
    fingerprint: str
    media_type: str
    byte_size: int

    def __post_init__(self) -> None:
        _validate_ref(self.opaque_ref, "artifact reference")
        _validate_sha256(self.fingerprint, "artifact fingerprint")
        if _SAFE_MEDIA_TYPE.fullmatch(self.media_type) is None:
            raise ValueError("weekly DAG artifact media type is invalid")
        if self.byte_size < 0:
            raise ValueError("weekly DAG artifact byte size must be non-negative")


@dataclass(frozen=True, slots=True)
class WeeklyDagRunSnapshot:
    run_id: UUID
    task_id: str
    week_start: date
    schedule_version: str
    selection_version: str
    dag_version: str
    graph_fingerprint: str
    input_fingerprint: str
    request_fingerprint: str
    status: WeeklyDagRunStatus
    aggregate_artifact: WeeklyDagArtifact | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    def __post_init__(self) -> None:
        _validate_ref(self.task_id, "task ID")
        if self.week_start.weekday() != 0:
            raise ValueError("weekly DAG run week_start must be a Monday")
        if (
            self.schedule_version != WEEKLY_EDITION_SCHEDULE_VERSION
            or self.selection_version != WEEKLY_EDITION_SELECTION_VERSION
            or self.dag_version != WEEKLY_DAG_VERSION
            or self.graph_fingerprint != weekly_dag_graph_fingerprint()
        ):
            raise ValueError("weekly DAG run version identity changed")
        _validate_sha256(self.input_fingerprint, "input fingerprint")
        _validate_sha256(self.request_fingerprint, "request fingerprint")
        _validate_aware(self.created_at, "created_at")
        _validate_aware(self.updated_at, "updated_at")
        if self.completed_at is not None:
            _validate_aware(self.completed_at, "completed_at")


@dataclass(frozen=True, slots=True)
class WeeklyDagNodeSnapshot:
    run_id: UUID
    definition: WeeklyDagNodeDefinition
    status: WeeklyDagNodeStatus
    input_fingerprint: str | None
    attempt_count: int
    max_attempts: int
    fencing_token: int
    output_artifact: WeeklyDagArtifact | None
    execution_artifact_id: UUID | None
    trace_event_id: UUID | None
    error_code: str | None
    available_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    def __post_init__(self) -> None:
        if self.input_fingerprint is not None:
            _validate_sha256(self.input_fingerprint, "node input fingerprint")
        if not (0 <= self.attempt_count <= self.max_attempts) or self.max_attempts <= 0:
            raise ValueError("weekly DAG attempt count is invalid")
        if self.fencing_token < 0:
            raise ValueError("weekly DAG fencing token must be non-negative")
        if self.error_code is not None and _SAFE_ERROR.fullmatch(self.error_code) is None:
            raise ValueError("weekly DAG error code is invalid")
        _validate_aware(self.available_at, "available_at")
        if self.started_at is not None:
            _validate_aware(self.started_at, "started_at")
        if self.completed_at is not None:
            _validate_aware(self.completed_at, "completed_at")
        if self.status is WeeklyDagNodeStatus.SUCCEEDED and (
            self.output_artifact is None
            or self.execution_artifact_id is None
            or self.trace_event_id is None
        ):
            raise ValueError("successful weekly DAG checkpoint is incomplete")


@dataclass(frozen=True, slots=True)
class WeeklyDagClaim:
    run: WeeklyDagRunSnapshot
    node: WeeklyDagNodeSnapshot
    dependencies: tuple[WeeklyDagNodeSnapshot, ...]
    worker_id: str
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        _validate_ref(self.worker_id, "worker ID")
        _validate_aware(self.lease_expires_at, "lease expiry")
        if self.node.status is not WeeklyDagNodeStatus.RUNNING:
            raise ValueError("weekly DAG claim must own a running node")
        if (
            tuple(item.definition.key for item in self.dependencies)
            != self.node.definition.dependencies
        ):
            raise ValueError("weekly DAG claim dependency order changed")
        if any(item.status is not WeeklyDagNodeStatus.SUCCEEDED for item in self.dependencies):
            raise ValueError("weekly DAG claim dependencies are incomplete")


@dataclass(frozen=True, slots=True)
class WeeklyDagStatusProjection:
    run: WeeklyDagRunSnapshot
    nodes: tuple[WeeklyDagNodeSnapshot, ...]

    def __post_init__(self) -> None:
        if tuple(node.definition.key for node in self.nodes) != tuple(
            definition.key for definition in WEEKLY_DAG_NODES
        ):
            raise ValueError("weekly DAG status node order changed")
        if any(node.run_id != self.run.run_id for node in self.nodes):
            raise ValueError("weekly DAG status contains a cross-run node")

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": str(self.run.run_id),
            "task_id": self.run.task_id,
            "week_start": self.run.week_start.isoformat(),
            "timezone": WEEKLY_EDITION_TIMEZONE,
            "schedule_version": self.run.schedule_version,
            "selection_version": self.run.selection_version,
            "dag_version": self.run.dag_version,
            "graph_fingerprint": self.run.graph_fingerprint,
            "status": self.run.status.value,
            "aggregate_artifact_ready": self.run.aggregate_artifact is not None,
            "nodes": [
                {
                    "node_key": node.definition.key,
                    "kind": node.definition.kind.value,
                    "role": node.definition.role.value if node.definition.role else None,
                    "status": node.status.value,
                    "attempt_count": node.attempt_count,
                    "max_attempts": node.max_attempts,
                    "error_code": node.error_code,
                    "artifact_ready": node.output_artifact is not None,
                    "available_at": node.available_at.isoformat(),
                    "started_at": node.started_at.isoformat() if node.started_at else None,
                    "completed_at": node.completed_at.isoformat() if node.completed_at else None,
                }
                for node in self.nodes
            ],
        }


def derive_weekly_dag_run_status(
    nodes: tuple[WeeklyDagNodeSnapshot, ...],
) -> WeeklyDagRunStatus:
    by_key = {node.definition.key: node for node in nodes}
    if by_key.get("finalize") is not None and (
        by_key["finalize"].status is WeeklyDagNodeStatus.SUCCEEDED
    ):
        return WeeklyDagRunStatus.READY
    if any(node.status is WeeklyDagNodeStatus.TERMINAL_FAILED for node in nodes):
        return WeeklyDagRunStatus.TERMINAL_FAILED
    if any(node.status is WeeklyDagNodeStatus.RETRYABLE_FAILED for node in nodes):
        return WeeklyDagRunStatus.RETRYABLE_FAILED
    if any(node.status is WeeklyDagNodeStatus.RUNNING for node in nodes):
        return WeeklyDagRunStatus.RUNNING
    if any(node.status is WeeklyDagNodeStatus.SUCCEEDED for node in nodes):
        return WeeklyDagRunStatus.PARTIAL
    return WeeklyDagRunStatus.PENDING


def _fingerprint(*parts: object) -> str:
    body = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()


def _validate_sha256(value: str, label: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"weekly DAG {label} must be lowercase SHA-256")


def _validate_aware(value: datetime, label: str) -> None:
    if value.utcoffset() is None:
        raise ValueError(f"weekly DAG {label} must be timezone-aware")


def utc_now() -> datetime:
    return datetime.now(UTC)
