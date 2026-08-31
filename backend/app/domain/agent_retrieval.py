from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.domain.value_objects import stable_key

AGENT_QUERY_PLAN_VERSION = "agent-query-plan-v1-zhipu-structured"
AGENT_MULTI_QUERY_FUSION_VERSION = "agent-multi-query-weighted-rrf-v1"
AGENT_RRF_K = 60
AGENT_ORIGINAL_QUERY_WEIGHT = 1.0
AGENT_REWRITTEN_QUERY_WEIGHT = 0.8

_ASCII_TERM = re.compile(r"[a-z0-9]{2,}")
_CJK_SEQUENCE = re.compile(r"[\u3400-\u9fff]+")


class AgentRetrievalKind(StrEnum):
    EVIDENCE = "evidence"
    BRAND = "brand"


class AgentRetrievalIntent(StrEnum):
    FACT_SEARCH = "fact_search"
    BRAND_EXPLANATION = "brand_explanation"


class AgentQueryPlanSource(StrEnum):
    ORIGINAL = "original"
    ZHIPU = "zhipu"
    FALLBACK_ORIGINAL = "fallback_original"


@dataclass(frozen=True, slots=True)
class AgentQueryPlan:
    original_query: str
    retrieval_kind: AgentRetrievalKind
    intent: AgentRetrievalIntent
    source: AgentQueryPlanSource
    rewritten_query: str | None = None
    version: str = AGENT_QUERY_PLAN_VERSION

    def __post_init__(self) -> None:
        if normalize_agent_query(self.original_query) != self.original_query:
            raise ValueError("agent query plan original query must be normalized")
        if not 1 <= len(self.original_query) <= 500:
            raise ValueError("agent query plan original query is out of bounds")
        expected_intent = (
            AgentRetrievalIntent.FACT_SEARCH
            if self.retrieval_kind is AgentRetrievalKind.EVIDENCE
            else AgentRetrievalIntent.BRAND_EXPLANATION
        )
        if self.intent is not expected_intent:
            raise ValueError("agent query plan intent does not match retrieval kind")
        if self.version != AGENT_QUERY_PLAN_VERSION:
            raise ValueError("agent query plan version is unsupported")
        if self.rewritten_query is not None:
            if normalize_agent_query(self.rewritten_query) != self.rewritten_query:
                raise ValueError("agent rewritten query must be normalized")
            if not 1 <= len(self.rewritten_query) <= 500:
                raise ValueError("agent rewritten query is out of bounds")
            if self.rewritten_query.casefold() == self.original_query.casefold():
                raise ValueError("agent rewritten query must differ from the original")
            if not agent_queries_overlap(self.original_query, self.rewritten_query):
                raise ValueError("agent rewritten query drifted from the original")

    @property
    def queries(self) -> tuple[str, ...]:
        if self.rewritten_query is None:
            return (self.original_query,)
        return (self.original_query, self.rewritten_query)

    @property
    def fingerprint(self) -> str:
        return stable_key(
            self.version,
            self.retrieval_kind.value,
            self.intent.value,
            self.source.value,
            self.original_query,
            self.rewritten_query or "",
        )


@dataclass(frozen=True, slots=True)
class AgentRrfRankedKey:
    key: str
    score: float

    def __post_init__(self) -> None:
        if not self.key or len(self.key) > 120:
            raise ValueError("agent RRF key must be bounded and non-blank")
        if not math.isfinite(self.score) or self.score <= 0:
            raise ValueError("agent RRF score must be finite and positive")


def normalize_agent_query(query: str) -> str:
    normalized = unicodedata.normalize("NFKC", query)
    return " ".join(normalized.split()).strip()


def original_agent_query_plan(
    query: str,
    retrieval_kind: AgentRetrievalKind,
    *,
    fallback: bool = False,
) -> AgentQueryPlan:
    normalized = normalize_agent_query(query)
    intent = (
        AgentRetrievalIntent.FACT_SEARCH
        if retrieval_kind is AgentRetrievalKind.EVIDENCE
        else AgentRetrievalIntent.BRAND_EXPLANATION
    )
    return AgentQueryPlan(
        original_query=normalized,
        retrieval_kind=retrieval_kind,
        intent=intent,
        source=(
            AgentQueryPlanSource.FALLBACK_ORIGINAL if fallback else AgentQueryPlanSource.ORIGINAL
        ),
    )


def agent_queries_overlap(original_query: str, rewritten_query: str) -> bool:
    original_terms = _query_terms(original_query)
    rewritten_terms = _query_terms(rewritten_query)
    if original_terms and rewritten_terms and original_terms.intersection(rewritten_terms):
        return True
    original_characters = {
        character for character in original_query.casefold() if character.isalnum()
    }
    rewritten_characters = {
        character for character in rewritten_query.casefold() if character.isalnum()
    }
    required = min(2, len(original_characters))
    return required > 0 and len(original_characters.intersection(rewritten_characters)) >= required


def weighted_reciprocal_rank_fusion(
    rankings: Sequence[tuple[Sequence[str], float]],
    *,
    rrf_k: int = AGENT_RRF_K,
) -> tuple[AgentRrfRankedKey, ...]:
    if not rankings or rrf_k < 1:
        raise ValueError("agent RRF inputs are invalid")
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    observation_index = 0
    for keys, weight in rankings:
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError("agent RRF weights must be finite and positive")
        seen_in_ranking: set[str] = set()
        for rank, key in enumerate(keys, 1):
            if not key or len(key) > 120 or key in seen_in_ranking:
                raise ValueError("agent RRF ranking contains an invalid or duplicate key")
            seen_in_ranking.add(key)
            if key not in first_seen:
                first_seen[key] = observation_index
                observation_index += 1
            scores[key] = scores.get(key, 0.0) + weight / (rrf_k + rank)
    return tuple(
        AgentRrfRankedKey(key=key, score=score)
        for key, score in sorted(
            scores.items(),
            key=lambda item: (-item[1], first_seen[item[0]], item[0]),
        )
    )


def _query_terms(query: str) -> set[str]:
    normalized = normalize_agent_query(query).casefold()
    terms = set(_ASCII_TERM.findall(normalized))
    for sequence in _CJK_SEQUENCE.findall(normalized):
        if len(sequence) == 1:
            terms.add(sequence)
        else:
            terms.update(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return terms
