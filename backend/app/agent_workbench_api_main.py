from __future__ import annotations

import ipaddress
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.agent_workbench_runtime import build_fixture_agent_workbench
from app.api.v1.routes import agent_workbench
from app.application.ports.agent_workbench import ToolCallingModel
from app.application.services.agent_workbench import AgentWorkbenchService
from app.core.agent_workbench_config import (
    AgentWorkbenchSettings,
    get_agent_workbench_settings,
)
from app.core.errors import AppError
from app.infrastructure.ai.agent_workbench import (
    DeterministicPolicyToolCallingModel,
    OpenAICompatibleToolCallingModel,
)
from app.schemas.common import ErrorDetail, ErrorEnvelope


class AgentWorkbenchHealthResponse(BaseModel):
    service: str
    status: Literal["ok"]
    environment: str
    enabled: bool


_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_LOCAL_UI_ORIGIN = "http://127.0.0.1:5173"


def create_agent_workbench_app(
    *,
    settings: AgentWorkbenchSettings | None = None,
    service: AgentWorkbenchService | None = None,
) -> FastAPI:
    resolved_settings = settings or get_agent_workbench_settings()
    provider_client: httpx.AsyncClient | None = None
    if service is None:
        if resolved_settings.agent_workbench_model_mode == "openai":
            provider_client = httpx.AsyncClient(follow_redirects=False)
            configured_model = OpenAICompatibleToolCallingModel(
                client=provider_client,
                base_url=resolved_settings.agent_workbench_openai_base_url or "",
                api_key=resolved_settings.agent_workbench_openai_api_key,
                model=resolved_settings.agent_workbench_openai_model,
            )

            def model_factory(mode: str) -> ToolCallingModel:
                if mode == "openai":
                    return configured_model
                if mode == "deterministic":
                    return DeterministicPolicyToolCallingModel()
                raise ValueError("agent model mode is unavailable")

            resolved_service = build_fixture_agent_workbench(
                model_factory=model_factory,
                default_model_mode="openai",
                allowed_model_modes=frozenset({"openai", "deterministic"}),
            )
        else:
            resolved_service = build_fixture_agent_workbench()
    else:
        resolved_service = service

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if provider_client is not None:
                await provider_client.aclose()

    local_app = FastAPI(
        title="Edu AI Agent Research Workbench",
        version="0.1.0",
        description=(
            "Local-only, read-only Agent research workbench with a bounded tool-calling loop. "
            "This independent application is absent from the production API and performs no "
            "publishing, delivery, arbitrary URL fetching, shell execution, or durable writes."
        ),
        lifespan=lifespan,
    )
    local_app.state.settings = resolved_settings
    local_app.state.agent_workbench_service = resolved_service
    local_app.include_router(agent_workbench.router, prefix="/api/v1")
    local_app.add_middleware(
        CORSMiddleware,
        allow_origins=[_LOCAL_UI_ORIGIN],
        allow_credentials=False,
        allow_methods=["POST"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    @local_app.middleware("http")
    async def local_request_gate(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _safe_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        if _contains_forwarding_header(request) or not _is_loopback_peer(request):
            return _error_response(
                request_id=request_id,
                status_code=403,
                code="agent_workbench_loopback_required",
                message="agent workbench requires a direct loopback connection",
            )
        origin = request.headers.get("origin")
        if origin is not None and origin != _LOCAL_UI_ORIGIN:
            return _error_response(
                request_id=request_id,
                status_code=403,
                code="agent_workbench_origin_rejected",
                message="agent workbench request origin is not allowlisted",
            )
        if (
            request.url.path.startswith("/api/v1/agent-workbench")
            and not resolved_settings.agent_workbench_enabled
        ):
            return _error_response(
                request_id=request_id,
                status_code=404,
                code="agent_workbench_disabled",
                message="agent workbench is disabled",
            )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @local_app.exception_handler(AppError)
    async def app_error_handler(request: Request, error: AppError) -> JSONResponse:
        return _error_response(
            request_id=_request_id(request),
            status_code=error.status_code,
            code=error.code,
            message=error.message,
        )

    @local_app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            request_id=_request_id(request),
            status_code=422,
            code="invalid_request",
            message="request validation failed",
        )

    @local_app.get("/healthz", response_model=AgentWorkbenchHealthResponse, tags=["system"])
    async def healthz() -> AgentWorkbenchHealthResponse:
        return AgentWorkbenchHealthResponse(
            service="edu-ai-agent-workbench",
            status="ok",
            environment=resolved_settings.app_env,
            enabled=resolved_settings.agent_workbench_enabled,
        )

    return local_app


def _contains_forwarding_header(request: Request) -> bool:
    return any(
        name.casefold() == "forwarded" or name.casefold().startswith("x-forwarded-")
        for name in request.headers
    )


def _is_loopback_peer(request: Request) -> bool:
    if request.client is None:
        return False
    try:
        address = ipaddress.ip_address(request.client.host)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped is not None and mapped.is_loopback


def _error_response(
    *,
    request_id: str,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    envelope = ErrorEnvelope(error=ErrorDetail(code=code, message=message, request_id=request_id))
    response = JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))
    response.headers["X-Request-ID"] = request_id
    return response


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) and value else str(uuid4())


def _safe_request_id(value: str | None) -> str:
    if value is not None and _SAFE_REQUEST_ID.fullmatch(value) is not None:
        return value
    return str(uuid4())


app = create_agent_workbench_app()
