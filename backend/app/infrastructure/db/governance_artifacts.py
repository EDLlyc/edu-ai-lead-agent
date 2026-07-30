from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.governance import (
    EmbeddingResult,
    FactualAnalysisResult,
    GovernanceArtifactRepository,
)
from app.core.errors import GovernanceLeaseLostError, NotFoundError, ProviderDimensionMismatchError
from app.domain.event_assignment import (
    EventArticleProfile,
    EventAssignmentDecision,
    EventAssignmentPolicy,
    EventCandidateProfile,
    decide_event_assignment,
)
from app.domain.governance_deduplication import (
    ExactDuplicateArtifact,
    ExactDuplicateDecision,
)
from app.domain.governance_entities import ClaimedGovernanceJob
from app.domain.governance_enums import (
    EmbeddingPurpose,
    EventAssignmentOutcome,
    EventTimePrecision,
    FactualCategory,
    FactualEntityType,
)
from app.domain.governance_normalization import NormalizedDocument, NormalizedPassage
from app.domain.governance_pipeline import (
    AnalysisArtifact,
    EmbeddingArtifact,
    ExactReuseArtifact,
    NormalizedArtifact,
    PersistedEventAssignment,
    RecentEventCandidate,
    SemanticCandidateArtifact,
    StoredGovernanceCandidate,
)
from app.domain.governance_semantic import SemanticDuplicateDecision
from app.domain.governance_value_objects import (
    event_assignment_lane_advisory_key,
    stable_governance_artifact_id,
)
from app.domain.value_objects import stable_key
from app.infrastructure.db.governance_repositories import assert_active_governance_lease
from app.infrastructure.db.models import (
    AnalysisCategoryModel,
    AnalysisEntityModel,
    AnalysisFactModel,
    ArticleEmbeddingModel,
    ArticleOccurrenceModel,
    CandidateAnalysisModel,
    DuplicateRelationModel,
    EventAssignmentDecisionModel,
    EventClusterModel,
    EventClusterVersionModel,
    EventMembershipModel,
    EvidenceBindingModel,
    EvidenceCandidateModel,
    ModelInvocationModel,
    NormalizedArticleModel,
    NormalizedPassageModel,
)
from app.schemas.governance_analysis import (
    EvidenceBoundStatement,
    FactualAnalysisOutput,
    FactualCategoryAssignment,
    FactualClaim,
    StructuredEntity,
)


async def load_stored_candidate(
    session: AsyncSession, claimed: ClaimedGovernanceJob
) -> StoredGovernanceCandidate:
    await assert_active_governance_lease(session, claimed)
    candidate = await session.get(EvidenceCandidateModel, claimed.candidate_id)
    if candidate is None:
        raise NotFoundError("evidence candidate")
    if candidate.content_hash != claimed.input_content_hash:
        raise GovernanceLeaseLostError()
    return StoredGovernanceCandidate(
        candidate_id=candidate.id,
        source_id=candidate.source_id,
        source_item_id=candidate.source_item_id,
        title=candidate.title,
        clean_text=candidate.clean_text,
        canonical_url=candidate.canonical_url,
        published_at=candidate.published_at,
        first_fetched_at=candidate.first_fetched_at,
        language=candidate.language,
        content_hash=candidate.content_hash,
    )


async def persist_normalized_document(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    document: NormalizedDocument,
    language: str,
) -> NormalizedArtifact:
    await assert_active_governance_lease(session, claimed, for_update=True)
    if (
        document.candidate_id != claimed.candidate_id
        or document.input_content_hash != claimed.input_content_hash
        or document.normalization_version != claimed.version_bundle.normalization_version
        or document.passage_schema_version != claimed.version_bundle.passage_schema_version
    ):
        raise ValueError("normalized document does not match the claimed version bundle")
    article_id = stable_governance_artifact_id(
        "normalized-article",
        document.candidate_id,
        document.input_content_hash,
        document.normalization_version,
    )
    await session.execute(
        insert(NormalizedArticleModel)
        .values(
            id=article_id,
            candidate_id=document.candidate_id,
            input_content_hash=document.input_content_hash,
            normalization_version=document.normalization_version,
            normalized_hash=document.normalized_hash,
            simhash_hex=document.simhash_hex,
            normalized_text=document.normalized_text,
            language=language,
        )
        .on_conflict_do_nothing(constraint="uq_normalized_articles_derivation")
    )
    stored_article_id = await session.scalar(
        select(NormalizedArticleModel.id).where(
            NormalizedArticleModel.candidate_id == document.candidate_id,
            NormalizedArticleModel.input_content_hash == document.input_content_hash,
            NormalizedArticleModel.normalization_version == document.normalization_version,
        )
    )
    if stored_article_id is None:
        raise RuntimeError("normalized article upsert did not produce an artifact")
    for passage in document.passages:
        await session.execute(
            insert(NormalizedPassageModel)
            .values(
                id=passage.passage_id,
                normalized_article_id=stored_article_id,
                candidate_id=document.candidate_id,
                ordinal=passage.ordinal,
                passage_hash=passage.passage_hash,
                text=passage.text,
                source_start=passage.source_start,
                source_end=passage.source_end,
            )
            .on_conflict_do_nothing(constraint="uq_normalized_passages_article_ordinal")
        )
    await assert_active_governance_lease(session, claimed, for_update=True)
    await session.commit()
    await assert_active_governance_lease(session, claimed)
    return await _load_normalized_artifact(session, stored_article_id)


