"""Offline smoke test for release f4ff3a4 (run with --network none inside the overlay image)."""

import hashlib
import importlib
from datetime import time
from pathlib import Path

for module in (
    "app.api_main",
    "app.worker_main",
    "app.content_scheduler_main",
    "app.content_worker_main",
    "app.wecom_dispatcher_main",
    "app.wecom_news_infographic_main",
    "app.quality_report_main",
):
    importlib.import_module(module)

from app.api.v1.routes import content_slots
from app.core.config import Settings
from app.infrastructure.db import (
    content_slot_human_picks,
    topic_selection,
)

# Every overlaid file is the reviewed one.
root = Path(importlib.import_module("app").__file__).resolve().parents[1]
manifest = root / "release-f4ff3a4-files.txt"
lines = (
    manifest if manifest.is_file() else Path(__file__).with_name("files.txt")
).read_text()
for line in lines.splitlines():
    if line.startswith("#") or not line.strip():
        continue
    path, _base, new = (part.strip() for part in line.split("|"))
    digest = hashlib.sha256((root / path).read_bytes()).hexdigest()
    assert digest == new, f"{path} is not the reviewed file"

# Selection: freshest events, newest first, the cap kept.
assert Settings(_env_file=None).content_freshness_window_days == 10
assert topic_selection.CANDIDATE_POOL_LIMIT == 500
assert topic_selection.CANDIDATE_POOL_FRESHNESS_MARGIN_DAYS == 1.0

# Human pick: held until 22:30, review routes present, auto-sender gated.
assert content_slot_human_picks.HUMAN_PICK_PUSH_DEADLINE_LOCAL_TIME == time(22, 30)
paths = {getattr(route, "path", "") for route in content_slots.router.routes}
assert "/content-slot-human-picks/{run_id}/copy" in paths
assert "/content-slot-human-picks/{run_id}/push" in paths
delivery = Path(
    importlib.import_module("app.application.services.wecom_delivery").__file__
)
assert b"human pick is held for the operator's review" in delivery.read_bytes()
print("smoke ok: release f4ff3a4 (fresh candidate pool + held human picks)")
