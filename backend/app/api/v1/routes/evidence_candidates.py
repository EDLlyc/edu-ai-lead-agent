from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.infrastructure.db.models import EvidenceCandidateModel
from app.infrastructure.db.repositories import get_candidate_detail, list_candidates
from app.schemas.evidence import (
    EvidenceCandidateDetailResponse,
    EvidenceCandidateListResponse,
    EvidenceCandidateSummary,
    ObservationResponse,
    SnapshotMetadataResponse,
)

router = APIRouter(prefix="/evidence-candidates", tags=["evidence"])


def _summary(
    candidate: EvidenceCandidateModel, *, source_slug: str, source_display_name: str
) -> EvidenceCandidateSummary:
    return EvidenceCandidateSummary(
        id=candidate.id,
        source_id=candidate.source_id,
        source_slug=source_slug,
        source_display_name=source_display_name,
        source_item_id=candidate.source_item_id,
        original_url=candidate.original_url,
        canonical_url=candidate.canonical_url,
        trust_tier=candidate.trust_tier,
        title=candidate.title,
        published_at=candidate.published_at,
        first_fetched_at=candidate.first_fetched_at,
        language=candidate.language,
        content_hash=candidate.content_hash,
        parser_version=candidate.parser_version,
        relevance_rule_version=candidate.relevance_rule_version,
        created_at=candidate.created_at,
    )


@router.get("", response_model=EvidenceCandidateListResponse)
async def get_evidence_candidates(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: UUID | None = None,
    source_id: UUID | None = None,
    relevance_rule_version: Annotated[str | None, Query(max_length=40)] = None,
) -> EvidenceCandidateListResponse:
    candidates = await list_candidates(
        session,
        limit=limit + 1,
        after=cursor,
        source_id=source_id,
        relevance_rule_version=relevance_rule_version,
    )
    has_more = len(candidates) > limit
    page = candidates[:limit]
    return EvidenceCandidateListResponse(
        items=[EvidenceCandidateSummary.model_validate(candidate) for candidate in page],
        next_cursor=page[-1]["id"] if has_more and page else None,
    )


@router.get("/{candidate_id}", response_model=EvidenceCandidateDetailResponse)
async def get_evidence_candidate(
    candidate_id: UUID, session: Annotated[AsyncSession, Depends(get_session)]
) -> EvidenceCandidateDetailResponse:
    detail = await get_candidate_detail(session, candidate_id)
    candidate = detail["candidate"]
    snapshot = detail["snapshot"]
    source = detail["source"]
    if snapshot is None or source is None:
        raise RuntimeError("candidate provenance is incomplete")
    summary = _summary(
        candidate,
        source_slug=source.slug,
        source_display_name=source.display_name,
    )
    return EvidenceCandidateDetailResponse(
        **summary.model_dump(),
        clean_text=candidate.clean_text,
        extraction_metadata=candidate.extraction_metadata,
        snapshot=SnapshotMetadataResponse(
            id=snapshot.id,
            bucket=snapshot.bucket,
            object_key=snapshot.object_key,
            media_type=snapshot.media_type,
            byte_size=snapshot.byte_size,
            sha256=snapshot.sha256,
            fetched_at=snapshot.fetched_at,
        ),
        observations=[
            ObservationResponse(
                id=observation.id,
                run_id=observation.run_id,
                job_id=observation.job_id,
                outcome=observation.outcome,
                observed_at=observation.observed_at,
                error_code=observation.error_code,
                snapshot_id=observation.snapshot_id,
                metadata=observation.observation_metadata,
            )
            for observation in detail["observations"]
        ],
    )
