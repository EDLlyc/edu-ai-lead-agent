"""运营后台 · 新闻审核: the operator's opinion on the AI's picks and rejections.

The page lists the recent news pools with the AI's verdict and score; a reviewer agrees, would
include or would exclude an item and may leave a note. A review is an opinion recorded with the
reviewer's account: it never changes a run, a score or a delivery.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.admin_dependencies import admin_guard, require_admin
from app.application.services.admin_auth import AdminPrincipal
from app.application.services.visitor_display import VisitorDisplayService
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.infrastructure.db.news_reviews import PostgresNewsReviewStore
from app.infrastructure.db.visitor_display import PostgresVisitorDisplayRepository
from app.infrastructure.visitor_review_store import NewsReviewSubject
from app.schemas.visitor_display import (
    VisitorDisplayHumanReview,
    VisitorDisplayNewsPool,
    VisitorDisplayNewsReviewRequest,
)

router = APIRouter(
    prefix="/admin/news-reviews", tags=["admin"], dependencies=[Depends(admin_guard)]
)

# The pool carries no picture URLs, so the exhibit's signed-asset secret is never used here.
_UNUSED_ASSET_SECRET = "admin-news-review-has-no-signed-assets"


def _service(request: Request, store: PostgresNewsReviewStore) -> VisitorDisplayService:
    session_factory = cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)
    return VisitorDisplayService(
        repository=PostgresVisitorDisplayRepository(session_factory),
        asset_secret=_UNUSED_ASSET_SECRET,
        reviews=store,
        # Picks are made in this console, so the pool shows their progress and the held copy.
        human_picks_enabled=_picks_enabled(request),
        human_pick_review=True,
    )


def _picks_enabled(request: Request) -> bool:
    settings = cast(Settings, request.app.state.settings)
    return bool(settings.content_enabled and settings.content_slot_mode_enabled)


def _store(request: Request) -> PostgresNewsReviewStore:
    return PostgresNewsReviewStore(
        cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)
    )


@router.get("", response_model=VisitorDisplayNewsPool)
async def get_admin_news_reviews(
    request: Request,
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
) -> VisitorDisplayNewsPool:
    return await _service(request, _store(request)).news_pool()


@router.post("", response_model=VisitorDisplayHumanReview)
async def post_admin_news_review(
    body: VisitorDisplayNewsReviewRequest,
    request: Request,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
) -> VisitorDisplayHumanReview:
    store = _store(request)
    found = await _service(request, store).find_news_candidate(body.key)
    if found is None:
        raise NotFoundError("news candidate")
    batch, candidate = found
    stored = await store.record(
        key=candidate.key,
        decision=body.decision,
        note=body.note,
        reviewer=principal.username,
        subject=NewsReviewSubject(
            title=candidate.title,
            source_name=candidate.source_name,
            ai_verdict=candidate.verdict,
            business_date=batch.business_date,
            slot=batch.slot,
            source_url=candidate.source_url,
            snippet=candidate.snippet,
            tier_label=candidate.tier_label,
            ai_score=candidate.score,
            ai_threshold=candidate.threshold,
            ai_rank=candidate.rank,
            ai_reasons=tuple(candidate.reasons),
        ),
    )
    return VisitorDisplayHumanReview(
        decision=cast(Any, stored.decision),
        note=stored.note,
        reviewed_at=stored.reviewed_at,
    )
