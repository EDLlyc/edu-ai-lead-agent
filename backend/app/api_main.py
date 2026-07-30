from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.routes import (
    acquisition_runs,
    candidate_analyses,
    events,
    evidence_candidates,
    governance_runs,
    sources,
    topic_selection_runs,
)
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.infrastructure.db.session import create_engine, create_session_factory
from app.schemas.common import ErrorDetail, ErrorEnvelope

settings = get_settings()
configure_logging(json_output=settings.app_env != "development")
engine = create_engine(settings)
session_factory = create_session_factory(engine)


class HealthResponse(BaseModel):
    service: str
    status: Literal["ok"]
    environment: str
    timezone: str


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="Edu AI Lead Agent API",
    version="0.3.0",
    description=(
        "Internal API for authoritative-source acquisition, factual governance, and auditable "
        "event organization, and deterministic daily topic selection. It does not expose "
        "generation, publishing, or arbitrary URL-fetch capabilities."
    ),
    lifespan=lifespan,
)
app.state.settings = settings
app.state.session_factory = session_factory
app.include_router(sources.router, prefix="/api/v1")
app.include_router(acquisition_runs.router, prefix="/api/v1")
app.include_router(evidence_candidates.router, prefix="/api/v1")
app.include_router(governance_runs.router, prefix="/api/v1")
app.include_router(candidate_analyses.router, prefix="/api/v1")
app.include_router(events.router, prefix="/api/v1")
app.include_router(topic_selection_runs.router, prefix="/api/v1")


@app.middleware("http")
async def request_context(request: Request, call_next):
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
