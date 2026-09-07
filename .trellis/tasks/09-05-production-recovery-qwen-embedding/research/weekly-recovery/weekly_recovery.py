"""One-shot September 7 recovery; the original failed DAG remains immutable."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from app.application.services.official_account_local import run_request_fingerprint
from app.core.config import get_settings
from app.core.errors import ConflictError
from app.domain.official_account_weekly_dag import WeeklyDagArtifact
from app.domain.official_account_weekly_edition import WeeklyArticleRole
from app.infrastructure.db import models
from app.infrastructure.db.official_account_local import (
    PostgresOfficialAccountRepository,
    material_package_source_snapshot,
)
from app.infrastructure.db.official_account_weekly_production import (
    PostgresWeeklyProductionInputPlanner,
)
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.official_account_media import OfficialAccountLocalMediaResolver
from app.infrastructure.official_account_runtime import (
    official_account_identity_from_settings,
)
from app.infrastructure.official_account_weekly_production import (
    LocalWeeklyProductionArtifactOwner,
)
from app.infrastructure.storage.minio_image_store import MinioImageStore
from app.infrastructure.storage.minio_snapshot_store import MinioSnapshotStore
from app.infrastructure.wechat_official_account.prepared_artifacts import (
    PreparedWeeklyDraftArtifactOwner,
)
from pydantic import ValidationError
from sqlalchemy import select, text

POLICY = "weekly-recovery-20260907-source-preflight-v1"
RUN = UUID("0ae1c882-4254-561f-bdac-17d254c0c166")
INPUT = "55fbb14c0f3acd4b73052f74ccd20d5c5dbca748abbc8a2280bee15b8898a0a3"
WEEK = date(2026, 9, 7)
CUTOFF = datetime.fromisoformat("2026-09-07T01:00:00.095359+00:00")
FAILED = UUID("b290e00b-1e00-43a3-a69f-8f3bdb05137f")
REPLACEMENT = UUID("198969a7-056d-482b-81f4-8219cbd2106b")
EVENT = UUID("cc95b8d8-6f8b-5a35-9ff8-bfd7ede2a49f")
EVENT_VERSION = UUID("62a95e9a-31e1-5058-9199-45f2c598b7f0")
SIBLINGS = (
    (
        UUID("5ca4d0ba-5234-4c96-9bfd-f453617d50a7"),
        UUID("85f62fb9-0e96-4a9e-95c0-48a99043fdd3"),
    ),
    (
        UUID("d6c1825a-c022-4db7-bc3c-40debfa8ce2d"),
        UUID("24ad4ddc-7c1e-46e3-a787-acff86a1f102"),
    ),
)
MAX_ROWS = 5000
MAX_AUDIT_BYTES = 65536


class RecoveryError(Exception):
    """Only operator-owned fixed codes may cross the CLI boundary."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RecoveryError(code)


