"""Offline smoke test for the watchdog + approved-actions overlay (run with --network none)."""

import asyncio
import hashlib
import importlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from app.application.services.ops_actions import ActionLog, FailedDelivery, approve, propose_resends
from app.ops_actions_main import main as cli

root = Path(importlib.import_module("app").__file__).resolve().parents[1]
for line in (root / "release-944f37a-actions-files.txt").read_text().splitlines():
    if line.startswith("#") or not line.strip():
        continue
    path, _base, new = (part.strip() for part in line.split("|"))
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == new, f"{path} is not reviewed"
for module in ("app.delivery_watchdog_main", "app.content_worker_main", "app.quality_report_main"):
    importlib.import_module(module)

with TemporaryDirectory() as tmp:
    log = ActionLog(Path(tmp) / "a.jsonl")
    now = datetime.now(UTC)
    (proposal,) = propose_resends(
        log,
        business_date=date(2026, 10, 2),
        slot="noon",
        deliveries=(FailedDelivery("noon", 2, "failed", "wecom_rate_limited"),),
        reason="smoke",
        proposed_by="smoke",
        now=now,
        window_end=lambda _t: now + timedelta(hours=1),
    )

    async def never(_p):  # noqa: ANN001, ANN202
        raise AssertionError("must not execute while disabled")

    assert asyncio.run(approve(log, proposal.id, by="smoke", now=now, enabled=False, execute=never)) == "approved"
    assert cli(["--log", str(Path(tmp) / "a.jsonl"), "list", "--all"]) == 0
print("smoke ok: watchdog diagnosis + approved actions (propose-only)")
