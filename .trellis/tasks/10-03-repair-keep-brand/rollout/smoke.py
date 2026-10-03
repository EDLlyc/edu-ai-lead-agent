"""Offline smoke test for release 6a4d660 (run with --network none)."""

import asyncio
import hashlib
import importlib
from pathlib import Path

root = Path(importlib.import_module("app").__file__).resolve().parents[1]
for line in (root / "release-6a4d660-files.txt").read_text().splitlines():
    if line.startswith("#") or not line.strip():
        continue
    path, _base, new = (part.strip() for part in line.split("|"))
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == new, f"{path} is not reviewed"
for module in (
    "app.api_main",
    "app.content_worker_main",
    "app.content_scheduler_main",
    "app.wecom_dispatcher_main",
    "app.wecom_news_infographic_main",
    "app.copy_repair_shadow_main",
):
    importlib.import_module(module)

from app.application.services.copy_generation import CopyGenerationExecutor  # noqa: E402
from app.application.services.copy_repair_agent import REPAIR_AGENT_VERSION  # noqa: E402
from app.application.services.copy_repair_tools import REPAIR_TOOL_RULES  # noqa: E402
from app.core.config import Settings  # noqa: E402

assert REPAIR_AGENT_VERSION == "copy-repair-agent-v4-keep-brand"
assert "不能删光" in REPAIR_TOOL_RULES
assert "brand_claim_missing" in Path(importlib.import_module("app.application.services.copy_generation").__file__).read_text()
assert Settings(_env_file=None).copy_repair_mode == "agent_first"
assert CopyGenerationExecutor is not None
print(f"smoke ok: release 6a4d660 ({REPAIR_AGENT_VERSION})")
