from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from app.application.ports.agent_retrieval import (
    AgentTextRerankItem,
    AgentTextRerankResult,
)
from app.application.ports.agent_workbench import (
    AgentEventRecord,
    AgentEvidenceRecord,
    CopyValidationContext,
)
from app.application.ports.brand_knowledge import (
    BrandEmbeddingRequest,
    BrandEmbeddingResult,
)
from app.application.services.agent_retrieval import (
    CachedBrandEmbeddingModel,
    EnhancedAgentKnowledgeReader,
)
from app.domain.agent_retrieval import (
    AgentQueryPlan,
    AgentQueryPlanSource,
    AgentRetrievalIntent,
    AgentRetrievalKind,
    normalize_agent_query,
    weighted_reciprocal_rank_fusion,
)
from app.domain.brand_knowledge import BrandAudience, BrandDocumentKind, BrandRetrievalHit
from app.domain.copy_generation import EligibleEvidence


def _uuid(prefix: int, suffix: int) -> UUID:
    return UUID(f"{prefix:08d}-0000-4000-8000-{suffix:012d}")


def _evidence(index: int) -> AgentEvidenceRecord:
    return AgentEvidenceRecord(
        evidence=EligibleEvidence(
            evidence_id=_uuid(1, index),
            candidate_id=_uuid(2, index),
            passage_id=_uuid(3, index),
            occurrence_id=_uuid(4, index),
            snapshot_id=_uuid(5, index),
            source_name=f"source-{index}",
            source_url=f"https://example.com/{index}",
            source_tier="A",
            published_at=datetime(2026, 8, 31, tzinfo=UTC),
            exact_quote=f"人工智能教育证据 {index}",
            governed_statement=f"人工智能教育事实 {index}",
        ),
        event_id=_uuid(6, index),
        event_version_id=_uuid(7, index),
        source_id=_uuid(8, index),
        event_title=f"人工智能教育事件 {index}",
    )


class _Planner:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def plan(
        self,
        *,
        query: str,
        retrieval_kind: AgentRetrievalKind,
    ) -> AgentQueryPlan:
        if self.fail:
            raise RuntimeError("provider detail")
        intent = (
            AgentRetrievalIntent.FACT_SEARCH
            if retrieval_kind is AgentRetrievalKind.EVIDENCE
            else AgentRetrievalIntent.BRAND_EXPLANATION
        )
        return AgentQueryPlan(
            original_query=normalize_agent_query(query),
            retrieval_kind=retrieval_kind,
            intent=intent,
            source=AgentQueryPlanSource.ZHIPU,
            rewritten_query=(
                "人工智能教育安全政策"
                if retrieval_kind is AgentRetrievalKind.EVIDENCE
                else "真小班班级人数和授课特点"
            ),
        )


class _Reranker:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.documents: tuple[str, ...] = ()

    async def rerank(
        self,
        *,
        query: str,
        documents: tuple[str, ...],
        limit: int,
    ) -> AgentTextRerankResult:
        del query
        if self.fail:
            raise RuntimeError("provider detail")
        self.documents = documents
        indexes = (2, 0)[:limit]
        return AgentTextRerankResult(
            items=tuple(
                AgentTextRerankItem(index=index, relevance_score=1 - position / 10)
                for position, index in enumerate(indexes)
            ),
            provider="zhipu",
            model="rerank",
            latency_ms=1,
        )


class _EvidenceReader:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search_evidence(
        self,
        *,
        query: str,
        limit: int,
        candidate_id: UUID | None,
    ) -> tuple[AgentEvidenceRecord, ...]:
        del limit, candidate_id
        self.queries.append(query)
        if query == "人工智能教育安全政策":
            return (_evidence(2), _evidence(3))
        return (_evidence(1), _evidence(2))

    async def get_event(self, event_id: UUID) -> AgentEventRecord:
        raise AssertionError(event_id)

    async def retrieve_brand_context(
        self,
        *,
        query: str,
        audience: BrandAudience,
        document_kinds: tuple[BrandDocumentKind, ...],
        valid_on: date,
        limit: int,
    ) -> tuple[BrandRetrievalHit, ...]:
        del query, audience, document_kinds, valid_on, limit
        raise AssertionError

    async def load_copy_validation_context(
        self,
        *,
        copy_run_id: UUID,
        brand_chunk_ids: tuple[UUID, ...],
    ) -> CopyValidationContext:
        del copy_run_id, brand_chunk_ids
        raise AssertionError


