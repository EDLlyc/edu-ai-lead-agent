from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import asyncpg
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app.core.config import Settings, get_settings
from app.infrastructure.db.session import create_engine, create_session_factory
from minio import Minio
from minio.error import S3Error
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@dataclass(frozen=True, slots=True)
class IntegrationContext:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def integration_context() -> AsyncIterator[IntegrationContext]:
    base_settings = Settings()
    base_url = make_url(base_settings.database_url.get_secret_value())
    database_name = f"edu_ai_test_{uuid4().hex}"
    admin_url = base_url.set(drivername="postgresql", database="postgres")
    admin = await asyncpg.connect(admin_url.render_as_string(hide_password=False))
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    await admin.close()

    test_url = base_url.set(database=database_name).render_as_string(hide_password=False)
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    get_settings.cache_clear()
    try:
        config = Config("backend/alembic.ini")
        await asyncio.to_thread(command.upgrade, config, "head")
        settings = Settings(
            database_url=SecretStr(test_url),
            minio_bucket=f"edu-ai-test-{uuid4().hex}",
            acquisition_first_run_item_limit=1,
            acquisition_daily_item_limit=1,
        )
        engine = create_engine(settings)
        yield IntegrationContext(settings, engine, create_session_factory(engine))
        await engine.dispose()
        minio_client = Minio(
            "127.0.0.1:9000",
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=False,
        )

        def remove_test_bucket() -> None:
            try:
                for item in minio_client.list_objects(settings.minio_bucket, recursive=True):
                    minio_client.remove_object(settings.minio_bucket, item.object_name)
                minio_client.remove_bucket(settings.minio_bucket)
            except S3Error as error:
                if error.code not in {"NoSuchBucket", "NoSuchKey"}:
                    raise

        await asyncio.to_thread(remove_test_bucket)
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
        get_settings.cache_clear()
        admin = await asyncpg.connect(admin_url.render_as_string(hide_password=False))
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE "{database_name}"')
        await admin.close()
