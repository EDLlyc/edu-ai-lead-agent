#!/usr/bin/env python3
"""Create the bounded legacy overlay locally; never invoke Docker or contact production."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

APPROVED_LEGACY_IMAGE = (
    "sha256:83a41e414fee1636c8d4897ae175ee5549afd9a7d4b37df0897b838c9b714851"
)
APPROVED_CONFIG_SHA256 = (
    "1155959c69c07bb99fbae68b61731743ca7ada0c4fc2e91f34542dc6dce77314"
)
FILES = (
    "app/official_account_worker_main.py",
    "app/official_account_weekly_dag_main.py",
    "app/governance_worker_main.py",
    "app/infrastructure/model_api_keys_overlay.py",
    "app/domain/model_api_keys.py",
    "app/domain/secret_box.py",
    "app/core/config.py",
    "app/infrastructure/official_account_single_runtime.py",
    "app/application/services/wechat_single_edition_delivery.py",
    "app/application/services/wechat_official_account_draft.py",
    "app/domain/official_account_layout_templates.py",
    "app/infrastructure/db/wechat_layout_templates.py",
)
FIELD_BEFORE = b'    business_timezone: str = "Asia/Shanghai"\n'
FIELD_AFTER = FIELD_BEFORE + b"    model_secret_key: SecretStr | None = None\n"
GETTER_BEFORE = b"@lru_cache\ndef get_settings() -> Settings:\n    return Settings()\n"
GETTER_AFTER = (
    b"@lru_cache\ndef get_settings() -> Settings:\n"
    b"    from app.infrastructure.model_api_keys_overlay import with_console_model_keys\n\n"
    b"    return with_console_model_keys(Settings())\n"
)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def port_config(original: bytes) -> bytes:
    if sha256(original) != APPROVED_CONFIG_SHA256:
        raise ValueError("unreviewed legacy Settings source")
    if original.count(FIELD_BEFORE) != 1 or original.count(GETTER_BEFORE) != 1:
        raise ValueError("legacy Settings insertion anchors changed")
    result = original.replace(FIELD_BEFORE, FIELD_AFTER).replace(
        GETTER_BEFORE, GETTER_AFTER
    )
    restored = result.replace(FIELD_AFTER, FIELD_BEFORE).replace(
        GETTER_AFTER, GETTER_BEFORE
    )
    if restored != original:
        raise ValueError("legacy Settings port changed unrelated bytes")
    compile(result, "app/core/config.py", "exec")
    return result


def build_context(
    *,
    repo_root: Path,
    legacy_root: Path,
    legacy_image: str,
    source_commit: str,
    output: Path,
    legacy_hashes: Path | None = None,
) -> dict[str, object]:
    if legacy_image != APPROVED_LEGACY_IMAGE:
        raise ValueError("unreviewed legacy image identity")
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ValueError("source commit must be a full Git SHA")
    if output.exists():
        raise ValueError("output must not exist; never overwrite a previous candidate")
    legacy_files = {}
    for path in sorted((legacy_root / "app").rglob("*.py")):
        if "__pycache__" in path.parts or path.is_symlink():
            raise ValueError("unexpected legacy source path")
        legacy_files[path.relative_to(legacy_root).as_posix()] = sha256(
            path.read_bytes()
        )
    if len(legacy_files) < 100:
        raise ValueError("legacy source snapshot is incomplete")
    if legacy_hashes is not None:
        full_files = json.loads(legacy_hashes.read_text())
        for name, value in full_files.items():
            path = Path(name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or re.fullmatch(r"[0-9a-f]{64}", value) is None
            ):
                raise ValueError("unsafe legacy hash manifest")
            if name not in {"pyproject.toml", "alembic.ini"} and path.parts[0] not in {
                "app",
                "alembic",
            }:
                raise ValueError("legacy hash manifest exceeds application scope")
        if {
            name: value
            for name, value in full_files.items()
            if name.startswith("app/") and name.endswith(".py")
        } != legacy_files:
            raise ValueError("legacy source snapshot differs from full file manifest")
        legacy_files = full_files
    original = (legacy_root / "app/core/config.py").read_bytes()
    derived = port_config(original)
    payloads = {}
    for name in FILES:
        source = repo_root / "backend" / name
        if source.is_symlink():
            raise ValueError("overlay source cannot be a symlink")
        payload = derived if name == "app/core/config.py" else source.read_bytes()
        if name != "app/core/config.py":
            committed = subprocess.run(
                ["git", "show", f"{source_commit}:backend/{name}"],
                cwd=repo_root,
                capture_output=True,
                check=True,
                timeout=30,
            ).stdout
            if payload != committed:
                raise ValueError(f"overlay differs from supplied source commit: {name}")
        compile(payload, name, "exec")
        payloads[name] = payload
    overlay_sha256 = {name: sha256(payload) for name, payload in payloads.items()}
    own = Path(__file__).resolve().parent
    helper_sha256 = {}
    for name in ("build_context.py", "smoke.py", "Dockerfile"):
        source = own / name
        relative = source.relative_to(repo_root.resolve()).as_posix()
        payload = source.read_bytes()
        committed = subprocess.run(
            ["git", "show", f"{source_commit}:{relative}"],
            cwd=repo_root,
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
        if payload != committed:
            raise ValueError(
                f"build helper differs from supplied source commit: {name}"
            )
        helper_sha256[name] = sha256(payload)
    manifest = {
        "version": 1,
        "legacy_image": legacy_image,
        "source_commit": source_commit,
        "full_legacy_manifest": legacy_hashes is not None,
        "app_file_scope": "app/, alembic/, alembic.ini, pyproject.toml excluding pyc and __pycache__"
        if legacy_hashes
        else "all app/**/*.py excluding __pycache__",
        "overlay_files": list(FILES),
        "legacy_files": legacy_files,
        "overlay_sha256": overlay_sha256,
        "expected_file_sha256": {**legacy_files, **overlay_sha256},
        "expected_app_sha256": {
            name: value
            for name, value in {**legacy_files, **overlay_sha256}.items()
            if name.startswith("app/")
        },
        "legacy_config_sha256": sha256(original),
        "derived_config_sha256": sha256(derived),
        "build_helpers_sha256": helper_sha256,
    }
    output.mkdir(parents=True)
    for name, payload in payloads.items():
        target = output / "overlay" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    verification = output / "verification"
    verification.mkdir()
    (verification / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    )
    (verification / "legacy-config.py").write_bytes(original)
    for name in helper_sha256:
        shutil.copyfile(own / name, verification / name)
    shutil.copyfile(own / "Dockerfile", output / "Dockerfile")
    (output / ".dockerignore").write_text("**/__pycache__\n**/*.pyc\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--legacy-root", required=True, type=Path)
    parser.add_argument("--legacy-image", required=True)
    parser.add_argument(
        "--legacy-hashes",
        type=Path,
        help="Actual image hashes including assets, migrations and package metadata; required for production smoke",
    )
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build_context(**vars(args))
    print(
        json.dumps(
            {
                "overlay_files": len(FILES),
                "legacy_files": len(result["legacy_files"]),
                "manifest": str(args.output / "verification/manifest.json"),
                "source_commit": args.source_commit,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
