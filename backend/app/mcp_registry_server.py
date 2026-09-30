"""Serve one TypedToolRegistry over MCP, unchanged.

The same registry object backs model function calling, local MCP clients and the evaluations, so
a tool's name, description, input and output schema, limits and refusals are defined once. This
adapter adds only what an MCP process needs around it:

- server instructions (the routing rules a client model should follow);
- tool annotations derived from the registry (read-only, or edits an in-memory workspace only);
- structured tool errors: `isError` with `{error_code, retryable, hint, fields?}` content, and an
  unknown tool as a JSON-RPC invalid-params protocol error;
- one JSON log line per call on stderr (never raw arguments), and a per-process call budget.
"""

from __future__ import annotations

import inspect
import json
import sys
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.tools import Tool
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INVALID_PARAMS,
    CallToolResult,
    InputRequiredResult,
    TextContent,
    ToolAnnotations,
)
from pydantic import BaseModel

from app.application.services.agent_tools import (
    AgentToolFailure,
    ToolDefinition,
    TypedToolRegistry,
)
from app.domain.agent_workbench import AgentToolErrorCode

DEFAULT_MCP_CALL_BUDGET = 200
MAX_MCP_CALL_BUDGET = 2_000
CALL_BUDGET_EXHAUSTED = "mcp_call_budget_exhausted"

CallLogger = Callable[[Mapping[str, object]], None]


def stderr_json_logger(record: Mapping[str, object]) -> None:
    """stdout carries the stdio protocol, so call logs go to stderr as JSON lines."""

    sys.stderr.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stderr.flush()


class RegistryMCPServer(MCPServer[None]):
    """An MCPServer whose tools and invocation path come only from one TypedToolRegistry."""

    def __init__(
        self,
        registry: TypedToolRegistry,
        *,
        name: str,
        title: str,
        description: str,
        instructions: str,
        version: str,
        call_budget: int = DEFAULT_MCP_CALL_BUDGET,
        call_logger: CallLogger | None = stderr_json_logger,
        lifespan: Callable[[MCPServer[None]], AbstractAsyncContextManager[None]] | None = None,
    ) -> None:
        if not 1 <= call_budget <= MAX_MCP_CALL_BUDGET:
            raise ValueError("MCP call budget is out of range")
        self.registry = registry
        self.call_budget = call_budget
        self.calls_used = 0
        self._call_logger = call_logger
        tools = tuple(_build_mcp_tool(registry, definition) for definition in registry)
        self._registered_tools = {tool.name: tool for tool in tools}
        super().__init__(
            name=name,
            title=title,
            description=description,
            instructions=instructions,
            version=version,
            tools=list(tools),
            lifespan=lifespan,
        )

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Any | None = None,
    ) -> CallToolResult | InputRequiredResult:
        del context
        started = time.monotonic()
        self.calls_used += 1
        argument_bytes = len(json.dumps(arguments, ensure_ascii=False).encode("utf-8"))
        if name not in self._registered_tools:
            self._log(name=None, error_code=AgentToolErrorCode.UNKNOWN.value, started=started)
            # An unknown tool is a protocol error, not a tool result a model should retry.
            raise MCPError(
                INVALID_PARAMS,
                f"{AgentToolErrorCode.UNKNOWN.value}: tool is not registered",
            )
        if self.calls_used > self.call_budget:
            self._log(name=name, error_code=CALL_BUDGET_EXHAUSTED, started=started)
            return _error_result(
                f"{CALL_BUDGET_EXHAUSTED}: this server process has used its call budget",
                {
                    "ok": False,
                    "error_code": CALL_BUDGET_EXHAUSTED,
                    "retryable": False,
                    "hint": "stop calling tools and report what is done so far",
                },
            )
        try:
            result = await self.registry.invoke(name, arguments)
        except AgentToolFailure as failure:
            self._log(
                name=name,
                error_code=failure.code.value,
                started=started,
                argument_bytes=argument_bytes,
            )
            return _error_result(f"{failure.code.value}: {failure.safe_message}", failure.payload())
        result_bytes = len(result.model_dump_json().encode("utf-8"))
        self._log(
            name=name,
            error_code=getattr(result, "error_code", None),
            started=started,
            argument_bytes=argument_bytes,
            result_bytes=result_bytes,
        )
        converted = self._registered_tools[name].fn_metadata.convert_result(result)
        if isinstance(converted, InputRequiredResult):  # pragma: no cover - registry never elicits
            return _error_result(
                "agent_tool_unavailable: tool elicitation is not supported",
                AgentToolFailure(AgentToolErrorCode.UNAVAILABLE).payload(),
            )
        return converted

    def _log(
        self,
        *,
        name: str | None,
        error_code: object,
        started: float,
        argument_bytes: int | None = None,
        result_bytes: int | None = None,
    ) -> None:
        if self._call_logger is None:
            return
        record: dict[str, object] = {
            "event": "mcp_tool_call",
            "server": self.name,
            # An unknown name is caller-controlled text, so it is never logged.
            "tool": name,
            "ok": error_code is None,
            "error_code": error_code if isinstance(error_code, str) else None,
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
            "call": self.calls_used,
            "budget": self.call_budget,
        }
        if argument_bytes is not None:
            record["argument_bytes"] = argument_bytes
        if result_bytes is not None:
            record["result_bytes"] = result_bytes
        self._call_logger(record)


def _error_result(text: str, payload: Mapping[str, object]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=dict(payload),
        is_error=True,
    )


def _annotations(definition: ToolDefinition) -> ToolAnnotations:
    if definition.read_only:
        return ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        )
    # Registry guards allow a writing tool only when it edits a caller-owned in-memory workspace.
    return ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=False,
    )


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
        annotations=_annotations(definition),
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


def call_budget_from_environment(environ: Mapping[str, str]) -> int:
    raw = environ.get("AGENT_MCP_MAX_CALLS", "").strip()
    if not raw:
        return DEFAULT_MCP_CALL_BUDGET
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError("AGENT_MCP_MAX_CALLS must be an integer") from None
    if not 1 <= value <= MAX_MCP_CALL_BUDGET:
        raise RuntimeError("AGENT_MCP_MAX_CALLS is out of range")
    return value
