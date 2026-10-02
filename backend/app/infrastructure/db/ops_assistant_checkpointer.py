"""Where the ops assistant keeps its LangGraph checkpoints.

Checkpoints are writes, so they never go to the database the assistant reads production through:
`OPS_DATABASE_URL` is a SELECT-only role behind the SSH tunnel, and the checkpoint database must be
a different server (normally the local development database, whose Alembic migrations already
create the LangGraph checkpoint tables used by the governance graph). Without
`OPS_ASSISTANT_CHECKPOINT_URL` the assistant keeps checkpoints in memory, so a pending approval is
lost when the process stops.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Checkpointer

CHECKPOINT_URL_ENV = "OPS_ASSISTANT_CHECKPOINT_URL"


def _endpoint(url: str) -> tuple[str, int]:
    parsed = urlsplit(url)
    return (parsed.hostname or "").lower(), parsed.port or 5432


def ops_assistant_checkpoint_url(environ: Mapping[str, str]) -> str | None:
    url = environ.get(CHECKPOINT_URL_ENV, "").strip()
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgresql", "postgres"} or not parsed.hostname:
        raise RuntimeError(f"{CHECKPOINT_URL_ENV} must be a psycopg postgresql:// URL")
    if not parsed.path.strip("/"):
        raise RuntimeError(f"{CHECKPOINT_URL_ENV} must name a database")
    ops_url = environ.get("OPS_DATABASE_URL", "").strip()
    if ops_url and _endpoint(ops_url) == _endpoint(url):
        raise RuntimeError(
            f"{CHECKPOINT_URL_ENV} points at the read-only ops database server; "
            "use a separate (local) database for checkpoints"
        )
    return url


@asynccontextmanager
async def ops_assistant_checkpointer(url: str | None) -> AsyncIterator[Checkpointer]:
    if url is None:
        yield InMemorySaver()
        return
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    # Alembic owns the checkpoint DDL in the application database; never call setup() here.
    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        yield saver
