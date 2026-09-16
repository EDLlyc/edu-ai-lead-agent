#!/usr/bin/env python3
"""Build from committed git blobs, never from a dirty application working tree."""

from __future__ import annotations

import argparse
import copy
import gzip
import importlib.util
import io
import json
import re
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "visual_release_common", Path(__file__).with_name("release-common.py")
)
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)
B = C.archived("build")


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=False,
    )
    C.require(result.returncode == 0, "git_object_read")
    return result.stdout


def committed_sources(
    repo: Path, revision: str
) -> tuple[dict[str, bytes], dict[str, bytes]]:
    C.require(
        re.fullmatch(r"[0-9a-f]{40}", revision) is not None
        and revision != C.PREVIOUS_REVISION,
        "revision",
    )
    C.require(
        git(repo, "rev-parse", revision + "^{commit}").decode().strip() == revision,
        "commit_object",
    )
    C.require(
        not git(
            repo,
            "diff",
            "--name-only",
            C.PREVIOUS_REVISION,
            revision,
            "--",
            "backend/pyproject.toml",
            "backend/uv.lock",
            "backend/alembic.ini",
            "backend/requirements",
            "backend/Dockerfile",
            "compose.yaml",
        ),
        "non_code_release_diff",
    )
    diff = (
        git(
            repo,
            "diff",
            "--name-status",
            "--no-renames",
            C.PREVIOUS_REVISION,
            revision,
            "--",
            "backend/app",
        )
        .decode()
        .splitlines()
    )
    bodies = {}
    for line in diff:
        kind, path = line.split("\t")
        C.require(
            kind in {"A", "M"} and path.startswith("backend/app/"), "runtime_diff"
        )
        relative = path.removeprefix("backend/app/")
        C.require(relative in C.ALLOWED_FILES, "unreviewed_app_file")
        tree = git(repo, "ls-tree", revision, "--", path).decode()
        C.require(
            tree.startswith("100644 blob ") and tree.count("\n") == 1, "git_file_mode"
        )
        bodies[relative] = git(repo, "show", revision + ":" + path)
    C.validate_files({k: C.digest(v) for k, v in bodies.items()})
    migration_diff = (
        git(
            repo,
            "diff",
            "--name-status",
            "--no-renames",
            C.PREVIOUS_REVISION,
            revision,
            "--",
            "backend/alembic",
        )
        .decode()
        .splitlines()
    )
    migrations = {}
    for line in migration_diff:
        kind, path = line.split("\t")
        relative = path.removeprefix("backend/")
        C.require(
            kind == "A"
            and path == "backend/" + C.MIGRATION_FILE
            and relative == C.MIGRATION_FILE,
            "unreviewed_migration_file",
        )
        tree = git(repo, "ls-tree", revision, "--", path).decode()
        C.require(
            tree.startswith("100644 blob ") and tree.count("\n") == 1,
            "migration_git_file_mode",
        )
        migrations[relative] = git(repo, "show", revision + ":" + path)
    C.validate_migration_files({k: C.digest(v) for k, v in migrations.items()})
    return bodies, migrations


def build_layer(
    app_bodies: dict[str, bytes], migration_bodies: dict[str, bytes]
) -> tuple[bytes, bytes]:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as layer:
        overlay = {
            **{"app/app/" + path: body for path, body in app_bodies.items()},
            **{"app/" + path: body for path, body in migration_bodies.items()},
        }
        for path, body in sorted(overlay.items()):
            entry = tarfile.TarInfo(path)
            entry.size, entry.mode, entry.uid, entry.gid = len(body), 0o644, 999, 999
            entry.uname = entry.gname = "app"
            entry.mtime = 0
            layer.addfile(entry, io.BytesIO(body))
    raw = buffer.getvalue()
    return raw, gzip.compress(raw, compresslevel=9, mtime=0)


