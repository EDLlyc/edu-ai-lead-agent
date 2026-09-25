#!/usr/bin/env python3
"""One offline 3e62b33 -> reviewed R13 Moments-copy release.

Build reads committed git blobs, never workspace source. Plan is read-only. Apply
requires exact candidate and independently captured baseline hashes. A failed
activation stops writers; an old application is never restarted after activation.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, cast
from zoneinfo import ZoneInfo

VERSION = "moments-heading-advisory-20260925-v2-mixed-baseline"
BASE_REVISION = "3e62b33fcc62582240cb73ede9b12756eda029c5"
BASE_ID = "sha256:2b3a9a7c5e35a3a7173a129a3bd7e0d5322caaeef2c125b9a4d63146e77c9d1a"
BASE_ARCHIVE_SHA = "651dbc6c08efc38ba405f133b630f4af077c45101de71f3777eab3a22827a80e"
NOTICE_REVISION = "a9db34f8937effda32a2a58358d2b849268700a5"
NOTICE_LABEL_REVISION = "a9db34f"
NOTICE_SERVICE = "wechat-official-account-draft-worker"
NOTICE_IMAGE_ID = (
    "sha256:c3f26a9d352332b4cbb63430922babcd71a025ba593fff2e792a4b6c1421e974"
)
NOTICE_IMAGE_TAG = "offline.local/edu-ai/edu-ai-lead-agent-backend:notice-a9db34f"
NOTICE_APP_HASHES = {
    "application/services/wechat_official_account_draft.py": "05ff063fccc9b8602dc969a9a51c1809ba55cfb4e4e01dc40ebaeb4eb386e3e5",
    "domain/official_account_editor_handoff.py": "71fd515fee2e1bb1124db9de77843a2dd5fd63746603b9354246ac44aa5a6c0e",
}
# One pre-existing July test document is still active with provider "fake".
# The production Zhipu retrieval filters it out; this release neither edits nor
# activates brand data. Pin its identity instead of weakening the provider gate.
LEGACY_FAKE_BRAND_SHA = (
    "8385e6303397820cdc3cb6c1811754cc6b843a0b93b6a6e8cf38337e8328351e"
)
# A previous offline release deliberately retained this live OCR integration.
# It is outside this change: Git equality is required, but the frozen base bytes
# (not the newer repository implementation) remain authoritative in the image.
PRESERVED_BASE_FILES = {
    "infrastructure/ai/zhipu.py": {
        "runtime_sha256": "b9aa021414acc1dcb25068bac707c97da3b52cbd5fc5cb3195ed1a3174514cd9",
        "runtime_size": 48896,
        "base_git_sha256": "3e63bf9d40131c3be51ee4351e8acec8832319f24ba5e5bfc9aab5e256f0345e",
        "candidate_git_sha256": "3e63bf9d40131c3be51ee4351e8acec8832319f24ba5e5bfc9aab5e256f0345e",
    },
}
REPOSITORY = "offline.local/edu-ai/edu-ai-lead-agent-backend"
BASE_REF = REPOSITORY + "@" + BASE_ID
SCHEMA = "20260916_0048"
POLICY_KEY = "OFFICIAL_ACCOUNT_LOCAL_VISUAL_PIPELINE_VERSION"
PROD_POLICY = "official-account-visual-pipeline-v4-resilient-tolerant-geometry"
APP = Path("/opt/edu-ai-lead-agent")
BACKUP_ROOT = Path("/opt/edu-ai-release-backups")
LOCK = Path("/var/lock/edu-ai-deploy.lock")
BACKUP_LOCK = Path("/var/lock/edu-ai-backup.lock")
OPERATOR_PATH = ".trellis/tasks/09-23-moments-brand-rag-diversity/research/r14-release/moments_release.py"
ALLOWED_APP_FILES = {
    "backend/app/application/services/copy_generation.py",
    "backend/app/application/services/wechat_official_account_draft.py",
    "backend/app/core/config.py",
    "backend/app/domain/copy_generation.py",
    "backend/app/domain/official_account_editor_handoff.py",
    "backend/app/schemas/copy_generation.py",
}
HOST_FILES: tuple[str, ...] = ()
PROTECTED_FILES = (
    ".env",
    ".release.env",
    ".release-commit",
    "RELEASE_COMMIT",
    "compose.yaml",
    "scripts/edu-ai-release-common.sh",
    "deploy/release/migration-compatibility.json",
    "deploy/release/deploy.py",
    "scripts/edu-ai-production-check.sh",
    "scripts/doctor.sh",
)
STANDARD_RELEASE_MARKERS = (
    "/var/lib/edu-ai/releases/current.json",
    str(APP / ".release-manifest.json"),
    "/usr/local/sbin/edu-ai-deploy",
)
PROTECTED_METADATA = {
    ".env": {"mode": 0o600, "uid": 1000, "gid": 1001},
    ".release.env": {"mode": 0o600, "uid": 0, "gid": 0},
    ".release-commit": {"mode": 0o600, "uid": 0, "gid": 0},
    "RELEASE_COMMIT": {"mode": 0o600, "uid": 0, "gid": 0},
    "compose.yaml": {"mode": 0o600, "uid": 0, "gid": 0},
    "scripts/edu-ai-release-common.sh": {"mode": 0o700, "uid": 0, "gid": 0},
    "deploy/release/migration-compatibility.json": {"mode": 0o644, "uid": 0, "gid": 0},
    "deploy/release/deploy.py": {"mode": 0o600, "uid": 0, "gid": 0},
    "scripts/edu-ai-production-check.sh": {"mode": 0o700, "uid": 0, "gid": 0},
    "scripts/doctor.sh": {"mode": 0o755, "uid": 0, "gid": 0},
}
SERVICES = (
    "acquisition-api",
    "acquisition-scheduler",
    "acquisition-worker",
    "governance-scheduler",
    "governance-worker",
    "content-scheduler",
    "content-worker",
    "official-account-weekly-dag-worker",
    "official-account-weekly-scheduler",
    "official-account-local-worker",
    "wechat-official-account-draft-worker",
    "wecom-dispatcher",
)
OA_WRITERS = (
    "official-account-weekly-dag-worker",
    "official-account-weekly-scheduler",
    "official-account-local-worker",
    "wechat-official-account-draft-worker",
)
SINGLE_SERVICES = (
    "official-account-weekly-dag-worker",
    "official-account-weekly-scheduler",
    "wechat-official-account-draft-worker",
)
BRAND_SERVICES = (
    "official-account-weekly-dag-worker",
    "acquisition-api",
    "content-worker",
    "official-account-local-worker",
    "wecom-dispatcher",
)
HISTORICAL_COPY_DATES = (
    "2026-08-04",
    "2026-08-05",
    "2026-08-07",
    "2026-08-08",
    "2026-08-09",
    "2026-08-10",
    "2026-08-11",
)
# Independently measured before the first release capture, never learned from
# whichever seven rows happen to exist when the operator is invoked.
HISTORICAL_COPY_COHORT_SHA = (
    "78f6de9ee6546cf15bfcbb8402b1e2e1d6094282dd9d15c05411c6733ca7ed24"
)
HISTORICAL_ARTICLE_UNKNOWN_SHA = (
    "636c9d034399d98ae6aaa3a507347e983c6163e2e128ca9b7354b2b624973ad9"
)
HISTORICAL_ARTICLE_UNKNOWN_CUTOFF = "2026-09-17T00:00:00+08:00"
PROFILES = (
    "governance",
    "content",
    "official-account-weekly-dag",
    "official-account-local",
    "wechat-official-account-draft",
    "wecom",
)
FLAGS = {
    "OFFICIAL_ACCOUNT_SINGLE_ENABLED": "true",
    "OFFICIAL_ACCOUNT_WEEKLY_SCHEDULER_ENABLED": "false",
    "OFFICIAL_ACCOUNT_WEEKLY_WORKER_ENABLED": "false",
    "WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED": "false",
    "WECHAT_MP_MODE": "draft_only",
    "IMAGE_MAX_ATTEMPTS": "1",
}
OCI = "application/vnd.oci.image."
APP_PROBE = r"""
import hashlib,json,pathlib
root=pathlib.Path('/app/app'); result={}
for p in sorted(root.rglob('*')):
    if '__pycache__' in p.parts or p.suffix=='.pyc': continue
    if p.is_symlink(): raise RuntimeError('app_symlink')
    if p.is_file(): result[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
print(json.dumps(result,sort_keys=True))
"""
RUNTIME_PROBE = r"""
import hashlib,importlib,json,pathlib,subprocess
from alembic.config import Config
from alembic.script import ScriptDirectory
root=pathlib.Path('/app'); result={}
paths=[root/'alembic.ini',root/'pyproject.toml',*sorted((root/'alembic').rglob('*'))]
for p in paths:
    if '__pycache__' in p.parts or p.suffix=='.pyc': continue
    if p.is_symlink(): raise RuntimeError('runtime_symlink')
    if p.is_file(): result[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
modules=('app.api_main','app.scheduler_main','app.worker_main','app.governance_scheduler_main',
 'app.governance_worker_main','app.content_scheduler_main','app.content_worker_main',
 'app.official_account_weekly_dag_main','app.official_account_weekly_scheduler_main',
 'app.official_account_worker_main','app.wechat_official_account_draft_main','app.wecom_dispatcher_main')
for name in modules: importlib.import_module(name)
from app.core.config import Settings
from app.api_main import app
Settings(); assert app.openapi()['openapi']
assert ScriptDirectory.from_config(Config('/app/alembic.ini')).get_heads()==['20260916_0048']
assert subprocess.run(['python','-m','pip','check'],capture_output=True,check=False).returncode==0
print(json.dumps(result,sort_keys=True))
"""
COPY_PROBE = r"""
import json
from app.core.config import Settings
s=Settings()
print(json.dumps({key:getattr(s,key) for key in (
 'copy_generator_prompt_version','copy_auditor_prompt_version',
 'copy_rule_version','copy_preview_policy_version',
 'brand_embedding_provider','brand_embedding_model','brand_embedding_dimensions')},sort_keys=True))
"""
BASE_COPY_VERSIONS = {
    "copy_generator_prompt_version": "moments-generator-v19-exact-claim-span",
    "copy_auditor_prompt_version": "moments-auditor-v18-xiaosai-insight",
    "copy_rule_version": "moments-rules-v11-compact-warning-recovery",
    "copy_preview_policy_version": "preview-v11-compact-content-warning-recovery",
}
CANDIDATE_COPY_VERSIONS = {
    "copy_generator_prompt_version": "moments-generator-v24-standalone-heading",
    "copy_auditor_prompt_version": "moments-auditor-v19-standalone-heading",
    "copy_rule_version": "moments-rules-v12-standalone-heading-advisory",
    "copy_preview_policy_version": "preview-v12-standalone-heading-advisory",
}


def require(ok: Any, code: str) -> None:
    if not ok:
        raise RuntimeError(code)


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def strict_json(body: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    return json.loads(
        body,
        object_pairs_hook=pairs,
        parse_constant=lambda _: require(False, "json_constant"),
    )


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    require(
        value
        and not path.is_absolute()
        and ".." not in path.parts
        and str(path) == value,
        "unsafe_relative_path",
    )
    require(not any(c.isspace() or ord(c) < 32 for c in value), "unsafe_relative_path")
    return value


def physical(path: Path) -> None:
    require(path.is_absolute() and path.resolve() == path, "nonphysical_path")
    for part in (path, *path.parents):
        require(not part.is_symlink(), "symlink_path")


def stable_file(path: Path) -> tuple[bytes, os.stat_result]:
    physical(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "unsafe_file")
        body = stream.read()
        after = os.fstat(stream.fileno())
    current = path.stat(follow_symlinks=False)
    fields = (
        "st_dev",
        "st_ino",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
        "st_mode",
        "st_uid",
        "st_gid",
        "st_nlink",
    )
    require(
        all(
            getattr(before, key) == getattr(after, key) == getattr(current, key)
            for key in fields
        )
        and len(body) == before.st_size,
        "file_read_race",
    )
    return body, before


def read_file(path: Path) -> bytes:
    return stable_file(path)[0]


def inventory_metadata(path: Path) -> dict[str, Any]:
    body, info = stable_file(path)
    return {
        "sha256": sha(body),
        "size": len(body),
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "gid": info.st_gid,
    }


def metadata(path: Path) -> dict[str, Any]:
    result = inventory_metadata(path)
    require(not result["mode"] & 0o022, "writable_file")
    return result


def brand_metadata(path: Path) -> dict[str, Any]:
    """Inventory existing read-only-mounted data without changing its permissions."""
    result = inventory_metadata(path)
    mode = result["mode"]
    require(
        not mode & 0o7000 and (mode == 0o664 or not mode & 0o022),
        "unsafe_brand_file_mode",
    )
    return result


def write_new(path: Path, body: bytes) -> None:
    physical(path.parent)
    with path.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def replace_file(path: Path, body: bytes, expected: dict[str, Any]) -> None:
    require(metadata(path) == expected, "file_changed_before_replace")
    fd, name = tempfile.mkstemp(prefix=".forward-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchown(stream.fileno(), expected["uid"], expected["gid"])
            os.fchmod(stream.fileno(), expected["mode"])
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        require(metadata(path) == expected, "file_changed_before_replace")
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        actual = metadata(path)
        require(
            actual == {**expected, "sha256": sha(body), "size": len(body)},
            "replace_readback",
        )
    finally:
        if Path(name).exists():
            Path(name).unlink()


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 120,
    input_data: bytes | None = None,
    output: Any = subprocess.PIPE,
    accepted_codes: tuple[int, ...] = (0,),
) -> bytes:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            input=input_data,
            stdout=output,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "LC_ALL": "C",
            },
        )
        require(result.returncode in accepted_codes, "subprocess_failed")
        return result.stdout or b""
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("subprocess_failed") from exc


def git(repo: Path, *args: str) -> bytes:
    return run(["git", *args], cwd=repo)


def git_files(repo: Path, revision: str, prefix: str) -> dict[str, bytes]:
    result = {}
    for record in git(repo, "ls-tree", "-rz", revision, "--", prefix).split(b"\0"):
        if not record:
            continue
        head, name = record.split(b"\t", 1)
        mode, kind, blob = head.split()
        require(mode in (b"100644", b"100755") and kind == b"blob", "git_file_type")
        relative = safe_relative(name.decode())
        result[relative] = git(repo, "cat-file", "blob", blob.decode())
    return result


def tar_member(
    bundle: tarfile.TarFile, name: str, body: bytes, *, uid: int = 0
) -> None:
    info = tarfile.TarInfo(safe_relative(name))
    info.mode, info.uid, info.gid, info.mtime, info.size = 0o644, uid, uid, 0, len(body)
    bundle.addfile(info, io.BytesIO(body))


def archive_bytes(members: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as bundle:
        for name, body in sorted(members.items()):
            tar_member(bundle, name, body)
    return gzip.compress(stream.getvalue(), mtime=0)


def archive_members(path: Path) -> dict[str, bytes]:
    body = read_file(path)
    require(len(body) < 512 * 1024 * 1024, "archive_size")
    result = {}
    seen = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
        for item in archive:
            name = safe_relative(item.name.rstrip("/"))
            require(name not in seen, "archive_duplicate")
            seen.add(name)
            require(item.isfile() or item.isdir(), "archive_type")
            require(
                item.mode in (0o644, 0o755) and item.uid == item.gid == 0,
                "archive_metadata",
            )
            if item.isdir():
                require(name in ("blobs", "blobs/sha256"), "archive_directory")
                continue
            total += item.size
            require(
                item.size <= 256 * 1024 * 1024 and total <= 1024 * 1024 * 1024,
                "archive_size",
            )
            stream = archive.extractfile(item)
            require(stream is not None, "archive_stream")
            result[name] = stream.read(item.size + 1)  # type: ignore[union-attr]
            require(len(result[name]) == item.size, "archive_size")
    return result


def describe(body: bytes, media_type: str) -> dict[str, Any]:
    return {"digest": "sha256:" + sha(body), "size": len(body), "mediaType": media_type}


def bounded_gunzip(body: bytes, limit: int = 512 * 1024 * 1024) -> bytes:
    with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
        result = stream.read(limit + 1)
    require(len(result) <= limit, "gzip_expansion_limit")
    return result


def oci_graph(
    members: dict[str, bytes], *, expected_tag: str | None = None
) -> tuple[dict[str, Any], dict[str, Any], str]:
    require(
        strict_json(members["oci-layout"]) == {"imageLayoutVersion": "1.0.0"},
        "oci_layout",
    )
    index = strict_json(members["index.json"])
    require(
        set(index) == {"schemaVersion", "mediaType", "manifests"}
        and index.get("schemaVersion") == 2
        and type(index["schemaVersion"]) is int
        and index["mediaType"] == OCI + "index.v1+json"
        and isinstance(index["manifests"], list)
        and len(index["manifests"]) == 1,
        "oci_index",
    )
    top = index["manifests"][0]
    require(
        set(top) == {"digest", "size", "mediaType", "platform", "annotations"}
        and top["platform"] == {"architecture": "amd64", "os": "linux"},
        "oci_top_descriptor",
    )
    annotations = top["annotations"]
    require(
        set(annotations)
        == {"io.containerd.image.name", "org.opencontainers.image.ref.name"}
        and isinstance(annotations["io.containerd.image.name"], str)
        and annotations["io.containerd.image.name"].startswith(REPOSITORY + ":")
        and annotations["org.opencontainers.image.ref.name"]
        == annotations["io.containerd.image.name"].split(":")[-1],
        "oci_annotations",
    )
    if expected_tag is not None:
        require(
            annotations["io.containerd.image.name"] == expected_tag, "oci_tag_binding"
        )
    reached = {"oci-layout", "index.json"}

    def get(desc: dict[str, Any], media: str) -> bytes:
        require(
            desc.get("mediaType") == media
            and type(desc.get("size")) is int
            and desc["size"] >= 0
            and re.fullmatch(r"sha256:[0-9a-f]{64}", desc.get("digest", "")),
            "oci_descriptor",
        )
        name = "blobs/sha256/" + desc["digest"][7:]
        data = members[name]
        require(
            desc["size"] == len(data) and desc["digest"] == "sha256:" + sha(data),
            "oci_blob_hash",
        )
        reached.add(name)
        return data

    manifest = strict_json(get(index["manifests"][0], OCI + "manifest.v1+json"))
    require(
        set(manifest) == {"schemaVersion", "mediaType", "config", "layers"}
        and type(manifest["schemaVersion"]) is int
        and manifest["schemaVersion"] == 2
        and manifest["mediaType"] == OCI + "manifest.v1+json",
        "oci_manifest",
    )
    require(
        set(manifest["config"]) == {"mediaType", "size", "digest"},
        "oci_config_descriptor",
    )
    config = strict_json(get(manifest["config"], OCI + "config.v1+json"))
    layers = manifest["layers"]
    require(len(layers) == len(config["rootfs"]["diff_ids"]), "oci_layer_count")
    for desc, diff_id in zip(layers, config["rootfs"]["diff_ids"], strict=True):
        require(set(desc) == {"mediaType", "size", "digest"}, "oci_layer_descriptor")
        require(
            "sha256:" + sha(bounded_gunzip(get(desc, OCI + "layer.v1.tar+gzip")))
            == diff_id,
            "oci_diff_id",
        )
    require(set(members) == reached, "oci_extra_blob")
    require(
        config["architecture"] == "amd64" and config["os"] == "linux", "oci_platform"
    )
    return manifest, config, index["manifests"][0]["digest"]


def preserved_base_hashes(
    members: dict[str, bytes], base_manifest: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Read only the fixed exception paths from the already verified OCI layers."""
    target_names = {"app/app/" + path: path for path in PRESERVED_BASE_FILES}
    found: dict[str, dict[str, Any]] = {}
    for descriptor in base_manifest["layers"]:
        body = bounded_gunzip(members["blobs/sha256/" + descriptor["digest"][7:]])
        seen: set[str] = set()
        layer_found: dict[str, dict[str, Any]] = {}
        removed: set[str] = set()
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:") as layer:
            for entry in layer:
                entry_path = PurePosixPath(entry.name)
                require(
                    not entry_path.is_absolute() and ".." not in entry_path.parts,
                    "preserved_base_unsafe_path",
                )
                name = entry_path.as_posix()
                for target, relative in target_names.items():
                    parts = PurePosixPath(target).parts
                    ancestors = [
                        "/".join(parts[:index]) for index in range(1, len(parts))
                    ]
                    whiteouts = [
                        "/".join((*parts[:index], ".wh." + parts[index]))
                        for index in range(len(parts))
                    ]
                    opaque = [
                        ".wh..wh..opq",
                        *(parent + "/.wh..wh..opq" for parent in ancestors),
                    ]
                    if name in whiteouts or name in opaque:
                        removed.add(relative)
                    if name in ancestors:
                        require(entry.isdir(), "preserved_base_ancestor_type")
                    if name != target:
                        continue
                    require(
                        name not in seen
                        and entry.isfile()
                        and entry.size <= 2 * 1024 * 1024,
                        "preserved_base_entry",
                    )
                    seen.add(name)
                    stream = layer.extractfile(entry)
                    require(stream is not None, "preserved_base_stream")
                    assert stream is not None
                    content = stream.read(entry.size + 1)
                    require(len(content) == entry.size, "preserved_base_size")
                    layer_found[relative] = {
                        "runtime_sha256": sha(content),
                        "runtime_size": len(content),
                    }
        # OCI whiteouts affect lower layers, never entries written by this same
        # layer. Tar member ordering must not change the effective bytes.
        for relative in removed:
            found.pop(relative, None)
        found.update(layer_found)
    expected = {
        path: {
            "runtime_sha256": value["runtime_sha256"],
            "runtime_size": value["runtime_size"],
        }
        for path, value in PRESERVED_BASE_FILES.items()
    }
    require(found == expected, "preserved_base_bytes")
    return found


def notice_tree(base_tree: dict[str, str]) -> dict[str, str]:
    require(set(NOTICE_APP_HASHES) <= set(base_tree), "notice_source_paths")
    return {**base_tree, **NOTICE_APP_HASHES}


def check_notice_app_tree(actual: dict[str, str], expected: dict[str, str]) -> None:
    require(actual == expected, "notice_app_tree")


def check_notice_image(base: dict[str, Any], notice: dict[str, Any]) -> None:
    """Bind the one independently released draft-Worker image, not a wildcard."""
    require(
        notice.get("Id") == NOTICE_IMAGE_ID
        and NOTICE_IMAGE_TAG in notice.get("RepoTags", [])
        and notice["Config"]["Labels"]["org.opencontainers.image.revision"]
        == NOTICE_LABEL_REVISION,
        "notice_image_identity",
    )
    base_layers = base["RootFS"]["Layers"]
    notice_layers = notice["RootFS"]["Layers"]
    require(
        len(notice_layers) == len(base_layers) + 2
        and notice_layers[: len(base_layers)] == base_layers,
        "notice_image_lineage",
    )
    require(
        {key: value for key, value in notice["Config"].items() if key != "Labels"}
        == {key: value for key, value in base["Config"].items() if key != "Labels"},
        "notice_runtime_config",
    )


def check_baseline_service_image(
    name: str, item: dict[str, Any], rendered_image: str
) -> None:
    expected_id = NOTICE_IMAGE_ID if name == NOTICE_SERVICE else BASE_ID
    expected_ref = NOTICE_IMAGE_TAG if name == NOTICE_SERVICE else BASE_REF
    require(
        item["Image"] == expected_id
        and item["Config"]["Image"] == expected_ref
        and rendered_image == BASE_REF,
        "baseline_service_image",
    )


def build(
    repo: Path, base_archive: Path, output: Path, revision: str
) -> dict[str, Any]:
    require(re.fullmatch(r"[0-9a-f]{40}", revision), "revision")
    require(
        git(repo, "rev-parse", revision + "^{commit}").decode().strip() == revision,
        "commit_missing",
    )
    git(repo, "merge-base", "--is-ancestor", BASE_REVISION, revision)
    changes = (
        git(repo, "diff", "--name-status", "--no-renames", BASE_REVISION, revision)
        .decode()
        .splitlines()
    )
    changed_app: set[str] = set()
    for change in changes:
        status, name = change.split("\t")
        require(
            not (
                name.startswith(
                    ("backend/migrations/", "backend/alembic/", "backend/requirements/")
                )
                or name
                in (
                    "compose.yaml",
                    "backend/Dockerfile",
                    "backend/pyproject.toml",
                    "backend/uv.lock",
                    "backend/requirements.lock",
                    "backend/requirements.txt",
                    "backend/alembic.ini",
                    "environment.yml",
                    "pyproject.toml",
                    "uv.lock",
                    "Makefile",
                )
            ),
            "forbidden_runtime_change",
        )
        if name.startswith("backend/app/"):
            require(name in ALLOWED_APP_FILES and status == "M", "app_allowlist")
            changed_app.add(name)
        else:
            require(
                name.startswith(
                    (
                        "backend/tests/",
                        ".trellis/tasks/09-23-moments-brand-rag-diversity/research/r14-release/",
                    )
                ),
                "unreviewed_source_change",
            )
    require(changed_app == ALLOWED_APP_FILES, "incomplete_app_port")
    old = git_files(repo, BASE_REVISION, "backend/app")
    new = git_files(repo, revision, "backend/app")
    require(set(old) <= set(new), "app_deletion")
    require(
        git(repo, "rev-parse", NOTICE_REVISION + "^{commit}").decode().strip()
        == NOTICE_REVISION,
        "notice_commit_missing",
    )
    git(repo, "merge-base", "--is-ancestor", BASE_REVISION, NOTICE_REVISION)
    notice_source = git_files(repo, NOTICE_REVISION, "backend/app")
    require(
        set(notice_source) == set(old)
        and {
            path.removeprefix("backend/app/"): sha(body)
            for path, body in notice_source.items()
            if old[path] != body
        }
        == NOTICE_APP_HASHES,
        "notice_git_tree",
    )
    for relative in NOTICE_APP_HASHES:
        path = "backend/app/" + relative
        require(new[path] == notice_source[path], "notice_fix_not_preserved")
    for relative, preserved in PRESERVED_BASE_FILES.items():
        path = "backend/app/" + relative
        require(
            path in old
            and path in new
            and old[path] == new[path]
            and sha(old[path])
            == preserved["base_git_sha256"]
            == preserved["candidate_git_sha256"],
            "preserved_file_git_changed",
        )
    overlay = {key: body for key, body in new.items() if old.get(key) != body}
    require(set(overlay) == ALLOWED_APP_FILES, "app_overlay_allowlist")
    immutable = git_files(repo, revision, "backend/alembic")
    for name in ("backend/alembic.ini", "backend/pyproject.toml"):
        immutable[name] = git(repo, "show", revision + ":" + name)
    operator = git(repo, "show", revision + ":" + OPERATOR_PATH)
    require(operator == read_file(Path(__file__).resolve()), "uncommitted_operator")
    compatibility = strict_json(
        git(repo, "show", revision + ":deploy/release/migration-compatibility.json")
    )
    require(
        compatibility["alembic_head"] == SCHEMA
        and compatibility["previous_application_compatible"] is False,
        "candidate_schema",
    )
    require(sha(read_file(base_archive)) == BASE_ARCHIVE_SHA, "base_archive_hash")
    members = archive_members(base_archive)
    base_manifest, base_config, base_id = oci_graph(members)
    require(
        base_id == BASE_ID
        and base_config["config"]["Labels"]["org.opencontainers.image.revision"]
        == BASE_REVISION,
        "base_identity",
    )
    preserved_base_hashes(members, base_manifest)
    raw_stream = io.BytesIO()
    with tarfile.open(fileobj=raw_stream, mode="w", format=tarfile.PAX_FORMAT) as layer:
        for path, body in sorted(overlay.items()):
            tar_member(layer, "app/" + path.removeprefix("backend/"), body, uid=999)
    raw_layer = raw_stream.getvalue()
    layer_body = gzip.compress(raw_layer, mtime=0)
    config = copy.deepcopy(base_config)
    labels = config["config"]["Labels"]
    labels.update(
        {
            "org.opencontainers.image.revision": revision,
            "edu.ai.overlay.base": BASE_ID,
            "edu.ai.change": VERSION,
        }
    )
    config["rootfs"]["diff_ids"].append("sha256:" + sha(raw_layer))
    config["history"].append(
        {"created_by": "COPY committed reviewed R13 Moments copy app blobs"}
    )
    config_body = canonical(config)
    manifest = {
        "schemaVersion": 2,
        "mediaType": OCI + "manifest.v1+json",
        "config": describe(config_body, OCI + "config.v1+json"),
        "layers": [
            *base_manifest["layers"],
            describe(layer_body, OCI + "layer.v1.tar+gzip"),
        ],
    }
    manifest_body = canonical(manifest)
    image_id = "sha256:" + sha(manifest_body)
    tag = REPOSITORY + ":moments-" + revision[:12]
    index = {
        "schemaVersion": 2,
        "mediaType": OCI + "index.v1+json",
        "manifests": [
            {
                **describe(manifest_body, OCI + "manifest.v1+json"),
                "platform": {"os": "linux", "architecture": "amd64"},
                "annotations": {
                    "io.containerd.image.name": tag,
                    "org.opencontainers.image.ref.name": tag.split(":")[-1],
                },
            }
        ],
    }
    keep = {"oci-layout": members["oci-layout"], "index.json": canonical(index)}
    for desc in base_manifest["layers"]:
        key = "blobs/sha256/" + desc["digest"][7:]
        keep[key] = members[key]
    for body in (manifest_body, config_body, layer_body):
        keep["blobs/sha256/" + sha(body)] = body
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    archive = archive_bytes(keep)
    write_new(output / "backend-image.oci.tar.gz", archive)
    write_new(output / "moments_release.py", operator)
    base_app_tree = {
        **{key.removeprefix("backend/app/"): sha(body) for key, body in old.items()},
        **{
            path: cast(str, item["runtime_sha256"])
            for path, item in PRESERVED_BASE_FILES.items()
        },
    }
    candidate = {
        "version": VERSION,
        "revision": revision,
        "base_revision": BASE_REVISION,
        "base_image": BASE_REF,
        "base_archive_sha256": BASE_ARCHIVE_SHA,
        "schema": SCHEMA,
        "candidate_ref": REPOSITORY + "@" + image_id,
        "candidate_tag": tag,
        "manifest_digest": image_id,
        "config_digest": "sha256:" + sha(config_body),
        "archive_sha256": sha(archive),
        "operator_sha256": sha(operator),
        "base_layers": base_manifest["layers"],
        "base_manifest": base_manifest,
        "base_config": base_config,
        "base_config_sha256": sha(canonical(base_config)),
        "files": {
            key.removeprefix("backend/app/"): sha(body) for key, body in overlay.items()
        },
        "base_app_tree": base_app_tree,
        "notice_revision": NOTICE_REVISION,
        "notice_image_id": NOTICE_IMAGE_ID,
        "notice_image_tag": NOTICE_IMAGE_TAG,
        "notice_app_tree": notice_tree(base_app_tree),
        "candidate_app_tree": {
            **{
                key.removeprefix("backend/app/"): sha(body) for key, body in new.items()
            },
            **{
                path: item["runtime_sha256"]
                for path, item in PRESERVED_BASE_FILES.items()
            },
        },
        "preserved_base_files": copy.deepcopy(PRESERVED_BASE_FILES),
        "app_allowlist": sorted(ALLOWED_APP_FILES),
        "immutable_runtime_tree": {
            key.removeprefix("backend/"): sha(body) for key, body in immutable.items()
        },
        "migration_executed": False,
        "standard_release_provenance": "incomplete",
    }
    write_new(output / "candidate.json", canonical(candidate))
    validate_bundle(output / "candidate.json", sha(canonical(candidate)))
    return candidate


def bound_json(path: Path, expected: str) -> dict[str, Any]:
    require(re.fullmatch(r"[0-9a-f]{64}", expected), "expected_hash")
    body = read_file(path)
    require(sha(body) == expected, "bound_json_hash")
    result = strict_json(body)
    require(isinstance(result, dict), "bound_json_shape")
    return cast(dict[str, Any], result)


def validate_bundle(path: Path, expected: str) -> dict[str, Any]:
    value = bound_json(path, expected)
    require(
        value["version"] == VERSION
        and value["base_revision"] == BASE_REVISION
        and value["base_image"] == BASE_REF
        and value["base_archive_sha256"] == BASE_ARCHIVE_SHA
        and value.get("notice_revision") == NOTICE_REVISION
        and value.get("notice_image_id") == NOTICE_IMAGE_ID
        and value.get("notice_image_tag") == NOTICE_IMAGE_TAG
        and value["schema"] == SCHEMA,
        "candidate_fixed_base",
    )
    require(
        value["migration_executed"] is False
        and value["standard_release_provenance"] == "incomplete",
        "candidate_provenance",
    )
    require(
        sha(read_file(path.parent / "moments_release.py"))
        == value["operator_sha256"]
        == sha(read_file(Path(__file__).resolve())),
        "operator_hash",
    )
    archive = path.parent / "backend-image.oci.tar.gz"
    require(
        sha(read_file(archive)) == value["archive_sha256"], "candidate_archive_hash"
    )
    members = archive_members(archive)
    require(
        re.fullmatch(r"[0-9a-f]{40}", value["revision"])
        and value["candidate_tag"] == REPOSITORY + ":moments-" + value["revision"][:12],
        "candidate_tag",
    )
    manifest, config, image_id = oci_graph(members, expected_tag=value["candidate_tag"])
    require(
        image_id == value["manifest_digest"]
        and value["candidate_ref"] == REPOSITORY + "@" + image_id
        and manifest["config"]["digest"] == value["config_digest"],
        "candidate_identity",
    )
    require(manifest["layers"][:-1] == value["base_layers"], "candidate_base_layers")
    require(
        "sha256:" + sha(canonical(value["base_manifest"])) == BASE_ID
        and "sha256:" + sha(canonical(value["base_config"]))
        == value["base_manifest"]["config"]["digest"]
        and value["base_layers"] == value["base_manifest"]["layers"],
        "bound_base_graph",
    )
    require(
        canonical(value.get("preserved_base_files")) == canonical(PRESERVED_BASE_FILES),
        "preserved_base_contract",
    )
    preserved_base_hashes(members, value["base_manifest"])
    expected_config = copy.deepcopy(value["base_config"])
    expected_config["config"]["Labels"].update(
        {
            "org.opencontainers.image.revision": value["revision"],
            "edu.ai.overlay.base": BASE_ID,
            "edu.ai.change": VERSION,
        }
    )
    expected_config["rootfs"]["diff_ids"].append(config["rootfs"]["diff_ids"][-1])
    expected_config["history"].append(
        {"created_by": "COPY committed reviewed R13 Moments copy app blobs"}
    )
    require(config == expected_config, "candidate_config_drift")
    labels = config["config"]["Labels"]
    require(
        labels["org.opencontainers.image.revision"] == value["revision"]
        and labels["edu.ai.overlay.base"] == BASE_ID
        and labels["edu.ai.change"] == VERSION,
        "candidate_labels",
    )
    # Base runtime comparison is performed again against the real loaded base image.
    layer_desc = manifest["layers"][-1]
    overlay = bounded_gunzip(
        members["blobs/sha256/" + layer_desc["digest"][7:]], 32 * 1024 * 1024
    )
    actual = {}
    with tarfile.open(fileobj=io.BytesIO(overlay), mode="r:") as layer:
        for entry in layer:
            require(
                entry.isfile()
                and entry.name.startswith("app/app/")
                and entry.mode == 0o644
                and entry.uid == entry.gid == 999,
                "overlay_entry",
            )
            relative = safe_relative(entry.name.removeprefix("app/app/"))
            require(relative not in actual, "overlay_duplicate")
            stream = layer.extractfile(entry)
            require(stream is not None, "overlay_stream")
            actual[relative] = sha(stream.read())  # type: ignore[union-attr]
    require(actual == value["files"], "overlay_files")
    require(
        {"backend/app/" + path for path in actual} == ALLOWED_APP_FILES,
        "app_overlay_allowlist",
    )
    require(
        value.get("app_allowlist") == sorted(ALLOWED_APP_FILES),
        "app_allowlist_manifest",
    )
    for relative, preserved in PRESERVED_BASE_FILES.items():
        require(
            relative not in actual
            and value["base_app_tree"].get(relative)
            == value["candidate_app_tree"].get(relative)
            == preserved["runtime_sha256"],
            "preserved_base_projection",
        )
    require(
        {**value["base_app_tree"], **actual} == value["candidate_app_tree"],
        "full_app_projection",
    )
    require(
        value.get("notice_app_tree") == notice_tree(value["base_app_tree"])
        and all(
            value["files"].get(path) == digest
            for path, digest in NOTICE_APP_HASHES.items()
        ),
        "notice_candidate_projection",
    )
    return value


def env_values(body: bytes) -> dict[str, str]:
    result = {}
    for line in body.decode().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        require("=" in line and not line.startswith("export "), "environment_syntax")
        key, value = line.split("=", 1)
        require(
            key not in result and re.fullmatch(r"[A-Z][A-Z0-9_]*", key),
            "environment_key",
        )
        result[key] = value.strip().strip("\"'")
    return result


def change_env(body: bytes, key: str, before: str, after: str) -> bytes:
    require(env_values(body).get(key) == before, "environment_value")
    lines = body.splitlines(keepends=True)
    matches = [
        i for i, line in enumerate(lines) if line.startswith((key + "=").encode())
    ]
    require(len(matches) == 1, "environment_key_count")
    index = matches[0]
    ending = (
        b"\r\n"
        if lines[index].endswith(b"\r\n")
        else b"\n"
        if lines[index].endswith(b"\n")
        else b""
    )
    lines[index] = (key + "=" + after).encode() + ending
    result = b"".join(lines)
    require(
        {k: v for k, v in env_values(body).items() if k != key}
        == {k: v for k, v in env_values(result).items() if k != key},
        "protected_environment_changed",
    )
    return result


def tree_manifest(
    root: Path, *, minio_business: bool = False, brand_data: bool = False
) -> dict[str, Any]:
    physical(root)
    require(root.is_dir(), "tree_root")
    result = {}
    for path in sorted(root.rglob("*")):
        if minio_business and path.relative_to(root).parts[0] == ".minio.sys":
            continue
        require(not path.is_symlink(), "tree_symlink")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = (
                brand_metadata(path) if brand_data else metadata(path)
            )
        else:
            require(path.is_dir(), "tree_entry_type")
    return result


def next_window(now: datetime) -> dict[str, str]:
    now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    for delta in range(8):
        day = now.date() + timedelta(days=delta)
        prepare = datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo).replace(
            hour=9
        )
        if day.weekday() in (0, 2, 4) and prepare > now:
            return {
                "prepare_at": prepare.isoformat(),
                "upload_at": prepare.replace(hour=10).isoformat(),
                "expires_at": prepare.replace(hour=16).isoformat(),
            }
    raise RuntimeError("next_window")


def runtime_source_manifest() -> dict[str, Any]:
    return {
        name: tree_manifest(APP / name)
        for name in ("backend", "deploy", "scripts", "infra")
    }


def volume_fingerprints(volumes: dict[str, str]) -> dict[str, str]:
    return {
        name: sha(
            canonical(
                tree_manifest(
                    Path(root), minio_business=name == "edu-ai-lead-agent_minio_data"
                )
            )
        )
        for name, root in volumes.items()
    }


def normalized_mounts(mounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Docker does not promise Mounts ordering; preserve every projected field."""
    result = []
    destinations: set[str] = set()
    for mount in mounts:
        item = {
            key: mount.get(key)
            for key in ("Type", "Name", "Source", "Destination", "RW")
        }
        destination = item["Destination"]
        require(isinstance(destination, str) and bool(destination), "mount_destination")
        assert isinstance(destination, str)
        require(destination not in destinations, "duplicate_mount_destination")
        require(type(item["RW"]) is bool, "mount_rw_type")
        destinations.add(destination)
        result.append(item)
    return sorted(result, key=canonical)


def check_application_mounts(mounts: list[dict[str, Any]]) -> None:
    """A bind or volume must not shadow code verified inside the OCI image."""
    directories = ("/app/app", "/app/alembic")
    files = ("/app/alembic.ini", "/app/pyproject.toml")
    for mount in mounts:
        destination = mount["Destination"].rstrip("/")
        require(
            not any(
                destination == path
                or path.startswith(destination + "/")
                or destination.startswith(path + "/")
                for path in directories
            )
            and not any(
                destination == path or path.startswith(destination + "/")
                for path in files
            ),
            "application_mount_shadow",
        )


def standard_release_markers_absent() -> dict[str, bool]:
    return {name: not os.path.lexists(name) for name in STANDARD_RELEASE_MARKERS}


def check_backup_space(baseline: dict[str, Any]) -> None:
    """Leave room for a full logical dump and the uncompressed backup inputs."""
    postgres_mounts = [
        mount
        for mount in baseline["services"]["postgres"]["mounts"]
        if mount["Type"] == "volume"
        and mount["Name"] == "edu-ai-lead-agent_postgres_data"
    ]
    require(len(postgres_mounts) == 1, "postgres_backup_source")
    sources = [
        Path(postgres_mounts[0]["Source"]),
        *(Path(root) for root in baseline["volumes"].values()),
        APP / "private/brand-materials",
        *(APP / name for name in ("backend", "deploy", "scripts", "infra")),
    ]
    size = 0
    for root in sources:
        physical(root)
        require(root.is_dir(), "backup_source_missing")
        for path in root.rglob("*"):
            info = path.lstat()
            require(
                stat.S_ISREG(info.st_mode)
                or stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode),
                "backup_source_type",
            )
            if not stat.S_ISDIR(info.st_mode):
                size += info.st_size
    # Compression usually helps, but never rely on it when reserving space.
    required = size * 3 // 2 + 512 * 1024 * 1024
    require(shutil.disk_usage(BACKUP_ROOT).free >= required, "backup_space")


def check_service_environment(
    name: str, item: dict[str, Any], config: dict[str, Any], policy: str
) -> dict[str, str]:
    env: dict[str, str] = {}
    for pair in item["Config"]["Env"]:
        key, value = pair.split("=", 1)
        require(key not in env, "duplicate_container_env")
        env[key] = value
    rendered = config["environment"]
    for key, value in rendered.items():
        expected = str(value).lower() if isinstance(value, bool) else str(value)
        require(env.get(key) == expected, "container_environment_drift")
    require(item["Config"]["Cmd"] == config["command"], "container_command_drift")
    required = {"APP_ENV": "production", "BUSINESS_TIMEZONE": "Asia/Shanghai"}
    if name in SINGLE_SERVICES:
        required.update(
            {
                "OFFICIAL_ACCOUNT_SINGLE_ENABLED": "true",
                "OFFICIAL_ACCOUNT_SINGLE_MIN_DATE": "2026-09-16",
                "OFFICIAL_ACCOUNT_SINGLE_PREPARE_MINUTES": "60",
                "OFFICIAL_ACCOUNT_SINGLE_CATCHUP_HOURS": "6",
                "OFFICIAL_ACCOUNT_SINGLE_MAX_ATTEMPTS": "3",
            }
        )
        require(
            re.fullmatch(
                r"[0-9a-f]{64}",
                env.get("OFFICIAL_ACCOUNT_SINGLE_ACCOUNT_FINGERPRINT", ""),
            ),
            "single_account_missing",
        )
    if name in (
        "official-account-weekly-dag-worker",
        "official-account-weekly-scheduler",
    ):
        required.update(
            {
                POLICY_KEY: policy,
                "OFFICIAL_ACCOUNT_WEEKLY_SCHEDULER_ENABLED": "false",
                "OFFICIAL_ACCOUNT_WEEKLY_WORKER_ENABLED": "false",
                "OFFICIAL_ACCOUNT_LOCAL_ENABLED": "true",
                "OFFICIAL_ACCOUNT_LOCAL_WORKER_ENABLED": "true",
                "OFFICIAL_ACCOUNT_WEEKLY_PRODUCTION_ENABLED": "true",
            }
        )
    if name == "official-account-local-worker":
        required.update(
            {
                POLICY_KEY: policy,
                "IMAGE_MAX_ATTEMPTS": "1",
                "OFFICIAL_ACCOUNT_LOCAL_ENABLED": "true",
                "OFFICIAL_ACCOUNT_LOCAL_WORKER_ENABLED": "true",
            }
        )
    if name == "wechat-official-account-draft-worker":
        required.update(
            {
                "WECHAT_MP_MODE": "draft_only",
                "WECHAT_MP_ENABLED": "true",
                "WECHAT_MP_DRAFT_WORKER_ENABLED": "true",
                "WECHAT_MP_DRAFT_PRODUCTION_ENABLED": "true",
                "WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED": "false",
            }
        )
    for key, expected in required.items():
        require(env.get(key) == expected, "required_runtime_flag")
    for key, expected in FLAGS.items():
        if key in env:
            require(env[key] == expected, "runtime_flag")
    if POLICY_KEY in env:
        require(env[POLICY_KEY] == policy, "runtime_visual_policy")
    return env


class Host:
    def compose(self, *args: str, **kwargs: Any) -> bytes:
        argv = [
            "docker",
            "compose",
            "--project-name",
            "edu-ai-lead-agent",
            "-f",
            str(APP / "compose.yaml"),
            "--env-file",
            str(APP / ".env"),
            "--env-file",
            str(APP / ".release.env"),
        ]
        for profile in PROFILES:
            argv += ["--profile", profile]
        return run([*argv, *args], cwd=APP, **kwargs)

    def inspect(self, name: str, *, image: bool = False) -> dict[str, Any]:
        values = strict_json(
            run(["docker", *(["image"] if image else []), "inspect", name])
        )
        require(len(values) == 1, "inspect_count")
        return cast(dict[str, Any], values[0])

    def service(self, name: str) -> dict[str, Any]:
        ids = self.compose("ps", "-a", "-q", name).decode().split()
        require(
            len(ids) == 1 and re.fullmatch(r"[0-9a-f]{12,64}", ids[0]), "service_count"
        )
        return self.inspect(ids[0])

    def scalar(self, sql: str) -> str:
        require(sql.startswith("SELECT "), "readonly_sql_only")
        return (
            self.compose(
                "exec",
                "-T",
                "postgres",
                "sh",
                "-c",
                'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"',
                "sh",
                sql,
            )
            .decode()
            .strip()
        )

    def app_tree(
        self, image: str, *, running: bool = False, probe: str = APP_PROBE
    ) -> dict[str, str]:
        argv = (
            ["docker", "exec", image]
            if running
            else [
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--entrypoint",
                "python",
                image,
            ]
        )
        if running:
            argv.append("python")
        return cast(dict[str, str], strict_json(run([*argv, "-B", "-c", probe])))

    def copy_identity(self, target: str, *, running: bool = True) -> dict[str, Any]:
        argv = (
            ["docker", "exec", target, "python"]
            if running
            else [
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--entrypoint",
                "python",
                target,
            ]
        )
        return cast(dict[str, Any], strict_json(run([*argv, "-B", "-c", COPY_PROBE])))

    def brand_identity(self) -> dict[str, Any]:
        result = strict_json(
            self.scalar(
                "SELECT json_build_object("
                "'active_count',count(*) FILTER (WHERE d.active_version_id IS NOT NULL),"
                "'wrong_provider',count(*) FILTER (WHERE d.active_version_id IS NOT NULL AND "
                "(v.embedding_provider <> 'zhipu' OR v.embedding_model <> 'embedding-3' "
                "OR v.embedding_dimensions <> 2048 OR v.status <> 'ready' OR v.active IS NOT TRUE)),"
                "'legacy_fake_count',count(*) FILTER (WHERE d.active_version_id IS NOT NULL "
                "AND v.embedding_provider='fake'),"
                "'legacy_fake_sha256',(SELECT encode(sha256(convert_to(jsonb_build_object("
                "'document_id',fd.id,'version_id',fv.id,'document_key',fd.document_key,"
                "'title',fd.title,'document_kind',fd.document_kind,'audience',fd.audience,"
                "'document_status',fd.status,'provider',fv.embedding_provider,"
                "'model',fv.embedding_model,'dimensions',fv.embedding_dimensions,"
                "'version_status',fv.status,'active',fv.active,'source_sha256',fv.sha256)"
                "::text,'UTF8')),'hex') FROM brand_documents fd "
                "JOIN brand_document_versions fv ON fv.id=fd.active_version_id "
                "WHERE fv.embedding_provider='fake'),"
                "'sha256',encode(sha256(convert_to(COALESCE(jsonb_agg(jsonb_build_object("
                "'document_id',d.id,'active_version_id',d.active_version_id,'status',d.status,"
                "'provider',v.embedding_provider,'model',v.embedding_model,'dimensions',v.embedding_dimensions,"
                "'parser',v.parser_version,'chunk',v.chunk_version,'input',v.embedding_input_version) "
                "ORDER BY d.id),'[]'::jsonb)::text,'UTF8')),'hex'))::text "
                "FROM brand_documents d LEFT JOIN brand_document_versions v ON v.id=d.active_version_id"
            ).encode()
        )
        require(
            isinstance(result, dict)
            and type(result.get("active_count")) is int
            and result["active_count"] >= 4
            and result.get("wrong_provider") == 1
            and result.get("legacy_fake_count") == 1
            and result.get("legacy_fake_sha256") == LEGACY_FAKE_BRAND_SHA
            and re.fullmatch(r"[0-9a-f]{64}", result.get("sha256", "")),
            "brand_identity",
        )
        return cast(dict[str, Any], result)

    def db_snapshot(self) -> dict[str, Any]:
        require(
            self.scalar("SELECT version_num FROM alembic_version") == SCHEMA,
            "live_schema",
        )
        names = self.scalar(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND "
            "(tablename LIKE 'official_account_%' OR tablename LIKE 'wechat_mp_%') ORDER BY tablename"
        ).splitlines()
        require(
            {
                "official_account_single_editions",
                "official_account_draft_owners",
                "official_account_article_versions",
                "official_account_render_versions",
                "official_account_generated_visuals",
                "official_account_article_attempts",
                "wechat_mp_draft_jobs",
            }
            <= set(names),
            "history_tables_missing",
        )
        result = {}
        protected_tables = [
            *names,
            *self.scalar(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename LIKE 'copy_generation_%' ORDER BY tablename"
            ).splitlines(),
        ]
        require(
            {"copy_generation_runs", "copy_generation_jobs", "copy_generation_attempts"}
            <= set(protected_tables),
            "copy_tables_missing",
        )
        for table in protected_tables:
            require(
                re.fullmatch(
                    r"(?:official_account|wechat_mp|copy_generation)_[a-z_]+", table
                ),
                "table_name",
            )
            result[table] = self.scalar(
                "SELECT json_build_object('count',count(*),'sha256',encode(sha256(convert_to("
                "COALESCE(jsonb_agg(v ORDER BY v::text),'[]'::jsonb)::text,'UTF8')),'hex'))::text "
                f"FROM (SELECT to_jsonb(t)-'updated_at' AS v FROM {table} t) q"
            )
        result["historical_preview_copy_jobs"] = self.scalar(
            "SELECT encode(sha256(convert_to(COALESCE(jsonb_agg(jsonb_build_object('job',to_jsonb(j)-'updated_at',"
            "'run',to_jsonb(r)-'updated_at') ORDER BY j.id),'[]'::jsonb)::text,'UTF8')),'hex') "
            "FROM copy_generation_jobs j JOIN copy_generation_runs r ON r.id=j.run_id WHERE j.status='queued' AND r.scoring_profile='preview'"
        )
        require(
            result["historical_preview_copy_jobs"] == HISTORICAL_COPY_COHORT_SHA,
            "historical_copy_cohort_drift",
        )
        return result

    def idle(self) -> None:
        tables = self.scalar(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND "
            "(tablename LIKE '%_jobs' OR tablename IN ('official_account_single_editions',"
            "'official_account_article_runs','official_account_weekly_dag_runs')) ORDER BY tablename"
        ).splitlines()
        require(tables, "job_tables_missing")
        for table in tables:
            require(re.fullmatch(r"[a-z_]+", table), "table_name")
            historical_exclusion = ""
            if table == "official_account_article_runs":
                # This model has no expires_at. Only these five independently
                # measured terminal rows are exempt, never a new unknown result.
                cutoff = HISTORICAL_ARTICLE_UNKNOWN_CUTOFF
                summary = strict_json(
                    self.scalar(
                        "SELECT json_build_object('count',count(*),'eligible',count(*) FILTER (WHERE "
                        f"created_at < TIMESTAMPTZ '{cutoff}' AND updated_at < TIMESTAMPTZ '{cutoff}' "
                        "AND lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL),"
                        "'sha256',encode(sha256(convert_to(COALESCE(jsonb_agg(to_jsonb(t)-'updated_at' "
                        "ORDER BY id),'[]'::jsonb)::text,'UTF8')),'hex'))::text "
                        "FROM official_account_article_runs t WHERE status='result_unknown'"
                    ).encode()
                )
                require(
                    isinstance(summary, dict)
                    and set(summary) == {"count", "eligible", "sha256"}
                    and type(summary["count"]) is int
                    and type(summary["eligible"]) is int
                    and summary["count"] == summary["eligible"] == 5
                    and summary["sha256"] == HISTORICAL_ARTICLE_UNKNOWN_SHA,
                    "historical_article_unknown_cohort_drift",
                )
                historical_exclusion = (
                    " AND NOT (v->>'status'='result_unknown' "
                    f"AND (v->>'created_at')::timestamptz < TIMESTAMPTZ '{cutoff}' "
                    f"AND (v->>'updated_at')::timestamptz < TIMESTAMPTZ '{cutoff}' "
                    "AND v->>'lease_owner' IS NULL AND v->>'lease_token' IS NULL "
                    "AND v->>'lease_expires_at' IS NULL)"
                )
            # An expired historical unknown is immutable history, not live work.
            count = self.scalar(
                "SELECT count(*) FROM (SELECT to_jsonb(t) AS v FROM "
                + table
                + " t) q WHERE "
                "v->>'status'='running' OR v->>'lease_token' IS NOT NULL OR v->>'lease_owner' IS NOT NULL OR "
                "v->>'lease_expires_at' IS NOT NULL OR "
                "(v->>'status' IN ('outcome_unknown','delivery_unknown','result_unknown') AND "
                "(v->>'expires_at' IS NULL OR (v->>'expires_at')::timestamptz > now())"
                + historical_exclusion
                + ")"
            )
            require(count == "0", "active_or_unknown_work")
            if table == "copy_generation_jobs":
                dates = ",".join("'" + day + "'" for day in HISTORICAL_COPY_DATES)
                require(
                    self.scalar(
                        "SELECT count(*) FROM copy_generation_jobs j JOIN copy_generation_runs r ON r.id=j.run_id "
                        "WHERE j.status='queued' AND j.attempt_count=0 AND r.scoring_profile='preview' "
                        f"AND r.business_date IN ({dates})"
                    )
                    == "7",
                    "historical_copy_cohort",
                )
                exclusion = (
                    " AND NOT EXISTS (SELECT 1 FROM copy_generation_runs r WHERE r.id=t.run_id AND r.scoring_profile='preview' "
                    + f"AND r.business_date IN ({dates}) AND t.attempt_count=0)"
                )
            else:
                exclusion = ""
            # No pending work, including future entries, may be activated during this narrow release.
            pending_statuses: tuple[str, ...] = (
                "queued",
                "pending",
                "retry_scheduled",
                "retryable_failed",
                "admitted",
                "generating",
                "preparing",
                "ready",
                "delivering",
                "partial",
            )
            # For WeChat jobs, _finish_job_ready is successful completion, not
            # waiting-to-send. Its claimable states are queued/retryable_failed.
            if table == "wechat_mp_draft_jobs":
                pending_statuses = tuple(
                    value for value in pending_statuses if value != "ready"
                )
            # Ready article_runs are immutable content, not a runnable job queue.
            if table in (
                "official_account_article_runs",
                "official_account_weekly_dag_runs",
            ):
                pending_statuses = (
                    "queued",
                    "running",
                    "retry_scheduled",
                    "retryable_failed",
                )
            pending = self.scalar(
                "SELECT count(*) FROM "
                + table
                + " t WHERE to_jsonb(t)->>'status' IN ("
                + ",".join("'" + value + "'" for value in pending_statuses)
                + ")"
                + exclusion
            )
            require(pending == "0", "pending_work")

    def capture(self, manifest: dict[str, Any]) -> dict[str, Any]:
        require(os.geteuid() == 0, "root_required")
        require(
            all(standard_release_markers_absent().values()),
            "standard_release_path_changed",
        )
        files = {name: metadata(APP / name) for name in PROTECTED_FILES}
        require(
            all(
                type(files[name][key]) is int and files[name][key] == value
                for name, expected in PROTECTED_METADATA.items()
                for key, value in expected.items()
            ),
            "protected_metadata_policy",
        )
        require(
            files[".env"]["mode"] == files[".release.env"]["mode"] == 0o600,
            "environment_mode",
        )
        for marker in (".release-commit", "RELEASE_COMMIT"):
            require(
                read_file(APP / marker).decode().strip() == BASE_REVISION,
                "baseline_revision",
            )
        env = env_values(read_file(APP / ".env"))
        release = env_values(read_file(APP / ".release.env"))
        require(
            release.get("APP_IMAGE") == BASE_REF and env.get(POLICY_KEY) == PROD_POLICY,
            "baseline_environment",
        )
        require(
            not any(
                key.startswith("COPY_") and key.endswith("_VERSION")
                for key in (*env, *release)
            ),
            "copy_version_override",
        )
        base = self.inspect(BASE_REF, image=True)
        require(
            base["Id"] == BASE_ID
            and base["Config"]["Labels"]["org.opencontainers.image.revision"]
            == BASE_REVISION,
            "baseline_image",
        )
        notice = self.inspect(NOTICE_IMAGE_TAG, image=True)
        check_notice_image(base, notice)
        config = strict_json(self.compose("config", "--format", "json"))
        services = {}
        volumes = {}
        for name in (*SERVICES, "postgres", "minio"):
            item = self.service(name)
            require(
                item["State"]["Status"] == "running"
                and item["State"].get("Health", {}).get("Status", "healthy")
                == "healthy"
                and item["RestartCount"] == 0,
                "baseline_service_health",
            )
            if name in SERVICES:
                check_baseline_service_image(
                    name, item, config["services"][name]["image"]
                )
                actual_env = check_service_environment(
                    name, item, config["services"][name], PROD_POLICY
                )
            mounts = normalized_mounts(item["Mounts"])
            if name in SERVICES:
                check_application_mounts(mounts)
            services[name] = {
                "id": item["Id"],
                "image": item["Image"],
                "mounts": mounts,
            }
            if name in SERVICES:
                services[name].update(
                    {
                        "config_image": item["Config"]["Image"],
                        "env_sha256": sha(canonical(actual_env)),
                        "command": item["Config"]["Cmd"],
                    }
                )
            if name in BRAND_SERVICES:
                require(
                    any(
                        mount["Type"] == "bind"
                        and mount["Source"] == str(APP / "private/brand-materials")
                        and mount["Destination"] == "/app/private/brand-materials"
                        and mount["RW"] is False
                        for mount in mounts
                    ),
                    "brand_mount",
                )
            for mount in mounts:
                if (
                    mount["Type"] == "volume"
                    and mount["Name"] != "edu-ai-lead-agent_postgres_data"
                ):
                    require(
                        re.fullmatch(r"edu-ai-lead-agent_[a-z_]+", mount["Name"]),
                        "volume_name",
                    )
                    volume = strict_json(
                        run(["docker", "volume", "inspect", mount["Name"]])
                    )[0]
                    require(
                        volume["Name"] == mount["Name"]
                        and volume["Mountpoint"] == mount["Source"],
                        "volume_identity",
                    )
                    volumes[mount["Name"]] = mount["Source"]
        require(
            set(volumes)
            == {
                "edu-ai-lead-agent_minio_data",
                "edu-ai-lead-agent_wechat_mp_draft_artifacts",
                "edu-ai-lead-agent_official_account_weekly_dag_output",
            },
            "backup_volumes_missing",
        )
        require(
            self.app_tree(services["acquisition-api"]["id"], running=True)
            == manifest["base_app_tree"],
            "base_app_tree",
        )
        check_notice_app_tree(
            self.app_tree(services[NOTICE_SERVICE]["id"], running=True),
            manifest["notice_app_tree"],
        )
        require(
            self.app_tree(
                services["acquisition-api"]["id"], running=True, probe=RUNTIME_PROBE
            )
            == manifest["immutable_runtime_tree"],
            "immutable_runtime_tree",
        )
        require(
            self.app_tree(
                services[NOTICE_SERVICE]["id"], running=True, probe=RUNTIME_PROBE
            )
            == manifest["immutable_runtime_tree"],
            "notice_immutable_runtime_tree",
        )
        copy_identity = self.copy_identity(services["acquisition-api"]["id"])
        require(
            {key: copy_identity.get(key) for key in BASE_COPY_VERSIONS}
            == BASE_COPY_VERSIONS
            and {
                key: copy_identity.get(key)
                for key in (
                    "brand_embedding_provider",
                    "brand_embedding_model",
                    "brand_embedding_dimensions",
                )
            }
            == {
                "brand_embedding_provider": "zhipu",
                "brand_embedding_model": "embedding-3",
                "brand_embedding_dimensions": 2048,
            },
            "baseline_copy_provider_identity",
        )
        self.idle()
        journal = tree_manifest(
            Path(volumes["edu-ai-lead-agent_wechat_mp_draft_artifacts"])
        )
        health = strict_json(
            run(
                [
                    "curl",
                    "--fail",
                    "--silent",
                    "--max-time",
                    "5",
                    "--max-filesize",
                    "65536",
                    "http://127.0.0.1:8000/healthz",
                ]
            )
        )
        require(
            health.get("status") == "ok" and health.get("environment") == "production",
            "api_health",
        )
        require(
            run(["systemctl", "is-active", "edu-ai-backup.timer"]).strip() == b"active",
            "backup_timer",
        )
        return {
            "version": VERSION,
            "revision": BASE_REVISION,
            "image": BASE_ID,
            "schema": SCHEMA,
            "files": files,
            "services": services,
            "volumes": volumes,
            "volume_fingerprints": volume_fingerprints(volumes),
            "runtime_source_manifest": runtime_source_manifest(),
            "db": self.db_snapshot(),
            "brand_identity": self.brand_identity(),
            "copy_identity": copy_identity,
            "journal_sha256": sha(canonical(journal)),
            "brand_sha256": sha(
                canonical(
                    tree_manifest(APP / "private/brand-materials", brand_data=True)
                )
            ),
            "standard_markers_absent": standard_release_markers_absent(),
            "compose_sha256": sha(canonical(config)),
            "schedule_window": next_window(datetime.now(UTC)),
            "captured_at": datetime.now(UTC).isoformat(),
        }


def same_baseline(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    require(
        {k: v for k, v in expected.items() if k != "captured_at"}
        == {k: v for k, v in actual.items() if k != "captured_at"},
        "baseline_drift",
    )


def verify_backup_archive(
    path: Path,
    source: Path,
    before: dict[str, Any],
    *,
    minio_business: bool = False,
    brand_data: bool = False,
) -> None:
    actual = {}
    with tarfile.open(path, "r:gz") as archive:
        for entry in archive:
            if entry.isdir():
                continue
            require(entry.isfile(), "backup_entry_type")
            name = entry.name.removeprefix("./")
            # User-owned brand/object names may contain spaces or Unicode. They
            # are not OCI/source-manifest records and must not inherit the
            # stricter ASCII-safe source-path rule.
            relative = PurePosixPath(name)
            require(
                bool(name)
                and not relative.is_absolute()
                and ".." not in relative.parts
                and str(relative) == name
                and not any(ord(char) < 32 or ord(char) == 127 for char in name),
                "unsafe_backup_path",
            )
            if minio_business and PurePosixPath(name).parts[0] == ".minio.sys":
                continue
            require(name not in actual, "backup_duplicate")
            stream = archive.extractfile(entry)
            require(stream is not None, "backup_stream")
            assert stream is not None
            actual[name] = {
                "sha256": sha(stream.read()),
                "size": entry.size,
                "mode": entry.mode,
                "uid": entry.uid,
                "gid": entry.gid,
            }
    require(
        actual
        == before
        == tree_manifest(source, minio_business=minio_business, brand_data=brand_data),
        "backup_source_changed",
    )


class Deployment:
    def __init__(
        self,
        host: Host,
        manifest_path: Path,
        manifest: dict[str, Any],
        baseline: dict[str, Any],
    ):
        self.host, self.manifest_path, self.manifest, self.baseline = (
            host,
            manifest_path,
            manifest,
            baseline,
        )
        self.backup_dir = BACKUP_ROOT / ("moments-" + manifest["revision"][:12])
        self.activated = False
        self.loaded_id: str | None = None

    def log(self, phase: str) -> None:
        print(json.dumps({"phase": phase, "operator": VERSION}), flush=True)

    def plan(self) -> None:
        require(not self.backup_dir.exists(), "attempt_already_exists_reconcile_only")
        details = BACKUP_ROOT.stat()
        physical(BACKUP_ROOT)
        require(
            stat.S_ISDIR(details.st_mode)
            and details.st_uid == details.st_gid == 0
            and stat.S_IMODE(details.st_mode) == 0o700,
            "backup_root_permissions",
        )
        same_baseline(self.baseline, self.host.capture(self.manifest))
        age = datetime.now(UTC) - datetime.fromisoformat(self.baseline["captured_at"])
        require(timedelta(0) <= age < timedelta(hours=2), "baseline_expired")
        require(
            datetime.fromisoformat(next_window(datetime.now(UTC))["prepare_at"])
            - datetime.now(UTC)
            > timedelta(minutes=20),
            "schedule_too_near",
        )
        require(
            self.baseline["schedule_window"] == next_window(datetime.now(UTC)),
            "schedule_changed",
        )
        check_backup_space(self.baseline)

    def load(self) -> None:
        image_rows = run(
            ["docker", "image", "ls", "--all", "--no-trunc", "--format", "{{json .}}"]
        ).splitlines()
        for row in image_rows:
            item = strict_json(row)
            if item["Repository"] + ":" + item["Tag"] == self.manifest["candidate_tag"]:
                require(
                    item["ID"]
                    in (
                        self.manifest["manifest_digest"],
                        self.manifest["config_digest"],
                    ),
                    "candidate_tag_already_owned",
                )
        run(
            [
                "docker",
                "load",
                "-i",
                str(self.manifest_path.parent / "backend-image.oci.tar.gz"),
            ],
            timeout=300,
        )
        image = self.host.inspect(self.manifest["candidate_ref"], image=True)
        tag = self.host.inspect(self.manifest["candidate_tag"], image=True)
        require(
            image["Id"] == tag["Id"]
            and image["Id"]
            in (self.manifest["manifest_digest"], self.manifest["config_digest"]),
            "loaded_image_identity",
        )
        require(
            self.manifest["candidate_ref"] in image.get("RepoDigests", []),
            "loaded_repo_digest",
        )
        base = self.host.inspect(BASE_REF, image=True)
        require(
            {key: value for key, value in base["Config"].items() if key != "Labels"}
            == {
                key: value for key, value in image["Config"].items() if key != "Labels"
            },
            "runtime_config_changed",
        )
        require(
            image["RootFS"]["Layers"][:-1] == base["RootFS"]["Layers"],
            "loaded_base_layers",
        )
        require(
            image["Config"]["Labels"]["org.opencontainers.image.revision"]
            == self.manifest["revision"],
            "loaded_revision",
        )
        require(
            self.host.app_tree(self.manifest["candidate_ref"])
            == self.manifest["candidate_app_tree"],
            "candidate_full_app_tree",
        )
        require(
            self.host.app_tree(self.manifest["candidate_ref"], probe=RUNTIME_PROBE)
            == self.manifest["immutable_runtime_tree"],
            "candidate_runtime_probe",
        )
        self.loaded_id = image["Id"]

    def backup(self) -> None:
        self.backup_dir.mkdir(mode=0o700, exist_ok=False)
        write_new(self.backup_dir / "baseline.json", canonical(self.baseline))
        write_new(self.backup_dir / "candidate.json", canonical(self.manifest))
        dump = self.backup_dir / "postgres.dump"
        with dump.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            self.host.compose(
                "exec",
                "-T",
                "postgres",
                "sh",
                "-c",
                'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc',
                output=stream,
                timeout=600,
            )
            stream.flush()
            os.fsync(stream.fileno())
        dump_bytes = read_file(dump)
        require(
            dump_bytes.startswith(b"PGDMP") and len(dump_bytes) > 1024,
            "postgres_dump_empty",
        )
        listing = self.host.compose(
            "exec",
            "-T",
            "postgres",
            "pg_restore",
            "--list",
            input_data=dump_bytes,
            timeout=120,
        )
        require(
            b"TABLE DATA" in listing and b"alembic_version" in listing,
            "postgres_dump_unverified",
        )
        inventory = {"postgres.dump": sha(dump_bytes)}
        # All non-Postgres volumes include MinIO, weekly output and the durable journal.
        for name, root in self.baseline["volumes"].items():
            source = Path(root)
            minio_business = name == "edu-ai-lead-agent_minio_data"
            before = tree_manifest(source, minio_business=minio_business)
            archive = self.backup_dir / (name + ".tar.gz")
            run(
                [
                    "tar",
                    "--create",
                    "--gzip",
                    "--file",
                    str(archive),
                    "--directory",
                    str(source),
                    ".",
                ],
                timeout=600,
                accepted_codes=(0, 1) if minio_business else (0,),
            )
            os.chmod(archive, 0o600)
            verify_backup_archive(
                archive, source, before, minio_business=minio_business
            )
            inventory[archive.name] = sha(read_file(archive))
        brand = APP / "private/brand-materials"
        before = tree_manifest(brand, brand_data=True)
        archive = self.backup_dir / "brand-materials.tar.gz"
        run(
            [
                "tar",
                "--create",
                "--gzip",
                "--file",
                str(archive),
                "--directory",
                str(brand),
                ".",
            ],
            timeout=600,
        )
        os.chmod(archive, 0o600)
        verify_backup_archive(archive, brand, before, brand_data=True)
        inventory[archive.name] = sha(read_file(archive))
        # Runtime source/config snapshot; base image remains immutable and cached.
        runtime_files = {}
        for root_name in ("backend", "deploy", "scripts", "infra"):
            root = APP / root_name
            for relative in tree_manifest(root):
                runtime_files[root_name + "/" + relative] = read_file(root / relative)
        for relative in PROTECTED_FILES:
            runtime_files[relative] = read_file(APP / relative)
        runtime_archive = archive_bytes(runtime_files)
        write_new(self.backup_dir / "runtime-config.tar.gz", runtime_archive)
        inventory["runtime-config.tar.gz"] = sha(runtime_archive)
        require(
            archive_members(self.backup_dir / "runtime-config.tar.gz") == runtime_files,
            "runtime_backup_verify",
        )
        write_new(
            self.backup_dir / "backup-verified.json",
            canonical({"sha256": inventory, "verified": True}),
        )

    def fence_stopped(self) -> None:
        require(
            {name: metadata(APP / name) for name in PROTECTED_FILES}
            == self.baseline["files"],
            "protected_file_drift",
        )
        require(
            self.host.db_snapshot() == self.baseline["db"], "historical_database_drift"
        )
        require(
            self.host.brand_identity() == self.baseline["brand_identity"],
            "active_brand_pointer_or_provider_drift",
        )
        require(
            runtime_source_manifest() == self.baseline["runtime_source_manifest"],
            "runtime_source_drift",
        )
        require(
            volume_fingerprints(self.baseline["volumes"])
            == self.baseline["volume_fingerprints"],
            "business_volume_drift",
        )
        require(
            sha(
                canonical(
                    tree_manifest(APP / "private/brand-materials", brand_data=True)
                )
            )
            == self.baseline["brand_sha256"],
            "brand_drift",
        )
        self.host.idle()
        for name in SERVICES:
            item = self.host.service(name)
            bound = self.baseline["services"][name]
            require(
                item["State"]["Status"] == "exited"
                and item["Id"] == bound["id"]
                and item["Image"] == bound["image"]
                and item["Config"]["Image"] == bound["config_image"]
                and normalized_mounts(item["Mounts"]) == bound["mounts"],
                "writer_not_stopped",
            )
        for name in ("postgres", "minio"):
            require(
                self.host.service(name)["Id"] == self.baseline["services"][name]["id"],
                "dependency_recreated",
            )
        root = Path(
            self.baseline["volumes"]["edu-ai-lead-agent_wechat_mp_draft_artifacts"]
        )
        require(
            sha(canonical(tree_manifest(root))) == self.baseline["journal_sha256"],
            "journal_drift",
        )

    def activate(self) -> None:
        # The intent write itself may fail after creating the file. Once we
        # begin that write, any uncertain outcome must use forward recovery,
        # never the pre-activation old-image restart path.
        self.activated = True
        write_new(
            self.backup_dir / "activation-intent.json",
            canonical(
                {
                    "candidate": self.manifest["candidate_ref"],
                    "old_app_restore_forbidden": True,
                }
            ),
        )
        replacements: dict[str, bytes] = {}
        replacements[".release.env"] = change_env(
            read_file(APP / ".release.env"),
            "APP_IMAGE",
            BASE_REF,
            self.manifest["candidate_ref"],
        )
        for name in (".release-commit", "RELEASE_COMMIT"):
            replacements[name] = (self.manifest["revision"] + "\n").encode()
        for name, body in replacements.items():
            replace_file(APP / name, body, self.baseline["files"][name])

    def start(self) -> None:
        self.host.compose(
            "up",
            "-d",
            "--no-build",
            "--no-deps",
            "--pull",
            "never",
            "--force-recreate",
            *SERVICES,
            timeout=240,
        )

    def verify(self) -> dict[str, Any]:
        require(self.loaded_id is not None, "loaded_id_missing")
        self.host.idle()
        for name in SERVICES:
            item = self.host.service(name)
            require(
                item["Image"] == self.loaded_id
                and item["Config"]["Image"] == self.manifest["candidate_ref"]
                and item["RestartCount"] == 0,
                "candidate_service_identity",
            )
            require(
                item["State"]["Status"] == "running"
                and item["State"].get("Health", {}).get("Status", "healthy")
                == "healthy",
                "candidate_service_not_ready",
            )
            require(
                normalized_mounts(item["Mounts"])
                == self.baseline["services"][name]["mounts"],
                "candidate_mount_changed",
            )
            check_application_mounts(normalized_mounts(item["Mounts"]))
        for name in ("postgres", "minio"):
            item = self.host.service(name)
            require(
                item["Id"] == self.baseline["services"][name]["id"]
                and item["State"]["Health"]["Status"] == "healthy",
                "dependency_changed",
            )
        require(
            self.host.db_snapshot() == self.baseline["db"],
            "historical_database_changed",
        )
        require(
            self.host.brand_identity() == self.baseline["brand_identity"],
            "active_brand_pointer_or_provider_changed",
        )
        copy_identity = self.host.copy_identity(
            self.host.service("acquisition-api")["Id"]
        )
        require(
            {key: copy_identity.get(key) for key in CANDIDATE_COPY_VERSIONS}
            == CANDIDATE_COPY_VERSIONS
            and {
                key: copy_identity.get(key)
                for key in (
                    "brand_embedding_provider",
                    "brand_embedding_model",
                    "brand_embedding_dimensions",
                )
            }
            == {
                key: self.baseline["copy_identity"][key]
                for key in (
                    "brand_embedding_provider",
                    "brand_embedding_model",
                    "brand_embedding_dimensions",
                )
            },
            "candidate_copy_provider_identity",
        )
        root = Path(
            self.baseline["volumes"]["edu-ai-lead-agent_wechat_mp_draft_artifacts"]
        )
        require(
            sha(canonical(tree_manifest(root))) == self.baseline["journal_sha256"],
            "historical_journal_changed",
        )
        require(
            sha(
                canonical(
                    tree_manifest(APP / "private/brand-materials", brand_data=True)
                )
            )
            == self.baseline["brand_sha256"],
            "brand_changed",
        )
        config = strict_json(self.host.compose("config", "--format", "json"))
        for name in SERVICES:
            actual_env = check_service_environment(
                name, self.host.service(name), config["services"][name], PROD_POLICY
            )
            require(
                sha(canonical(actual_env))
                == self.baseline["services"][name]["env_sha256"],
                "protected_runtime_environment_changed",
            )
            settings = config["services"][name].get("environment", {})
            require(
                config["services"][name]["image"] == self.manifest["candidate_ref"],
                "candidate_config_image",
            )
            for key, expected in FLAGS.items():
                if key in settings:
                    require(str(settings[key]).lower() == expected, "candidate_flags")
            if POLICY_KEY in settings:
                require(settings[POLICY_KEY] == PROD_POLICY, "candidate_visual_policy")
        actual_files = {name: metadata(APP / name) for name in PROTECTED_FILES}
        backup_files = archive_members(self.backup_dir / "runtime-config.tar.gz")
        expected_bodies = {name: backup_files[name] for name in PROTECTED_FILES}
        expected_bodies[".release.env"] = change_env(
            backup_files[".release.env"],
            "APP_IMAGE",
            BASE_REF,
            self.manifest["candidate_ref"],
        )
        for marker in (".release-commit", "RELEASE_COMMIT"):
            expected_bodies[marker] = (self.manifest["revision"] + "\n").encode()
        for name, body in expected_bodies.items():
            require(
                actual_files[name]
                == {
                    **self.baseline["files"][name],
                    "sha256": sha(body),
                    "size": len(body),
                },
                "activation_file_drift",
            )
        require(
            runtime_source_manifest() == self.baseline["runtime_source_manifest"],
            "activated_runtime_source_drift",
        )
        require(
            volume_fingerprints(self.baseline["volumes"])
            == self.baseline["volume_fingerprints"],
            "business_volume_changed",
        )
        state = strict_json(
            self.host.compose(
                "exec",
                "-T",
                "official-account-weekly-scheduler",
                "python",
                "-B",
                "-m",
                "app.official_account_weekly_dag_main",
                "single-status",
            )
        )
        require(
            state["single_enabled"] is True
            and state["legacy_mutual_exclusion"] is True
            and state["visual_pipeline_version"] == PROD_POLICY
            and state["leases"]["active"] == state["leases"]["stale"] == 0
            and state["next_window"] is not None,
            "single_status_failed",
        )
        require(state["history_ready"] is True, "history_barrier_not_ready")
        window = state["next_window"]
        expected_window = self.baseline["schedule_window"]
        require(
            window["business_date"] == expected_window["prepare_at"][:10]
            and window["prepare_at"] == expected_window["prepare_at"]
            and window["deliver_at"] == expected_window["upload_at"]
            and window["expires_at"] == expected_window["expires_at"],
            "single_window_drift",
        )
        # Standard health knows actual 0048 and explicitly reports isolated old unknowns.
        health = run(
            ["bash", str(APP / "scripts/edu-ai-production-check.sh")],
            cwd=APP,
            timeout=180,
        ).decode()
        require("runtime_health=ok" in health, "standard_health_failed")
        require(
            run(["systemctl", "is-active", "edu-ai-backup.timer"]).strip() == b"active",
            "backup_timer",
        )
        require(
            all(self.baseline["standard_markers_absent"].values())
            and standard_release_markers_absent()
            == self.baseline["standard_markers_absent"],
            "standard_release_path_changed",
        )
        return {
            "status": "deployed",
            "revision": self.manifest["revision"],
            "image": self.loaded_id,
            "schema": SCHEMA,
            "applications": len(SERVICES),
            "dependencies_preserved": 2,
            "historical_database_unchanged": True,
            "active_brand_identity_unchanged": True,
            "copy_versions": CANDIDATE_COPY_VERSIONS,
            "journal_unchanged": True,
            "policy": PROD_POLICY,
            "next_window": state["next_window"],
            "migration_executed": False,
            "operator_model_calls": 0,
            "operator_social_calls": 0,
            "standard_release_provenance": "incomplete",
        }

    def apply(self) -> dict[str, Any]:
        self.plan()
        self.log("load_and_verify_candidate")
        self.load()
        same_baseline(self.baseline, self.host.capture(self.manifest))
        check_backup_space(self.baseline)
        stopped = False
        try:
            self.log("quiesce")
            stopped = True
            self.host.compose("stop", "-t", "60", *reversed(SERVICES), timeout=180)
            self.fence_stopped()
            self.log("backup_and_verify")
            self.backup()
            self.fence_stopped()
            self.log("activate_candidate")
            self.activate()
            self.start()
            deadline = time.monotonic() + 120
            while True:
                try:
                    result = self.verify()
                    break
                except RuntimeError as exc:
                    if (
                        str(exc)
                        not in (
                            "candidate_service_not_ready",
                            "history_barrier_not_ready",
                        )
                        or time.monotonic() > deadline
                    ):
                        raise
                    time.sleep(3)
            write_new(self.backup_dir / "activation-receipt.json", canonical(result))
            return result
        except BaseException:
            if stopped:
                if self.activated:
                    # Candidate-only forward incident state. No old-image restart, DB restore,
                    # migration downgrade, or replay of any historical unknown is permitted.
                    self.host.compose("stop", "-t", "60", *SERVICES, timeout=180)
                    self.log(
                        "candidate_failed_all_writers_stopped_forward_recovery_required"
                    )
                else:
                    try:
                        # A partial stop is already mutating. Quiesce every writer,
                        # then prove effects/configuration are still the bound
                        # baseline before any old application may restart.
                        self.host.compose("stop", "-t", "60", *SERVICES, timeout=180)
                        self.fence_stopped()
                        require(
                            {name: metadata(APP / name) for name in PROTECTED_FILES}
                            == self.baseline["files"],
                            "preactivation_config_drift_writers_stopped",
                        )
                        self.host.compose("start", *SERVICES, timeout=120)
                        deadline = time.monotonic() + 90
                        while True:
                            try:
                                same_baseline(
                                    self.baseline, self.host.capture(self.manifest)
                                )
                                break
                            except RuntimeError as exc:
                                if (
                                    str(exc) != "baseline_service_health"
                                    or time.monotonic() >= deadline
                                ):
                                    raise
                                time.sleep(3)
                        self.log(
                            "preactivation_failed_original_services_health_verified"
                        )
                    except BaseException:
                        self.host.compose("stop", "-t", "60", *SERVICES, timeout=180)
                        self.log(
                            "preactivation_recovery_unverified_all_writers_stopped"
                        )
                        raise
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("build", "smoke", "capture", "plan", "apply"),
        nargs="?",
        default="plan",
    )
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--base-archive", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-sha256")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.action == "build":
            require(
                all((args.repo, args.base_archive, args.output, args.revision)),
                "build_arguments",
            )
            candidate = build(
                args.repo.resolve(),
                args.base_archive.resolve(),
                args.output.absolute(),
                args.revision,
            )
            print(
                json.dumps(
                    {
                        "status": "built",
                        "manifest_sha256": sha(canonical(candidate)),
                        "image": candidate["candidate_ref"],
                        "revision": candidate["revision"],
                    }
                )
            )
            return 0
        require(args.manifest and args.manifest_sha256, "manifest_arguments")
        manifest = validate_bundle(args.manifest.absolute(), args.manifest_sha256)
        host = Host()
        if args.action == "smoke":
            require(
                host.app_tree(manifest["candidate_ref"])
                == manifest["candidate_app_tree"]
                and host.app_tree(manifest["candidate_ref"], probe=RUNTIME_PROBE)
                == manifest["immutable_runtime_tree"],
                "offline_smoke",
            )
            identity = host.copy_identity(manifest["candidate_ref"], running=False)
            require(
                {key: identity.get(key) for key in CANDIDATE_COPY_VERSIONS}
                == CANDIDATE_COPY_VERSIONS,
                "offline_copy_versions",
            )
            print(
                json.dumps(
                    {
                        "status": "offline_smoke_passed",
                        "network": "none",
                        "schema": SCHEMA,
                    }
                )
            )
            return 0
        if args.action == "capture":
            require(args.output is not None, "capture_output_required")
            baseline = host.capture(manifest)
            write_new(args.output.absolute(), canonical(baseline))
            print(
                json.dumps(
                    {
                        "status": "captured",
                        "baseline_sha256": sha(canonical(baseline)),
                        "schema": SCHEMA,
                    }
                )
            )
            return 0
        require(args.baseline and args.baseline_sha256, "baseline_arguments")
        baseline = bound_json(args.baseline.absolute(), args.baseline_sha256)
        deployment = Deployment(host, args.manifest.absolute(), manifest, baseline)
        if args.action == "plan":
            deployment.plan()
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "writes": 0,
                        "schema": SCHEMA,
                        "next_window": next_window(datetime.now(UTC)),
                    }
                )
            )
            return 0
        require(args.apply and os.geteuid() == 0, "explicit_apply_required")
        fd = os.open(LOCK, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        backup_fd = os.open(
            BACKUP_LOCK, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "w") as lock, os.fdopen(backup_fd, "w") as backup_lock:
            details = os.fstat(lock.fileno())
            require(
                details.st_uid == 0
                and details.st_nlink == 1
                and stat.S_ISREG(details.st_mode)
                and stat.S_IMODE(details.st_mode) == 0o600,
                "lock_permissions",
            )
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            backup_details = os.fstat(backup_lock.fileno())
            require(
                backup_details.st_uid == 0
                and backup_details.st_nlink == 1
                and stat.S_ISREG(backup_details.st_mode)
                and stat.S_IMODE(backup_details.st_mode) == 0o600,
                "backup_lock_permissions",
            )
            fcntl.flock(backup_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

            def interrupted(_signum: int, _frame: Any) -> None:
                raise RuntimeError("deployment_interrupted")

            signal.signal(signal.SIGTERM, interrupted)
            print(json.dumps(deployment.apply()))
        return 0
    except BaseException as exc:  # noqa: BLE001 -- bounded safe error on signals and failures
        code = (
            str(exc)
            if isinstance(exc, RuntimeError) and re.fullmatch(r"[a-z_]+", str(exc))
            else "operator_failed"
        )
        print(json.dumps({"status": "failed", "code": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
