"""Local stdio MCP server for the read-only operations tools.

It connects only through OPS_DATABASE_URL (a dedicated SELECT-only role, reached through an SSH
tunnel for production; see scripts/ops) and never through the application's DATABASE_URL. On
start it checks that the role cannot write and refuses to serve otherwise.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server import MCPServer
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.application.services.ops_tools import (
    OPS_TOOL_RULES,
    OPS_TOOLSET_VERSION,
    OpsReader,
    build_ops_tool_registry,
)
from app.infrastructure.db.ops_reader import (
    PostgresOpsReader,
    create_ops_engine,
    ops_database_url,
    verify_read_only_role,
)
from app.mcp_registry_server import (
    DEFAULT_MCP_CALL_BUDGET,
    CallLogger,
    RegistryMCPServer,
    call_budget_from_environment,
    stderr_json_logger,
)

MCP_SERVER_NAME = "edu-ai-ops"
OPS_INSTRUCTIONS = OPS_TOOL_RULES + "\n每个服务进程有调用次数上限。"


def build_ops_mcp_server(
    reader: OpsReader,
    *,
    engine: AsyncEngine | None = None,
    call_budget: int = DEFAULT_MCP_CALL_BUDGET,
    call_logger: CallLogger | None = stderr_json_logger,
) -> RegistryMCPServer:
    @asynccontextmanager
    async def lifespan(_server: MCPServer[None]) -> AsyncIterator[None]:
        if engine is None:
            yield
            return
        try:
            role = await verify_read_only_role(engine)
            if call_logger is not None:
                call_logger({"event": "ops_mcp_ready", "role": role})
            yield
        finally:
            await engine.dispose()

    return RegistryMCPServer(
        build_ops_tool_registry(reader),
        name=MCP_SERVER_NAME,
        title="Read-only Operations Tools",
        description="Slot runs, copy runs and WeCom deliveries, read through a SELECT-only role.",
        instructions=OPS_INSTRUCTIONS,
        version=OPS_TOOLSET_VERSION,
        call_budget=call_budget,
        call_logger=call_logger,
        lifespan=lifespan,
    )


def main() -> None:
    engine = create_ops_engine(ops_database_url(os.environ))
    reader = PostgresOpsReader(async_sessionmaker(engine, expire_on_commit=False))
    build_ops_mcp_server(
        reader, engine=engine, call_budget=call_budget_from_environment(os.environ)
    ).run(transport="stdio")


if __name__ == "__main__":
    main()
