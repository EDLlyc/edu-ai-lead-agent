from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import cast
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.agent_workbench import (
    AgentEventMemberRecord,
    AgentEventRecord,
    AgentEvidenceRecord,
    CopyValidationContext,
)
from app.application.ports.brand_knowledge import BrandEmbeddingModel, BrandKnowledgeRepository
from app.application.services.brand_knowledge import retrieve_brand_context
from app.core.errors import NotFoundError, ProviderIdentityMismatchError
from app.domain.brand_knowledge import (
    BrandAudience,
    BrandDocumentKind,
    BrandRetrievalHit,
    BrandVersionStatus,
)
from app.domain.copy_generation import (
    ENGLISH_EVIDENCE_COPY_PIPELINE_VERSION,
    ActiveBrandContext,
    EligibleEvidence,
    LockedTopicContext,
)
from app.infrastructure.db.brand_knowledge import active_brand_context_filters
from app.infrastructure.db.brand_knowledge import retrieve_brand_context as retrieve_brand_rows
from app.infrastructure.db.copy_generation import (
    governed_evidence_eligibility_filters,
    load_governed_event_evidence,
    load_locked_topic_origin,
)
from app.infrastructure.db.governance_queries import get_event_detail
from app.infrastructure.db.models import (
    AnalysisFactModel,
    ArticleOccurrenceModel,
    BrandChunkModel,
    BrandDocumentModel,
    BrandDocumentVersionModel,
    CandidateAnalysisModel,
    CopyGenerationRunModel,
    EventClusterModel,
    EventClusterVersionModel,
    EventMembershipModel,
    EvidenceBindingModel,
    NormalizedArticleModel,
)

_STATEMENT_TIMEOUT_MS = 4_500


