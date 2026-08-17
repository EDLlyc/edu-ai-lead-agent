from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.infrastructure.db.models import (
    AnalysisCategoryModel,
    AnalysisEntityModel,
    AnalysisFactModel,
    ArticleOccurrenceModel,
    CandidateAnalysisModel,
    DuplicateRelationModel,
    EventAssignmentDecisionModel,
    EventClusterModel,
    EventClusterVersionModel,
    EventMembershipModel,
    EvidenceBindingModel,
    EvidenceCandidateModel,
    GovernanceJobModel,
    GovernanceRunModel,
    ModelInvocationModel,
    NormalizedArticleModel,
    NormalizedPassageModel,
)


@dataclass(frozen=True, slots=True)
class GovernanceRunUsage:
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    latency_ms: int


@dataclass(frozen=True, slots=True)
class CandidateAnalysisListRow:
    analysis: CandidateAnalysisModel
    article: NormalizedArticleModel
    candidate: EvidenceCandidateModel
    primary_category: str | None


@dataclass(frozen=True, slots=True)
class CandidateGovernanceDetail:
    requested_candidate: EvidenceCandidateModel
    requested_article: NormalizedArticleModel
    analysis: CandidateAnalysisModel
    analysis_article: NormalizedArticleModel
    analysis_candidate: EvidenceCandidateModel
    primary_category: str | None
    facts: tuple[AnalysisFactModel, ...]
    entities: tuple[AnalysisEntityModel, ...]
    categories: tuple[AnalysisCategoryModel, ...]
    passages: tuple[NormalizedPassageModel, ...]
    bindings: tuple[EvidenceBindingModel, ...]
    occurrences: tuple[ArticleOccurrenceModel, ...]
    duplicate_relations: tuple[DuplicateRelationModel, ...]
    assignment: EventAssignmentDecisionModel | None
    membership: EventMembershipModel | None
    active_event_version_id: UUID | None


@dataclass(frozen=True, slots=True)
class EventListRow:
    event: EventClusterModel
    version: EventClusterVersionModel
    member_count: int
    review_count: int


@dataclass(frozen=True, slots=True)
class EventMemberDetail:
    membership: EventMembershipModel
    article: NormalizedArticleModel
    candidate: EvidenceCandidateModel
    decision: EventAssignmentDecisionModel
    analysis: CandidateAnalysisModel | None
    passages: tuple[NormalizedPassageModel, ...]
    occurrences: tuple[ArticleOccurrenceModel, ...]


@dataclass(frozen=True, slots=True)
class EventDetailProjection:
    event: EventClusterModel
    current_version: EventClusterVersionModel
    versions: tuple[EventClusterVersionModel, ...]
    members: tuple[EventMemberDetail, ...]
    review_decisions: tuple[EventAssignmentDecisionModel, ...]


async def get_governance_run_with_usage(
    session: AsyncSession, run_id: UUID
) -> tuple[GovernanceRunModel, GovernanceRunUsage]:
    run = await session.get(GovernanceRunModel, run_id)
    if run is None:
        raise NotFoundError("governance run")
    usage = (
        await session.execute(
            select(
                func.coalesce(func.sum(ModelInvocationModel.prompt_tokens), 0),
                func.coalesce(func.sum(ModelInvocationModel.completion_tokens), 0),
                func.coalesce(func.sum(ModelInvocationModel.reasoning_tokens), 0),
                func.coalesce(func.sum(ModelInvocationModel.latency_ms), 0),
            )
            .select_from(GovernanceJobModel)
            .outerjoin(
                ModelInvocationModel,
                ModelInvocationModel.governance_job_id == GovernanceJobModel.id,
            )
            .where(GovernanceJobModel.run_id == run_id)
        )
    ).one()
    return run, GovernanceRunUsage(
        prompt_tokens=int(usage[0] or 0),
        completion_tokens=int(usage[1] or 0),
        reasoning_tokens=int(usage[2] or 0),
        latency_ms=int(usage[3] or 0),
    )


async def list_governance_jobs(
    session: AsyncSession,
    *,
    run_id: UUID,
    limit: int,
    after: UUID | None,
) -> tuple[GovernanceJobModel, ...]:
    if await session.get(GovernanceRunModel, run_id) is None:
        raise NotFoundError("governance run")
    statement = select(GovernanceJobModel).where(GovernanceJobModel.run_id == run_id)
    if after is not None:
        statement = statement.where(GovernanceJobModel.id > after)
    return tuple(
        (await session.scalars(statement.order_by(GovernanceJobModel.id).limit(limit))).all()
    )


