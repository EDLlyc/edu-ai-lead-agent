from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from app import visitor_display_main as entry
from app.core.errors import AppError, ConflictError, NotFoundError
from app.infrastructure.db.visitor_display import PostgresVisitorDisplayRepository
from app.infrastructure.db.visitor_report import VisitorReportDay
from app.infrastructure.storage import minio_image_store, minio_snapshot_store
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

SECRET = "unit-test-visitor-asset-secret-32-bytes"
ENV = {
    "VISITOR_DISPLAY_ENABLED": "true",
    "VISITOR_DISPLAY_ASSET_SECRET": SECRET,
    "DATABASE_URL": "postgresql+asyncpg://reader:private-test-password@127.0.0.1:15433/live",
    "MINIO_ENDPOINT": "http://127.0.0.1:19000",
    "MINIO_BUCKET": "private-test-bucket",
    "MINIO_SECURE": "false",
    "MINIO_ACCESS_KEY": "private-test-access",
    "MINIO_SECRET_KEY": "private-test-secret",
}
PRIVATE = "SELECT private_column FROM /private/path password=SECRET_SENTINEL"


@pytest.fixture
def infrastructure(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[MagicMock, AsyncMock]]:
    engine = AsyncMock(spec=AsyncEngine)
    create_engine = MagicMock(return_value=engine)
    monkeypatch.setattr(entry, "create_async_engine", create_engine)
    monkeypatch.setattr(entry, "create_session_factory", MagicMock())
    monkeypatch.setattr(entry, "MinioImageStore", MagicMock())
    monkeypatch.setattr(entry, "MinioSnapshotStore", MagicMock())
    yield create_engine, engine


def _application() -> FastAPI:
    return entry.create_app(entry.load_settings(ENV))


def test_settings_ignore_dotenv_and_unrelated_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "APP_ENV=production\nVISITOR_DISPLAY_ENABLED=true\nDATABASE_URL=private-value\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_ENV", "not-an-environment")
    monkeypatch.setenv("AI_MAX_TOKENS_PER_RUN", "not-an-integer")
    monkeypatch.setenv("VISITOR_DISPLAY_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "not-a-url")

    disabled = entry.load_settings({})
    enabled = entry.load_settings(ENV)

    assert disabled.visitor_display_enabled is False
    assert enabled.visitor_display_enabled is True
    assert enabled.app_env == "development"
    assert enabled.image_asset_manifest == ""
    assert enabled.database_url.get_secret_value() == ENV["DATABASE_URL"]
    assert enabled.minio_bucket == ENV["MINIO_BUCKET"]
    assert SECRET not in repr(enabled)
    assert "private-test-password" not in repr(enabled)


def test_factory_loads_only_allowlisted_process_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("AI_MAX_TOKENS_PER_RUN", "not-an-integer")
    application = entry.create_app()
    assert application.state.settings.visitor_display_enabled is True
    assert application.state.settings.image_asset_manifest == ""


@pytest.mark.parametrize("key", list(ENV))
def test_enabled_configuration_requires_explicit_values(key: str) -> None:
    values = dict(ENV)
    del values[key]
    if key == "VISITOR_DISPLAY_ENABLED":
        assert entry.load_settings(values).visitor_display_enabled is False
    else:
        with pytest.raises(entry.VisitorDisplayConfigurationError) as raised:
            entry.load_settings(values)
        assert str(raised.value) == "visitor display configuration rejected"
        assert raised.value.__suppress_context__ is True


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("VISITOR_DISPLAY_ENABLED", PRIVATE),
        ("VISITOR_DISPLAY_ASSET_SECRET", "too-short"),
        ("VISITOR_DISPLAY_ASSET_SECRET", " " * 64),
        ("DATABASE_URL", "sqlite+aiosqlite:///private/path"),
        ("DATABASE_URL", "postgresql+asyncpg://reader:secret@db:5432/live"),
        ("DATABASE_URL", "postgresql+asyncpg://reader:secret@localhost:15433/live"),
        ("DATABASE_URL", "postgresql+asyncpg://reader:secret@127.0.0.1/live"),
        ("DATABASE_URL", "postgresql+asyncpg://reader@127.0.0.1:15433/live"),
        ("DATABASE_URL", ENV["DATABASE_URL"] + "?host=private-server"),
        (
            "DATABASE_URL",
            "postgresql+asyncpg://edu_ai:edu_ai_local_change_me@127.0.0.1:5432/edu_ai",
        ),
        ("MINIO_ENDPOINT", "http://private-server:9000"),
        ("MINIO_ENDPOINT", "http://secret@127.0.0.1:19000"),
        ("MINIO_ENDPOINT", "http://127.0.0.1:19000/private"),
        ("MINIO_ENDPOINT", "http://127.0.0.1:19000?private=value"),
        ("MINIO_ENDPOINT", "http://127.0.0.1:19000#private"),
        ("MINIO_ENDPOINT", "http://127.0.0.1:99999"),
        ("MINIO_ENDPOINT", "http://127.0.0.1"),
        ("MINIO_SECURE", "true"),
        ("MINIO_BUCKET", " "),
        ("MINIO_ACCESS_KEY", ""),
        ("MINIO_ACCESS_KEY", "edu_ai_minio"),
        ("MINIO_SECRET_KEY", ""),
        ("MINIO_SECRET_KEY", "edu_ai_minio_local_change_me"),
    ],
)
def test_unsafe_configuration_has_only_safe_error(key: str, value: str) -> None:
    with pytest.raises(entry.VisitorDisplayConfigurationError) as raised:
        entry.load_settings({**ENV, key: value})
    assert str(raised.value) == "visitor display configuration rejected"
    assert raised.value.__suppress_context__ is True


