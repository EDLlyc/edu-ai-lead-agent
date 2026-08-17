from __future__ import annotations

import asyncio
import json
from typing import cast
from uuid import uuid4

import pytest
from app.agent_workbench_runtime import build_fixture_tool_registry
from app.application.services.agent_tools import (
    AgentToolFailure,
    ToolDefinition,
    TypedToolRegistry,
)
from app.domain.agent_workbench import AgentToolErrorCode
from app.infrastructure.agent_workbench_fixture import (
    FIXTURE_BRAND_CHUNK_ID,
    FIXTURE_COPY_RUN_ID,
    build_fixture_material_draft,
)
from app.schemas.agent_workbench import (
    EventMemberToolItem,
    EvidenceToolItem,
    GetEventResult,
    SearchEvidenceArguments,
    SearchEvidenceResult,
    ValidateCopyResult,
)
from app.schemas.copy_generation import CopyIssue
from pydantic import BaseModel, ValidationError


def test_registry_is_canonical_read_only_and_stable() -> None:
    first = build_fixture_tool_registry()
    second = build_fixture_tool_registry()

    assert tuple(definition.name for definition in first) == (
        "get_event",
        "retrieve_brand_context",
        "search_evidence",
        "validate_copy",
    )
    assert first.schema_hash == second.schema_hash
    assert len(first.schema_hash) == 64
    assert all(definition.read_only and not definition.open_world for definition in first)
    assert all(definition.input_schema() for definition in first)
    assert all(definition.output_schema() for definition in first)


@pytest.mark.asyncio
async def test_four_fixture_tools_preserve_evidence_brand_and_validator_boundaries() -> None:
    registry = build_fixture_tool_registry()

    evidence = cast(
        SearchEvidenceResult,
        await registry.invoke(
            "search_evidence",
            {"query": "人工智能教育安全要求", "limit": 3, "candidate_id": None},
        ),
    )
    assert len(evidence.items) == 1
    assert evidence.items[0].evidence_eligible is True
    assert evidence.items[0].source_tier == "A"
    assert evidence.items[0].url.startswith("https://")

    event = await registry.invoke(
        "get_event",
        {"event_id": str(evidence.items[0].event_id)},
    )
    assert event.model_dump()["members"]

    brand = await registry.invoke(
        "retrieve_brand_context",
        {
            "query": "家长沟通语气",
            "valid_on": "2026-08-16",
            "audience": "parents",
            "document_kinds": [],
            "limit": 3,
        },
    )
    brand_item = cast(list[dict[str, object]], brand.model_dump(mode="json")["items"])[0]
    assert brand_item["evidence_eligible"] is False
    assert "url" not in brand_item

    validation = cast(
        ValidateCopyResult,
        await registry.invoke(
            "validate_copy",
            {
                "copy_run_id": str(FIXTURE_COPY_RUN_ID),
                "draft": build_fixture_material_draft().model_dump(mode="json"),
                "brand_chunk_ids": [str(FIXTURE_BRAND_CHUNK_ID)],
            },
        ),
    )
    assert validation.accepted is True
    assert validation.copy_run_id == FIXTURE_COPY_RUN_ID
    assert validation.brand_chunk_ids == (FIXTURE_BRAND_CHUNK_ID,)


@pytest.mark.asyncio
async def test_validate_copy_verdict_considers_errors_beyond_bounded_issue_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings = tuple(
        CopyIssue(code=f"warning_{index}", message="bounded warning", severity="warning")
        for index in range(32)
    )
    hidden_error = CopyIssue(code="hard_error", message="must fail closed", severity="error")

    def validation_with_more_than_thirty_two_issues(
        *_args: object, **_kwargs: object
    ) -> tuple[CopyIssue, ...]:
        return (*warnings, hidden_error)

    monkeypatch.setattr(
        "app.application.services.agent_tools.validate_material_draft",
        validation_with_more_than_thirty_two_issues,
    )

    validation = cast(
        ValidateCopyResult,
        await build_fixture_tool_registry().invoke(
            "validate_copy",
            {
                "copy_run_id": str(FIXTURE_COPY_RUN_ID),
                "draft": build_fixture_material_draft().model_dump(mode="json"),
                "brand_chunk_ids": [str(FIXTURE_BRAND_CHUNK_ID)],
            },
        ),
    )

    assert validation.accepted is False
    assert len(validation.issues) == 32
    assert all(issue.severity == "warning" for issue in validation.issues)


