from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, cast

from pydantic import BaseModel, ValidationError

from app.application.ports.agent_workbench import AgentKnowledgeReader
from app.core.errors import AppError, NotFoundError
from app.core.security import is_public_https_url
from app.domain.agent_workbench import AgentToolErrorCode, SafeTraceValue
from app.domain.brand_knowledge import BrandAudience
from app.domain.copy_generation import validate_material_draft
from app.schemas.agent_workbench import (
    BrandContextToolItem,
    CopyValidationIssue,
    EventMemberToolItem,
    EvidenceToolItem,
    GetEventArguments,
    GetEventResult,
    RetrieveBrandContextArguments,
    RetrieveBrandContextResult,
    SearchEvidenceArguments,
    SearchEvidenceResult,
    ValidateCopyArguments,
    ValidateCopyResult,
)

_TOOL_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_TOOL_DESCRIPTION_MAX = 600
_QUERY_HASH_PREFIX = 16

ToolHandler = Callable[[BaseModel], Awaitable[BaseModel]]


class AgentToolFailure(Exception):
    def __init__(self, code: AgentToolErrorCode) -> None:
        super().__init__(code.value)
        self.code = code

    @property
    def safe_message(self) -> str:
        return {
            AgentToolErrorCode.INVALID_ARGUMENTS: "tool arguments failed validation",
            AgentToolErrorCode.UNKNOWN: "tool is not registered",
            AgentToolErrorCode.TIMEOUT: "tool execution timed out",
            AgentToolErrorCode.UNAVAILABLE: "tool is temporarily unavailable",
            AgentToolErrorCode.NOT_FOUND: "requested tool resource was not found",
            AgentToolErrorCode.OUTPUT_TOO_LARGE: "tool result exceeded its safe output limit",
        }[self.code]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    argument_model: type[BaseModel]
    result_model: type[BaseModel]
    handler: ToolHandler
    timeout_seconds: float = 5.0
    max_argument_bytes: int = 16 * 1024
    max_result_bytes: int = 32 * 1024
    read_only: bool = True
    open_world: bool = False

    def __post_init__(self) -> None:
        if _TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError("tool name is invalid")
        if not self.description.strip() or len(self.description) > _TOOL_DESCRIPTION_MAX:
            raise ValueError("tool description must be bounded and non-blank")
        if not 0 < self.timeout_seconds <= 5:
            raise ValueError("tool timeout must be between zero and five seconds")
        if not 1 <= self.max_argument_bytes <= 16 * 1024:
            raise ValueError("tool argument limit exceeds the workbench contract")
        if not 1 <= self.max_result_bytes <= 32 * 1024:
            raise ValueError("tool result limit exceeds the workbench contract")
        if not self.read_only or self.open_world:
            raise ValueError("agent workbench tools must be closed-world and read-only")

    def input_schema(self) -> dict[str, object]:
        return cast(dict[str, object], self.argument_model.model_json_schema(mode="validation"))

    def output_schema(self) -> dict[str, object]:
        return cast(dict[str, object], self.result_model.model_json_schema(mode="serialization"))

    def model_tool_schema(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema(),
                "strict": True,
            },
        }


