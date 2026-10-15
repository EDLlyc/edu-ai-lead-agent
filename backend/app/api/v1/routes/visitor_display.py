from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.application.services.visitor_display import (
    VisitorDisplayService,
    resolve_media_asset,
)
from app.application.services.visitor_moments import (
    MOMENT_ASSET_PREFIX,
    image_signature_matches,
    resolve_moment_asset,
)
from app.core.errors import ConflictError, NotFoundError
from app.infrastructure.db.visitor_display import (
    PostgresVisitorDisplayRepository,
    load_visible_ready_media,
)
from app.infrastructure.official_account_media import (
    OfficialAccountLocalMediaResolver,
    OfficialAccountMediaIntegrityError,
    persisted_media_snapshot,
)
from app.schemas.visitor_display import VisitorDisplaySnapshot

router = APIRouter(prefix="/visitor-display", tags=["visitor-display"])


@router.get("/snapshot", response_model=VisitorDisplaySnapshot)
async def read_snapshot(request: Request, response: Response) -> VisitorDisplaySnapshot:
    secret = require_enabled(request)
    service = VisitorDisplayService(
        repository=PostgresVisitorDisplayRepository(request.app.state.session_factory),
        asset_secret=secret,
        # Only the operator-local adapter wires a review store; the main API never does.
        reviews=getattr(request.app.state, "review_store", None),
        human_picks_enabled=getattr(request.app.state, "human_pick_client", None) is not None,
    )
    result = await service.snapshot()
    set_snapshot_headers(response)
    return result


@router.get("/assets/{asset_ref}", response_class=Response)
async def read_asset(
    asset_ref: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    secret = require_enabled(request)
    if asset_ref.startswith(MOMENT_ASSET_PREFIX):
        return await _read_moment_asset(request, secret=secret, asset_ref=asset_ref)
    media_rows = await load_visible_ready_media(session)
    media = resolve_media_asset(secret=secret, asset_ref=asset_ref, media=media_rows)
    resolver = OfficialAccountLocalMediaResolver(
        image_asset_manifest=getattr(request.app.state.settings, "image_asset_manifest", None),
        image_store=getattr(request.app.state, "image_store", None),
        snapshot_store=getattr(request.app.state, "snapshot_store", None),
    )
    snapshot = persisted_media_snapshot(media)
    try:
        body = await resolver.read_verified_bytes(session=session, media=snapshot)
    except OfficialAccountMediaIntegrityError as error:
        raise ConflictError("visitor display asset integrity check failed") from error
    return _asset_response(body, snapshot.media_type)


async def _read_moment_asset(request: Request, *, secret: str, asset_ref: str) -> Response:
    """A generated image or long image of one currently shown 朋友圈 post, re-verified."""
    rows = await PostgresVisitorDisplayRepository(request.app.state.session_factory).load_moments()
    image = resolve_moment_asset(secret=secret, asset_ref=asset_ref, rows=rows)
    store = getattr(request.app.state, "image_store", None)
    if store is None:
        raise NotFoundError("visitor display asset")
    body = await store.get_content_addressed_bytes(
        media_type=image.media_type, byte_size=image.byte_size, sha256=image.sha256
    )
    if not image_signature_matches(image.media_type, body):
        raise ConflictError("visitor display asset integrity check failed")
    return _asset_response(body, image.media_type)


def _asset_response(body: bytes, media_type: str) -> Response:
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=60",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


def require_enabled(request: Request) -> str:
    settings = request.app.state.settings
    if not getattr(settings, "visitor_display_enabled", False):
        raise NotFoundError("visitor display")
    configured = getattr(settings, "visitor_display_asset_secret", None)
    if not isinstance(configured, SecretStr):
        raise NotFoundError("visitor display")
    secret = configured.get_secret_value().strip()
    if len(secret.encode("utf-8")) < 32:
        raise NotFoundError("visitor display")
    return secret


def set_snapshot_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"


__all__ = ["router"]
