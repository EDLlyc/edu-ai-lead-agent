"""Offline smoke test for the 运营后台 release bdb0963 (run with --network none inside the overlay image)."""

import hashlib
import importlib
from pathlib import Path

for module in (
    "app.api_main",
    "app.worker_main",
    "app.content_scheduler_main",
    "app.content_worker_main",
    "app.wecom_dispatcher_main",
    "app.wecom_news_infographic_main",
    "app.admin_users_main",
    "app.seed_sources",
):
    importlib.import_module(module)

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.api_main import app
from app.domain.topic_selection import TopicVetoCode
from app.infrastructure.ingestion.connectors import get_connector

# Every overlaid file is the reviewed one.
root = Path(importlib.import_module("app").__file__).resolve().parents[1]
manifest = root / "release-bdb0963-files.txt"
lines = (manifest if manifest.is_file() else Path(__file__).with_name("files.txt")).read_text()
for line in lines.splitlines():
    if line.startswith("#") or not line.strip():
        continue
    path, _base, new = (part.strip() for part in line.split("|"))
    digest = hashlib.sha256((root / path).read_bytes()).hexdigest()
    assert digest == new, f"{path} is not the reviewed file"

# One migration head, the new one.
heads = ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_heads()
assert heads == ["20261008_0054"], heads

# Admin routes present; the rest of the API unchanged in shape.
paths = set(app.openapi()["paths"])
for path in (
    "/api/v1/admin/auth/login",
    "/api/v1/admin/auth/me",
    "/api/v1/admin/audit-events",
    "/api/v1/admin/sources",
    "/api/v1/admin/sources/preview",
    "/api/v1/admin/keywords",
    "/api/v1/admin/keywords/impact",
    "/api/v1/content-slot-human-picks/{run_id}/push",
):
    assert path in paths, path

# Generic connectors build from settings; code connectors unchanged.
get_connector("generic_html_v1", {"kind": "html"})
get_connector("generic_rss_v1", {"kind": "rss"})
get_connector("gmw_education_v1")
assert TopicVetoCode.OPERATOR_BLOCKED_TERM.value == "operator_blocked_term"
print("smoke ok: release bdb0963 (运营后台 login/audit + 新闻源 + 关键词, head 20261008_0054)")
