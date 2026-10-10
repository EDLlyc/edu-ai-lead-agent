"""运营后台 · 模型配置 (owner only): model provider keys, tested before every switch."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, cast
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Request, status
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_dependencies import admin_guard, require_owner
from app.api.dependencies import get_session
from app.application.services.admin_auth import AdminPrincipal
from app.application.services.model_api_keys import (
    key_consumers,
    key_history,
    latest_versions,
    restore_version,
    save_key,
    test_key,
    use_environment_key,
)
from app.core.config import Settings
from app.domain.model_api_keys import MODEL_KEY_PROVIDERS, ModelKeyProvider
from app.domain.secret_box import last4
from app.infrastructure.db.models import ModelApiKeyModel
from app.infrastructure.model_api_keys_overlay import environment_model_keys
from app.schemas.admin_models import (
    AdminModelKeyConsumer,
    AdminModelKeyHistoryResponse,
    AdminModelKeyRequest,
    AdminModelKeyRestoreRequest,
    AdminModelKeyTestResponse,
    AdminModelKeyVersion,
    AdminModelProvider,
    AdminModelProvidersResponse,
)

router = APIRouter(prefix="/admin/models", tags=["admin"], dependencies=[Depends(admin_guard)])

Owner = Annotated[AdminPrincipal, Depends(require_owner)]
Session = Annotated[AsyncSession, Depends(get_session)]


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _http(request: Request) -> httpx.AsyncClient | None:
    # Tests install a client with a mock transport; production opens one per call.
    return cast(httpx.AsyncClient | None, getattr(request.app.state, "model_probe_http", None))


def _env_keys(request: Request) -> Mapping[str, SecretStr | None]:
    override = getattr(request.app.state, "environment_model_keys", None)
    return cast(Mapping[str, SecretStr | None], override or environment_model_keys())


def _origin(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    return f"{parts.scheme}://{parts.hostname}" if parts.scheme and parts.hostname else None


def _endpoint(provider: ModelKeyProvider, settings: Settings) -> tuple[str | None, list[str]]:
    if provider.id == "zhipu":
        return settings.ai_platform_base_url, sorted(
            {
                settings.ai_chat_model,
                settings.image_quality_audit_model,
                settings.brand_ocr_model,
                settings.ai_embedding_model,
            }
        )
    if provider.id == "comfly":
        return settings.comfly_base_url, [settings.image_model]
    endpoint = settings.visual_embedding_endpoint
    # The endpoint is a secret setting; show its origin only.
    return _origin(endpoint.get_secret_value() if endpoint else None), [
        settings.visual_embedding_model
    ]


def _provider_view(
    provider: ModelKeyProvider,
    row: ModelApiKeyModel | None,
    settings: Settings,
    env_keys: Mapping[str, SecretStr | None],
) -> AdminModelProvider:
    base_url, models = _endpoint(provider, settings)
    env_key = env_keys.get(provider.id)
    env_value = env_key.get_secret_value().strip() if env_key is not None else ""
    if row is not None and row.key_sealed is not None:
        source, hint = "console", f"••••{row.key_last4}"
    elif env_value:
        source, hint = "env", f"••••{last4(env_value)}"
    else:
        source, hint = "none", None
    return AdminModelProvider(
        id=provider.id,
        name=provider.name,
        used_for=provider.used_for,
        base_url=base_url,
        models=models,
        source=source,
        key_hint=hint,
        version=row.version if row else None,
        updated_by=row.created_by if row else None,
        updated_at=row.created_at if row else None,
    )


async def _providers(session: AsyncSession, request: Request) -> dict[str, AdminModelProvider]:
    latest = await latest_versions(session)
    settings, env_keys = _settings(request), _env_keys(request)
    return {
        provider.id: _provider_view(provider, latest.get(provider.id), settings, env_keys)
        for provider in MODEL_KEY_PROVIDERS
    }


@router.get("", response_model=AdminModelProvidersResponse)
async def get_model_providers(
    _owner: Owner, session: Session, request: Request
) -> AdminModelProvidersResponse:
    configured = _settings(request).model_secret_key
    consumers = await key_consumers(session, now=datetime.now(UTC))
    return AdminModelProvidersResponse(
        secret_key_configured=configured is not None
        and bool(configured.get_secret_value().strip()),
        providers=list((await _providers(session, request)).values()),
        consumers=[
            AdminModelKeyConsumer(
                service=service,
                label=label,
                reporting=row is not None,
                versions=None if row is None or row.versions is None else dict(row.versions),
                load_errors=(
                    None if row is None or row.load_errors is None else dict(row.load_errors)
                ),
                started_at=row.started_at if row else None,
                seen_at=row.seen_at if row else None,
            )
            for service, label, row in consumers
        ],
    )


@router.post("/{provider_id}/test", response_model=AdminModelKeyTestResponse)
async def post_model_key_test(
    provider_id: str, body: AdminModelKeyRequest, _owner: Owner, request: Request
) -> AdminModelKeyTestResponse:
    result = await test_key(
        settings=_settings(request),
        http=_http(request),
        provider_id=provider_id,
        api_key=body.api_key,
    )
    return AdminModelKeyTestResponse(
        ok=result.ok, latency_ms=result.latency_ms, message=result.message
    )


@router.post(
    "/{provider_id}/keys",
    response_model=AdminModelProvider,
    status_code=status.HTTP_201_CREATED,
)
async def post_model_key(
    provider_id: str,
    body: AdminModelKeyRequest,
    owner: Owner,
    session: Session,
    request: Request,
) -> AdminModelProvider:
    await save_key(
        session,
        settings=_settings(request),
        http=_http(request),
        principal=owner,
        provider_id=provider_id,
        api_key=body.api_key,
        note=body.note,
        now=datetime.now(UTC),
    )
    return (await _providers(session, request))[provider_id]


@router.get("/{provider_id}/history", response_model=AdminModelKeyHistoryResponse)
async def get_model_key_history(
    provider_id: str, _owner: Owner, session: Session
) -> AdminModelKeyHistoryResponse:
    rows = await key_history(session, provider_id)
    return AdminModelKeyHistoryResponse(
        items=[
            AdminModelKeyVersion(
                version=row.version,
                source="console" if row.key_sealed is not None else "env",
                key_hint=f"••••{row.key_last4}" if row.key_last4 else None,
                note=row.note,
                restored_from=row.restored_from,
                probe_latency_ms=row.probe_latency_ms,
                created_by=row.created_by,
                created_at=row.created_at,
                current=index == 0,
            )
            for index, row in enumerate(rows)
        ]
    )


@router.post("/{provider_id}/restore", response_model=AdminModelProvider)
async def post_model_key_restore(
    provider_id: str,
    body: AdminModelKeyRestoreRequest,
    owner: Owner,
    session: Session,
    request: Request,
) -> AdminModelProvider:
    await restore_version(
        session,
        settings=_settings(request),
        http=_http(request),
        principal=owner,
        provider_id=provider_id,
        version=body.version,
        env_keys=_env_keys(request),
        now=datetime.now(UTC),
    )
    return (await _providers(session, request))[provider_id]


@router.post("/{provider_id}/use-env", response_model=AdminModelProvider)
async def post_model_key_use_env(
    provider_id: str, owner: Owner, session: Session, request: Request
) -> AdminModelProvider:
    await use_environment_key(
        session,
        settings=_settings(request),
        http=_http(request),
        principal=owner,
        provider_id=provider_id,
        env_keys=_env_keys(request),
        now=datetime.now(UTC),
    )
    return (await _providers(session, request))[provider_id]
