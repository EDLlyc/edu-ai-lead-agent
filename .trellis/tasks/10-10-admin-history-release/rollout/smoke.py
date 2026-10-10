"""Provider-free candidate smoke; run in the image with --network none and no env file."""
import hashlib
import importlib
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

for name in (
    "app.api_main", "app.worker_main", "app.content_scheduler_main",
    "app.content_worker_main", "app.wecom_news_infographic_main", "app.wecom_dispatcher_main",
):
    importlib.import_module(name)

from app.api_main import app
from app.application.services.wechat_admin import OPEN_STATUSES
from app.infrastructure.model_api_keys_overlay import loaded_versions

root = Path(importlib.import_module("app").__file__).resolve().parents[1]
manifest = root / "release-admin-history-files.txt"
if not manifest.is_file():
    manifest = Path(__file__).with_name("files.txt")
checked = 0
for line in manifest.read_text().splitlines():
    if not line or line.startswith("#"):
        continue
    name, _, expected = (part.strip() for part in line.split("|"))
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
    checked += 1
assert checked >= 12
assert ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_heads() == [
    "20261010_0061"
]
assert {"outcome_unknown", "succeeded"}.issubset(OPEN_STATUSES)
schema = app.openapi()
base = "/api/v1/admin/wechat/publish-jobs/{job_id}"
assert base + "/recheck" in schema["paths"]
assert base + "/reconcile" in schema["paths"]
assert {"range_start", "range_end", "missing_dates"}.issubset(
    schema["components"]["schemas"]["AdminWeChatStatsResponse"]["required"]
)
assert loaded_versions() is None
jobs = schema["paths"]["/api/v1/admin/wechat/publish-jobs"]["get"]
assert {"offset", "limit", "status", "date_from", "date_to"}.issubset({p["name"] for p in jobs["parameters"]})
assert {"items", "total", "offset", "limit", "business_timezone"}.issubset(schema["components"]["schemas"]["AdminWeChatPublishJobListResponse"]["properties"])
print(f"admin history offline smoke passed ({checked} file hashes, schema 0061)")
