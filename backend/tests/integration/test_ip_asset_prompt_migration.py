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
from sqlalchemy.exc import DBAPIError

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_ip_prompt_migration_preserves_text_and_refuses_lossy_downgrade(
    integration_context: IntegrationContext,
) -> None:
    base_url = make_url(integration_context.settings.database_url.get_secret_value())
    admin_url = base_url.set(drivername="postgresql", database="postgres")
    database_name = f"edu_ai_ip_prompt_migration_{uuid4().hex}"
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
    try:
        config = Config("backend/alembic.ini")
        await asyncio.to_thread(command.upgrade, config, "20260825_0036")
        job_id = uuid4()
        short_prompt = "升级前保留的 IP 创作提示词"
        connection = await asyncpg.connect(postgres_url)
        try:
            await connection.execute(
                """
                INSERT INTO ip_asset_generation_jobs (
                    id, job_ref, idempotency_key, request_fingerprint, prompt,
                    character, asset_type, ratio, provider, model, status
                ) VALUES (
                    $1, 'ipg_11111111111111111111', 'prompt-migration-before-upgrade',
                    $2, $3, 'xiao_sai', 'scene_illustration', '1:1',
                    'fake', 'gpt-image-2', 'queued'
                )
                """,
                job_id,
                "a" * 64,
                short_prompt,
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.upgrade, config, "head")
        long_prompt = "图" * 2_001
        connection = await asyncpg.connect(postgres_url)
        try:
            assert (
                await connection.fetchval(
                    "SELECT prompt FROM ip_asset_generation_jobs WHERE id = $1", job_id
                )
                == short_prompt
            )
            await connection.execute(
                "UPDATE ip_asset_generation_jobs SET prompt = $1 WHERE id = $2",
                long_prompt,
                job_id,
            )
        finally:
            await connection.close()

        with pytest.raises(DBAPIError, match="prompts exceed 2000 characters"):
            await asyncio.to_thread(command.downgrade, config, "20260825_0036")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert (
                await connection.fetchval("SELECT version_num FROM alembic_version")
                == "20260831_0038"
            )
            assert (
                await connection.fetchval(
                    "SELECT prompt FROM ip_asset_generation_jobs WHERE id = $1", job_id
                )
                == long_prompt
            )
            await connection.execute(
                "UPDATE ip_asset_generation_jobs SET prompt = $1 WHERE id = $2",
                short_prompt,
                job_id,
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.downgrade, config, "20260825_0036")
        connection = await asyncpg.connect(postgres_url)
        try:
            column_type = await connection.fetchval(
                """
                SELECT data_type
                FROM information_schema.columns
                WHERE table_name = 'ip_asset_generation_jobs' AND column_name = 'prompt'
                """
            )
            prompt = await connection.fetchval(
                "SELECT prompt FROM ip_asset_generation_jobs WHERE id = $1", job_id
            )
        finally:
            await connection.close()
        assert column_type == "character varying"
        assert prompt == short_prompt
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
