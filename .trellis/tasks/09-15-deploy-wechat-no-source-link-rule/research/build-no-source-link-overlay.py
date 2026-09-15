#!/usr/bin/env python3
"""Build one deterministic OCI layer on the exact deployed d2e709c archive."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PREVIOUS_REVISION = "d2e709c0b6a5e47d1b91d2ec623de734aa3c0eb2"
BASE_ARCHIVE_SHA256 = "23493bf1382b2965e5a8118412ba19b9d02f07052fc937fd7c04fdbae90262a1"
BASE_MANIFEST = (
    "sha256:baffc27e9dc4ccbd9fed5ab248e4e00784f80ecfb25f966fe8c63ee286601d8d"
)
REPOSITORY = "offline.local/edu-ai/edu-ai-lead-agent-backend"
FILES = {
    "domain/official_account_source_presentation.py": "6bd12a2e24551ffaca1cd370d3284169463602ac8bcff0390a7dd693e77fb57a",
    "domain/official_account_editor_handoff_v2.py": "0851427717287b591ba6f9835abec530c978619a3da7a538d8dbbca9df34fd65",
    "application/services/official_account_strict_prepared.py": "919ff0a12cc015d9b5815022f7a3e0369cdb5cb90763c8b3a47e8df38435a6b1",
    "application/services/wechat_official_account_draft.py": "b116c3dba73623778f78c04c0d49f6292bdbb348b8ebd3f28046cd7b35c4965a",
    "infrastructure/wechat_official_account/prepared_artifacts.py": "70de4170346170a28b72daf1e24993f3b412d09519868cfc1e90d8855b002050",
}
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_LAYER = "application/vnd.oci.image.layer.v1.tar+gzip"


def require(value: bool, code: str) -> None:
    if not value:
        raise RuntimeError(code)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def command(repo: Path, *args: str) -> str:
    result = subprocess.run(
        args,
        cwd=repo,
        env={
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LC_ALL": "C",
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def load_validator(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("no_source_link_oci_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("validator_import")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def descriptor(body: bytes, media_type: str) -> dict[str, object]:
    return {
        "mediaType": media_type,
        "digest": "sha256:" + digest(body),
        "size": len(body),
    }


def build_layer(repo: Path) -> tuple[bytes, bytes]:
    raw_buffer = io.BytesIO()
    with tarfile.open(fileobj=raw_buffer, mode="w", format=tarfile.PAX_FORMAT) as layer:
        for relative in sorted(FILES):
            body = (repo / "backend/app" / relative).read_bytes()
            require(digest(body) == FILES[relative], "source_hash")
            info = tarfile.TarInfo("app/app/" + relative)
            info.size = len(body)
            info.mode = 0o644
            info.uid = info.gid = 999
            info.uname = info.gname = "app"
            info.mtime = 0
            layer.addfile(info, io.BytesIO(body))
    raw = raw_buffer.getvalue()
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    return raw, compressed


def add_tar_file(
    bundle: tarfile.TarFile, name: str, body: bytes, mode: int = 0o644
) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(body)
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = 0
    bundle.addfile(info, io.BytesIO(body))


def write_archive(path: Path, members: dict[str, bytes]) -> None:
    with path.open("xb") as raw:
        os.fchmod(raw.fileno(), 0o600)
        with (
            gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0
            ) as zipped,
            tarfile.open(
                fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT
            ) as bundle,
        ):
            for directory in ("blobs", "blobs/sha256"):
                info = tarfile.TarInfo(directory)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.uid = info.gid = 0
                info.mtime = 0
                bundle.addfile(info)
            for name in sorted(members):
                add_tar_file(bundle, name, members[name])
        raw.flush()
        os.fsync(raw.fileno())


def write_mode_600(path: Path, body: bytes) -> None:
    with path.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def build(
    repo: Path, base_archive: Path, output: Path, revision: str
) -> dict[str, object]:
    require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "revision")
    require(command(repo, "git", "rev-parse", "HEAD") == revision, "head_revision")
    require(
        not command(repo, "git", "status", "--porcelain=v1", "--untracked-files=all"),
        "dirty_tree",
    )
    changed = command(
        repo,
        "git",
        "diff",
        "--name-status",
        "--no-renames",
        PREVIOUS_REVISION,
        revision,
        "--",
        "backend/app",
    ).splitlines()
    expected = {"M\tbackend/app/" + item for item in FILES}
    require(set(changed) == expected and len(changed) == len(expected), "runtime_diff")
    require(file_digest(base_archive) == BASE_ARCHIVE_SHA256, "base_archive_hash")
    validator_path = Path(__file__).with_name("validate-no-source-link-overlay.py")
    validator = load_validator(validator_path)
    base_members = validator.safe_members(base_archive)
    base_index = validator.strict_json(base_members["index.json"], "base_index")
    require(
        isinstance(base_index, dict) and len(base_index["manifests"]) == 1, "base_index"
    )
    base_top = base_index["manifests"][0]
    require(base_top["digest"] == BASE_MANIFEST, "base_manifest")
    base_manifest_body = base_members["blobs/sha256/" + BASE_MANIFEST[7:]]
    base_manifest = validator.strict_json(base_manifest_body, "base_manifest")
    require(isinstance(base_manifest, dict), "base_manifest")
    base_config_digest = base_manifest["config"]["digest"]
    base_config = validator.strict_json(
        base_members["blobs/sha256/" + base_config_digest[7:]], "base_config"
    )
    require(isinstance(base_config, dict), "base_config")
    raw_layer, compressed_layer = build_layer(repo)
    created = (
        datetime.fromtimestamp(
            int(command(repo, "git", "show", "-s", "--format=%ct", revision)), UTC
        )
        .isoformat()
        .replace("+00:00", "Z")
    )
    config = copy.deepcopy(base_config)
    labels = config["config"]["Labels"]
    labels["org.opencontainers.image.revision"] = revision
    labels["org.opencontainers.image.created"] = created
    labels["edu.ai.change"] = "wechat-no-source-links-v2"
    labels["edu.ai.overlay.base"] = BASE_MANIFEST
    config["rootfs"]["diff_ids"].append("sha256:" + digest(raw_layer))
    config["history"].append(
        {
            "created": created,
            "created_by": "COPY five reviewed no-source-link application files",
            "comment": "trellis exact-base offline overlay",
        }
    )
    config_body = canonical(config)
    layer_description = descriptor(compressed_layer, OCI_LAYER)
    manifest = {
        "schemaVersion": 2,
        "mediaType": OCI_MANIFEST,
        "config": descriptor(config_body, OCI_CONFIG),
        "layers": [*base_manifest["layers"], layer_description],
    }
    manifest_body = canonical(manifest)
    candidate_manifest = "sha256:" + digest(manifest_body)
    tag = REPOSITORY + ":no-source-links-" + revision[:12]
    index = {
        "schemaVersion": 2,
        "mediaType": OCI_INDEX,
        "manifests": [
            {
                **descriptor(manifest_body, OCI_MANIFEST),
                "annotations": {
                    "io.containerd.image.name": tag,
                    "org.opencontainers.image.ref.name": tag.rsplit(":", 1)[1],
                },
                "platform": {"architecture": "amd64", "os": "linux"},
            }
        ],
    }
    keep = {
        "oci-layout": canonical({"imageLayoutVersion": "1.0.0"}),
        "index.json": canonical(index),
        "blobs/sha256/" + digest(manifest_body): manifest_body,
        "blobs/sha256/" + digest(config_body): config_body,
        "blobs/sha256/" + digest(compressed_layer): compressed_layer,
    }
    for item in base_manifest["layers"]:
        key = "blobs/sha256/" + item["digest"][7:]
        keep[key] = base_members[key]
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    archive = output / "backend-image.oci.tar.gz"
    write_archive(archive, keep)
    copied_validator = output / validator_path.name
    write_mode_600(copied_validator, validator_path.read_bytes())
    operator_path = Path(__file__).with_name("deploy-no-source-links.py")
    copied_operator = output / operator_path.name
    write_mode_600(copied_operator, operator_path.read_bytes())
    candidate_ref = REPOSITORY + "@" + candidate_manifest
    validation = validator.validate(
        archive,
        candidate_tag=tag,
        candidate_ref=candidate_ref,
        revision=revision,
    )
    require(validation["manifest_digest"] == candidate_manifest, "candidate_validation")
    result: dict[str, object] = {
        "version": "no-source-links-offline-v1",
        "revision": revision,
        "previous_revision": PREVIOUS_REVISION,
        "base_ref": REPOSITORY + "@" + BASE_MANIFEST,
        "base_archive_sha256": BASE_ARCHIVE_SHA256,
        "candidate_tag": tag,
        "candidate_ref": candidate_ref,
        "candidate_image_id": candidate_manifest,
        "archive": archive.name,
        "archive_sha256": file_digest(archive),
        "app_files": FILES,
        "validator": validator_path.name,
        "validator_sha256": file_digest(copied_validator),
    }
    manifest_path = output / "candidate.json"
    write_mode_600(manifest_path, canonical(result))
    checksum_paths = (archive, manifest_path, copied_operator, copied_validator)
    checksums = "".join(
        f"{file_digest(path)}  {path.name}\n" for path in checksum_paths
    ).encode()
    write_mode_600(output / "artifacts.sha256", checksums)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--base-archive", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[4]
    output = args.output_dir.absolute()
    require(
        output.is_absolute() and not output.exists() and output.parent.is_dir(),
        "output_dir",
    )
    result = build(repo, args.base_archive.absolute(), output, args.revision)
    print(
        json.dumps(
            {
                "status": "built",
                "revision": result["revision"],
                "candidate_ref": result["candidate_ref"],
                "archive_sha256": result["archive_sha256"],
                "manifest_sha256": file_digest(output / "candidate.json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
