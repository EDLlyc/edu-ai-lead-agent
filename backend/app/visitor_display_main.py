"""Local, read-only visitor adapter; run with uvicorn's explicit --factory mode.

Only allowlisted process settings are read. Importing this module does not construct an
application, load dotenv files, connect to storage, or initialize a production provider.
Production database access stays read-only. The optional operator review store is a local
SQLite file. The optional "人工加推" forwards one PIN-approved candidate to the production API
through the loopback tunnel; production validates it and runs the normal pipeline.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.exceptions import HTTPException
from starlette.middleware.gzip import GZipMiddleware

from app.api.v1.routes.visitor_display import router
from app.api.v1.routes.visitor_display_human_pick import router as human_pick_router
from app.api.v1.routes.visitor_display_review import OperatorGate
from app.api.v1.routes.visitor_display_review import router as review_router
from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.storage.minio_image_store import MinioImageStore
from app.infrastructure.storage.minio_snapshot_store import MinioSnapshotStore
from app.infrastructure.visitor_review_store import VisitorReviewStore

_ENV_FIELDS = {
    "VISITOR_DISPLAY_ENABLED": "visitor_display_enabled",
    "VISITOR_DISPLAY_ASSET_SECRET": "visitor_display_asset_secret",
    "DATABASE_URL": "database_url",
    "MINIO_ENDPOINT": "minio_endpoint",
    "MINIO_BUCKET": "minio_bucket",
    "MINIO_SECURE": "minio_secure",
    "MINIO_ACCESS_KEY": "minio_access_key",
    "MINIO_SECRET_KEY": "minio_secret_key",
    "IMAGE_ASSET_MANIFEST": "image_asset_manifest",
    "VISITOR_DISPLAY_REVIEW_DB": "visitor_display_review_db",
    "VISITOR_DISPLAY_OPERATOR_PIN": "visitor_display_operator_pin",
    "VISITOR_DISPLAY_PRODUCTION_API_URL": "visitor_display_production_api_url",
}
_REQUIRED_CONNECTION_FIELDS = frozenset(
    {
        "database_url",
        "minio_endpoint",
        "minio_bucket",
        "minio_secure",
        "minio_access_key",
        "minio_secret_key",
    }
)
_LOGGER = logging.getLogger(__name__)
_SAFE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class VisitorDisplayConfigurationError(ValueError):
    """A configuration rejection without input values, paths, or credentials."""


class _VisitorSettings(Settings):
    # The production baseline predates these two fields. Do not import the full API
    # or replace its Settings module just to read the visitor projection.
    visitor_display_enabled: bool = False
    visitor_display_asset_secret: SecretStr | None = None
    # Operator-local human review; both must be set, otherwise review is simply absent.
    visitor_display_review_db: str = ""
    visitor_display_operator_pin: SecretStr | None = None
    # Loopback end of the SSH tunnel to the production API; enables PIN-gated "人工加推".
    visitor_display_production_api_url: str = ""

    @property
    def visitor_review_enabled(self) -> bool:
        return (
            bool(self.visitor_display_review_db) and self.visitor_display_operator_pin is not None
        )

    @property
    def visitor_human_pick_enabled(self) -> bool:
        return self.visitor_review_enabled and bool(self.visitor_display_production_api_url)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


class _HealthResponse(BaseModel):
    service: str = "visitor-display-local"
    status: str = "ok"


def load_settings(environ: Mapping[str, str] | None = None) -> _VisitorSettings:
    """Load the small operator allowlist, never the root dotenv or provider config."""
    source = os.environ if environ is None else environ
    values = {field: source[key] for key, field in _ENV_FIELDS.items() if key in source}
    return _validated_settings(values)


def _validated_settings(values: Mapping[str, Any]) -> _VisitorSettings:
    try:
        settings = _VisitorSettings(_env_file=None, **dict(values))  # type: ignore[call-arg]
        if settings.visitor_display_enabled:
            _validate_connections(settings)
        _validate_review(settings)
        _validate_production_api(settings)
        # An absent operator-supplied catalog is unavailable, not a default local catalog.
        if "image_asset_manifest" not in values:
            settings.image_asset_manifest = ""
        return settings
    except Exception:
        raise VisitorDisplayConfigurationError("visitor display configuration rejected") from None


def _validate_connections(settings: _VisitorSettings) -> None:
    if not _REQUIRED_CONNECTION_FIELDS.issubset(settings.model_fields_set):
        raise ValueError("explicit connection settings required")
    secret = settings.visitor_display_asset_secret
    if secret is None or len(secret.get_secret_value().strip().encode("utf-8")) < 32:
        raise ValueError("asset secret required")
    database = make_url(settings.database_url.get_secret_value())
    if (
        database.drivername != "postgresql+asyncpg"
        or database.host not in {"127.0.0.1", "::1"}
        or database.port is None
        or not 1 <= database.port <= 65535
        or not database.username
        or not database.password
        or not database.database
        or database.query
        or database.password == "edu_ai_local_change_me"
    ):
        raise ValueError("explicit loopback database required")
    endpoint = urlsplit(settings.minio_endpoint)
    if (
        endpoint.scheme != ("https" if settings.minio_secure else "http")
        or endpoint.hostname not in {"127.0.0.1", "::1"}
        or endpoint.port is None
        or not 1 <= endpoint.port <= 65535
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.path not in {"", "/"}
        or endpoint.query
        or endpoint.fragment
        or not settings.minio_bucket.strip()
        or not settings.minio_access_key.get_secret_value().strip()
        or not settings.minio_secret_key.get_secret_value().strip()
        or settings.minio_access_key.get_secret_value() == "edu_ai_minio"
        or settings.minio_secret_key.get_secret_value() == "edu_ai_minio_local_change_me"
    ):
        raise ValueError("explicit loopback object store required")


def _validate_review(settings: _VisitorSettings) -> None:
    configured = (bool(settings.visitor_display_review_db), settings.visitor_display_operator_pin)
    if not configured[0] and configured[1] is None:
        return
    pin = configured[1].get_secret_value() if configured[1] is not None else ""
    if (
        not configured[0]
        or not Path(settings.visitor_display_review_db).is_absolute()
        or not 4 <= len(pin) <= 32
        or pin != pin.strip()
    ):
        raise ValueError("review store and operator PIN must be configured together")


def _validate_production_api(settings: _VisitorSettings) -> None:
    value = settings.visitor_display_production_api_url
    if not value:
        return
    url = urlsplit(value)
    if (
        not settings.visitor_review_enabled
        or url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "::1"}
        or url.port is None
        or not 1 <= url.port <= 65535
        or url.username is not None
        or url.password is not None
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        raise ValueError("human pick needs the operator PIN and a loopback production API")


def _safe_error(status_code: int) -> JSONResponse:
    code, message = {
        403: ("forbidden", "operator PIN was rejected"),
        404: ("not_found", "visitor display resource was not found"),
        405: ("method_not_allowed", "method is not supported"),
        409: ("conflict", "visitor display content could not be verified"),
        422: ("invalid_request", "visitor display request was rejected"),
        429: ("too_many_attempts", "operator PIN is temporarily locked"),
    }.get(status_code, ("visitor_display_unavailable", "visitor display is unavailable"))
    status = status_code if status_code in {403, 404, 405, 409, 422, 429} else 503
    headers = dict(_SAFE_HEADERS)
    if status == 405:
        headers["Allow"] = "GET"
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Compose only visitor reads, with fresh sanitized settings and bounded storage."""
    configured = (
        load_settings()
        if settings is None
        else _validated_settings(
            {
                field: getattr(settings, field)
                for field in _ENV_FIELDS.values()
                if field in settings.model_fields_set
            }
        )
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if not configured.visitor_display_enabled:
            yield
            return
        engine = None
        human_pick_client: httpx.AsyncClient | None = None
        try:
            engine = create_async_engine(
                configured.database_url.get_secret_value(),
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
            application.state.session_factory = create_session_factory(engine)
            application.state.image_store = MinioImageStore(configured)
            application.state.snapshot_store = MinioSnapshotStore(configured)
            if configured.visitor_review_enabled:
                store = VisitorReviewStore(Path(configured.visitor_display_review_db))
                store.initialize()
                application.state.review_store = store
            if configured.visitor_human_pick_enabled:
                human_pick_client = httpx.AsyncClient(
                    base_url=configured.visitor_display_production_api_url.rstrip("/"),
                    timeout=httpx.Timeout(20.0, connect=5.0),
                    trust_env=False,
                    follow_redirects=False,
                )
                application.state.human_pick_client = human_pick_client
            yield
        except Exception:
            raise RuntimeError("visitor display lifecycle failed") from None
        finally:
            if human_pick_client is not None:
                await human_pick_client.aclose()
            if engine is not None:
                try:
                    await engine.dispose()
                except Exception:
                    raise RuntimeError("visitor display cleanup failed") from None

    application = FastAPI(
        title="Local visitor display",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        redirect_slashes=False,
    )
    application.state.settings = configured
    # The snapshot is several hundred KB of JSON, refetched every few seconds by each screen.
    application.add_middleware(GZipMiddleware, minimum_size=4096)
    application.include_router(router, prefix="/api/v1")
    if configured.visitor_display_enabled and configured.visitor_review_enabled:
        assert configured.visitor_display_operator_pin is not None
        application.state.operator_gate = OperatorGate(
            configured.visitor_display_operator_pin.get_secret_value()
        )
        application.include_router(review_router, prefix="/api/v1")
        if configured.visitor_human_pick_enabled:
            application.include_router(human_pick_router, prefix="/api/v1")

    @application.middleware("http")
    async def safe_boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not configured.visitor_display_enabled and request.url.path.startswith(
            "/api/v1/visitor-display/"
        ):
            return _safe_error(404)
        try:
            return await call_next(request)
        except Exception as error:
            # A generic Exception handler alone is re-raised by Starlette and logged
            # by uvicorn with SQL/credentials. Consume it at the outer HTTP boundary;
            # record only the route kind and exception class for the operator.
            parts = request.url.path.split("/")
            _LOGGER.warning(
                "visitor adapter request failed: %s %s",
                parts[4] if len(parts) > 4 else "other",
                type(error).__name__,
            )
            return _safe_error(503)

    @application.exception_handler(AppError)
    async def app_error(_request: Request, error: AppError) -> JSONResponse:
        return _safe_error(error.status_code)

    @application.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException) -> JSONResponse:
        return _safe_error(error.status_code)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
        return _safe_error(422)

    @application.get("/healthz", response_model=_HealthResponse)
    async def healthz() -> _HealthResponse:
        # Process liveness only; a snapshot is required to establish database access.
        return _HealthResponse()

    return application


__all__ = ["VisitorDisplayConfigurationError", "create_app", "load_settings"]
