from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.agent_retrieval import AgentQueryPlanner, AgentTextReranker
from app.application.ports.agent_workbench import AgentKnowledgeReader, ToolCallingModel
from app.application.ports.brand_knowledge import BrandEmbeddingModel
from app.application.services.agent_retrieval import EnhancedAgentKnowledgeReader
from app.application.services.agent_tools import TypedToolRegistry, build_agent_tool_registry
from app.application.services.agent_workbench import AgentWorkbenchService
from app.domain.agent_workbench import AgentRunLimits
from app.infrastructure.agent_workbench_fixture import build_fixture_reader
from app.infrastructure.ai.agent_workbench import DeterministicPolicyToolCallingModel
from app.infrastructure.db.agent_workbench import PostgresAgentKnowledgeReader


def build_fixture_tool_registry(scenario_id: str | None = None) -> TypedToolRegistry:
    return build_agent_tool_registry(build_fixture_reader(scenario_id))


def build_postgres_agent_tool_registry(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    brand_embeddings: BrandEmbeddingModel,
    brand_retrieval_version: str,
    query_planner: AgentQueryPlanner | None = None,
    text_reranker: AgentTextReranker | None = None,
) -> TypedToolRegistry:
    """Compose the canonical tool registry over bounded PostgreSQL read projections."""

    if (query_planner is None) != (text_reranker is None):
        raise ValueError("agent retrieval planner and reranker must be configured together")
    reader: AgentKnowledgeReader = PostgresAgentKnowledgeReader(
        session_factory,
        brand_embeddings=brand_embeddings,
        brand_retrieval_version=brand_retrieval_version,
    )
    if query_planner is not None and text_reranker is not None:
        reader = EnhancedAgentKnowledgeReader(
            reader,
            planner=query_planner,
            reranker=text_reranker,
        )
    return build_agent_tool_registry(reader)


def build_fixture_agent_workbench(
    *,
    model_factory: Callable[[str], ToolCallingModel] | None = None,
    default_model_mode: str = "deterministic",
    allowed_model_modes: frozenset[str] | None = None,
    limits: AgentRunLimits | None = None,
) -> AgentWorkbenchService:
    resolved_factory = model_factory or _deterministic_model_factory
    return AgentWorkbenchService(
        registry_factory=build_fixture_tool_registry,
        model_factory=resolved_factory,
        default_model_mode=default_model_mode,
        allowed_model_modes=allowed_model_modes,
        limits=limits,
    )


def _deterministic_model_factory(mode: str) -> ToolCallingModel:
    if mode != "deterministic":
        raise ValueError("only deterministic mode is available in the fixture runtime")
    return DeterministicPolicyToolCallingModel()
