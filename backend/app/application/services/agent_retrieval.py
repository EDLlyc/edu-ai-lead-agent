from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable, Sequence
from datetime import date
from time import monotonic
from typing import TypeVar
from uuid import UUID

import structlog

from app.application.ports.agent_retrieval import AgentQueryPlanner, AgentTextReranker
from app.application.ports.agent_workbench import (
    AgentEventRecord,
    AgentEvidenceRecord,
    AgentKnowledgeReader,
    CopyValidationContext,
)
from app.application.ports.brand_knowledge import (
    BrandEmbeddingModel,
    BrandEmbeddingRequest,
    BrandEmbeddingResult,
)
from app.domain.agent_retrieval import (
    AGENT_MULTI_QUERY_FUSION_VERSION,
    AGENT_ORIGINAL_QUERY_WEIGHT,
    AGENT_REWRITTEN_QUERY_WEIGHT,
    AgentQueryPlan,
    AgentRetrievalKind,
    original_agent_query_plan,
    weighted_reciprocal_rank_fusion,
)
from app.domain.brand_knowledge import BrandAudience, BrandDocumentKind, BrandRetrievalHit
from app.domain.value_objects import sha256_bytes, stable_key

logger = structlog.get_logger()

_RETRIEVAL_CANDIDATE_LIMIT = 5
_RERANK_CANDIDATE_LIMIT = 10
_RERANK_DOCUMENT_LIMIT = 4_096
_RetrievalResult = TypeVar("_RetrievalResult")


