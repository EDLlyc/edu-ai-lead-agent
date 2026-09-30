from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from app.application.services.ops_tools import (
    OPS_TOOL_RULES,
    CopyRunDetail,
    CopyRunItem,
    CopyRunsResult,
    DayTraceResult,
    DeliveriesResult,
    SlotRunsResult,
    build_ops_tool_registry,
)
from app.core.errors import NotFoundError
from app.ops_mcp_main import build_ops_mcp_server
from mcp import Client

RUN_ID = uuid4()


class _FakeReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def list_slot_runs(self, business_date: date) -> SlotRunsResult:
        self.calls.append(("list_slot_runs", business_date))
        return SlotRunsResult(runs=())

    async def list_copy_runs(self, business_date: date, limit: int) -> CopyRunsResult:
        self.calls.append(("list_copy_runs", (business_date, limit)))
        return CopyRunsResult(
            runs=(
                CopyRunItem(
                    run_id=RUN_ID,
                    content_slot="noon",
                    ordinal=1,
                    title="示例新闻",
                    status="accepted",
                    decision_kind="selected",
                    repair_count=0,
                    error_code=None,
                    generator_prompt_version="moments-generator-v28-shared-quotes",
                    auditor_prompt_version="moments-auditor-v21-lean-context",
                    created_at=datetime(2026, 9, 30, 3, tzinfo=UTC),
                    completed_at=None,
                ),
            )
        )

    async def get_copy_run(self, run_id: UUID) -> CopyRunDetail:
        raise NotFoundError("copy generation run")

    async def list_deliveries(self, business_date: date) -> DeliveriesResult:
        return DeliveriesResult(deliveries=())

    async def get_day_trace(self, business_date: date) -> DayTraceResult:
        return DayTraceResult(business_date=business_date, posts=(), usage=())


def test_ops_registry_is_read_only_and_describes_every_field() -> None:
    registry = build_ops_tool_registry(_FakeReader())
    schema = registry.canonical_schema()

    tools = schema["tools"]  # type: ignore[index]
    assert [tool["name"] for tool in tools] == [
        "get_copy_run",
        "get_day_trace",
        "list_copy_runs",
        "list_deliveries",
        "list_slot_runs",
    ]
    for tool in tools:
        assert tool["annotations"] == {"read_only": True, "open_world": False}
        for field in tool["input_schema"]["properties"].values():
            assert field.get("description"), tool["name"]
        assert "recipient" not in json.dumps(tool["output_schema"])


@pytest.mark.asyncio
async def test_ops_mcp_routes_calls_and_reports_missing_runs_as_not_retryable() -> None:
    reader = _FakeReader()
    server = build_ops_mcp_server(reader, call_logger=None)

    async with Client(server) as client:
        instructions = client.instructions
        listed = await client.call_tool("list_copy_runs", {"business_date": "2026-09-30"})
        missing = await client.call_tool("get_copy_run", {"run_id": str(RUN_ID)})
        bad_date = await client.call_tool("list_slot_runs", {"business_date": "yesterday"})

    assert instructions is not None and OPS_TOOL_RULES in instructions
    assert listed.structured_content is not None
    assert listed.structured_content["runs"][0]["content_slot"] == "noon"
    assert reader.calls == [("list_copy_runs", (date(2026, 9, 30), 20))]
    assert missing.is_error is True
    assert json.loads(missing.content[0].text)["error_code"] == "agent_tool_not_found"
    assert json.loads(missing.content[0].text)["retryable"] is False
    assert bad_date.structured_content is not None
    assert bad_date.structured_content["fields"] == ["business_date:date_from_datetime_parsing"]


def test_ops_server_requires_a_dedicated_asyncpg_url() -> None:
    from app.infrastructure.db.ops_reader import ops_database_url

    with pytest.raises(RuntimeError, match="OPS_DATABASE_URL"):
        ops_database_url({"DATABASE_URL": "postgresql+asyncpg://edu_ai@127.0.0.1/edu_ai"})
    with pytest.raises(RuntimeError, match="asyncpg"):
        ops_database_url({"OPS_DATABASE_URL": "postgresql://ro@127.0.0.1/edu_ai"})
