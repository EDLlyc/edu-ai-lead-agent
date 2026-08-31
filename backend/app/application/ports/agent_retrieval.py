from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from app.domain.agent_retrieval import AgentQueryPlan, AgentRetrievalKind


@dataclass(frozen=True, slots=True)
class AgentTextRerankItem:
    index: int
    relevance_score: float

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("agent rerank index must not be negative")
        if not math.isfinite(self.relevance_score):
            raise ValueError("agent rerank score must be finite")


@dataclass(frozen=True, slots=True)
class AgentTextRerankResult:
    items: tuple[AgentTextRerankItem, ...]
    provider: str
    model: str
    latency_ms: int

    def __post_init__(self) -> None:
        if not self.items or len(self.items) > 10:
            raise ValueError("agent rerank result must be non-empty and bounded")
        indexes = tuple(item.index for item in self.items)
        if len(indexes) != len(set(indexes)):
            raise ValueError("agent rerank indexes must be unique")
        if not self.provider.strip() or not self.model.strip() or self.latency_ms < 0:
            raise ValueError("agent rerank identity and latency are invalid")


class AgentQueryPlanner(Protocol):
    async def plan(
        self,
        *,
        query: str,
        retrieval_kind: AgentRetrievalKind,
    ) -> AgentQueryPlan: ...


class AgentTextReranker(Protocol):
    async def rerank(
        self,
        *,
        query: str,
        documents: tuple[str, ...],
        limit: int,
    ) -> AgentTextRerankResult: ...
