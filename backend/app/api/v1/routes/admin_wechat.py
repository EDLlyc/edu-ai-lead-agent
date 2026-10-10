"""运营后台 · 公众号: accounts (owner); drafts, publishing, stats and 排版模板 (editor)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, cast
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_dependencies import admin_guard, require_admin, require_owner
from app.api.dependencies import get_session
from app.application.services.admin_auth import AdminPrincipal
from app.application.services.wechat_admin import (
    OPEN_STATUSES,
    account_client,
    bind_account,
    cancel_job,
    create_publish_job,
    list_accounts,
    list_jobs,
    poll_job,
    reconcile_job,
    update_account,
    verify_account,
    wechat_call_error,
)
from app.application.services.wechat_layout_templates import (
    layout_preview,
    list_account_layouts,
    set_layout_template,
)
from app.application.services.wechat_stats import account_stats, business_today, manual_sync
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.domain.official_account_layout_templates import (
    DEFAULT_LAYOUT_TEMPLATE_ID,
    LAYOUT_TEMPLATES,
)
from app.infrastructure.db.models import WeChatAccountModel, WeChatPublishJobModel
from app.infrastructure.wechat_official_account.admin_client import WeChatAdminError
from app.schemas.admin_wechat import (
    AdminLayoutAccount,
    AdminLayoutPreviewResponse,
    AdminLayoutTemplate,
    AdminLayoutTemplateSetRequest,
    AdminLayoutTemplatesResponse,
    AdminWeChatAccountCreateRequest,
    AdminWeChatAccountListResponse,
    AdminWeChatAccountOption,
    AdminWeChatAccountOptionsResponse,
    AdminWeChatAccountResponse,
    AdminWeChatAccountUpdateRequest,
    AdminWeChatArticleStats,
    AdminWeChatDailyStats,
    AdminWeChatDraft,
    AdminWeChatDraftArticle,
    AdminWeChatDraftListResponse,
    AdminWeChatPublished,
    AdminWeChatPublishedArticle,
    AdminWeChatPublishedListResponse,
    AdminWeChatPublishJob,
    AdminWeChatPublishJobListResponse,
    AdminWeChatPublishReconcileRequest,
    AdminWeChatPublishRequest,
    AdminWeChatStatsResponse,
    AdminWeChatStatusResponse,
    AdminWeChatSyncResponse,
)

router = APIRouter(prefix="/admin/wechat", tags=["admin"], dependencies=[Depends(admin_guard)])

Owner = Annotated[AdminPrincipal, Depends(require_owner)]
Operator = Annotated[AdminPrincipal, Depends(require_admin)]
Session = Annotated[AsyncSession, Depends(get_session)]


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _http(request: Request) -> httpx.AsyncClient | None:
    # Tests install a client with a mock transport; production opens one per call.
    return cast(httpx.AsyncClient | None, getattr(request.app.state, "wechat_http", None))


def _account(row: WeChatAccountModel) -> AdminWeChatAccountResponse:
    return AdminWeChatAccountResponse(
        id=row.id,
        name=row.name,
        app_id=row.app_id,
        secret_hint=f"••••{row.app_secret_last4}",
        topics=list(row.topics),
        enabled=row.enabled,
        last_verified_at=row.last_verified_at,
        last_verify_error=row.last_verify_error,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _stamp(value: int) -> datetime:
    return datetime.fromtimestamp(value, UTC)


@router.get("/status", response_model=AdminWeChatStatusResponse)
async def get_wechat_status(_operator: Operator, request: Request) -> AdminWeChatStatusResponse:
    key = _settings(request).admin_secret_key
    return AdminWeChatStatusResponse(
        secret_key_configured=key is not None and bool(key.get_secret_value().strip())
    )


@router.get("/accounts", response_model=AdminWeChatAccountListResponse)
async def get_wechat_accounts(_owner: Owner, session: Session) -> AdminWeChatAccountListResponse:
    items = [_account(row) for row in await list_accounts(session)]
    return AdminWeChatAccountListResponse(items=items, count=len(items))


@router.get("/account-options", response_model=AdminWeChatAccountOptionsResponse)
async def get_wechat_account_options(
    _operator: Operator, session: Session
) -> AdminWeChatAccountOptionsResponse:
    return AdminWeChatAccountOptionsResponse(
        items=[
            AdminWeChatAccountOption(id=row.id, name=row.name, topics=list(row.topics))
            for row in await list_accounts(session)
            if row.enabled
        ]
    )


@router.post(
    "/accounts", response_model=AdminWeChatAccountResponse, status_code=status.HTTP_201_CREATED
)
async def post_wechat_account(
    body: AdminWeChatAccountCreateRequest, owner: Owner, session: Session, request: Request
) -> AdminWeChatAccountResponse:
    row = await bind_account(
        session,
        settings=_settings(request),
        http=_http(request),
        actor_id=owner.user_id,
        actor=owner.username,
        name=body.name,
        app_id=body.app_id,
        app_secret=body.app_secret,
        topics=body.topics,
        now=datetime.now(UTC),
    )
    return _account(row)


@router.patch("/accounts/{account_id}", response_model=AdminWeChatAccountResponse)
async def patch_wechat_account(
    account_id: UUID,
    body: AdminWeChatAccountUpdateRequest,
    owner: Owner,
    session: Session,
    request: Request,
) -> AdminWeChatAccountResponse:
    row = await update_account(
        session,
        settings=_settings(request),
        http=_http(request),
        principal=owner,
        account_id=account_id,
        name=body.name,
        topics=body.topics,
        enabled=body.enabled,
        app_secret=body.app_secret,
        now=datetime.now(UTC),
    )
    return _account(row)


@router.post("/accounts/{account_id}/verify", response_model=AdminWeChatAccountResponse)
async def post_wechat_account_verify(
    account_id: UUID, owner: Owner, session: Session, request: Request
) -> AdminWeChatAccountResponse:
    row = await verify_account(
        session,
        settings=_settings(request),
        http=_http(request),
        principal=owner,
        account_id=account_id,
        now=datetime.now(UTC),
    )
    return _account(row)


@router.get("/accounts/{account_id}/drafts", response_model=AdminWeChatDraftListResponse)
async def get_wechat_drafts(
    account_id: UUID,
    _operator: Operator,
    session: Session,
    request: Request,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> AdminWeChatDraftListResponse:
    _row, client = await account_client(
        session, settings=_settings(request), http=_http(request), account_id=account_id
    )
    try:
        total, drafts = await client.drafts(offset=offset, count=20)
    except WeChatAdminError as error:
        raise wechat_call_error(error) from error
    open_jobs = {
        job.media_id: job.id
        for job in (
            await session.scalars(
                select(WeChatPublishJobModel).where(
                    WeChatPublishJobModel.account_id == account_id,
                    WeChatPublishJobModel.status.in_(OPEN_STATUSES),
                )
            )
        ).all()
    }
    return AdminWeChatDraftListResponse(
        total=total,
        items=[
            AdminWeChatDraft(
                media_id=draft.media_id,
                updated_at=_stamp(draft.updated_at),
                articles=[
                    AdminWeChatDraftArticle(title=a.title, author=a.author, digest=a.digest)
                    for a in draft.articles
                ],
                open_job_id=open_jobs.get(draft.media_id),
            )
            for draft in drafts
        ],
    )


@router.get("/accounts/{account_id}/published", response_model=AdminWeChatPublishedListResponse)
async def get_wechat_published(
    account_id: UUID,
    _operator: Operator,
    session: Session,
    request: Request,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> AdminWeChatPublishedListResponse:
    _row, client = await account_client(
        session, settings=_settings(request), http=_http(request), account_id=account_id
    )
    try:
        total, items = await client.published(offset=offset, count=20)
    except WeChatAdminError as error:
        raise wechat_call_error(error) from error
    return AdminWeChatPublishedListResponse(
        total=total,
        items=[
            AdminWeChatPublished(
                article_id=item.article_id,
                updated_at=_stamp(item.updated_at),
                articles=[
                    AdminWeChatPublishedArticle(title=a.title, url=a.url) for a in item.articles
                ],
            )
            for item in items
        ],
    )


async def _job(session: AsyncSession, job: WeChatPublishJobModel) -> AdminWeChatPublishJob:
    account = await session.get(WeChatAccountModel, job.account_id)
    return AdminWeChatPublishJob(
        id=job.id,
        account_id=job.account_id,
        account_name=account.name if account is not None else "",
        media_id=job.media_id,
        title=job.title,
        scheduled_at=job.scheduled_at,
        status=job.status,
        article_url=job.article_url,
        error=job.error,
        created_by=job.created_by,
        cancelled_by=job.cancelled_by,
        created_at=job.created_at,
        completed_at=job.completed_at,
        updated_at=job.updated_at,
        reconciled_by=job.reconciled_by,
        reconciliation_note=job.reconciliation_note,
        can_recheck=job.status in ("publishing", "outcome_unknown") and job.publish_id is not None,
    )


@router.get("/publish-jobs", response_model=AdminWeChatPublishJobListResponse)
async def get_wechat_publish_jobs(
    _operator: Operator, session: Session, account_id: UUID | None = None
) -> AdminWeChatPublishJobListResponse:
    jobs = await list_jobs(session, account_id=account_id)
    return AdminWeChatPublishJobListResponse(items=[await _job(session, job) for job in jobs])


@router.post(
    "/publish-jobs", response_model=AdminWeChatPublishJob, status_code=status.HTTP_201_CREATED
)
async def post_wechat_publish_job(
    body: AdminWeChatPublishRequest, operator: Operator, session: Session, request: Request
) -> AdminWeChatPublishJob:
    job = await create_publish_job(
        session,
        settings=_settings(request),
        http=_http(request),
        principal=operator,
        account_id=body.account_id,
        media_id=body.media_id,
        title=body.title,
        scheduled_at=body.scheduled_at,
        now=datetime.now(UTC),
    )
    return await _job(session, job)


@router.post("/publish-jobs/{job_id}/cancel", response_model=AdminWeChatPublishJob)
async def post_wechat_publish_job_cancel(
    job_id: UUID, operator: Operator, session: Session
) -> AdminWeChatPublishJob:
    job = await cancel_job(session, principal=operator, job_id=job_id, now=datetime.now(UTC))
    return await _job(session, job)


@router.post("/publish-jobs/{job_id}/recheck", response_model=AdminWeChatPublishJob)
async def post_wechat_publish_job_recheck(
    job_id: UUID, operator: Operator, session: Session, request: Request
) -> AdminWeChatPublishJob:
    job = await poll_job(
        session,
        settings=_settings(request),
        http=_http(request),
        job_id=job_id,
        principal=operator,
        now=datetime.now(UTC),
    )
    if job is None:
        raise NotFoundError("publish job")
    return await _job(session, job)


@router.post("/publish-jobs/{job_id}/reconcile", response_model=AdminWeChatPublishJob)
async def post_wechat_publish_job_reconcile(
    job_id: UUID, body: AdminWeChatPublishReconcileRequest, owner: Owner, session: Session
) -> AdminWeChatPublishJob:
    job = await reconcile_job(
        session,
        principal=owner,
        job_id=job_id,
        result=body.result,
        note=body.note,
        confirmed=body.confirmed,
        expected_updated_at=body.expected_updated_at,
        now=datetime.now(UTC),
    )
    return await _job(session, job)


@router.get("/accounts/{account_id}/stats", response_model=AdminWeChatStatsResponse)
async def get_wechat_stats(
    account_id: UUID,
    _operator: Operator,
    session: Session,
    request: Request,
    days: Annotated[int, Query(ge=7, le=90)] = 30,
) -> AdminWeChatStatsResponse:
    account = await session.get(WeChatAccountModel, account_id)
    if account is None:
        raise NotFoundError("wechat account")
    today = business_today(_settings(request), datetime.now(UTC))
    since, until = today - timedelta(days=days), today - timedelta(days=1)
    daily, articles = await account_stats(session, account_id=account_id, since=since, until=until)
    present = {row.ref_date for row in daily}
    return AdminWeChatStatsResponse(
        range_start=since,
        range_end=until,
        missing_dates=[
            since + timedelta(days=offset)
            for offset in range(days)
            if since + timedelta(days=offset) not in present
        ],
        synced_on=account.stats_synced_on,
        sync_error=account.stats_sync_error,
        daily=[
            AdminWeChatDailyStats(
                date=row.ref_date,
                read_user=row.read_user,
                share_user=row.share_user,
                like_user=row.like_user,
                zaikan_user=row.zaikan_user,
                comment_count=row.comment_count,
                collection_user=row.collection_user,
            )
            for row in daily
        ],
        articles=[
            AdminWeChatArticleStats(
                msgid=row.msgid,
                title=row.title,
                url=row.url,
                publish_date=row.publish_date,
                stat_date=row.stat_date,
                read_user=row.read_user,
                share_user=row.share_user,
                collection_user=row.collection_user,
                read_delivery_rate=row.read_delivery_rate,
                read_finish_rate=row.read_finish_rate,
                read_avg_activetime=row.read_avg_activetime,
                read_sources={str(k): int(v) for k, v in row.read_sources.items()},
            )
            for row in articles
        ],
    )


@router.post("/accounts/{account_id}/stats/sync", response_model=AdminWeChatSyncResponse)
async def post_wechat_stats_sync(
    account_id: UUID, operator: Operator, session: Session, request: Request
) -> AdminWeChatSyncResponse:
    report = await manual_sync(
        session,
        settings=_settings(request),
        http=_http(request),
        principal=operator,
        account_id=account_id,
        now=datetime.now(UTC),
    )
    return AdminWeChatSyncResponse(articles=report.articles, days=report.days)


def _layout_account(row: WeChatAccountModel) -> AdminLayoutAccount:
    return AdminLayoutAccount(id=row.id, name=row.name, layout_template_id=row.layout_template_id)


@router.get("/layout-templates", response_model=AdminLayoutTemplatesResponse)
async def get_layout_templates(
    _operator: Operator, session: Session
) -> AdminLayoutTemplatesResponse:
    return AdminLayoutTemplatesResponse(
        templates=[
            AdminLayoutTemplate(
                id=template.id,
                name=template.name,
                description=template.description,
                swatches=list(template.swatches),
                is_default=template.id == DEFAULT_LAYOUT_TEMPLATE_ID,
            )
            for template in LAYOUT_TEMPLATES
        ],
        accounts=[_layout_account(row) for row in await list_account_layouts(session)],
    )


@router.get("/layout-templates/{template_id}/preview", response_model=AdminLayoutPreviewResponse)
async def get_layout_template_preview(
    template_id: str, _operator: Operator
) -> AdminLayoutPreviewResponse:
    return AdminLayoutPreviewResponse(html=layout_preview(template_id))


@router.put("/accounts/{account_id}/layout-template", response_model=AdminLayoutAccount)
async def put_account_layout_template(
    account_id: UUID,
    body: AdminLayoutTemplateSetRequest,
    operator: Operator,
    session: Session,
) -> AdminLayoutAccount:
    row = await set_layout_template(
        session,
        principal=operator,
        account_id=account_id,
        template_id=body.template_id,
        now=datetime.now(UTC),
    )
    return _layout_account(row)
