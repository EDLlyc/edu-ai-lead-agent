from __future__ import annotations

from app.application.services.agent_retrieval import EnhancedAgentKnowledgeReader
from app.application.services.agent_tools import build_agent_tool_registry
from app.domain.agent_retrieval import AgentRetrievalKind, original_agent_query_plan
from app.infrastructure.agent_workbench_fixture import build_fixture_reader
from evals.agent_retrieval_live_ab.models import LiveAbCase


class _Planner:
    async def plan(self, *, query: str, retrieval_kind: AgentRetrievalKind):
        return original_agent_query_plan(query, retrieval_kind)


class _Reranker:
    async def rerank(self, *, query: str, documents: tuple[str, ...], limit: int):
        raise AssertionError("schema construction must not invoke the reranker")


def test_reader_enhancement_is_the_only_registry_variable() -> None:
    plain_reader = build_fixture_reader("evidence")
    enhanced_reader = EnhancedAgentKnowledgeReader(
        build_fixture_reader("evidence"),
        planner=_Planner(),
        reranker=_Reranker(),
    )

    plain = build_agent_tool_registry(plain_reader)
    enhanced = build_agent_tool_registry(enhanced_reader)

    assert plain.schema_hash == enhanced.schema_hash
    assert tuple(item.name for item in plain) == (
        "get_event",
        "retrieve_brand_context",
        "search_evidence",
        "validate_copy",
    )


def test_model_visible_case_schema_has_no_oracle_fields() -> None:
    properties = LiveAbCase.model_json_schema()["properties"]

    assert set(properties) == {
        "schema_version",
        "case_id",
        "category",
        "query",
        "retrieval_sensitive",
    }
    assert not {"qrels", "required_tools", "allowed_tools", "expected_terminal"} & set(properties)
