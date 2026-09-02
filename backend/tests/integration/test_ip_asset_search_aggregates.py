from __future__ import annotations

import asyncio
import os
from datetime import date
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from app.core.config import get_settings
from app.domain.ip_assets import (
    IP_ASSET_SEARCH_V3_VERSION,
    IpAssetSearchEventKind,
    IpAssetSearchMode,
)
from app.infrastructure.db.ip_assets import PostgresIpAssetRepository
from app.infrastructure.db.models import IpAssetSearchAggregateModel
from sqlalchemy import delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_search_aggregate_migration_is_additive_and_downgrade_drops_only_counters(
    integration_context: IntegrationContext,
) -> None:
    base_url = make_url(integration_context.settings.database_url.get_secret_value())
    admin_url = base_url.set(drivername="postgresql", database="postgres")
    database_name = f"edu_ai_ip_search_mig_{uuid4().hex}"
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
        await asyncio.to_thread(command.upgrade, config, "20260827_0037")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval(
                "SELECT to_regclass('public.ip_asset_search_aggregates') IS NULL"
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.upgrade, config, "head")
        connection = await asyncpg.connect(postgres_url)
        try:
            await connection.execute(
                """
                INSERT INTO ip_asset_search_aggregates (
                    business_date, search_version, mode, event_kind, count
                ) VALUES ($1, $2, $3, $4, 1)
                """,
                date(2099, 8, 31),
                IP_ASSET_SEARCH_V3_VERSION,
                IpAssetSearchMode.SEMANTIC.value,
                IpAssetSearchEventKind.SEARCH_RESULTS.value,
            )
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260902_0044"
            )
        finally:
            await connection.close()

        await asyncio.to_thread(command.downgrade, config, "20260827_0037")
        connection = await asyncpg.connect(postgres_url)
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
                "20260827_0037"
            )
            assert await connection.fetchval(
                "SELECT to_regclass('public.ip_asset_search_aggregates') IS NULL"
            )
            assert await connection.fetchval("SELECT to_regclass('public.ip_assets') IS NOT NULL")
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


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_search_aggregate_upsert_is_atomic_bounded_and_identity_free(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresIpAssetRepository(integration_context.session_factory)
    target_date = date(2099, 8, 31)
    previous_date = date(2099, 8, 30)
    try:
        await asyncio.gather(
            *(
                repository.increment_search_aggregate(
                    business_date=target_date,
                    search_version=IP_ASSET_SEARCH_V3_VERSION,
                    mode=IpAssetSearchMode.SEMANTIC,
                    event_kind=IpAssetSearchEventKind.SEARCH_RESULTS,
                )
                for _ in range(12)
            )
        )
        await repository.increment_search_aggregate(
            business_date=target_date,
            search_version=IP_ASSET_SEARCH_V3_VERSION,
            mode=IpAssetSearchMode.SEMANTIC,
            event_kind=IpAssetSearchEventKind.PREVIEW_FROM_SEARCH,
        )
        await repository.increment_search_aggregate(
            business_date=previous_date,
            search_version=IP_ASSET_SEARCH_V3_VERSION,
            mode=IpAssetSearchMode.DEGRADED_METADATA,
            event_kind=IpAssetSearchEventKind.ZERO_RESULTS,
        )

        current = await repository.list_search_aggregates(
            start_date=target_date, end_date=target_date
        )
        assert {(row.mode, row.event_kind): row.count for row in current} == {
            (IpAssetSearchMode.SEMANTIC, IpAssetSearchEventKind.SEARCH_RESULTS): 12,
            (
                IpAssetSearchMode.SEMANTIC,
                IpAssetSearchEventKind.PREVIEW_FROM_SEARCH,
            ): 1,
        }
        window = await repository.list_search_aggregates(
            start_date=previous_date, end_date=target_date
        )
        assert len(window) == 3

        async with integration_context.session_factory() as session:
            columns = tuple(
                await session.scalars(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'ip_asset_search_aggregates' "
                        "ORDER BY ordinal_position"
                    )
                )
            )
        assert columns == (
            "business_date",
            "search_version",
            "mode",
            "event_kind",
            "count",
            "created_at",
            "updated_at",
        )
        serialized_columns = " ".join(columns)
        for prohibited in (
            "query",
            "asset",
            "profile",
            "session",
            "user",
            "ip_address",
            "agent",
            "referrer",
            "cookie",
        ):
            assert prohibited not in serialized_columns

        async with integration_context.session_factory() as session:
            session.add(
                IpAssetSearchAggregateModel(
                    business_date=target_date,
                    search_version="unsupported-version",
                    mode=IpAssetSearchMode.SEMANTIC.value,
                    event_kind=IpAssetSearchEventKind.DOWNLOAD_FROM_SEARCH.value,
                    count=1,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        async with integration_context.session_factory() as session:
            await session.execute(
                delete(IpAssetSearchAggregateModel).where(
                    IpAssetSearchAggregateModel.business_date.in_((previous_date, target_date))
                )
            )
            await session.commit()
