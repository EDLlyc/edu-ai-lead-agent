# ruff: noqa: RUF001
"""公众号账号 and 发布 in the 运营后台.

Accounts:
- A bound account is verified with WeChat (`stable_token`) before it is saved.
- Its AppSecret is sealed with `ADMIN_SECRET_KEY` and never returned.
- Accounts are disabled, never deleted.

Publishing:
- A publish job takes one draft `media_id` either now (submitted in the request) or at a time,
  when the background loop submits it.
- A submitted job is polled with `freepublish/get` until it succeeds, fails, or is given up as
  `outcome_unknown` after 30 minutes.
- A timeout on submit is also `outcome_unknown` and is never retried automatically, because a
  second submit could publish twice.

Every action is audited without secrets.
"""

from __future__ import annotations

import re
import socket
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.services.admin_auth import AdminPrincipal
from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.domain.secret_box import SecretBoxError, last4, open_sealed, parse_key, seal
from app.domain.wechat_official_account_draft_jobs import wechat_draft_account_fingerprint
from app.infrastructure.db.admin_auth import add_audit_event
from app.infrastructure.db.models import WeChatAccountModel, WeChatPublishJobModel
from app.infrastructure.wechat_official_account.admin_client import (
    WeChatAdminClient,
    WeChatAdminError,
    WeChatAdminOutcomeUnknown,
    forget_token,
)

logger = structlog.get_logger()

_APP_ID = re.compile(r"^wx[0-9a-f]{16}$")
_SECRET = re.compile(r"^[0-9A-Za-z]{16,64}$")
PUBLISH_GIVE_UP_AFTER = timedelta(minutes=30)
SUBMIT_LEASE = timedelta(minutes=5)
OPEN_STATUSES = ("scheduled", "submitting", "publishing", "outcome_unknown", "succeeded")

PUBLISH_STATUS_TEXT = {
    0: "发布成功",
    1: "发布中",
    2: "原创声明失败",
    3: "发布失败",
    4: "平台审核不通过",
    5: "发布成功后，文章被删除",
    6: "发布成功后，文章被平台封禁",
}


class WeChatAdminRejected(AppError):
    def __init__(self, message: str, code: str = "wechat_admin_rejected", status: int = 422):
        super().__init__(code, message, status)


def secret_key(settings: Settings) -> bytes:
    configured = settings.admin_secret_key
    if configured is None or not configured.get_secret_value().strip():
        raise WeChatAdminRejected(
            "服务器还没配置加密密钥（ADMIN_SECRET_KEY），不能保存公众号密钥",
            "wechat_secret_key_missing",
            503,
        )
    try:
        return parse_key(configured.get_secret_value())
    except SecretBoxError as error:
        raise WeChatAdminRejected(
            "服务器的加密密钥格式不对", "wechat_secret_key_invalid", 503
        ) from error


def _purpose(app_id: str) -> str:
    return f"wechat_app_secret:{app_id}"


def _clean_name(value: str) -> str:
    name = " ".join(value.split())
    if not 1 <= len(name) <= 40:
        raise WeChatAdminRejected("名称要 1–40 个字")
    return name


def _clean_topics(values: list[str]) -> list[str]:
    topics: list[str] = []
    for raw in values:
        topic = " ".join(raw.split())
        if not topic:
            continue
        if len(topic) > 20:
            raise WeChatAdminRejected("每个主题最多 20 个字")
        if topic not in topics:
            topics.append(topic)
    if len(topics) > 10:
        raise WeChatAdminRejected("主题最多 10 个")
    return topics


def _check_credentials(app_id: str, app_secret: str) -> None:
    if not _APP_ID.fullmatch(app_id):
        raise WeChatAdminRejected("AppID 格式不对（wx 开头，后面 16 位）")
    if not _SECRET.fullmatch(app_secret):
        raise WeChatAdminRejected("AppSecret 格式不对")


