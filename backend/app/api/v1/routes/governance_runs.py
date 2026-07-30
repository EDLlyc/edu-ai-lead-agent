from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.v1.routes.governance_views import (
    governance_job_response,
    governance_run_response,
)
from app.application.services.enqueue_governance import enqueue_governance_run
from app.application.services.governance_runtime import build_governance_version_bundle
from app.core.config import Settings
from app.infrastructure.db.governance_queries import (
    get_governance_run_with_usage,
    list_governance_jobs,
)
from app.infrastructure.db.governance_repositories import PostgresGovernanceRepository
from app.schemas.governance import (
    CreateGovernanceRunRequest,
    GovernanceJobListResponse,
    GovernanceRunResponse,
)

router = APIRouter(prefix="/governance-runs", tags=["governance"])


@router.post("", response_model=GovernanceRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_governance_run(
    payload: CreateGovernanceRunRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ] = None,
) -> GovernanceRunResponse:
    settings: Settings = request.app.state.settings
    repository = PostgresGovernanceRepository(request.app.state.session_factory)
    run_id = await enqueue_governance_run(
        repository,
        settings,
        build_governance_version_bundle(settings),
        acquisition_run_id=payload.acquisition_run_id,
        candidate_ids=payload.candidate_ids,
        idempotency_key=idempotency_key,
    )
    run, usage = await get_governance_run_with_usage(session, run_id)
    projected = governance_run_response(run, usage)
    response.headers["Location"] = projected.status_url
    return projected


@router.get("/{run_id}", response_model=GovernanceRunResponse)
async def get_governance_run(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GovernanceRunResponse:
    run, usage = await get_governance_run_with_usage(session, run_id)
    return governance_run_response(run, usage)


@router.get("/{run_id}/jobs", response_model=GovernanceJobListResponse)
async def get_governance_run_jobs(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: UUID | None = None,
) -> GovernanceJobListResponse:
    rows = await list_governance_jobs(
        session,
        run_id=run_id,
        limit=limit + 1,
        after=cursor,
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    return GovernanceJobListResponse(
        items=[governance_job_response(job) for job in page],
        next_cursor=page[-1].id if has_more and page else None,
    )
