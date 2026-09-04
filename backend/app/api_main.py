from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

import httpx
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.routes import (
    acquisition_runs,
    brand_knowledge,
    candidate_analyses,
    content_slots,
    copy_generation,
    events,
    evidence_candidates,
    governance_runs,
    ip_assets,
    material_packages,
    official_account_local,
    sources,
    topic_selection_runs,
    wecom_deliveries,
)
from app.application.ports.ip_assets import IpAssetRecognitionModel
from app.application.ports.visual_retrieval import VisualEmbeddingModel
from app.application.services.ip_asset_recognition import IpAssetRecognitionService
from app.application.services.ip_assets import IpAssetService
from app.application.services.visual_retrieval import VisualRetrievalService
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.infrastructure.ai.factory import (
    create_brand_embedding_model,
    create_image_generator,
    create_ip_asset_recognition_model,
    select_brand_embedding_client,
)
from app.infrastructure.ai.visual_embedding import (
    AlibabaVisualEmbeddingAdapter,
    DeterministicFakeVisualEmbedding,
)
from app.infrastructure.db.ip_assets import PostgresIpAssetRepository
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.visual_retrieval import PostgresVisualIndexRepository
from app.infrastructure.storage.minio_brand_store import MinioBrandOriginalStore
from app.infrastructure.storage.minio_image_store import MinioImageStore
from app.infrastructure.storage.minio_ip_asset_store import MinioIpAssetStore
from app.infrastructure.storage.minio_snapshot_store import MinioSnapshotStore
from app.schemas.common import ErrorDetail, ErrorEnvelope

settings = get_settings()
configure_logging(json_output=settings.app_env != "development")
logger = structlog.get_logger()
engine = create_engine(settings)
session_factory = create_session_factory(engine)


class HealthResponse(BaseModel):
    service: str
    status: Literal["ok"]
    environment: str
    timezone: str


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    image_client: httpx.AsyncClient | None = None
    brand_embedding_client: httpx.AsyncClient | None = None
    visual_embedding_client: httpx.AsyncClient | None = None
    ip_asset_recognition_client: httpx.AsyncClient | None = None
    visual_embeddings: VisualEmbeddingModel | None = None
    ip_asset_recognition_model: IpAssetRecognitionModel | None = None
    _app.state.brand_original_store = MinioBrandOriginalStore(settings)
    _app.state.brand_embedding_model = None
    _app.state.image_store = MinioImageStore(settings)
    _app.state.snapshot_store = MinioSnapshotStore(settings)
    _app.state.image_generator = None
    _app.state.visual_retrieval_service = None
    _app.state.ip_asset_service = None
    _app.state.ip_asset_recognition_service = None
    _app.state.ip_asset_upload_semaphore = asyncio.Semaphore(settings.ip_asset_upload_concurrency)
    brand_embedding_mode = settings.resolved_brand_embedding_provider_mode
    alibaba_embedding_required = brand_embedding_mode == "alibaba" or (
        settings.visual_semantic_enabled and settings.visual_embedding_provider_mode == "alibaba"
    )
    if brand_embedding_mode == "zhipu":
        brand_embedding_client = httpx.AsyncClient(follow_redirects=False)
    if alibaba_embedding_required:
        visual_embedding_client = httpx.AsyncClient(follow_redirects=False)
    if brand_embedding_mode != "disabled":
        _app.state.brand_embedding_model = create_brand_embedding_model(
            settings,
            client=select_brand_embedding_client(
                settings,
                zhipu_client=brand_embedding_client,
                alibaba_client=visual_embedding_client,
            ),
        )
    logger.info(
        "api_brand_embedding_configured",
        provider=settings.brand_embedding_provider,
        model=settings.brand_embedding_model,
        dimensions=settings.brand_embedding_dimensions,
    )
    if settings.image_enabled and settings.image_provider_mode != "disabled":
        if settings.image_provider_mode in {"toapis", "comfly"}:
            image_client = httpx.AsyncClient(follow_redirects=False)
        _app.state.image_generator = create_image_generator(settings, client=image_client)
    if settings.visual_semantic_enabled:
        if settings.visual_embedding_provider_mode == "fake":
            visual_embeddings = DeterministicFakeVisualEmbedding()
        else:
            if (
                settings.visual_embedding_endpoint is None
                or settings.visual_embedding_api_key is None
            ):
                raise RuntimeError("validated visual embedding secrets are unavailable")
            if visual_embedding_client is None:
                visual_embedding_client = httpx.AsyncClient(follow_redirects=False)
            visual_embeddings = AlibabaVisualEmbeddingAdapter(
                client=visual_embedding_client,
                endpoint=settings.visual_embedding_endpoint,
                api_key=settings.visual_embedding_api_key,
                timeout_seconds=settings.visual_embedding_timeout_seconds,
                concurrency=settings.visual_embedding_concurrency,
            )
        _app.state.visual_retrieval_service = VisualRetrievalService(
            embeddings=visual_embeddings,
            repository=PostgresVisualIndexRepository(session_factory),
            identity=settings.visual_embedding_identity,
        )
    if settings.ip_asset_hub_enabled:
        _app.state.ip_asset_service = IpAssetService(
            repository=PostgresIpAssetRepository(session_factory),
            store=MinioIpAssetStore(settings),
            embeddings=visual_embeddings,
            identity=settings.visual_embedding_identity,
            search_version=settings.ip_asset_search_version,
            business_timezone=settings.business_timezone,
        )
    if settings.ip_asset_recognition_enabled:
        ip_asset_recognition_client = httpx.AsyncClient(follow_redirects=False)
        ip_asset_recognition_model = create_ip_asset_recognition_model(
            settings,
            client=ip_asset_recognition_client,
        )
        if ip_asset_recognition_model is None:
            raise RuntimeError("validated IP asset recognition provider is unavailable")
        _app.state.ip_asset_recognition_service = IpAssetRecognitionService(
            ip_asset_recognition_model
        )
    try:
        yield
    finally:
        if image_client is not None:
            await image_client.aclose()
        if brand_embedding_client is not None:
            await brand_embedding_client.aclose()
        if visual_embedding_client is not None:
            await visual_embedding_client.aclose()
        if ip_asset_recognition_client is not None:
            await ip_asset_recognition_client.aclose()
        await engine.dispose()


