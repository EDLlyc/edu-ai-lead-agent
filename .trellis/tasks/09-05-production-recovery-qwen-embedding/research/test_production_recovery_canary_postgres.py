"""Real PostgreSQL safety checks on the task's isolated, provider-disabled test network."""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.domain.brand_knowledge import BrandAudience, BrandDocumentKind
from app.infrastructure.db.brand_knowledge import PostgresBrandKnowledgeRepository
from pydantic import SecretStr
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

SCRIPT = Path(__file__).with_name("production-recovery-canary.py")
SPEC = importlib.util.spec_from_file_location("recovery_canary_postgres_review", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
canary = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = canary
SPEC.loader.exec_module(canary)

LOCAL_DATABASE_URL = "postgresql+asyncpg://edu_ai:edu_ai_local_change_me@postgres:5432/edu_ai"


@pytest.fixture
async def engines() -> AsyncIterator[tuple[AsyncEngine, AsyncEngine, str, str]]:
    # Never accept an arbitrary database endpoint or inherit application/provider settings.
    # The runner additionally binds the task-owned isolated Docker network.
    if (
        os.environ.get("DATABASE_URL") != LOCAL_DATABASE_URL
        or os.environ.get("AI_PROVIDER_MODE") != "disabled"
    ):
        pytest.skip("requires the isolated provider-disabled task test environment")
    settings = Settings(_env_file=None).model_copy(
        update={"database_url": SecretStr(LOCAL_DATABASE_URL)}
    )
    setup = create_async_engine(LOCAL_DATABASE_URL)
    readonly = cast(AsyncEngine, canary.readonly_engine(settings))
    table = f"canary_review_{uuid4().hex}"
    sequence = f"canary_review_{uuid4().hex}"
    created = False
    try:
        async with setup.begin() as connection:
            await connection.execute(text(f'CREATE TABLE "{table}" (value integer NOT NULL)'))
            await connection.execute(text(f'INSERT INTO "{table}" VALUES (17)'))
            await connection.execute(text(f'CREATE SEQUENCE "{sequence}"'))
        created = True
        yield setup, readonly, table, sequence
    finally:
        await readonly.dispose()
        if created:
            async with setup.begin() as connection:
                await connection.execute(text(f'DROP TABLE "{table}"'))
                await connection.execute(text(f'DROP SEQUENCE "{sequence}"'))
        await setup.dispose()


async def test_real_sessions_and_new_transactions_are_readonly(
    engines: tuple[AsyncEngine, AsyncEngine, str, str],
) -> None:
    _, engine, _, _ = engines
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    for _ in range(3):
        async with sessions() as session:
            assert await session.scalar(text("SHOW default_transaction_read_only")) == "on"
            assert await session.scalar(text("SHOW transaction_read_only")) == "on"
            assert await session.scalar(text("SHOW statement_timeout")) == "10s"
            await session.commit()
            assert await session.scalar(text("SHOW transaction_read_only")) == "on"


@pytest.mark.parametrize("operation", ["insert", "update", "delete", "change_readonly"])
async def test_real_database_write_statements_are_denied_before_execution(
    engines: tuple[AsyncEngine, AsyncEngine, str, str], operation: str
) -> None:
    setup, readonly, table, _ = engines
    statements = {
        "insert": f'INSERT INTO "{table}" VALUES (29)',
        "update": f'UPDATE "{table}" SET value=29',
        "delete": f'DELETE FROM "{table}"',
        "change_readonly": "SET TRANSACTION READ WRITE",
    }
    async with readonly.connect() as connection:
        with pytest.raises(canary.CanaryError, match="database_statement_denied"):
            await connection.execute(text(statements[operation]))
    async with setup.connect() as connection:
        assert (await connection.scalars(text(f'SELECT value FROM "{table}"'))).all() == [17]


@pytest.mark.parametrize("operation", ["nextval", "row_lock"])
async def test_postgresql_itself_rejects_write_side_effects_in_select(
    engines: tuple[AsyncEngine, AsyncEngine, str, str], operation: str
) -> None:
    setup, readonly, table, sequence = engines
    statement = (
        f"SELECT nextval('{sequence}')"
        if operation == "nextval"
        else f'SELECT * FROM "{table}" FOR UPDATE'
    )
    # These deliberately pass the SQL prefix guard. The real server, not a mocked event,
    # must enforce the second boundary with SQLSTATE read_only_sql_transaction.
    async with readonly.connect() as connection:
        with pytest.raises(DBAPIError) as captured:
            await connection.execute(text(statement))
        assert getattr(captured.value.orig, "sqlstate", None) == "25006"
    async with setup.connect() as connection:
        assert (await connection.scalars(text(f'SELECT value FROM "{table}"'))).all() == [17]
        assert await connection.scalar(text(f'SELECT is_called FROM "{sequence}"')) is False


async def test_real_brand_repository_sessions_keep_readonly_boundary(
    engines: tuple[AsyncEngine, AsyncEngine, str, str],
) -> None:
    _, engine, _, _ = engines
    observed: list[str] = []

    @event.listens_for(engine.sync_engine, "begin")
    def observe_readonly(connection: Connection) -> None:
        observed.append(str(connection.exec_driver_sql("SHOW transaction_read_only").scalar()))

    settings = Settings(_env_file=None)
    repository = PostgresBrandKnowledgeRepository(
        async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    )
    await repository.retrieve(
        query_text="synthetic canary brand context",
        query_vector=(1.0,) + (0.0,) * 2047,
        query_provider="canary-review-unused-provider",
        query_model="synthetic-model",
        audience=BrandAudience.PARENTS,
        document_kinds=tuple(BrandDocumentKind),
        valid_on=date(2026, 9, 5),
        limit=1,
        candidate_limit=5,
        retrieval_version=settings.brand_retrieval_version,
    )
    assert observed == ["on"]
