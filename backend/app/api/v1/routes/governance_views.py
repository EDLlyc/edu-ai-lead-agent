from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.infrastructure.db.governance_queries import (
    CandidateAnalysisListRow,
    CandidateGovernanceDetail,
    EventDetailProjection,
    EventListRow,
    EventMemberDetail,
    GovernanceRunUsage,
)
from app.infrastructure.db.models import (
    ArticleOccurrenceModel,
    CandidateAnalysisModel,
    DuplicateRelationModel,
    EventAssignmentDecisionModel,
    EventClusterVersionModel,
    GovernanceJobModel,
    GovernanceRunModel,
    NormalizedPassageModel,
)
from app.schemas.governance import (
    CandidateAnalysisDetailResponse,
    CandidateAnalysisSummaryResponse,
    DuplicateRelationResponse,
    EventAssignmentResponse,
    EventDetailResponse,
    EventMemberResponse,
    EventSummaryResponse,
    EventVersionResponse,
    GovernanceCategoryResponse,
    GovernanceEntityResponse,
    GovernanceEvidenceBindingResponse,
    GovernanceFactResponse,
    GovernanceJobResponse,
    GovernanceOccurrenceResponse,
    GovernancePassageResponse,
    GovernanceRunResponse,
)


def governance_run_response(
    run: GovernanceRunModel, usage: GovernanceRunUsage
) -> GovernanceRunResponse:
    return GovernanceRunResponse(
        id=run.id,
        trigger=run.trigger,
        acquisition_run_id=run.acquisition_run_id,
        timezone=run.timezone,
        profile_fingerprint=run.profile_fingerprint,
        version_bundle={
            str(key): value
            for key, value in run.version_bundle.items()
            if isinstance(value, (str, int)) and not isinstance(value, bool)
        },
        status=run.status,
        total_jobs=run.total_jobs,
        succeeded_jobs=run.succeeded_jobs,
        review_jobs=run.review_jobs,
        failed_jobs=run.failed_jobs,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        model_latency_ms=usage.latency_ms,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        status_url=f"/api/v1/governance-runs/{run.id}",
    )


