from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import SecretStr

from app.application.ports.governance import GovernanceCheckpointer


class PostgresGovernanceCheckpointer(GovernanceCheckpointer):
    """Official async saver using Alembic-owned tables and a psycopg URL."""

    def __init__(self, database_url: SecretStr) -> None:
        url = database_url.get_secret_value()
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"postgresql", "postgres"}
            or not parsed.hostname
            or not parsed.path.strip("/")
            or parsed.fragment
        ):
            raise ValueError("LangGraph checkpointing requires a psycopg PostgreSQL URL")
        self._database_url = database_url

    @asynccontextmanager
    async def saver(self) -> AsyncIterator[AsyncPostgresSaver]:
        # Alembic owns checkpoint DDL; never call saver.setup() at runtime.
        async with AsyncPostgresSaver.from_conn_string(
            self._database_url.get_secret_value()
        ) as saver:
            yield saver

    async def checkpoint_exists(self, *, thread_id: str) -> bool:
        async with self.saver() as saver:
            checkpoint = await saver.aget_tuple(
                {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
            )
        return checkpoint is not None
