"""Deterministic scheduling, hard budgets, and oracle-side attempt scoring."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from hashlib import sha256
from typing import cast

from app.application.ports.agent_retrieval import (
    AgentQueryPlanner,
    AgentTextReranker,
    AgentTextRerankResult,
)
from app.application.ports.agent_workbench import (
    AgentModelFailure,
    ModelDecision,
    ModelDecisionRequest,
    ToolCallingModel,
)
from app.application.ports.brand_knowledge import (
    BrandEmbeddingModel,
    BrandEmbeddingRequest,
    BrandEmbeddingResult,
)
from app.application.services.agent_retrieval import CachedBrandEmbeddingModel
from app.application.services.agent_tools import TypedToolRegistry
from app.domain.agent_retrieval import AgentQueryPlan, AgentRetrievalKind
from app.domain.agent_workbench import (
    AgentClaimKind,
    AgentModelErrorCode,
    AgentRunResult,
    AgentRunStatus,
    AgentToolErrorCode,
    AgentTraceKind,
)

from .models import (
    ATTEMPT_SCHEMA_VERSION,
    MAX_AGENT_ATTEMPTS,
    SCHEDULE_SEED,
    AttemptExecutionStatus,
    AttemptObservation,
    AttemptScore,
    Capability,
    CapabilityCounts,
    CapabilityLimits,
    CaseOracle,
    ExperimentArm,
    LiveAbCase,
    SafeClaimObservation,
    SafeToolObservation,
    evidence_sha256,
)


class CapabilityBudgetExhausted(RuntimeError):
    def __init__(self, capability: Capability) -> None:
        super().__init__(f"{capability.value}_budget_exhausted")
        self.capability = capability


@dataclass(frozen=True, slots=True)
class AttemptPlan:
    ordinal: int
    case_id: str
    repetition: int
    arm: ExperimentArm

    @property
    def canary(self) -> bool:
        return self.ordinal <= 2

    @property
    def attempt_ref(self) -> str:
        return f"{self.case_id}.r{self.repetition}.{self.arm.value}"


class CapabilityBudget:
    """Single-event-loop hard counters checked immediately before provider boundaries."""

    def __init__(self, limits: CapabilityLimits | None = None) -> None:
        resolved = limits or CapabilityLimits()
        self._limits = {
            Capability.AGENT: resolved.agent_decisions,
            Capability.PLANNER: resolved.planner_requests,
            Capability.RERANKER: resolved.rerank_requests,
            Capability.EMBEDDING: resolved.embedding_requests,
        }
        self._counts = {capability: 0 for capability in Capability}
        self._exhausted: Capability | None = None

    def consume(self, capability: Capability) -> None:
        if self._counts[capability] >= self._limits[capability]:
            self._exhausted = capability
            raise CapabilityBudgetExhausted(capability)
        self._counts[capability] += 1

    @property
    def exhausted(self) -> Capability | None:
        return self._exhausted

    def snapshot(self) -> CapabilityCounts:
        return CapabilityCounts(
            agent=self._counts[Capability.AGENT],
            planner=self._counts[Capability.PLANNER],
            reranker=self._counts[Capability.RERANKER],
            embedding=self._counts[Capability.EMBEDDING],
        )

    @staticmethod
    def delta(before: CapabilityCounts, after: CapabilityCounts) -> CapabilityCounts:
        return CapabilityCounts(
            agent=after.agent - before.agent,
            planner=after.planner - before.planner,
            reranker=after.reranker - before.reranker,
            embedding=after.embedding - before.embedding,
        )


class CapabilityFailureLedger:
    """Safe per-capability failures, including enhancement fallbacks hidden by the reader."""

    def __init__(self) -> None:
        self._counts = {capability: 0 for capability in Capability}

    def record(self, capability: Capability) -> None:
        self._counts[capability] += 1

    def snapshot(self) -> dict[str, int]:
        return {capability.value: count for capability, count in self._counts.items() if count}

    @staticmethod
    def delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
        return {
            capability.value: difference
            for capability in Capability
            if (difference := after.get(capability.value, 0) - before.get(capability.value, 0))
        }


class BudgetedToolCallingModel:
    def __init__(
        self,
        model: ToolCallingModel,
        budget: CapabilityBudget,
        failures: CapabilityFailureLedger,
    ) -> None:
        self._model = model
        self._budget = budget
        self._failures = failures

    async def decide(self, request: ModelDecisionRequest) -> ModelDecision:
        try:
            self._budget.consume(Capability.AGENT)
        except CapabilityBudgetExhausted:
            raise AgentModelFailure(AgentModelErrorCode.UNAVAILABLE) from None
        try:
            return await self._model.decide(request)
        except Exception:
            self._failures.record(Capability.AGENT)
            raise


class BudgetedQueryPlanner:
    def __init__(
        self,
        planner: AgentQueryPlanner,
        budget: CapabilityBudget,
        failures: CapabilityFailureLedger,
    ) -> None:
        self._planner = planner
        self._budget = budget
        self._failures = failures

    async def plan(
        self,
        *,
        query: str,
        retrieval_kind: AgentRetrievalKind,
    ) -> AgentQueryPlan:
        self._budget.consume(Capability.PLANNER)
        try:
            return await self._planner.plan(query=query, retrieval_kind=retrieval_kind)
        except Exception:
            self._failures.record(Capability.PLANNER)
            raise


class BudgetedTextReranker:
    def __init__(
        self,
        reranker: AgentTextReranker,
        budget: CapabilityBudget,
        failures: CapabilityFailureLedger,
    ) -> None:
        self._reranker = reranker
        self._budget = budget
        self._failures = failures

    async def rerank(
        self,
        *,
        query: str,
        documents: tuple[str, ...],
        limit: int,
    ) -> AgentTextRerankResult:
        self._budget.consume(Capability.RERANKER)
        try:
            return await self._reranker.rerank(query=query, documents=documents, limit=limit)
        except Exception:
            self._failures.record(Capability.RERANKER)
            raise


class BudgetedBrandEmbeddingModel:
    def __init__(
        self,
        model: BrandEmbeddingModel,
        budget: CapabilityBudget,
        failures: CapabilityFailureLedger,
    ) -> None:
        self._model = model
        self._budget = budget
        self._failures = failures

    async def embed_brand(self, request: BrandEmbeddingRequest) -> BrandEmbeddingResult:
        self._budget.consume(Capability.EMBEDDING)
        try:
            return await self._model.embed_brand(request)
        except Exception:
            self._failures.record(Capability.EMBEDDING)
            raise


def build_schedule(
    case_ids: tuple[str, ...],
    *,
    repetitions: int = 3,
    seed: int = SCHEDULE_SEED,
) -> tuple[AttemptPlan, ...]:
    if len(case_ids) != 12 or len(set(case_ids)) != 12 or repetitions != 3:
        raise ValueError("live A/B schedule requires twelve unique cases and three repetitions")
    rng = random.Random(seed)
    schedule: list[AttemptPlan] = []
    for case_id in case_ids:
        for repetition in range(1, repetitions + 1):
            arms = [ExperimentArm.RAW, ExperimentArm.ENHANCED]
            rng.shuffle(arms)
            for arm in arms:
                schedule.append(
                    AttemptPlan(
                        ordinal=len(schedule) + 1,
                        case_id=case_id,
                        repetition=repetition,
                        arm=arm,
                    )
                )
    if len(schedule) != MAX_AGENT_ATTEMPTS:
        raise AssertionError("live A/B schedule did not produce exactly 72 attempts")
    return tuple(schedule)


def require_registry_equality(
    baseline: TypedToolRegistry,
    treatment: TypedToolRegistry,
) -> str:
    if baseline.schema_hash != treatment.schema_hash:
        raise ValueError("A/B registries differ; reader enhancement is not isolated")
    return baseline.schema_hash


def canary_attempt_passed(attempt: AttemptObservation) -> bool:
    """Require the complete retrieval and Agent contract for each mandatory canary arm."""

    return (
        attempt.canary
        and attempt.execution_status is AttemptExecutionStatus.COMPLETED
        and attempt.terminal_status in {"completed", "refused"}
        and attempt.error_code is None
        and not attempt.capability_failure_counts
        and attempt.score.task_success
        and attempt.score.terminal_match
        and attempt.score.tool_precision == 1
        and attempt.score.tool_recall == 1
        and attempt.score.argument_valid_rate == 1
        and attempt.score.citation_precision == 1
        and attempt.score.citation_coverage == 1
        and attempt.score.hit_at_3 == 1
        and attempt.score.recall_at_3 == 1
        and attempt.score.target_citation_coverage == 1
    )


def is_systemic_failure(attempt: AttemptObservation) -> bool:
    """Classify only provider/protocol/budget failures for deterministic circuit breaking."""

    return (
        attempt.execution_status is AttemptExecutionStatus.FAILED
        or attempt.terminal_status in {"failed", "budget_exhausted", "cancelled"}
        or bool(attempt.capability_failure_counts)
        or bool(
            attempt.error_code
            and (
                attempt.error_code.startswith("agent_model_")
                or "budget_exhausted" in attempt.error_code
                or attempt.error_code.startswith("executor_")
            )
        )
    )


def score_result(case: LiveAbCase, oracle: CaseOracle, result: AgentRunResult) -> AttemptScore:
    del case
    tool_steps = tuple(
        step
        for step in result.steps
        if step.kind is AgentTraceKind.TOOL_CALL and step.tool_name is not None
    )
    result_steps = {
        (step.call_id, step.tool_name): step
        for step in result.steps
        if step.kind is AgentTraceKind.TOOL_RESULT
    }
    selected = tuple(cast(str, step.tool_name) for step in tool_steps)
    selected_set = set(selected)
    required = set(oracle.required_tools)
    allowed = set(oracle.allowed_tools)
    tool_precision = _ratio(len(selected_set & allowed), len(selected_set))
    tool_recall = _ratio(len(selected_set & required), len(required))

    exact_constraints = {(item.tool, item.key): item.value for item in oracle.exact_arguments}
    valid_calls = 0
    for step in tool_steps:
        result_step = result_steps.get((step.call_id, step.tool_name))
        safe_arguments = {key: _argument_string(value) for key, value in step.safe_arguments}
        constraints = {
            key: value for (tool, key), value in exact_constraints.items() if tool == step.tool_name
        }
        invalid_code = result_step is None or result_step.code in {
            AgentToolErrorCode.INVALID_ARGUMENTS.value,
            AgentToolErrorCode.UNKNOWN.value,
        }
        if not invalid_code and all(
            safe_arguments.get(key) == value for key, value in constraints.items()
        ):
            valid_calls += 1
    argument_valid_rate = _ratio(valid_calls, len(tool_steps))

    qrel_by_id = {item.target_id: item.relevance for item in oracle.qrels}
    retrieval_metrics = _retrieval_metrics(result, oracle)
    hit_at_3 = retrieval_metrics[0] if qrel_by_id else None
    recall_at_3 = retrieval_metrics[1] if qrel_by_id else None
    mrr_at_3 = retrieval_metrics[2] if qrel_by_id else None
    ndcg_at_3 = retrieval_metrics[3] if qrel_by_id else None

    used_citations = {citation_id for claim in result.claims for citation_id in claim.citation_ids}
    observed_citations = {
        citation_id
        for step in result.steps
        if step.kind is AgentTraceKind.TOOL_RESULT
        for citation_id in step.citation_ids
    }
    target_ids = set(qrel_by_id)
    evidence_citations = {
        citation_id
        for step in result.steps
        if step.kind is AgentTraceKind.TOOL_RESULT and step.tool_name == "search_evidence"
        for citation_id in step.citation_ids
    }
    brand_citations = {
        citation_id
        for step in result.steps
        if step.kind is AgentTraceKind.TOOL_RESULT and step.tool_name == "retrieve_brand_context"
        for citation_id in step.citation_ids
    }
    citation_claims = tuple(
        claim
        for claim in result.claims
        if claim.kind in {AgentClaimKind.EXTERNAL_FACT, AgentClaimKind.BRAND_STATEMENT}
    )
    supported_claims = tuple(
        claim
        for claim in citation_claims
        if claim.citation_ids
        and set(claim.citation_ids).issubset(
            evidence_citations if claim.kind is AgentClaimKind.EXTERNAL_FACT else brand_citations
        )
    )
    unsupported = tuple(claim for claim in citation_claims if claim not in supported_claims)
    citation_precision = _ratio(len(used_citations & observed_citations), len(used_citations))
    citation_coverage = _ratio(len(supported_claims), len(citation_claims))
    target_citation_coverage = (
        _ratio(len(used_citations & target_ids), len(target_ids)) if qrel_by_id else None
    )
    unsupported_claim_rate = (
        _ratio(len(unsupported), len(citation_claims)) if citation_claims else 0.0
    )
    terminal_match = result.status.value == oracle.expected_terminal.value
    refusal_correct = (result.status is AgentRunStatus.REFUSED) == oracle.expect_refusal

    failures: list[str] = []
    _failure(failures, not terminal_match, "terminal_mismatch")
    _failure(failures, not required.issubset(selected_set), "missing_required_tool")
    _failure(failures, not selected_set.issubset(allowed), "unexpected_tool")
    _failure(failures, argument_valid_rate < 1, "invalid_arguments")
    _failure(failures, not refusal_correct, "refusal_mismatch")
    _failure(failures, unsupported_claim_rate > 0, "unsupported_claim")
    _failure(failures, not used_citations.issubset(observed_citations), "citation_not_observed")
    if qrel_by_id:
        _failure(failures, hit_at_3 != 1, "target_not_retrieved_at_3")
        _failure(
            failures,
            target_citation_coverage is None or target_citation_coverage <= 0,
            "target_not_cited",
        )

    return AttemptScore(
        task_success=not failures,
        terminal_match=terminal_match,
        tool_precision=tool_precision,
        tool_recall=tool_recall,
        argument_valid_rate=argument_valid_rate,
        citation_precision=citation_precision,
        citation_coverage=citation_coverage,
        unsupported_claim_rate=unsupported_claim_rate,
        refusal_correct=refusal_correct,
        hit_at_3=hit_at_3,
        recall_at_3=recall_at_3,
        mrr_at_3=mrr_at_3,
        ndcg_at_3=ndcg_at_3,
        target_citation_coverage=target_citation_coverage,
        failure_codes=tuple(failures),
    )


def build_attempt_observation(
    *,
    plan: AttemptPlan,
    case: LiveAbCase,
    oracle: CaseOracle,
    result: AgentRunResult,
    manifest_sha256: str,
    authorization_sha256: str,
    capability_counts: CapabilityCounts,
    capability_failure_counts: dict[str, int],
    embedding_cache: CachedBrandEmbeddingModel,
    cache_hits_before: int,
    cache_misses_before: int,
) -> AttemptObservation:
    result_steps = {
        (step.call_id, step.tool_name): step
        for step in result.steps
        if step.kind is AgentTraceKind.TOOL_RESULT
    }
    tools: list[SafeToolObservation] = []
    for step in result.steps:
        if step.kind is not AgentTraceKind.TOOL_CALL or step.tool_name is None:
            continue
        result_step = result_steps.get((step.call_id, step.tool_name))
        safe_arguments = dict(step.safe_arguments)
        exact_keys = {item.key for item in oracle.exact_arguments if item.tool == step.tool_name}
        tools.append(
            SafeToolObservation(
                name=step.tool_name,
                succeeded=result_step is not None and result_step.status.value == "succeeded",
                argument_keys=tuple(sorted(safe_arguments)),
                exact_arguments={
                    key: rendered
                    for key, value in safe_arguments.items()
                    if key in exact_keys and (rendered := _argument_string(value)) is not None
                },
                citation_ids=result_step.citation_ids if result_step is not None else (),
                error_code=result_step.code if result_step is not None else "missing_tool_result",
            )
        )
    observed = tuple(
        dict.fromkeys(citation_id for tool in tools for citation_id in tool.citation_ids)
    )
    return AttemptObservation(
        schema_version=ATTEMPT_SCHEMA_VERSION,
        attempt_ref=plan.attempt_ref,
        schedule_ordinal=plan.ordinal,
        canary=plan.canary,
        manifest_sha256=manifest_sha256,
        authorization_sha256=authorization_sha256,
        case_id=case.case_id,
        repetition=plan.repetition,
        arm=plan.arm,
        execution_status=AttemptExecutionStatus.COMPLETED,
        terminal_status=result.status.value,
        error_code=result.error_code,
        summary_sha256=sha256(result.summary.encode("utf-8")).hexdigest(),
        tools=tuple(tools),
        claims=tuple(
            SafeClaimObservation(
                kind=claim.kind.value,
                text_sha256=sha256(claim.text.encode("utf-8")).hexdigest(),
                citation_ids=claim.citation_ids,
            )
            for claim in result.claims
        ),
        observed_citation_ids=observed,
        duration_ms=result.metrics.duration_ms,
        model_latency_ms=result.metrics.model_latency_ms,
        tool_latency_ms=result.metrics.tool_latency_ms,
        prompt_tokens=result.metrics.prompt_tokens,
        completion_tokens=result.metrics.completion_tokens,
        reasoning_tokens=result.metrics.reasoning_tokens,
        capability_counts=capability_counts,
        capability_failure_counts=capability_failure_counts,
        embedding_cache_hits=embedding_cache.cache_hits - cache_hits_before,
        embedding_cache_misses=embedding_cache.cache_misses - cache_misses_before,
        score=score_result(case, oracle, result),
    )


def build_failed_attempt(
    *,
    plan: AttemptPlan,
    case: LiveAbCase,
    manifest_sha256: str,
    authorization_sha256: str,
    capability_counts: CapabilityCounts,
    capability_failure_counts: dict[str, int],
    failure_code: str,
) -> AttemptObservation:
    score = AttemptScore(
        task_success=False,
        terminal_match=False,
        tool_precision=0,
        tool_recall=0,
        argument_valid_rate=0,
        citation_precision=0,
        citation_coverage=0,
        unsupported_claim_rate=0,
        refusal_correct=False,
        failure_codes=("executor_failed",),
    )
    return AttemptObservation(
        schema_version=ATTEMPT_SCHEMA_VERSION,
        attempt_ref=plan.attempt_ref,
        schedule_ordinal=plan.ordinal,
        canary=plan.canary,
        manifest_sha256=manifest_sha256,
        authorization_sha256=authorization_sha256,
        case_id=case.case_id,
        repetition=plan.repetition,
        arm=plan.arm,
        execution_status=AttemptExecutionStatus.FAILED,
        terminal_status="failed",
        error_code=failure_code[:120],
        summary_sha256=evidence_sha256({"failure": failure_code[:120]}),
        duration_ms=0,
        model_latency_ms=0,
        tool_latency_ms=0,
        prompt_tokens=0,
        completion_tokens=0,
        reasoning_tokens=0,
        capability_counts=capability_counts,
        capability_failure_counts=capability_failure_counts,
        embedding_cache_hits=0,
        embedding_cache_misses=0,
        score=score,
    )


def _argument_string(value: object) -> str | None:
    if isinstance(value, tuple):
        return ",".join(str(item) for item in value)
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return None


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _mrr(ranked: tuple[str, ...], relevant: set[str]) -> float:
    for index, item in enumerate(ranked, start=1):
        if item in relevant:
            return 1 / index
    return 0.0


def _ndcg(ranked: tuple[str, ...], qrels: dict[str, int]) -> float:
    actual = sum(
        (2 ** qrels.get(item, 0) - 1) / math.log2(index + 2) for index, item in enumerate(ranked)
    )
    ideal_relevances = sorted(qrels.values(), reverse=True)[:3]
    ideal = sum(
        (2**relevance - 1) / math.log2(index + 2)
        for index, relevance in enumerate(ideal_relevances)
    )
    return actual / ideal if ideal else 1.0


def _retrieval_metrics(
    result: AgentRunResult,
    oracle: CaseOracle,
) -> tuple[float, float, float, float]:
    """Macro-average top-three quality per retrieval namespace.

    Evidence and brand IDs come from different tools. Treating their combined output as one
    global ranking would make the second tool in a multi-tool case unable to contribute at @3.
    """

    tool_for_kind = {
        "evidence": "search_evidence",
        "brand_context": "retrieve_brand_context",
    }
    values: list[tuple[float, float, float, float]] = []
    for target_kind in {item.target_kind for item in oracle.qrels}:
        qrels = {
            item.target_id: item.relevance
            for item in oracle.qrels
            if item.target_kind is target_kind
        }
        ranked = tuple(
            dict.fromkeys(
                citation_id
                for step in result.steps
                if step.kind is AgentTraceKind.TOOL_RESULT
                and step.tool_name == tool_for_kind[target_kind.value]
                for citation_id in step.citation_ids
            )
        )[:3]
        relevant = set(qrels)
        values.append(
            (
                float(any(item in relevant for item in ranked)),
                _ratio(len(set(ranked) & relevant), len(relevant)),
                _mrr(ranked, relevant),
                _ndcg(ranked, qrels),
            )
        )
    if not values:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        sum(row[0] for row in values) / len(values),
        sum(row[1] for row in values) / len(values),
        sum(row[2] for row in values) / len(values),
        sum(row[3] for row in values) / len(values),
    )


def _failure(values: list[str], condition: bool, code: str) -> None:
    if condition:
        values.append(code)
