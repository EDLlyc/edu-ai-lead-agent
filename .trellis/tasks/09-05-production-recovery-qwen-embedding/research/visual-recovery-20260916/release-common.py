"""Exact-base V3 release constants and hash-bound archived helpers."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PREVIOUS_REVISION = "01ff75eed1ed82f5951580af994b6c5c750e53ae"
BASE_MANIFEST = (
    "sha256:febd216660c4fdf3919a8cd2c7da8c233d69d1e53503ff50b27df00c2aa58655"
)
BASE_ARCHIVE_SHA256 = "17e59b96cd2e7d929314b17b33b1407d50cb2c8156bf476025332819fdfa1c19"
REPOSITORY = "offline.local/edu-ai/edu-ai-lead-agent-backend"
BASE_REF = REPOSITORY + "@" + BASE_MANIFEST
EDITION = "41b26b7f-e792-56ff-bdfa-643171114056"
ARTICLE = "5e2bbc6e-6bec-4234-b516-7b2c58e198c6"
VERSION = "5107bfe9-ae30-4a2d-9fd0-c57a369fa6a8"
VISUAL = "31c58fc2-2722-4a28-957d-0b7b9b16d510"
BUSINESS_DATE = "2026-09-16"
EVENT = "b1de9144-9300-54bc-9588-0c4c92c7e87f"
CHANGE = "wechat-visual-recovery-20260916"
HISTORY_COMMAND = "COPY reviewed resilient visual application and migration files"
PREVIOUS_SCHEMA = "20260914_0047"
TARGET_SCHEMA = "20260916_0048"
MIGRATION_FILE = "alembic/versions/20260916_0048_resilient_visual_policy.py"
VISUAL_POLICY_KEY = "OFFICIAL_ACCOUNT_LOCAL_VISUAL_PIPELINE_VERSION"
PREVIOUS_VISUAL_POLICY = "official-account-visual-pipeline-v2-native-observe"
TARGET_VISUAL_POLICY = "official-account-visual-pipeline-v3-resilient-advisory"
IMAGE_MAX_ATTEMPTS = "1"
BODY_CHECKSUM_INDEX = "uq_official_account_local_media_body_checksum"
BODY_CHECKSUM_INDEX_BASELINE = {
    "name": BODY_CHECKSUM_INDEX,
    "table": "official_account_local_media",
    "unique": True,
    "valid": True,
    "ready": True,
    "columns": ["run_id", "sha256"],
    "predicate": "((role)::text = 'body'::text)",
}
ALLOWED_FILES = frozenset(
    {
        "core/errors.py",
        "application/ports/official_account_local.py",
        "application/ports/official_account_strict_visual.py",
        "application/services/official_account_local.py",
        "application/services/official_account_strict_prepared.py",
        "application/services/official_account_strict_visual.py",
        "domain/official_account_visual_pipeline.py",
        "infrastructure/ai/official_account_visual_strict.py",
        "infrastructure/db/models.py",
        "infrastructure/db/official_account_local.py",
        "infrastructure/db/official_account_strict_visual.py",
        "infrastructure/db/official_account_visual_compensation.py",
        "infrastructure/official_account_local.py",
    }
)
ARCHIVED = {
    "build": (
        "build-no-source-link-overlay.py",
        "8bbf23ba2fc1d8dcdb566063ea5bbcf571a39eb69e5423aa45d8c7ec265703d1",
    ),
    "validate": (
        "validate-no-source-link-overlay.py",
        "8f6e169935f9970f0f31c8980783433017d6b836d75651cb61ce1e96225a5e93",
    ),
    "deploy": (
        "deploy-no-source-links.py",
        "0ead97b4d5abdac7b06247d976abc795050241140188768ac182adf228df39a9",
    ),
}


def require(value: bool, code: str) -> None:
    if not value:
        raise RuntimeError(code)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def import_file(path: Path, name: str) -> Any:
    require(path.is_file() and not path.is_symlink(), "helper_path")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "helper_import")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def archived_path(role: str) -> Path:
    filename, checksum = ARCHIVED[role]
    path = ROOT / ("release-base-" + role + ".py")
    if not path.exists():
        roots = [
            parent / ".trellis"
            for parent in ROOT.parents
            if (parent / ".trellis").is_dir()
        ]
        require(bool(roots), "archive_root")
        path = (
            roots[0]
            / "tasks/archive/2026-09/09-15-deploy-wechat-no-source-link-rule/research"
            / filename
        )
    require(path.is_file() and not path.is_symlink(), "archive_helper_path")
    require(digest(path.read_bytes()) == checksum, "archive_helper_hash")
    return path


def archived(role: str) -> Any:
    return import_file(archived_path(role), "visual_recovery_base_" + role)


def validate_files(files: object) -> dict[str, str]:
    # The reviewed manifest digest binds the exact subset and all module bytes.
    require(
        isinstance(files, dict) and set(files) == ALLOWED_FILES,
        "app_files",
    )
    for path, checksum in files.items():
        require(
            isinstance(path, str)
            and re.fullmatch(
                r"(?:application/(?:services|ports)|core|domain|infrastructure(?:/(?:ai|db))?)/[a-z][a-z0-9_]*\.py",
                path,
            )
            is not None,
            "app_file_path",
        )
        require(
            isinstance(checksum, str)
            and re.fullmatch(r"[0-9a-f]{64}", checksum) is not None,
            "app_file_hash",
        )
    return files


def validate_migration_files(files: object) -> dict[str, str]:
    require(
        isinstance(files, dict) and set(files) == {MIGRATION_FILE}, "migration_files"
    )
    checksum = files[MIGRATION_FILE]
    require(
        isinstance(checksum, str)
        and re.fullmatch(r"[0-9a-f]{64}", checksum) is not None,
        "migration_file_hash",
    )
    return files


def source_module(name: str) -> Any:
    return import_file(ROOT / ("release-" + name + ".py"), "visual_recovery_" + name)


def manifest(path: Path, expected_hash: str) -> dict:
    base = archived("deploy")
    raw = base.safe_file(path)
    require(digest(raw) == expected_hash, "manifest_hash")
    value = json.loads(raw, object_pairs_hook=base.unique_object)
    required = {
        "version",
        "revision",
        "previous_revision",
        "base_ref",
        "base_archive_sha256",
        "candidate_tag",
        "candidate_ref",
        "candidate_image_id",
        "archive",
        "archive_sha256",
        "app_files",
        "migration_files",
        "previous_schema",
        "target_schema",
        "config_transition",
        "validator",
        "validator_sha256",
        "helpers",
        "production_snapshot",
    }
    require(isinstance(value, dict) and set(value) == required, "manifest_fields")
    require(
        all(
            isinstance(value[k], str)
            for k in required
            - {
                "app_files",
                "migration_files",
                "config_transition",
                "helpers",
                "production_snapshot",
            }
        ),
        "manifest_types",
    )
    require(
        value["version"] == CHANGE
        and re.fullmatch(r"[0-9a-f]{40}", value["revision"]) is not None
        and value["revision"] != PREVIOUS_REVISION,
        "manifest_revision",
    )
    require(
        value["previous_revision"] == PREVIOUS_REVISION
        and value["base_ref"] == BASE_REF
        and value["base_archive_sha256"] == BASE_ARCHIVE_SHA256,
        "manifest_base",
    )
    require(
        value["candidate_tag"]
        == REPOSITORY + ":visual-recovery-" + value["revision"][:12],
        "manifest_tag",
    )
    require(
        re.fullmatch(r"sha256:[0-9a-f]{64}", value["candidate_image_id"]) is not None
        and value["candidate_image_id"] != BASE_MANIFEST
        and value["candidate_ref"] == REPOSITORY + "@" + value["candidate_image_id"],
        "manifest_image",
    )
    require(
        value["archive"] == "backend-image.oci.tar.gz"
        and re.fullmatch(r"[0-9a-f]{64}", value["archive_sha256"]) is not None,
        "manifest_archive",
    )
    require(
        value["validator"] == "release-validate.py"
        and re.fullmatch(r"[0-9a-f]{64}", value["validator_sha256"]) is not None,
        "manifest_validator",
    )
    validate_files(value["app_files"])
    validate_migration_files(value["migration_files"])
    require(
        value["previous_schema"] == PREVIOUS_SCHEMA
        and value["target_schema"] == TARGET_SCHEMA,
        "manifest_schema",
    )
    require(
        value["config_transition"]
        == {
            "key": VISUAL_POLICY_KEY,
            "from": PREVIOUS_VISUAL_POLICY,
            "to": TARGET_VISUAL_POLICY,
            "image_max_attempts": IMAGE_MAX_ATTEMPTS,
        },
        "manifest_config_transition",
    )
    helpers = value["helpers"]
    names = {
        "release-build.py",
        "release-common.py",
        "release-snapshot.py",
        "release-journal.py",
        "release-validate.py",
        "release-deploy.py",
        "release-base-build.py",
        "release-base-validate.py",
        "release-base-deploy.py",
    }
    require(isinstance(helpers, dict) and set(helpers) == names, "manifest_helpers")
    require(
        all(
            isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) is not None
            for v in helpers.values()
        ),
        "manifest_helper_hash",
    )
    require(
        helpers["release-validate.py"] == value["validator_sha256"],
        "manifest_validator_hash",
    )
    for role, (_filename, checksum) in ARCHIVED.items():
        require(
            helpers["release-base-" + role + ".py"] == checksum,
            "manifest_archived_hash",
        )
    for name in names:
        if name.startswith("release-base-"):
            continue
        require(
            digest(base.safe_file(ROOT / name)) == helpers[name],
            "manifest_helper_changed",
        )
    # Import the snapshot validator only after its exact bundle byte hash is proven.
    source_module("snapshot").validate_snapshot(value["production_snapshot"])
    return value
