from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.infrastructure.db.repositories import list_sources
from app.schemas.acquisition import SourceListResponse, SourceResponse

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=SourceListResponse)
async def get_sources(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SourceListResponse:
    rows = await list_sources(session)
    items = [SourceResponse.model_validate(row) for row in rows]
    return SourceListResponse(items=items, count=len(items))
