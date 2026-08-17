from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.application.services.agent_workbench import AgentWorkbenchService
from app.core.errors import AppError
from app.schemas.agent_workbench import (
    AgentWorkbenchRunRequest,
    AgentWorkbenchRunResponse,
)

router = APIRouter(prefix="/agent-workbench", tags=["agent-workbench"])


def get_agent_workbench_service(request: Request) -> AgentWorkbenchService:
    return cast(AgentWorkbenchService, request.app.state.agent_workbench_service)


@router.post("/runs", response_model=AgentWorkbenchRunResponse)
async def run_agent_workbench(
    request: AgentWorkbenchRunRequest,
    service: Annotated[AgentWorkbenchService, Depends(get_agent_workbench_service)],
) -> AgentWorkbenchRunResponse:
    try:
        result = await service.run(
            request.query,
            scenario_id=request.scenario_id,
            model_mode=request.model_mode,
        )
    except ValueError:
        raise AppError(
            "agent_workbench_invalid_mode",
            "the requested workbench scenario or model mode is unavailable",
            422,
        ) from None
    return AgentWorkbenchRunResponse.from_result(result)
