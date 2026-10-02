# ruff: noqa: RUF001

from __future__ import annotations

from datetime import date
from uuid import UUID

from app.application.services.copy_repair_agent import ChatTurn
from app.application.services.ops_assistant import OpsAssistant
from app.ops_assistant_main import AssistantRuntime, create_app
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from tests.unit.test_copy_repair_tools import _call, _workspace
from tests.unit.test_ops_tools import RUN_ID, _FakeReader


class _Scripted:
    def __init__(self, turns: list[ChatTurn]) -> None:
        self.turns = turns

    async def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        return self.turns.pop(0)


class _FakeRuntime(AssistantRuntime):
    def __init__(
        self,
        turns: list[ChatTurn],
        *,
        checkpointer: InMemorySaver | None = None,
        thread_id: str | None = None,
    ) -> None:
        super().__init__(thread_id=thread_id)
        self._turns = turns
        self._checkpointer = checkpointer or InMemorySaver()

    async def start(self) -> str:
        self.reset(self._initial_thread)
        return "edu_ai_ops_ro"

    def reset(self, thread_id: str | None = None) -> None:
        async def load(run_id: UUID):  # type: ignore[no-untyped-def]
            return _workspace()

        self.assistant = OpsAssistant(
            _Scripted(self._turns),
            _FakeReader(),
            load,
            today=date(2026, 10, 1),
            checkpointer=self._checkpointer,
            thread_id=thread_id,
        )

    async def stop(self) -> None:
        return None


HOST = {"host": "127.0.0.1:4190"}


def _client(turns: list[ChatTurn]) -> TestClient:
    return TestClient(create_app(_FakeRuntime(turns), port=4190), base_url="http://127.0.0.1:4190")


def test_page_and_api_refuse_other_hosts_and_non_json_posts() -> None:
    with _client([]) as client:
        assert client.get("/", headers=HOST).status_code == 200
        assert client.get("/", headers={"host": "evil.example:80"}).status_code == 403
        rebinding = client.post(
            "/api/message", json={"text": "hi"}, headers={"host": "attacker.test:4190"}
        )
        assert rebinding.status_code == 403
        form = client.post(
            "/api/message", content="text=hi", headers={**HOST, "content-type": "text/plain"}
        )
        assert form.status_code == 415


def test_an_edit_waits_for_the_decision_and_blocks_new_messages_meanwhile() -> None:
    turns = [
        ChatTurn(None, (_call("1", "open_draft", {"run_id": str(RUN_ID)}),), 10, 1),
        ChatTurn(
            None,
            (_call("2", "rewrite_hook", {"text": "机器人在学着观察世界，和孩子聊聊吧🔍"}),),
            10,
            1,
        ),
        ChatTurn("改好了，请到审核页提交。", (), 10, 1),
    ]
    with _client(turns) as client:
        paused = client.post("/api/message", json={"text": "改一下引导语"}, headers=HOST).json()
        blocked = client.post("/api/message", json={"text": "再问一句"}, headers=HOST)
        done = client.post("/api/decision", json={"approve": True}, headers=HOST).json()

    assert paused["kind"] == "approval"
    assert paused["approval"]["tool"] == "rewrite_hook"
    assert paused["draft"]["edits"] == []
    assert blocked.status_code == 409
    assert done["kind"] == "answer"
    assert done["draft"]["edits"] == ["rewrite_hook"]
    assert done["steps"][0]["approval"] == "approved"


def test_a_restarted_page_restores_the_waiting_approval_of_its_thread() -> None:
    checkpointer = InMemorySaver()
    turns = [
        ChatTurn(None, (_call("1", "open_draft", {"run_id": str(RUN_ID)}),), 10, 1),
        ChatTurn(
            None,
            (_call("2", "rewrite_hook", {"text": "机器人在学着观察世界，和孩子聊聊吧🔍"}),),
            10,
            1,
        ),
    ]
    first = _FakeRuntime(turns, checkpointer=checkpointer, thread_id="ops-assistant:page")
    with TestClient(create_app(first, port=4190), base_url="http://127.0.0.1:4190") as client:
        paused = client.post("/api/message", json={"text": "改一下引导语"}, headers=HOST).json()
    assert paused["kind"] == "approval"

    restarted = _FakeRuntime(
        [ChatTurn("改好了。", (), 10, 1)], checkpointer=checkpointer, thread_id="ops-assistant:page"
    )
    with TestClient(create_app(restarted, port=4190), base_url="http://127.0.0.1:4190") as client:
        state = client.get("/api/state", headers=HOST).json()
        done = client.post("/api/decision", json={"approve": True}, headers=HOST).json()
        reset = client.post("/api/reset", json={}, headers=HOST).json()

    assert state["thread_id"] == "ops-assistant:page"
    assert state["pending"]["tool"] == "rewrite_hook"
    assert done["kind"] == "answer" and done["draft"]["edits"] == ["rewrite_hook"]
    assert reset["thread_id"] != "ops-assistant:page"
