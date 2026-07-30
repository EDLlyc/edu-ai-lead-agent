from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from app.core.config import get_settings
from sqlalchemy.engine import make_url

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_governance_migration_downgrades_without_touching_acquisition(
    integration_context: IntegrationContext,
) -> None:
    base_url = make_url(integration_context.settings.database_url.get_secret_value())
    admin_url = base_url.set(drivername="postgresql", database="postgres")
    database_name = f"edu_ai_governance_downgrade_{uuid4().hex}"
    admin_dsn = admin_url.render_as_string(hide_password=False)
    admin = await asyncpg.connect(admin_dsn)
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    await admin.close()

    test_url = base_url.set(database=database_name).render_as_string(hide_password=False)
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    get_settings.cache_clear()
    try:
        config = Config("backend/alembic.ini")
        await asyncio.to_thread(command.upgrade, config, "head")
        populated = await asyncpg.connect(
            make_url(test_url).set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            await populated.execute(
                """
                INSERT INTO governance_runs (
                    id, trigger, manual_idempotency_key, timezone, profile_fingerprint,
                    version_bundle, status
                ) VALUES ($1, 'manual', $2, 'Asia/Shanghai', $3, '{}'::jsonb, 'succeeded')
                """,
                uuid4(),
                f"downgrade-guard-{uuid4()}",
                uuid4().hex + uuid4().hex,
            )
        finally:
            await populated.close()
        with pytest.raises(RuntimeError, match="governance or checkpoint data exists"):
            await asyncio.to_thread(command.downgrade, config, "20260729_0003")
        populated = await asyncpg.connect(
            make_url(test_url).set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            revision_after_refusal = await populated.fetchval(
                "SELECT version_num FROM alembic_version"
            )
            await populated.execute("DELETE FROM governance_runs")
        finally:
            await populated.close()
        assert revision_after_refusal == "20260730_0007"
        await asyncio.to_thread(command.downgrade, config, "20260729_0003")

        downgraded_url = make_url(test_url)
        connection = await asyncpg.connect(
            downgraded_url.set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            revision = await connection.fetchval("SELECT version_num FROM alembic_version")
            acquisition_exists = await connection.fetchval(
                "SELECT to_regclass('public.acquisition_runs') IS NOT NULL"
            )
            governance_exists = await connection.fetchval(
                "SELECT to_regclass('public.governance_runs') IS NOT NULL"
            )
            checkpoints_exist = await connection.fetchval(
                "SELECT to_regclass('public.checkpoints') IS NOT NULL"
            )
        finally:
            await connection.close()

        assert revision == "20260729_0003"
        assert acquisition_exists is True
        assert governance_exists is False
        assert checkpoints_exist is False
    finally:
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