def _brand_hit(index: int) -> BrandRetrievalHit:
    return BrandRetrievalHit(
        chunk_id=_uuid(11, index),
        document_id=_uuid(12, index),
        version_id=_uuid(13, index),
        document_title=f"真小班品牌资料 {index}",
        document_kind=BrandDocumentKind.POSITIONING,
        audience=BrandAudience.PARENTS,
        text=f"真小班班级人数与授课特点 {index}",
        tone_tags=(),
        safety_tags=(),
        visual_tags=(),
        full_text_score=0.5,
        vector_score=0.5,
        fused_score=0.5,
    )


class _BrandReader:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search_evidence(
        self,
        *,
        query: str,
        limit: int,
        candidate_id: UUID | None,
    ) -> tuple[AgentEvidenceRecord, ...]:
        del query, limit, candidate_id
        raise AssertionError

    async def get_event(self, event_id: UUID) -> AgentEventRecord:
        raise AssertionError(event_id)

    async def retrieve_brand_context(
        self,
        *,
        query: str,
        audience: BrandAudience,
        document_kinds: tuple[BrandDocumentKind, ...],
        valid_on: date,
        limit: int,
    ) -> tuple[BrandRetrievalHit, ...]:
        del audience, document_kinds, valid_on, limit
        self.queries.append(query)
        if query == "真小班班级人数和授课特点":
            return (_brand_hit(2), _brand_hit(3))
        return (_brand_hit(1), _brand_hit(2))

    async def load_copy_validation_context(
        self,
        *,
        copy_run_id: UUID,
        brand_chunk_ids: tuple[UUID, ...],
    ) -> CopyValidationContext:
        del copy_run_id, brand_chunk_ids
        raise AssertionError


def test_query_normalization_overlap_and_weighted_rrf_are_deterministic() -> None:
    assert normalize_agent_query("  \uff21\uff29\n教育  ") == "AI 教育"
    fused = weighted_reciprocal_rank_fusion(
        (
            (("a", "b"), 1.0),
            (("b", "c"), 0.8),
        )
    )

    assert tuple(item.key for item in fused) == ("b", "a", "c")
    assert fused[0].score > fused[1].score > fused[2].score
    with pytest.raises(ValueError, match="drifted"):
        AgentQueryPlan(
            original_query="人工智能教育",
            retrieval_kind=AgentRetrievalKind.EVIDENCE,
            intent=AgentRetrievalIntent.FACT_SEARCH,
            source=AgentQueryPlanSource.ZHIPU,
            rewritten_query="火星任务发射时间",
        )


@pytest.mark.asyncio
async def test_enhanced_reader_fuses_original_and_rewrite_then_reranks() -> None:
    reader = _EvidenceReader()
    reranker = _Reranker()
    enhanced = EnhancedAgentKnowledgeReader(
        reader,
        planner=_Planner(),
        reranker=reranker,
    )

    records = await enhanced.search_evidence(
        query="人工智能教育有什么政策",
        limit=2,
        candidate_id=None,
    )

    assert reader.queries == ["人工智能教育有什么政策", "人工智能教育安全政策"]
    assert tuple(record.evidence.evidence_id for record in records) == (_uuid(1, 3), _uuid(1, 2))
    assert len(reranker.documents) == 3


@pytest.mark.asyncio
async def test_enhanced_reader_falls_back_to_original_and_rrf_order() -> None:
    reader = _EvidenceReader()
    enhanced = EnhancedAgentKnowledgeReader(
        reader,
        planner=_Planner(fail=True),
        reranker=_Reranker(fail=True),
    )

    records = await enhanced.search_evidence(
        query="人工智能教育有什么政策",
        limit=2,
        candidate_id=None,
    )

    assert reader.queries == ["人工智能教育有什么政策"]
    assert tuple(record.evidence.evidence_id for record in records) == (_uuid(1, 1), _uuid(1, 2))