app = FastAPI(
    title="Edu AI Lead Agent API",
    version="0.3.0",
    description=(
        "Internal API for authoritative-source acquisition, factual governance, and auditable "
        "event organization, deterministic daily topic selection, and private brand knowledge "
        "ingestion with internal copy-generation context retrieval. It does not expose public "
        "brand search, publishing, or arbitrary URL-fetch capabilities."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.browser_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID", "X-IP-Profile-Token"],
)
app.state.settings = settings
app.state.session_factory = session_factory
app.include_router(sources.router, prefix="/api/v1")
app.include_router(acquisition_runs.router, prefix="/api/v1")
app.include_router(evidence_candidates.router, prefix="/api/v1")
app.include_router(governance_runs.router, prefix="/api/v1")
app.include_router(ip_assets.router, prefix="/api/v1")
app.include_router(candidate_analyses.router, prefix="/api/v1")
app.include_router(events.router, prefix="/api/v1")
app.include_router(topic_selection_runs.router, prefix="/api/v1")
app.include_router(content_slots.router, prefix="/api/v1")
app.include_router(brand_knowledge.router, prefix="/api/v1")
app.include_router(copy_generation.router, prefix="/api/v1")
app.include_router(material_packages.router, prefix="/api/v1")
app.include_router(official_account_local.router, prefix="/api/v1")
app.include_router(wecom_deliveries.router, prefix="/api/v1")


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, error: AppError) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code=error.code,
            message=error.message,
            request_id=_request_id(request),
        )
    )
    return JSONResponse(status_code=error.status_code, content=envelope.model_dump(mode="json"))


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, _error: RequestValidationError
) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code="invalid_request",
            message="request validation failed",
            request_id=_request_id(request),
        )
    )
    return JSONResponse(status_code=422, content=envelope.model_dump(mode="json"))


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) and value else str(uuid4())


@app.get("/healthz", response_model=HealthResponse, tags=["system"])
async def healthz() -> HealthResponse:
    return HealthResponse(
        service="edu-ai-lead-agent-api",
        status="ok",
        environment=settings.app_env,
        timezone=settings.business_timezone,
    )
