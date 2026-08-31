from __future__ import annotations

import asyncio
import json

import pytest
from app.agent_workbench_runtime import (
    build_fixture_agent_workbench,
    build_fixture_tool_registry,
)
from app.application.ports.agent_workbench import (
    AgentModelFailure,
    AgentToolCall,
    FinalAnswerDecision,
    ModelDecisionMetadata,
    ModelDecisionRequest,
    ToolCallsDecision,
)
from app.application.services.agent_tools import ToolDefinition, TypedToolRegistry
from app.application.services.agent_workbench_graph import BoundedAgentRunner
from app.domain.agent_workbench import (
    AgentClaim,
    AgentClaimKind,
    AgentModelErrorCode,
    AgentRunStatus,
    ProposedAgentAnswer,
)
from app.infrastructure.agent_workbench_fixture import FIXTURE_EVIDENCE_ID
from app.infrastructure.ai.agent_workbench import RecordedToolCallingModel
from app.schemas.agent_workbench import SearchEvidenceArguments, SearchEvidenceResult
from pydantic import BaseModel


def _metadata() -> ModelDecisionMetadata:
    return ModelDecisionMetadata(provider="recorded", model="protocol-v1")


def _call(call_id: str, name: str, arguments: dict[str, object]) -> AgentToolCall:
    return AgentToolCall(
        call_id=call_id,
        name=name,
        arguments_json=json.dumps(arguments, separators=(",", ":"), sort_keys=True),
    )


@pytest.mark.asyncio
async def test_deterministic_fixture_run_is_grounded_and_redacted() -> None:
    query = "这条人工智能教育事件有哪些可靠证据? secret-do-not-trace"
    result = await build_fixture_agent_workbench().run(query, scenario_id="evidence")

    assert result.status is AgentRunStatus.COMPLETED
    assert result.metrics.model_turns == 2
    assert result.metrics.tool_calls == 1
    assert result.claims[0].citation_ids == (str(FIXTURE_EVIDENCE_ID),)
    assert result.citations[0].evidence_eligible is True
    serialized_trace = json.dumps(
        [
            {
                "kind": step.kind,
                "arguments": dict(step.safe_arguments),
                "code": step.code,
            }
            for step in result.steps
        ],
        ensure_ascii=False,
        default=str,
    )
    assert "secret-do-not-trace" not in serialized_trace
    assert "query_length" in serialized_trace
    assert "query_hash" in serialized_trace


@pytest.mark.asyncio
async def test_policy_refuses_side_effects_and_insufficient_evidence() -> None:
    service = build_fixture_agent_workbench()
    unsafe = await service.run("请发布到企微并发送给销售", scenario_id="evidence")
    insufficient = await service.run("火星小学有什么可靠证据?", scenario_id="insufficient")

    assert unsafe.status is AgentRunStatus.REFUSED
    assert unsafe.error_code == "policy_refused"
    assert unsafe.metrics.tool_calls == 0
    assert insufficient.status is AgentRunStatus.REFUSED
    assert insufficient.error_code == "insufficient_evidence"
    assert insufficient.metrics.tool_calls == 1


@pytest.mark.asyncio
async def test_unknown_and_invalid_tool_calls_are_observed_without_execution() -> None:
    decisions = (
        ToolCallsDecision(
            calls=(_call("call-1", "unregistered_tool", {}),),
            metadata=_metadata(),
        ),
        ToolCallsDecision(
            calls=(
                _call(
                    "call-2",
                    "search_evidence",
                    {"query": "", "limit": 99, "candidate_id": None},
                ),
            ),
            metadata=_metadata(),
        ),
        FinalAnswerDecision(
            answer=ProposedAgentAnswer(
                status="refused",
                summary="No safe tool result was available.",
                refusal_code="insufficient_evidence",
            ),
            metadata=_metadata(),
        ),
    )
    result = await BoundedAgentRunner(
        registry=build_fixture_tool_registry(),
        model=RecordedToolCallingModel(decisions),
    ).run("Test invalid tool calls")

    assert result.status is AgentRunStatus.REFUSED
    assert result.metrics.tool_calls == 2
    assert result.metrics.successful_tool_calls == 0
    codes = {step.code for step in result.steps}
    assert "agent_tool_unknown" in codes
    assert "agent_tool_invalid_arguments" in codes