async def find_exact_duplicate_artifacts(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    article: NormalizedArtifact,
) -> tuple[ExactDuplicateArtifact, ...]:
    await assert_active_governance_lease(session, claimed)
    incoming_candidate = await session.get(EvidenceCandidateModel, article.candidate_id)
    if incoming_candidate is None:
        raise NotFoundError("evidence candidate")
    rows = list(
        (
            await session.execute(
                select(NormalizedArticleModel, EvidenceCandidateModel)
                .join(
                    EvidenceCandidateModel,
                    EvidenceCandidateModel.id == NormalizedArticleModel.candidate_id,
                )
                .where(
                    NormalizedArticleModel.id != article.normalized_article_id,
                    or_(
                        NormalizedArticleModel.normalized_hash == article.normalized_hash,
                        and_(
                            EvidenceCandidateModel.canonical_url
                            == incoming_candidate.canonical_url,
                            EvidenceCandidateModel.content_hash == incoming_candidate.content_hash,
                        ),
                        and_(
                            EvidenceCandidateModel.source_id == incoming_candidate.source_id,
                            EvidenceCandidateModel.source_item_id
                            == incoming_candidate.source_item_id,
                            EvidenceCandidateModel.content_hash == incoming_candidate.content_hash,
                        ),
                    ),
                )
                .order_by(EvidenceCandidateModel.first_fetched_at, EvidenceCandidateModel.id)
                .limit(50)
            )
        ).tuples()
    )
    artifacts: list[ExactDuplicateArtifact] = []
    for normalized, candidate in rows:
        occurrence_ids = tuple(
            (
                await session.scalars(
                    select(ArticleOccurrenceModel.id)
                    .where(ArticleOccurrenceModel.candidate_id == candidate.id)
                    .order_by(ArticleOccurrenceModel.id)
                )
            ).all()
        )
        artifacts.append(
            ExactDuplicateArtifact(
                normalized_article_id=normalized.id,
                candidate_id=candidate.id,
                source_id=candidate.source_id,
                normalized_hash=normalized.normalized_hash,
                input_content_hash=normalized.input_content_hash,
                canonical_url=candidate.canonical_url,
                source_item_id=candidate.source_item_id,
                first_fetched_at=candidate.first_fetched_at,
                occurrence_ids=occurrence_ids,
            )
        )
    return tuple(artifacts)


async def persist_exact_duplicate_relations(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    incoming: ExactDuplicateArtifact,
    decision: ExactDuplicateDecision,
    policy_version: str,
) -> tuple[UUID, ...]:
    await assert_active_governance_lease(session, claimed, for_update=True)
    if policy_version != claimed.version_bundle.similarity_rule_version:
        raise ValueError("exact-duplicate policy does not match the claimed version bundle")
    relation_ids: list[UUID] = []
    for relation in decision.relations:
        relation_id = stable_governance_artifact_id(
            "duplicate-relation",
            relation.left_article_id,
            relation.right_article_id,
            relation.relation_kind.value,
            policy_version,
        )
        await session.execute(
            insert(DuplicateRelationModel)
            .values(
                id=relation_id,
                left_article_id=relation.left_article_id,
                right_article_id=relation.right_article_id,
                relation_kind=relation.relation_kind.value,
                policy_version=policy_version,
                outcome="matched",
                threshold=None,
                features={
                    "incoming_article_id": str(incoming.normalized_article_id),
                    "canonical_article_id": str(decision.canonical.normalized_article_id),
                    "occurrence_count": len(decision.occurrence_ids),
                },
            )
            .on_conflict_do_nothing(constraint="uq_duplicate_relations_pair_policy")
        )
        relation_ids.append(relation_id)
    await assert_active_governance_lease(session, claimed, for_update=True)
    await session.commit()
    return tuple(relation_ids)


async def find_exact_reuse_artifact(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    canonical_article_id: UUID,
) -> ExactReuseArtifact | None:
    await assert_active_governance_lease(session, claimed)
    analysis_id = await session.scalar(
        select(CandidateAnalysisModel.id)
        .where(
            CandidateAnalysisModel.normalized_article_id == canonical_article_id,
            CandidateAnalysisModel.status == "accepted",
            CandidateAnalysisModel.prompt_version == claimed.version_bundle.prompt_version,
            CandidateAnalysisModel.schema_version == claimed.version_bundle.analysis_schema_version,
            CandidateAnalysisModel.taxonomy_version == claimed.version_bundle.taxonomy_version,
            CandidateAnalysisModel.provider == claimed.version_bundle.chat_provider,
            CandidateAnalysisModel.model == claimed.version_bundle.chat_model,
        )
        .order_by(CandidateAnalysisModel.created_at.desc())
        .limit(1)
    )
    if analysis_id is None:
        return None
    event_id = await session.scalar(
        select(EventMembershipModel.event_id)
        .where(
            EventMembershipModel.normalized_article_id == canonical_article_id,
            EventMembershipModel.active.is_(True),
            EventMembershipModel.policy_version == claimed.version_bundle.event_assignment_version,
        )
        .order_by(EventMembershipModel.created_at.desc())
        .limit(1)
    )
    return ExactReuseArtifact(
        canonical_article_id=canonical_article_id,
        analysis_id=analysis_id,
        event_id=event_id,
    )


