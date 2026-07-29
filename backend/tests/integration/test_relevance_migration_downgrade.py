from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from app.core.config import get_settings
from app.infrastructure.db.repositories import seed_sources
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.ingestion.source_profiles import SOURCE_SEEDS
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_relevance_downgrade_reactivates_legacy_source_version(
    integration_context: IntegrationContext,
) -> None:
    base_url = make_url(integration_context.settings.database_url.get_secret_value())
    admin_url = base_url.set(drivername="postgresql", database="postgres")
    database_name = f"edu_ai_downgrade_{uuid4().hex}"
    admin_dsn = admin_url.render_as_string(hide_password=False)
    admin = await asyncpg.connect(admin_dsn)
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    await admin.close()

    test_url = base_url.set(database=database_name).render_as_string(hide_password=False)
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    get_settings.cache_clear()
    engine = None
    try:
        config = Config("backend/alembic.ini")
        await asyncio.to_thread(command.upgrade, config, "head")
        settings = integration_context.settings.model_copy(
            update={"database_url": SecretStr(test_url)}
        )
        engine = create_engine(settings)
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            await seed_sources(session)

        seed = SOURCE_SEEDS[0]
        legacy_id = uuid4()
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO source_versions (
                        id, source_id, version, trust_tier, connector_key, entry_url,
                        allowed_hosts, allowed_path_prefixes, cadence, timezone, language,
                        robots_status, terms_reviewed_at, rate_limit_seconds,
                        connector_version, parser_version, relevance_rule_version,
                        config_fingerprint
                    )
                    SELECT
                        :legacy_id, source_id, version + 1000, trust_tier, connector_key,
                        entry_url, allowed_hosts, allowed_path_prefixes, cadence, timezone,
                        language, robots_status, terms_reviewed_at, rate_limit_seconds,
                        connector_version, parser_version, NULL, :legacy_fingerprint
                    FROM source_versions
                    WHERE id = :current_id
                    """
                ),
                {
                    "legacy_id": legacy_id,
                    "legacy_fingerprint": uuid4().hex,
                    "current_id": seed.source_version_id,
                },
            )
        await engine.dispose()
        engine = None

        await asyncio.to_thread(command.downgrade, config, "20260728_0002")

        downgraded_engine = create_engine(settings)
        try:
            async with downgraded_engine.connect() as connection:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                active_version_id = await connection.scalar(
                    text("SELECT active_version_id FROM sources WHERE id = :source_id"),
                    {"source_id": seed.source_id},
                )
                no_legacy_active_version_id = await connection.scalar(
                    text("SELECT active_version_id FROM sources WHERE id = :source_id"),
                    {"source_id": SOURCE_SEEDS[1].source_id},
                )
                current_version_count = await connection.scalar(
                    text("SELECT count(*) FROM source_versions WHERE id = :current_id"),
                    {"current_id": seed.source_version_id},
                )
        finally:
            await downgraded_engine.dispose()

        assert revision == "20260728_0002"
        assert active_version_id == legacy_id
        assert no_legacy_active_version_id is None
        assert current_version_count == 1
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
