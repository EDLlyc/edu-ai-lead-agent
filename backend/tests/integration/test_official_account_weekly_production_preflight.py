from __future__ import annotations

import asyncio
import importlib.util
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.application.services.official_account_weekly_dag import OfficialAccountWeeklyDagService
from app.application.services.official_account_weekly_production import (
    ProductionWeeklyDagHandlers,
    WeeklyProductionArticleRepository,
    WeeklyProductionPreparedArtifacts,
)
from app.domain.official_account_weekly_dag import WeeklyDagNodeStatus, WeeklyDagRunStatus
from app.domain.official_account_weekly_edition import WeeklyArticleRole
from app.infrastructure.db.execution_governance import PostgresExecutionGovernanceRepository
from app.infrastructure.db.models import (
    OfficialAccountArticleRunModel,
    OfficialAccountWeeklyDagAttemptModel,
)
from app.infrastructure.db.official_account_local import PostgresOfficialAccountRepository
from app.infrastructure.db.official_account_weekly_dag import (
    PostgresOfficialAccountWeeklyDagRepository,
)
from app.infrastructure.official_account_runtime import official_account_identity_from_settings
from app.infrastructure.official_account_weekly_dag_governance import (
    PostgresOfficialAccountWeeklyDagGovernance,
)
from app.infrastructure.official_account_weekly_production import LocalWeeklyProductionArtifactOwner
from sqlalchemy import (
    Column,
    ForeignKey,
    MetaData,
    Table,
    Text,
    Uuid,
    inspect,
    literal,
    select,
    text,
)
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import registry

from .conftest import IntegrationContext

