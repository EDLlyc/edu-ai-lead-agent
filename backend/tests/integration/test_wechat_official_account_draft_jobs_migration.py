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
async def test_wechat_draft_jobs_migration_empty_downgrade_and_populated_refusal(
    integration_context: IntegrationContext,
) -> None:
    base_url = make_url(integration_context.settings.database_url.get_secret_value())
    admin_url = base_url.set(drivername="postgresql", database="postgres")
    database_name = f"edu_ai_wechat_draft_mig_{uuid4().hex}"
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
        await asyncio.to_thread(command.upgrade, config, "20260901_0041")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval(
                "SELECT to_regclass('public.wechat_mp_draft_jobs') IS NULL"
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.upgrade, config, "20260901_0042")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260901_0042"
            )
            tables = {
                row["table_name"]
                for row in await connection.fetch(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name LIKE 'wechat_mp_draft_%'
                    """
                )
            }
            assert tables == {
                "wechat_mp_draft_jobs",
                "wechat_mp_draft_items",
                "wechat_mp_draft_attempts",
            }
            columns = {
                row["column_name"]
                for row in await connection.fetch(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name IN (
                          'wechat_mp_draft_jobs',
                          'wechat_mp_draft_items',
                          'wechat_mp_draft_attempts'
                      )
                    """
                )
            }
            for prohibited in (
                "app_id",
                "app_secret",
                "access_token",
                "media_id",
                "body",
                "content",
                "filesystem_path",
                "object_key",
            ):
                assert prohibited not in columns
        finally:
            await connection.close()

        await asyncio.to_thread(command.downgrade, config, "20260901_0041")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260901_0041"
            )
            assert await connection.fetchval(
                "SELECT to_regclass('public.wechat_mp_draft_jobs') IS NULL"
            )
            assert await connection.fetchval(
                "SELECT to_regclass('public.wechat_mp_draft_items') IS NULL"
            )
            assert await connection.fetchval(
                "SELECT to_regclass('public.wechat_mp_draft_attempts') IS NULL"
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.upgrade, config, "20260901_0042")
        connection = await asyncpg.connect(postgres_url)
        job_id = uuid4()
        try:
            await connection.execute(
                """
                INSERT INTO wechat_mp_draft_jobs (
                    id, request_fingerprint, account_fingerprint,
                    aggregate_fingerprint, batch_fingerprint, policy_version,
                    status, max_attempts, available_at
                ) VALUES (
                    $1, $2, $3, $4, $5, 'wechat-mp-draft-job-v1',
                    'queued', 3, now()
                )
                """,
                job_id,
                "a" * 64,
                "b" * 64,
                "c" * 64,
                "d" * 64,
            )
        finally:
            await connection.close()

        with pytest.raises(
            DBAPIError,
            match=("cannot downgrade WeChat Official Account draft jobs while durable data exists"),
        ):
            await asyncio.to_thread(command.downgrade, config, "20260901_0041")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260901_0042"
            )
            await connection.execute(
                "DELETE FROM wechat_mp_draft_jobs WHERE id = $1",
                job_id,
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.downgrade, config, "20260901_0041")
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