async def list_candidate_analysis_rows(
    session: AsyncSession,
    *,
    limit: int,
    after: UUID | None,
) -> tuple[CandidateAnalysisListRow, ...]:
    primary_category = AnalysisCategoryModel.category.label("primary_category")
    statement = (
        select(
            CandidateAnalysisModel,
            NormalizedArticleModel,
            EvidenceCandidateModel,
            primary_category,
        )
        .join(
            NormalizedArticleModel,
            NormalizedArticleModel.id == CandidateAnalysisModel.normalized_article_id,
        )
        .join(
            EvidenceCandidateModel,
            EvidenceCandidateModel.id == CandidateAnalysisModel.candidate_id,
        )
        .outerjoin(
            AnalysisCategoryModel,
            and_(
                AnalysisCategoryModel.analysis_id == CandidateAnalysisModel.id,
                AnalysisCategoryModel.is_primary.is_(True),
            ),
        )
        .where(CandidateAnalysisModel.status == "accepted")
    )
    if after is not None:
        statement = statement.where(CandidateAnalysisModel.id > after)
    rows = (
        await session.execute(statement.order_by(CandidateAnalysisModel.id).limit(limit))
    ).tuples()
    return tuple(
        CandidateAnalysisListRow(
            analysis=analysis,
            article=article,
            candidate=candidate,
            primary_category=category,
        )
        for analysis, article, candidate, category in rows
    )


async def get_candidate_governance_detail(
    session: AsyncSession, candidate_id: UUID
) -> CandidateGovernanceDetail:
    requested_candidate = await session.get(EvidenceCandidateModel, candidate_id)
    if requested_candidate is None:
        raise NotFoundError("evidence candidate")
    requested_article = await session.scalar(
        select(NormalizedArticleModel)
        .where(NormalizedArticleModel.candidate_id == candidate_id)
        .order_by(NormalizedArticleModel.created_at.desc(), NormalizedArticleModel.id.desc())
        .limit(1)
    )
    if requested_article is None:
        raise NotFoundError("candidate analysis")
    duplicate_relations = tuple(
        (
            await session.scalars(
                select(DuplicateRelationModel)
                .where(
                    or_(
                        DuplicateRelationModel.left_article_id == requested_article.id,
                        DuplicateRelationModel.right_article_id == requested_article.id,
                    )
                )
                .order_by(DuplicateRelationModel.created_at, DuplicateRelationModel.id)
            )
        ).all()
    )
    analysis = await _accepted_analysis_for_article(session, requested_article.id)
    if analysis is None:
        related_article_ids = tuple(
            relation.right_article_id
            if relation.left_article_id == requested_article.id
            else relation.left_article_id
            for relation in duplicate_relations
            if relation.outcome == "matched"
            and relation.relation_kind in {"same_content", "same_url", "same_source_item"}
        )
        if related_article_ids:
            analysis = await session.scalar(
                select(CandidateAnalysisModel)
                .where(
                    CandidateAnalysisModel.normalized_article_id.in_(related_article_ids),
                    CandidateAnalysisModel.status == "accepted",
                )
                .order_by(
                    CandidateAnalysisModel.created_at.desc(),
                    CandidateAnalysisModel.id.desc(),
                )
                .limit(1)
            )
    if analysis is None:
        raise NotFoundError("candidate analysis")
    analysis_article = await session.get(NormalizedArticleModel, analysis.normalized_article_id)
    analysis_candidate = await session.get(EvidenceCandidateModel, analysis.candidate_id)
    if analysis_article is None or analysis_candidate is None:
        raise RuntimeError("candidate analysis provenance is incomplete")
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
    passages = await _passages_for_article(session, analysis_article.id)
    bindings = tuple(
        (
            await session.scalars(
                select(EvidenceBindingModel)
                .where(EvidenceBindingModel.analysis_id == analysis.id)
                .order_by(
                    EvidenceBindingModel.statement_kind,
                    EvidenceBindingModel.fact_id,
                    EvidenceBindingModel.passage_id,
                    EvidenceBindingModel.occurrence_id,
                )
            )
        ).all()
    )
    occurrences = await _occurrences_for_candidates(
        session,
        {candidate_id, analysis.candidate_id},
    )
    assignment = await session.scalar(
        select(EventAssignmentDecisionModel)
        .where(EventAssignmentDecisionModel.normalized_article_id == requested_article.id)
        .order_by(
            EventAssignmentDecisionModel.created_at.desc(),
            EventAssignmentDecisionModel.id.desc(),
        )
        .limit(1)
    )
    membership = await session.scalar(
        select(EventMembershipModel)
        .where(
            EventMembershipModel.normalized_article_id == requested_article.id,
            EventMembershipModel.active.is_(True),
        )
        .order_by(EventMembershipModel.created_at.desc())
        .limit(1)
    )
    active_event_version_id: UUID | None = None
    if membership is not None:
        event = await session.get(EventClusterModel, membership.event_id)
        active_event_version_id = event.current_version_id if event is not None else None
    primary_category = next(
        (category.category for category in categories if category.is_primary), None
    )
    return CandidateGovernanceDetail(
        requested_candidate=requested_candidate,
        requested_article=requested_article,
        analysis=analysis,
        analysis_article=analysis_article,
        analysis_candidate=analysis_candidate,
        primary_category=primary_category,
        facts=facts,
        entities=entities,
        categories=categories,
        passages=passages,
        bindings=bindings,
        occurrences=occurrences,
        duplicate_relations=duplicate_relations,
        assignment=assignment,
        membership=membership,
        active_event_version_id=active_event_version_id,
    )


