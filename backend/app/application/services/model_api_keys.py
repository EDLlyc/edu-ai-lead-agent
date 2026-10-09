# ruff: noqa: RUF001
"""运营后台 · 模型配置: rotate model provider keys, with a passing test before every switch.

Every change writes a new version; the newest version per provider is in force. A version holds a
sealed key, or null for "use the key from the server environment". Processes pick the newest
version up when they start (see `app.infrastructure.model_api_keys_overlay`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from time import monotonic
from uuid import uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.admin_auth import AdminPrincipal
from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.domain.model_api_keys import (
    ModelKeyProvider,
    model_key_provider,
    sealed_key_purpose,
    valid_api_key,
)
from app.domain.secret_box import SecretBoxError, last4, open_sealed, parse_key, seal
from app.infrastructure.ai.model_key_probe import ProbeResult, probe_model_key
from app.infrastructure.db.admin_auth import add_audit_event
from app.infrastructure.db.models import ModelApiKeyModel

TEST_GAP_SECONDS = 3.0
_LAST_TEST: dict[str, float] = {}

Probe = Callable[..., Awaitable[ProbeResult]]


class ModelKeyRejected(AppError):
    def __init__(self, message: str, code: str = "model_key_rejected", status: int = 422):
        super().__init__(code, message, status)


def model_secret_key(settings: Settings) -> bytes:
    configured = settings.model_secret_key
    if configured is None or not configured.get_secret_value().strip():
        raise ModelKeyRejected(
            "服务器还没配置加密密钥（MODEL_SECRET_KEY），暂时不能保存模型 key",
            "model_secret_key_missing",
            503,
        )
    try:
        return parse_key(configured.get_secret_value())
    except SecretBoxError as error:
        raise ModelKeyRejected(
            "服务器的 MODEL_SECRET_KEY 格式不对", "model_secret_key_invalid", 503
        ) from error


def _provider(provider_id: str) -> ModelKeyProvider:
    provider = model_key_provider(provider_id)
    if provider is None:
        raise NotFoundError("model provider")
    return provider


async def latest_versions(session: AsyncSession) -> dict[str, ModelApiKeyModel]:
    rows = (
        await session.scalars(
            select(ModelApiKeyModel)
            .distinct(ModelApiKeyModel.provider)
            .order_by(ModelApiKeyModel.provider, ModelApiKeyModel.version.desc())
        )
    ).all()
    return {row.provider: row for row in rows}


async def key_history(session: AsyncSession, provider_id: str) -> list[ModelApiKeyModel]:
    _provider(provider_id)
    return list(
        (
            await session.scalars(
                select(ModelApiKeyModel)
                .where(ModelApiKeyModel.provider == provider_id)
                .order_by(ModelApiKeyModel.version.desc())
                .limit(20)
            )
        ).all()
    )


async def test_key(
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    provider_id: str,
    api_key: str,
    probe: Probe = probe_model_key,
) -> ProbeResult:
    _provider(provider_id)
    candidate = api_key.strip()
    if not valid_api_key(candidate):
        raise ModelKeyRejected("key 格式不对：8–300 个字符，不能有空格", "model_key_invalid")
    last = _LAST_TEST.get(provider_id)
    if last is not None and monotonic() - last < TEST_GAP_SECONDS:
        raise ModelKeyRejected("测得太快了，等几秒再试", "model_key_test_too_soon", 429)
    _LAST_TEST[provider_id] = monotonic()
    return await probe(provider_id, candidate, settings=settings, http=http)


async def _require_passing(
    probe: Probe,
    provider_id: str,
    api_key: str,
    settings: Settings,
    http: httpx.AsyncClient | None,
) -> ProbeResult:
    result = await probe(provider_id, api_key, settings=settings, http=http)
    if not result.ok:
        raise ModelKeyRejected(f"测试没通过，没有保存：{result.message}", "model_key_probe_failed")
    return result


async def _add_version(
    session: AsyncSession,
    *,
    principal: AdminPrincipal,
    provider_id: str,
    key_sealed: str | None,
    key_last4: str | None,
    note: str | None,
    restored_from: int | None,
    latency_ms: int,
    action: str,
    now: datetime,
) -> ModelApiKeyModel:
    current = await session.scalar(
        select(func.max(ModelApiKeyModel.version)).where(ModelApiKeyModel.provider == provider_id)
    )
    row = ModelApiKeyModel(
        id=uuid4(),
        provider=provider_id,
        version=(current or 0) + 1,
        key_sealed=key_sealed,
        key_last4=key_last4,
        note=note,
        restored_from=restored_from,
        probe_latency_ms=latency_ms,
        created_by=principal.username,
        created_at=now,
    )
    session.add(row)
    detail: dict[str, object] = {"provider": provider_id, "version": row.version}
    if restored_from is not None:
        detail["restored_from"] = restored_from
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action=action,
        target_type="model_provider",
        target_id=provider_id,
        detail=detail,
    )
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise ModelKeyRejected("别人刚改过，请刷新后再试", "model_key_conflict", 409) from error
    return row


async def save_key(
    session: AsyncSession,
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    principal: AdminPrincipal,
    provider_id: str,
    api_key: str,
    note: str | None,
    now: datetime,
    probe: Probe = probe_model_key,
) -> ModelApiKeyModel:
    _provider(provider_id)
    candidate = api_key.strip()
    if not valid_api_key(candidate):
        raise ModelKeyRejected("key 格式不对：8–300 个字符，不能有空格", "model_key_invalid")
    key = model_secret_key(settings)
    result = await _require_passing(probe, provider_id, candidate, settings, http)
    return await _add_version(
        session,
        principal=principal,
        provider_id=provider_id,
        key_sealed=seal(candidate, key=key, purpose=sealed_key_purpose(provider_id)),
        key_last4=last4(candidate),
        note=(note or "").strip()[:200] or None,
        restored_from=None,
        latency_ms=result.latency_ms,
        action="model_key.rotated",
        now=now,
    )


async def restore_version(
    session: AsyncSession,
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    principal: AdminPrincipal,
    provider_id: str,
    version: int,
    env_keys: Mapping[str, SecretStr | None],
    now: datetime,
    probe: Probe = probe_model_key,
) -> ModelApiKeyModel:
    _provider(provider_id)
    key = model_secret_key(settings)
    target = await session.scalar(
        select(ModelApiKeyModel).where(
            ModelApiKeyModel.provider == provider_id, ModelApiKeyModel.version == version
        )
    )
    if target is None:
        raise NotFoundError("model key version")
    latest = (await latest_versions(session)).get(provider_id)
    if latest is not None and latest.version == version:
        raise ModelKeyRejected("已经在用这一版了", "model_key_already_current", 409)
    sealed, hint = target.key_sealed, target.key_last4
    if sealed is None:
        plaintext = _env_key(env_keys, provider_id)
    else:
        try:
            plaintext = open_sealed(sealed, key=key, purpose=sealed_key_purpose(provider_id))
        except SecretBoxError as error:
            raise ModelKeyRejected(
                "这一版的 key 打不开（服务器的加密密钥换过）", "model_key_unreadable", 409
            ) from error
    result = await _require_passing(probe, provider_id, plaintext, settings, http)
    return await _add_version(
        session,
        principal=principal,
        provider_id=provider_id,
        key_sealed=sealed,
        key_last4=hint,
        note=f"恢复第 {version} 版",
        restored_from=version,
        latency_ms=result.latency_ms,
        action="model_key.restored",
        now=now,
    )


async def use_environment_key(
    session: AsyncSession,
    *,
    settings: Settings,
    http: httpx.AsyncClient | None,
    principal: AdminPrincipal,
    provider_id: str,
    env_keys: Mapping[str, SecretStr | None],
    now: datetime,
    probe: Probe = probe_model_key,
) -> ModelApiKeyModel:
    _provider(provider_id)
    model_secret_key(settings)
    latest = (await latest_versions(session)).get(provider_id)
    if latest is None or latest.key_sealed is None:
        raise ModelKeyRejected("已经在用服务器配置的 key 了", "model_key_already_env", 409)
    result = await _require_passing(
        probe, provider_id, _env_key(env_keys, provider_id), settings, http
    )
    return await _add_version(
        session,
        principal=principal,
        provider_id=provider_id,
        key_sealed=None,
        key_last4=None,
        note="改回服务器配置的 key",
        restored_from=None,
        latency_ms=result.latency_ms,
        action="model_key.env_restored",
        now=now,
    )


def _env_key(env_keys: Mapping[str, SecretStr | None], provider_id: str) -> str:
    value = env_keys.get(provider_id)
    if value is None or not value.get_secret_value().strip():
        raise ModelKeyRejected(
            "服务器环境里没有配置这个 key，不能改回", "model_key_env_missing", 409
        )
    return value.get_secret_value().strip()


__all__ = [
    "ModelKeyRejected",
    "key_history",
    "latest_versions",
    "model_secret_key",
    "restore_version",
    "save_key",
    "test_key",
    "use_environment_key",
]
