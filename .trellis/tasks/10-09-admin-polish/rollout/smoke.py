"""Offline smoke test for the 运营后台 polish release 0854380 (run with --network none in the overlay image)."""

import hashlib
import importlib
from pathlib import Path

for module in ("app.api_main", "app.worker_main", "app.content_worker_main", "app.admin_users_main"):
    importlib.import_module(module)

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.api_main import app
from app.domain.admin_auth import generate_initial_password

root = Path(importlib.import_module("app").__file__).resolve().parents[1]
manifest = root / "release-0854380-files.txt"
lines = (manifest if manifest.is_file() else Path(__file__).with_name("files.txt")).read_text()
for line in lines.splitlines():
    if line.startswith("#") or not line.strip():
        continue
    path, _base, new = (part.strip() for part in line.split("|"))
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == new, f"{path} is not the reviewed file"

# No migration in this release.
assert ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_heads() == ["20261008_0054"]
paths = set(app.openapi()["paths"])
for path in (
    "/api/v1/admin/accounts",
    "/api/v1/admin/accounts/{username}/reset-password",
    "/api/v1/admin/auth/password",
    "/api/v1/admin/sources/{source_id}/articles",
    "/api/v1/admin/keywords",
):
    assert path in paths, path
assert len(generate_initial_password()) == 14
print("smoke ok: release 0854380 (accounts + own password + source articles + audit filters)")
