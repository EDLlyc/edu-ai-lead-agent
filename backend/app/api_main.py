from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from app.core.config import get_settings


class HealthResponse(BaseModel):
    service: str
    status: Literal["ok"]
    environment: str
    timezone: str


settings = get_settings()

app = FastAPI(
    title="Edu AI Lead Agent API",
    version="0.1.0",
    description=(
        "Environment verification shell; business pipeline endpoints are not implemented yet."
    ),
)


@app.get("/healthz", response_model=HealthResponse, tags=["system"])
async def healthz() -> HealthResponse:
    return HealthResponse(
        service="edu-ai-lead-agent-api",
        status="ok",
        environment=settings.app_env,
        timezone=settings.business_timezone,
    )