def governance_job_response(job: GovernanceJobModel) -> GovernanceJobResponse:
    return GovernanceJobResponse(
        id=job.id,
        run_id=job.run_id,
        candidate_id=job.candidate_id,
        status=job.status,
        current_stage=job.current_stage,
        attempt_count=job.attempt_count,
        outcome=job.outcome,
        error_code=job.error_code,
        safe_metadata=job.safe_metadata,
        available_at=job.available_at,
        heartbeat_at=job.heartbeat_at,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def candidate_analysis_summary(
    row: CandidateAnalysisListRow,
) -> CandidateAnalysisSummaryResponse:
    return _candidate_analysis_summary(
        analysis=row.analysis,
        normalized_article_id=row.article.id,
        candidate_id=row.candidate.id,
        title=row.candidate.title,
        original_url=row.candidate.original_url,
        canonical_url=row.candidate.canonical_url,
        published_at=row.candidate.published_at,
        primary_category=row.primary_category,
    )


def candidate_analysis_detail(
    detail: CandidateGovernanceDetail,
) -> CandidateAnalysisDetailResponse:
    summary = _candidate_analysis_summary(
        analysis=detail.analysis,
        normalized_article_id=detail.analysis_article.id,
        candidate_id=detail.requested_candidate.id,
        title=detail.requested_candidate.title,
        original_url=detail.requested_candidate.original_url,
        canonical_url=detail.requested_candidate.canonical_url,
        published_at=detail.requested_candidate.published_at,
        primary_category=detail.primary_category,
    )
    return CandidateAnalysisDetailResponse(
        **summary.model_dump(),
        requested_candidate_id=detail.requested_candidate.id,
        analysis_candidate_id=detail.analysis_candidate.id,
        analysis_reused=detail.analysis.candidate_id != detail.requested_candidate.id,
        facts=[
            GovernanceFactResponse(
                id=fact.id,
                ordinal=fact.ordinal,
                text=fact.fact_text,
                event_time_start=fact.event_time_start,
                event_time_end=fact.event_time_end,
                event_time_precision=fact.event_time_precision,
            )
            for fact in detail.facts
        ],
        entities=[
            GovernanceEntityResponse(
                id=entity.id,
                ordinal=entity.ordinal,
                entity_type=entity.entity_type,
                source_mention=entity.source_mention,
                canonical_name=entity.canonical_name,
                support_passage_id=entity.support_passage_id,
            )
            for entity in detail.entities
        ],
        categories=[
            GovernanceCategoryResponse(
                category=category.category,
                is_primary=category.is_primary,
                confidence=category.confidence,
                taxonomy_version=category.taxonomy_version,
            )
            for category in detail.categories
        ],
        passages=[passage_response(passage) for passage in detail.passages],
        evidence_bindings=[
            GovernanceEvidenceBindingResponse(
                id=binding.id,
                statement_kind=binding.statement_kind,
                fact_id=binding.fact_id,
                passage_id=binding.passage_id,
                candidate_id=binding.candidate_id,
                occurrence_id=binding.occurrence_id,
                snapshot_id=binding.snapshot_id,
                exact_quote=binding.exact_quote,
                quote_start=binding.quote_start,
                quote_end=binding.quote_end,
                validated=binding.validated,
            )
            for binding in detail.bindings
        ],
        source_occurrences=[occurrence_response(occurrence) for occurrence in detail.occurrences],
        duplicate_relations=[
            duplicate_relation_response(relation) for relation in detail.duplicate_relations
        ],
        assignment=(
            assignment_response(detail.assignment) if detail.assignment is not None else None
        ),
        active_event_id=(detail.membership.event_id if detail.membership is not None else None),
        active_event_version_id=detail.active_event_version_id,
    )


def event_summary(row: EventListRow) -> EventSummaryResponse:
    summary_value = row.version.summary_projection.get("summary")
    return EventSummaryResponse(
        id=row.event.id,
        status=row.event.status,
        current_version_id=row.version.id,
        representative_title=row.version.representative_title,
        summary=summary_value if isinstance(summary_value, str) else None,
        event_time_start=row.version.event_time_start,
        event_time_end=row.version.event_time_end,
        source_diversity=row.version.source_diversity,
        categories=list(row.version.category_projection),
        member_count=row.member_count,
        review_count=row.review_count,
        updated_at=row.event.updated_at,
    )


def event_detail(detail: EventDetailProjection) -> EventDetailResponse:
    current_row = EventListRow(
        event=detail.event,
        version=detail.current_version,
        member_count=len(detail.members),
        review_count=len(detail.review_decisions),
    )
    summary = event_summary(current_row)
    return EventDetailResponse(
        **summary.model_dump(),
        created_at=detail.event.created_at,
        current_version=event_version_response(detail.current_version),
        versions=[event_version_response(version) for version in detail.versions],
        members=[event_member_response(member) for member in detail.members],
        review_decisions=[assignment_response(decision) for decision in detail.review_decisions],
    )


def event_member_response(member: EventMemberDetail) -> EventMemberResponse:
    return EventMemberResponse(
        membership_id=member.membership.id,
        normalized_article_id=member.article.id,
        candidate_id=member.candidate.id,
        title=member.candidate.title,
        original_url=member.candidate.original_url,
        canonical_url=member.candidate.canonical_url,
        published_at=member.candidate.published_at,
        active=member.membership.active,
        policy_version=member.membership.policy_version,
        analysis_id=member.analysis.id if member.analysis is not None else None,
        summary=member.analysis.summary if member.analysis is not None else None,
        passages=[passage_response(passage) for passage in member.passages],
        source_occurrences=[occurrence_response(occurrence) for occurrence in member.occurrences],
        assignment=assignment_response(member.decision),
    )


def event_version_response(version: EventClusterVersionModel) -> EventVersionResponse:
    return EventVersionResponse(
        id=version.id,
        event_id=version.event_id,
        version=version.version,
        representative_article_id=version.representative_article_id,
        representative_title=version.representative_title,
        summary_projection=version.summary_projection,
        event_time_start=version.event_time_start,
        event_time_end=version.event_time_end,
        event_time_precision=version.event_time_precision,
        member_set_hash=version.member_set_hash,
        source_diversity=version.source_diversity,
        category_projection=list(version.category_projection),
        entity_projection=list(version.entity_projection),
        clustering_policy_version=version.clustering_policy_version,
        version_bundle_fingerprint=version.version_bundle_fingerprint,
        created_by_run_id=version.created_by_run_id,
        created_at=version.created_at,
    )


def assignment_response(
    decision: EventAssignmentDecisionModel,
) -> EventAssignmentResponse:
    return EventAssignmentResponse(
        id=decision.id,
        normalized_article_id=decision.normalized_article_id,
        governance_run_id=decision.governance_run_id,
        selected_event_id=decision.selected_event_id,
        policy_version=decision.policy_version,
        outcome=decision.outcome,
        review_required=decision.outcome == "review_required",
        recent_window_start=decision.recent_window_start,
        recent_window_end=decision.recent_window_end,
        features=decision.features,
        thresholds=decision.thresholds,
        alternatives=decision.alternatives,
        created_at=decision.created_at,
    )


def passage_response(passage: NormalizedPassageModel) -> GovernancePassageResponse:
    return GovernancePassageResponse(
        id=passage.id,
        normalized_article_id=passage.normalized_article_id,
        ordinal=passage.ordinal,
        passage_hash=passage.passage_hash,
        text=passage.text,
        source_start=passage.source_start,
        source_end=passage.source_end,
    )


def occurrence_response(
    occurrence: ArticleOccurrenceModel,
) -> GovernanceOccurrenceResponse:
    return GovernanceOccurrenceResponse(
        id=occurrence.id,
        candidate_id=occurrence.candidate_id,
        observation_id=occurrence.observation_id,
        snapshot_id=occurrence.snapshot_id,
        source_id=occurrence.source_id,
        source_version_id=occurrence.source_version_id,
        source_item_id=occurrence.source_item_id,
        source_slug=occurrence.source_slug,
        source_display_name=occurrence.source_display_name,
        trust_tier=occurrence.trust_tier,
        original_url=occurrence.original_url,
        final_url=occurrence.final_url,
        published_at=occurrence.published_at,
        fetched_at=occurrence.fetched_at,
        parser_version=occurrence.parser_version,
        relevance_rule_version=occurrence.relevance_rule_version,
    )


def duplicate_relation_response(
    relation: DuplicateRelationModel,
) -> DuplicateRelationResponse:
    return DuplicateRelationResponse(
        id=relation.id,
        left_article_id=relation.left_article_id,
        right_article_id=relation.right_article_id,
        relation_kind=relation.relation_kind,
        policy_version=relation.policy_version,
        outcome=relation.outcome,
        threshold=relation.threshold,
        features=relation.features,
        created_at=relation.created_at,
    )


def _candidate_analysis_summary(
    *,
    analysis: CandidateAnalysisModel,
    normalized_article_id: UUID,
    candidate_id: UUID,
    title: str,
    original_url: str,
    canonical_url: str,
    published_at: datetime | None,
    primary_category: str | None,
) -> CandidateAnalysisSummaryResponse:
    return CandidateAnalysisSummaryResponse(
        candidate_id=candidate_id,
        normalized_article_id=normalized_article_id,
        analysis_id=analysis.id,
        title=title,
        original_url=original_url,
        canonical_url=canonical_url,
        published_at=published_at,
        status=analysis.status,
        summary=analysis.summary,
        primary_category=primary_category,
        keywords=list(analysis.keywords),
        event_time_start=analysis.event_time_start,
        event_time_end=analysis.event_time_end,
        event_time_precision=analysis.event_time_precision,
        provider=analysis.provider,
        model=analysis.model,
        prompt_version=analysis.prompt_version,
        schema_version=analysis.schema_version,
        taxonomy_version=analysis.taxonomy_version,
        created_at=analysis.created_at,
    )
