from __future__ import annotations

from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.application.services.copy_generation import build_copy_version_bundle
from app.core.config import Settings
from app.core.errors import ConflictError
from app.infrastructure.db.copy_generation import (
    PostgresCopyGenerationRepository,
    get_copy_generation_projection,
    get_copy_generation_run,
)
from app.infrastructure.db.models import CopyGenerationRunModel
from app.schemas.copy_generation import (
    CopyClaimResponse,
    CopyDraftResponse,
    CopyGenerationDetailResponse,
    CopyGenerationRunResponse,
    CreateCopyGenerationRunRequest,
)

router = APIRouter(tags=["copy-generation"])


@router.post(
    "/copy-generation-runs",
    response_model=CopyGenerationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_copy_generation_run(
    payload: CreateCopyGenerationRunRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CopyGenerationRunResponse:
    settings: Settings = request.app.state.settings
    if not settings.content_enabled:
        raise ConflictError("content production is disabled")
    repository = PostgresCopyGenerationRepository(request.app.state.session_factory)
    run_id = await repository.enqueue_for_daily_topic(
        business_date=payload.business_date,
        timezone=settings.business_timezone,
        scoring_profile=payload.scoring_profile,
        version_bundle=build_copy_version_bundle(
            settings,
            scoring_profile=payload.scoring_profile,
        ),
        max_attempts=settings.content_max_attempts,
    )
    projected = _run_response(await get_copy_generation_run(session, run_id))
    response.headers["Location"] = projected.status_url
    return projected


@router.get(
    "/copy-generation-runs/{run_id}",
    response_model=CopyGenerationRunResponse,
)
async def read_copy_generation_run(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CopyGenerationRunResponse:
    return _run_response(await get_copy_generation_run(session, run_id))


@router.get(
    "/copy-generation-runs/{run_id}/detail",
    response_model=CopyGenerationDetailResponse,
)
async def read_copy_generation_detail(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CopyGenerationDetailResponse:
    projection = await get_copy_generation_projection(session, run_id)
    run = _run_response(projection.run)
    drafts = []
    for stored in projection.drafts:
        issues = list(stored.validation_issues)
        if stored.audit is not None:
            issues.extend(stored.audit.issues)
        drafts.append(
            CopyDraftResponse(
                id=stored.id,
                version=stored.version,
                repair_of_version_id=stored.repair_of_version_id,
                copywriting=stored.draft.copywriting,
                parent_takeaway=stored.draft.parent_takeaway,
                interaction=stored.draft.interaction,
                source_note=stored.draft.source_note,
                image_prompt=stored.draft.image_prompt,
                validation_passed=stored.validation_passed,
                audit_accepted=stored.audit.accepted if stored.audit is not None else None,
                claims=[
                    CopyClaimResponse(
                        claim_id=claim.id,
                        text=claim.text,
                        kind=claim.kind,
                        evidence_ids=list(claim.evidence_ids),
                        brand_chunk_ids=list(claim.brand_chunk_ids),
                    )
                    for claim in stored.draft.claims
                ],
                issues=issues,
                created_at=stored.created_at,
            )
        )
    return CopyGenerationDetailResponse(**run.model_dump(), drafts=drafts)


def _run_response(run: CopyGenerationRunModel) -> CopyGenerationRunResponse:
    return CopyGenerationRunResponse(
        id=run.id,
        origin_kind=(
            "content_slot" if run.content_slot_selection_id is not None else "legacy_daily"
        ),
        daily_topic_selection_id=run.daily_topic_selection_id,
        content_slot_selection_id=run.content_slot_selection_id,
        business_date=run.business_date,
        timezone=run.timezone,
        scoring_profile=run.scoring_profile,
        decision_kind=cast(Literal["selected", "no_topic"], run.decision_kind),
        selected_event_id=run.selected_event_id,
        selected_event_version_id=run.selected_event_version_id,
        no_topic_code=run.no_topic_code,
        status=cast(
            Literal[
                "queued",
                "running",
                "no_topic",
                "accepted",
                "review_required",
                "failed",
            ],
            run.status,
        ),
        active_draft_version_id=run.active_draft_version_id,
        repair_count=run.repair_count,
        error_code=run.error_code,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        status_url=f"/api/v1/copy-generation-runs/{run.id}",
        detail_url=f"/api/v1/copy-generation-runs/{run.id}/detail",
    )