async def _verify(app_id: str, app_secret: str, http: httpx.AsyncClient | None) -> None:
    forget_token(app_id)
    try:
        await WeChatAdminClient(app_id=app_id, app_secret=app_secret, client=http).token()
    except WeChatAdminError as error:
        raise WeChatAdminRejected(f"微信验证没通过：{error.message}") from error


async def list_accounts(session: AsyncSession) -> list[WeChatAccountModel]:
    return list(
        (
            await session.scalars(
                select(WeChatAccountModel).order_by(
                    WeChatAccountModel.enabled.desc(), WeChatAccountModel.created_at
                )
            )
        ).all()
    )


async def _account(
    session: AsyncSession, account_id: UUID, *, lock: bool = False
) -> WeChatAccountModel:
    statement = select(WeChatAccountModel).where(WeChatAccountModel.id == account_id)
    if lock:
        statement = statement.with_for_update()
    account = await session.scalar(statement)
    if account is None:
        raise NotFoundError("wechat account")
    return account


async def bind_account(
    session: AsyncSession,
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    actor_id: UUID | None,
    actor: str,
    name: str,
    app_id: str,
    app_secret: str,
    topics: list[str],
    now: datetime,
) -> WeChatAccountModel:
    key = secret_key(settings)
    app_id, app_secret = app_id.strip(), app_secret.strip()
    _check_credentials(app_id, app_secret)
    clean_name, clean_topics = _clean_name(name), _clean_topics(topics)
    if await session.scalar(
        select(WeChatAccountModel.id).where(WeChatAccountModel.app_id == app_id)
    ):
        raise ConflictError("这个公众号已经绑定过了")
    await _verify(app_id, app_secret, http)
    account = WeChatAccountModel(
        id=uuid4(),
        name=clean_name,
        app_id=app_id,
        account_fingerprint=wechat_draft_account_fingerprint(app_id),
        app_secret_sealed=seal(app_secret, key=key, purpose=_purpose(app_id)),
        app_secret_last4=last4(app_secret),
        topics=clean_topics,
        enabled=True,
        last_verified_at=now,
        last_verify_error=None,
        created_by=actor[:40],
        created_at=now,
        updated_at=now,
    )
    session.add(account)
    await session.flush()
    await add_audit_event(
        session,
        now=now,
        user_id=actor_id,
        username=actor,
        action="wechat_account.bound",
        target_type="wechat_account",
        target_id=str(account.id),
        detail={"name": clean_name, "app_id": app_id, "topics": clean_topics},
    )
    await session.commit()
    return account


async def update_account(
    session: AsyncSession,
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    principal: AdminPrincipal,
    account_id: UUID,
    name: str | None,
    topics: list[str] | None,
    enabled: bool | None,
    app_secret: str | None,
    now: datetime,
) -> WeChatAccountModel:
    account = await _account(session, account_id, lock=True)
    changed: list[str] = []
    if name is not None and _clean_name(name) != account.name:
        account.name = _clean_name(name)
        changed.append("name")
    if topics is not None and _clean_topics(topics) != account.topics:
        account.topics = _clean_topics(topics)
        changed.append("topics")
    if enabled is not None and enabled != account.enabled:
        account.enabled = enabled
        changed.append("enabled" if enabled else "disabled")
    if app_secret is not None and app_secret.strip():
        key = secret_key(settings)
        replacement = app_secret.strip()
        _check_credentials(account.app_id, replacement)
        await _verify(account.app_id, replacement, http)
        account.app_secret_sealed = seal(replacement, key=key, purpose=_purpose(account.app_id))
        account.app_secret_last4 = last4(replacement)
        account.last_verified_at = now
        account.last_verify_error = None
        changed.append("credentials")
    if not changed:
        await session.rollback()
        return account
    account.updated_at = now
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="wechat_account.updated",
        target_type="wechat_account",
        target_id=str(account.id),
        detail={"name": account.name, "changed": changed},
    )
    await session.commit()
    return account


