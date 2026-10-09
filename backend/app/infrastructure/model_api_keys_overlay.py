"""Model keys rotated in the 运营后台 replace the environment keys when a process starts.

`get_settings()` calls `with_console_model_keys` once per process. It reads the newest version per
provider with one short synchronous query (the event loop may not exist yet) and opens the sealed
keys with `MODEL_SECRET_KEY`. Without that key, or on any failure, the environment keys stay, so
the console can never stop a process from starting.

Long-running services also call `start_model_key_watch`. A daemon thread compares the newest
versions with the ones this process loaded; on a change it sends the process its own SIGTERM.
Every service finishes its current job on SIGTERM, then exits, and Docker
(`restart: unless-stopped`) starts it again with the new key.
"""

from __future__ import annotations

import os
import random
import re
import signal
import threading
import time
from functools import lru_cache
from typing import TYPE_CHECKING

import structlog
from pydantic import SecretStr

from app.domain.model_api_keys import (
    MODEL_KEY_PROVIDERS,
    model_key_provider,
    sealed_key_purpose,
)
from app.domain.secret_box import SecretBoxError, open_sealed, parse_key

if TYPE_CHECKING:
    from app.core.config import Settings

logger = structlog.get_logger(__name__)

WATCH_POLL_SECONDS = 60.0
WATCH_MIN_UPTIME_SECONDS = 120.0
WATCH_JITTER_SECONDS = 30.0
_LATEST_SQL = (
    "SELECT DISTINCT ON (provider) provider, version, key_sealed "
    "FROM model_api_keys ORDER BY provider, version DESC"
)

_started_at = time.monotonic()
# Newest version per provider as read at start; None when that read failed.
_loaded_versions: dict[str, int] | None = None
_watch_started = False


def _configured_key(settings: Settings) -> str | None:
    value = settings.model_secret_key
    if value is None or not value.get_secret_value().strip():
        return None
    return value.get_secret_value()


def _sync_url(settings: Settings) -> str:
    return re.sub(r"^postgresql\+\w+://", "postgresql://", settings.database_url.get_secret_value())


def read_latest_versions(settings: Settings) -> dict[str, tuple[int, str | None]]:
    import psycopg

    with psycopg.connect(_sync_url(settings), connect_timeout=5, autocommit=True) as connection:
        rows = connection.execute(_LATEST_SQL).fetchall()
    return {str(provider): (int(version), sealed) for provider, version, sealed in rows}


def with_console_model_keys(settings: Settings) -> Settings:
    global _loaded_versions
    configured = _configured_key(settings)
    if configured is None:
        return settings
    try:
        key = parse_key(configured)
        latest = read_latest_versions(settings)
    except Exception as error:
        # Never block start-up on the console: the environment keys keep working.
        logger.warning("console_model_keys_unavailable", error_type=type(error).__name__)
        return settings
    _loaded_versions = {provider: version for provider, (version, _sealed) in latest.items()}
    updates: dict[str, SecretStr] = {}
    for provider_id, (version, sealed) in latest.items():
        provider = model_key_provider(provider_id)
        if provider is None or sealed is None:
            continue
        try:
            updates[provider.settings_field] = SecretStr(
                open_sealed(sealed, key=key, purpose=sealed_key_purpose(provider_id))
            )
        except SecretBoxError:
            logger.warning("console_model_key_unreadable", provider=provider_id, version=version)
    if updates:
        logger.info(
            "console_model_keys_applied",
            versions={p: v for p, v in _loaded_versions.items()},
            fields=sorted(updates),
        )
    return settings.model_copy(update=updates)


def keys_changed(loaded: dict[str, int] | None, latest: dict[str, int]) -> bool:
    if loaded is None:
        # The start-up read failed; only a stored key is worth a restart.
        return bool(latest)
    return loaded != latest


def start_model_key_watch(settings: Settings) -> bool:
    """Restart this long-running process (via SIGTERM) after an owner rotates a model key."""

    global _watch_started
    if _watch_started or _configured_key(settings) is None:
        return False
    _watch_started = True
    threading.Thread(target=_watch, args=(settings,), name="model-key-watch", daemon=True).start()
    return True


def _watch(settings: Settings) -> None:
    uptime = time.monotonic() - _started_at
    time.sleep(
        max(0.0, WATCH_MIN_UPTIME_SECONDS - uptime) + random.uniform(0, WATCH_JITTER_SECONDS)
    )
    while True:
        try:
            latest = {p: v for p, (v, _sealed) in read_latest_versions(settings).items()}
        except Exception:
            latest = None
        if latest is not None and keys_changed(_loaded_versions, latest):
            logger.info("console_model_keys_changed_restarting", versions=latest)
            os.kill(os.getpid(), signal.SIGTERM)
            return
        time.sleep(WATCH_POLL_SECONDS)


@lru_cache
def environment_model_keys() -> dict[str, SecretStr | None]:
    """The keys this process got from its environment, before any console version."""

    from app.core.config import Settings

    env = Settings()
    return {provider.id: getattr(env, provider.settings_field) for provider in MODEL_KEY_PROVIDERS}


def loaded_versions() -> dict[str, int] | None:
    return None if _loaded_versions is None else dict(_loaded_versions)


__all__ = [
    "environment_model_keys",
    "keys_changed",
    "loaded_versions",
    "read_latest_versions",
    "start_model_key_watch",
    "with_console_model_keys",
]