_RECOVERY_OPERATOR_PATH = (
    Path(__file__).resolve().parents[3]
    / ".trellis/tasks/09-05-production-recovery-qwen-embedding/research/weekly-recovery"
    / "weekly_recovery.py"
)
_SOURCE_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "unit/test_official_account_weekly_material_preflight.py"
)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_missing_frozen_material_is_terminal_after_one_durable_attempt(
    integration_context: IntegrationContext, tmp_path: Path
) -> None:
    week_start = date(2098, 1, 6)
    now = datetime(2098, 1, 6, 1, tzinfo=UTC)
    package_ids = tuple(uuid4() for _role in WeeklyArticleRole)
    owner = LocalWeeklyProductionArtifactOwner(tmp_path / "weekly")
    frozen_input = owner.put_json(
        {
            "version": "official-account-weekly-production-input-v1",
            "week_start": week_start.isoformat(),
            "selection_fingerprint": sha256(b"weekly-material-preflight").hexdigest(),
            "items": [
                {
                    "role": role.value,
                    "material_package_id": str(package_id),
                    "event_id": str(uuid4()),
                    "event_version_id": str(uuid4()),
                }
                for role, package_id in zip(WeeklyArticleRole, package_ids, strict=True)
            ],
        }
    )
    article_repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    handlers = ProductionWeeklyDagHandlers(
        checkpoints=owner,
        article_repository=cast(WeeklyProductionArticleRepository, article_repository),
        prepared_artifacts=cast(WeeklyProductionPreparedArtifacts, object()),
        article_identity=official_account_identity_from_settings(
            integration_context.settings, provider="zhipu", model="glm-test"
        ),
    )
    repository = PostgresOfficialAccountWeeklyDagRepository(integration_context.session_factory)
    governance = PostgresOfficialAccountWeeklyDagGovernance(
        repository=PostgresExecutionGovernanceRepository(integration_context.session_factory),
        session_factory=integration_context.session_factory,
    )
    service = OfficialAccountWeeklyDagService(
        repository=repository,
        governance=governance,
        handlers=handlers.registry(),
        clock=lambda: now,
    )
    run, created = await service.enqueue(
        week_start=week_start, input_fingerprint=frozen_input.fingerprint, now=now
    )
    assert created
    for phase in ("schedule", "selection", "build"):
        assert await service.process_once(worker_id=f"preflight.{phase}", lease_seconds=30)

    terminal = await service.status(run.run_id)
    assert terminal.run.status is WeeklyDagRunStatus.TERMINAL_FAILED
    failed = terminal.nodes[2]
    assert failed.definition.key == "official_anchor:build_article"
    assert failed.status is WeeklyDagNodeStatus.TERMINAL_FAILED
    assert failed.error_code == "invalid_selection"
    assert failed.attempt_count == 1
    assert failed.max_attempts == 3
    assert terminal.run.aggregate_artifact is None
    assert all(node.attempt_count == 0 for node in terminal.nodes[3:])

    for _ in range(3):
        assert await service.process_once(worker_id="preflight.repeat", lease_seconds=30) is None
    repeated = await service.status(run.run_id)
    assert repeated == terminal
    async with integration_context.session_factory() as session:
        attempts = tuple(
            await session.scalars(
                select(OfficialAccountWeeklyDagAttemptModel).where(
                    OfficialAccountWeeklyDagAttemptModel.run_id == run.run_id,
                    OfficialAccountWeeklyDagAttemptModel.node_key == failed.definition.key,
                )
            )
        )
        article_runs = tuple(
            await session.scalars(
                select(OfficialAccountArticleRunModel).where(
                    OfficialAccountArticleRunModel.material_package_id.in_(package_ids)
                )
            )
        )
    assert len(attempts) == 1
    assert attempts[0].error_code == "invalid_selection"
    assert article_runs == ()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_recovery_source_lock_blocks_updates_but_permits_fk_enqueue(
    integration_context: IntegrationContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the real operator lock sequence and PG FK locks on an isolated test schema.

    These three synthetic tables isolate lock semantics from paid article-generation fixtures;
    the preceding test separately exercises the real application repository and migrated tables.
    """
    spec = importlib.util.spec_from_file_location(
        "weekly_recovery_lock_check", _RECOVERY_OPERATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    operator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(operator)
    metadata = MetaData()
    mapper = registry(metadata=metadata)
    images = Table(
        "weekly_recovery_test_images",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("content", Text, nullable=False),
    )
    materials = Table(
        "weekly_recovery_test_materials",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("image_artifact_id", Uuid, ForeignKey(images.c.id), nullable=False),
        Column("content", Text, nullable=False),
    )
    articles = Table(
        "weekly_recovery_test_articles",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("material_package_id", Uuid, ForeignKey(materials.c.id), nullable=False),
    )

    class Material:
        pass

    class Image:
        pass

    mapper.map_imperatively(Material, materials)
    mapper.map_imperatively(Image, images)
    image_id, article_id = uuid4(), uuid4()
    async with integration_context.engine.begin() as connection:
        # Explicit test-only DDL; production metadata/migrations are untouched.
        await connection.execute(
            text(
                "CREATE TABLE weekly_recovery_test_images "
                "(id uuid PRIMARY KEY, content text NOT NULL)"
            )
        )
        await connection.execute(
            text(
                "CREATE TABLE weekly_recovery_test_materials (id uuid PRIMARY KEY, "
                "image_artifact_id uuid NOT NULL REFERENCES weekly_recovery_test_images(id), "
                "content text NOT NULL)"
            )
        )
        await connection.execute(
            text(
                "CREATE TABLE weekly_recovery_test_articles (id uuid PRIMARY KEY, "
                "material_package_id uuid NOT NULL REFERENCES weekly_recovery_test_materials(id))"
            )
        )
        await connection.execute(images.insert().values(id=image_id, content="image"))
        await connection.execute(
            materials.insert().values(
                id=operator.REPLACEMENT, image_artifact_id=image_id, content="material"
            )
        )
    monkeypatch.setattr(
        operator, "models", SimpleNamespace(MaterialPackageModel=Material, ImageArtifactModel=Image)
    )
    monkeypatch.setattr(
        operator,
        "material_package_source_snapshot",
        lambda package, image: SimpleNamespace(
            source_fingerprint=operator.digest([package.content, image.content])
        ),
    )
    monkeypatch.setattr(operator, "run_request_fingerprint", lambda **kwargs: "b" * 64)
    calls = []

    async def ordinary_enqueue(*, material_package_id, identity):
        calls.append(material_package_id)
        for table, row_id in ((materials, operator.REPLACEMENT), (images, image_id)):
            async with integration_context.engine.begin() as connection:
                await connection.execute(text("SET LOCAL lock_timeout = '100ms'"))
                with pytest.raises(DBAPIError) as caught:
                    await connection.execute(
                        table.update().where(table.c.id == row_id).values(content="drift")
                    )
                assert getattr(caught.value.orig, "sqlstate", None) == "55P03"
                await connection.rollback()
        # A different transaction performs the same package FK check as the normal enqueue.
        async with integration_context.engine.begin() as connection:
            await connection.execute(text("SET LOCAL lock_timeout = '1s'"))
            await connection.execute(
                articles.insert().values(id=article_id, material_package_id=material_package_id)
            )
        return SimpleNamespace(id=article_id), True

    runtime = object.__new__(operator.Runtime)
    runtime.factory = integration_context.session_factory
    runtime.identity = object()
    runtime.repository = SimpleNamespace(enqueue_material_package=ordinary_enqueue)
    binding = {
        "material_package_id": str(operator.REPLACEMENT),
        "source_fingerprint": operator.digest(["material", "image"]),
        "article_request_fingerprint": "b" * 64,
    }
    result, created = await asyncio.wait_for(runtime.enqueue(binding), timeout=5)
    assert created and result.id == article_id
    assert calls == [operator.REPLACEMENT]
    async with integration_context.engine.begin() as connection:
        assert await connection.scalar(select(materials.c.content)) == "material"
        assert await connection.scalar(select(images.c.content)) == "image"
        assert await connection.scalar(select(articles.c.id)) == article_id
        # Locks are released on return, including the lock-only transaction's rollback.
        await connection.execute(text("SET LOCAL lock_timeout = '1s'"))
        await connection.execute(materials.update().values(content="after_release"))


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_readonly_recovery_planner_retains_loaded_rows_after_rollback(
    integration_context: IntegrationContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real AsyncSession + ORM + planner; SELECT literals avoids unrelated FK fixture setup."""
    modules = []
    for name, path in (
        ("weekly_recovery_detach_check", _RECOVERY_OPERATOR_PATH),
        ("weekly_recovery_synthetic_sources", _SOURCE_FIXTURE_PATH),
    ):
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    operator, fixtures = modules
    seeds = tuple(fixtures._row(index) for index in range(1, 4))
    loaded = []

    async def load_model(session, seed):
        # Values are synthetic, but returned instances belong to the real AsyncSession
        # and would be expired by rollback unless the operator detaches them first.
        model = type(seed)
        projection = select(
            *(
                literal(getattr(seed, column.key), type_=column.type).label(column.key)
                for column in model.__table__.columns
            )
        )
        result = await session.scalar(select(model).from_statement(projection))
        assert result is not None and inspect(result).persistent
        loaded.append(result)
        return result

    async def load_rows(self, session, *, cutoff):
        return tuple([tuple([await load_model(session, seed) for seed in row]) for row in seeds])

    async def load_scores(self, session, rows):
        scores = {}
        for index, (package, run, _event, _image) in enumerate(rows, start=1):
            seed = fixtures.TopicScoreModel(
                id=uuid4(),
                event_id=run.selected_event_id,
                event_version_id=run.selected_event_version_id,
                raw_features={},
                normalized_features={},
                weights={},
                penalty_weights={},
                positive_components={},
                penalty_components={},
                total=0.99 - index / 100,
                threshold=0.59,
                passes_threshold=True,
                eligible=True,
                veto_codes=[],
                rank=index,
                deterministic_rank=index,
                explanation={"scoring_version": "scoring-test", "scoring_profile": "test"},
            )
            scores[package.id] = await load_model(session, seed)
        return scores

    monkeypatch.setattr(
        operator.PostgresWeeklyProductionInputPlanner, "_load_material_rows", load_rows
    )
    monkeypatch.setattr(operator.PostgresWeeklyProductionInputPlanner, "_load_scores", load_scores)
    monkeypatch.setattr(
        operator.PostgresWeeklyProductionInputPlanner,
        "_load_source_authority",
        AsyncMock(
            return_value={
                row[1].selected_event_id: (
                    ("government" if index == 0 else "authoritative_media", "a" * 64),
                )
                for index, row in enumerate(seeds)
            }
        ),
    )
    runtime = object.__new__(operator.Runtime)
    runtime.factory = integration_context.session_factory
    planner = operator.FullPreflightPlanner(runtime.readonly)
    result = await planner.plan(week_start=operator.WEEK, cutoff=operator.CUTOFF)
    assert [item.material_package_id for item in result.items] == [row[0].id for row in seeds]
    assert len(loaded) == 15
    assert all(inspect(row).detached and not inspect(row).expired for row in loaded)
