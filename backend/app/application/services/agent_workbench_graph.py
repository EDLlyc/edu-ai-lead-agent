from __future__ import annotations

import asyncio
import json
from concurrent.futures import CancelledError as FutureCancelledError
from time import monotonic
from typing import Literal, TypedDict, cast
from uuid import UUID, uuid4

from langgraph.errors import NodeCancelledError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from app.application.ports.agent_workbench import (
    AgentModelFailure,
    AgentToolCall,
    AgentToolExchange,
    AgentToolObservation,
    FinalAnswerDecision,
    ModelDecisionRequest,
    MonotonicClock,
    ToolCallingModel,
)
from app.application.services.agent_tools import (
    AgentToolFailure,
    TypedToolRegistry,
)
from app.core.security import is_public_https_url
from app.domain.agent_workbench import (
    AgentCitation,
    AgentCitationKind,
    AgentClaim,
    AgentClaimKind,
    AgentModelErrorCode,
    AgentRunLimits,
    AgentRunMetrics,
    AgentRunResult,
    AgentRunStatus,
    AgentToolErrorCode,
    AgentTraceKind,
    AgentTraceStatus,
    AgentTraceStep,
    ProposedAgentAnswer,
    SafeTraceValue,
)
from app.schemas.agent_workbench import (
    GetEventResult,
    RetrieveBrandContextResult,
    SearchEvidenceResult,
    ValidateCopyResult,
)


class SystemMonotonicClock:
    def monotonic(self) -> float:
        return monotonic()


class AgentWorkbenchGraphState(TypedDict, total=False):
    query: str
    run_id: str
    started_at: float
    model_turns: int
    tool_calls: int
    successful_tool_calls: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    model_latency_ms: int
    tool_latency_ms: int
    history: tuple[AgentToolExchange, ...]
    current_calls: tuple[AgentToolCall, ...]
    current_observations: tuple[AgentToolObservation, ...]
    pending_calls: tuple[AgentToolCall, ...]
    steps: tuple[AgentTraceStep, ...]
    proposed_answer: ProposedAgentAnswer
    terminal_status: AgentRunStatus
    terminal_summary: str
    terminal_claims: tuple[AgentClaim, ...]
    terminal_citations: tuple[AgentCitation, ...]
    error_code: str


CompiledAgentWorkbenchGraph = CompiledStateGraph[
    AgentWorkbenchGraphState,
    None,
    AgentWorkbenchGraphState,
    AgentWorkbenchGraphState,
]


