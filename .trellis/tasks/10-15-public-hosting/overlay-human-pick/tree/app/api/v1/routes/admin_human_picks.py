"""运营后台 · 人工加推: pick one news item, review the held copy, push it to the formal group.

The same production pipeline as the exhibit's 人工加推, called in-process with the signed-in
account as the reviewer. Creating a pick only makes the copy and the picture and holds them; a
push is the only call that reaches the formal WeCom group, and production refuses a second one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Path, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.admin_dependencies import admin_guard, require_admin
from app.api.dependencies import get_session
from app.application.services.admin_auth import AdminPrincipal
from app.application.services.human_pick_review import push_human_pick, revise_human_pick_copy
from app.application.services.visitor_display import (
    VisitorDisplayService,
    split_headline_hook_copy,
)
from app.core.config import Settings
from app.core.errors import NotFoundError, PolicyRejectedError
from app.infrastructure.db.content_slot_human_picks import create_human_pick
from app.infrastructure.db.visitor_display import (
    PostgresVisitorDisplayRepository,
    VisitorHumanPickReviewRow,
)
from app.schemas.visitor_display import (
    NEWS_KEY_PATTERN,
    VisitorDisplayHumanPick,
    VisitorDisplayHumanPickRequest,
    VisitorHumanPickCopyRequest,
    VisitorHumanPickIssue,
    VisitorHumanPickReview,
)

router = APIRouter(prefix="/admin/human-picks", tags=["admin"], dependencies=[Depends(admin_guard)])

# The pool carries no picture URLs, so the exhibit's signed-asset secret is never used here.
_UNUSED_ASSET_SECRET = "admin-human-pick-has-no-signed-assets"
NewsKey = Annotated[str, Path(pattern=NEWS_KEY_PATTERN)]
Principal = Annotated[AdminPrincipal, Depends(require_admin)]
Session = Annotated[AsyncSession, Depends(get_session)]


def _repository(request: Request) -> PostgresVisitorDisplayRepository:
    return PostgresVisitorDisplayRepository(
        cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)
    )


def _service(request: Request) -> VisitorDisplayService:
    return VisitorDisplayService(repository=_repository(request), asset_secret=_UNUSED_ASSET_SECRET)


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


@router.post("", response_model=VisitorDisplayHumanPick)
async def create_admin_human_pick(
    body: VisitorDisplayHumanPickRequest,
    request: Request,
    principal: Principal,
    session: Session,
) -> VisitorDisplayHumanPick:
    """Queue copy and picture for one candidate; nothing is sent to the group yet."""
    settings = _settings(request)
    if not settings.content_enabled or not settings.content_slot_mode_enabled:
        raise PolicyRejectedError("content_slot_disabled", "content slot mode is disabled")
    source = await _service(request).find_news_source(body.key)
    if source is None:
        raise NotFoundError("news candidate")
    source_run_id, event_id = source
    note = body.note or f"后台加推: {principal.username}"
    result = await create_human_pick(
        session,
        source_run_id=source_run_id,
        event_id=event_id,
        note=note[:280],
        now=datetime.now(UTC),
        timezone=settings.business_timezone,
        scoring_profile=settings.content_scoring_profile,
    )
    return VisitorDisplayHumanPick(stage="queued", picked_at=result.run.target_at)


@router.get("/{key}/review", response_model=VisitorHumanPickReview)
async def read_admin_human_pick_review(
    key: NewsKey, request: Request, _principal: Principal
) -> VisitorHumanPickReview:
    """The held pick's copy as it will be pushed."""
    row, now = await _held_pick(request, key)
    editable = (
        row.copywriting is not None
        and not row.pushed
        and row.package_review_status == "pending"
        and now < row.expires_at
    )
    return _review(
        row.copywriting,
        issues=row.issues,
        stage=_review_stage(row, now=now),
        editable=editable,
        push_deadline=row.expires_at,
    )


@router.post("/{key}/copy", response_model=VisitorHumanPickReview)
async def revise_admin_human_pick_copy(
    key: NewsKey,
    body: VisitorHumanPickCopyRequest,
    request: Request,
    principal: Principal,
    session: Session,
) -> VisitorHumanPickReview:
    """Check (``dry_run``) or save the hook and hashtags; the copy rules decide what passes."""
    row, now = await _held_pick(request, key)
    result = await revise_human_pick_copy(
        session,
        run_id=row.run_id,
        hook=body.hook,
        hashtags=tuple(body.hashtags),
        reviewer=principal.username,
        dry_run=body.dry_run,
        now=now,
    )
    revision = result.revision
    issues = tuple(
        {"code": issue.code, "severity": issue.severity, "message": issue.message}
        for issue in revision.issues
    )
    review = _review(
        revision.copywriting,
        issues=issues,
        stage="awaiting_review",
        editable=True,
        push_deadline=result.push_deadline,
    )
    # A failed check keeps what the operator typed, even when it could not be rendered.
    return review.model_copy(
        update={
            "hook": review.hook if review.copywriting is not None else body.hook.strip(),
            "passed": revision.passed,
            "saved": result.saved,
        }
    )


@router.post("/{key}/push", response_model=VisitorDisplayHumanPick)
async def push_admin_human_pick(
    key: NewsKey, request: Request, principal: Principal, session: Session
) -> VisitorDisplayHumanPick:
    """Send the held pick to the formal WeCom group now; a second push is refused."""
    row, now = await _held_pick(request, key)
    await push_human_pick(
        session,
        run_id=row.run_id,
        reviewer=principal.username,
        note=None,
        settings=_settings(request),
        now=now,
    )
    return VisitorDisplayHumanPick(stage="sending", picked_at=row.picked_at)


async def _held_pick(request: Request, key: str) -> tuple[VisitorHumanPickReviewRow, datetime]:
    source = await _service(request).find_news_source(key)
    if source is None:
        raise NotFoundError("news candidate")
    now = datetime.now(UTC)
    row = await _repository(request).load_human_pick_review(event_id=source[1], now=now)
    if row is None:
        raise NotFoundError("human pick")
    return row, now


def _review_stage(row: VisitorHumanPickReviewRow, *, now: datetime) -> str:
    if row.pushed or row.package_review_status == "approved":
        return "sending"
    if row.package_review_status == "rejected":
        return "failed"
    if now >= row.expires_at:
        return "expired"
    return "awaiting_review" if row.copywriting is not None else "imaging"


def _review(
    copywriting: str | None,
    *,
    issues: tuple[Any, ...],
    stage: str,
    editable: bool,
    push_deadline: datetime,
) -> VisitorHumanPickReview:
    parts = split_headline_hook_copy(copywriting) if copywriting else {}
    safe_issues: list[VisitorHumanPickIssue] = []
    for issue in issues[:40]:
        try:
            safe_issues.append(
                VisitorHumanPickIssue.model_validate(
                    {name: issue.get(name) for name in ("code", "severity", "message")}
                )
            )
        except (ValidationError, AttributeError):
            continue
    return VisitorHumanPickReview.model_validate(
        {
            "stage": stage,
            "editable": editable,
            "push_deadline": push_deadline,
            "copywriting": copywriting,
            **parts,
            "issues": safe_issues,
        }
    )