def test_manifest_is_opt_in_and_explicit_settings_are_revalidated() -> None:
    settings = entry.load_settings({**ENV, "IMAGE_ASSET_MANIFEST": "/private/catalog.json"})
    application = entry.create_app(settings)
    assert application.state.settings.image_asset_manifest == "/private/catalog.json"
    assert application.state.settings is not settings
    tampered = settings.model_copy(update={"database_url": "private-invalid-url"})
    with pytest.raises(entry.VisitorDisplayConfigurationError):
        entry.create_app(tampered)


async def test_lifespan_uses_read_only_bounded_engine_and_disposes(
    infrastructure: tuple[MagicMock, AsyncMock],
) -> None:
    create_engine, engine = infrastructure
    application = _application()
    create_engine.assert_not_called()
    async with application.router.lifespan_context(application):
        create_engine.assert_called_once_with(
            ENV["DATABASE_URL"],
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=0,
            pool_timeout=10,
            echo=False,
            hide_parameters=True,
            connect_args={
                "timeout": 10,
                "server_settings": {
                    "default_transaction_read_only": "on",
                    "statement_timeout": "10000",
                    "application_name": "visitor_display_local",
                },
            },
        )
        engine.dispose.assert_not_awaited()
    engine.dispose.assert_awaited_once()


async def test_real_storage_constructors_perform_no_initialization_or_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = AsyncMock(spec=AsyncEngine)
    monkeypatch.setattr(entry, "create_async_engine", MagicMock(return_value=engine))
    monkeypatch.setattr(entry, "create_session_factory", MagicMock())
    image_client = MagicMock()
    snapshot_client = MagicMock()
    image_constructor = MagicMock(return_value=image_client)
    snapshot_constructor = MagicMock(return_value=snapshot_client)
    monkeypatch.setattr(minio_image_store, "Minio", image_constructor)
    monkeypatch.setattr(minio_snapshot_store, "Minio", snapshot_constructor)
    application = _application()

    async with application.router.lifespan_context(application):
        assert isinstance(application.state.image_store, minio_image_store.MinioImageStore)
        assert isinstance(application.state.snapshot_store, minio_snapshot_store.MinioSnapshotStore)
    for constructor, client in (
        (image_constructor, image_client),
        (snapshot_constructor, snapshot_client),
    ):
        constructor.assert_called_once_with(
            "127.0.0.1:19000",
            access_key=ENV["MINIO_ACCESS_KEY"],
            secret_key=ENV["MINIO_SECRET_KEY"],
            secure=False,
        )
        assert client.mock_calls == []
    engine.dispose.assert_awaited_once()


async def test_lifespan_preserves_cancellation_and_disposes(
    infrastructure: tuple[MagicMock, AsyncMock],
) -> None:
    application = _application()
    with pytest.raises(asyncio.CancelledError):
        async with application.router.lifespan_context(application):
            raise asyncio.CancelledError
    infrastructure[1].dispose.assert_awaited_once()


async def test_cleanup_failure_is_sanitized(infrastructure: tuple[MagicMock, AsyncMock]) -> None:
    infrastructure[1].dispose.side_effect = RuntimeError(PRIVATE)
    application = _application()
    with pytest.raises(RuntimeError, match=r"^visitor display cleanup failed$") as raised:
        async with application.router.lifespan_context(application):
            pass
    assert raised.value.__suppress_context__ is True


async def test_disabled_app_never_constructs_storage_and_both_routes_are_404(
    infrastructure: tuple[MagicMock, AsyncMock],
) -> None:
    application = entry.create_app(entry.load_settings({}))
    async with (
        application.router.lifespan_context(application),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client,
    ):
        health = await client.get("/healthz")
        assert health.json() == {"service": "visitor-display-local", "status": "ok"}
        for path in ("snapshot", "assets/vd1_" + "a" * 43):
            response = await client.get("/api/v1/visitor-display/" + path)
            assert response.status_code == 404
            assert response.headers["cache-control"] == "no-store"
    infrastructure[0].assert_not_called()


