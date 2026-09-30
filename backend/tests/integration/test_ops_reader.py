from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from app.core.errors import NotFoundError
from app.infrastructure.db.models import Base
from app.infrastructure.db.ops_reader import (
    OPS_READ_COLUMNS,
    OPS_READ_TABLES,
    PostgresOpsReader,
    verify_read_only_role,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_every_ops_query_runs_against_the_migrated_schema(integration_context) -> None:
    reader = PostgresOpsReader(integration_context.session_factory)
    day = date(2026, 9, 30)

    assert (await reader.list_slot_runs(day)).runs == ()
    assert (await reader.list_copy_runs(day, 20)).runs == ()
    assert (await reader.list_deliveries(day)).deliveries == ()
    trace = await reader.get_day_trace(day)
    assert trace.posts == () and trace.usage == ()
    with pytest.raises(NotFoundError):
        await reader.get_copy_run(uuid4())


def test_granted_tables_and_columns_exist_and_exclude_recipients() -> None:
    tables = Base.metadata.tables
    assert set(OPS_READ_TABLES) <= set(tables)
    assert not set(OPS_READ_TABLES) & set(OPS_READ_COLUMNS)
    for table, columns in OPS_READ_COLUMNS.items():
        assert set(columns) <= set(tables[table].columns.keys()), table
        assert not any("recipient" in column for column in columns)
    for table in OPS_READ_TABLES:
        assert not any("recipient" in column for column in tables[table].columns.keys()), table


async def test_the_role_check_refuses_a_superuser_connection(integration_context) -> None:
    # The integration database is reached as the application's superuser account.
    with pytest.raises(RuntimeError, match="read-only"):
        await verify_read_only_role(integration_context.engine)
