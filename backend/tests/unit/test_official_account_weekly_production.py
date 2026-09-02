from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from app.application.ports.official_account_weekly_production import (
    WeeklyProductionInput,
    WeeklyProductionInputItem,
)
from app.application.services.official_account_weekly_production import (
    ProductionWeeklyDagHandlers,
)
from app.core.config import Settings
from app.domain.official_account_weekly_dag import (
    WEEKLY_DAG_NODES,
    WEEKLY_DAG_VERSION,
    WeeklyDagClaim,
    WeeklyDagNodeSnapshot,
    WeeklyDagNodeStatus,
    WeeklyDagRunSnapshot,
    WeeklyDagRunStatus,
    weekly_dag_graph_fingerprint,
    weekly_dag_request_fingerprint,
    weekly_dag_run_id,
    weekly_dag_task_id,
)
from app.domain.official_account_weekly_edition import (
    WEEKLY_EDITION_SCHEDULE_VERSION,
    WEEKLY_EDITION_SELECTION_VERSION,
    WeeklyArticleRole,
    WeeklyArticleSelection,
    WeeklyEditionSchedule,
    WeeklyEditionSelection,
    WeeklySelectionReason,
)
from app.infrastructure.official_account_runtime import official_account_identity_from_settings
from app.infrastructure.official_account_weekly_dag_governance import (
    weekly_dag_capability_registry,
    weekly_dag_node_limits,
)
from app.infrastructure.official_account_weekly_production import (
    LocalWeeklyProductionArtifactOwner,
)
from app.infrastructure.wechat_official_account.artifacts import (
    LocalWeChatDraftArtifactStore,
)
from app.infrastructure.wechat_official_account.prepared_artifacts import (
    PREPARED_DRAFT_BATCH_VERSION,
    PREPARED_DRAFT_CHILD_VERSION,
    load_prepared_weekly_draft_batch,
)
from PIL import Image
from pydantic import SecretStr, ValidationError


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _selection() -> WeeklyEditionSelection:
    schedule = WeeklyEditionSchedule()
    selected: list[WeeklyArticleSelection] = []
    for ordinal, role in enumerate(WeeklyArticleRole, start=1):
        is_official = role is WeeklyArticleRole.OFFICIAL_ANCHOR
        selected.append(
            WeeklyArticleSelection(
                role=role,
                event_id=UUID(int=ordinal),
                event_version_id=UUID(int=ordinal + 10),
                event_time=datetime(2026, 9, ordinal, tzinfo=UTC),
                source_metadata_fingerprint=_sha(f"source:{ordinal}"),
                organization_type="government" if is_official else "authoritative_media",
                official_authority=("stored_government_organization_type" if is_official else None),
                selection_reason=(
                    WeeklySelectionReason.OFFICIAL_CURRENT_WINDOW
                    if is_official
                    else WeeklySelectionReason.ROLE_AFFINITY
                ),
                affinity_reasons=() if is_official else (f"role-fit-{ordinal}",),
                governed_total=0.9 - ordinal / 100,
                governed_score_version="scoring-v1",
            )
        )
    return WeeklyEditionSelection(
        week_start=date(2026, 8, 31),
        timezone=schedule.timezone,
        policy_version=WEEKLY_EDITION_SELECTION_VERSION,
        schedule_fingerprint=schedule.fingerprint,
        selected=(selected[0], selected[1], selected[2]),
    )


def _production_input() -> WeeklyProductionInput:
    selection = _selection()
    items = tuple(
        WeeklyProductionInputItem(
            role=selected.role,
            material_package_id=UUID(int=ordinal + 20),
            event_id=selected.event_id,
            event_version_id=selected.event_version_id,
            title=f"真实选题 {ordinal}",
            material_request_fingerprint=_sha(f"material:{ordinal}"),
            score_fingerprint=_sha(f"score:{ordinal}"),
            source_metadata_fingerprint=selected.source_metadata_fingerprint,
            organization_type=selected.organization_type,
            official_authority=selected.official_authority,
            selection_reason=selected.selection_reason.value,
            affinity_reasons=selected.affinity_reasons,
            governed_total=selected.governed_total,
            governed_score_version=selected.governed_score_version,
        )
        for ordinal, selected in enumerate(selection.selected, start=1)
    )
    return WeeklyProductionInput(
        week_start=selection.week_start,
        cutoff=datetime(2026, 9, 1, 1, tzinfo=UTC),
        selection=selection,
        items=(items[0], items[1], items[2]),
    )