class BoundedAgentRunner:
    def __init__(
        self,
        *,
        registry: TypedToolRegistry,
        model: ToolCallingModel,
        limits: AgentRunLimits | None = None,
        clock: MonotonicClock | None = None,
    ) -> None:
        self._registry = registry
        self._model = model
        self._limits = limits or AgentRunLimits()
        self._clock = clock or SystemMonotonicClock()
        self._graph = self._build_graph()

    @property
    def registry(self) -> TypedToolRegistry:
        return self._registry

    async def run(self, query: str, *, run_id: UUID | None = None) -> AgentRunResult:
        normalized_query = query.strip()
        if not normalized_query or len(normalized_query) > 500:
            raise ValueError("agent workbench query must be 1-500 characters")
        resolved_run_id = run_id or uuid4()
        initial = AgentWorkbenchGraphState(
            query=normalized_query,
            run_id=str(resolved_run_id),
            started_at=self._clock.monotonic(),
            model_turns=0,
            tool_calls=0,
            successful_tool_calls=0,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            model_latency_ms=0,
            tool_latency_ms=0,
            history=(),
            current_calls=(),
            current_observations=(),
            pending_calls=(),
            steps=(),
            terminal_claims=(),
            terminal_citations=(),
        )
        try:
            final = await self._graph.ainvoke(
                initial,
                config={"recursion_limit": self._limits.recursion_limit},
            )
        except (asyncio.CancelledError, FutureCancelledError, NodeCancelledError):
            return self._cancelled_result(resolved_run_id, initial)
        except Exception:
            failed = _terminal_state(
                initial,
                status=AgentRunStatus.FAILED,
                summary="Agent workbench execution failed safely.",
                error_code=AgentModelErrorCode.UNAVAILABLE.value,
            )
            return self._result_from_state(resolved_run_id, failed)
        return self._result_from_state(
            resolved_run_id,
            cast(AgentWorkbenchGraphState, final),
        )

    def _build_graph(self) -> CompiledAgentWorkbenchGraph:
        builder = StateGraph(AgentWorkbenchGraphState)
        builder.add_node("model_decision", self._model_decision_node)
        builder.add_node("execute_tool", self._execute_tool_node)
        builder.add_node("finalize", self._finalize_node)
        builder.add_edge(START, "model_decision")
        builder.add_conditional_edges(
            "model_decision",
            _route_after_model,
            {"execute_tool": "execute_tool", "finalize": "finalize", "end": END},
        )
        builder.add_conditional_edges(
            "execute_tool",
            _route_after_tool,
            {"execute_tool": "execute_tool", "model_decision": "model_decision", "end": END},
        )
        builder.add_edge("finalize", END)
        return builder.compile()

    async def _model_decision_node(
        self,
        state: AgentWorkbenchGraphState,
    ) -> AgentWorkbenchGraphState:
        if _deadline_exhausted(state, self._limits, self._clock):
            return _budget_exhausted(state)
        model_turns = state["model_turns"]
        if model_turns >= self._limits.max_model_turns:
            return _budget_exhausted(state)
        remaining_seconds = _remaining_seconds(state, self._limits, self._clock)
        request = ModelDecisionRequest(
            query=state["query"],
            tools=self._registry.model_tool_schemas(),
            history=state["history"],
        )
        try:
            async with asyncio.timeout(min(self._limits.model_timeout_seconds, remaining_seconds)):
                decision = await self._model.decide(request)
        except TimeoutError:
            return _model_failure_state(state, AgentModelErrorCode.UNAVAILABLE)
        except asyncio.CancelledError:
            raise
        except AgentModelFailure as error:
            return _model_failure_state(state, error.code)
        except (RuntimeError, TypeError, ValueError):
            return _model_failure_state(state, AgentModelErrorCode.INVALID_OUTPUT)

        metadata = decision.metadata
        next_state = AgentWorkbenchGraphState(
            model_turns=model_turns + 1,
            prompt_tokens=state["prompt_tokens"] + metadata.prompt_tokens,
            completion_tokens=state["completion_tokens"] + metadata.completion_tokens,
            reasoning_tokens=state["reasoning_tokens"] + metadata.reasoning_tokens,
            model_latency_ms=state["model_latency_ms"] + metadata.latency_ms,
        )
        if isinstance(decision, FinalAnswerDecision):
            next_state["proposed_answer"] = decision.answer
            next_state["steps"] = _append_step(
                state,
                AgentTraceStep(
                    ordinal=len(state["steps"]) + 1,
                    kind=AgentTraceKind.MODEL_DECISION,
                    status=AgentTraceStatus.SUCCEEDED,
                    item_count=len(decision.answer.claims),
                    provider=metadata.provider,
                    model=metadata.model,
                    duration_ms=metadata.latency_ms,
                    prompt_tokens=metadata.prompt_tokens,
                    completion_tokens=metadata.completion_tokens,
                    reasoning_tokens=metadata.reasoning_tokens,
                ),
            )
            return next_state

        remaining_calls = self._limits.max_tool_calls - state["tool_calls"]
        previous_ids = {call.call_id for exchange in state["history"] for call in exchange.calls}
        if len(decision.calls) > remaining_calls or any(
            call.call_id in previous_ids for call in decision.calls
        ):
            merged = AgentWorkbenchGraphState(**state)
            merged.update(next_state)
            return (
                _budget_exhausted(merged)
                if len(decision.calls) > remaining_calls
                else _model_failure_state(merged, AgentModelErrorCode.INVALID_OUTPUT)
            )
        next_state["current_calls"] = decision.calls
        next_state["current_observations"] = ()
        next_state["pending_calls"] = decision.calls
        next_state["steps"] = _append_step(
            state,
            AgentTraceStep(
                ordinal=len(state["steps"]) + 1,
                kind=AgentTraceKind.MODEL_DECISION,
                status=AgentTraceStatus.SUCCEEDED,
                item_count=len(decision.calls),
                provider=metadata.provider,
                model=metadata.model,
                duration_ms=metadata.latency_ms,
                prompt_tokens=metadata.prompt_tokens,
                completion_tokens=metadata.completion_tokens,
                reasoning_tokens=metadata.reasoning_tokens,
            ),
        )
        return next_state

    async def _execute_tool_node(
        self,
        state: AgentWorkbenchGraphState,
    ) -> AgentWorkbenchGraphState:
        if _deadline_exhausted(state, self._limits, self._clock):
            return _budget_exhausted(state)
        pending = state["pending_calls"]
        if not pending or state["tool_calls"] >= self._limits.max_tool_calls:
            return _budget_exhausted(state)
        call = pending[0]
        tool_calls = state["tool_calls"] + 1
        argument_summary = self._argument_summary(call)
        call_step = AgentTraceStep(
            ordinal=len(state["steps"]) + 1,
            kind=AgentTraceKind.TOOL_CALL,
            status=AgentTraceStatus.SUCCEEDED,
            tool_name=call.name,
            call_id=call.call_id,
            safe_arguments=argument_summary,
        )
        started_at = self._clock.monotonic()
        result: BaseModel | None = None
        failure: AgentToolFailure | None = None
        try:
            async with asyncio.timeout(_remaining_seconds(state, self._limits, self._clock)):
                result = await self._registry.invoke(call.name, call.arguments_json)
        except TimeoutError:
            failure = AgentToolFailure(AgentToolErrorCode.TIMEOUT)
        except asyncio.CancelledError:
            raise
        except AgentToolFailure as error:
            failure = error
        duration_ms = max(0, int((self._clock.monotonic() - started_at) * 1_000))
        if failure is None and result is not None:
            content_json = result.model_dump_json()
            observation = AgentToolObservation(
                call_id=call.call_id,
                name=call.name,
                status="succeeded",
                content_json=content_json,
            )
            item_count, issue_count, citation_ids = _result_projection(result)
            result_step = AgentTraceStep(
                ordinal=call_step.ordinal + 1,
                kind=AgentTraceKind.TOOL_RESULT,
                status=AgentTraceStatus.SUCCEEDED,
                tool_name=call.name,
                call_id=call.call_id,
                duration_ms=duration_ms,
                item_count=item_count,
                issue_count=issue_count,
                citation_ids=citation_ids,
            )
            successful_tool_calls = state["successful_tool_calls"] + 1
        else:
            resolved_failure = failure or AgentToolFailure(AgentToolErrorCode.UNAVAILABLE)
            content_json = json.dumps(
                {
                    "error": {
                        "code": resolved_failure.code.value,
                        "message": resolved_failure.safe_message,
                    }
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            observation = AgentToolObservation(
                call_id=call.call_id,
                name=call.name,
                status="failed",
                content_json=content_json,
                error_code=resolved_failure.code.value,
            )
            result_step = AgentTraceStep(
                ordinal=call_step.ordinal + 1,
                kind=AgentTraceKind.TOOL_RESULT,
                status=AgentTraceStatus.FAILED,
                code=resolved_failure.code.value,
                tool_name=call.name,
                call_id=call.call_id,
                duration_ms=duration_ms,
            )
            successful_tool_calls = state["successful_tool_calls"]

        observations = (*state["current_observations"], observation)
        remaining_pending = pending[1:]
        next_state = AgentWorkbenchGraphState(
            tool_calls=tool_calls,
            successful_tool_calls=successful_tool_calls,
            tool_latency_ms=state["tool_latency_ms"] + duration_ms,
            current_observations=observations,
            pending_calls=remaining_pending,
            steps=(*state["steps"], call_step, result_step),
        )
        if not remaining_pending:
            next_state["history"] = (
                *state["history"],
                AgentToolExchange(
                    calls=state["current_calls"],
                    observations=observations,
                ),
            )
            next_state["current_calls"] = ()
            next_state["current_observations"] = ()
        return next_state

    async def _finalize_node(
        self,
        state: AgentWorkbenchGraphState,
    ) -> AgentWorkbenchGraphState:
        proposed = state["proposed_answer"]
        if proposed.status == "refused":
            status = AgentRunStatus.REFUSED
            summary = proposed.summary
            claims: tuple[AgentClaim, ...] = ()
            citations: tuple[AgentCitation, ...] = ()
            error_code: str | None = proposed.refusal_code or "policy_refused"
        else:
            status, summary, claims, citations, error_code = _validated_final_answer(
                proposed,
                state["history"],
            )
        step = AgentTraceStep(
            ordinal=len(state["steps"]) + 1,
            kind=AgentTraceKind.FINAL,
            status=(
                AgentTraceStatus.SUCCEEDED
                if status is AgentRunStatus.COMPLETED
                else AgentTraceStatus.FAILED
            ),
            code=error_code,
            item_count=len(claims),
            citation_ids=tuple(citation.id for citation in citations),
        )
        result = AgentWorkbenchGraphState(
            terminal_status=status,
            terminal_summary=summary,
            terminal_claims=claims,
            terminal_citations=citations,
            steps=(*state["steps"], step),
        )
        if error_code is not None:
            result["error_code"] = error_code
        return result

    def _argument_summary(
        self,
        call: AgentToolCall,
    ) -> tuple[tuple[str, SafeTraceValue], ...]:
        try:
            return self._registry.summarize_arguments(call.name, call.arguments_json)
        except AgentToolFailure:
            return (("argument_bytes", len(call.arguments_json.encode("utf-8"))),)

    def _cancelled_result(
        self,
        run_id: UUID,
        state: AgentWorkbenchGraphState,
    ) -> AgentRunResult:
        cancelled = _terminal_state(
            state,
            status=AgentRunStatus.CANCELLED,
            summary="Agent workbench execution was cancelled.",
            error_code="cancelled",
        )
        return self._result_from_state(run_id, cancelled)

    def _result_from_state(
        self,
        run_id: UUID,
        state: AgentWorkbenchGraphState,
    ) -> AgentRunResult:
        if "terminal_status" not in state:
            state = _terminal_state(
                state,
                status=AgentRunStatus.FAILED,
                summary="Agent workbench execution ended without a terminal result.",
                error_code=AgentModelErrorCode.INVALID_OUTPUT.value,
            )
        duration_ms = max(0, int((self._clock.monotonic() - state["started_at"]) * 1_000))
        return AgentRunResult(
            run_id=run_id,
            status=state["terminal_status"],
            summary=state["terminal_summary"],
            claims=state.get("terminal_claims", ()),
            citations=state.get("terminal_citations", ()),
            steps=state["steps"],
            metrics=AgentRunMetrics(
                model_turns=state["model_turns"],
                tool_calls=state["tool_calls"],
                successful_tool_calls=state["successful_tool_calls"],
                prompt_tokens=state["prompt_tokens"],
                completion_tokens=state["completion_tokens"],
                reasoning_tokens=state["reasoning_tokens"],
                model_latency_ms=state["model_latency_ms"],
                tool_latency_ms=state["tool_latency_ms"],
                duration_ms=duration_ms,
            ),
            error_code=state.get("error_code"),
        )


def _route_after_model(
    state: AgentWorkbenchGraphState,
) -> Literal["execute_tool", "finalize", "end"]:
    if "terminal_status" in state:
        return "end"
    if "proposed_answer" in state:
        return "finalize"
    if state.get("pending_calls"):
        return "execute_tool"
    return "end"


def _route_after_tool(
    state: AgentWorkbenchGraphState,
) -> Literal["execute_tool", "model_decision", "end"]:
    if "terminal_status" in state:
        return "end"
    if state.get("pending_calls"):
        return "execute_tool"
    return "model_decision"


def _remaining_seconds(
    state: AgentWorkbenchGraphState,
    limits: AgentRunLimits,
    clock: MonotonicClock,
) -> float:
    return max(0.001, limits.total_timeout_seconds - (clock.monotonic() - state["started_at"]))


def _deadline_exhausted(
    state: AgentWorkbenchGraphState,
    limits: AgentRunLimits,
    clock: MonotonicClock,
) -> bool:
    return clock.monotonic() - state["started_at"] >= limits.total_timeout_seconds


def _append_step(
    state: AgentWorkbenchGraphState,
    step: AgentTraceStep,
) -> tuple[AgentTraceStep, ...]:
    return (*state["steps"], step)


def _model_failure_state(
    state: AgentWorkbenchGraphState,
    code: AgentModelErrorCode,
) -> AgentWorkbenchGraphState:
    return _terminal_state(
        state,
        status=AgentRunStatus.FAILED,
        summary="The model could not produce a safe structured decision.",
        error_code=code.value,
    )


def _budget_exhausted(state: AgentWorkbenchGraphState) -> AgentWorkbenchGraphState:
    return _terminal_state(
        state,
        status=AgentRunStatus.BUDGET_EXHAUSTED,
        summary="The bounded agent budget was exhausted before a final answer was accepted.",
        error_code="budget_exhausted",
    )


def _terminal_state(
    state: AgentWorkbenchGraphState,
    *,
    status: AgentRunStatus,
    summary: str,
    error_code: str,
) -> AgentWorkbenchGraphState:
    if "terminal_status" in state:
        return state
    step = AgentTraceStep(
        ordinal=len(state["steps"]) + 1,
        kind=AgentTraceKind.ERROR,
        status=AgentTraceStatus.FAILED,
        code=error_code,
    )
    result = AgentWorkbenchGraphState(**state)
    result["terminal_status"] = status
    result["terminal_summary"] = summary
    result["terminal_claims"] = ()
    result["terminal_citations"] = ()
    result["error_code"] = error_code
    result["steps"] = (*state["steps"], step)
    return result


def _result_projection(result: BaseModel) -> tuple[int | None, int | None, tuple[str, ...]]:
    if isinstance(result, SearchEvidenceResult):
        return len(result.items), None, tuple(str(item.evidence_id) for item in result.items)
    if isinstance(result, RetrieveBrandContextResult):
        return len(result.items), None, tuple(str(item.chunk_id) for item in result.items)
    if isinstance(result, GetEventResult):
        return len(result.members), None, ()
    if isinstance(result, ValidateCopyResult):
        return None, len(result.issues), ()
    return None, None, ()


def _validated_final_answer(
    proposed: ProposedAgentAnswer,
    history: tuple[AgentToolExchange, ...],
) -> tuple[
    AgentRunStatus,
    str,
    tuple[AgentClaim, ...],
    tuple[AgentCitation, ...],
    str | None,
]:
    candidates, conflicting_ids = _citation_candidates(history)
    if conflicting_ids:
        return _unsupported_answer()
    used_ids: list[str] = []
    for claim in proposed.claims:
        if claim.kind is AgentClaimKind.EXTERNAL_FACT:
            if not claim.citation_ids:
                return _insufficient_answer()
            if any(
                citation_id not in candidates
                or candidates[citation_id].kind is not AgentCitationKind.EVIDENCE
                or not candidates[citation_id].evidence_eligible
                for citation_id in claim.citation_ids
            ):
                return _unsupported_answer()
        elif claim.kind is AgentClaimKind.BRAND_STATEMENT:
            if not claim.citation_ids or any(
                citation_id not in candidates
                or candidates[citation_id].kind is not AgentCitationKind.BRAND_CONTEXT
                or candidates[citation_id].evidence_eligible
                for citation_id in claim.citation_ids
            ):
                return _unsupported_answer()
        elif claim.citation_ids:
            return _unsupported_answer()
        for citation_id in claim.citation_ids:
            if citation_id not in used_ids:
                used_ids.append(citation_id)
    if len(used_ids) > 20:
        return _unsupported_answer()
    return (
        AgentRunStatus.COMPLETED,
        proposed.summary,
        proposed.claims,
        tuple(candidates[citation_id] for citation_id in used_ids),
        None,
    )


def _citation_candidates(
    history: tuple[AgentToolExchange, ...],
) -> tuple[dict[str, AgentCitation], set[str]]:
    candidates: dict[str, AgentCitation] = {}
    conflicts: set[str] = set()
    for exchange in history:
        for observation in exchange.observations:
            if observation.status != "succeeded":
                continue
            try:
                raw = json.loads(observation.content_json)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            raw_items = raw.get("items")
            if not isinstance(raw_items, list):
                continue
            for item in raw_items:
                citation = _citation_from_item(observation.name, item)
                if citation is None:
                    continue
                existing = candidates.get(citation.id)
                if existing is not None and existing != citation:
                    conflicts.add(citation.id)
                else:
                    candidates[citation.id] = citation
    return candidates, conflicts


def _citation_from_item(tool_name: str, raw: object) -> AgentCitation | None:
    if not isinstance(raw, dict):
        return None
    try:
        if tool_name == "search_evidence":
            evidence_id = _required_string(raw, "evidence_id", 80)
            url = _required_string(raw, "url", 2_000)
            if not _is_safe_https_url(url) or raw.get("evidence_eligible") is not True:
                return None
            return AgentCitation(
                id=evidence_id,
                kind=AgentCitationKind.EVIDENCE,
                source_name=_required_string(raw, "source_name", 120),
                title=_required_string(raw, "title", 200),
                url=url,
                evidence_eligible=True,
            )
        if tool_name == "retrieve_brand_context":
            if raw.get("evidence_eligible") is not False:
                return None
            return AgentCitation(
                id=_required_string(raw, "chunk_id", 80),
                kind=AgentCitationKind.BRAND_CONTEXT,
                source_name="赛先生品牌资料",
                title=_required_string(raw, "document_title", 200),
                url=None,
                evidence_eligible=False,
            )
    except ValueError:
        return None
    return None


def _required_string(raw: dict[object, object], key: str, limit: int) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("citation field is invalid")
    return value


def _is_safe_https_url(value: str) -> bool:
    return is_public_https_url(value)


def _unsupported_answer() -> tuple[
    AgentRunStatus,
    str,
    tuple[AgentClaim, ...],
    tuple[AgentCitation, ...],
    str,
]:
    return (
        AgentRunStatus.REFUSED,
        "The proposed answer contained an unsupported or mismatched citation.",
        (),
        (),
        "unsupported_citation",
    )


def _insufficient_answer() -> tuple[
    AgentRunStatus,
    str,
    tuple[AgentClaim, ...],
    tuple[AgentCitation, ...],
    str,
]:
    return (
        AgentRunStatus.REFUSED,
        "There was not enough eligible evidence to support the proposed factual claim.",
        (),
        (),
        "insufficient_evidence",
    )