async def persist_analysis_artifact(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    article: NormalizedArtifact,
    result: FactualAnalysisResult,
    prompt_version: str,
    schema_version: str,
    taxonomy_version: str,
) -> AnalysisArtifact:
    if not isinstance(result, FactualAnalysisResult):
        raise TypeError("analysis result must use the application-owned result type")
    await assert_active_governance_lease(session, claimed, for_update=True)
    if (
        prompt_version != claimed.version_bundle.prompt_version
        or schema_version != claimed.version_bundle.analysis_schema_version
        or taxonomy_version != claimed.version_bundle.taxonomy_version
        or result.provider != claimed.version_bundle.chat_provider
        or result.model != claimed.version_bundle.chat_model
    ):
        raise ValueError("analysis result does not match the claimed version bundle")
    invocation_id = stable_governance_artifact_id(
        "model-invocation", "factual-analysis", result.request_fingerprint
    )
    await session.execute(
        insert(ModelInvocationModel)
        .values(
            id=invocation_id,
            governance_job_id=claimed.job_id,
            capability="factual_analysis",
            provider=result.provider,
            model=result.model,
            request_fingerprint=result.request_fingerprint,
            provider_request_id=result.provider_request_id,
            status="succeeded",
            prompt_version=prompt_version,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            reasoning_tokens=result.reasoning_tokens,
            latency_ms=result.latency_ms,
            safe_usage={
                "validation_correction_count": result.validation_corrections,
            },
            completed_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(constraint="uq_model_invocations_request")
    )
    stored_invocation_id = await session.scalar(
        select(ModelInvocationModel.id).where(
            ModelInvocationModel.capability == "factual_analysis",
            ModelInvocationModel.request_fingerprint == result.request_fingerprint,
        )
    )
    if stored_invocation_id is None:
        raise RuntimeError("model invocation upsert did not produce an artifact")
    analysis_id = stable_governance_artifact_id("candidate-analysis", result.request_fingerprint)
    inserted_analysis_id = await session.scalar(
        insert(CandidateAnalysisModel)
        .values(
            id=analysis_id,
            normalized_article_id=article.normalized_article_id,
            candidate_id=article.candidate_id,
            invocation_id=stored_invocation_id,
            request_fingerprint=result.request_fingerprint,
            prompt_version=prompt_version,
            schema_version=schema_version,
            taxonomy_version=taxonomy_version,
            provider=result.provider,
            model=result.model,
            status="accepted",
            summary=result.analysis.summary.text,
            event_time_start=result.analysis.event_time_start,
            event_time_end=result.analysis.event_time_end,
            event_time_precision=result.analysis.event_time_precision.value,
            keywords=list(result.analysis.keywords),
        )
        .on_conflict_do_nothing(constraint="uq_candidate_analyses_request")
        .returning(CandidateAnalysisModel.id)
    )
    stored_analysis_id = inserted_analysis_id or await session.scalar(
        select(CandidateAnalysisModel.id).where(
            CandidateAnalysisModel.request_fingerprint == result.request_fingerprint
        )
    )
    if stored_analysis_id is None:
        raise RuntimeError("candidate analysis upsert did not produce an artifact")
    if inserted_analysis_id is not None:
        await _persist_analysis_children(
            session,
            analysis_id=stored_analysis_id,
            article=article,
            output=result.analysis,
            taxonomy_version=taxonomy_version,
        )
    await assert_active_governance_lease(session, claimed, for_update=True)
    await session.commit()
    loaded = await load_analysis_artifact(
        session,
        claimed=claimed,
        normalized_article_id=article.normalized_article_id,
    )
    if loaded is None:
        raise RuntimeError("accepted candidate analysis could not be reloaded")
    return loaded


async def load_analysis_artifact(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    normalized_article_id: UUID,
) -> AnalysisArtifact | None:
    await assert_active_governance_lease(session, claimed)
    analysis = await session.scalar(
        select(CandidateAnalysisModel)
        .where(
            CandidateAnalysisModel.normalized_article_id == normalized_article_id,
            CandidateAnalysisModel.status == "accepted",
            CandidateAnalysisModel.prompt_version == claimed.version_bundle.prompt_version,
            CandidateAnalysisModel.schema_version == claimed.version_bundle.analysis_schema_version,
            CandidateAnalysisModel.taxonomy_version == claimed.version_bundle.taxonomy_version,
            CandidateAnalysisModel.provider == claimed.version_bundle.chat_provider,
            CandidateAnalysisModel.model == claimed.version_bundle.chat_model,
        )
        .order_by(CandidateAnalysisModel.created_at.desc())
        .limit(1)
    )
    if analysis is None:
        return None
    candidate = await session.get(EvidenceCandidateModel, analysis.candidate_id)
    if candidate is None:
        raise RuntimeError("analysis candidate is missing")
    facts = tuple(
        (
            await session.scalars(
                select(AnalysisFactModel)
                .where(AnalysisFactModel.analysis_id == analysis.id)
                .order_by(AnalysisFactModel.ordinal)
            )
        ).all()
    )
    entities = tuple(
        (
            await session.scalars(
                select(AnalysisEntityModel)
                .where(AnalysisEntityModel.analysis_id == analysis.id)
                .order_by(AnalysisEntityModel.ordinal)
            )
        ).all()
    )
    categories = tuple(
        (
            await session.scalars(
                select(AnalysisCategoryModel)
                .where(AnalysisCategoryModel.analysis_id == analysis.id)
                .order_by(AnalysisCategoryModel.category)
            )
        ).all()
    )
    bindings = tuple(
        (
            await session.scalars(
                select(EvidenceBindingModel)
                .where(EvidenceBindingModel.analysis_id == analysis.id)
                .order_by(EvidenceBindingModel.statement_kind, EvidenceBindingModel.passage_id)
            )
        ).all()
    )
    summary_passage_ids = tuple(
        dict.fromkeys(
            binding.passage_id for binding in bindings if binding.statement_kind == "summary"
        )
    )
    fact_passage_ids: dict[UUID, list[UUID]] = defaultdict(list)
    for binding in bindings:
        if (
            binding.fact_id is not None
            and binding.passage_id not in fact_passage_ids[binding.fact_id]
        ):
            fact_passage_ids[binding.fact_id].append(binding.passage_id)
    output = FactualAnalysisOutput(
        summary=EvidenceBoundStatement(
            text=analysis.summary or "",
            passage_ids=summary_passage_ids,
        ),
        key_facts=tuple(
            FactualClaim(
                text=fact.fact_text,
                passage_ids=tuple(fact_passage_ids[fact.id]),
                event_time_start=fact.event_time_start,
                event_time_end=fact.event_time_end,
                event_time_precision=EventTimePrecision(fact.event_time_precision),
            )
            for fact in facts
        ),
        entities=tuple(
            StructuredEntity(
                entity_type=FactualEntityType(entity.entity_type),
                source_mention=entity.source_mention,
                canonical_name=entity.canonical_name,
                passage_id=entity.support_passage_id,
            )
            for entity in entities
        ),
        categories=tuple(
            FactualCategoryAssignment(
                category=FactualCategory(category.category),
                confidence=category.confidence,
            )
            for category in categories
        ),
        primary_category=next(
            (FactualCategory(category.category) for category in categories if category.is_primary),
            None,
        ),
        keywords=tuple(analysis.keywords),
        event_time_start=analysis.event_time_start,
        event_time_end=analysis.event_time_end,
        event_time_precision=EventTimePrecision(analysis.event_time_precision),
        publication_time=candidate.published_at,
    )
    return AnalysisArtifact(
        analysis_id=analysis.id,
        normalized_article_id=analysis.normalized_article_id,
        candidate_id=analysis.candidate_id,
        request_fingerprint=analysis.request_fingerprint,
        analysis=output,
    )


async def persist_embedding_artifact(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    normalized_article_id: UUID,
    purpose: EmbeddingPurpose,
    input_hash: str,
    input_version: str,
    result: EmbeddingResult,
) -> EmbeddingArtifact:
    if not isinstance(result, EmbeddingResult):
        raise TypeError("embedding result must use the application-owned result type")
    await assert_active_governance_lease(session, claimed, for_update=True)
    if (
        result.dimensions != claimed.version_bundle.embedding_dimensions
        or len(result.vector) != claimed.version_bundle.embedding_dimensions
    ):
        raise ProviderDimensionMismatchError()
    if (
        result.provider != claimed.version_bundle.embedding_provider
        or result.model != claimed.version_bundle.embedding_model
        or input_version != claimed.version_bundle.embedding_input_version
    ):
        raise ValueError("embedding result does not match the claimed version bundle")
    invocation_id = stable_governance_artifact_id(
        "model-invocation", f"embedding-{purpose.value}", result.request_fingerprint
    )
    await session.execute(
        insert(ModelInvocationModel)
        .values(
            id=invocation_id,
            governance_job_id=claimed.job_id,
            capability=f"embedding_{purpose.value}",
            provider=result.provider,
            model=result.model,
            request_fingerprint=result.request_fingerprint,
            provider_request_id=result.provider_request_id,
            status="succeeded",
            prompt_tokens=result.prompt_tokens,
            latency_ms=result.latency_ms,
            safe_usage={"dimension_count": result.dimensions},
            completed_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(constraint="uq_model_invocations_request")
    )
    embedding_id = stable_governance_artifact_id(
        "article-embedding",
        normalized_article_id,
        purpose.value,
        result.provider,
        result.model,
        input_hash,
        input_version,
    )
    await session.execute(
        insert(ArticleEmbeddingModel)
        .values(
            id=embedding_id,
            normalized_article_id=normalized_article_id,
            purpose=purpose.value,
            provider=result.provider,
            model=result.model,
            dimensions=result.dimensions,
            input_hash=input_hash,
            input_version=input_version,
            vector=list(result.vector),
        )
        .on_conflict_do_nothing(constraint="uq_article_embeddings_derivation")
    )
    await assert_active_governance_lease(session, claimed, for_update=True)
    await session.commit()
    loaded = await load_embedding_artifact(
        session,
        claimed=claimed,
        normalized_article_id=normalized_article_id,
        purpose=purpose,
        input_hash=input_hash,
        input_version=input_version,
    )
    if loaded is None:
        raise RuntimeError("embedding upsert did not produce an artifact")
    return loaded


async def load_embedding_artifact(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    normalized_article_id: UUID,
    purpose: EmbeddingPurpose,
    input_hash: str,
    input_version: str,
) -> EmbeddingArtifact | None:
    await assert_active_governance_lease(session, claimed)
    model = await session.scalar(
        select(ArticleEmbeddingModel).where(
            ArticleEmbeddingModel.normalized_article_id == normalized_article_id,
            ArticleEmbeddingModel.purpose == purpose.value,
            ArticleEmbeddingModel.provider == claimed.version_bundle.embedding_provider,
            ArticleEmbeddingModel.model == claimed.version_bundle.embedding_model,
            ArticleEmbeddingModel.dimensions == claimed.version_bundle.embedding_dimensions,
            ArticleEmbeddingModel.input_hash == input_hash,
            ArticleEmbeddingModel.input_version == input_version,
        )
    )
    return _embedding_projection(model) if model is not None else None


async def find_semantic_candidate_artifacts(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    article: NormalizedArtifact,
    embedding: EmbeddingArtifact,
    limit: int,
) -> tuple[SemanticCandidateArtifact, ...]:
    await assert_active_governance_lease(session, claimed)
    distance = ArticleEmbeddingModel.vector.cosine_distance(list(embedding.vector)).label(
        "cosine_distance"
    )
    rows = list(
        (
            await session.execute(
                select(ArticleEmbeddingModel, NormalizedArticleModel, distance)
                .join(
                    NormalizedArticleModel,
                    NormalizedArticleModel.id == ArticleEmbeddingModel.normalized_article_id,
                )
                .where(
                    ArticleEmbeddingModel.normalized_article_id != article.normalized_article_id,
                    ArticleEmbeddingModel.purpose == EmbeddingPurpose.NEAR_DUPLICATE.value,
                    ArticleEmbeddingModel.provider == embedding.provider,
                    ArticleEmbeddingModel.model == embedding.model,
                    ArticleEmbeddingModel.dimensions == embedding.dimensions,
                    ArticleEmbeddingModel.input_version == embedding.input_version,
                )
                .order_by(distance, ArticleEmbeddingModel.id)
                .limit(limit)
            )
        ).tuples()
    )
    return tuple(
        SemanticCandidateArtifact(
            normalized_article_id=normalized.id,
            candidate_id=normalized.candidate_id,
            simhash_hex=normalized.simhash_hex,
            vector=tuple(float(value) for value in stored_embedding.vector),
            cosine_distance=float(cosine_distance),
        )
        for stored_embedding, normalized, cosine_distance in rows
    )


async def persist_semantic_duplicate_decisions(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    decisions: tuple[SemanticDuplicateDecision, ...],
) -> tuple[UUID, ...]:
    await assert_active_governance_lease(session, claimed, for_update=True)
    if any(
        decision.policy_version != claimed.version_bundle.similarity_rule_version
        for decision in decisions
    ):
        raise ValueError("semantic policy does not match the claimed version bundle")
    relation_ids: list[UUID] = []
    for decision in decisions:
        relation_id = stable_governance_artifact_id(
            "duplicate-relation",
            decision.left_article_id,
            decision.right_article_id,
            decision.relation_kind.value,
            decision.policy_version,
        )
        await session.execute(
            insert(DuplicateRelationModel)
            .values(
                id=relation_id,
                left_article_id=decision.left_article_id,
                right_article_id=decision.right_article_id,
                relation_kind=decision.relation_kind.value,
                policy_version=decision.policy_version,
                outcome="matched" if decision.matched else "distinct",
                threshold=decision.threshold,
                features={
                    **decision.features.as_metadata(),
                    "minimum_similarity": decision.threshold,
                    "maximum_simhash_distance": decision.maximum_simhash_distance,
                },
            )
            .on_conflict_do_nothing(constraint="uq_duplicate_relations_pair_policy")
        )
        relation_ids.append(relation_id)
    await assert_active_governance_lease(session, claimed, for_update=True)
    await session.commit()
    return tuple(relation_ids)


async def find_recent_event_candidate_artifacts(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    incoming: EventArticleProfile,
    embedding: EmbeddingArtifact,
    policy: EventAssignmentPolicy,
    now: datetime,
) -> tuple[RecentEventCandidate, ...]:
    await assert_active_governance_lease(session, claimed)
    if policy.version != claimed.version_bundle.event_assignment_version:
        raise ValueError("event policy does not match the claimed version bundle")
    return await _find_recent_events(
        session,
        incoming=incoming,
        provider=embedding.provider,
        model=embedding.model,
        input_version=embedding.input_version,
        version_bundle_fingerprint=claimed.version_bundle.fingerprint,
        policy=policy,
        now=now,
    )


async def persist_event_assignment_artifact(
    session: AsyncSession,
    *,
    claimed: ClaimedGovernanceJob,
    incoming: EventArticleProfile,
    decision: EventAssignmentDecision,
    policy: EventAssignmentPolicy,
    now: datetime,
) -> PersistedEventAssignment:
    await assert_active_governance_lease(session, claimed)
    if (
        policy.version != claimed.version_bundle.event_assignment_version
        or decision.policy_version != policy.version
    ):
        raise ValueError("event decision does not match the claimed version bundle")
    await session.scalar(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": event_assignment_lane_advisory_key(policy.version)},
    )
    await assert_active_governance_lease(session, claimed, for_update=True)
    existing = await session.scalar(
        select(EventAssignmentDecisionModel).where(
            EventAssignmentDecisionModel.normalized_article_id == incoming.normalized_article_id,
            EventAssignmentDecisionModel.governance_run_id == claimed.run_id,
            EventAssignmentDecisionModel.policy_version == policy.version,
        )
    )
    if existing is not None:
        return await _existing_assignment_projection(session, existing)

    active_event_id = await session.scalar(
        select(EventMembershipModel.event_id).where(
            EventMembershipModel.normalized_article_id == incoming.normalized_article_id,
            EventMembershipModel.policy_version == policy.version,
            EventMembershipModel.active.is_(True),
        )
    )
    locked_decision = decision
    if active_event_id is not None:
        locked_decision = EventAssignmentDecision(
            outcome=EventAssignmentOutcome.ASSIGNED_EXISTING,
            selected_event_id=active_event_id,
            features=decision.features,
            alternatives=decision.alternatives,
            policy_version=policy.version,
        )
    # A featureless pre-lock CREATED_NEW decision only means no candidate was visible yet.
    # Recompute it after serialization; only explicit exact-event reuse may skip retrieval.
    elif not (
        decision.outcome is EventAssignmentOutcome.ASSIGNED_EXISTING
        and decision.selected_event_id is not None
        and decision.features is None
    ):
        candidates = await _find_recent_events(
            session,
            incoming=incoming,
            provider=claimed.version_bundle.embedding_provider,
            model=claimed.version_bundle.embedding_model,
            input_version=claimed.version_bundle.embedding_input_version,
            version_bundle_fingerprint=claimed.version_bundle.fingerprint,
            policy=policy,
            now=now,
        )
        locked_decision = decide_event_assignment(
            incoming,
            tuple(candidate.profile for candidate in candidates),
            policy,
        )

    selected_event_id = locked_decision.selected_event_id
    if locked_decision.outcome is EventAssignmentOutcome.CREATED_NEW:
        selected_event_id = stable_governance_artifact_id(
            "event-cluster", incoming.normalized_article_id, policy.version
        )
        await session.execute(
            insert(EventClusterModel)
            .values(id=selected_event_id, status="active")
            .on_conflict_do_nothing(index_elements=[EventClusterModel.id])
        )
    if (
        locked_decision.outcome is EventAssignmentOutcome.ASSIGNED_EXISTING
        and selected_event_id is None
    ):
        raise ValueError("existing-event assignment requires an event ID")
    decision_id = stable_governance_artifact_id(
        "event-assignment-decision",
        incoming.normalized_article_id,
        claimed.run_id,
        policy.version,
    )
    await session.execute(
        insert(EventAssignmentDecisionModel)
        .values(
            id=decision_id,
            normalized_article_id=incoming.normalized_article_id,
            governance_run_id=claimed.run_id,
            selected_event_id=selected_event_id,
            policy_version=policy.version,
            outcome=locked_decision.outcome.value,
            recent_window_start=now - timedelta(days=policy.recent_window_days),
            recent_window_end=now,
            features=(
                locked_decision.features.as_metadata()
                if locked_decision.features is not None
                else {}
            ),
            thresholds=policy.as_metadata(),
            alternatives=[
                alternative.as_metadata() for alternative in locked_decision.alternatives
            ],
        )
        .on_conflict_do_nothing(constraint="uq_event_assignment_decisions_article_run_policy")
    )
    if locked_decision.outcome is EventAssignmentOutcome.REVIEW_REQUIRED:
        await assert_active_governance_lease(session, claimed, for_update=True)
        await session.commit()
        return PersistedEventAssignment(
            decision_id=decision_id,
            outcome=locked_decision.outcome,
            event_id=selected_event_id,
            event_version_id=None,
            source_diversity=0,
        )
    if selected_event_id is None:
        raise RuntimeError("terminal event assignment did not select or create an event")
    membership_id = stable_governance_artifact_id(
        "event-membership",
        selected_event_id,
        incoming.normalized_article_id,
        policy.version,
    )
    await session.execute(
        insert(EventMembershipModel)
        .values(
            id=membership_id,
            event_id=selected_event_id,
            normalized_article_id=incoming.normalized_article_id,
            assignment_decision_id=decision_id,
            policy_version=policy.version,
            active=True,
        )
        .on_conflict_do_nothing(constraint="uq_event_memberships_event_article_policy")
    )
    version_id, source_diversity = await _create_event_projection_version(
        session,
        event_id=selected_event_id,
        claimed=claimed,
        policy=policy,
    )
    await assert_active_governance_lease(session, claimed, for_update=True)
    await session.commit()
    return PersistedEventAssignment(
        decision_id=decision_id,
        outcome=locked_decision.outcome,
        event_id=selected_event_id,
        event_version_id=version_id,
        source_diversity=source_diversity,
    )


async def _persist_analysis_children(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    article: NormalizedArtifact,
    output: FactualAnalysisOutput,
    taxonomy_version: str,
) -> None:
    fact_ids: dict[int, UUID] = {}
    for ordinal, fact in enumerate(output.key_facts):
        fact_id = stable_governance_artifact_id("analysis-fact", analysis_id, ordinal)
        fact_ids[ordinal] = fact_id
        session.add(
            AnalysisFactModel(
                id=fact_id,
                analysis_id=analysis_id,
                ordinal=ordinal,
                fact_text=fact.text,
                event_time_start=fact.event_time_start,
                event_time_end=fact.event_time_end,
                event_time_precision=fact.event_time_precision.value,
                status="accepted",
            )
        )
    for ordinal, entity in enumerate(output.entities):
        session.add(
            AnalysisEntityModel(
                id=stable_governance_artifact_id("analysis-entity", analysis_id, ordinal),
                analysis_id=analysis_id,
                ordinal=ordinal,
                entity_type=entity.entity_type.value,
                source_mention=entity.source_mention,
                canonical_name=entity.canonical_name,
                support_passage_id=entity.passage_id,
            )
        )
    for assignment in output.categories:
        session.add(
            AnalysisCategoryModel(
                id=stable_governance_artifact_id(
                    "analysis-category", analysis_id, assignment.category.value
                ),
                analysis_id=analysis_id,
                taxonomy_version=taxonomy_version,
                category=assignment.category.value,
                is_primary=assignment.category == output.primary_category,
                confidence=assignment.confidence,
            )
        )
    passage_by_id = {passage.passage_id: passage for passage in article.passages}
    occurrences = tuple(
        (
            await session.scalars(
                select(ArticleOccurrenceModel)
                .where(ArticleOccurrenceModel.candidate_id == article.candidate_id)
                .order_by(ArticleOccurrenceModel.id)
            )
        ).all()
    )
    if not occurrences:
        raise ValueError("accepted analysis requires at least one synchronized occurrence")
    await _persist_statement_bindings(
        session,
        analysis_id=analysis_id,
        fact_id=None,
        statement_kind="summary",
        passage_ids=output.summary.passage_ids,
        passage_by_id=passage_by_id,
        occurrences=occurrences,
        candidate_id=article.candidate_id,
    )
    for ordinal, fact in enumerate(output.key_facts):
        await _persist_statement_bindings(
            session,
            analysis_id=analysis_id,
            fact_id=fact_ids[ordinal],
            statement_kind="fact",
            passage_ids=fact.passage_ids,
            passage_by_id=passage_by_id,
            occurrences=occurrences,
            candidate_id=article.candidate_id,
        )


async def _persist_statement_bindings(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    fact_id: UUID | None,
    statement_kind: str,
    passage_ids: tuple[UUID, ...],
    passage_by_id: dict[UUID, NormalizedPassage],
    occurrences: tuple[ArticleOccurrenceModel, ...],
    candidate_id: UUID,
) -> None:
    for passage_id in passage_ids:
        passage = passage_by_id.get(passage_id)
        if passage is None:
            raise ValueError("analysis referenced a passage outside its normalized article")
        for occurrence in occurrences:
            binding_key = stable_key(
                analysis_id,
                fact_id or "summary",
                passage_id,
                occurrence.id,
            )
            session.add(
                EvidenceBindingModel(
                    id=stable_governance_artifact_id("evidence-binding", binding_key),
                    binding_key=binding_key,
                    analysis_id=analysis_id,
                    fact_id=fact_id,
                    statement_kind=statement_kind,
                    passage_id=passage_id,
                    candidate_id=candidate_id,
                    occurrence_id=occurrence.id,
                    snapshot_id=occurrence.snapshot_id,
                    exact_quote=passage.text,
                    quote_start=passage.source_start,
                    quote_end=passage.source_end,
                    validated=True,
                )
            )


async def _find_recent_events(
    session: AsyncSession,
    *,
    incoming: EventArticleProfile,
    provider: str,
    model: str,
    input_version: str,
    version_bundle_fingerprint: str,
    policy: EventAssignmentPolicy,
    now: datetime,
) -> tuple[RecentEventCandidate, ...]:
    distance = ArticleEmbeddingModel.vector.cosine_distance(list(incoming.vector)).label(
        "cosine_distance"
    )
    window_start = now - timedelta(days=policy.recent_window_days)
    rows = list(
        (
            await session.execute(
                select(
                    EventClusterModel,
                    EventClusterVersionModel,
                    ArticleEmbeddingModel,
                    NormalizedArticleModel,
                    EvidenceCandidateModel,
                    distance,
                )
                .join(
                    EventClusterVersionModel,
                    EventClusterVersionModel.id == EventClusterModel.current_version_id,
                )
                .join(
                    ArticleEmbeddingModel,
                    and_(
                        ArticleEmbeddingModel.normalized_article_id
                        == EventClusterVersionModel.representative_article_id,
                        ArticleEmbeddingModel.purpose == EmbeddingPurpose.EVENT_ASSIGNMENT.value,
                    ),
                )
                .join(
                    NormalizedArticleModel,
                    NormalizedArticleModel.id == EventClusterVersionModel.representative_article_id,
                )
                .join(
                    EvidenceCandidateModel,
                    EvidenceCandidateModel.id == NormalizedArticleModel.candidate_id,
                )
                .where(
                    EventClusterModel.status == "active",
                    EventClusterVersionModel.version_bundle_fingerprint
                    == version_bundle_fingerprint,
                    ArticleEmbeddingModel.provider == provider,
                    ArticleEmbeddingModel.model == model,
                    ArticleEmbeddingModel.input_version == input_version,
                    or_(
                        EventClusterVersionModel.event_time_end >= window_start,
                        EventClusterVersionModel.event_time_start >= window_start,
                        EvidenceCandidateModel.published_at >= window_start,
                        EvidenceCandidateModel.first_fetched_at >= window_start,
                    ),
                )
                .order_by(distance, EventClusterModel.id)
                .limit(policy.candidate_limit * 8)
            )
        ).tuples()
    )
    candidates: list[RecentEventCandidate] = []
    seen_events: set[UUID] = set()
    for event, version, stored_embedding, normalized, candidate, raw_distance in rows:
        if event.id in seen_events:
            continue
        categories = frozenset(FactualCategory(value) for value in version.category_projection)
        if incoming.categories and categories and not incoming.categories.intersection(categories):
            continue
        entities = frozenset(
            str(item.get("canonical_name", "")).casefold()
            for item in version.entity_projection
            if isinstance(item, dict) and item.get("canonical_name")
        )
        seen_events.add(event.id)
        profile = EventCandidateProfile(
            event_id=event.id,
            representative_article_id=version.representative_article_id,
            representative_title=version.representative_title,
            vector=tuple(float(value) for value in stored_embedding.vector),
            simhash_hex=normalized.simhash_hex,
            categories=categories,
            entities=entities,
            event_time=version.event_time_start,
            representative_published_at=(candidate.published_at or candidate.first_fetched_at),
            source_diversity=version.source_diversity,
        )
        candidates.append(
            RecentEventCandidate(profile=profile, cosine_distance=float(raw_distance))
        )
        if len(candidates) >= policy.candidate_limit:
            break
    return tuple(candidates)


async def _create_event_projection_version(
    session: AsyncSession,
    *,
    event_id: UUID,
    claimed: ClaimedGovernanceJob,
    policy: EventAssignmentPolicy,
) -> tuple[UUID, int]:
    event = await session.scalar(
        select(EventClusterModel).where(EventClusterModel.id == event_id).with_for_update()
    )
    if event is None:
        raise NotFoundError("event cluster")
    previous_representative_article_id: UUID | None = None
    if event.current_version_id is not None:
        current_version = await session.get(EventClusterVersionModel, event.current_version_id)
        if current_version is not None:
            previous_representative_article_id = current_version.representative_article_id
    members = tuple(
        (
            await session.execute(
                select(
                    EventMembershipModel,
                    NormalizedArticleModel,
                    EvidenceCandidateModel,
                    CandidateAnalysisModel,
                )
                .join(
                    NormalizedArticleModel,
                    NormalizedArticleModel.id == EventMembershipModel.normalized_article_id,
                )
                .join(
                    EvidenceCandidateModel,
                    EvidenceCandidateModel.id == NormalizedArticleModel.candidate_id,
                )
                .outerjoin(
                    CandidateAnalysisModel,
                    and_(
                        CandidateAnalysisModel.normalized_article_id == NormalizedArticleModel.id,
                        CandidateAnalysisModel.status == "accepted",
                        CandidateAnalysisModel.prompt_version
                        == claimed.version_bundle.prompt_version,
                        CandidateAnalysisModel.schema_version
                        == claimed.version_bundle.analysis_schema_version,
                        CandidateAnalysisModel.taxonomy_version
                        == claimed.version_bundle.taxonomy_version,
                        CandidateAnalysisModel.provider == claimed.version_bundle.chat_provider,
                        CandidateAnalysisModel.model == claimed.version_bundle.chat_model,
                    ),
                )
                .where(
                    EventMembershipModel.event_id == event_id,
                    EventMembershipModel.active.is_(True),
                )
                .order_by(
                    func.coalesce(
                        EvidenceCandidateModel.published_at,
                        EvidenceCandidateModel.first_fetched_at,
                    ),
                    NormalizedArticleModel.id,
                )
            )
        ).tuples()
    )
    if not members:
        raise RuntimeError("event projection requires at least one active member")
    article_ids = tuple(member[1].id for member in members)
    candidate_ids = tuple(member[2].id for member in members)
    analysis_ids = tuple(member[3].id for member in members if member[3] is not None)
    member_set_hash = stable_key(
        *(str(article_id) for article_id in sorted(article_ids, key=lambda value: value.int))
    )
    existing_version = await session.scalar(
        select(EventClusterVersionModel).where(
            EventClusterVersionModel.event_id == event_id,
            EventClusterVersionModel.member_set_hash == member_set_hash,
            EventClusterVersionModel.clustering_policy_version == policy.version,
            EventClusterVersionModel.version_bundle_fingerprint
            == claimed.version_bundle.fingerprint,
        )
    )
    source_diversity_value = await session.scalar(
        select(func.count(func.distinct(ArticleOccurrenceModel.source_id))).where(
            ArticleOccurrenceModel.candidate_id.in_(candidate_ids)
        )
    )
    source_diversity = int(source_diversity_value or 0)
    if source_diversity == 0:
        raise RuntimeError("event projection requires at least one governed source occurrence")
    if existing_version is not None:
        event.current_version_id = existing_version.id
        event.updated_at = datetime.now(UTC)
        return existing_version.id, existing_version.source_diversity
    categories = (
        tuple(
            (
                await session.scalars(
                    select(AnalysisCategoryModel.category)
                    .where(AnalysisCategoryModel.analysis_id.in_(analysis_ids))
                    .distinct()
                    .order_by(AnalysisCategoryModel.category)
                )
            ).all()
        )
        if analysis_ids
        else ()
    )
    entity_rows = (
        tuple(
            (
                await session.execute(
                    select(
                        AnalysisEntityModel.entity_type,
                        AnalysisEntityModel.canonical_name,
                    )
                    .where(AnalysisEntityModel.analysis_id.in_(analysis_ids))
                    .distinct()
                    .order_by(
                        AnalysisEntityModel.entity_type,
                        AnalysisEntityModel.canonical_name,
                    )
                )
            ).tuples()
        )
        if analysis_ids
        else ()
    )
    representative = next(
        (member for member in members if member[1].id == previous_representative_article_id),
        None,
    )
    if representative is None:
        representative = next((member for member in members if member[3] is not None), members[0])
    representative_candidate = representative[2]
    representative_analysis = representative[3]
    facts = (
        tuple(
            (
                await session.scalars(
                    select(AnalysisFactModel.fact_text)
                    .where(AnalysisFactModel.analysis_id == representative_analysis.id)
                    .order_by(AnalysisFactModel.ordinal)
                )
            ).all()
        )
        if representative_analysis is not None
        else ()
    )
    event_time_starts = [
        member[3].event_time_start
        for member in members
        if member[3] is not None and member[3].event_time_start is not None
    ]
    event_time_ends: list[datetime] = []
    for member in members:
        analysis = member[3]
        if analysis is None:
            continue
        event_time_end = analysis.event_time_end or analysis.event_time_start
        if event_time_end is not None:
            event_time_ends.append(event_time_end)
    next_version_value = await session.scalar(
        select(func.coalesce(func.max(EventClusterVersionModel.version), 0) + 1).where(
            EventClusterVersionModel.event_id == event_id
        )
    )
    next_version = int(next_version_value or 1)
    version_id = stable_governance_artifact_id(
        "event-cluster-version",
        event_id,
        member_set_hash,
        policy.version,
        claimed.version_bundle.fingerprint,
    )
    session.add(
        EventClusterVersionModel(
            id=version_id,
            event_id=event_id,
            version=next_version,
            representative_article_id=representative[1].id,
            representative_title=representative_candidate.title,
            summary_projection={
                "analysis_id": (
                    str(representative_analysis.id) if representative_analysis is not None else None
                ),
                "summary": (
                    representative_analysis.summary if representative_analysis is not None else None
                ),
                "facts": list(facts),
            },
            event_time_start=min(event_time_starts) if event_time_starts else None,
            event_time_end=max(event_time_ends) if event_time_ends else None,
            event_time_precision=(
                representative_analysis.event_time_precision
                if representative_analysis is not None
                else "unknown"
            ),
            member_set_hash=member_set_hash,
            source_diversity=source_diversity,
            category_projection=list(categories),
            entity_projection=[
                {"entity_type": entity_type, "canonical_name": canonical_name}
                for entity_type, canonical_name in entity_rows
            ],
            clustering_policy_version=policy.version,
            version_bundle_fingerprint=claimed.version_bundle.fingerprint,
            created_by_run_id=claimed.run_id,
        )
    )
    await session.flush()
    event.current_version_id = version_id
    event.updated_at = datetime.now(UTC)
    return version_id, source_diversity


async def _existing_assignment_projection(
    session: AsyncSession,
    decision: EventAssignmentDecisionModel,
) -> PersistedEventAssignment:
    membership = await session.scalar(
        select(EventMembershipModel).where(
            EventMembershipModel.assignment_decision_id == decision.id,
            EventMembershipModel.active.is_(True),
        )
    )
    event_version_id: UUID | None = None
    source_diversity = 0
    if membership is not None:
        event = await session.get(EventClusterModel, membership.event_id)
        if event is not None:
            event_version_id = event.current_version_id
            if event.current_version_id is not None:
                version = await session.get(EventClusterVersionModel, event.current_version_id)
                source_diversity = version.source_diversity if version is not None else 0
    return PersistedEventAssignment(
        decision_id=decision.id,
        outcome=EventAssignmentOutcome(decision.outcome),
        event_id=decision.selected_event_id,
        event_version_id=event_version_id,
        source_diversity=source_diversity,
    )


async def _load_normalized_artifact(
    session: AsyncSession, normalized_article_id: UUID
) -> NormalizedArtifact:
    article = await session.get(NormalizedArticleModel, normalized_article_id)
    if article is None:
        raise NotFoundError("normalized article")
    passages = tuple(
        (
            await session.scalars(
                select(NormalizedPassageModel)
                .where(NormalizedPassageModel.normalized_article_id == normalized_article_id)
                .order_by(NormalizedPassageModel.ordinal)
            )
        ).all()
    )
    return NormalizedArtifact(
        normalized_article_id=article.id,
        candidate_id=article.candidate_id,
        input_content_hash=article.input_content_hash,
        normalization_version=article.normalization_version,
        normalized_hash=article.normalized_hash,
        simhash_hex=article.simhash_hex,
        normalized_text=article.normalized_text,
        passages=tuple(
            NormalizedPassage(
                passage_id=passage.id,
                ordinal=passage.ordinal,
                passage_hash=passage.passage_hash,
                text=passage.text,
                source_start=passage.source_start,
                source_end=passage.source_end,
            )
            for passage in passages
        ),
    )


def _embedding_projection(model: ArticleEmbeddingModel) -> EmbeddingArtifact:
    return EmbeddingArtifact(
        embedding_id=model.id,
        normalized_article_id=model.normalized_article_id,
        purpose=EmbeddingPurpose(model.purpose),
        provider=model.provider,
        model=model.model,
        dimensions=model.dimensions,
        input_hash=model.input_hash,
        input_version=model.input_version,
        vector=tuple(float(value) for value in model.vector),
    )


class PostgresGovernanceArtifactRepository(GovernanceArtifactRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_candidate(self, claimed: ClaimedGovernanceJob) -> StoredGovernanceCandidate:
        async with self._session_factory() as session:
            return await load_stored_candidate(session, claimed)

    async def persist_normalized(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        document: NormalizedDocument,
        language: str,
    ) -> NormalizedArtifact:
        async with self._session_factory() as session:
            return await persist_normalized_document(
                session, claimed=claimed, document=document, language=language
            )

    async def find_exact_duplicates(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        article: NormalizedArtifact,
    ) -> tuple[ExactDuplicateArtifact, ...]:
        async with self._session_factory() as session:
            return await find_exact_duplicate_artifacts(session, claimed=claimed, article=article)

    async def persist_exact_duplicate_decision(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        incoming: ExactDuplicateArtifact,
        decision: ExactDuplicateDecision,
        policy_version: str,
    ) -> tuple[UUID, ...]:
        async with self._session_factory() as session:
            return await persist_exact_duplicate_relations(
                session,
                claimed=claimed,
                incoming=incoming,
                decision=decision,
                policy_version=policy_version,
            )

    async def find_exact_reuse(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        canonical_article_id: UUID,
    ) -> ExactReuseArtifact | None:
        async with self._session_factory() as session:
            return await find_exact_reuse_artifact(
                session,
                claimed=claimed,
                canonical_article_id=canonical_article_id,
            )

    async def load_analysis(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        normalized_article_id: UUID,
    ) -> AnalysisArtifact | None:
        async with self._session_factory() as session:
            return await load_analysis_artifact(
                session,
                claimed=claimed,
                normalized_article_id=normalized_article_id,
            )

    async def persist_analysis(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        article: NormalizedArtifact,
        result: FactualAnalysisResult,
        prompt_version: str,
        schema_version: str,
        taxonomy_version: str,
    ) -> AnalysisArtifact:
        async with self._session_factory() as session:
            return await persist_analysis_artifact(
                session,
                claimed=claimed,
                article=article,
                result=result,
                prompt_version=prompt_version,
                schema_version=schema_version,
                taxonomy_version=taxonomy_version,
            )

    async def load_embedding(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        normalized_article_id: UUID,
        purpose: EmbeddingPurpose,
        input_hash: str,
        input_version: str,
    ) -> EmbeddingArtifact | None:
        async with self._session_factory() as session:
            return await load_embedding_artifact(
                session,
                claimed=claimed,
                normalized_article_id=normalized_article_id,
                purpose=purpose,
                input_hash=input_hash,
                input_version=input_version,
            )

    async def persist_embedding(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        normalized_article_id: UUID,
        purpose: EmbeddingPurpose,
        input_hash: str,
        input_version: str,
        result: EmbeddingResult,
    ) -> EmbeddingArtifact:
        async with self._session_factory() as session:
            return await persist_embedding_artifact(
                session,
                claimed=claimed,
                normalized_article_id=normalized_article_id,
                purpose=purpose,
                input_hash=input_hash,
                input_version=input_version,
                result=result,
            )

    async def find_semantic_candidates(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        article: NormalizedArtifact,
        embedding: EmbeddingArtifact,
        limit: int,
    ) -> tuple[SemanticCandidateArtifact, ...]:
        async with self._session_factory() as session:
            return await find_semantic_candidate_artifacts(
                session,
                claimed=claimed,
                article=article,
                embedding=embedding,
                limit=limit,
            )

    async def persist_semantic_decisions(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        decisions: tuple[SemanticDuplicateDecision, ...],
    ) -> tuple[UUID, ...]:
        async with self._session_factory() as session:
            return await persist_semantic_duplicate_decisions(
                session, claimed=claimed, decisions=decisions
            )

    async def find_recent_event_candidates(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        incoming: EventArticleProfile,
        embedding: EmbeddingArtifact,
        policy: EventAssignmentPolicy,
        now: datetime,
    ) -> tuple[RecentEventCandidate, ...]:
        async with self._session_factory() as session:
            return await find_recent_event_candidate_artifacts(
                session,
                claimed=claimed,
                incoming=incoming,
                embedding=embedding,
                policy=policy,
                now=now,
            )

    async def persist_event_assignment(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        incoming: EventArticleProfile,
        decision: EventAssignmentDecision,
        policy: EventAssignmentPolicy,
        now: datetime,
    ) -> PersistedEventAssignment:
        async with self._session_factory() as session:
            return await persist_event_assignment_artifact(
                session,
                claimed=claimed,
                incoming=incoming,
                decision=decision,
                policy=policy,
                now=now,
            )
