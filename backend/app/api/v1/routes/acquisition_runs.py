from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.application.services.enqueue_runs import enqueue_manual_run
from app.core.config import Settings
from app.infrastructure.db.repositories import (
    PostgresAcquisitionRepository,
    get_run,
    list_run_jobs,
)
from app.schemas.acquisition import (
    AcquisitionJobListResponse,
    AcquisitionJobResponse,
    AcquisitionRunResponse,
    CreateAcquisitionRunRequest,
)

router = APIRouter(prefix="/acquisition-runs", tags=["acquisition"])


def _run_response(run: object) -> AcquisitionRunResponse:
    from app.infrastructure.db.models import AcquisitionRunModel

    assert isinstance(run, AcquisitionRunModel)
    return AcquisitionRunResponse(
        id=run.id,
        trigger=run.trigger,
        business_date=run.business_date,
        timezone=run.timezone,
        acquisition_version=run.acquisition_version,
        status=run.status,
        total_jobs=run.total_jobs,
        succeeded_jobs=run.succeeded_jobs,
        failed_jobs=run.failed_jobs,
        new_count=run.new_count,
        unchanged_count=run.unchanged_count,
        duplicate_count=run.duplicate_count,
        filtered_count=run.filtered_count,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        status_url=f"/api/v1/acquisition-runs/{run.id}",
    )


@router.post("", response_model=AcquisitionRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_acquisition_run(
    payload: CreateAcquisitionRunRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ] = None,
) -> AcquisitionRunResponse:
    repository = PostgresAcquisitionRepository(request.app.state.session_factory)
    settings: Settings = request.app.state.settings
    run_id, _created = await enqueue_manual_run(
        repository,
        settings,
        source_ids=payload.source_ids,
        idempotency_key=idempotency_key,
    )
    run = await get_run(session, run_id)
    response.headers["Location"] = f"/api/v1/acquisition-runs/{run.id}"
    return _run_response(run)


@router.get("/{run_id}", response_model=AcquisitionRunResponse)
async def get_acquisition_run(
    run_id: UUID, session: Annotated[AsyncSession, Depends(get_session)]
) -> AcquisitionRunResponse:
    return _run_response(await get_run(session, run_id))


@router.get("/{run_id}/jobs", response_model=AcquisitionJobListResponse)
async def get_acquisition_run_jobs(
    run_id: UUID, session: Annotated[AsyncSession, Depends(get_session)]
) -> AcquisitionJobListResponse:
    rows = await list_run_jobs(session, run_id)
    items = [AcquisitionJobResponse.model_validate(row) for row in rows]
    return AcquisitionJobListResponse(items=items, count=len(items))
