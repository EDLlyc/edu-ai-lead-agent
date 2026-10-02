"""Offline smoke test for release 11ad19c (run with --network none inside the overlay image).

Mount the brand materials to check at /app/private/brand-materials (read-only): every asset in the
manifest must match its file, and every approved action image must fit the reference budget.
"""

import hashlib
import importlib
from collections import Counter
from pathlib import Path

for module in (
    "app.api_main",
    "app.worker_main",
    "app.content_scheduler_main",
    "app.content_worker_main",
    "app.wecom_dispatcher_main",
    "app.wecom_news_infographic_main",
    "app.quality_report_main",
    "evals.visual_replay.plan_sim",
):
    importlib.import_module(module)

from app.application.services import material_package
from app.domain import visual_diversity
from app.domain.image_generation import IMAGE_REFERENCE_BUDGET_BYTES
from app.domain.visual_assets import VisualAssetCatalogLoader, VisualAssetRole, action_pool_capacity
from app.infrastructure.brand.visual_catalog import load_visual_catalog

# Every overlaid file is the reviewed one.
root = Path(importlib.import_module("app").__file__).resolve().parents[1]
manifest = root / "release-11ad19c-files.txt"
lines = (manifest if manifest.is_file() else Path(__file__).with_name("files.txt")).read_text()
for line in lines.splitlines():
    if line.startswith("#") or not line.strip():
        continue
    path, _base, new = (part.strip() for part in line.split("|"))
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == new, f"{path} is not the reviewed file"

# Planner: pool-aware penalties, wired only for selector v3 with prop labels.
assert visual_diversity.POOL_EXHAUSTED_PENALTY == 1_500
assert visual_diversity.POOL_LOW_PENALTY == 300
assert "action_capacity=action_capacity" in Path(material_package.__file__).read_text()

# Brand materials: every file matches the manifest; action images fit the budget.
loaded = load_visual_catalog(root / "private/brand-materials/visual-assets.manifest.json")
reader = VisualAssetCatalogLoader(loaded.materials_root)
for asset in loaded.catalog.assets:
    reader.read_asset(asset)
actions = [
    asset
    for asset in loaded.catalog.assets
    if asset.approved and VisualAssetRole.ACTION_REFERENCE in asset.roles
]
too_large = [asset.filename for asset in actions if asset.byte_size > IMAGE_REFERENCE_BUDGET_BYTES]
assert not too_large, f"action images over the budget: {too_large}"
assert all(asset.props is not None for asset in actions)
capacity = action_pool_capacity(
    loaded.catalog, recent_action_sequence=(), max_reference_bytes=IMAGE_REFERENCE_BUDGET_BYTES
)
by_cast = Counter()
for (_subject, cast), count in capacity.items():
    by_cast[cast.value] = max(by_cast[cast.value], count)
print(
    f"smoke ok: release 11ad19c; {len(loaded.catalog.assets)} assets verified, "
    f"{len(actions)} action images all within budget (largest {max(a.byte_size for a in actions)}), "
    f"best fresh pool per cast {dict(by_cast)}"
)
