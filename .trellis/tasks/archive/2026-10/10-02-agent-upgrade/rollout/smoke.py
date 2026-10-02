"""Offline smoke test for release de22d32 (run with --network none inside the overlay image)."""

import hashlib
import importlib
import inspect
from pathlib import Path

for module in (
    "app.api_main",
    "app.worker_main",
    "app.content_scheduler_main",
    "app.content_worker_main",
    "app.wecom_dispatcher_main",
    "app.wecom_news_infographic_main",
    "app.quality_report_main",
    "app.copy_repair_shadow_main",
):
    importlib.import_module(module)

from app.application.services.copy_generation import CopyGenerationExecutor
from app.application.services.copy_repair_agent import REPAIR_AGENT_VERSION
from app.core.config import Settings
from app.infrastructure.db.copy_generation import PostgresCopyGenerationRepository

root = Path(importlib.import_module("app").__file__).resolve().parents[1]
manifest = root / "release-de22d32-files.txt"
lines = (manifest if manifest.is_file() else Path(__file__).with_name("files.txt")).read_text()
for line in lines.splitlines():
    if line.startswith("#") or not line.strip():
        continue
    path, _base, new = (part.strip() for part in line.split("|"))
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == new, f"{path} is not reviewed"

settings = Settings(_env_file=None)
assert settings.copy_repair_mode == "agent_first"
assert settings.copy_repair_agent_timeout_seconds == 150.0
assert settings.copy_generator_prompt_version == "moments-generator-v28-shared-quotes"
assert settings.copy_auditor_prompt_version == "moments-auditor-v22-enumerated-codes"
assert "repair_model" in inspect.signature(CopyGenerationExecutor).parameters
assert hasattr(PostgresCopyGenerationRepository, "record_repair_agent_attempt")
worker = Path(importlib.import_module("app.content_worker_main").__file__).read_text()
assert "repair_model=repair_model" in worker and "ZhipuRepairChatModel(" in worker
print(f"smoke ok: release de22d32 (agent-first repair, {REPAIR_AGENT_VERSION})")