def test_production_input_freezes_selection_authority_and_score_lineage() -> None:
    planned = _production_input()

    projection = planned.as_dict()
    projected_items = projection["items"]
    assert isinstance(projected_items, list)
    first = projected_items[0]
    assert isinstance(first, dict)
    assert first["organization_type"] == "government"
    assert first["official_authority"] == "stored_government_organization_type"
    assert first["governed_score_version"] == "scoring-v1"
    assert planned.fingerprint == _fingerprint(projection)


def _claim(
    *,
    planned: WeeklyProductionInput,
    ordinal: int,
    dependencies: tuple[WeeklyDagNodeSnapshot, ...] = (),
) -> WeeklyDagClaim:
    now = datetime(2026, 8, 31, 1, tzinfo=UTC)
    run = WeeklyDagRunSnapshot(
        run_id=weekly_dag_run_id(planned.week_start),
        task_id=weekly_dag_task_id(planned.week_start),
        week_start=planned.week_start,
        schedule_version=WEEKLY_EDITION_SCHEDULE_VERSION,
        selection_version=WEEKLY_EDITION_SELECTION_VERSION,
        dag_version=WEEKLY_DAG_VERSION,
        graph_fingerprint=weekly_dag_graph_fingerprint(),
        input_fingerprint=planned.fingerprint,
        request_fingerprint=weekly_dag_request_fingerprint(
            week_start=planned.week_start,
            input_fingerprint=planned.fingerprint,
        ),
        status=WeeklyDagRunStatus.RUNNING,
        aggregate_artifact=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
    node = WeeklyDagNodeSnapshot(
        run_id=run.run_id,
        definition=WEEKLY_DAG_NODES[ordinal],
        status=WeeklyDagNodeStatus.RUNNING,
        input_fingerprint=_sha(f"node-input:{ordinal}"),
        attempt_count=1,
        max_attempts=3,
        fencing_token=1,
        output_artifact=None,
        execution_artifact_id=None,
        trace_event_id=None,
        error_code=None,
        available_at=now,
        started_at=now,
        completed_at=None,
    )
    return WeeklyDagClaim(
        run=run,
        node=node,
        dependencies=dependencies,
        worker_id="production-test-worker",
        lease_expires_at=datetime(2026, 8, 31, 1, 15, tzinfo=UTC),
    )


class _ArticleRepository:
    def __init__(self, *, created: bool) -> None:
        self._created = created
        self.run = SimpleNamespace(id=UUID(int=90), status="ready")

    async def enqueue_material_package(self, **_kwargs: object) -> tuple[SimpleNamespace, bool]:
        return self.run, self._created

    async def get_run(self, _run_id: UUID) -> SimpleNamespace:
        return self.run


class _UnusedPreparedArtifacts:
    pass


@pytest.mark.asyncio
async def test_production_schedule_and_article_checkpoints_are_replay_stable(
    tmp_path: Path,
) -> None:
    planned = _production_input()
    owner = LocalWeeklyProductionArtifactOwner(tmp_path / "weekly")
    assert owner.put_json(planned.as_dict()).fingerprint == planned.fingerprint
    identity = official_account_identity_from_settings(
        Settings.model_validate({}),
        provider="zhipu",
        model="glm-test",
    )

    first_handlers = ProductionWeeklyDagHandlers(
        checkpoints=owner,
        article_repository=_ArticleRepository(created=True),
        prepared_artifacts=_UnusedPreparedArtifacts(),  # type: ignore[arg-type]
        article_identity=identity,
        article_wait_seconds=30,
        article_poll_seconds=0.5,
    )
    schedule = await first_handlers.execute(_claim(planned=planned, ordinal=0))
    schedule_payload = owner.get_json(schedule.artifact)
    assert schedule_payload["draft_only"] is True
    assert schedule_payload["published"] is False

    successful_schedule = replace(
        _claim(planned=planned, ordinal=0).node,
        status=WeeklyDagNodeStatus.SUCCEEDED,
        output_artifact=schedule.artifact,
        execution_artifact_id=UUID(int=201),
        trace_event_id=UUID(int=202),
        completed_at=datetime(2026, 8, 31, 1, tzinfo=UTC),
    )
    roles = await first_handlers.execute(
        _claim(planned=planned, ordinal=1, dependencies=(successful_schedule,))
    )
    successful_roles = replace(
        _claim(planned=planned, ordinal=1, dependencies=(successful_schedule,)).node,
        status=WeeklyDagNodeStatus.SUCCEEDED,
        output_artifact=roles.artifact,
        execution_artifact_id=UUID(int=203),
        trace_event_id=UUID(int=204),
        completed_at=datetime(2026, 8, 31, 1, tzinfo=UTC),
    )
    first_article = await first_handlers.execute(
        _claim(planned=planned, ordinal=2, dependencies=(successful_roles,))
    )

    replay_handlers = ProductionWeeklyDagHandlers(
        checkpoints=owner,
        article_repository=_ArticleRepository(created=False),
        prepared_artifacts=_UnusedPreparedArtifacts(),  # type: ignore[arg-type]
        article_identity=identity,
        article_wait_seconds=30,
        article_poll_seconds=0.5,
    )
    replay_article = await replay_handlers.execute(
        _claim(planned=planned, ordinal=2, dependencies=(successful_roles,))
    )
    assert replay_article.artifact == first_article.artifact
    assert "created" not in owner.get_json(first_article.artifact)


def test_weekly_production_checkpoint_owner_is_content_addressed(tmp_path: Path) -> None:
    owner = LocalWeeklyProductionArtifactOwner(tmp_path / "weekly")
    payload: dict[str, object] = {"version": "test-v1", "published": False}

    first = owner.put_json(payload)
    second = owner.put_json(dict(payload))

    assert first == second
    assert first.opaque_ref == f"weekly-production-v1:{first.fingerprint}"
    assert owner.get_json(first) == payload
    assert owner.get_json_by_fingerprint(first.fingerprint) == payload


def test_weekly_dag_long_article_wait_remains_hard_bounded() -> None:
    assert weekly_dag_node_limits().elapsed_ms == 900_000
    assert {
        definition.timeout_ms for definition in weekly_dag_capability_registry().definitions
    } == {900_000}


def test_weekly_production_settings_are_default_off_and_require_activation_monday() -> None:
    defaults = Settings.model_validate({})
    assert defaults.official_account_weekly_production_enabled is False
    assert defaults.official_account_weekly_scheduler_enabled is False
    assert defaults.official_account_weekly_worker_enabled is False
    assert defaults.official_account_weekly_worker_lease_seconds == 900
    assert defaults.official_account_weekly_article_wait_seconds == 720

    production = {
        "app_env": "production",
        "database_url": SecretStr("postgresql+asyncpg://app:prod@postgres:5432/app"),
        "governance_checkpoint_database_url": SecretStr("postgresql://app:prod@postgres:5432/app"),
        "minio_access_key": SecretStr("production-access"),
        "minio_secret_key": SecretStr("production-secret"),
        "official_account_weekly_production_enabled": True,
        "official_account_weekly_scheduler_enabled": True,
    }
    with pytest.raises(ValidationError, match="minimum week"):
        Settings.model_validate(production)
    with pytest.raises(ValidationError, match="cannot activate before"):
        Settings.model_validate(
            {**production, "official_account_weekly_min_week_start": "2026-08-31"}
        )
    enabled = Settings.model_validate(
        {**production, "official_account_weekly_min_week_start": "2026-09-07"}
    )
    assert enabled.official_account_weekly_min_week_start == date(2026, 9, 7)


def _jpeg(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (96, 64), color).save(output, format="JPEG", quality=88)
    return output.getvalue()


def _write_prepared_batch(inbox: Path) -> Path:
    week_start = date(2026, 9, 7)
    children: list[dict[str, object]] = []
    child_files: list[tuple[str, dict[str, bytes], dict[str, object]]] = []
    for role in WeeklyArticleRole:
        body_path = "assets/body-0.jpg"
        cover_path = "assets/cover-0.jpg"
        body = _jpeg((40 * role.ordinal, 80, 140))
        cover = _jpeg((140, 30 * role.ordinal, 60))
        html = f'<section><p><img src="{body_path}" alt="配图"></p></section>'.encode()
        files = {
            "article-body.html": html,
            body_path: body,
            cover_path: cover,
        }
        file_projection = [
            {"path": path, "byte_size": len(value), "sha256": hashlib.sha256(value).hexdigest()}
            for path, value in sorted(files.items())
        ]
        article_fingerprint = _sha(f"article:{role.value}")
        content_fingerprint = _sha(f"content:{role.value}")
        identity: dict[str, object] = {
            "version": PREPARED_DRAFT_CHILD_VERSION,
            "role": role.value,
            "run_id": str(UUID(int=100 + role.ordinal)),
            "article_fingerprint": article_fingerprint,
            "content_fingerprint": content_fingerprint,
            "title": f"每周科技观察 {role.ordinal}",
            "author": "赛先生",
            "digest": f"第 {role.ordinal} 篇自动草稿摘要",
            "media": [
                {
                    "path": body_path,
                    "role": "body",
                    "ordinal": 0,
                    "media_type": "image/jpeg",
                    "byte_size": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "width": 96,
                    "height": 64,
                },
                {
                    "path": cover_path,
                    "role": "cover",
                    "ordinal": 0,
                    "media_type": "image/jpeg",
                    "byte_size": len(cover),
                    "sha256": hashlib.sha256(cover).hexdigest(),
                    "width": 96,
                    "height": 64,
                },
            ],
            "files": file_projection,
            "published": False,
            "draft_only": True,
        }
        child_fingerprint = _fingerprint(identity)
        directory_name = f"{role.ordinal:02d}-{role.value}"
        children.append(
            {
                "role": role.value,
                "ordinal": role.ordinal,
                "directory": f"articles/{directory_name}",
                "child_fingerprint": child_fingerprint,
                "article_fingerprint": article_fingerprint,
                "content_fingerprint": content_fingerprint,
            }
        )
        child_files.append(
            (directory_name, files, {**identity, "child_fingerprint": child_fingerprint})
        )
    batch_fingerprint = _fingerprint(
        {
            "version": PREPARED_DRAFT_BATCH_VERSION,
            "week_start": week_start.isoformat(),
            "children": children,
        }
    )
    identity = {
        "version": PREPARED_DRAFT_BATCH_VERSION,
        "week_start": week_start.isoformat(),
        "batch_fingerprint": batch_fingerprint,
        "children": children,
        "published": False,
        "draft_only": True,
    }
    aggregate_fingerprint = _fingerprint(identity)
    root = inbox / f"official-account-prepared-weekly-{aggregate_fingerprint}"
    for directory_name, files, manifest in child_files:
        child_root = root / "articles" / directory_name
        for relative, body in files.items():
            target = child_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        (child_root / "prepared-manifest.json").write_bytes(_json_bytes(manifest))
    root.mkdir(parents=True, exist_ok=True)
    (root / "prepared-weekly.json").write_bytes(
        _json_bytes({**identity, "aggregate_fingerprint": aggregate_fingerprint})
    )
    return root


def test_prepared_batch_preflights_all_three_and_resolves_opaque_sources(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    source = _write_prepared_batch(inbox)
    prepared = load_prepared_weekly_draft_batch(source, max_image_bytes=10 * 1024 * 1024)
    store = LocalWeChatDraftArtifactStore(
        staging_root=tmp_path / "staging",
        inbox_root=inbox,
        minimum_week_start=date(2026, 9, 7),
    )

    discovered = store.discover_weekly()
    assert len(discovered.batches) == 1
    assert discovered.skipped_by_code == {}
    batch = discovered.batches[0]
    assert batch.aggregate_fingerprint == prepared.aggregate_fingerprint
    assert tuple(item.role for item in batch.sources) == tuple(
        role.value for role in WeeklyArticleRole
    )
    resolved = store.resolve(batch.sources[0].source_ref)
    assert resolved.source == batch.sources[0]
    assert resolved.directory.name == "01-official_anchor"


def test_prepared_batch_rejects_unbound_extra_root_file(tmp_path: Path) -> None:
    source = _write_prepared_batch(tmp_path / "inbox")
    (source / "unexpected.txt").write_text("not fingerprinted", encoding="utf-8")

    with pytest.raises(ValueError, match="root file set"):
        load_prepared_weekly_draft_batch(source, max_image_bytes=10 * 1024 * 1024)


def test_prepared_batch_rejects_nested_symlink_before_loading_child(tmp_path: Path) -> None:
    source = _write_prepared_batch(tmp_path / "inbox")
    child = source / "articles" / "01-official_anchor"
    (child / "external-assets").symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        load_prepared_weekly_draft_batch(source, max_image_bytes=10 * 1024 * 1024)
