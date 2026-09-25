#!/usr/bin/env python3
"""Build and inspect one forward-only R15 OCI layer over the active R14 image.

This builder reads committed Git blobs and the independently verified R14 OCI
bundle. It neither mutates production nor invokes provider/business workflows.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import importlib.util
import io
import json
import re
import tarfile
from pathlib import Path
from types import ModuleType
from typing import Any, cast

OLD_REVISION = "5d1fe54fee3308a46f944d63436c0ee5b3e12b8a"
OLD_IMAGE = "sha256:95d43691e51ca7a284b455051812fd2cb43ff49ecc04bcbe21901bd71e1b4506"
OLD_ARCHIVE_SHA = "786142633836f5c51541d62ccf4fddda080c161e578ba62fdc4bbf2bf84e6f0e"
SUPPORT_SHA = "feac4db50bc01ac2ca40d984261cb943528b67447e1b7871ec98d31908605991"
REPOSITORY = "offline.local/edu-ai/edu-ai-lead-agent-backend"
SOURCE_PATH = "backend/app/infrastructure/db/copy_generation.py"
OPERATOR_PATH = (
    ".trellis/tasks/09-23-moments-brand-rag-diversity/research/"
    "r15-recovery/forward_release.py"
)
ACTIVATOR_PATH = (
    ".trellis/tasks/09-23-moments-brand-rag-diversity/research/"
    "r15-recovery/forward_activate.py"
)
VERSION = "moments-copy-startup-no-replay-20260925-v1"


def support(path: Path) -> ModuleType:
    import hashlib

    if hashlib.sha256(path.read_bytes()).hexdigest() != SUPPORT_SHA:
        raise RuntimeError("r14_support_hash")
    spec = importlib.util.spec_from_file_location("r14_release_support", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("r14_support_import")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(repo: Path, revision: str, previous: Path, output: Path) -> dict[str, Any]:
    s = support(previous.parent / "moments_release.py")
    old = s.validate_bundle(previous, s.sha(s.read_file(previous)))
    s.require(old["revision"] == OLD_REVISION, "old_revision")
    s.require(old["manifest_digest"] == OLD_IMAGE, "old_image")
    s.require(old["archive_sha256"] == OLD_ARCHIVE_SHA, "old_archive")
    s.require(not output.exists(), "output_exists")
    s.require(re.fullmatch(r"[0-9a-f]{40}", revision), "revision_shape")
    s.require(
        s.git(repo, "rev-parse", revision + "^{commit}").decode().strip() == revision,
        "revision_missing",
    )
    s.git(repo, "merge-base", "--is-ancestor", OLD_REVISION, revision)
    s.require(s.git(repo, "status", "--porcelain") == b"", "dirty_release_worktree")
    changed = (
        s.git(repo, "diff", "--name-only", OLD_REVISION, revision).decode().splitlines()
    )
    permitted = (
        "backend/tests/",
        ".trellis/tasks/09-23-moments-brand-rag-diversity/research/r15-recovery/",
    )
    s.require(SOURCE_PATH in changed, "source_change_missing")
    s.require(
        all(path == SOURCE_PATH or path.startswith(permitted) for path in changed),
        "unreviewed_release_change",
    )
    prior_app = s.git_files(repo, OLD_REVISION, "backend/app")
    new_app = s.git_files(repo, revision, "backend/app")
    s.require(set(prior_app) == set(new_app), "app_tree_shape")
    s.require(
        {path for path in new_app if new_app[path] != prior_app[path]} == {SOURCE_PATH},
        "app_overlay_scope",
    )
    s.require(
        s.git(repo, "show", revision + ":" + OPERATOR_PATH)
        == Path(__file__).read_bytes(),
        "uncommitted_builder",
    )
    activator = Path(__file__).with_name("forward_activate.py").read_bytes()
    s.require(
        s.git(repo, "show", revision + ":" + ACTIVATOR_PATH) == activator,
        "uncommitted_activator",
    )
    s.require(
        s.git_files(repo, OLD_REVISION, "backend/alembic")
        == s.git_files(repo, revision, "backend/alembic"),
        "migration_changed",
    )

    old_archive = previous.parent / "backend-image.oci.tar.gz"
    members = s.archive_members(old_archive)
    old_manifest, old_config, old_digest = s.oci_graph(
        members, expected_tag=old["candidate_tag"]
    )
    s.require(old_digest == OLD_IMAGE, "old_archive_identity")
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as layer:
        s.tar_member(
            layer,
            "app/app/infrastructure/db/copy_generation.py",
            new_app[SOURCE_PATH],
            uid=999,
        )
    raw_layer = raw.getvalue()
    compressed_layer = gzip.compress(raw_layer, mtime=0)
    config = copy.deepcopy(old_config)
    config["config"]["Labels"].update(
        {
            "org.opencontainers.image.revision": revision,
            "edu.ai.overlay.base": OLD_IMAGE,
            "edu.ai.change": VERSION,
        }
    )
    config["rootfs"]["diff_ids"].append("sha256:" + s.sha(raw_layer))
    config["history"].append(
        {"created_by": "COPY committed R15 no-replay repository blob"}
    )
    config_body = s.canonical(config)
    manifest = {
        "schemaVersion": 2,
        "mediaType": s.OCI + "manifest.v1+json",
        "config": s.describe(config_body, s.OCI + "config.v1+json"),
        "layers": [
            *old_manifest["layers"],
            s.describe(compressed_layer, s.OCI + "layer.v1.tar+gzip"),
        ],
    }
    manifest_body = s.canonical(manifest)
    image = "sha256:" + s.sha(manifest_body)
    tag = REPOSITORY + ":moments-r15-" + revision[:12]
    index = {
        "schemaVersion": 2,
        "mediaType": s.OCI + "index.v1+json",
        "manifests": [
            {
                **s.describe(manifest_body, s.OCI + "manifest.v1+json"),
                "platform": {"os": "linux", "architecture": "amd64"},
                "annotations": {
                    "io.containerd.image.name": tag,
                    "org.opencontainers.image.ref.name": tag.split(":")[-1],
                },
            }
        ],
    }
    keep = {"oci-layout": members["oci-layout"], "index.json": s.canonical(index)}
    for desc in old_manifest["layers"]:
        key = "blobs/sha256/" + desc["digest"][7:]
        keep[key] = members[key]
    for body in (manifest_body, config_body, compressed_layer):
        keep["blobs/sha256/" + s.sha(body)] = body
    archive = s.archive_bytes(keep)
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    s.write_new(output / "backend-image.oci.tar.gz", archive)
    s.write_new(
        output / "r14_support.py", s.read_file(previous.parent / "moments_release.py")
    )
    s.write_new(output / "forward_release.py", Path(__file__).read_bytes())
    s.write_new(output / "forward_activate.py", activator)
    result = {
        "version": VERSION,
        "revision": revision,
        "old_revision": OLD_REVISION,
        "old_image": OLD_IMAGE,
        "old_archive_sha256": OLD_ARCHIVE_SHA,
        "archive_sha256": s.sha(archive),
        "image": image,
        "candidate_ref": REPOSITORY + "@" + image,
        "tag": tag,
        "source_sha256": s.sha(new_app[SOURCE_PATH]),
        "operator_sha256": s.sha(Path(__file__).read_bytes()),
        "activator_sha256": s.sha(activator),
        "support_sha256": SUPPORT_SHA,
        "schema": old["schema"],
        "app_tree": {
            **old["candidate_app_tree"],
            "infrastructure/db/copy_generation.py": s.sha(new_app[SOURCE_PATH]),
        },
    }
    s.write_new(output / "candidate.json", s.canonical(result))
    check(output / "candidate.json", s.sha(s.canonical(result)))
    return result


def check(path: Path, expected_sha: str) -> dict[str, Any]:
    s = support(path.parent / "r14_support.py")
    result = s.bound_json(path, expected_sha)
    s.require(
        result["version"] == VERSION
        and result["old_revision"] == OLD_REVISION
        and result["old_image"] == OLD_IMAGE
        and result["schema"] == "20260916_0048",
        "candidate_contract",
    )
    s.require(
        result["support_sha256"] == SUPPORT_SHA
        and s.sha(s.read_file(path.parent / "forward_release.py"))
        == result["operator_sha256"]
        == s.sha(Path(__file__).read_bytes()),
        "operator_identity",
    )
    s.require(
        s.sha(s.read_file(path.parent / "forward_activate.py"))
        == result["activator_sha256"],
        "activator_identity",
    )
    archive_path = path.parent / "backend-image.oci.tar.gz"
    s.require(
        s.sha(s.read_file(archive_path)) == result["archive_sha256"], "archive_hash"
    )
    members = s.archive_members(archive_path)
    manifest, config, digest = s.oci_graph(members, expected_tag=result["tag"])
    s.require(
        digest == result["image"]
        and result["candidate_ref"] == REPOSITORY + "@" + digest,
        "candidate_image",
    )
    s.require(
        config["config"]["Labels"]["org.opencontainers.image.revision"]
        == result["revision"]
        and config["config"]["Labels"]["edu.ai.overlay.base"] == OLD_IMAGE
        and config["config"]["Labels"]["edu.ai.change"] == VERSION,
        "candidate_labels",
    )
    layer = s.bounded_gunzip(
        members["blobs/sha256/" + manifest["layers"][-1]["digest"][7:]],
        4 * 1024 * 1024,
    )
    with tarfile.open(fileobj=io.BytesIO(layer), mode="r:") as archive:
        entries = archive.getmembers()
        s.require(
            len(entries) == 1
            and entries[0].name == "app/app/infrastructure/db/copy_generation.py"
            and entries[0].uid == 999,
            "candidate_overlay",
        )
        stream = archive.extractfile(entries[0])
        s.require(
            stream is not None and s.sha(stream.read()) == result["source_sha256"],
            "candidate_source",
        )
    return cast(dict[str, Any], result)


def smoke(path: Path, expected_sha: str) -> dict[str, Any]:
    result = check(path, expected_sha)
    s = support(path.parent / "r14_support.py")
    s.run(
        ["docker", "load", "-i", str(path.parent / "backend-image.oci.tar.gz")],
        timeout=240,
    )
    host = s.Host()
    image = host.inspect(result["tag"], image=True)
    by_ref = host.inspect(result["candidate_ref"], image=True)
    s.require(image["Id"] == by_ref["Id"] == result["image"], "loaded_image_identity")
    s.require(
        host.app_tree(result["candidate_ref"]) == result["app_tree"],
        "loaded_app_tree",
    )
    host.app_tree(result["candidate_ref"], probe=s.RUNTIME_PROBE)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "check", "smoke"))
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args()
    if args.action == "build":
        if not (args.repo and args.revision and args.previous and args.output):
            parser.error("build requires repo, revision, previous and output")
        result = build(
            args.repo.resolve(),
            args.revision,
            args.previous.resolve(),
            args.output.resolve(),
        )
    else:
        if not (args.manifest and args.manifest_sha256):
            parser.error("check/smoke require manifest and manifest-sha256")
        result = (check if args.action == "check" else smoke)(
            args.manifest.resolve(), args.manifest_sha256
        )
    print(
        json.dumps(
            {
                "action": args.action,
                "revision": result["revision"],
                "image": result["image"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
