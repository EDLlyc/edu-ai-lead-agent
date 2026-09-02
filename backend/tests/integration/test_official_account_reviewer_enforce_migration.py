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


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_enforce_migration_refuses_populated_downgrade_and_allows_empty_round_trip() -> None:
    base_url = make_url(get_settings().database_url.get_secret_value())
    admin_url = base_url.set(database="postgres", drivername="postgresql")
    database_name = f"edu_ai_rev_enf_{uuid4().hex}"
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
        await asyncio.to_thread(command.upgrade, config, "head")
        connection = await asyncpg.connect(postgres_url)
        run_id = uuid4()
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260902_0044"
            )
            assert await connection.fetchval(
                "SELECT to_regclass('public.official_account_repair_requests') IS NOT NULL"
            )
            article_columns = {
                row["column_name"]
                for row in await connection.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' "
                    "AND table_name='official_account_article_versions'"
                )
            }
            assert {"revision_no", "repair_of_article_version_id"} <= article_columns
            review_record_columns = {
                row["column_name"]
                for row in await connection.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' "
                    "AND table_name='official_account_review_records'"
                )
            }
            assert {"run_id", "article_version_id"} <= review_record_columns
            lineage_constraints = {
                row["conname"]
                for row in await connection.fetch(
                    "SELECT conname FROM pg_constraint WHERE conname = ANY($1::text[])",
                    [
                        "fk_official_review_records_request_lineage",
                        "fk_official_account_repair_requests_review_lineage",
                        "fk_official_account_article_runs_active_review_record",
                        "fk_official_account_render_versions_review_record_id",
                    ],
                )
            }
            assert lineage_constraints == {
                "fk_official_review_records_request_lineage",
                "fk_official_account_repair_requests_review_lineage",
                "fk_official_account_article_runs_active_review_record",
                "fk_official_account_render_versions_review_record_id",
            }
            await connection.execute(
                "INSERT INTO official_account_article_runs "
                "(id, fixture_id, generation_mode, source_fingerprint, request_fingerprint, "
                "provider, model, version_bundle, status, current_stage) "
                "VALUES ($1, 'enforce-migration-fixture', 'fixture', $2, $3, 'fake', "
                "'official-account-fixture-v1', $4::jsonb, 'queued', 'queued')",
                run_id,
                "a" * 64,
                "b" * 64,
                '{"reviewer_mode":"enforce"}',
            )
        finally:
            await connection.close()

        with pytest.raises(
            RuntimeError,
            match="cannot downgrade Reviewer enforce while durable evidence exists",
        ):
            await asyncio.to_thread(command.downgrade, config, "20260902_0043")
        connection = await asyncpg.connect(postgres_url)
        governed_run_id = uuid4()
        governed_task_id = f"official.review:{uuid4()}"
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260902_0044"
            )
            await connection.execute(
                "DELETE FROM official_account_article_runs WHERE id=$1",
                run_id,
            )
            await connection.execute(
                "INSERT INTO execution_governed_runs "
                "(id, task_id, root_agent_id, policy_version, request_fingerprint, status, "
                "limit_elapsed_ms, limit_model_turns, limit_input_tokens, limit_output_tokens, "
                "limit_tool_calls, limit_tool_result_bytes, limit_artifact_bytes, limit_children, "
                "max_depth, allow_child_agents) VALUES "
                "($1, $2, 'official.review.orchestrator', 'execution-governance-v1', $3, "
                "'running', 1000, 4, 1, 1, 4, 1, 1, 4, 1, true)",
                governed_run_id,
                governed_task_id,
                "c" * 64,
            )
            await connection.execute(
                "INSERT INTO execution_agent_allocations "
                "(run_id, task_id, agent_id, role, status, depth, allow_child_agents, max_depth, "
                "limit_elapsed_ms, limit_model_turns, limit_input_tokens, limit_output_tokens, "
                "limit_tool_calls, limit_tool_result_bytes, limit_artifact_bytes, limit_children) "
                "VALUES ($1, $2, 'official.review.orchestrator', 'orchestrator', 'running', 0, "
                "true, 1, 1000, 4, 1, 1, 4, 1, 1, 4)",
                governed_run_id,
                governed_task_id,
            )
        finally:
            await connection.close()

        with pytest.raises(
            RuntimeError,
            match="cannot downgrade Reviewer enforce while durable evidence exists",
        ):
            await asyncio.to_thread(command.downgrade, config, "20260902_0043")
        connection = await asyncpg.connect(postgres_url)
        try:
            await connection.execute(
                "DELETE FROM execution_agent_allocations WHERE run_id=$1",
                governed_run_id,
            )
            await connection.execute(
                "DELETE FROM execution_governed_runs WHERE id=$1",
                governed_run_id,
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.downgrade, config, "20260902_0043")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260902_0043"
            )
            assert await connection.fetchval(
                "SELECT to_regclass('public.official_account_repair_requests') IS NULL"
            )
        finally:
            await connection.close()
        await asyncio.to_thread(command.upgrade, config, "head")
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
        get_settings.cache_clear()
        admin = await asyncpg.connect(admin_dsn)
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=$1", database_name
        )
        await admin.execute(f'DROP DATABASE "{database_name}"')
        await admin.close()
