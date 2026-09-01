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
async def test_image_eval_migration_empty_downgrade_and_populated_refusal(
    integration_context: IntegrationContext,
) -> None:
    base_url = make_url(integration_context.settings.database_url.get_secret_value())
    admin_url = base_url.set(drivername="postgresql", database="postgres")
    database_name = f"edu_ai_image_eval_mig_{uuid4().hex}"
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
        await asyncio.to_thread(command.upgrade, config, "20260831_0040")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval(
                "SELECT to_regclass('public.official_account_generated_visual_evals') IS NULL"
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.upgrade, config, "20260901_0041")
        connection = await asyncpg.connect(postgres_url)
        try:
            columns = {
                row["column_name"]
                for row in await connection.fetch(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'official_account_generated_visual_evals'
                    """
                )
            }
            constraints = {
                row["conname"]: row["definition"]
                for row in await connection.fetch(
                    """
                    SELECT con.conname, pg_get_constraintdef(con.oid) AS definition
                    FROM pg_constraint AS con
                    JOIN pg_class AS rel ON rel.oid = con.conrelid
                    WHERE rel.relname = 'official_account_generated_visual_evals'
                    """
                )
            }
            assert "record_fingerprint" in columns
            assert "raw_prompt" not in columns
            assert "provider_body" not in columns
            assert "uq_official_generated_visual_evals_record_fingerprint" in constraints
            assert (
                "FOREIGN KEY (generated_visual_id, run_id, publication_sha256)"
                in constraints["fk_official_generated_visual_evals_visual_run_sha"]
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.downgrade, config, "20260831_0040")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260831_0040"
            )
            assert await connection.fetchval(
                "SELECT to_regclass('public.official_account_generated_visual_evals') IS NULL"
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.upgrade, config, "20260901_0041")
        connection = await asyncpg.connect(postgres_url)
        eval_id = uuid4()
        try:
            # The repository integration test covers the real composite parent fence. This row
            # exists only to exercise 0041's own non-empty downgrade guard in an isolated DB.
            await connection.execute("SET session_replication_role = replica")
            try:
                await connection.execute(
                    """
                    INSERT INTO official_account_generated_visual_evals (
                        id, generated_visual_id, run_id, publication_sha256,
                        decision, hard_gate_passed, manual_review_required,
                        evaluator_version, audit_prompt_version, rubric_version,
                        decision_policy_version, request_fingerprint, record_fingerprint,
                        provider, model, issue_codes, observation_snapshot
                    ) VALUES (
                        $1, $2, $3, $4,
                        'unavailable', false, true,
                        'migration-evaluator-v1', 'migration-prompt-v1',
                        'image-quality-rubric-v1', 'image-quality-decision-policy-v1',
                        $5, $6, NULL, NULL, '[]'::jsonb,
                        '[{},{},{},{},{}]'::jsonb
                    )
                    """,
                    eval_id,
                    uuid4(),
                    uuid4(),
                    "a" * 64,
                    "b" * 64,
                    "c" * 64,
                )
            finally:
                await connection.execute("SET session_replication_role = origin")
        finally:
            await connection.close()

        with pytest.raises(
            DBAPIError,
            match="cannot downgrade official-account generated visual eval artifacts",
        ):
            await asyncio.to_thread(command.downgrade, config, "20260831_0040")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260901_0041"
            )
            await connection.execute(
                "DELETE FROM official_account_generated_visual_evals WHERE id = $1",
                eval_id,
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.downgrade, config, "20260831_0040")
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
