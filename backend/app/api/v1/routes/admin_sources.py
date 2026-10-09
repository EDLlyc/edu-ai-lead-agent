"""运营后台 · 新闻源: list, preview, add, edit, switch on/off and archive news sources."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_dependencies import admin_guard, require_admin
from app.api.dependencies import get_session
from app.application.services.admin_auth import AdminPrincipal
from app.application.services.source_admin import (
    SourceFetcher,
    archive_operator_source,
    create_operator_source,
    preview_source,
    set_source_enabled,
    update_operator_source,
)
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.domain.source_admin import (
    GENERIC_CONNECTOR_KEYS,
    OperatorSourceDraft,
    build_operator_source_draft,
)
from app.infrastructure.db.admin_auth import add_audit_event
from app.infrastructure.db.models import SourceModel
from app.infrastructure.db.source_admin import (
    AdminSourceRow,
    list_admin_sources,
    recent_source_articles,
)
from app.infrastructure.ingestion.fetcher import SafeHttpFetcher
from app.schemas.admin_sources import (
    AdminSourceArticle,
    AdminSourceArticleListResponse,
    AdminSourceConfig,
    AdminSourceDraftRequest,
    AdminSourceLatestJob,
    AdminSourceListResponse,
    AdminSourcePreviewLink,
    AdminSourcePreviewRequest,
    AdminSourcePreviewResponse,
    AdminSourcePreviewSample,
    AdminSourceResponse,
)

router = APIRouter(prefix="/admin/sources", tags=["admin"], dependencies=[Depends(admin_guard)])


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _fetcher(request: Request) -> SourceFetcher:
    # Tests install a fetcher with a mock transport; production builds the real one.
    injected = getattr(request.app.state, "source_admin_fetcher", None)
    if injected is not None:
        return cast(SourceFetcher, injected)
    return SafeHttpFetcher(_settings(request))


def _draft(body: AdminSourceDraftRequest) -> OperatorSourceDraft:
    return build_operator_source_draft(
        display_name=body.display_name,
        organization_type=body.organization_type,
        tier=body.tier,
        entry_url=body.entry_url,
        config=body.config.model_dump(),
    )


def _response(row: AdminSourceRow) -> AdminSourceResponse:
    source, version = row.source, row.version
    generic = version.connector_key in GENERIC_CONNECTOR_KEYS and version.connector_config
    config = AdminSourceConfig.model_validate(version.connector_config) if generic else None
    kind: Literal["code", "html", "rss"] = config.kind if config is not None else "code"
    job = row.latest_job
    return AdminSourceResponse(
        id=source.id,
        display_name=source.display_name,
        organization_type=source.organization_type,
        tier="A" if version.trust_tier == "A" else "B",
        managed_by="operator" if source.managed_by == "operator" else "seed",
        enabled=source.enabled,
        archived_at=source.archived_at,
        entry_url=version.entry_url,
        kind=kind,
        config=config,
        version=version.version,
        robots_status=version.robots_status,
        latest_job=None
        if job is None
        else AdminSourceLatestJob(
            status=job.status,
            outcome=job.outcome,
            error_code=job.error_code,
            new_count=job.new_count,
            filtered_count=job.filtered_count,
            duplicate_count=job.duplicate_count,
            completed_at=job.completed_at,
        ),
        new_last_7_days=row.new_last_7_days,
    )


async def _one(session: AsyncSession, source_id: UUID) -> AdminSourceResponse:
    rows = await list_admin_sources(session, now=datetime.now(UTC), include_archived=True)
    return _response(next(row for row in rows if row.source.id == source_id))


@router.get("", response_model=AdminSourceListResponse)
async def get_admin_sources(
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    include_archived: Annotated[bool, Query()] = False,
) -> AdminSourceListResponse:
    rows = await list_admin_sources(
        session, now=datetime.now(UTC), include_archived=include_archived
    )
    items = [_response(row) for row in rows]
    return AdminSourceListResponse(items=items, count=len(items))


@router.post("/preview", response_model=AdminSourcePreviewResponse)
async def post_admin_source_preview(
    body: AdminSourcePreviewRequest,
    request: Request,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminSourcePreviewResponse:
    draft = build_operator_source_draft(
        display_name="预览",
        organization_type="authoritative_media",
        tier="B",
        entry_url=body.entry_url,
        config=body.config.model_dump(),
    )
    now = datetime.now(UTC)
    preview = await preview_source(_fetcher(request), draft, settings=_settings(request), now=now)
    # A preview fetches someone else's site from our server; keep a record of who asked.
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="source.previewed",
        target_type="source_url",
        target_id=draft.host[:80],
        detail={"entry_url": draft.entry_url, "kind": draft.config.kind, "ok": preview.ok},
    )
    await session.commit()
    return AdminSourcePreviewResponse(
        ok=preview.ok,
        robots=preview.robots,
        problem=preview.problem,
        links=[
            AdminSourcePreviewLink(title=item.title, url=item.url, published_at=item.published_at)
            for item in preview.links
        ],
        samples=[
            AdminSourcePreviewSample(
                title=sample.title,
                url=sample.url,
                published_at=sample.published_at,
                characters=sample.characters,
                excerpt=sample.excerpt,
                freshness=sample.freshness,
                relevant=sample.relevant,
                topic=sample.topic,
                problem=sample.problem,
            )
            for sample in preview.samples
        ],
    )


@router.post("", response_model=AdminSourceResponse, status_code=status.HTTP_201_CREATED)
async def post_admin_source(
    body: AdminSourceDraftRequest,
    request: Request,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminSourceResponse:
    source, _version = await create_operator_source(
        session,
        _fetcher(request),
        _draft(body),
        principal=principal,
        settings=_settings(request),
        now=datetime.now(UTC),
    )
    return await _one(session, source.id)


@router.patch("/{source_id}", response_model=AdminSourceResponse)
async def patch_admin_source(
    source_id: UUID,
    body: AdminSourceDraftRequest,
    request: Request,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminSourceResponse:
    await update_operator_source(
        session,
        _fetcher(request),
        source_id,
        _draft(body),
        principal=principal,
        settings=_settings(request),
        now=datetime.now(UTC),
    )
    return await _one(session, source_id)


@router.post("/{source_id}/enable", response_model=AdminSourceResponse)
async def post_admin_source_enable(
    source_id: UUID,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminSourceResponse:
    await set_source_enabled(
        session, source_id, enabled=True, principal=principal, now=datetime.now(UTC)
    )
    return await _one(session, source_id)


@router.post("/{source_id}/disable", response_model=AdminSourceResponse)
async def post_admin_source_disable(
    source_id: UUID,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminSourceResponse:
    await set_source_enabled(
        session, source_id, enabled=False, principal=principal, now=datetime.now(UTC)
    )
    return await _one(session, source_id)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_source(
    source_id: UUID,
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await archive_operator_source(session, source_id, principal=principal, now=datetime.now(UTC))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/{source_id}/articles", response_model=AdminSourceArticleListResponse)
async def get_admin_source_articles(
    source_id: UUID,
    _principal: Annotated[AdminPrincipal, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=30)] = 10,
) -> AdminSourceArticleListResponse:
    if await session.get(SourceModel, source_id) is None:
        raise NotFoundError("source")
    rows = await recent_source_articles(session, source_id, limit=limit)
    items = [
        AdminSourceArticle(
            title=row.title,
            url=row.canonical_url,
            published_at=row.published_at,
            fetched_at=row.first_fetched_at,
        )
        for row in rows
    ]
    return AdminSourceArticleListResponse(items=items, count=len(items))
