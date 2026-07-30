from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.v1.routes.governance_views import (
    candidate_analysis_detail,
    candidate_analysis_summary,
)
from app.infrastructure.db.governance_queries import (
    get_candidate_governance_detail,
    list_candidate_analysis_rows,
)
from app.schemas.governance import (
    CandidateAnalysisDetailResponse,
    CandidateAnalysisListResponse,
)

router = APIRouter(prefix="/candidate-analyses", tags=["governance"])


@router.get("", response_model=CandidateAnalysisListResponse)
async def get_candidate_analyses(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: UUID | None = None,
) -> CandidateAnalysisListResponse:
    rows = await list_candidate_analysis_rows(
        session,
        limit=limit + 1,
        after=cursor,
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    return CandidateAnalysisListResponse(
        items=[candidate_analysis_summary(row) for row in page],
        next_cursor=page[-1].analysis.id if has_more and page else None,
    )


@router.get("/{candidate_id}", response_model=CandidateAnalysisDetailResponse)
async def get_candidate_analysis(
    candidate_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CandidateAnalysisDetailResponse:
    return candidate_analysis_detail(await get_candidate_governance_detail(session, candidate_id))