@pytest.mark.asyncio
async def test_exact_four_calls_can_still_receive_final_synthesis() -> None:
    search_arguments = {"query": "人工智能教育", "limit": 1, "candidate_id": None}
    decisions = (
        ToolCallsDecision(
            calls=tuple(
                _call(f"call-{index}", "search_evidence", search_arguments) for index in range(1, 5)
            ),
            metadata=_metadata(),
        ),
        FinalAnswerDecision(
            answer=ProposedAgentAnswer(
                status="completed",
                summary="The evidence supports a bounded factual answer.",
                claims=(
                    AgentClaim(
                        text="The governed guidance requires safe supervised AI use.",
                        kind=AgentClaimKind.EXTERNAL_FACT,
                        citation_ids=(str(FIXTURE_EVIDENCE_ID),),
                    ),
                ),
            ),
            metadata=_metadata(),
        ),
    )
    result = await BoundedAgentRunner(
        registry=build_fixture_tool_registry(),
        model=RecordedToolCallingModel(decisions),
    ).run("Use four evidence calls and then synthesize")

    assert result.status is AgentRunStatus.COMPLETED
    assert result.metrics.tool_calls == 4
    assert result.metrics.model_turns == 2


@pytest.mark.asyncio
async def test_repeated_exact_tool_call_reuses_success_within_one_agent_run() -> None:
    executions = 0

    async def handler(_arguments: BaseModel) -> BaseModel:
        nonlocal executions
        executions += 1
        return SearchEvidenceResult()

    registry = TypedToolRegistry(
        (
            ToolDefinition(
                name="search_evidence",
                description="Read-only cache behavior test.",
                argument_model=SearchEvidenceArguments,
                result_model=SearchEvidenceResult,
                handler=handler,
            ),
        )
    )
    arguments = {"query": "人工智能教育", "limit": 1, "candidate_id": None}
    decisions = (
        ToolCallsDecision(
            calls=(
                _call("call-cache-1", "search_evidence", arguments),
                _call("call-cache-2", "search_evidence", arguments),
            ),
            metadata=_metadata(),
        ),
        FinalAnswerDecision(
            answer=ProposedAgentAnswer(
                status="refused",
                summary="No evidence was available.",
                refusal_code="insufficient_evidence",
            ),
            metadata=_metadata(),
        ),
    )

    result = await BoundedAgentRunner(
        registry=registry,
        model=RecordedToolCallingModel(decisions),
    ).run("Repeat one exact tool call")

    assert executions == 1
    assert result.metrics.tool_calls == 2
    assert result.metrics.successful_tool_calls == 2
    call_steps = [step for step in result.steps if step.kind.value == "tool_call"]
    assert [dict(step.safe_arguments)["cache_hit"] for step in call_steps] == [False, True]
    assert all(dict(step.safe_arguments)["cache_scope"] == "agent_run" for step in call_steps)


@pytest.mark.asyncio
async def test_four_model_turns_without_final_answer_exhaust_budget() -> None:
    decisions = tuple(
        ToolCallsDecision(
            calls=(
                _call(
                    f"call-{index}",
                    "search_evidence",
                    {"query": "人工智能教育", "limit": 1, "candidate_id": None},
                ),
            ),
            metadata=_metadata(),
        )
        for index in range(1, 5)
    )
    result = await BoundedAgentRunner(
        registry=build_fixture_tool_registry(),
        model=RecordedToolCallingModel(decisions),
    ).run("Never return a final answer")

    assert result.status is AgentRunStatus.BUDGET_EXHAUSTED
    assert result.error_code == "budget_exhausted"
    assert result.metrics.model_turns == 4
    assert result.metrics.tool_calls == 4


@pytest.mark.asyncio
async def test_invented_and_brand_as_fact_citations_are_rejected() -> None:
    invented = FinalAnswerDecision(
        answer=ProposedAgentAnswer(
            status="completed",
            summary="Unsupported answer",
            claims=(
                AgentClaim(
                    text="Invented fact",
                    kind=AgentClaimKind.EXTERNAL_FACT,
                    citation_ids=("invented-evidence",),
                ),
            ),
        ),
        metadata=_metadata(),
    )
    result = await BoundedAgentRunner(
        registry=build_fixture_tool_registry(),
        model=RecordedToolCallingModel((invented,)),
    ).run("Return an invented citation")

    assert result.status is AgentRunStatus.REFUSED
    assert result.error_code == "unsupported_citation"
    assert result.claims == ()
    assert result.citations == ()


class _FailingModel:
    async def decide(self, request: ModelDecisionRequest) -> FinalAnswerDecision:
        del request
        raise AgentModelFailure(AgentModelErrorCode.UNAVAILABLE)


class _CancelledModel:
    async def decide(self, request: ModelDecisionRequest) -> FinalAnswerDecision:
        del request
        raise asyncio.CancelledError


@pytest.mark.asyncio
async def test_provider_failure_and_cancellation_are_typed_terminal_results() -> None:
    failed = await BoundedAgentRunner(
        registry=build_fixture_tool_registry(),
        model=_FailingModel(),
    ).run("Provider failure")
    cancelled = await BoundedAgentRunner(
        registry=build_fixture_tool_registry(),
        model=_CancelledModel(),
    ).run("Cancellation")

    assert failed.status is AgentRunStatus.FAILED
    assert failed.error_code == "agent_model_unavailable"
    assert cancelled.status is AgentRunStatus.CANCELLED
    assert cancelled.error_code == "cancelled"