def build(
    repo: Path, base_archive: Path, output: Path, revision: str, snapshot: dict
) -> dict:
    C.source_module("snapshot").validate_snapshot(snapshot)
    sources, migrations = committed_sources(repo, revision)
    app_files = {k: C.digest(v) for k, v in sources.items()}
    migration_files = {k: C.digest(v) for k, v in migrations.items()}
    C.require(B.file_digest(base_archive) == C.BASE_ARCHIVE_SHA256, "base_archive_hash")
    V = C.archived("validate")
    blobs = V.safe_members(base_archive)
    index = V.strict_json(blobs["index.json"], "base_index")
    C.require(
        len(index["manifests"]) == 1
        and index["manifests"][0]["digest"] == C.BASE_MANIFEST,
        "base_manifest",
    )
    base = V.strict_json(blobs["blobs/sha256/" + C.BASE_MANIFEST[7:]], "base_manifest")
    config = copy.deepcopy(
        V.strict_json(
            blobs["blobs/sha256/" + base["config"]["digest"][7:]], "base_config"
        )
    )
    raw, zipped = build_layer(sources, migrations)
    created = (
        datetime.fromtimestamp(
            int(git(repo, "show", "-s", "--format=%ct", revision)), UTC
        )
        .isoformat()
        .replace("+00:00", "Z")
    )
    config["config"]["Labels"].update(
        {
            "org.opencontainers.image.revision": revision,
            "org.opencontainers.image.created": created,
            "edu.ai.change": C.CHANGE,
            "edu.ai.overlay.base": C.BASE_MANIFEST,
        }
    )
    config["rootfs"]["diff_ids"].append("sha256:" + C.digest(raw))
    config["history"].append(
        {
            "created": created,
            "created_by": C.HISTORY_COMMAND,
            "comment": "trellis exact-base offline overlay",
        }
    )
    cb = C.canonical(config)
    mb = C.canonical(
        {
            "schemaVersion": 2,
            "mediaType": B.OCI_MANIFEST,
            "config": B.descriptor(cb, B.OCI_CONFIG),
            "layers": [*base["layers"], B.descriptor(zipped, B.OCI_LAYER)],
        }
    )
    image_id = "sha256:" + C.digest(mb)
    tag = C.REPOSITORY + ":visual-recovery-" + revision[:12]
    candidate_ref = C.REPOSITORY + "@" + image_id
    members = {
        "oci-layout": C.canonical({"imageLayoutVersion": "1.0.0"}),
        "index.json": C.canonical(
            {
                "schemaVersion": 2,
                "mediaType": B.OCI_INDEX,
                "manifests": [
                    {
                        **B.descriptor(mb, B.OCI_MANIFEST),
                        "annotations": {
                            "io.containerd.image.name": tag,
                            "org.opencontainers.image.ref.name": tag.rsplit(":", 1)[1],
                        },
                        "platform": {"architecture": "amd64", "os": "linux"},
                    }
                ],
            }
        ),
        "blobs/sha256/" + C.digest(cb): cb,
        "blobs/sha256/" + C.digest(mb): mb,
        "blobs/sha256/" + C.digest(zipped): zipped,
    }
    for layer in base["layers"]:
        key = "blobs/sha256/" + layer["digest"][7:]
        members[key] = blobs[key]
    helper_bodies = {}
    for name in (
        "release-common.py",
        "release-snapshot.py",
        "release-journal.py",
        "release-validate.py",
        "release-deploy.py",
        "release-build.py",
    ):
        path = C.ROOT / name
        relative = path.relative_to(repo).as_posix()
        body = git(repo, "show", revision + ":" + relative)
        C.require(body == path.read_bytes(), "uncommitted_release_helper")
        helper_bodies[name] = body
    for role in C.ARCHIVED:
        helper_bodies["release-base-" + role + ".py"] = C.archived_path(
            role
        ).read_bytes()
    output.mkdir(mode=0o700, exist_ok=False)
    archive = output / "backend-image.oci.tar.gz"
    B.write_archive(archive, members)
    for name, body in helper_bodies.items():
        B.write_mode_600(output / name, body)
    V2 = C.source_module("validate")
    V2.validate(
        archive,
        candidate_tag=tag,
        candidate_ref=candidate_ref,
        revision=revision,
        app_files=app_files,
        migration_files=migration_files,
    )
    helpers = {k: C.digest(v) for k, v in helper_bodies.items()}
    value = {
        "version": C.CHANGE,
        "revision": revision,
        "previous_revision": C.PREVIOUS_REVISION,
        "base_ref": C.BASE_REF,
        "base_archive_sha256": C.BASE_ARCHIVE_SHA256,
        "candidate_tag": tag,
        "candidate_ref": candidate_ref,
        "candidate_image_id": image_id,
        "archive": archive.name,
        "archive_sha256": B.file_digest(archive),
        "app_files": app_files,
        "migration_files": migration_files,
        "previous_schema": C.PREVIOUS_SCHEMA,
        "target_schema": C.TARGET_SCHEMA,
        "config_transition": {
            "key": C.VISUAL_POLICY_KEY,
            "from": C.PREVIOUS_VISUAL_POLICY,
            "to": C.TARGET_VISUAL_POLICY,
            "image_max_attempts": C.IMAGE_MAX_ATTEMPTS,
        },
        "validator": "release-validate.py",
        "validator_sha256": helpers["release-validate.py"],
        "helpers": helpers,
        "production_snapshot": snapshot,
    }
    manifest = output / "candidate.json"
    B.write_mode_600(manifest, C.canonical(value))
    C.manifest(manifest, B.file_digest(manifest))
    checksums = "".join(
        f"{B.file_digest(path)}  {path.name}\n" for path in sorted(output.iterdir())
    )
    B.write_mode_600(output / "artifacts.sha256", checksums.encode())
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--base-archive", type=Path, required=True)
    parser.add_argument("--production-snapshot", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.production_snapshot.read_bytes())
    value = build(
        args.repo.resolve(),
        args.base_archive.absolute(),
        args.output_dir.absolute(),
        args.revision,
        snapshot,
    )
    print(
        C.canonical(
            {
                "status": "built",
                "revision": value["revision"],
                "candidate_ref": value["candidate_ref"],
                "manifest_sha256": B.file_digest(args.output_dir / "candidate.json"),
            }
        ).decode()
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 -- operator emits no raw subprocess output
        raise SystemExit("release_build_failed") from None
