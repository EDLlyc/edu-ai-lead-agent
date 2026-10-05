"""Offline smoke test for the ops cron image 51c91df (run with --network none)."""

import hashlib
import importlib
from pathlib import Path

root = Path(importlib.import_module("app").__file__).resolve().parents[1]
for line in (root / "release-51c91df-ops-files.txt").read_text().splitlines():
    if line.startswith("#") or not line.strip():
        continue
    path, _base, new = (part.strip() for part in line.split("|"))
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == new, f"{path} is not reviewed"
for module in (
    "app.content_worker_main",
    "app.quality_report_main",
    "app.delivery_watchdog_main",
    "app.ops_actions_main",
    "app.copy_repair_shadow_main",
    "app.weekly_report_main",
):
    importlib.import_module(module)
from app.copy_repair_shadow_main import SHADOW_SCHEMA  # noqa: E402
from app.application.services.copy_repair_agent import REPAIR_AGENT_VERSION  # noqa: E402

assert SHADOW_SCHEMA == "copy-repair-shadow-v2"
assert REPAIR_AGENT_VERSION == "copy-repair-agent-v4-keep-brand"
print("smoke ok: ops cron image 51c91df")