class EnhancedAgentKnowledgeReader:
    """Adds bounded query planning, multi-query RRF and reranking to two search methods."""

    def __init__(
        self,
        reader: AgentKnowledgeReader,
        *,
        planner: AgentQueryPlanner,
        reranker: AgentTextReranker,
        planner_timeout_seconds: float = 2.0,
        rewrite_timeout_seconds: float = 1.0,
        rerank_timeout_seconds: float = 1.0,
    ) -> None:
        if (
            not 0 < planner_timeout_seconds <= 2
            or not 0 < rewrite_timeout_seconds <= 1.5
            or not 0 < rerank_timeout_seconds <= 2
        ):
            raise ValueError("agent retrieval enhancement timeouts must be in (0, 2] seconds")
        self._reader = reader
        self._planner = planner
        self._reranker = reranker
        self._planner_timeout_seconds = planner_timeout_seconds
        self._rewrite_timeout_seconds = rewrite_timeout_seconds
        self._rerank_timeout_seconds = rerank_timeout_seconds

    async def search_evidence(
        self,
        *,
        query: str,
        limit: int,
        candidate_id: UUID | None,
    ) -> tuple[AgentEvidenceRecord, ...]:
        planner_task = asyncio.create_task(
            self._safe_plan(query=query, retrieval_kind=AgentRetrievalKind.EVIDENCE)
        )
        original_task = asyncio.create_task(
            self._reader.search_evidence(
                query=query,
                limit=_RETRIEVAL_CANDIDATE_LIMIT,
                candidate_id=candidate_id,
            )
        )
        original_records, plan = await _await_original_and_plan(original_task, planner_task)
        rankings: list[tuple[Sequence[str], float]] = [
            (
                tuple(str(record.evidence.evidence_id) for record in original_records),
                AGENT_ORIGINAL_QUERY_WEIGHT,
            )
        ]
        records_by_id = {str(record.evidence.evidence_id): record for record in original_records}
        if plan.rewritten_query is not None:
            rewritten_records = await self._optional_evidence_retrieval(
                query=plan.rewritten_query,
                candidate_id=candidate_id,
                plan=plan,
            )
            rankings.append(
                (
                    tuple(str(record.evidence.evidence_id) for record in rewritten_records),
                    AGENT_REWRITTEN_QUERY_WEIGHT,
                )
            )
            for record in rewritten_records:
                records_by_id.setdefault(str(record.evidence.evidence_id), record)
        fused = weighted_reciprocal_rank_fusion(rankings)
        candidates = tuple(records_by_id[item.key] for item in fused[:_RERANK_CANDIDATE_LIMIT])
        documents = tuple(_evidence_rerank_document(record) for record in candidates)
        ordered_indexes = await self._safe_rerank(
            query=plan.original_query,
            documents=documents,
            limit=min(limit, len(candidates)),
            retrieval_kind=AgentRetrievalKind.EVIDENCE,
        )
        records = (
            candidates[:limit]
            if ordered_indexes is None
            else tuple(candidates[index] for index in ordered_indexes)
        )
        _log_retrieval_success(
            plan=plan,
            candidate_count=len(candidates),
            result_count=len(records),
            rerank_applied=ordered_indexes is not None and len(candidates) > 1,
        )
        return records

    async def get_event(self, event_id: UUID) -> AgentEventRecord:
        return await self._reader.get_event(event_id)

    async def retrieve_brand_context(
        self,
        *,
        query: str,
        audience: BrandAudience,
        document_kinds: tuple[BrandDocumentKind, ...],
        valid_on: date,
        limit: int,
    ) -> tuple[BrandRetrievalHit, ...]:
        planner_task = asyncio.create_task(
            self._safe_plan(query=query, retrieval_kind=AgentRetrievalKind.BRAND)
        )
        original_task = asyncio.create_task(
            self._reader.retrieve_brand_context(
                query=query,
                audience=audience,
                document_kinds=document_kinds,
                valid_on=valid_on,
                limit=_RETRIEVAL_CANDIDATE_LIMIT,
            )
        )
        original_hits, plan = await _await_original_and_plan(original_task, planner_task)
        rankings: list[tuple[Sequence[str], float]] = [
            (tuple(str(hit.chunk_id) for hit in original_hits), AGENT_ORIGINAL_QUERY_WEIGHT)
        ]
        hits_by_id = {str(hit.chunk_id): hit for hit in original_hits}
        if plan.rewritten_query is not None:
            rewritten_hits = await self._optional_brand_retrieval(
                query=plan.rewritten_query,
                audience=audience,
                document_kinds=document_kinds,
                valid_on=valid_on,
                plan=plan,
            )
            rankings.append(
                (
                    tuple(str(hit.chunk_id) for hit in rewritten_hits),
                    AGENT_REWRITTEN_QUERY_WEIGHT,
                )
            )
            for hit in rewritten_hits:
                hits_by_id.setdefault(str(hit.chunk_id), hit)
        fused = weighted_reciprocal_rank_fusion(rankings)
        candidates = tuple(hits_by_id[item.key] for item in fused[:_RERANK_CANDIDATE_LIMIT])
        documents = tuple(_brand_rerank_document(hit) for hit in candidates)
        ordered_indexes = await self._safe_rerank(
            query=plan.original_query,
            documents=documents,
            limit=min(limit, len(candidates)),
            retrieval_kind=AgentRetrievalKind.BRAND,
        )
        hits = (
            candidates[:limit]
            if ordered_indexes is None
            else tuple(candidates[index] for index in ordered_indexes)
        )
        _log_retrieval_success(
            plan=plan,
            candidate_count=len(candidates),
            result_count=len(hits),
            rerank_applied=ordered_indexes is not None and len(candidates) > 1,
        )
        return hits

    async def load_copy_validation_context(
        self,
        *,
        copy_run_id: UUID,
        brand_chunk_ids: tuple[UUID, ...],
    ) -> CopyValidationContext:
        return await self._reader.load_copy_validation_context(
            copy_run_id=copy_run_id,
            brand_chunk_ids=brand_chunk_ids,
        )

    async def _safe_plan(
        self,
        *,
        query: str,
        retrieval_kind: AgentRetrievalKind,
    ) -> AgentQueryPlan:
        try:
            async with asyncio.timeout(self._planner_timeout_seconds):
                return await self._planner.plan(query=query, retrieval_kind=retrieval_kind)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "agent_query_planner_fallback",
                retrieval_kind=retrieval_kind.value,
                query_hash=_query_hash(query),
            )
            return original_agent_query_plan(query, retrieval_kind, fallback=True)

    async def _optional_evidence_retrieval(
        self,
        *,
        query: str,
        candidate_id: UUID | None,
        plan: AgentQueryPlan,
    ) -> tuple[AgentEvidenceRecord, ...]:
        try:
            async with asyncio.timeout(self._rewrite_timeout_seconds):
                return await self._reader.search_evidence(
                    query=query,
                    limit=_RETRIEVAL_CANDIDATE_LIMIT,
                    candidate_id=candidate_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "agent_rewritten_retrieval_fallback",
                retrieval_kind=plan.retrieval_kind.value,
                plan_fingerprint=plan.fingerprint,
            )
            return ()

    async def _optional_brand_retrieval(
        self,
        *,
        query: str,
        audience: BrandAudience,
        document_kinds: tuple[BrandDocumentKind, ...],
        valid_on: date,
        plan: AgentQueryPlan,
    ) -> tuple[BrandRetrievalHit, ...]:
        try:
            async with asyncio.timeout(self._rewrite_timeout_seconds):
                return await self._reader.retrieve_brand_context(
                    query=query,
                    audience=audience,
                    document_kinds=document_kinds,
                    valid_on=valid_on,
                    limit=_RETRIEVAL_CANDIDATE_LIMIT,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "agent_rewritten_retrieval_fallback",
                retrieval_kind=plan.retrieval_kind.value,
                plan_fingerprint=plan.fingerprint,
            )
            return ()

    async def _safe_rerank(
        self,
        *,
        query: str,
        documents: tuple[str, ...],
        limit: int,
        retrieval_kind: AgentRetrievalKind,
    ) -> tuple[int, ...] | None:
        if not documents or limit < 1:
            return ()
        if len(documents) == 1:
            return (0,)
        try:
            async with asyncio.timeout(self._rerank_timeout_seconds):
                result = await self._reranker.rerank(
                    query=query,
                    documents=documents,
                    limit=limit,
                )
            indexes = tuple(item.index for item in result.items)
            if len(indexes) != limit or any(index >= len(documents) for index in indexes):
                raise ValueError("agent rerank result does not cover the requested top results")
            return indexes
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "agent_text_rerank_fallback",
                retrieval_kind=retrieval_kind.value,
                query_hash=_query_hash(query),
                candidate_count=len(documents),
            )
            return None


