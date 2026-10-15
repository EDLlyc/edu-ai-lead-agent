"""Operator-only human news review for the local visitor adapter.

Mounted only by ``visitor_display_main`` when a local review store and operator PIN are
configured. A review is an opinion recorded in a local SQLite file; it never changes
production rows, starts generation, or touches WeChat/WeCom.
"""

from __future__ import annotations

import hmac
import time
from collections.abc import Callable
from typing import Annotated, Any, cast

from fastapi import APIRouter, Header, Request, Response
from starlette.exceptions import HTTPException

from app.api.v1.routes.visitor_display import require_enabled, set_snapshot_headers
from app.application.services.visitor_display import VisitorDisplayService
from app.core.errors import NotFoundError
from app.infrastructure.db.visitor_display import PostgresVisitorDisplayRepository
from app.infrastructure.visitor_review_store import NewsReviewSubject, VisitorReviewStore
from app.schemas.visitor_display import (
    VisitorDisplayHumanReview,
    VisitorDisplayNewsReviewRequest,
    VisitorDisplayOperatorSessionRequest,
)

router = APIRouter(prefix="/visitor-display", tags=["visitor-display-review"])


class OperatorGate:
    """Constant-time PIN check with a short lockout after repeated failures."""

    def __init__(
        self,
        pin: str,
        *,
        max_failures: int = 5,
        lockout_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 4 <= len(pin) <= 32:
            raise ValueError("operator PIN must be 4-32 characters")
        self._pin = pin.encode("utf-8")
        self._max_failures = max_failures
        self._lockout_seconds = lockout_seconds
        self._clock = clock
        self._failures = 0
        self._locked_until = 0.0

    def verify(self, candidate: str | None) -> None:
        now = self._clock()
        if now < self._locked_until:
            raise HTTPException(status_code=429)
        if candidate is not None and hmac.compare_digest(candidate.encode("utf-8"), self._pin):
            self._failures = 0
            return
        self._failures += 1
        if self._failures >= self._max_failures:
            self._failures = 0
            self._locked_until = now + self._lockout_seconds
        raise HTTPException(status_code=403)


@router.post("/operator/session", status_code=204, response_class=Response)
async def open_operator_session(
    body: VisitorDisplayOperatorSessionRequest, request: Request
) -> Response:
    require_enabled(request)
    _gate(request).verify(body.pin)
    response = Response(status_code=204)
    set_snapshot_headers(response)
    return response


@router.post("/news-reviews", response_model=VisitorDisplayHumanReview)
async def record_news_review(
    body: VisitorDisplayNewsReviewRequest,
    request: Request,
    response: Response,
    x_operator_pin: Annotated[str | None, Header()] = None,
) -> VisitorDisplayHumanReview:
    secret = require_enabled(request)
    _gate(request).verify(x_operator_pin)
    store = cast(VisitorReviewStore, request.app.state.review_store)
    service = VisitorDisplayService(
        repository=PostgresVisitorDisplayRepository(request.app.state.session_factory),
        asset_secret=secret,
        reviews=store,
    )
    found = await service.find_news_candidate(body.key)
    if found is None:
        raise NotFoundError("visitor news candidate")
    batch, candidate = found
    stored = await store.record(
        key=candidate.key,
        decision=body.decision,
        note=body.note,
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
    set_snapshot_headers(response)
    return VisitorDisplayHumanReview(
        decision=cast(Any, stored.decision),
        note=stored.note,
        reviewed_at=stored.reviewed_at,
    )


def _gate(request: Request) -> OperatorGate:
    gate = getattr(request.app.state, "operator_gate", None)
    if not isinstance(gate, OperatorGate):
        raise NotFoundError("visitor news review")
    return gate


__all__ = ["OperatorGate", "router"]
