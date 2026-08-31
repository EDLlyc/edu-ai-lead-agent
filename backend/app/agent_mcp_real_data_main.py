"""Development-only STDIO MCP adapter over governed local PostgreSQL projections."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
from mcp.server import MCPServer
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent_mcp_main import AgentWorkbenchMCPServer, build_agent_mcp_server
from app.agent_workbench_runtime import build_postgres_agent_tool_registry
from app.application.services.agent_retrieval import CachedBrandEmbeddingModel
from app.application.services.agent_tools import TypedToolRegistry
from app.core.agent_workbench_config import (
    AgentWorkbenchSettings,
    get_agent_workbench_settings,
)
from app.core.config import Settings, get_settings
from app.infrastructure.ai.agent_retrieval import (
    ZhipuAgentQueryPlanner,
    ZhipuAgentTextReranker,
)
from app.infrastructure.ai.factory import create_brand_embedding_model
from app.infrastructure.db.session import create_engine, create_session_factory

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PLANNER_CONNECT_TIMEOUT_SECONDS = 0.5
_PLANNER_READ_TIMEOUT_SECONDS = 1.75
_PLANNER_TOTAL_TIMEOUT_SECONDS = 2.0
_RERANK_CONNECT_TIMEOUT_SECONDS = 0.5
_RERANK_READ_TIMEOUT_SECONDS = 0.75
_RERANK_TOTAL_TIMEOUT_SECONDS = 1.0


@dataclass(slots=True)
class _RealDataMCPResources:
    engine: AsyncEngine
    embedding_client: httpx.AsyncClient

    @asynccontextmanager
    async def lifespan(self, _server: MCPServer[None]) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await self.embedding_client.aclose()
            await self.engine.dispose()


def validate_real_data_mcp_settings(
    workbench_settings: AgentWorkbenchSettings,
    application_settings: Settings,
) -> None:
    """Fail closed before this local-only process can compose real data access."""

    if workbench_settings.app_env != "development" or application_settings.app_env != "development":
        raise RuntimeError("real-data agent MCP is development-only")
    if not workbench_settings.agent_mcp_real_data_enabled:
        raise RuntimeError("real-data agent MCP requires explicit enablement")
    if workbench_settings.agent_mcp_data_mode != "postgres":
        raise RuntimeError("real-data agent MCP requires postgres data mode")
    if application_settings.ai_provider_mode != "zhipu":
        raise RuntimeError("real-data agent MCP requires configured Zhipu planning and reranking")
    if application_settings.resolved_brand_embedding_provider_mode != "alibaba":
        raise RuntimeError("real-data agent MCP requires Alibaba multimodal brand embedding")
    api_key = application_settings.ai_platform_api_key
    if (
        application_settings.ai_platform_base_url is None
        or api_key is None
        or not api_key.get_secret_value().strip()
    ):
        raise RuntimeError("real-data agent MCP requires configured Zhipu credentials")


def build_real_data_mcp_server(
    registry: TypedToolRegistry,
    *,
    engine: AsyncEngine,
    embedding_client: httpx.AsyncClient,
) -> AgentWorkbenchMCPServer:
    """Attach owned real-data resources to the canonical MCP adapter lifecycle."""

    resources = _RealDataMCPResources(engine=engine, embedding_client=embedding_client)
    return build_agent_mcp_server(registry, lifespan=resources.lifespan)


def create_real_data_mcp_server(
    *,
    workbench_settings: AgentWorkbenchSettings | None = None,
    application_settings: Settings | None = None,
) -> AgentWorkbenchMCPServer:
    """Compose the development database reader without changing fixture MCP defaults."""

    resolved_workbench_settings = workbench_settings or get_agent_workbench_settings()
    resolved_application_settings = application_settings or get_settings()
    validate_real_data_mcp_settings(resolved_workbench_settings, resolved_application_settings)

    engine = create_engine(resolved_application_settings)
    embedding_client = httpx.AsyncClient(follow_redirects=False)
    brand_embeddings = CachedBrandEmbeddingModel(
        create_brand_embedding_model(
            resolved_application_settings,
            client=embedding_client,
        ),
        cache_namespace=":".join(
            (
                resolved_application_settings.brand_embedding_provider,
                resolved_application_settings.brand_embedding_model,
                resolved_application_settings.brand_embedding_input_version,
            )
        ),
    )
    base_url = resolved_application_settings.ai_platform_base_url
    api_key = resolved_application_settings.ai_platform_api_key
    assert base_url is not None and api_key is not None
    query_planner = ZhipuAgentQueryPlanner(
        client=embedding_client,
        base_url=base_url,
        api_key=api_key,
        model=resolved_application_settings.ai_chat_model,
        connect_timeout_seconds=_PLANNER_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds=_PLANNER_READ_TIMEOUT_SECONDS,
        total_timeout_seconds=_PLANNER_TOTAL_TIMEOUT_SECONDS,
        concurrency=min(resolved_application_settings.ai_provider_concurrency, 2),
        max_attempts=1,
    )
    text_reranker = ZhipuAgentTextReranker(
        client=embedding_client,
        base_url=base_url,
        api_key=api_key,
        connect_timeout_seconds=_RERANK_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds=_RERANK_READ_TIMEOUT_SECONDS,
        total_timeout_seconds=_RERANK_TOTAL_TIMEOUT_SECONDS,
        concurrency=min(resolved_application_settings.ai_provider_concurrency, 2),
        max_attempts=1,
    )
    registry = build_postgres_agent_tool_registry(
        create_session_factory(engine),
        brand_embeddings=brand_embeddings,
        brand_retrieval_version=resolved_application_settings.brand_retrieval_version,
        query_planner=query_planner,
        text_reranker=text_reranker,
    )
    return build_real_data_mcp_server(
        registry,
        engine=engine,
        embedding_client=embedding_client,
    )


def main() -> None:
    """Run the real-data MCP server over local stdio only."""

    os.chdir(_PROJECT_ROOT)
    create_real_data_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()
