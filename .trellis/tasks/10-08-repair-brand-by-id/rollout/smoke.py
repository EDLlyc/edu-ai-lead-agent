"""Offline smoke test for the unified image e9feebd (run with --network none)."""

import hashlib
import importlib
from pathlib import Path

root = Path(importlib.import_module("app").__file__).resolve().parents[1]
for line in (root / "release-e9feebd-files.txt").read_text().splitlines():
    if line.startswith("#") or not line.strip():
        continue
    path, _base, new = (part.strip() for part in line.split("|"))
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == new, f"{path} is not reviewed"
for module in (
    "app.api_main",
    "app.worker_main",
    "app.content_scheduler_main",
    "app.content_worker_main",
    "app.wecom_dispatcher_main",
    "app.wecom_news_infographic_main",
    "app.quality_report_main",
    "app.delivery_watchdog_main",
    "app.ops_actions_main",
    "app.copy_repair_shadow_main",
    "app.weekly_report_main",
):
    importlib.import_module(module)
from app.application.services.copy_repair_agent import REPAIR_AGENT_VERSION  # noqa: E402
from app.application.services.copy_repair_tools import REPAIR_TOOLSET_VERSION, REPAIR_TOOL_RULES  # noqa: E402
from app.core.config import Settings  # noqa: E402

assert REPAIR_AGENT_VERSION == "copy-repair-agent-v5-brand-by-id"
assert REPAIR_TOOLSET_VERSION == "copy-repair-tools-v4-brand-by-id"
assert "use_brand_sentence" in REPAIR_TOOL_RULES
assert Settings(_env_file=None).copy_repair_mode == "agent_first"
print(f"smoke ok: unified image e9feebd ({REPAIR_AGENT_VERSION})")
