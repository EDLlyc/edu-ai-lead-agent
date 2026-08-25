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
            slot_acquisition_id = uuid4()
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
            await populated.execute(
                """
                INSERT INTO acquisition_runs (
                    id, trigger, business_date, timezone, acquisition_version,
                    content_slot, status
                ) VALUES (
                    $1, 'scheduled', DATE '2093-08-14', 'Asia/Shanghai',
                    'downgrade-slot-v1', 'morning', 'succeeded'
                )
                """,
                slot_acquisition_id,
            )
        finally:
            await populated.close()
        await asyncio.to_thread(command.downgrade, config, "20260814_0020")
        previous_head = await asyncpg.connect(
            make_url(test_url).set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            historical_document_id = uuid4()
            historical_version_id = uuid4()
            historical_chunk_id = uuid4()
            historical_text = "historical synthetic brand chunk"
            historical_hash = "a" * 64
            await previous_head.execute(
                """
                INSERT INTO brand_documents (
                    id, brand_slug, document_key, title, document_kind,
                    audience, language, status
                ) VALUES (
                    $1, 'sai-xiansheng', $2, 'Synthetic migration document',
                    'other', 'internal', 'zh-CN', 'active'
                )
                """,
                historical_document_id,
                "b" * 64,
            )
            await previous_head.execute(
                """
                INSERT INTO brand_document_versions (
                    id, document_id, version, safe_filename, media_type,
                    byte_size, sha256, bucket, object_key, metadata_fingerprint,
                    parser_version, chunk_version, embedding_input_version,
                    embedding_provider, embedding_model, embedding_dimensions,
                    status, active, tone_tags, safety_tags, visual_tags
                ) VALUES (
                    $1, $2, 1, 'synthetic.md', 'text/markdown',
                    1, $3, 'synthetic', 'synthetic/object', $4,
                    'parser-v2', 'chunk-v2', 'input-v1',
                    'configured-provider', 'configured-model', 2048,
                    'ready', false, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb
                )
                """,
                historical_version_id,
                historical_document_id,
                "c" * 64,
                "d" * 64,
            )
            await previous_head.execute(
                """
                INSERT INTO brand_chunks (
                    id, version_id, ordinal, chunk_key, text_hash,
                    text, char_start, char_end
                ) VALUES ($1, $2, 0, $3, $4, $5, 0, $6)
                """,
                historical_chunk_id,
                historical_version_id,
                "e" * 64,
                historical_hash,
                historical_text,
                len(historical_text),
            )
            revision_at_previous_head = await previous_head.fetchval(
                "SELECT version_num FROM alembic_version"
            )
            preserved_slot = await previous_head.fetchval(
                "SELECT count(*) FROM acquisition_runs WHERE id = $1",
                slot_acquisition_id,
            )
            preserved_governance = await previous_head.fetchval(
                "SELECT count(*) FROM governance_runs"
            )
        finally:
            await previous_head.close()
        assert revision_at_previous_head == "20260814_0020"
        assert preserved_slot == 1
        assert preserved_governance == 1
        await asyncio.to_thread(command.upgrade, config, "head")
        populated = await asyncpg.connect(
            make_url(test_url).set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            historical_chunk = await populated.fetchrow(
                """
                SELECT section_id, section_ordinal, embedding_text,
                       embedding_input_hash, content_type, claim_scope,
                       verification_required,
                       search_vector @@ plainto_tsquery('simple', 'historical') AS searchable
                FROM brand_chunks
                WHERE id = $1
                """,
                historical_chunk_id,
            )
        finally:
            await populated.close()
        assert historical_chunk is not None
        assert historical_chunk["section_id"] is None
        assert historical_chunk["section_ordinal"] is None
        assert historical_chunk["embedding_text"] == historical_text
        assert historical_chunk["embedding_input_hash"] == historical_hash
        assert historical_chunk["content_type"] == "other"
        assert historical_chunk["claim_scope"] == "brand_statement"
        assert historical_chunk["verification_required"] is False
        assert historical_chunk["searchable"] is True
        with pytest.raises(RuntimeError, match="content-slot artifacts exist"):
            await asyncio.to_thread(command.downgrade, config, "20260807_0019")
        populated = await asyncpg.connect(
            make_url(test_url).set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            revision_after_slot_refusal = await populated.fetchval(
                "SELECT version_num FROM alembic_version"
            )
            await populated.execute(
                "DELETE FROM acquisition_runs WHERE id = $1",
                slot_acquisition_id,
            )
        finally:
            await populated.close()
        assert revision_after_slot_refusal == "20260824_0035"
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
        assert revision_after_refusal == "20260824_0035"
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
