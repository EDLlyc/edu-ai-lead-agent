from __future__ import annotations

import json

import httpx
import pytest
from app.agent_workbench_runtime import build_fixture_tool_registry
from app.application.ports.agent_workbench import (
    AgentModelFailure,
    FinalAnswerDecision,
    ModelDecisionRequest,
    ToolCallsDecision,
)
from app.domain.agent_workbench import AgentModelErrorCode
from app.infrastructure.ai.agent_workbench import OpenAICompatibleToolCallingModel
from pydantic import SecretStr


def _request() -> ModelDecisionRequest:
    return ModelDecisionRequest(
        query="Find governed AI education evidence",
        tools=build_fixture_tool_registry().model_tool_schemas(),
        history=(),
    )


@pytest.mark.asyncio
async def test_openai_compatible_adapter_sends_canonical_tools_and_parses_usage() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_evidence",
                                        "arguments": json.dumps(
                                            {
                                                "query": "AI education",
                                                "limit": 3,
                                                "candidate_id": None,
                                            }
                                        ),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 21,
                    "completion_tokens": 7,
                    "completion_tokens_details": {"reasoning_tokens": 2},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAICompatibleToolCallingModel(
            client=client,
            base_url="https://api.example.com/v1",
            api_key=SecretStr("test-only-key"),
            model="test-model",
        )
        decision = await adapter.decide(_request())

    assert isinstance(decision, ToolCallsDecision)
    assert decision.calls[0].name == "search_evidence"
    assert decision.metadata.prompt_tokens == 21
    assert decision.metadata.reasoning_tokens == 2
    payload = captured["payload"]
    assert isinstance(payload, dict)
    tools = payload["tools"]
    assert isinstance(tools, list)
    assert [tool["function"]["name"] for tool in tools] == [
        "get_event",
        "retrieve_brand_context",
        "search_evidence",
        "validate_copy",
    ]
    assert all(tool["function"]["strict"] is True for tool in tools)
    assert captured["authorization"] == "Bearer test-only-key"


@pytest.mark.asyncio
async def test_openai_compatible_adapter_parses_bounded_final_answer() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "status": "refused",
                                    "summary": "Insufficient governed evidence.",
                                    "claims": [],
                                    "refusal_code": "insufficient_evidence",
                                }
                            )
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        decision = await OpenAICompatibleToolCallingModel(
            client=client,
            base_url="https://api.example.com/v1",
            model="test-model",
        ).decide(_request())

    assert isinstance(decision, FinalAnswerDecision)
    assert decision.answer.status == "refused"
    assert decision.answer.refusal_code == "insufficient_evidence"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    (
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "same-id",
                    "type": "function",
                    "function": {"name": "search_evidence", "arguments": "{}"},
                },
                {
                    "id": "same-id",
                    "type": "function",
                    "function": {"name": "get_event", "arguments": "{}"},
                },
            ],
        },
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "write_database", "arguments": "{}"},
                }
            ],
        },
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "search_evidence",
                        "arguments": '{"query":"ok","query":"duplicate"}',
                    },
                }
            ],
        },
    ),
)
async def test_openai_compatible_adapter_rejects_malformed_tool_calls(
    message: dict[str, object],
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": message}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAICompatibleToolCallingModel(
            client=client,
            base_url="https://api.example.com/v1",
            model="test-model",
        )
        with pytest.raises(AgentModelFailure) as error:
            await adapter.decide(_request())
    assert error.value.code is AgentModelErrorCode.INVALID_OUTPUT


@pytest.mark.asyncio
async def test_openai_compatible_adapter_bounds_response_and_projects_http_failure() -> None:
    async def oversized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 2_000)

    async with httpx.AsyncClient(transport=httpx.MockTransport(oversized)) as client:
        adapter = OpenAICompatibleToolCallingModel(
            client=client,
            base_url="https://api.example.com/v1",
            model="test-model",
            max_response_bytes=1_024,
        )
        with pytest.raises(AgentModelFailure) as too_large:
            await adapter.decide(_request())
    assert too_large.value.code is AgentModelErrorCode.INVALID_OUTPUT

    async def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"provider body must not escape")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as client:
        adapter = OpenAICompatibleToolCallingModel(
            client=client,
            base_url="https://api.example.com/v1",
            model="test-model",
        )
        with pytest.raises(AgentModelFailure) as failed:
            await adapter.decide(_request())
    assert failed.value.code is AgentModelErrorCode.UNAVAILABLE
    assert "provider body" not in str(failed.value)


@pytest.mark.parametrize(
    "base_url",
    (
        "http://api.example.com/v1",
        "http://10.0.0.1/v1",
        "https://" + "fixture-user@" + "example.com/v1",
    ),
)
def test_openai_compatible_adapter_rejects_unsafe_base_urls(base_url: str) -> None:
    client = httpx.AsyncClient()
    try:
        with pytest.raises(ValueError, match="base URL"):
            OpenAICompatibleToolCallingModel(
                client=client,
                base_url=base_url,
                model="test-model",
            )
    finally:
        # No transport call occurs; close in a short standalone loop-free helper below.
        import asyncio

        asyncio.run(client.aclose())
