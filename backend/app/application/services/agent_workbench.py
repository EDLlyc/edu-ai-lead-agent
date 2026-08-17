from __future__ import annotations

from collections.abc import Callable

from app.application.ports.agent_workbench import ToolCallingModel
from app.application.services.agent_tools import TypedToolRegistry
from app.application.services.agent_workbench_graph import BoundedAgentRunner
from app.domain.agent_workbench import AgentRunLimits, AgentRunResult

RegistryFactory = Callable[[str | None], TypedToolRegistry]
ModelFactory = Callable[[str], ToolCallingModel]


class AgentWorkbenchService:
    def __init__(
        self,
        *,
        registry_factory: RegistryFactory,
        model_factory: ModelFactory,
        default_model_mode: str = "deterministic",
        allowed_model_modes: frozenset[str] | None = None,
        limits: AgentRunLimits | None = None,
    ) -> None:
        self._registry_factory = registry_factory
        self._model_factory = model_factory
        self._default_model_mode = default_model_mode
        self._allowed_model_modes = allowed_model_modes or frozenset({default_model_mode})
        if default_model_mode not in self._allowed_model_modes:
            raise ValueError("default agent model mode must be allowlisted")
        self._limits = limits or AgentRunLimits()
        self._canonical_registry = registry_factory(None)

    @property
    def canonical_registry(self) -> TypedToolRegistry:
        return self._canonical_registry

    async def run(
        self,
        query: str,
        *,
        scenario_id: str | None = None,
        model_mode: str | None = None,
    ) -> AgentRunResult:
        resolved_mode = model_mode or self._default_model_mode
        if resolved_mode not in self._allowed_model_modes:
            raise ValueError("agent model mode is not enabled for this runtime")
        registry = self._registry_factory(scenario_id)
        runner = BoundedAgentRunner(
            registry=registry,
            model=self._model_factory(resolved_mode),
            limits=self._limits,
        )
        return await runner.run(query)
