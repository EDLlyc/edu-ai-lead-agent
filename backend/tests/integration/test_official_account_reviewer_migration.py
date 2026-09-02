from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from app.application.services.official_account_reviewer import review_execution_scope
from app.core.config import Settings, get_settings
from app.infrastructure.db.models import (
    ExecutionAgentAllocationModel,
    ExecutionArtifactModel,
    ExecutionBudgetReservationModel,
    ExecutionGovernedRunModel,
    ExecutionTraceEventModel,
    OfficialAccountReviewRecordModel,
    OfficialAccountReviewRequestModel,
)
from app.infrastructure.db.official_account_local import PostgresOfficialAccountRepository
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.official_account_reviewer import (
    DeterministicFakeOfficialAccountReviewer,
)
from pydantic import SecretStr
from sqlalchemy import delete
from sqlalchemy.engine import make_url

from .conftest import IntegrationContext
from .test_official_account_local import _identity
from .test_official_account_reviewer_observe import _executor


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_reviewer_migration_is_additive_and_refuses_only_populated_downgrade(
    integration_context: IntegrationContext,
) -> None:
    base_url = make_url(integration_context.settings.database_url.get_secret_value())
    admin_url = base_url.set(drivername="postgresql", database="postgres")
    database_name = f"edu_ai_reviewer_mig_{uuid4().hex}"
    admin_dsn = admin_url.render_as_string(hide_password=False)
    admin = await asyncpg.connect(admin_dsn)
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    await admin.close()

    test_url = base_url.set(database=database_name).render_as_string(hide_password=False)
    postgres_url = (
        make_url(test_url).set(drivername="postgresql").render_as_string(hide_password=False)
    )
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    get_settings.cache_clear()
    engine = None
    try:
        config = Config("backend/alembic.ini")
        await asyncio.to_thread(command.upgrade, config, "20260901_0042")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval(
                "SELECT to_regclass('public.official_account_review_requests') IS NULL"
            )
            assert await connection.fetchval(
                "SELECT to_regclass('public.official_account_review_records') IS NULL"
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.upgrade, config, "head")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260902_0044"
            )
            columns = {
                row["column_name"]
                for row in await connection.fetch(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'official_account_review_requests'
                    """
                )
            }
            assert {
                "request_schema_version",
                "verdict_schema_version",
                "attempt_number",
                "article_sha256",
                "source_sha256",
                "brand_sha256",
                "reservation_id",
                "request_event_id",
            }.issubset(columns)
            constraints = {
                row["conname"]
                for row in await connection.fetch(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conname IN (
                        'uq_execution_reservations_identity',
                        'uq_execution_artifacts_producer',
                        'fk_official_review_requests_reservation',
                        'fk_official_account_review_records_execution_artifact_id'
                    )
                    """
                )
            }
            assert constraints == {
                "uq_execution_reservations_identity",
                "uq_execution_artifacts_producer",
                "fk_official_review_requests_reservation",
                "fk_official_account_review_records_execution_artifact_id",
            }
        finally:
            await connection.close()

        settings = Settings(_env_file=None, database_url=SecretStr(test_url))
        engine = create_engine(settings)
        context = IntegrationContext(settings, engine, create_session_factory(engine))
        repository = PostgresOfficialAccountRepository(context.session_factory)
        _run, created = await repository.enqueue_fixture(
            identity=replace(
                _identity(suffix="review-migration-populated"),
                reviewer_mode="observe",
            )
        )
        assert created is True
        executor, _, _ = _executor(context, DeterministicFakeOfficialAccountReviewer())
        assert await executor.execute_next("review-migration-worker") is True

        with pytest.raises(
            RuntimeError,
            match="refusing to drop populated official-account Reviewer observations",
        ):
            await asyncio.to_thread(command.downgrade, config, "20260901_0042")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260902_0044"
            )
        finally:
            await connection.close()

        async with context.session_factory() as session:
            await session.execute(delete(OfficialAccountReviewRecordModel))
            await session.execute(delete(OfficialAccountReviewRequestModel))
            await session.commit()
        with pytest.raises(
            RuntimeError,
            match="refusing to drop populated official-account Reviewer observations",
        ):
            await asyncio.to_thread(command.downgrade, config, "20260901_0042")

        execution_run_id, _ = review_execution_scope(_run.id)
        async with context.session_factory() as session:
            await session.execute(
                delete(ExecutionArtifactModel).where(
                    ExecutionArtifactModel.run_id == execution_run_id
                )
            )
            await session.execute(
                delete(ExecutionBudgetReservationModel).where(
                    ExecutionBudgetReservationModel.run_id == execution_run_id
                )
            )
            await session.execute(
                delete(ExecutionTraceEventModel).where(
                    ExecutionTraceEventModel.run_id == execution_run_id
                )
            )
            await session.execute(
                delete(ExecutionAgentAllocationModel).where(
                    ExecutionAgentAllocationModel.run_id == execution_run_id
                )
            )
            await session.execute(
                delete(ExecutionGovernedRunModel).where(
                    ExecutionGovernedRunModel.id == execution_run_id
                )
            )
            await session.commit()
        await engine.dispose()
        engine = None
        await asyncio.to_thread(command.downgrade, config, "20260901_0042")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260901_0042"
            )
            assert await connection.fetchval(
                "SELECT to_regclass('public.official_account_review_requests') IS NULL"
            )
            assert (
                await connection.fetchval(
                    "SELECT 1 FROM pg_constraint WHERE conname = 'uq_execution_artifacts_producer'"
                )
                is None
            )
        finally:
            await connection.close()
    finally:
        if engine is not None:
            await engine.dispose()
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
        get_settings.cache_clear()
        admin = await asyncpg.connect(admin_dsn)
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE "{database_name}"')
        await admin.close()