class TypedToolRegistry:
    def __init__(self, definitions: Iterable[ToolDefinition]) -> None:
        ordered = tuple(definitions)
        if not ordered:
            raise ValueError("agent tool registry cannot be empty")
        names = tuple(definition.name for definition in ordered)
        if len(names) != len(set(names)):
            raise ValueError("agent tool registry contains duplicate names")
        if names != tuple(sorted(names)):
            raise ValueError("agent tool registry must use stable name ordering")
        self._definitions = ordered
        self._by_name = {definition.name: definition for definition in ordered}

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self._definitions

    def __iter__(self) -> Iterator[ToolDefinition]:
        return iter(self._definitions)

    def get(self, name: str) -> ToolDefinition:
        definition = self._by_name.get(name)
        if definition is None:
            raise AgentToolFailure(AgentToolErrorCode.UNKNOWN)
        return definition

    def canonical_schema(self) -> dict[str, object]:
        return {
            "schema_version": "agent-tool-registry-v1",
            "tools": [
                {
                    "name": definition.name,
                    "description": definition.description,
                    "input_schema": definition.input_schema(),
                    "output_schema": definition.output_schema(),
                    "timeout_seconds": definition.timeout_seconds,
                    "max_argument_bytes": definition.max_argument_bytes,
                    "max_result_bytes": definition.max_result_bytes,
                    "annotations": {
                        "read_only": definition.read_only,
                        "open_world": definition.open_world,
                    },
                }
                for definition in self._definitions
            ],
        }

    @property
    def schema_hash(self) -> str:
        payload = json.dumps(
            self.canonical_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return sha256(payload).hexdigest()

    def model_tool_schemas(self) -> tuple[Mapping[str, object], ...]:
        return tuple(definition.model_tool_schema() for definition in self._definitions)

    async def invoke(
        self,
        name: str,
        arguments: Mapping[str, object] | str,
    ) -> BaseModel:
        definition = self.get(name)
        arguments_json = _arguments_json(arguments, definition.max_argument_bytes)
        try:
            validated_arguments = definition.argument_model.model_validate_json(arguments_json)
        except ValidationError:
            raise AgentToolFailure(AgentToolErrorCode.INVALID_ARGUMENTS) from None
        try:
            async with asyncio.timeout(definition.timeout_seconds):
                raw_result = await definition.handler(validated_arguments)
        except TimeoutError:
            raise AgentToolFailure(AgentToolErrorCode.TIMEOUT) from None
        except asyncio.CancelledError:
            raise
        except NotFoundError:
            raise AgentToolFailure(AgentToolErrorCode.NOT_FOUND) from None
        except AgentToolFailure:
            raise
        except AppError:
            raise AgentToolFailure(AgentToolErrorCode.UNAVAILABLE) from None
        except Exception:
            raise AgentToolFailure(AgentToolErrorCode.UNAVAILABLE) from None
        try:
            result = definition.result_model.model_validate(raw_result, from_attributes=True)
        except ValidationError:
            raise AgentToolFailure(AgentToolErrorCode.UNAVAILABLE) from None
        if len(result.model_dump_json().encode("utf-8")) > definition.max_result_bytes:
            raise AgentToolFailure(AgentToolErrorCode.OUTPUT_TOO_LARGE)
        return result

    def summarize_arguments(
        self,
        name: str,
        arguments: Mapping[str, object] | str,
    ) -> tuple[tuple[str, SafeTraceValue], ...]:
        definition = self.get(name)
        arguments_json = _arguments_json(arguments, definition.max_argument_bytes)
        try:
            parsed = definition.argument_model.model_validate_json(arguments_json)
        except ValidationError:
            return (("argument_bytes", len(arguments_json.encode("utf-8"))),)
        if isinstance(parsed, SearchEvidenceArguments):
            values: list[tuple[str, SafeTraceValue]] = [
                ("query_length", len(parsed.query)),
                ("query_hash", _query_hash(parsed.query)),
                ("limit", parsed.limit),
            ]
            if parsed.candidate_id is not None:
                values.append(("candidate_id", str(parsed.candidate_id)))
            return tuple(values)
        if isinstance(parsed, GetEventArguments):
            return (("event_id", str(parsed.event_id)),)
        if isinstance(parsed, RetrieveBrandContextArguments):
            return (
                ("query_length", len(parsed.query)),
                ("query_hash", _query_hash(parsed.query)),
                ("valid_on", parsed.valid_on.isoformat()),
                ("audience", parsed.audience),
                ("document_kinds", tuple(kind.value for kind in parsed.document_kinds)),
                ("limit", parsed.limit),
            )
        if isinstance(parsed, ValidateCopyArguments):
            return (
                ("copy_run_id", str(parsed.copy_run_id)),
                ("draft_bytes", len(parsed.draft.model_dump_json().encode("utf-8"))),
                ("claim_count", len(parsed.draft.claims)),
                ("brand_chunk_ids", tuple(str(item) for item in parsed.brand_chunk_ids)),
            )
        return (("argument_bytes", len(arguments_json.encode("utf-8"))),)


def build_agent_tool_registry(reader: AgentKnowledgeReader) -> TypedToolRegistry:
    async def get_event_handler(raw: BaseModel) -> BaseModel:
        arguments = cast(GetEventArguments, raw)
        event = await reader.get_event(arguments.event_id)
        members: list[EventMemberToolItem] = []
        remaining_sources = 8
        for member in event.members:
            if len(members) >= 8:
                break
            if not _is_safe_https_url(member.url):
                continue
            source_count = min(len(member.source_ids), remaining_sources)
            members.append(
                EventMemberToolItem(
                    candidate_id=member.candidate_id,
                    title=_bounded_text(member.title, 200),
                    url=member.url,
                    published_at=member.published_at,
                    source_ids=member.source_ids[:source_count],
                    source_names=tuple(
                        _bounded_text(name, 120) for name in member.source_names[:source_count]
                    ),
                )
            )
            remaining_sources -= source_count
        return GetEventResult(
            event_id=event.event_id,
            current_version_id=event.current_version_id,
            representative_title=_bounded_text(event.representative_title, 200),
            summary=(
                _bounded_text(event.summary, 1_000)
                if event.summary and event.summary.strip()
                else None
            ),
            source_diversity=event.source_diversity,
            categories=tuple(_bounded_text(item, 80) for item in event.categories[:8]),
            members=tuple(members),
        )

    async def retrieve_brand_context_handler(raw: BaseModel) -> BaseModel:
        arguments = cast(RetrieveBrandContextArguments, raw)
        hits = await reader.retrieve_brand_context(
            query=arguments.query,
            audience=BrandAudience.PARENTS,
            document_kinds=arguments.document_kinds,
            valid_on=arguments.valid_on,
            limit=arguments.limit,
        )
        return RetrieveBrandContextResult(
            items=tuple(
                BrandContextToolItem(
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    version_id=hit.version_id,
                    document_title=_bounded_text(hit.document_title, 200),
                    document_kind=hit.document_kind,
                    excerpt=_bounded_text(hit.text, 500),
                    tone_tags=tuple(_bounded_text(item, 80) for item in hit.tone_tags[:12]),
                    safety_tags=tuple(_bounded_text(item, 80) for item in hit.safety_tags[:12]),
                    evidence_eligible=False,
                )
                for hit in hits[: arguments.limit]
            )
        )

    async def search_evidence_handler(raw: BaseModel) -> BaseModel:
        arguments = cast(SearchEvidenceArguments, raw)
        records = await reader.search_evidence(
            query=arguments.query,
            limit=arguments.limit,
            candidate_id=arguments.candidate_id,
        )
        return SearchEvidenceResult(
            items=tuple(
                EvidenceToolItem(
                    evidence_id=record.evidence.evidence_id,
                    event_id=record.event_id,
                    event_version_id=record.event_version_id,
                    candidate_id=record.evidence.candidate_id,
                    source_id=record.source_id,
                    source_name=_bounded_text(record.evidence.source_name, 120),
                    source_tier=cast(Literal["A", "B"], record.evidence.source_tier),
                    title=_bounded_text(record.event_title, 200),
                    url=record.evidence.source_url,
                    published_at=record.evidence.published_at,
                    quote=_bounded_text(record.evidence.exact_quote, 500),
                    evidence_eligible=True,
                )
                for record in records[: arguments.limit]
                if _is_safe_https_url(record.evidence.source_url)
            )
        )

    async def validate_copy_handler(raw: BaseModel) -> BaseModel:
        arguments = cast(ValidateCopyArguments, raw)
        context = await reader.load_copy_validation_context(
            copy_run_id=arguments.copy_run_id,
            brand_chunk_ids=arguments.brand_chunk_ids,
        )
        issues = validate_material_draft(
            arguments.draft,
            topic=context.topic,
            brand_context=context.brand_context,
            rule_version=context.rule_version,
        )
        bounded_issues = issues[:32]
        return ValidateCopyResult(
            copy_run_id=context.copy_run_id,
            accepted=not any(issue.severity == "error" for issue in issues),
            issues=tuple(
                CopyValidationIssue(
                    code=issue.code,
                    severity=issue.severity,
                    field=issue.field,
                    claim_id=issue.claim_id,
                )
                for issue in bounded_issues
            ),
            evidence_ids=tuple(item.evidence_id for item in context.topic.evidence),
            brand_chunk_ids=tuple(item.chunk_id for item in context.brand_context),
            rule_version=context.rule_version,
        )

    return TypedToolRegistry(
        (
            ToolDefinition(
                name="get_event",
                description=(
                    "Read one governed event's bounded current summary and source overview "
                    "by its exact event UUID. This read-only tool does not provide factual "
                    "citations."
                ),
                argument_model=GetEventArguments,
                result_model=GetEventResult,
                handler=get_event_handler,
            ),
            ToolDefinition(
                name="retrieve_brand_context",
                description=(
                    "Retrieve bounded internal brand-expression context for the parents audience. "
                    "Every returned chunk is explicitly ineligible as factual evidence."
                ),
                argument_model=RetrieveBrandContextArguments,
                result_model=RetrieveBrandContextResult,
                handler=retrieve_brand_context_handler,
            ),
            ToolDefinition(
                name="search_evidence",
                description=(
                    "Search accepted, validated Tier A/B evidence attached to governed current "
                    "event versions. Returns bounded HTTPS citations and never fetches arbitrary "
                    "URLs."
                ),
                argument_model=SearchEvidenceArguments,
                result_model=SearchEvidenceResult,
                handler=search_evidence_handler,
            ),
            ToolDefinition(
                name="validate_copy",
                description=(
                    "Run the existing deterministic copy and evidence validator against one "
                    "bounded draft and an immutable copy-run context. It never repairs, writes, "
                    "or enqueues."
                ),
                argument_model=ValidateCopyArguments,
                result_model=ValidateCopyResult,
                handler=validate_copy_handler,
            ),
        )
    )


def _arguments_json(arguments: Mapping[str, object] | str, max_bytes: int) -> str:
    try:
        payload = (
            arguments
            if isinstance(arguments, str)
            else json.dumps(arguments, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        )
    except (TypeError, ValueError):
        raise AgentToolFailure(AgentToolErrorCode.INVALID_ARGUMENTS) from None
    if not payload or len(payload.encode("utf-8")) > max_bytes:
        raise AgentToolFailure(AgentToolErrorCode.INVALID_ARGUMENTS)
    return payload


def _query_hash(query: str) -> str:
    return sha256(query.encode("utf-8")).hexdigest()[:_QUERY_HASH_PREFIX]


def _bounded_text(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("tool text projection must be non-blank")
    return normalized[:limit]


def _is_safe_https_url(value: str) -> bool:
    return is_public_https_url(value)
