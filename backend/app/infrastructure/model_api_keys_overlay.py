"""Model keys rotated in the 运营后台 replace the environment keys when a process starts.

`get_settings()` calls `with_console_model_keys` once per process. It reads the newest version per
provider with one short synchronous query (the event loop may not exist yet) and opens the sealed
keys with `MODEL_SECRET_KEY`. Without that key, or on any failure, the environment keys stay, so
the console can never stop a process from starting.

Long-running services also call `start_model_key_watch`. Once a minute a daemon thread reports
the versions this process loaded and safe load errors (`model_key_consumers`, shown on the
模型配置 page). It compares the versions attempted at startup with the newest ones, so an
unreadable key does not cause repeated restarts. On a change it sends its own SIGTERM after the
process has run 2 minutes. Every service finishes its current job on SIGTERM, then exits, and
Docker (`restart: unless-stopped`) starts it again with the new key.
"""

from __future__ import annotations

import os
import random
import re
import signal
import socket
import threading
import time
from datetime import UTC, datetime
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

_BEAT_SQL = (
    "INSERT INTO model_key_consumers (service, host, versions, load_errors, started_at, seen_at) "
    "VALUES (%s, %s, %s, %s, %s, now()) ON CONFLICT (service, host) DO UPDATE SET "
    "versions = EXCLUDED.versions, load_errors = EXCLUDED.load_errors, "
    "started_at = EXCLUDED.started_at, seen_at = now()"
)
# A recreated container gets a new host name; forget the old rows after a day.
_PRUNE_SQL = "DELETE FROM model_key_consumers WHERE seen_at < now() - interval '1 day'"

_started_at = time.monotonic()
_started_wall = datetime.now(UTC)
# A version is loaded only after decryption succeeds, or an explicit env restore is applied.
# Keep attempts separately: retries of the same bad ciphertext must not restart the service.
_attempted_versions: dict[str, int] | None = None
_loaded_versions: dict[str, int] | None = None
_load_errors: dict[str, str] | None = None
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
    global _attempted_versions, _loaded_versions, _load_errors
    _attempted_versions = None
    _loaded_versions = None
    _load_errors = None
    configured = _configured_key(settings)
    if configured is None:
        return settings
    try:
        latest = read_latest_versions(settings)
    except Exception:
        # Never block start-up on the console: the environment keys keep working.
        _load_errors = {
            provider.id: "configuration_unavailable" for provider in MODEL_KEY_PROVIDERS
        }
        logger.warning("console_model_keys_unavailable")
        return settings
    _attempted_versions = {provider: version for provider, (version, _sealed) in latest.items()}
    _loaded_versions = {}
    _load_errors = {}
    try:
        key = parse_key(configured)
    except SecretBoxError:
        key = None
    updates: dict[str, SecretStr] = {}
    for provider_id, (version, sealed) in latest.items():
        provider = model_key_provider(provider_id)
        if provider is None:
            continue
        if sealed is None:
            _loaded_versions[provider_id] = version
            continue
        if key is None:
            _load_errors[provider_id] = "encryption_key_invalid"
            continue
        try:
            updates[provider.settings_field] = SecretStr(
                open_sealed(sealed, key=key, purpose=sealed_key_purpose(provider_id))
            )
            _loaded_versions[provider_id] = version
        except SecretBoxError:
            _load_errors[provider_id] = "key_unreadable"
            logger.warning("console_model_key_unreadable", provider=provider_id, version=version)
    if updates:
        logger.info(
            "console_model_keys_applied",
            versions={p: v for p, v in _loaded_versions.items()},
            fields=sorted(updates),
        )
    return settings.model_copy(update=updates)


def keys_changed(attempted: dict[str, int] | None, latest: dict[str, int]) -> bool:
    if attempted is None:
        # The start-up read failed; only a stored key is worth a restart.
        return bool(latest)
    return attempted != latest


def start_model_key_watch(settings: Settings, *, service: str) -> bool:
    """Report the loaded versions, and restart this process (SIGTERM) after a key rotation."""

    global _watch_started
    if _watch_started or _configured_key(settings) is None:
        return False
    _watch_started = True
    threading.Thread(
        target=_watch, args=(settings, service), name="model-key-watch", daemon=True
    ).start()
    return True


def beat_and_read(settings: Settings, service: str, host: str) -> dict[str, int]:
    """Write this process's heartbeat, then read the newest version per provider."""

    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(_sync_url(settings), connect_timeout=5, autocommit=True) as connection:
        try:
            versions = None if _loaded_versions is None else Jsonb(_loaded_versions)
            errors = None if _load_errors is None else Jsonb(_load_errors)
            connection.execute(
                _BEAT_SQL, (service[:60], host[:100], versions, errors, _started_wall)
            )
            connection.execute(_PRUNE_SQL)
        except psycopg.Error:
            # The page loses this row; the restart below still works.
            logger.warning("console_model_key_heartbeat_failed", service=service)
        rows = connection.execute(_LATEST_SQL).fetchall()
    return {str(provider): int(version) for provider, version, _sealed in rows}


def _watch(settings: Settings, service: str) -> None:
    host = socket.gethostname()
    while True:
        try:
            latest: dict[str, int] | None = beat_and_read(settings, service, host)
        except Exception:
            latest = None
        if latest is not None and keys_changed(_attempted_versions, latest):
            # Never restart a process in its first minutes; spread the services out a little.
            remaining = WATCH_MIN_UPTIME_SECONDS - (time.monotonic() - _started_at)
            time.sleep(max(0.0, remaining) + random.uniform(0, WATCH_JITTER_SECONDS))
            logger.info("console_model_keys_changed_restarting", service=service, versions=latest)
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
    "beat_and_read",
    "environment_model_keys",
    "keys_changed",
    "loaded_versions",
    "read_latest_versions",
    "start_model_key_watch",
    "with_console_model_keys",
]