async def list_event_rows(
    session: AsyncSession,
    *,
    limit: int,
    after: UUID | None,
) -> tuple[EventListRow, ...]:
    member_count = func.count(func.distinct(EventMembershipModel.id)).label("member_count")
    review_count = func.count(func.distinct(EventAssignmentDecisionModel.id)).label("review_count")
    statement = (
        select(EventClusterModel, EventClusterVersionModel, member_count, review_count)
        .join(
            EventClusterVersionModel,
            EventClusterVersionModel.id == EventClusterModel.current_version_id,
        )
        .outerjoin(
            EventMembershipModel,
            and_(
                EventMembershipModel.event_id == EventClusterModel.id,
                EventMembershipModel.active.is_(True),
            ),
        )
        .outerjoin(
            EventAssignmentDecisionModel,
            and_(
                EventAssignmentDecisionModel.selected_event_id == EventClusterModel.id,
                EventAssignmentDecisionModel.outcome == "review_required",
            ),
        )
        .where(EventClusterModel.status == "active")
        .group_by(EventClusterModel.id, EventClusterVersionModel.id)
    )
    if after is not None:
        statement = statement.where(EventClusterModel.id > after)
    rows = (await session.execute(statement.order_by(EventClusterModel.id).limit(limit))).tuples()
    return tuple(
        EventListRow(
            event=event,
            version=version,
            member_count=int(members),
            review_count=int(reviews),
        )
        for event, version, members, reviews in rows
    )


