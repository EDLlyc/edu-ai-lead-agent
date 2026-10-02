# ruff: noqa: RUF001

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
from app.application.services.copy_repair_agent import ChatTurn
from app.application.services.ops_assistant import OpsAssistant
from app.infrastructure.db.ops_assistant_checkpointer import (
    ops_assistant_checkpoint_url,
    ops_assistant_checkpointer,
)
from sqlalchemy.engine import make_url
from tests.unit.test_copy_repair_tools import EVIDENCE_A, _call, _workspace
from tests.unit.test_ops_tools import RUN_ID, _FakeReader

from .conftest import IntegrationContext


class _Scripted:
    def __init__(self, turns: list[ChatTurn]) -> None:
        self.turns = turns

    async def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        return self.turns.pop(0)


async def _load(run_id: UUID):  # type: ignore[no-untyped-def]
    assert run_id == RUN_ID
    return _workspace(claim_text="该模型在五项测试中表现领先。")


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_a_pending_approval_survives_a_process_restart_in_postgres(
    integration_context: IntegrationContext,
) -> None:
    psycopg_url = (
        make_url(integration_context.settings.database_url.get_secret_value())
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )
    url = ops_assistant_checkpoint_url({"OPS_ASSISTANT_CHECKPOINT_URL": psycopg_url})
    thread_id = "ops-assistant:integration"
    replace = {
        "claim_id": "fact-1",
        "text": "该模型在三项测试中表现领先。",
        "evidence_ids": [str(EVIDENCE_A)],
    }

    async with ops_assistant_checkpointer(url) as checkpointer:
        first = OpsAssistant(
            _Scripted(
                [
                    ChatTurn(None, (_call("1", "open_draft", {"run_id": str(RUN_ID)}),), 10, 1),
                    ChatTurn(None, (_call("2", "replace_claim", replace),), 10, 1),
                ]
            ),
            _FakeReader(),
            _load,
            today=date(2026, 10, 2),
            checkpointer=checkpointer,
            thread_id=thread_id,
        )
        paused = await first.send("把错误的数字改掉")
    assert paused.kind == "approval"

    # A new connection pool and a new assistant: only the database and the thread id remain.
    async with ops_assistant_checkpointer(url) as checkpointer:
        restarted = OpsAssistant(
            _Scripted([ChatTurn("改好了，请到审核页提交。", (), 10, 1)]),
            _FakeReader(),
            _load,
            today=date(2026, 10, 2),
            checkpointer=checkpointer,
            thread_id=thread_id,
        )
        pending = await restarted.pending()
        done = await restarted.decide(approve=True)
        approvals = await restarted.approvals()

    assert pending is not None and pending.preview["after"] == "该模型在三项测试中表现领先。"
    assert done.kind == "answer"
    assert done.draft is not None and done.draft["edits"] == ["replace_claim:fact-1"]
    assert [(a["tool"], a["approved"]) for a in approvals] == [("replace_claim", True)]


def test_checkpoints_never_go_to_the_read_only_ops_database() -> None:
    environ = {
        "OPS_DATABASE_URL": "postgresql+asyncpg://edu_ai_ops_ro:x@127.0.0.1:15432/edu_ai",
        "OPS_ASSISTANT_CHECKPOINT_URL": "postgresql://edu_ai:x@127.0.0.1:15432/edu_ai",
    }
    with pytest.raises(RuntimeError, match="read-only ops database"):
        ops_assistant_checkpoint_url(environ)
    with pytest.raises(RuntimeError, match="psycopg"):
        ops_assistant_checkpoint_url({"OPS_ASSISTANT_CHECKPOINT_URL": "sqlite:///x.db"})
    local = "postgresql://edu_ai:x@127.0.0.1:5432/edu_ai"
    assert ops_assistant_checkpoint_url({**environ, "OPS_ASSISTANT_CHECKPOINT_URL": local}) == local
    assert ops_assistant_checkpoint_url({}) is None
