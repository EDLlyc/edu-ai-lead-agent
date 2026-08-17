from __future__ import annotations

from collections.abc import Callable

from app.application.ports.agent_workbench import ToolCallingModel
from app.application.services.agent_tools import TypedToolRegistry, build_agent_tool_registry
from app.application.services.agent_workbench import AgentWorkbenchService
from app.domain.agent_workbench import AgentRunLimits
from app.infrastructure.agent_workbench_fixture import build_fixture_reader
from app.infrastructure.ai.agent_workbench import DeterministicPolicyToolCallingModel


def build_fixture_tool_registry(scenario_id: str | None = None) -> TypedToolRegistry:
    return build_agent_tool_registry(build_fixture_reader(scenario_id))


def build_fixture_agent_workbench(
    *,
    model_factory: Callable[[str], ToolCallingModel] | None = None,
    default_model_mode: str = "deterministic",
    allowed_model_modes: frozenset[str] | None = None,
    limits: AgentRunLimits | None = None,
) -> AgentWorkbenchService:
    resolved_factory = model_factory or _deterministic_model_factory
    return AgentWorkbenchService(
        registry_factory=build_fixture_tool_registry,
        model_factory=resolved_factory,
        default_model_mode=default_model_mode,
        allowed_model_modes=allowed_model_modes,
        limits=limits,
    )


def _deterministic_model_factory(mode: str) -> ToolCallingModel:
    if mode != "deterministic":
        raise ValueError("only deterministic mode is available in the fixture runtime")
    return DeterministicPolicyToolCallingModel()