async def get_event_detail(
    session: AsyncSession,
    event_id: UUID,
    *,
    member_limit: int | None = None,
    occurrence_limit: int | None = None,
    include_history: bool = True,
    include_member_content: bool = True,
) -> EventDetailProjection:
    if member_limit is not None and not 1 <= member_limit <= 100:
        raise ValueError("event member limit must be between one and 100")
    if occurrence_limit is not None and not 1 <= occurrence_limit <= 100:
        raise ValueError("event occurrence limit must be between one and 100")
    event = await session.get(EventClusterModel, event_id)
    if event is None or event.current_version_id is None:
        raise NotFoundError("event")
    current_version = await session.get(EventClusterVersionModel, event.current_version_id)
    if current_version is None:
        raise RuntimeError("event current version is missing")
    versions = (
        tuple(
            (
                await session.scalars(
                    select(EventClusterVersionModel)
                    .where(EventClusterVersionModel.event_id == event_id)
                    .order_by(EventClusterVersionModel.version)
                )
            ).all()
        )
        if include_history
        else (current_version,)
    )
    member_statement = (
        select(
            EventMembershipModel,
            NormalizedArticleModel,
            EvidenceCandidateModel,
            EventAssignmentDecisionModel,
        )
        .join(
            NormalizedArticleModel,
            NormalizedArticleModel.id == EventMembershipModel.normalized_article_id,
        )
        .join(
            EvidenceCandidateModel,
            EvidenceCandidateModel.id == NormalizedArticleModel.candidate_id,
        )
        .join(
            EventAssignmentDecisionModel,
            EventAssignmentDecisionModel.id == EventMembershipModel.assignment_decision_id,
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
    if member_limit is not None:
        member_statement = member_statement.limit(member_limit)
    member_rows = tuple((await session.execute(member_statement)).tuples())
    occurrences_by_candidate: dict[UUID, list[ArticleOccurrenceModel]] = {}
    if not include_member_content and member_rows:
        occurrences = await _occurrences_for_candidates(
            session,
            {candidate.id for _membership, _article, candidate, _decision in member_rows},
            per_candidate_limit=occurrence_limit,
        )
        for occurrence in occurrences:
            occurrences_by_candidate.setdefault(occurrence.candidate_id, []).append(occurrence)
    members: list[EventMemberDetail] = []
    for membership, article, candidate, decision in member_rows:
        analysis = (
            await _accepted_or_reused_analysis(session, article.id)
            if include_member_content
            else None
        )
        analysis_article_id = analysis.normalized_article_id if analysis is not None else article.id
        members.append(
            EventMemberDetail(
                membership=membership,
                article=article,
                candidate=candidate,
                decision=decision,
                analysis=analysis,
                passages=(
                    await _passages_for_article(session, analysis_article_id)
                    if include_member_content
                    else ()
                ),
                occurrences=(
                    await _occurrences_for_candidate(
                        session,
                        candidate.id,
                        limit=occurrence_limit,
                    )
                    if include_member_content
                    else tuple(occurrences_by_candidate.get(candidate.id, ()))
                ),
            )
        )
    review_decisions = (
        tuple(
            (
                await session.scalars(
                    select(EventAssignmentDecisionModel)
                    .where(
                        EventAssignmentDecisionModel.selected_event_id == event_id,
                        EventAssignmentDecisionModel.outcome == "review_required",
                    )
                    .order_by(
                        EventAssignmentDecisionModel.created_at,
                        EventAssignmentDecisionModel.id,
                    )
                )
            ).all()
        )
        if include_history
        else ()
    )
    return EventDetailProjection(
        event=event,
        current_version=current_version,
        versions=versions,
        members=tuple(members),
        review_decisions=review_decisions,
    )


async def _accepted_analysis_for_article(
    session: AsyncSession, normalized_article_id: UUID
) -> CandidateAnalysisModel | None:
    return cast(
        CandidateAnalysisModel | None,
        await session.scalar(
            select(CandidateAnalysisModel)
            .where(
                CandidateAnalysisModel.normalized_article_id == normalized_article_id,
                CandidateAnalysisModel.status == "accepted",
            )
            .order_by(CandidateAnalysisModel.created_at.desc(), CandidateAnalysisModel.id.desc())
            .limit(1)
        ),
    )


async def _accepted_or_reused_analysis(
    session: AsyncSession, normalized_article_id: UUID
) -> CandidateAnalysisModel | None:
    analysis = await _accepted_analysis_for_article(session, normalized_article_id)
    if analysis is not None:
        return analysis
    relation = await session.scalar(
        select(DuplicateRelationModel)
        .where(
            or_(
                DuplicateRelationModel.left_article_id == normalized_article_id,
                DuplicateRelationModel.right_article_id == normalized_article_id,
            ),
            DuplicateRelationModel.outcome == "matched",
            DuplicateRelationModel.relation_kind.in_(
                ["same_content", "same_url", "same_source_item"]
            ),
        )
        .order_by(DuplicateRelationModel.created_at, DuplicateRelationModel.id)
        .limit(1)
    )
    if relation is None:
        return None
    related_article_id = (
        relation.right_article_id
        if relation.left_article_id == normalized_article_id
        else relation.left_article_id
    )
    return await _accepted_analysis_for_article(session, related_article_id)


async def _passages_for_article(
    session: AsyncSession, normalized_article_id: UUID
) -> tuple[NormalizedPassageModel, ...]:
    return tuple(
        (
            await session.scalars(
                select(NormalizedPassageModel)
                .where(NormalizedPassageModel.normalized_article_id == normalized_article_id)
                .order_by(NormalizedPassageModel.ordinal)
            )
        ).all()
    )


async def _occurrences_for_candidate(
    session: AsyncSession,
    candidate_id: UUID,
    *,
    limit: int | None = None,
) -> tuple[ArticleOccurrenceModel, ...]:
    return await _occurrences_for_candidates(
        session,
        {candidate_id},
        per_candidate_limit=limit,
    )


async def _occurrences_for_candidates(
    session: AsyncSession,
    candidate_ids: set[UUID],
    *,
    per_candidate_limit: int | None = None,
) -> tuple[ArticleOccurrenceModel, ...]:
    if not candidate_ids:
        return ()
    if per_candidate_limit is not None:
        ranked_occurrences = (
            select(
                ArticleOccurrenceModel.id.label("occurrence_id"),
                ArticleOccurrenceModel.candidate_id.label("candidate_id"),
                func.row_number()
                .over(
                    partition_by=ArticleOccurrenceModel.candidate_id,
                    order_by=(
                        ArticleOccurrenceModel.fetched_at,
                        ArticleOccurrenceModel.id,
                    ),
                )
                .label("candidate_rank"),
            )
            .where(ArticleOccurrenceModel.candidate_id.in_(candidate_ids))
            .subquery()
        )
        statement = (
            select(ArticleOccurrenceModel)
            .join(
                ranked_occurrences,
                ranked_occurrences.c.occurrence_id == ArticleOccurrenceModel.id,
            )
            .where(ranked_occurrences.c.candidate_rank <= per_candidate_limit)
            .order_by(
                ranked_occurrences.c.candidate_id,
                ranked_occurrences.c.candidate_rank,
            )
        )
    else:
        statement = (
            select(ArticleOccurrenceModel)
            .where(ArticleOccurrenceModel.candidate_id.in_(candidate_ids))
            .order_by(ArticleOccurrenceModel.fetched_at, ArticleOccurrenceModel.id)
        )
    return tuple((await session.scalars(statement)).all())
