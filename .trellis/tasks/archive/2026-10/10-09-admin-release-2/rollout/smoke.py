"""Offline smoke test for 运营后台 release 9eaaaf3 (run with --network none in the overlay image)."""

import hashlib
import importlib
from pathlib import Path

RELEASE = "9eaaaf3"

# Every entry point of the six recreated services, plus the operator CLIs.
for module in (
    "app.api_main",
    "app.worker_main",
    "app.scheduler_main",
    "app.content_worker_main",
    "app.content_scheduler_main",
    "app.wecom_news_infographic_main",
    "app.wecom_dispatcher_main",
    "app.admin_users_main",
    "app.wechat_accounts_main",
):
    importlib.import_module(module)

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.api_main import app
from app.application.services.wechat_layout_templates import layout_preview
from app.core.config import get_settings
from app.domain.official_account_layout_templates import apply_layout_template
from app.domain.secret_box import new_key, open_sealed, parse_key, seal
from app.infrastructure.model_api_keys_overlay import loaded_versions, start_model_key_watch

root = Path(importlib.import_module("app").__file__).resolve().parents[1]
manifest = root / f"release-{RELEASE}-files.txt"
lines = (manifest if manifest.is_file() else Path(__file__).with_name("files.txt")).read_text()
checked = 0
for line in lines.splitlines():
    if line.startswith("#") or not line.strip():
        continue
    path, _base, new = (part.strip() for part in line.split("|"))
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == new, f"{path} is not reviewed"
    checked += 1
assert checked == 42, checked

assert ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_heads() == [
    "20261009_0059"
]
paths = set(app.openapi()["paths"])
for path in (
    "/api/v1/admin/accounts",
    "/api/v1/admin/auth/password",
    "/api/v1/admin/sources/{source_id}/articles",
    "/api/v1/admin/wechat/accounts",
    "/api/v1/admin/wechat/publish-jobs",
    "/api/v1/admin/wechat/accounts/{account_id}/stats",
    "/api/v1/admin/wechat/layout-templates",
    "/api/v1/admin/wechat/accounts/{account_id}/layout-template",
    "/api/v1/admin/models",
    "/api/v1/admin/models/{provider_id}/keys",
):
    assert path in paths, path

key = parse_key(new_key())
assert open_sealed(seal("x" * 32, key=key, purpose="p"), key=key, purpose="p") == "x" * 32
sample = layout_preview("xiaosai-blue")
assert apply_layout_template(sample, None) is sample and "#0B7A64" in layout_preview("jade-green")

# Without MODEL_SECRET_KEY the console keys are off: no DB read, no watch.
settings = get_settings()
assert settings.model_secret_key is None and loaded_versions() is None
assert start_model_key_watch(settings, service="acquisition-api") is False
print(f"smoke ok: release {RELEASE} (admin polish + wechat 3/4/5 + layout 6 + model keys 8)")
