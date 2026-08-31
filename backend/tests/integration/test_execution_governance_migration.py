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
async def test_execution_governance_migration_is_additive_private_and_refuses_populated_downgrade(
    integration_context: IntegrationContext,
) -> None:
    base_url = make_url(integration_context.settings.database_url.get_secret_value())
    admin_url = base_url.set(drivername="postgresql", database="postgres")
    database_name = f"edu_ai_execution_mig_{uuid4().hex}"
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
        await asyncio.to_thread(command.upgrade, config, "20260831_0038")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval(
                "SELECT to_regclass('public.execution_governed_runs') IS NULL"
            )
            assert await connection.fetchval(
                "SELECT to_regclass('public.ip_asset_search_aggregates') IS NOT NULL"
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.upgrade, config, "head")
        connection = await asyncpg.connect(postgres_url)
        run_id = uuid4()
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260831_0039"
            )
            for table_name in (
                "execution_governed_runs",
                "execution_agent_allocations",
                "execution_trace_events",
                "execution_artifacts",
                "execution_budget_reservations",
            ):
                assert await connection.fetchval(
                    "SELECT to_regclass($1) IS NOT NULL", f"public.{table_name}"
                )
            columns = tuple(
                await connection.fetch(
                    """
                    SELECT table_name, column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name LIKE 'execution_%'
                    ORDER BY table_name, ordinal_position
                    """
                )
            )
            serialized_columns = " ".join(
                f"{row['table_name']}.{row['column_name']}" for row in columns
            )
            for prohibited in (
                "prompt",
                "message",
                "reasoning",
                "provider_body",
                "argument_json",
                "result_json",
                "object_key",
                "private_path",
                "credential",
                "database_url",
                "ip_address",
                "user_agent",
                "profile_token",
            ):
                assert prohibited not in serialized_columns

            await connection.execute(
                """
                INSERT INTO execution_governed_runs (
                    id, task_id, root_agent_id, policy_version, request_fingerprint, status,
                    limit_elapsed_ms, limit_model_turns, limit_input_tokens,
                    limit_output_tokens, limit_tool_calls, limit_tool_result_bytes,
                    limit_artifact_bytes, limit_children, max_depth, allow_child_agents
                ) VALUES (
                    $1, 'migration-test', 'root', 'execution-governance-v1', $2, 'running',
                    1000, 0, 0, 0, 0, 0, 0, 0, 1, false
                )
                """,
                run_id,
                "a" * 64,
            )
        finally:
            await connection.close()

        with pytest.raises(RuntimeError, match="destructive downgrade is disabled"):
            await asyncio.to_thread(command.downgrade, config, "20260831_0038")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260831_0039"
            )
            await connection.execute("DELETE FROM execution_governed_runs WHERE id = $1", run_id)
        finally:
            await connection.close()

        await asyncio.to_thread(command.downgrade, config, "20260831_0038")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260831_0038"
            )
            assert await connection.fetchval(
                "SELECT to_regclass('public.execution_governed_runs') IS NULL"
            )
            assert await connection.fetchval(
                "SELECT to_regclass('public.ip_asset_search_aggregates') IS NOT NULL"
            )
        finally:
            await connection.close()
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