async def test_only_three_get_routes_and_no_private_or_docs_surface(
    infrastructure: tuple[MagicMock, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    application = _application()
    assert {
        path: {method.upper() for method in methods}
        for path, methods in application.openapi()["paths"].items()
    } == {
        "/healthz": {"GET"},
        "/api/v1/visitor-display/snapshot": {"GET"},
        "/api/v1/visitor-display/assets/{asset_ref}": {"GET"},
    }
    load_latest = AsyncMock(return_value=())
    monkeypatch.setattr(PostgresVisitorDisplayRepository, "load_latest", load_latest)
    # The route inventory is under test here, not the optional pool/report reads.
    monkeypatch.setattr(
        PostgresVisitorDisplayRepository, "load_news_pool", AsyncMock(return_value=())
    )
    monkeypatch.setattr(
        PostgresVisitorDisplayRepository, "load_moments", AsyncMock(return_value=())
    )
    monkeypatch.setattr(
        PostgresVisitorDisplayRepository, "load_issue_signals", AsyncMock(return_value=())
    )
    monkeypatch.setattr(
        PostgresVisitorDisplayRepository,
        "load_report",
        AsyncMock(return_value=(VisitorReportDay(day=date(2026, 9, 28)),)),
    )
    async with (
        application.router.lifespan_context(application),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client,
    ):
        for path in (
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v1/official-account-local/article-runs",
        ):
            assert (await client.get(path)).status_code == 404
        for path in (
            "/healthz",
            "/api/v1/visitor-display/snapshot",
            "/api/v1/visitor-display/assets/x",
        ):
            for method in ("HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
                response = await client.request(method, path)
                assert response.status_code == 405
                assert response.headers["allow"] == "GET"
        assert (await client.get("/api/v1/visitor-display/snapshot/")).status_code == 404
        snapshot = await client.get("/api/v1/visitor-display/snapshot")
        assert snapshot.status_code == 200
        assert snapshot.json()["state"] == "empty"
        assert snapshot.json()["articles"] == []
        assert snapshot.headers["cache-control"] == "no-store"
        assert "access-control-allow-origin" not in snapshot.headers
    load_latest.assert_awaited_once()


async def test_large_json_is_compressed_and_small_answers_are_not(
    infrastructure: tuple[MagicMock, AsyncMock],
) -> None:
    application = _application()
    # Stands in for the snapshot, which is several hundred KB with live data.
    application.add_api_route("/large", lambda: {"rows": ["候选新闻"] * 4000})
    async with (
        application.router.lifespan_context(application),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client,
    ):
        large = await client.get("/large", headers={"accept-encoding": "gzip"})
        assert large.headers["content-encoding"] == "gzip"
        assert len(large.json()["rows"]) == 4000
        assert int(large.headers["content-length"]) < 2000

        plain = await client.get("/large", headers={"accept-encoding": "identity"})
        assert "content-encoding" not in plain.headers
        assert "content-encoding" not in (await client.get("/healthz")).headers


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (NotFoundError(PRIVATE), 404),
        (ConflictError(PRIVATE), 409),
        (AppError(PRIVATE, PRIVATE, 422), 422),
        (AppError(PRIVATE, PRIVATE, 500), 503),
        (RuntimeError(PRIVATE), 503),
    ],
)
async def test_error_privacy_without_reraising_to_server_logs(
    infrastructure: tuple[MagicMock, AsyncMock],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    status: int,
) -> None:
    application = _application()
    monkeypatch.setattr(
        PostgresVisitorDisplayRepository, "load_latest", AsyncMock(side_effect=error)
    )
    async with (
        application.router.lifespan_context(application),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application, raise_app_exceptions=True),
            base_url="http://test",
        ) as client,
    ):
        response = await client.get("/api/v1/visitor-display/snapshot")
    assert response.status_code == status
    for forbidden in (PRIVATE, SECRET, "private-test", "Traceback"):
        assert forbidden not in response.text
        assert forbidden not in caplog.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_startup_failure_disposes_engine_without_exposing_exception(
    infrastructure: tuple[MagicMock, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(entry, "MinioImageStore", MagicMock(side_effect=RuntimeError(PRIVATE)))
    application = _application()
    with pytest.raises(RuntimeError, match=r"^visitor display lifecycle failed$") as raised:
        async with application.router.lifespan_context(application):
            pytest.fail("failed startup entered lifespan")
    assert raised.value.__suppress_context__ is True
    infrastructure[1].dispose.assert_awaited_once()


def test_fresh_import_and_disabled_startup_do_not_import_runtime_or_providers(
    tmp_path: Path,
) -> None:
    backend = Path(__file__).resolve().parents[2]
    script = """
import asyncio
import sys
from app.visitor_display_main import create_app, load_settings
app = create_app(load_settings({}))
async def check():
    async with app.router.lifespan_context(app):
        assert not hasattr(app.state, 'session_factory')
asyncio.run(check())
for name in sys.modules:
    assert name != 'app.api_main'
    assert not name.startswith('app.infrastructure.ai.')
    assert not (name.startswith('app.') and name.endswith(('_worker_main', '_scheduler_main')))
print('isolated_import_ok')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={"PATH": os.environ["PATH"], "PYTHONPATH": str(backend)},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "isolated_import_ok"