@pytest.mark.asyncio
async def test_enhanced_brand_reader_reranks_governed_chunks() -> None:
    reader = _BrandReader()
    enhanced = EnhancedAgentKnowledgeReader(
        reader,
        planner=_Planner(),
        reranker=_Reranker(),
    )

    hits = await enhanced.retrieve_brand_context(
        query="真小班有什么特点",
        audience=BrandAudience.PARENTS,
        document_kinds=(BrandDocumentKind.POSITIONING,),
        valid_on=date(2026, 8, 31),
        limit=2,
    )

    assert reader.queries == ["真小班有什么特点", "真小班班级人数和授课特点"]
    assert tuple(hit.chunk_id for hit in hits) == (_uuid(11, 3), _uuid(11, 2))


class _EmbeddingModel:
    def __init__(self) -> None:
        self.calls = 0

    async def embed_brand(self, request: BrandEmbeddingRequest) -> BrandEmbeddingResult:
        self.calls += 1
        await asyncio.sleep(0)
        return BrandEmbeddingResult(
            vector=(0.5,),
            provider="zhipu",
            model="embedding-3",
            request_fingerprint=request.input_hash,
            provider_request_id=None,
        )


@pytest.mark.asyncio
async def test_embedding_cache_is_single_flight_bounded_and_expires() -> None:
    now = [10.0]
    model = _EmbeddingModel()
    cached = CachedBrandEmbeddingModel(
        model,
        cache_namespace="zhipu:embedding-3:brand-embedding-input-v2",
        max_entries=2,
        ttl_seconds=5,
        clock=lambda: now[0],
    )
    request = BrandEmbeddingRequest(
        chunk_id=_uuid(9, 1),
        input_hash="a" * 64,
        text="真小班有什么特点",
    )

    first, second = await asyncio.gather(
        cached.embed_brand(request),
        cached.embed_brand(request),
    )
    assert first == second
    assert model.calls == 1
    assert cached.cache_hits == 1
    assert cached.cache_misses == 1

    await cached.embed_brand(
        BrandEmbeddingRequest(
            chunk_id=_uuid(9, 2),
            input_hash=request.input_hash,
            text="相同输入哈希但文本不同",
        )
    )
    await cached.embed_brand(
        BrandEmbeddingRequest(
            chunk_id=_uuid(9, 3),
            input_hash="b" * 64,
            text="第三个缓存项用于触发 LRU 淘汰",
        )
    )
    await cached.embed_brand(request)
    assert model.calls == 4

    now[0] = 16.0
    await cached.embed_brand(request)
    assert model.calls == 5
    assert cached.cache_misses == 5


@pytest.mark.asyncio
async def test_embedding_cache_does_not_reuse_artifact_bound_result_across_chunks() -> None:
    model = _EmbeddingModel()
    cached = CachedBrandEmbeddingModel(
        model,
        cache_namespace="alibaba-model-studio:qwen3-vl-embedding:brand-embedding-input-v2",
    )
    shared = {"input_hash": "d" * 64, "text": "两个 chunk 可以包含完全相同的文本"}

    await cached.embed_brand(BrandEmbeddingRequest(chunk_id=_uuid(9, 20), **shared))
    await cached.embed_brand(BrandEmbeddingRequest(chunk_id=_uuid(9, 21), **shared))

    assert model.calls == 2


class _InitiallyFailingEmbeddingModel(_EmbeddingModel):
    async def embed_brand(self, request: BrandEmbeddingRequest) -> BrandEmbeddingResult:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("provider detail")
        return BrandEmbeddingResult(
            vector=(0.5,),
            provider="zhipu",
            model="embedding-3",
            request_fingerprint=request.input_hash,
            provider_request_id=None,
        )


@pytest.mark.asyncio
async def test_embedding_cache_does_not_cache_failures() -> None:
    model = _InitiallyFailingEmbeddingModel()
    cached = CachedBrandEmbeddingModel(
        model,
        cache_namespace="zhipu:embedding-3:brand-embedding-input-v2",
    )
    request = BrandEmbeddingRequest(
        chunk_id=_uuid(9, 4),
        input_hash="c" * 64,
        text="失败结果不应该进入缓存",
    )

    with pytest.raises(RuntimeError, match="provider detail"):
        await cached.embed_brand(request)
    result = await cached.embed_brand(request)

    assert result.provider == "zhipu"
    assert model.calls == 2
