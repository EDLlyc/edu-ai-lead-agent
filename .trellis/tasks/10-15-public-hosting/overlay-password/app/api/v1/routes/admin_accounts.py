"""运营后台 · 账号管理 (owner only): list, create, reset password, disable/enable, edit."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_dependencies import admin_guard, require_owner
from app.api.dependencies import get_session
from app.application.services.admin_accounts import (
    AccountView,
    create_account,
    list_accounts,
    reset_account_password,
    set_account_active,
    update_account,
)
from app.application.services.admin_auth import AdminPrincipal
from app.schemas.admin import (
    AdminAccountCreateRequest,
    AdminAccountListResponse,
    AdminAccountResetRequest,
    AdminAccountResponse,
    AdminAccountUpdateRequest,
    AdminAccountWithPasswordResponse,
)

router = APIRouter(prefix="/admin/accounts", tags=["admin"], dependencies=[Depends(admin_guard)])

Owner = Annotated[AdminPrincipal, Depends(require_owner)]
Session = Annotated[AsyncSession, Depends(get_session)]


def _account(view: AccountView) -> AdminAccountResponse:
    return AdminAccountResponse(
        username=view.username,
        display_name=view.display_name,
        role=view.role,
        active=view.active,
        locked=view.locked,
        last_login_at=view.last_login_at,
        created_at=view.created_at,
        live_sessions=view.live_sessions,
    )


@router.get("", response_model=AdminAccountListResponse)
async def get_admin_accounts(_owner: Owner, session: Session) -> AdminAccountListResponse:
    items = [_account(view) for view in await list_accounts(session, now=datetime.now(UTC))]
    return AdminAccountListResponse(items=items, count=len(items))


@router.post(
    "", response_model=AdminAccountWithPasswordResponse, status_code=status.HTTP_201_CREATED
)
async def post_admin_account(
    body: AdminAccountCreateRequest, owner: Owner, session: Session
) -> AdminAccountWithPasswordResponse:
    view, password = await create_account(
        session,
        principal=owner,
        username=body.username,
        display_name=body.display_name,
        role=body.role,
        now=datetime.now(UTC),
        password=body.password,
    )
    return AdminAccountWithPasswordResponse(account=_account(view), initial_password=password)


@router.patch("/{username}", response_model=AdminAccountResponse)
async def patch_admin_account(
    username: str, body: AdminAccountUpdateRequest, owner: Owner, session: Session
) -> AdminAccountResponse:
    view = await update_account(
        session,
        principal=owner,
        username=username,
        display_name=body.display_name,
        role=body.role,
        now=datetime.now(UTC),
    )
    return _account(view)


@router.post("/{username}/reset-password", response_model=AdminAccountWithPasswordResponse)
async def post_admin_account_reset(
    username: str,
    owner: Owner,
    session: Session,
    body: AdminAccountResetRequest | None = None,
) -> AdminAccountWithPasswordResponse:
    now = datetime.now(UTC)
    password = await reset_account_password(
        session,
        principal=owner,
        username=username,
        now=now,
        password=None if body is None else body.password,
    )
    view = next(item for item in await list_accounts(session, now=now) if item.username == username)
    return AdminAccountWithPasswordResponse(account=_account(view), initial_password=password)


@router.post("/{username}/disable", response_model=AdminAccountResponse)
async def post_admin_account_disable(
    username: str, owner: Owner, session: Session
) -> AdminAccountResponse:
    return _account(
        await set_account_active(
            session, principal=owner, username=username, active=False, now=datetime.now(UTC)
        )
    )


@router.post("/{username}/enable", response_model=AdminAccountResponse)
async def post_admin_account_enable(
    username: str, owner: Owner, session: Session
) -> AdminAccountResponse:
    return _account(
        await set_account_active(
            session, principal=owner, username=username, active=True, now=datetime.now(UTC)
        )
    )
