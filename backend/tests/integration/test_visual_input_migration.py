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
async def test_visual_input_v2_migration_backfills_v1_and_guards_downgrade(
    integration_context: IntegrationContext,
) -> None:
    base_url = make_url(integration_context.settings.database_url.get_secret_value())
    admin_url = base_url.set(drivername="postgresql", database="postgres")
    database_name = f"edu_ai_visual_input_migration_{uuid4().hex}"
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
        await asyncio.to_thread(command.upgrade, config, "20260821_0024")
        connection = await asyncpg.connect(postgres_url)
        job_id = uuid4()
        unsupported_job_id = uuid4()
        checksum = "a" * 64
        try:
            await connection.execute(
                """
                INSERT INTO brand_visual_index_jobs (
                    id, derivation_key, asset_id, asset_checksum, catalog_version,
                    provider, model, dimensions, input_policy_version, status
                ) VALUES (
                    $1, $2, $3, $3, 'brand-visual-catalog-v1',
                    'alibaba-model-studio', 'qwen3-vl-embedding', 2048,
                    'brand-visual-embedding-input-v1', 'succeeded'
                )
                """,
                job_id,
                "b" * 64,
                checksum,
            )
            vector_literal = "[1," + ",".join("0" for _ in range(2_047)) + "]"
            await connection.execute(
                """
                INSERT INTO brand_visual_asset_embeddings (
                    id, job_id, derivation_key, asset_id, asset_checksum,
                    catalog_version, provider, model, dimensions,
                    input_policy_version, request_fingerprint, vector
                ) VALUES (
                    $1, $2, $3, $4, $4, 'brand-visual-catalog-v1',
                    'alibaba-model-studio', 'qwen3-vl-embedding', 2048,
                    'brand-visual-embedding-input-v1', $5, $6::vector
                )
                """,
                uuid4(),
                job_id,
                "b" * 64,
                checksum,
                "c" * 64,
                vector_literal,
            )
            await connection.execute(
                """
                INSERT INTO brand_visual_index_jobs (
                    id, derivation_key, asset_id, asset_checksum, catalog_version,
                    provider, model, dimensions, input_policy_version, status
                ) VALUES (
                    $1, $2, $3, $3, 'brand-visual-catalog-v1',
                    'alibaba-model-studio', 'qwen3-vl-embedding', 2048,
                    'brand-visual-embedding-input-v2', 'failed'
                )
                """,
                unsupported_job_id,
                "d" * 64,
                "e" * 64,
            )
        finally:
            await connection.close()

        with pytest.raises(RuntimeError, match="only historical visual v1 rows"):
            await asyncio.to_thread(command.upgrade, config, "head")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert (
                await connection.fetchval("SELECT version_num FROM alembic_version")
                == "20260821_0024"
            )
            assert not await connection.fetchval(
                "SELECT EXISTS ("
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'brand_visual_index_jobs' "
                "AND column_name = 'embedding_input_sha256')"
            )
            await connection.execute(
                "DELETE FROM brand_visual_index_jobs WHERE id = $1",
                unsupported_job_id,
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.upgrade, config, "head")
        connection = await asyncpg.connect(postgres_url)
        try:
            revision = await connection.fetchval("SELECT version_num FROM alembic_version")
            job_input_hash = await connection.fetchval(
                "SELECT embedding_input_sha256 FROM brand_visual_index_jobs WHERE id = $1",
                job_id,
            )
            embedding_input_hash = await connection.fetchval(
                "SELECT embedding_input_sha256 "
                "FROM brand_visual_asset_embeddings WHERE job_id = $1",
                job_id,
            )
        finally:
            await connection.close()
        assert revision == "20260825_0036"
        assert job_input_hash == checksum
        assert embedding_input_hash == checksum

        await asyncio.to_thread(command.downgrade, config, "20260821_0024")
        await asyncio.to_thread(command.upgrade, config, "head")
        connection = await asyncpg.connect(postgres_url)
        try:
            await connection.execute(
                "UPDATE brand_visual_index_jobs "
                "SET input_policy_version = 'brand-visual-embedding-input-v2' WHERE id = $1",
                job_id,
            )
        finally:
            await connection.close()
        with pytest.raises(RuntimeError, match="normalized visual embedding rows"):
            await asyncio.to_thread(command.downgrade, config, "20260821_0024")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert (
                await connection.fetchval("SELECT version_num FROM alembic_version")
                == "20260825_0036"
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
