from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.v1.routes.topic_selection_views import (
    topic_decision_kind,
    topic_rerank_summary,
    topic_score_response,
    topic_selection_run_response,
)
from app.application.services.topic_selection import enqueue_manual_topic_selection
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.infrastructure.db.topic_selection import (
    PostgresTopicSelectionRepository,
    get_daily_topic_result,
    get_topic_rerank_record,
    get_topic_selection_run,
    list_topic_score_rows,
)
from app.schemas.topic_selection import (
    CreateTopicSelectionRunRequest,
    DailyTopicResponse,
    TopicScoreListResponse,
    TopicSelectionRunResponse,
)

router = APIRouter(tags=["topic-selection"])


@router.post(
    "/topic-selection-runs",
    response_model=TopicSelectionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_topic_selection_run(
    payload: CreateTopicSelectionRunRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TopicSelectionRunResponse:
    settings: Settings = request.app.state.settings
    if not settings.content_enabled:
        raise ConflictError("content topic selection is disabled")
    repository = PostgresTopicSelectionRepository(request.app.state.session_factory)
    run_id = await enqueue_manual_topic_selection(
        repository,
        settings,
        business_date=payload.business_date,
        now=datetime.now(UTC),
    )
    run = await get_topic_selection_run(session, run_id)
    projected = topic_selection_run_response(
        run,
        await get_topic_rerank_record(session, topic_selection_run_id=run.id),
    )
    response.headers["Location"] = projected.status_url
    return projected


@router.get(
    "/topic-selection-runs/{run_id}",
    response_model=TopicSelectionRunResponse,
)
async def read_topic_selection_run(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TopicSelectionRunResponse:
    return topic_selection_run_response(
        await get_topic_selection_run(session, run_id),
        await get_topic_rerank_record(session, topic_selection_run_id=run_id),
    )


@router.get(
    "/topic-selection-runs/{run_id}/scores",
    response_model=TopicScoreListResponse,
)
async def read_topic_selection_scores(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TopicScoreListResponse:
    rows = await list_topic_score_rows(session, run_id)
    return TopicScoreListResponse(
        items=[topic_score_response(row) for row in rows],
        count=len(rows),
    )


@router.get("/daily-topics/{business_date}", response_model=DailyTopicResponse)
async def read_daily_topic(
    business_date: date,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    profile: Annotated[str, Query(min_length=1, max_length=40)] = "preview",
) -> DailyTopicResponse:
    settings: Settings = request.app.state.settings
    projection = await get_daily_topic_result(
        session,
        business_date=business_date,
        timezone=settings.business_timezone,
        scoring_profile=profile,
    )
    if projection is None:
        raise NotFoundError("daily topic")
    score_rows = await list_topic_score_rows(session, projection.run.id)
    selected_score = next(
        (
            topic_score_response(row)
            for row in score_rows
            if row.score.event_id == projection.selection.selected_event_id
        ),
        None,
    )
    config_version = projection.run.config_snapshot.get("version")
    rerank_record = await get_topic_rerank_record(session, topic_selection_run_id=projection.run.id)
    return DailyTopicResponse(
        business_date=projection.selection.business_date,
        timezone=projection.selection.timezone,
        scoring_version=(config_version if isinstance(config_version, str) else "unknown"),
        scoring_profile=projection.selection.scoring_profile,
        revision=projection.selection.revision,
        decision=topic_decision_kind(projection.selection.decision_kind),
        run_id=projection.run.id,
        selected_event_id=projection.selection.selected_event_id,
        selected_event_version_id=projection.selection.selected_event_version_id,
        no_topic_code=projection.selection.no_topic_code,
        decided_at=projection.selection.created_at,
        selected_score=selected_score,
        rerank=topic_rerank_summary(
            config_snapshot=projection.run.rerank_config_snapshot,
            config_fingerprint=projection.run.rerank_config_fingerprint,
            record=rerank_record,
        ),
    )
