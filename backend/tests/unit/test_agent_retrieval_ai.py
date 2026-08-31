from __future__ import annotations

import json

import httpx
import pytest
from app.core.errors import InvalidProviderOutputError
from app.domain.agent_retrieval import (
    AgentQueryPlanSource,
    AgentRetrievalIntent,
    AgentRetrievalKind,
)
from app.infrastructure.ai.agent_retrieval import (
    ZhipuAgentQueryPlanner,
    ZhipuAgentTextReranker,
)
from pydantic import SecretStr

_SECRET = "zhipu-agent-retrieval-test-secret"


def _planner(transport: httpx.MockTransport) -> tuple[ZhipuAgentQueryPlanner, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=transport)
    return (
        ZhipuAgentQueryPlanner(
            client=client,
            base_url="https://open.bigmodel.cn/api/paas/v4",
            api_key=SecretStr(_SECRET),
            model="glm-5.2",
            connect_timeout_seconds=0.25,
            read_timeout_seconds=1,
            total_timeout_seconds=1.5,
            concurrency=1,
            max_attempts=1,
        ),
        client,
    )


def _reranker(
    transport: httpx.MockTransport,
) -> tuple[ZhipuAgentTextReranker, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=transport)
    return (
        ZhipuAgentTextReranker(
            client=client,
            base_url="https://open.bigmodel.cn/api/paas/v4",
            api_key=SecretStr(_SECRET),
            connect_timeout_seconds=0.25,
            read_timeout_seconds=1,
            total_timeout_seconds=1.5,
            concurrency=1,
            max_attempts=1,
        ),
        client,
    )


@pytest.mark.asyncio
async def test_zhipu_query_planner_uses_strict_json_and_disabled_thinking() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "rewritten_query": "真小班的班级人数和授课特点",
                                    "intent": "brand_explanation",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    planner, client = _planner(httpx.MockTransport(handler))
    try:
        result = await planner.plan(
            query="真小班有什么不一样?",
            retrieval_kind=AgentRetrievalKind.BRAND,
        )
    finally:
        await client.aclose()

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert captured["url"] == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert captured["authorization"] == f"Bearer {_SECRET}"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["do_sample"] is False
    assert payload["temperature"] == 0.0
    assert result.source is AgentQueryPlanSource.ZHIPU
    assert result.intent is AgentRetrievalIntent.BRAND_EXPLANATION
    assert result.rewritten_query == "真小班的班级人数和授课特点"


@pytest.mark.asyncio
async def test_zhipu_query_planner_rejects_semantic_drift() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "rewritten_query": "火星探测任务发射时间",
                                    "intent": "brand_explanation",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    planner, client = _planner(httpx.MockTransport(handler))
    try:
        with pytest.raises(InvalidProviderOutputError) as error:
            await planner.plan(
                query="真小班有什么不一样?",
                retrieval_kind=AgentRetrievalKind.BRAND,
            )
    finally:
        await client.aclose()

    assert error.value.issue_codes == ("agent_query_plan_semantic_drift",)


@pytest.mark.asyncio
async def test_zhipu_text_reranker_uses_dedicated_endpoint_and_validates_order() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.92},
                    {"index": 0, "relevance_score": 0.71},
                ]
            },
        )

    reranker, client = _reranker(httpx.MockTransport(handler))
    try:
        result = await reranker.rerank(
            query="人工智能教育安全",
            documents=("证据 A", "证据 B"),
            limit=2,
        )
    finally:
        await client.aclose()

    assert captured["url"] == "https://open.bigmodel.cn/api/paas/v4/rerank"
    assert captured["payload"] == {
        "model": "rerank",
        "query": "人工智能教育安全",
        "documents": ["证据 A", "证据 B"],
        "top_n": 2,
        "return_documents": False,
        "return_raw_scores": False,
    }
    assert tuple(item.index for item in result.items) == (1, 0)
    assert result.provider == "zhipu"
    assert result.model == "rerank"


@pytest.mark.asyncio
async def test_zhipu_text_reranker_rejects_duplicate_indexes() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.8},
                ]
            },
        )

    reranker, client = _reranker(httpx.MockTransport(handler))
    try:
        with pytest.raises(InvalidProviderOutputError) as error:
            await reranker.rerank(
                query="人工智能教育安全",
                documents=("证据 A", "证据 B"),
                limit=2,
            )
    finally:
        await client.aclose()

    assert error.value.issue_codes == ("agent_rerank_ranking_invalid",)