class PostgresAgentKnowledgeReader:
    """Read-only projection adapter for already-governed local developer data."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        brand_embeddings: BrandEmbeddingModel,
    ) -> None:
        self._session_factory = session_factory
        self._brand_embeddings = brand_embeddings
        self._brand_repository = cast(
            BrandKnowledgeRepository,
            _ReadOnlyBrandRepository(session_factory),
        )

    async def search_evidence(
        self,
        *,
        query: str,
        limit: int,
        candidate_id: UUID | None,
    ) -> tuple[AgentEvidenceRecord, ...]:
        normalized_query = query.strip()
        if not normalized_query or len(normalized_query) > 500 or not 1 <= limit <= 5:
            raise ValueError("agent evidence search bounds are invalid")
        ts_query = func.websearch_to_tsquery("simple", normalized_query)
        searchable_text = func.concat_ws(
            " ",
            EvidenceBindingModel.exact_quote,
            AnalysisFactModel.fact_text,
            CandidateAnalysisModel.summary,
            EventClusterVersionModel.representative_title,
        )
        search_vector = func.to_tsvector("simple", searchable_text)
        rank = func.ts_rank(search_vector, ts_query)
        statement = (
            select(
                EvidenceBindingModel,
                ArticleOccurrenceModel,
                CandidateAnalysisModel.summary,
                AnalysisFactModel.fact_text,
                EventClusterVersionModel,
                rank.label("rank"),
            )
            .select_from(EventClusterVersionModel)
            .join(
                EventClusterModel,
                EventClusterModel.current_version_id == EventClusterVersionModel.id,
            )
            .join(
                EventMembershipModel,
                EventMembershipModel.event_id == EventClusterVersionModel.event_id,
            )
            .join(
                NormalizedArticleModel,
                NormalizedArticleModel.id == EventMembershipModel.normalized_article_id,
            )
            .join(
                CandidateAnalysisModel,
                CandidateAnalysisModel.normalized_article_id == NormalizedArticleModel.id,
            )
            .join(
                EvidenceBindingModel,
                EvidenceBindingModel.analysis_id == CandidateAnalysisModel.id,
            )
            .join(
                ArticleOccurrenceModel,
                ArticleOccurrenceModel.id == EvidenceBindingModel.occurrence_id,
            )
            .outerjoin(AnalysisFactModel, AnalysisFactModel.id == EvidenceBindingModel.fact_id)
            .where(
                EventClusterModel.status == "active",
                search_vector.op("@@")(ts_query),
                *governed_evidence_eligibility_filters(
                    event_id=EventClusterVersionModel.event_id,
                    version_created_at=EventClusterVersionModel.created_at,
                ),
            )
            .distinct()
        )
        if candidate_id is not None:
            statement = statement.where(EvidenceBindingModel.candidate_id == candidate_id)
        statement = statement.order_by(
            rank.desc(),
            ArticleOccurrenceModel.trust_tier,
            ArticleOccurrenceModel.source_display_name,
            EvidenceBindingModel.id,
        ).limit(limit)
        async with self._read_only_session() as session:
            rows = tuple((await session.execute(statement)).tuples())
            return tuple(
                AgentEvidenceRecord(
                    evidence=EligibleEvidence(
                        evidence_id=binding.id,
                        candidate_id=binding.candidate_id,
                        passage_id=binding.passage_id,
                        occurrence_id=binding.occurrence_id,
                        snapshot_id=binding.snapshot_id,
                        source_name=occurrence.source_display_name,
                        source_url=occurrence.final_url,
                        source_tier=occurrence.trust_tier,
                        published_at=occurrence.published_at,
                        exact_quote=binding.exact_quote,
                        governed_statement=fact_text or summary,
                    ),
                    event_id=version.event_id,
                    event_version_id=version.id,
                    source_id=occurrence.source_id,
                    event_title=version.representative_title,
                )
                for binding, occurrence, summary, fact_text, version, _rank in rows
            )

    async def get_event(self, event_id: UUID) -> AgentEventRecord:
        async with self._read_only_session() as session:
            detail = await get_event_detail(
                session,
                event_id,
                member_limit=8,
                occurrence_limit=8,
                include_history=False,
                include_member_content=False,
            )
            raw_summary = detail.current_version.summary_projection.get("summary")
            unique_members = []
            seen_candidate_ids: set[UUID] = set()
            for member in detail.members:
                if member.candidate.id in seen_candidate_ids:
                    continue
                seen_candidate_ids.add(member.candidate.id)
                unique_members.append(member)
            return AgentEventRecord(
                event_id=detail.event.id,
                current_version_id=detail.current_version.id,
                representative_title=detail.current_version.representative_title,
                summary=raw_summary if isinstance(raw_summary, str) else None,
                source_diversity=detail.current_version.source_diversity,
                categories=tuple(
                    item
                    for item in detail.current_version.category_projection
                    if isinstance(item, str)
                ),
                members=tuple(
                    AgentEventMemberRecord(
                        candidate_id=member.candidate.id,
                        title=member.candidate.title,
                        url=member.candidate.canonical_url,
                        published_at=member.candidate.published_at,
                        source_ids=tuple(
                            occurrence.source_id
                            for occurrence in _unique_occurrences(member.occurrences)
                        ),
                        source_names=tuple(
                            occurrence.source_display_name
                            for occurrence in _unique_occurrences(member.occurrences)
                        ),
                    )
                    for member in unique_members
                ),
            )

    async def retrieve_brand_context(
        self,
        *,
        query: str,
        audience: BrandAudience,
        document_kinds: tuple[BrandDocumentKind, ...],
        valid_on: date,
        limit: int,
    ) -> tuple[BrandRetrievalHit, ...]:
        return await retrieve_brand_context(
            repository=self._brand_repository,
            embeddings=self._brand_embeddings,
            query=query,
            audience=audience,
            document_kinds=document_kinds,
            valid_on=valid_on,
            limit=limit,
        )

    async def load_copy_validation_context(
        self,
        *,
        copy_run_id: UUID,
        brand_chunk_ids: tuple[UUID, ...],
    ) -> CopyValidationContext:
        async with self._read_only_session() as session:
            run = await session.get(CopyGenerationRunModel, copy_run_id)
            if run is None or run.decision_kind != "selected":
                raise NotFoundError("copy generation run")
            if run.selected_event_id is None or run.selected_event_version_id is None:
                raise RuntimeError("copy validation run has no locked event version")
            version = await session.get(EventClusterVersionModel, run.selected_event_version_id)
            if version is None or version.event_id != run.selected_event_id:
                raise RuntimeError("copy validation event version is unavailable")
            origin = await load_locked_topic_origin(session, run)
            evidence = await load_governed_event_evidence(
                session,
                version,
                include_governed_statement=(
                    run.pipeline_version == ENGLISH_EVIDENCE_COPY_PIPELINE_VERSION
                ),
            )
            brand_context = await _load_active_brand_context(
                session,
                brand_chunk_ids=brand_chunk_ids,
                valid_on=run.business_date,
            )
            raw_summary = version.summary_projection.get("summary")
            raw_rule_version = run.version_bundle.get("rule_version")
            if not isinstance(raw_rule_version, str) or not raw_rule_version.strip():
                raise RuntimeError("copy validation rule version is unavailable")
            topic = LockedTopicContext(
                origin=origin,
                business_date=run.business_date,
                timezone=run.timezone,
                scoring_profile=run.scoring_profile,
                decision_kind="selected",
                selected_event_id=run.selected_event_id,
                selected_event_version_id=run.selected_event_version_id,
                no_topic_code=None,
                title=version.representative_title,
                summary=raw_summary if isinstance(raw_summary, str) else None,
                evidence=evidence,
            )
        return CopyValidationContext(
            copy_run_id=copy_run_id,
            topic=topic,
            brand_context=brand_context,
            rule_version=raw_rule_version,
        )

    @asynccontextmanager
    async def _read_only_session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session:
            await _mark_transaction_read_only(session)
            try:
                yield session
            finally:
                await session.rollback()


class _ReadOnlyBrandRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def retrieve(
        self,
        *,
        query_text: str,
        query_vector: tuple[float, ...],
        query_provider: str,
        query_model: str,
        audience: BrandAudience,
        document_kinds: tuple[BrandDocumentKind, ...],
        valid_on: date,
        limit: int,
        candidate_limit: int,
    ) -> tuple[BrandRetrievalHit, ...]:
        async with self._session_factory() as session:
            await _mark_transaction_read_only(session)
            try:
                active_scope = active_brand_context_filters(
                    audience=audience,
                    document_kinds=document_kinds,
                    valid_on=valid_on,
                )
                active_versions = (
                    select(BrandDocumentVersionModel.id)
                    .select_from(BrandDocumentVersionModel)
                    .join(
                        BrandDocumentModel,
                        BrandDocumentModel.id == BrandDocumentVersionModel.document_id,
                    )
                    .where(*active_scope)
                )
                matching_versions = active_versions.where(
                    BrandDocumentVersionModel.embedding_provider == query_provider,
                    BrandDocumentVersionModel.embedding_model == query_model,
                )
                has_active, has_matching_identity = (
                    await session.execute(
                        select(
                            active_versions.exists(),
                            matching_versions.exists(),
                        )
                    )
                ).one()
                if bool(has_active) and not bool(has_matching_identity):
                    raise ProviderIdentityMismatchError()
                return await retrieve_brand_rows(
                    session,
                    query_text=query_text,
                    query_vector=query_vector,
                    query_provider=query_provider,
                    query_model=query_model,
                    audience=audience,
                    document_kinds=document_kinds,
                    valid_on=valid_on,
                    limit=limit,
                    candidate_limit=candidate_limit,
                )
            finally:
                await session.rollback()


async def _load_active_brand_context(
    session: AsyncSession,
    *,
    brand_chunk_ids: tuple[UUID, ...],
    valid_on: date,
) -> tuple[ActiveBrandContext, ...]:
    if not brand_chunk_ids:
        return ()
    rows = tuple(
        (
            await session.execute(
                select(BrandChunkModel, BrandDocumentVersionModel, BrandDocumentModel)
                .join(
                    BrandDocumentVersionModel,
                    BrandDocumentVersionModel.id == BrandChunkModel.version_id,
                )
                .join(
                    BrandDocumentModel,
                    BrandDocumentModel.id == BrandDocumentVersionModel.document_id,
                )
                .where(
                    BrandChunkModel.id.in_(brand_chunk_ids),
                    BrandDocumentModel.status == "active",
                    BrandDocumentModel.audience == BrandAudience.PARENTS.value,
                    BrandDocumentModel.active_version_id == BrandDocumentVersionModel.id,
                    BrandDocumentVersionModel.active.is_(True),
                    BrandDocumentVersionModel.status == BrandVersionStatus.READY.value,
                    or_(
                        BrandDocumentVersionModel.valid_from.is_(None),
                        BrandDocumentVersionModel.valid_from <= valid_on,
                    ),
                    or_(
                        BrandDocumentVersionModel.valid_until.is_(None),
                        BrandDocumentVersionModel.valid_until >= valid_on,
                    ),
                )
            )
        ).tuples()
    )
    by_id = {
        chunk.id: ActiveBrandContext(
            chunk_id=chunk.id,
            document_id=document.id,
            version_id=version.id,
            document_title=document.title,
            document_kind=document.document_kind,
            text=chunk.text,
            tone_tags=tuple(version.tone_tags),
            safety_tags=tuple(version.safety_tags),
            visual_tags=tuple(version.visual_tags),
        )
        for chunk, version, document in rows
    }
    if set(by_id) != set(brand_chunk_ids):
        raise NotFoundError("brand chunk")
    return tuple(by_id[chunk_id] for chunk_id in brand_chunk_ids)


async def _mark_transaction_read_only(session: AsyncSession) -> None:
    await session.execute(text("SET TRANSACTION READ ONLY"))
    await session.execute(text(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT_MS}ms'"))


def _unique_occurrences(
    occurrences: tuple[ArticleOccurrenceModel, ...],
) -> tuple[ArticleOccurrenceModel, ...]:
    by_source: dict[UUID, ArticleOccurrenceModel] = {}
    for occurrence in occurrences:
        by_source.setdefault(occurrence.source_id, occurrence)
    return tuple(by_source[source_id] for source_id in sorted(by_source, key=str))
