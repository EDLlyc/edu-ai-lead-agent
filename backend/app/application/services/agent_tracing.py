"""Step traces for tool-using agents, named after the OpenTelemetry GenAI semantic conventions.

One agent invocation is an `invoke_agent` span; each model call inside it is a `chat` span and
each tool call an `execute_tool` span, with the convention's attribute names
(`gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`,
`gen_ai.tool.name`, `gen_ai.tool.call.id`, `gen_ai.conversation.id`, ...).

Two sinks, same span names and attributes:

- `OpenTelemetryTracer` when the opentelemetry API is installed and the caller configured a
  tracer provider (OTLP or any other exporter). It is an optional dependency: production code
  never imports opentelemetry at module load.
- `JsonlTraceRecorder` otherwise: keeps finished spans in memory (for evaluations and tests) and
  optionally appends one JSON line per span to a file.

Spans never carry message bodies, tool arguments or results: only names, ids, counts, timings and
error codes, so a trace file can be shared without copy, evidence or brand text.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

AttributeValue = str | int | float | bool

OPERATION = "gen_ai.operation.name"
AGENT_NAME = "gen_ai.agent.name"
CONVERSATION_ID = "gen_ai.conversation.id"
PROVIDER = "gen_ai.provider.name"
REQUEST_MODEL = "gen_ai.request.model"
INPUT_TOKENS = "gen_ai.usage.input_tokens"
OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
TOOL_NAME = "gen_ai.tool.name"
TOOL_CALL_ID = "gen_ai.tool.call.id"
TOOL_TYPE = "gen_ai.tool.type"
ERROR_TYPE = "error.type"


class TraceSpan(Protocol):
    def set_attribute(self, key: str, value: AttributeValue) -> None: ...


class AgentTracer(Protocol):
    def span(
        self, operation: str, name: str, attributes: Mapping[str, AttributeValue]
    ) -> Any:  # a context manager yielding a TraceSpan
        ...


def invoke_agent_attributes(
    agent_name: str, conversation_id: str, model: str | None, provider: str | None
) -> dict[str, AttributeValue]:
    attributes: dict[str, AttributeValue] = {
        OPERATION: "invoke_agent",
        AGENT_NAME: agent_name,
        CONVERSATION_ID: conversation_id,
    }
    if model:
        attributes[REQUEST_MODEL] = model
    if provider:
        attributes[PROVIDER] = provider
    return attributes


class NoopTracer:
    @contextmanager
    def span(
        self, operation: str, name: str, attributes: Mapping[str, AttributeValue]
    ) -> Iterator[TraceSpan]:
        yield _NoopSpan()


class _NoopSpan:
    def set_attribute(self, key: str, value: AttributeValue) -> None:
        return None


@dataclass(slots=True)
class RecordedSpan:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    start_ns: int
    end_ns: int = 0
    attributes: dict[str, AttributeValue] = field(default_factory=dict)
    status: str = "ok"

    def set_attribute(self, key: str, value: AttributeValue) -> None:
        self.attributes[key] = value

    def as_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "start_ns": self.start_ns,
            "end_ns": self.end_ns,
            "duration_ms": round((self.end_ns - self.start_ns) / 1_000_000, 1),
            "status": self.status,
            "attributes": dict(self.attributes),
        }


_CURRENT: ContextVar[RecordedSpan | None] = ContextVar("agent_trace_current", default=None)


class JsonlTraceRecorder:
    """Records spans in memory and, when given a path, appends them as JSON lines."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.spans: list[RecordedSpan] = []

    @contextmanager
    def span(
        self, operation: str, name: str, attributes: Mapping[str, AttributeValue]
    ) -> Iterator[RecordedSpan]:
        parent = _CURRENT.get()
        span = RecordedSpan(
            name=name,
            trace_id=parent.trace_id if parent is not None else secrets.token_hex(16),
            span_id=secrets.token_hex(8),
            parent_span_id=parent.span_id if parent is not None else None,
            start_ns=time.time_ns(),
            attributes={OPERATION: operation, **attributes},
        )
        token = _CURRENT.set(span)
        try:
            yield span
        except BaseException as error:
            span.status = "error"
            span.attributes.setdefault(ERROR_TYPE, type(error).__name__)
            raise
        finally:
            _CURRENT.reset(token)
            span.end_ns = time.time_ns()
            if ERROR_TYPE in span.attributes:
                span.status = "error"
            self.spans.append(span)
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(span.as_record(), ensure_ascii=False) + "\n")

    def records(self) -> list[dict[str, Any]]:
        return [span.as_record() for span in self.spans]


class OpenTelemetryTracer:
    """The same spans through the OpenTelemetry API (optional dependency)."""

    def __init__(self, instrumentation_name: str = "edu_ai.agents") -> None:
        from opentelemetry import trace  # optional; ImportError means "use the JSONL recorder"

        self._trace = trace
        self._tracer = trace.get_tracer(instrumentation_name)

    @contextmanager
    def span(
        self, operation: str, name: str, attributes: Mapping[str, AttributeValue]
    ) -> Iterator[Any]:
        kind = self._trace.SpanKind.CLIENT if operation == "chat" else self._trace.SpanKind.INTERNAL
        with self._tracer.start_as_current_span(
            name, kind=kind, attributes={OPERATION: operation, **attributes}
        ) as span:
            yield span


def default_tracer(path: Path | None = None) -> AgentTracer:
    """OpenTelemetry when importable, otherwise JSON lines (in memory, or appended to `path`)."""

    try:
        return OpenTelemetryTracer()
    except ImportError:
        return JsonlTraceRecorder(path)
