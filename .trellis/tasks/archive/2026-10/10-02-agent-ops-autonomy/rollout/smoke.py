"""Offline smoke test for the watchdog diagnosis overlay (run with --network none)."""

import asyncio
import hashlib
import importlib
import json
from pathlib import Path

from app.application.services.copy_repair_agent import ChatToolCall, ChatTurn
from app.application.services.ops_diagnosis import DIAGNOSIS_AGENT_VERSION, DiagnosisAgent
from app.delivery_watchdog_main import SlotCheck, alert_text

root = Path(importlib.import_module("app").__file__).resolve().parents[1]
for line in (root / "release-92c80df-watchdog-files.txt").read_text().splitlines():
    if line.startswith("#") or not line.strip():
        continue
    path, _base, new = (part.strip() for part in line.split("|"))
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == new, f"{path} is not reviewed"
for module in ("app.content_worker_main", "app.copy_repair_shadow_main", "app.api_main"):
    importlib.import_module(module)


class Reader:
    async def list_deliveries(self, business_date):  # noqa: ANN001, ANN201
        from app.application.services.ops_tools import DeliveriesResult

        return DeliveriesResult(deliveries=())


class Model:
    def __init__(self):  # noqa: ANN204
        self.turns = [
            ChatTurn(None, (ChatToolCall("1", "list_deliveries", '{"business_date": "2026-10-02"}'),), 10, 1),
            ChatTurn(
                None,
                (
                    ChatToolCall(
                        "2",
                        "report_diagnosis",
                        json.dumps({"stage": "delivery", "cause": "没有发送任务记录。", "action": "manual_review"}),
                    ),
                ),
                10,
                1,
            ),
        ]

    async def complete(self, messages, tools):  # noqa: ANN001, ANN201
        return self.turns.pop(0)


from datetime import date  # noqa: E402

outcome = asyncio.run(DiagnosisAgent(Model(), Reader()).diagnose(date(2026, 10, 2), "noon", ("x",)))
assert outcome.stopped == "reported", outcome
text = alert_text(SlotCheck(date(2026, 10, 2), "noon", problems=["x"]), outcome)
assert "【自动诊断】" in text
print(f"smoke ok: watchdog diagnosis {DIAGNOSIS_AGENT_VERSION}")