@pytest.mark.asyncio
async def test_registry_rejects_unknown_invalid_timeout_and_oversized_result() -> None:
    registry = build_fixture_tool_registry()
    with pytest.raises(AgentToolFailure) as unknown:
        await registry.invoke("delete_everything", {})
    assert unknown.value.code is AgentToolErrorCode.UNKNOWN

    with pytest.raises(AgentToolFailure) as invalid:
        await registry.invoke("search_evidence", {"query": "ok", "limit": "5"})
    assert invalid.value.code is AgentToolErrorCode.INVALID_ARGUMENTS

    async def slow_handler(_arguments: BaseModel) -> BaseModel:
        await asyncio.sleep(0.02)
        return SearchEvidenceResult()

    timeout_registry = TypedToolRegistry(
        (
            ToolDefinition(
                name="search_evidence",
                description="Read-only test search.",
                argument_model=SearchEvidenceArguments,
                result_model=SearchEvidenceResult,
                handler=slow_handler,
                timeout_seconds=0.001,
            ),
        )
    )
    with pytest.raises(AgentToolFailure) as timed_out:
        await timeout_registry.invoke("search_evidence", {"query": "ok", "limit": 1})
    assert timed_out.value.code is AgentToolErrorCode.TIMEOUT

    async def large_handler(_arguments: BaseModel) -> BaseModel:
        return SearchEvidenceResult()

    tiny_registry = TypedToolRegistry(
        (
            ToolDefinition(
                name="search_evidence",
                description="Read-only test search.",
                argument_model=SearchEvidenceArguments,
                result_model=SearchEvidenceResult,
                handler=large_handler,
                max_result_bytes=1,
            ),
        )
    )
    with pytest.raises(AgentToolFailure) as oversized:
        await tiny_registry.invoke("search_evidence", {"query": "ok", "limit": 1})
    assert oversized.value.code is AgentToolErrorCode.OUTPUT_TOO_LARGE

    async def failing_handler(_arguments: BaseModel) -> BaseModel:
        raise KeyError("private implementation detail")

    failing_registry = TypedToolRegistry(
        (
            ToolDefinition(
                name="search_evidence",
                description="Read-only test search.",
                argument_model=SearchEvidenceArguments,
                result_model=SearchEvidenceResult,
                handler=failing_handler,
            ),
        )
    )
    with pytest.raises(AgentToolFailure) as unavailable:
        await failing_registry.invoke("search_evidence", {"query": "ok", "limit": 1})
    assert unavailable.value.code is AgentToolErrorCode.UNAVAILABLE


def test_registry_rejects_duplicate_or_mutating_definitions() -> None:
    async def handler(_arguments: BaseModel) -> BaseModel:
        return SearchEvidenceResult()

    definition = ToolDefinition(
        name="search_evidence",
        description="Read-only test search.",
        argument_model=SearchEvidenceArguments,
        result_model=SearchEvidenceResult,
        handler=handler,
    )
    with pytest.raises(ValueError, match="duplicate"):
        TypedToolRegistry((definition, definition))
    with pytest.raises(ValueError, match="read-only"):
        ToolDefinition(
            name="write_database",
            description="Forbidden mutating test tool.",
            argument_model=SearchEvidenceArguments,
            result_model=SearchEvidenceResult,
            handler=handler,
            read_only=False,
        )


def test_event_result_enforces_one_global_eight_source_budget() -> None:
    members = tuple(
        EventMemberToolItem(
            candidate_id=uuid4(),
            title=f"member {index}",
            url=f"https://example.com/member-{index}",
            source_ids=tuple(uuid4() for _ in range(5)),
            source_names=tuple(f"source {source}" for source in range(5)),
        )
        for index in range(2)
    )

    with pytest.raises(ValidationError, match="more than eight sources"):
        GetEventResult(
            event_id=uuid4(),
            current_version_id=uuid4(),
            representative_title="event",
            source_diversity=10,
            members=members,
        )


@pytest.mark.parametrize(
    "url",
    (
        "http://example.com/item",
        "https://localhost/item",
        "https://127.0.0.1/item",
        "https://10.0.0.1/item",
        "https://service.internal/item",
        "https://service.test/item",
        "https://service.example/item",
        "https://service.invalid/item",
        "https://service.onion/item",
        "https://home.arpa/item",
    ),
)
def test_evidence_schema_rejects_non_public_urls(url: str) -> None:
    payload = {
        "evidence_id": "10000000-0000-4000-8000-000000000003",
        "event_id": "10000000-0000-4000-8000-000000000001",
        "event_version_id": "10000000-0000-4000-8000-000000000002",
        "candidate_id": "10000000-0000-4000-8000-000000000004",
        "source_id": "10000000-0000-4000-8000-000000000008",
        "source_name": "source",
        "source_tier": "A",
        "title": "title",
        "url": url,
        "quote": "quote",
        "evidence_eligible": True,
    }
    with pytest.raises(ValidationError) as rejected:
        EvidenceToolItem.model_validate_json(json.dumps(payload))

    assert {error["loc"] for error in rejected.value.errors()} == {("url",)}
