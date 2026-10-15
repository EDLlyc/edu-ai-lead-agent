"""Operator-only "人工加推" for the local visitor adapter.

Mounted only by ``visitor_display_main`` when the operator PIN and a loopback production API
URL (the SSH tunnel) are configured. Unlike the opinion-only news review, this forwards one
operator-approved candidate to the production API, which runs the normal copy → image → WeCom →
long-image pipeline for it. The adapter's own database session stays read-only.
"""

from __future__ import annotations

from typing import Annotated, Any, cast, get_args

import httpx
from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse

from app.api.v1.routes.visitor_display import require_enabled, set_snapshot_headers
from app.api.v1.routes.visitor_display_review import OperatorGate
from app.application.services.visitor_display import VisitorDisplayService
from app.core.errors import NotFoundError
from app.infrastructure.db.visitor_display import PostgresVisitorDisplayRepository
from app.schemas.visitor_display import (
    VisitorDisplayHumanPick,
    VisitorDisplayHumanPickRequest,
    VisitorHumanPickRejection,
)

router = APIRouter(prefix="/visitor-display", tags=["visitor-display-human-pick"])

PRODUCTION_HUMAN_PICK_PATH = "/api/v1/content-slot-human-picks"
_REJECTIONS = frozenset(get_args(VisitorHumanPickRejection))


@router.post("/human-picks", response_model=VisitorDisplayHumanPick)
async def create_human_pick(
    body: VisitorDisplayHumanPickRequest,
    request: Request,
    response: Response,
    x_operator_pin: Annotated[str | None, Header()] = None,
) -> Any:
    secret = require_enabled(request)
    gate = getattr(request.app.state, "operator_gate", None)
    client = getattr(request.app.state, "human_pick_client", None)
    if not isinstance(gate, OperatorGate) or not isinstance(client, httpx.AsyncClient):
        raise NotFoundError("visitor human pick")
    gate.verify(x_operator_pin)
    service = VisitorDisplayService(
        repository=PostgresVisitorDisplayRepository(request.app.state.session_factory),
        asset_secret=secret,
    )
    source = await service.find_news_source(body.key)
    if source is None:
        raise NotFoundError("visitor news candidate")
    run_id, event_id = source
    upstream = await client.post(
        PRODUCTION_HUMAN_PICK_PATH,
        json={"source_run_id": str(run_id), "event_id": str(event_id), "note": body.note},
    )
    set_snapshot_headers(response)
    if upstream.status_code in {200, 201}:
        payload = upstream.json()
        return VisitorDisplayHumanPick(stage="queued", picked_at=payload["target_at"])
    code = _error_code(upstream)
    if upstream.status_code in {409, 422} and code in _REJECTIONS:
        # A known, operator-actionable refusal (already sent, too late, slot busy, ...).
        refused = JSONResponse(
            status_code=409,
            content={"error": {"code": code, "message": "human pick was refused"}},
        )
        set_snapshot_headers(refused)
        return refused
    if upstream.status_code == 404:
        raise NotFoundError("visitor news candidate")
    raise RuntimeError(f"production human pick returned {upstream.status_code}")


def _error_code(upstream: httpx.Response) -> str | None:
    try:
        payload = cast(dict[str, Any], upstream.json())
        code = payload["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return None
    return code if isinstance(code, str) else None


__all__ = ["PRODUCTION_HUMAN_PICK_PATH", "router"]