def encoded(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def digest(value: object) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def identity_payload(identity: Any) -> dict[str, Any]:
    payload = asdict(identity)
    if payload.get("context_media_plan_version") is None:
        payload.pop("context_media_plan_version", None)
    return payload


def physical_directory(path: str | Path, *, allow_missing_leaf: bool = False) -> Path:
    value = Path(path)
    require(
        value.is_absolute()
        and value != Path(value.anchor)
        and not value.is_symlink()
        and value.resolve(strict=False) == value,
        "artifact_root_invalid",
    )
    if not value.exists() and allow_missing_leaf:
        require(value.parent.is_dir(), "artifact_root_parent_missing")
    else:
        require(value.is_dir(), "artifact_root_invalid")
    return value


def seal(observation: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "policy": POLICY,
        "original_run_id": str(RUN),
        "week_start": WEEK.isoformat(),
        "observation": observation,
    }
    return {**payload, "plan_sha256": digest(payload)}


def verify_plan(plan: dict[str, Any], expected_sha: str) -> None:
    require(
        set(plan)
        == {"policy", "original_run_id", "week_start", "observation", "plan_sha256"},
        "plan_shape_invalid",
    )
    payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    require(
        plan["policy"] == POLICY
        and plan["original_run_id"] == str(RUN)
        and plan["week_start"] == WEEK.isoformat(),
        "plan_incident_changed",
    )
    require(plan["plan_sha256"] == expected_sha == digest(payload), "plan_hash_changed")


class FullPreflightPlanner(PostgresWeeklyProductionInputPlanner):
    """Task-local compatibility adapter for the unchanged 5c runtime; no monkeypatch."""

    async def _load_material_rows(self, session: Any, *, cutoff: datetime) -> Any:
        rows = await super()._load_material_rows(session, cutoff=cutoff)
        compatible = []
        for row in rows:
            try:
                material_package_source_snapshot(row[0], row[3])
            except (ConflictError, ValidationError):
                continue
            compatible.append(row)
        return tuple(compatible)


class Audit:
    """An exclusive durable intent is also the cross-process single-incident lock."""

    def __init__(self, root: Path, plan: dict[str, Any]) -> None:
        require(root.is_dir() and not root.is_symlink(), "audit_root_invalid")
        self.path = root / f"{POLICY}.jsonl"
        try:
            self.fd = os.open(
                self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            raise RecoveryError("recovery_intent_already_exists") from None
        self.sequence = 0
        self.previous = "0" * 64
        self.size = 0
        self.append(
            "intent",
            {
                "plan": plan,
                "original_run_id": str(RUN),
                "original_dag_status": "terminal_failed",
            },
        )
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def append(self, phase: str, data: dict[str, Any]) -> None:
        payload = {
            "sequence": self.sequence,
            "previous_sha256": self.previous,
            "at": datetime.now(UTC).isoformat(),
            "phase": phase,
            **data,
        }
        record_sha = digest(payload)
        body = encoded({**payload, "record_sha256": record_sha}) + b"\n"
        require(self.size + len(body) <= MAX_AUDIT_BYTES, "audit_limit_exceeded")
        offset = 0
        while offset < len(body):
            offset += os.write(self.fd, body[offset:])
        os.fsync(self.fd)
        self.size += len(body)
        self.sequence += 1
        self.previous = record_sha

    def close(self) -> None:
        os.close(self.fd)


class Runtime:
    def __init__(self, settings: Any, factory: Any) -> None:
        require(settings.app_env == "production", "production_runtime_required")
        require(
            settings.official_account_weekly_production_enabled
            and settings.official_account_weekly_worker_enabled
            and settings.official_account_local_enabled
            and settings.official_account_local_worker_enabled
            and settings.ai_provider_mode == "zhipu",
            "runtime_flags_changed",
        )
        self.settings = settings
        self.factory = factory
        self.identity = official_account_identity_from_settings(
            settings, provider="zhipu", model=settings.ai_chat_model
        )
        self.root = physical_directory(settings.official_account_weekly_artifact_root)
        self.inbox = physical_directory(
            settings.wechat_mp_draft_weekly_inbox_root, allow_missing_leaf=True
        )
        self.checkpoints = LocalWeeklyProductionArtifactOwner(self.root)
        self.repository = PostgresOfficialAccountRepository(factory)

    @asynccontextmanager
    async def readonly(self) -> Any:
        async with self.factory() as session:
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            await session.execute(text("SET LOCAL statement_timeout = '10s'"))
            try:
                yield session
            finally:
                # The planner consumes fully loaded rows after its session exits. Rollback
                # expires attached ORM state even with expire_on_commit=False; detach first.
                session.expunge_all()
                await session.rollback()

    async def _rows(
        self, session: Any, table: Any, column: str, ids: tuple[UUID, ...]
    ) -> list[Any]:
        # Table and column names come only from code-owned SQLAlchemy metadata.
        rows = list(
            (
                await session.execute(
                    select(table).where(table.c[column].in_(ids)).limit(MAX_ROWS + 1)
                )
            ).mappings()
        )
        require(len(rows) <= MAX_ROWS, "snapshot_row_limit")
        safe = json.loads(json.dumps([dict(row) for row in rows], default=str))
        return sorted(safe, key=encoded)

    async def observe(
        self, extra_run: UUID | None = None, *, permit_handoff: bool = False
    ) -> dict[str, Any]:
        physical_directory(self.root)
        physical_directory(self.inbox, allow_missing_leaf=True)
        original = self.checkpoints.get_json_by_fingerprint(INPUT)
        require(
            original.get("week_start") == WEEK.isoformat()
            and original.get("cutoff") == CUTOFF.isoformat(),
            "original_input_changed",
        )
        original_items = original.get("items")
        require(
            isinstance(original_items, list) and len(original_items) == 3,
            "original_roles_changed",
        )
        original_items = cast(list[dict[str, Any]], original_items)
        require(
            all(isinstance(item, dict) for item in original_items),
            "original_roles_changed",
        )
        expected_packages = [str(pair[0]) for pair in SIBLINGS] + [str(FAILED)]
        require(
            [item.get("material_package_id") for item in original_items]
            == expected_packages,
            "original_packages_changed",
        )
        planned = await FullPreflightPlanner(cast(Any, self.readonly)).plan(
            week_start=WEEK, cutoff=CUTOFF
        )
        require(
            [item.material_package_id for item in planned.items]
            == [pair[0] for pair in SIBLINGS] + [REPLACEMENT],
            "replacement_selection_changed",
        )
        require(
            planned.items[2].event_id == EVENT
            and planned.items[2].event_version_id == EVENT_VERSION,
            "replacement_event_changed",
        )
        for index in range(2):
            require(
                planned.items[index].as_dict() == original_items[index],
                "successful_role_selection_changed",
            )
        bindings = []
        protected: dict[str, Any] = {}
        children = []
        async with self.readonly() as session:
            run = await session.get(models.OfficialAccountWeeklyDagRunModel, RUN)
            root = await session.get(models.ExecutionGovernedRunModel, RUN)
            require(
                run is not None
                and run.input_fingerprint == INPUT
                and run.week_start == WEEK
                and run.status == "terminal_failed"
                and run.aggregate_artifact_ref is None,
                "original_run_changed",
            )
            require(
                root is not None
                and root.status == "failed"
                and root.completed_at is not None,
                "original_root_changed",
            )
            nodes = list(
                await session.scalars(
                    select(models.OfficialAccountWeeklyDagNodeModel).where(
                        models.OfficialAccountWeeklyDagNodeModel.run_id == RUN
                    )
                )
            )
            by_key = {node.node_key: node for node in nodes}
            require(
                len(nodes) == 16
                and all(
                    node.status != "running"
                    and node.lease_owner is None
                    and node.lease_expires_at is None
                    for node in nodes
                ),
                "original_nodes_active",
            )
            failed = by_key.get("application_case:build_article")
            require(
                failed is not None
                and failed.status == "terminal_failed"
                and failed.attempt_count == failed.max_attempts == 3,
                "original_failure_changed",
            )
            for node in nodes:
                if node.output_media_type == "application/json":
                    self.checkpoints.get_json_by_fingerprint(
                        node.output_artifact_fingerprint
                    )
            for role, (_package, article_id) in zip(
                tuple(WeeklyArticleRole)[:2], SIBLINGS, strict=True
            ):
                for suffix in (
                    "build_article",
                    "plan_media",
                    "render_handoff",
                    "validate_child",
                ):
                    require(
                        by_key[f"{role.value}:{suffix}"].status == "succeeded",
                        "successful_branch_changed",
                    )
                built = self.checkpoints.get_json_by_fingerprint(
                    by_key[f"{role.value}:build_article"].output_artifact_fingerprint
                )
                require(
                    built.get("official_account_run_id") == str(article_id),
                    "successful_article_binding_changed",
                )
                child_node = by_key[f"{role.value}:render_handoff"]
                self.prepared_owner().validate_child(
                    WeeklyDagArtifact(
                        opaque_ref=child_node.output_artifact_ref,
                        fingerprint=child_node.output_artifact_fingerprint,
                        media_type=child_node.output_media_type,
                        byte_size=child_node.output_byte_size,
                    ),
                    role=role,
                )
                children.append(child_node.output_artifact_fingerprint)
            for table in models.Base.metadata.sorted_tables:
                if table.name in {
                    "official_account_weekly_dag_runs",
                    "execution_governed_runs",
                }:
                    rows = await self._rows(session, table, "id", (RUN,))
                elif (
                    table.name.startswith("official_account_weekly_dag_")
                    or table.name.startswith("execution_")
                ) and "run_id" in table.c:
                    rows = await self._rows(session, table, "run_id", (RUN,))
                    if table.name == "execution_agent_allocations":
                        require(
                            all(row["status"] != "running" for row in rows),
                            "original_allocation_active",
                        )
                    if table.name == "execution_budget_reservations":
                        require(
                            all(row["status"] != "reserved" for row in rows),
                            "original_reservation_active",
                        )
                elif table.name == "official_account_article_runs":
                    rows = await self._rows(
                        session, table, "id", tuple(pair[1] for pair in SIBLINGS)
                    )
                elif table.name.startswith("official_account_") and "run_id" in table.c:
                    rows = await self._rows(
                        session, table, "run_id", tuple(pair[1] for pair in SIBLINGS)
                    )
                else:
                    continue
                protected[table.name] = {"count": len(rows), "sha256": digest(rows)}
            article_rows = list(
                await session.scalars(
                    select(models.OfficialAccountArticleRunModel).limit(MAX_ROWS + 1)
                )
            )
            expected_articles = {pair[1] for pair in SIBLINGS} | (
                {extra_run} if extra_run is not None else set()
            )
            require(
                {row.id for row in article_rows} == expected_articles,
                "article_population_changed",
            )
            for package_id, article_id in SIBLINGS:
                sibling = next(row for row in article_rows if row.id == article_id)
                require(
                    sibling.material_package_id == package_id
                    and sibling.status == "ready"
                    and sibling.generation_mode == "live"
                    and digest(sibling.version_bundle)
                    == digest(identity_payload(self.identity)),
                    "successful_article_changed",
                )
            for item in planned.items:
                package = await session.get(
                    models.MaterialPackageModel, item.material_package_id
                )
                require(package is not None, "selected_material_missing")
                image = await session.get(
                    models.ImageArtifactModel, package.image_artifact_id
                )
                require(image is not None, "selected_image_missing")
                source = material_package_source_snapshot(package, image)
                request = run_request_fingerprint(
                    source_fingerprint=source.source_fingerprint,
                    generation_mode="live",
                    identity=self.identity,
                )
                bindings.append(
                    {
                        "role": item.role.value,
                        "material_package_id": str(item.material_package_id),
                        "event_id": str(item.event_id),
                        "event_version_id": str(item.event_version_id),
                        "source_fingerprint": source.source_fingerprint,
                        "article_request_fingerprint": request,
                        "selection_item_sha256": digest(item.as_dict()),
                    }
                )
            if extra_run is not None:
                extra = next(row for row in article_rows if row.id == extra_run)
                require(
                    extra.material_package_id == REPLACEMENT
                    and extra.request_fingerprint
                    == bindings[2]["article_request_fingerprint"],
                    "replacement_article_changed",
                )
            for index, (_package_id, article_id) in enumerate(SIBLINGS):
                sibling = next(row for row in article_rows if row.id == article_id)
                require(
                    sibling.source_fingerprint == bindings[index]["source_fingerprint"]
                    and sibling.request_fingerprint
                    == bindings[index]["article_request_fingerprint"],
                    "successful_article_source_changed",
                )
            if not permit_handoff:
                for draft_model in (
                    models.WeChatOfficialAccountDraftJobModel,
                    models.WeChatOfficialAccountDraftItemModel,
                    models.WeChatOfficialAccountDraftAttemptModel,
                ):
                    require(
                        await session.scalar(select(draft_model).limit(1)) is None,
                        "draft_rows_already_exist",
                    )
        if not permit_handoff:
            require(
                not self.inbox.exists()
                or not any(
                    path.name.startswith("official-account-")
                    for path in self.inbox.iterdir()
                ),
                "weekly_inbox_already_staged",
            )
        return {
            "input_fingerprint": INPUT,
            "cutoff": CUTOFF.isoformat(),
            "planned_input_fingerprint": planned.fingerprint,
            "article_identity_sha256": digest(identity_payload(self.identity)),
            "artifact_roots_sha256": digest([str(self.root), str(self.inbox)]),
            "bindings": bindings,
            "sibling_article_ids": [str(pair[1]) for pair in SIBLINGS],
            "sibling_child_fingerprints": children,
            "protected": protected,
        }

    def prepared_owner(self) -> PreparedWeeklyDraftArtifactOwner:
        return PreparedWeeklyDraftArtifactOwner(
            session_factory=self.factory,
            resolver=OfficialAccountLocalMediaResolver(
                image_asset_manifest=self.settings.image_asset_manifest,
                image_store=MinioImageStore(self.settings),
                snapshot_store=MinioSnapshotStore(self.settings),
            ),
            work_root=self.root / "prepared",
            inbox_root=self.inbox,
            max_image_bytes=self.settings.wechat_mp_max_image_bytes,
        )

    async def enqueue(self, binding: dict[str, Any]) -> Any:
        # Keep the sealed source stable until the ordinary repository commits its enqueue.
        # FOR SHARE blocks UPDATE/DELETE while permitting the INSERT's FK KEY SHARE lock.
        async with self.factory() as session:
            await session.execute(text("SET LOCAL statement_timeout = '10s'"))
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            try:
                package = await session.scalar(
                    select(models.MaterialPackageModel)
                    .where(models.MaterialPackageModel.id == REPLACEMENT)
                    .with_for_update(read=True)
                )
                require(package is not None, "selected_material_missing")
                image = await session.scalar(
                    select(models.ImageArtifactModel)
                    .where(models.ImageArtifactModel.id == package.image_artifact_id)
                    .with_for_update(read=True)
                )
                require(image is not None, "selected_image_missing")
                source = material_package_source_snapshot(package, image)
                request = run_request_fingerprint(
                    source_fingerprint=source.source_fingerprint,
                    generation_mode="live",
                    identity=self.identity,
                )
                require(
                    binding["material_package_id"] == str(REPLACEMENT)
                    and source.source_fingerprint == binding["source_fingerprint"]
                    and request == binding["article_request_fingerprint"],
                    "enqueue_source_changed",
                )
                return await asyncio.wait_for(
                    self.repository.enqueue_material_package(
                        material_package_id=REPLACEMENT, identity=self.identity
                    ),
                    timeout=20,
                )
            finally:
                await session.rollback()

    async def wait_ready(self, run_id: UUID) -> None:
        deadline = asyncio.get_running_loop().time() + 720
        while True:
            run = await self.repository.get_run(run_id)
            if run.status == "ready":
                return
            require(
                run.status not in {"review_required", "failed", "result_unknown"},
                "replacement_article_terminal",
            )
            require(
                asyncio.get_running_loop().time() < deadline,
                "replacement_article_wait_timeout",
            )
            await asyncio.sleep(2)


async def execute(
    runtime: Any, plan: dict[str, Any], expected_sha: str
) -> dict[str, Any]:
    verify_plan(plan, expected_sha)
    require(
        not (runtime.root / f"{POLICY}.jsonl").exists(),
        "recovery_intent_already_exists",
    )
    require(seal(await runtime.observe()) == plan, "plan_state_drift")
    audit = Audit(runtime.root, plan)
    phase = "before_enqueue"
    try:
        # Close the read-to-intent gap before the only article enqueue.
        require(seal(await runtime.observe()) == plan, "plan_state_drift")
        audit.append(
            "enqueue_intent",
            {
                "material_package_id": str(REPLACEMENT),
                "article_request_fingerprint": plan["observation"]["bindings"][2][
                    "article_request_fingerprint"
                ],
            },
        )
        phase = "enqueue_started"
        article, created = await runtime.enqueue(plan["observation"]["bindings"][2])
        require(created, "replacement_enqueue_not_created")
        run_id = UUID(str(article.id))
        audit.append(
            "article_enqueued", {"article_run_id": str(run_id), "created": True}
        )
        phase = "article_enqueued"
        await runtime.wait_ready(run_id)
        require(
            await runtime.observe(run_id) == plan["observation"],
            "protected_state_drift",
        )
        audit.append("article_ready", {"article_run_id": str(run_id)})
        owner = runtime.prepared_owner()
        children = []
        prepared = []
        for index, (role, article_id) in enumerate(
            zip(
                WeeklyArticleRole,
                (*[pair[1] for pair in SIBLINGS], run_id),
                strict=True,
            )
        ):
            artifact = await owner.build_child(run_id=article_id, role=role)
            child = owner.validate_child(artifact, role=role)
            if index < 2:
                require(
                    artifact.fingerprint
                    == plan["observation"]["sibling_child_fingerprints"][index],
                    "successful_child_changed",
                )
            children.append(artifact)
            prepared.append(child)
            audit.append(
                "child_validated",
                {
                    "role": role.value,
                    "article_run_id": str(article_id),
                    "child_fingerprint": artifact.fingerprint,
                },
            )
        require(
            len({child.article_fingerprint for child in prepared})
            == len({child.content_fingerprint for child in prepared})
            == len({child.fingerprint for child in children})
            == 3,
            "duplicate_prepared_children",
        )
        require(
            await runtime.observe(run_id) == plan["observation"],
            "preaggregate_state_drift",
        )
        audit.append(
            "aggregate_intent",
            {
                "week_start": WEEK.isoformat(),
                "child_fingerprints": [child.fingerprint for child in children],
            },
        )
        phase = "aggregate_started"
        aggregate = owner.aggregate(week_start=WEEK, children=tuple(children))
        batch = owner.validate_batch(aggregate)
        require(
            await runtime.observe(run_id, permit_handoff=True) == plan["observation"],
            "postaggregate_protected_state_drift",
        )
        result = {
            "original_run_id": str(RUN),
            "original_dag_status": "terminal_failed",
            "replacement_article_run_id": str(run_id),
            "batch_fingerprint": batch.batch_fingerprint,
            "aggregate_fingerprint": batch.aggregate_fingerprint,
            "recovery_status": "inbox_ready",
            "draft_delivery_status": "not_observed",
            "published": False,
        }
        audit.append("result", result)
        return result
    except BaseException as error:
        code = str(error) if isinstance(error, RecoveryError) else "operator_failed"
        audit.append(
            "failure", {"phase_reached": phase, "code": code, "retry_allowed": False}
        )
        raise RecoveryError(code) from None
    finally:
        audit.close()


def load_plan(path: Path) -> dict[str, Any]:
    require(
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_size <= MAX_AUDIT_BYTES,
        "plan_file_invalid",
    )

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, "plan_duplicate_key")
            result[key] = value
        return result

    value = json.loads(path.read_bytes(), object_pairs_hook=unique)
    require(isinstance(value, dict), "plan_shape_invalid")
    return cast(dict[str, Any], value)


async def cli(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        runtime = Runtime(settings, create_session_factory(engine))
        if args.command == "plan":
            return seal(await runtime.observe())
        return await execute(runtime, load_plan(args.plan_file), args.plan_sha256)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan")
    run = commands.add_parser("execute")
    run.add_argument("--plan-file", type=Path, required=True)
    run.add_argument("--plan-sha256", required=True)
    try:
        result = asyncio.run(cli(parser.parse_args()))
    except Exception as error:
        result = {
            "status": "failed",
            "code": str(error)
            if isinstance(error, RecoveryError)
            else "operator_failed",
        }
        print(json.dumps(result, sort_keys=True))
        sys.exit(1)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
