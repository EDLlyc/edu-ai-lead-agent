from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.v1.routes.governance_views import event_detail, event_summary
from app.infrastructure.db.governance_queries import get_event_detail, list_event_rows
from app.schemas.governance import EventDetailResponse, EventListResponse

router = APIRouter(prefix="/events", tags=["governance"])


@router.get("", response_model=EventListResponse)
async def get_events(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: UUID | None = None,
) -> EventListResponse:
    rows = await list_event_rows(session, limit=limit + 1, after=cursor)
    has_more = len(rows) > limit
    page = rows[:limit]
    return EventListResponse(
        items=[event_summary(row) for row in page],
        next_cursor=page[-1].event.id if has_more and page else None,
    )


@router.get("/{event_id}", response_model=EventDetailResponse)
async def get_event(
    event_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventDetailResponse:
    return event_detail(await get_event_detail(session, event_id))