def _client(
    account: WeChatAccountModel, settings: Settings, http: httpx.AsyncClient | None
) -> WeChatAdminClient:
    try:
        app_secret = open_sealed(
            account.app_secret_sealed, key=secret_key(settings), purpose=_purpose(account.app_id)
        )
    except SecretBoxError as error:
        raise WeChatAdminRejected(
            "存的公众号密钥解不开（服务器密钥变了？），请重新填写 AppSecret",
            "wechat_secret_unreadable",
            409,
        ) from error
    return WeChatAdminClient(app_id=account.app_id, app_secret=app_secret, client=http)


async def verify_account(
    session: AsyncSession,
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    principal: AdminPrincipal,
    account_id: UUID,
    now: datetime,
) -> WeChatAccountModel:
    account = await _account(session, account_id, lock=True)
    client = _client(account, settings, http)
    forget_token(account.app_id)
    try:
        await client.token()
        account.last_verified_at, account.last_verify_error = now, None
    except WeChatAdminError as error:
        account.last_verify_error = error.message[:200]
    account.updated_at = now
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="wechat_account.verified",
        target_type="wechat_account",
        target_id=str(account.id),
        detail={"name": account.name, "ok": account.last_verify_error is None},
    )
    await session.commit()
    return account


async def account_client(
    session: AsyncSession,
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    account_id: UUID,
) -> tuple[WeChatAccountModel, WeChatAdminClient]:
    account = await _account(session, account_id)
    if not account.enabled:
        raise WeChatAdminRejected("这个公众号已停用", "wechat_account_disabled", 409)
    return account, _client(account, settings, http)


def wechat_call_error(error: WeChatAdminError) -> WeChatAdminRejected:
    return WeChatAdminRejected(error.message, "wechat_call_failed", 502)


# ---- publishing ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoopReport:
    submitted: int
    polled: int
    recovered: int


async def create_publish_job(
    session: AsyncSession,
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    principal: AdminPrincipal,
    account_id: UUID,
    media_id: str,
    title: str,
    scheduled_at: datetime | None,
    now: datetime,
) -> WeChatPublishJobModel:
    account, _ = await account_client(session, settings=settings, http=http, account_id=account_id)
    media = media_id.strip()
    if not media or len(media) > 128:
        raise WeChatAdminRejected("草稿编号不对")
    if scheduled_at is not None:
        if scheduled_at.tzinfo is None:
            raise WeChatAdminRejected("定时发布的时间要带时区")
        if scheduled_at < now + timedelta(minutes=2):
            raise WeChatAdminRejected("定时发布至少要比现在晚 2 分钟")
        if scheduled_at > now + timedelta(days=30):
            raise WeChatAdminRejected("定时发布最多排到 30 天后")
    job = WeChatPublishJobModel(
        id=uuid4(),
        account_id=account.id,
        media_id=media,
        title=(" ".join(title.split()) or "（无标题）")[:200],
        scheduled_at=scheduled_at or now,
        status="scheduled",
        created_by=principal.username,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise ConflictError("这篇草稿已发布、正在发布或结果待核对，不能重复提交") from error
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="wechat.publish_scheduled" if scheduled_at else "wechat.publish_requested",
        target_type="wechat_publish_job",
        target_id=str(job.id),
        detail={
            "account": account.name,
            "title": job.title,
            "scheduled_at": job.scheduled_at.isoformat(),
        },
    )
    await session.commit()
    if scheduled_at is None:
        await submit_job(session, settings=settings, http=http, job_id=job.id, now=now)
        await session.refresh(job)
    return job


