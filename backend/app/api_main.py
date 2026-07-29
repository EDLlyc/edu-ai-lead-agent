from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.routes import acquisition_runs, evidence_candidates, sources
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
    version="0.2.0",
    description=(
        "Internal API for governed authoritative-source acquisition and evidence ingestion."
    ),
    lifespan=lifespan,
)
app.state.settings = settings
app.state.session_factory = session_factory
app.include_router(sources.router, prefix="/api/v1")
app.include_router(acquisition_runs.router, prefix="/api/v1")
app.include_router(evidence_candidates.router, prefix="/api/v1")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, error: AppError) -> JSONResponse:
    envelope = ErrorEnvelope(error=ErrorDetail(code=error.code, message=error.message))
    return JSONResponse(status_code=error.status_code, content=envelope.model_dump(mode="json"))


@app.get("/healthz", response_model=HealthResponse, tags=["system"])
async def healthz() -> HealthResponse:
    return HealthResponse(
        service="edu-ai-lead-agent-api",
        status="ok",
        environment=settings.app_env,
        timezone=settings.business_timezone,
    )