class CachedBrandEmbeddingModel:
    """Bounded process-local TTL/LRU cache with single-flight provider calls."""

    def __init__(
        self,
        model: BrandEmbeddingModel,
        *,
        cache_namespace: str,
        max_entries: int = 256,
        ttl_seconds: float = 600,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if (
            not cache_namespace.strip()
            or len(cache_namespace) > 240
            or not 1 <= max_entries <= 4_096
            or not 1 <= ttl_seconds <= 86_400
        ):
            raise ValueError("brand embedding cache bounds are invalid")
        self._model = model
        self._cache_namespace = cache_namespace.strip()
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._cache: OrderedDict[str, tuple[float, BrandEmbeddingResult]] = OrderedDict()
        self._inflight: dict[str, asyncio.Task[BrandEmbeddingResult]] = {}
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0

    @property
    def cache_hits(self) -> int:
        return self._hits

    @property
    def cache_misses(self) -> int:
        return self._misses

    async def embed_brand(self, request: BrandEmbeddingRequest) -> BrandEmbeddingResult:
        key = stable_key(
            "agent-brand-embedding-cache-v2-artifact-bound",
            self._cache_namespace,
            request.chunk_id,
            request.input_hash,
            sha256_bytes(request.text.encode("utf-8")),
        )
        async with self._lock:
            self._discard_expired()
            cached = self._cache.get(key)
            if cached is not None:
                self._hits += 1
                self._cache.move_to_end(key)
                return cached[1]
            task = self._inflight.get(key)
            if task is not None:
                self._hits += 1
            else:
                self._misses += 1
                task = asyncio.create_task(self._load_and_cache(key=key, request=request))
                self._inflight[key] = task
        return await task

    async def _load_and_cache(
        self,
        *,
        key: str,
        request: BrandEmbeddingRequest,
    ) -> BrandEmbeddingResult:
        try:
            result = await self._model.embed_brand(request)
            async with self._lock:
                self._cache[key] = (self._clock() + self._ttl_seconds, result)
                self._cache.move_to_end(key)
                while len(self._cache) > self._max_entries:
                    self._cache.popitem(last=False)
            return result
        finally:
            async with self._lock:
                current = self._inflight.get(key)
                if current is asyncio.current_task():
                    self._inflight.pop(key, None)

    def _discard_expired(self) -> None:
        now = self._clock()
        expired = tuple(key for key, (expires_at, _) in self._cache.items() if expires_at <= now)
        for key in expired:
            self._cache.pop(key, None)


def _evidence_rerank_document(record: AgentEvidenceRecord) -> str:
    values = (
        record.event_title,
        record.evidence.source_name,
        record.evidence.governed_statement or "",
        record.evidence.exact_quote,
    )
    return _bounded_document(values)


def _brand_rerank_document(hit: BrandRetrievalHit) -> str:
    values = (
        hit.document_title,
        hit.section_title or "",
        hit.question_text or "",
        hit.text,
    )
    return _bounded_document(values)


def _bounded_document(values: Sequence[str]) -> str:
    document = "\n".join(" ".join(value.split()) for value in values if value.strip())
    if not document:
        raise ValueError("agent rerank document must be non-blank")
    return document[:_RERANK_DOCUMENT_LIMIT]


def _query_hash(query: str) -> str:
    return sha256_bytes(query.encode("utf-8"))[:16]


def _log_retrieval_success(
    *,
    plan: AgentQueryPlan,
    candidate_count: int,
    result_count: int,
    rerank_applied: bool,
) -> None:
    logger.info(
        "agent_retrieval_enhanced",
        retrieval_kind=plan.retrieval_kind.value,
        query_hash=_query_hash(plan.original_query),
        query_plan_version=plan.version,
        query_plan_source=plan.source.value,
        query_count=len(plan.queries),
        fusion_version=AGENT_MULTI_QUERY_FUSION_VERSION,
        candidate_count=candidate_count,
        result_count=result_count,
        rerank_applied=rerank_applied,
    )


async def _await_original_and_plan(
    retrieval_task: asyncio.Task[_RetrievalResult],
    planner_task: asyncio.Task[AgentQueryPlan],
) -> tuple[_RetrievalResult, AgentQueryPlan]:
    try:
        retrieval_result = await retrieval_task
    except asyncio.CancelledError:
        planner_task.cancel()
        await asyncio.gather(planner_task, return_exceptions=True)
        raise
    except Exception:
        planner_task.cancel()
        await asyncio.gather(planner_task, return_exceptions=True)
        raise
    return retrieval_result, await planner_task
