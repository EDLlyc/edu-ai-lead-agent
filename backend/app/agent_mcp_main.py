"""Local-only stdio MCP adapter for the canonical Agent Workbench tool registry."""

from __future__ import annotations

import inspect
import os
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from mcp.types import CallToolResult, InputRequiredResult, ToolAnnotations
from pydantic import BaseModel

from app.application.services.agent_tools import (
    AgentToolFailure,
    ToolDefinition,
    TypedToolRegistry,
    build_agent_tool_registry,
)
from app.infrastructure.agent_workbench_fixture import build_fixture_reader

MCP_SERVER_NAME = "edu-ai-agent-workbench"
MCP_SERVER_VERSION = "1.0.0"


class AgentWorkbenchMCPServer(MCPServer[None]):
    """MCPServer whose invocation path delegates only to the shared registry."""

    def __init__(
        self,
        registry: TypedToolRegistry,
        *,
        lifespan: Callable[[MCPServer[None]], AbstractAsyncContextManager[None]] | None = None,
    ) -> None:
        self.registry = registry
        tools = tuple(_build_mcp_tool(registry, definition) for definition in registry)
        self._registered_tools = {tool.name: tool for tool in tools}
        super().__init__(
            name=MCP_SERVER_NAME,
            title="Local Agent Research Workbench",
            description=(
                "Four bounded, read-only tools backed by the canonical local workbench registry."
            ),
            version=MCP_SERVER_VERSION,
            tools=list(tools),
            lifespan=lifespan,
        )

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Any | None = None,
    ) -> CallToolResult | InputRequiredResult:
        """Invoke the registry and project only bounded stable failures to MCP."""

        del context
        try:
            result = await self.registry.invoke(name, arguments)
        except AgentToolFailure as exc:
            raise ToolError(f"{exc.code.value}: {exc.safe_message}") from None
        tool = self._registered_tools[name]
        converted = tool.fn_metadata.convert_result(result)
        if isinstance(converted, InputRequiredResult):  # pragma: no cover - registry never elicits
            raise ToolError("agent_tool_unavailable: tool elicitation is not supported")
        return converted


def build_agent_mcp_server(
    registry: TypedToolRegistry | None = None,
    *,
    lifespan: Callable[[MCPServer[None]], AbstractAsyncContextManager[None]] | None = None,
) -> AgentWorkbenchMCPServer:
    """Build the stdio-capable server with fixture-only defaults."""

    resolved = registry or build_agent_tool_registry(build_fixture_reader())
    return AgentWorkbenchMCPServer(resolved, lifespan=lifespan)


def validate_agent_mcp_environment(environ: Mapping[str, str]) -> None:
    """Reject production or live-provider process configuration before stdio starts."""

    environment = environ.get("APP_ENV", "development").strip().casefold()
    provider_mode = environ.get("AI_PROVIDER_MODE", "fake").strip().casefold()
    if environment == "production":
        raise RuntimeError("agent MCP is local-only and cannot run in production")
    if provider_mode not in {"", "fake"}:
        raise RuntimeError("agent MCP supports only the offline fixture provider mode")


def main() -> None:
    """Run the official MCP v2 server on stdio and no network transport."""

    validate_agent_mcp_environment(os.environ)
    build_agent_mcp_server().run(transport="stdio")


def _build_mcp_tool(registry: TypedToolRegistry, definition: ToolDefinition) -> Tool:
    # MCPServer's decorator derives a second schema from a Python signature. The pinned v2 Tool
    # registration object lets list_tools expose the registry's exact canonical schema instead;
    # contract tests lock this narrow SDK seam and structured-output conversion behavior.
    async def invoke_registered_tool(**arguments: object) -> BaseModel:
        return await registry.invoke(definition.name, arguments)

    invoke_registered_tool.__name__ = definition.name
    invoke_registered_tool.__doc__ = definition.description
    invoke_registered_tool.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=tuple(
            inspect.Parameter(
                name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=(
                    inspect.Parameter.empty
                    if field.is_required()
                    else field.get_default(call_default_factory=True)
                ),
                annotation=field.rebuild_annotation(),
            )
            for name, field in definition.argument_model.model_fields.items()
        ),
        return_annotation=definition.result_model,
    )
    generated = Tool.from_function(
        invoke_registered_tool,
        name=definition.name,
        description=definition.description,
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    metadata = generated.fn_metadata.model_copy(
        update={
            "output_schema": definition.output_schema(),
            "output_model": definition.result_model,
            "wrap_output": False,
        }
    )
    return generated.model_copy(
        update={
            "parameters": definition.input_schema(),
            "fn_metadata": metadata,
        }
    )


if __name__ == "__main__":
    main()
