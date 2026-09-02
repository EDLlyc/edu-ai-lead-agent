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
async def test_personal_library_migration_backfills_shared_assets_and_refuses_data_loss(
    integration_context: IntegrationContext,
) -> None:
    base_url = make_url(integration_context.settings.database_url.get_secret_value())
    admin_url = base_url.set(drivername="postgresql", database="postgres")
    database_name = f"edu_ai_ip_personal_migration_{uuid4().hex}"
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
        await asyncio.to_thread(command.upgrade, config, "20260824_0034")
        asset_id = uuid4()
        connection = await asyncpg.connect(postgres_url)
        try:
            await connection.execute(
                """
                INSERT INTO ip_assets (
                    id, asset_ref, blob_sha256, perceptual_hash, safe_original_filename,
                    media_type, byte_size, width, height, has_alpha, orientation,
                    bucket, object_key, naming_key, canonical_name, canonical_slug,
                    name_version, character, asset_type, source_kind, department,
                    contributor, emotion, action, scene, intended_use, style,
                    status, semantic_status
                ) VALUES (
                    $1, 'ipa_11111111111111111111', $2, '0000000000000000', 'legacy.png',
                    'image/png', 128, 64, 64, true, 'square',
                    'private-bucket', 'ip-assets/originals/sha256/aa/legacy.png', $3,
                    '小赛-表情包-方图-v001', 'xiao-sai-meme-square-v001', 1,
                    'xiao_sai', 'meme_sticker', 'uploaded', '', '', '', '', '', '', '',
                    'ready', 'unavailable'
                )
                """,
                asset_id,
                "a" * 64,
                "b" * 64,
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.upgrade, config, "head")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval(
                "SELECT shared_at IS NOT NULL FROM ip_assets WHERE id = $1", asset_id
            )
            await connection.execute(
                """
                INSERT INTO ip_asset_profiles (
                    id, profile_ref, token_digest, display_name, department
                ) VALUES ($1, 'ipp_22222222222222222222', $2, '本地同事', '品牌部')
                """,
                uuid4(),
                "c" * 64,
            )
        finally:
            await connection.close()

        with pytest.raises(DBAPIError, match="personal-library data exists"):
            await asyncio.to_thread(command.downgrade, config, "20260824_0034")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert (
                await connection.fetchval("SELECT version_num FROM alembic_version")
                == "20260902_0044"
            )
            await connection.execute("DELETE FROM ip_asset_profiles")
        finally:
            await connection.close()

        await asyncio.to_thread(command.downgrade, config, "20260824_0034")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM ip_assets WHERE id = $1)", asset_id
            )
            assert not await connection.fetchval(
                "SELECT EXISTS ("
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'ip_assets' AND column_name = 'shared_at')"
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
