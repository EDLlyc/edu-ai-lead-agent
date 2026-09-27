#!/usr/bin/env python3
"""Convert a committed R16 Docker save to an independently checked OCI archive.

This is a local image-packaging utility, not a production activation operator.
It never builds, migrates, sends, or changes a remote host.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Any

OCI = "application/vnd.oci.image."
REPOSITORY = "offline.local/edu-ai/edu-ai-lead-agent-backend"
MAX_ARCHIVE = 1024 * 1024 * 1024
MAX_MEMBER = 512 * 1024 * 1024


class ImageError(RuntimeError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise ImageError(code)


def digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def strict_json(body: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    return json.loads(body, object_pairs_hook=unique)


def member_name(name: str) -> str:
    require(
        bool(name) and not name.startswith("/") and ".." not in Path(name).parts,
        "unsafe_archive_path",
    )
    return name


def members(path: Path, *, compressed: bool) -> dict[str, bytes]:
    require(path.is_file() and path.stat().st_size <= MAX_ARCHIVE, "archive_size")
    result: dict[str, bytes] = {}
    total = 0
    with tarfile.open(path, "r:gz" if compressed else "r:") as archive:
        for item in archive:
            name = member_name(item.name.rstrip("/"))
            require(name not in result, "duplicate_archive_path")
            if item.isdir():
                continue
            require(item.isfile() and item.size <= MAX_MEMBER, "archive_entry")
            stream = archive.extractfile(item)
            require(stream is not None, "archive_stream")
            assert stream is not None
            body = stream.read(item.size + 1)
            require(len(body) == item.size, "archive_entry_size")
            total += len(body)
            require(total <= MAX_ARCHIVE, "archive_expansion")
            result[name] = body
    return result


def descriptor(body: bytes, media_type: str) -> dict[str, Any]:
    return {"mediaType": media_type, "digest": digest(body), "size": len(body)}


def raw_layer(body: bytes, diff_id: str) -> bytes:
    if digest(body) == diff_id:
        return body
    # Docker 29's containerd-backed `docker save` includes both manifest.json
    # and OCI layout and points manifest.json.Layers at compressed OCI blobs.
    # Older Docker archives point at uncompressed tar layers. Normalize either
    # representation to the same bounded raw diff ID before OCI re-packing.
    require(body.startswith(b"\x1f\x8b"), "docker_layer_diff_id")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            raw = stream.read(MAX_MEMBER + 1)
    except (EOFError, OSError) as exc:
        raise ImageError("docker_layer_gzip") from exc
    require(len(raw) <= MAX_MEMBER and digest(raw) == diff_id, "docker_layer_diff_id")
    return raw


def archive_bytes(content: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, body in sorted(content.items()):
            info = tarfile.TarInfo(member_name(name))
            info.mode = 0o644
            info.uid = info.gid = info.mtime = 0
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    return gzip.compress(buffer.getvalue(), mtime=0)


def _blob(content: dict[str, bytes], info: dict[str, Any], media_type: str) -> bytes:
    require(
        info.get("mediaType") == media_type
        and isinstance(info.get("size"), int)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", info.get("digest", "")) is not None,
        "oci_descriptor",
    )
    body = content["blobs/sha256/" + info["digest"][7:]]
    require(info["size"] == len(body) and info["digest"] == digest(body), "oci_blob")
    return body


def check_oci(path: Path, *, tag: str, revision: str, config_id: str) -> dict[str, Any]:
    content = members(path, compressed=True)
    require(
        strict_json(content["oci-layout"]) == {"imageLayoutVersion": "1.0.0"},
        "oci_layout",
    )
    index = strict_json(content["index.json"])
    require(
        index.get("schemaVersion") == 2
        and index.get("mediaType") == OCI + "index.v1+json"
        and len(index.get("manifests", [])) == 1,
        "oci_index",
    )
    top = index["manifests"][0]
    require(
        top.get("platform") == {"os": "linux", "architecture": "amd64"}
        and top.get("annotations", {}).get("io.containerd.image.name") == tag,
        "oci_platform_tag",
    )
    image_body = _blob(content, top, OCI + "manifest.v1+json")
    image = strict_json(image_body)
    require(
        image.get("schemaVersion") == 2
        and image.get("mediaType") == OCI + "manifest.v1+json",
        "oci_manifest",
    )
    config_body = _blob(content, image["config"], OCI + "config.v1+json")
    config = strict_json(config_body)
    require(digest(config_body) == config_id, "config_id")
    require(
        config.get("architecture") == "amd64"
        and config.get("os") == "linux"
        and config.get("config", {})
        .get("Labels", {})
        .get("org.opencontainers.image.revision")
        == revision,
        "image_revision_platform",
    )
    diff_ids = config.get("rootfs", {}).get("diff_ids", [])
    require(len(image["layers"]) == len(diff_ids) and len(diff_ids) > 0, "layer_count")
    reached = {
        "oci-layout",
        "index.json",
        "blobs/sha256/" + top["digest"][7:],
        "blobs/sha256/" + image["config"]["digest"][7:],
    }
    for layer, diff_id in zip(image["layers"], diff_ids, strict=True):
        compressed = _blob(content, layer, OCI + "layer.v1.tar+gzip")
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            raw = stream.read(MAX_MEMBER + 1)
        require(len(raw) <= MAX_MEMBER, "layer_expansion")
        require(digest(raw) == diff_id, "layer_diff_id")
        reached.add("blobs/sha256/" + layer["digest"][7:])
    require(set(content) == reached, "unreferenced_oci_blob")
    return {
        "revision": revision,
        "tag": tag,
        "image": digest(image_body),
        "config_id": config_id,
        "archive_sha256": digest(path.read_bytes())[7:],
        "layers": len(diff_ids),
    }


def convert(
    docker_archive: Path, output: Path, *, tag: str, revision: str
) -> dict[str, Any]:
    require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "revision")
    require(tag == f"{REPOSITORY}:infographic-r16-{revision[:12]}", "tag")
    require(not output.exists(), "output_exists")
    source = members(docker_archive, compressed=False)
    docker_manifest = strict_json(source["manifest.json"])
    require(
        isinstance(docker_manifest, list) and len(docker_manifest) == 1,
        "docker_manifest",
    )
    record = docker_manifest[0]
    require(record.get("RepoTags") == [tag], "docker_tag")
    config_path = member_name(record["Config"])
    config_body = source[config_path]
    config = strict_json(config_body)
    require(
        config.get("architecture") == "amd64"
        and config.get("os") == "linux"
        and config.get("config", {})
        .get("Labels", {})
        .get("org.opencontainers.image.revision")
        == revision,
        "docker_config_identity",
    )
    layers = record["Layers"]
    diff_ids = config.get("rootfs", {}).get("diff_ids", [])
    require(
        isinstance(layers, list) and len(layers) == len(diff_ids) and bool(layers),
        "docker_layers",
    )
    content = {"oci-layout": canonical({"imageLayoutVersion": "1.0.0"})}
    descriptors: list[dict[str, Any]] = []
    for path, diff_id in zip(layers, diff_ids, strict=True):
        raw = raw_layer(source[member_name(path)], diff_id)
        packed = gzip.compress(raw, mtime=0)
        desc = descriptor(packed, OCI + "layer.v1.tar+gzip")
        content["blobs/sha256/" + desc["digest"][7:]] = packed
        descriptors.append(desc)
    config_desc = descriptor(config_body, OCI + "config.v1+json")
    content["blobs/sha256/" + config_desc["digest"][7:]] = config_body
    image_body = canonical(
        {
            "schemaVersion": 2,
            "mediaType": OCI + "manifest.v1+json",
            "config": config_desc,
            "layers": descriptors,
        }
    )
    image_desc = descriptor(image_body, OCI + "manifest.v1+json")
    content["blobs/sha256/" + image_desc["digest"][7:]] = image_body
    content["index.json"] = canonical(
        {
            "schemaVersion": 2,
            "mediaType": OCI + "index.v1+json",
            "manifests": [
                {
                    **image_desc,
                    "platform": {"os": "linux", "architecture": "amd64"},
                    "annotations": {
                        "io.containerd.image.name": tag,
                        "org.opencontainers.image.ref.name": tag.rsplit(":", 1)[1],
                    },
                }
            ],
        }
    )
    body = archive_bytes(content)
    with tempfile.TemporaryDirectory(prefix="r16-oci-", dir=output.parent) as temp:
        candidate = Path(temp) / "image.oci.tar.gz"
        candidate.write_bytes(body)
        result = check_oci(
            candidate, tag=tag, revision=revision, config_id=digest(config_body)
        )
        require(result["image"] == image_desc["digest"], "converted_image")
        # Linking a checked inode fails if another process created the target
        # after the initial guard; an existing release is never overwritten.
        os.link(candidate, output)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    try:
        result = convert(
            args.docker_archive,
            args.output,
            tag=args.tag,
            revision=args.revision,
        )
    except (
        ImageError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        tarfile.TarError,
    ) as exc:
        print(json.dumps({"status": "blocked", "code": str(exc)}))
        return 2
    print(json.dumps({"status": "checked", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