async def submit_job(
    session: AsyncSession,
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    job_id: UUID,
    now: datetime,
    worker: str = "api",
) -> None:
    job = await session.scalar(
        select(WeChatPublishJobModel)
        .where(WeChatPublishJobModel.id == job_id, WeChatPublishJobModel.status == "scheduled")
        .with_for_update(skip_locked=True)
    )
    if job is None:
        await session.rollback()
        return
    account = await session.get(WeChatAccountModel, job.account_id)
    if account is None or not account.enabled:
        job.status, job.error, job.completed_at = "failed", "公众号已停用", now
        job.updated_at = now
        await session.commit()
        return
    claim = f"{worker[:90]}:{uuid4().hex}"
    job.status, job.lease_owner = "submitting", claim
    job.lease_expires_at, job.updated_at = now + SUBMIT_LEASE, now
    media_id, account_name = job.media_id, account.name
    await session.commit()
    publish_id: str | None = None
    failure: tuple[str, str] | None = None
    try:
        publish_id = await _client(account, settings, http).submit(media_id)
    except WeChatAdminOutcomeUnknown as error:
        failure = ("outcome_unknown", error.message)
    except (WeChatAdminError, WeChatAdminRejected) as error:
        failure = ("failed", error.message)
    # A recovered lease or operator reconciliation owns the newer decision. Never overwrite it
    # with a response from an old submit, and never automatically send that draft again.
    current = await session.scalar(
        select(WeChatPublishJobModel)
        .where(
            WeChatPublishJobModel.id == job_id,
            WeChatPublishJobModel.status == "submitting",
            WeChatPublishJobModel.lease_owner == claim,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None:
        await session.rollback()
        return
    if failure is not None:
        await _finish(session, current, failure[0], now, error=failure[1])
        return
    current.status, current.publish_id, current.submitted_at = "publishing", publish_id, now
    current.lease_owner, current.lease_expires_at, current.updated_at = None, None, now
    await add_audit_event(
        session,
        now=now,
        user_id=None,
        username="system",
        action="wechat.publish_submitted",
        target_type="wechat_publish_job",
        target_id=str(current.id),
        detail={"account": account_name, "title": current.title},
    )
    await session.commit()


async def _finish(
    session: AsyncSession,
    job: WeChatPublishJobModel,
    status: str,
    now: datetime,
    *,
    error: str | None = None,
    wechat_status: int | None = None,
) -> None:
    job.status, job.error, job.wechat_status = (
        status,
        (error or None) and error[:200],
        wechat_status,
    )
    job.completed_at, job.updated_at = now, now
    job.lease_owner, job.lease_expires_at = None, None
    await add_audit_event(
        session,
        now=now,
        user_id=None,
        username="system",
        action=f"wechat.publish_{status}",
        target_type="wechat_publish_job",
        target_id=str(job.id),
        detail={"title": job.title, "error": job.error, "article_url": job.article_url},
    )
    await session.commit()


async def poll_job(
    session: AsyncSession,
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    job_id: UUID,
    now: datetime,
    principal: AdminPrincipal | None = None,
) -> WeChatPublishJobModel | None:
    allowed = ("publishing", "outcome_unknown") if principal else ("publishing",)
    job: WeChatPublishJobModel | None = await session.scalar(
        select(WeChatPublishJobModel)
        .where(WeChatPublishJobModel.id == job_id)
        .execution_options(populate_existing=True)
    )
    if job is None:
        if principal:
            raise NotFoundError("publish job")
        await session.rollback()
        return None
    if job.status not in allowed or job.publish_id is None:
        if principal:
            raise ConflictError("只有有发布编号且仍待核对的记录可以重新查询")
        await session.rollback()
        return None
    expected = (job.status, job.updated_at, job.publish_id)
    account = await session.get(WeChatAccountModel, job.account_id)
    # End the read transaction before the provider request. Reacquire a lock and compare the
    # observed state afterwards, so a slow poll cannot undo a newer reconciliation/result.
    await session.commit()
    state = None
    poll_error: str | None = None
    try:
        if account is None:
            raise WeChatAdminRejected("公众号不存在，无法查询")
        state = await _client(account, settings, http).publish_status(expected[2])
    except (WeChatAdminError, WeChatAdminRejected) as error:
        poll_error = error.message
        logger.warning("wechat_publish_poll_failed", job_id=str(job_id), code=error.code)
    job = await session.scalar(
        select(WeChatPublishJobModel)
        .where(WeChatPublishJobModel.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        await session.rollback()
        return None
    changed = (job.status, job.updated_at, job.publish_id) != expected
    if principal:
        await add_audit_event(
            session,
            now=now,
            user_id=principal.user_id,
            username=principal.username,
            action="wechat.publish_rechecked",
            target_type="wechat_publish_job",
            target_id=str(job.id),
            detail={"ok": state is not None, "ignored_newer_state": changed},
        )
    if changed:
        await session.commit()
        return job
    expired = now - (job.submitted_at or job.created_at) >= PUBLISH_GIVE_UP_AFTER
    if state is None:
        if expired or job.status == "outcome_unknown":
            await _finish(
                session,
                job,
                "outcome_unknown",
                now,
                error="未能核实发布结果，请重新查询或到公众号后台核对："
                + (poll_error or "查询失败"),
            )
        else:
            job.error, job.updated_at = poll_error, now
            await session.commit()
    elif state.status == 0:
        job.article_id, job.article_url = state.article_id, state.article_url
        await _finish(session, job, "succeeded", now, wechat_status=0)
    elif state.status == 1:
        if expired or job.status == "outcome_unknown":
            await _finish(
                session,
                job,
                "outcome_unknown",
                now,
                error="微信超过 30 分钟仍未确认结果，请到公众号后台核对",
                wechat_status=1,
            )
        else:
            job.wechat_status, job.error, job.updated_at = 1, None, now
            await session.commit()
    elif state.status in (5, 6):
        # It was published before deletion/platform blocking; a retry would be a second publish.
        await _finish(
            session,
            job,
            "succeeded",
            now,
            error=PUBLISH_STATUS_TEXT[state.status],
            wechat_status=state.status,
        )
    else:
        await _finish(
            session,
            job,
            "failed",
            now,
            error=PUBLISH_STATUS_TEXT[state.status],
            wechat_status=state.status,
        )
    return job


async def reconcile_job(
    session: AsyncSession,
    *,
    principal: AdminPrincipal,
    job_id: UUID,
    result: Literal["published", "not_published"],
    note: str,
    confirmed: bool,
    expected_updated_at: datetime,
    now: datetime,
) -> WeChatPublishJobModel:
    if principal.role != "owner":
        raise WeChatAdminRejected("只有管理员可以确认核对结果", "admin_owner_required", 403)
    clean_note = " ".join(note.split())
    if not confirmed or not 5 <= len(clean_note) <= 500:
        raise WeChatAdminRejected("请确认已在公众号后台核对，并填写 5–500 字的核对依据")
    job = await session.scalar(
        select(WeChatPublishJobModel)
        .where(WeChatPublishJobModel.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise NotFoundError("publish job")
    if job.status != "outcome_unknown" or job.updated_at != expected_updated_at:
        raise ConflictError("发布记录已经变化，请刷新后重新核对")
    job.status = "succeeded" if result == "published" else "failed"
    job.reconciled_by, job.reconciliation_note = principal.username, clean_note
    job.error = None if result == "published" else "已人工核对未发布，可以重新提交"
    job.completed_at, job.updated_at = now, now
    job.lease_owner, job.lease_expires_at = None, None
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="wechat.publish_reconciled",
        target_type="wechat_publish_job",
        target_id=str(job.id),
        detail={"result": result, "note": clean_note, "previous_status": "outcome_unknown"},
    )
    await session.commit()
    return job


async def run_publish_loop_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    now: datetime,
    worker: str | None = None,
) -> LoopReport:
    """Submit due scheduled jobs, poll publishing ones, give up on stuck submits."""

    name = worker or f"{socket.gethostname()}:wechat-publish"
    async with session_factory() as session:
        stale = (
            WeChatPublishJobModel.status == "submitting",
            or_(
                WeChatPublishJobModel.lease_expires_at.is_(None),
                WeChatPublishJobModel.lease_expires_at < now,
            ),
        )
        stuck_ids = list(
            (await session.scalars(select(WeChatPublishJobModel.id).where(*stale).limit(20))).all()
        )
        await session.commit()
        recovered = 0
        for job_id in stuck_ids:
            job = await session.scalar(
                select(WeChatPublishJobModel)
                .where(WeChatPublishJobModel.id == job_id, *stale)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
            if job is None:
                await session.rollback()
                continue
            await _finish(
                session,
                job,
                "outcome_unknown",
                now,
                error="提交时服务中断，请到公众号后台确认是否已发布",
            )
            recovered += 1
        due_ids = list(
            (
                await session.scalars(
                    select(WeChatPublishJobModel.id)
                    .where(
                        WeChatPublishJobModel.status == "scheduled",
                        WeChatPublishJobModel.scheduled_at <= now,
                    )
                    .order_by(WeChatPublishJobModel.scheduled_at)
                    .limit(5)
                )
            ).all()
        )
        publishing_ids = list(
            (
                await session.scalars(
                    select(WeChatPublishJobModel.id)
                    .where(WeChatPublishJobModel.status == "publishing")
                    .limit(20)
                )
            ).all()
        )
    for job_id in due_ids:
        async with session_factory() as session:
            await submit_job(
                session, settings=settings, http=http, job_id=job_id, now=now, worker=name
            )
    for job_id in publishing_ids:
        async with session_factory() as session:
            await poll_job(session, settings=settings, http=http, job_id=job_id, now=now)
    return LoopReport(submitted=len(due_ids), polled=len(publishing_ids), recovered=recovered)


async def cancel_job(
    session: AsyncSession, *, principal: AdminPrincipal, job_id: UUID, now: datetime
) -> WeChatPublishJobModel:
    job = await session.scalar(
        select(WeChatPublishJobModel).where(WeChatPublishJobModel.id == job_id).with_for_update()
    )
    if job is None:
        raise NotFoundError("publish job")
    if job.status != "scheduled":
        await session.rollback()
        raise ConflictError("只有还没开始的定时发布可以取消")
    job.status, job.cancelled_by = "cancelled", principal.username
    job.completed_at, job.updated_at = now, now
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="wechat.publish_cancelled",
        target_type="wechat_publish_job",
        target_id=str(job.id),
        detail={"title": job.title, "scheduled_at": job.scheduled_at.isoformat()},
    )
    await session.commit()
    return job


async def list_jobs(
    session: AsyncSession,
    *,
    account_id: UUID | None,
    business_timezone: str,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[int, list[WeChatPublishJobModel]]:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise WeChatAdminRejected("创建日期的开始日期不能晚于结束日期", "invalid_date_range")
    # Bound the selected rows and count the exact same predicates. Business dates
    # are inclusive; the UTC upper bound is the next local midnight (also across DST).
    predicates = []
    if account_id is not None:
        predicates.append(WeChatPublishJobModel.account_id == account_id)
    if status is not None:
        predicates.append(WeChatPublishJobModel.status == status)
    zone = ZoneInfo(business_timezone)
    if date_from is not None:
        since = datetime.combine(date_from, time.min, zone).astimezone(UTC)
        predicates.append(WeChatPublishJobModel.created_at >= since)
    if date_to is not None:
        until = datetime.combine(date_to + timedelta(days=1), time.min, zone).astimezone(UTC)
        predicates.append(WeChatPublishJobModel.created_at < until)
    total = await session.scalar(
        select(func.count()).select_from(WeChatPublishJobModel).where(*predicates)
    )
    statement = (
        select(WeChatPublishJobModel)
        .where(*predicates)
        .order_by(WeChatPublishJobModel.created_at.desc(), WeChatPublishJobModel.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return int(total or 0), list((await session.scalars(statement)).all())


__all__ = [
    "OPEN_STATUSES",
    "PUBLISH_STATUS_TEXT",
    "LoopReport",
    "WeChatAdminRejected",
    "account_client",
    "bind_account",
    "cancel_job",
    "create_publish_job",
    "list_accounts",
    "list_jobs",
    "poll_job",
    "reconcile_job",
    "run_publish_loop_once",
    "secret_key",
    "submit_job",
    "update_account",
    "verify_account",
    "wechat_call_error",
]
