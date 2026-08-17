#!/usr/bin/env python3
"""Pure validators for the broad offline release artifacts.

This helper performs no Docker, network, database, or provider operation.  The
release operator runs it before loading the isolated candidate image or
stopping an application service.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import pathlib
import re
import sys
import tarfile
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Any, NoReturn

SHA256_HEX = re.compile(r"[0-9a-f]{64}")
SHA256_ID = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_TAG = re.compile(r"edu-ai-lead-agent(?:-backend)?:[A-Za-z0-9._-]+")
MANIFEST_LINE = re.compile(r"([0-9a-f]{64})  ([^\r\n]+)")
MAX_JSON = 16 * 1024 * 1024
MAX_BLOB = 1024 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024 * 1024
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_MANIFESTS = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
OCI_CONFIGS = {
    "application/vnd.oci.image.config.v1+json",
    "application/vnd.docker.container.image.v1+json",
}
RAW_LAYERS = {
    "application/vnd.oci.image.layer.v1.tar",
    "application/vnd.oci.image.layer.nondistributable.v1.tar",
    "application/vnd.docker.image.rootfs.diff.tar",
    "application/vnd.docker.image.rootfs.foreign.diff.tar",
}
GZIP_LAYERS = {
    "application/vnd.oci.image.layer.v1.tar+gzip",
    "application/vnd.oci.image.layer.nondistributable.v1.tar+gzip",
    "application/vnd.docker.image.rootfs.diff.tar.gzip",
    "application/vnd.docker.image.rootfs.foreign.diff.tar.gzip",
}
OCI_LAYERS = RAW_LAYERS | GZIP_LAYERS
FORBIDDEN_ROOTS = {
    ".git",
    ".trellis",
    ".venv",
    "frontend",
    "node_modules",
    "output",
    "private",
    "reports",
}
FORBIDDEN_NAMES = {".env", ".release.env"}
FORBIDDEN_SUFFIXES = {".fdb_latexmk", ".fls", ".xdv"}
ALLOWED_SOURCE_ROOTS = {"backend", "deploy", "infra", "scripts"}
ALLOWED_SOURCE_ROOT_FILES = {
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "Makefile",
    "README.md",
    "compose.yaml",
    "environment.yml",
}
REQUIRED_SOURCE_PATHS = {
    "compose.yaml",
    "backend/alembic.ini",
    "backend/pyproject.toml",
    "backend/requirements/runtime.lock",
}
REQUIRED_IMAGE_PATHS = {"alembic.ini", "pyproject.toml"}
IMAGE_SOURCE_ROOTS = {"alembic", "app"}
IMAGE_SOURCE_SUFFIXES = {".html", ".py"}


def fail(reason: str) -> NoReturn:
    raise ValueError(reason)


@contextmanager
def readable_tar(path: pathlib.Path | str, *, label: str) -> Any:
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            yield archive
    except (OSError, tarfile.TarError):
        fail(f"{label} is not a readable gzip tar")


def safe_path(raw: str, *, directory: bool = False) -> str:
    value = raw.removeprefix("./")
    if directory:
        value = value.rstrip("/")
    pure = pathlib.PurePosixPath(value)
    if (
        not value
        or pure.is_absolute()
        or str(pure) != value
        or any(part in {"", ".", ".."} for part in pure.parts)
        or any(character in value for character in ("\0", "\n", "\r", "\t"))
    ):
        fail("unsafe artifact path")
    return value


def parse_checksum_manifest(
    path: pathlib.Path,
    *,
    expected_count: int,
    source_scope: bool,
) -> list[tuple[str, str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        fail(f"checksum manifest is unreadable: {exc.__class__.__name__}")
    entries: list[tuple[str, str]] = []
    for line in lines:
        match = MANIFEST_LINE.fullmatch(line)
        if match is None:
            fail("checksum manifest syntax is unsafe")
        digest, raw = match.groups()
        value = safe_path(raw)
        pure = pathlib.PurePosixPath(value)
        if source_scope and (
            pure.parts[0] in FORBIDDEN_ROOTS
            or pure.name in FORBIDDEN_NAMES
            or pure.suffix in FORBIDDEN_SUFFIXES
            or "__pycache__" in pure.parts
            or "private" in pure.parts
            or (
                value not in ALLOWED_SOURCE_ROOT_FILES
                and pure.parts[0] not in ALLOWED_SOURCE_ROOTS
            )
        ):
            fail("source checksum path is outside the active runtime scope")
        entries.append((value, digest))
    paths = [value for value, _digest in entries]
    if expected_count <= 0 or len(entries) != expected_count:
        fail("checksum manifest count mismatch")
    if len(paths) != len(set(paths)) or paths != sorted(paths):
        fail("checksum manifest is duplicate or non-deterministic")
    return entries


def validate_source(args: argparse.Namespace) -> None:
    archive_path = pathlib.Path(args.archive)
    manifest_path = pathlib.Path(args.manifest)
    entries = parse_checksum_manifest(
        manifest_path,
        expected_count=args.expected_count,
        source_scope=True,
    )
    expected = dict(entries)
    if not REQUIRED_SOURCE_PATHS.issubset(expected):
        fail("source manifest omits a required runtime/dependency input")
    observed: dict[str, str] = {}
    modes: dict[str, str] = {}
    directories: set[str] = set()
    seen: set[str] = set()
    with readable_tar(archive_path, label="source archive") as archive:
        for member in archive.getmembers():
            if member.isdir():
                value = safe_path(member.name, directory=True)
                if value in seen or member.mode not in {0o755, 0o775}:
                    fail("source archive directory is duplicate or has an unsafe mode")
                seen.add(value)
                directories.add(value)
                continue
            if not member.isfile():
                fail("source archive contains a non-regular member")
            value = safe_path(member.name)
            if value in seen or value not in expected:
                fail("source archive member is duplicate or outside the manifest")
            seen.add(value)
            canonical_mode = {
                0o644: "0644",
                0o664: "0644",
                0o755: "0755",
                0o775: "0755",
            }.get(member.mode)
            if canonical_mode is None:
                fail("source archive regular member mode is unsafe")
            extracted = archive.extractfile(member)
            if extracted is None:
                fail("source archive member is unreadable")
            hasher = hashlib.sha256()
            observed_size = 0
            while chunk := extracted.read(1024 * 1024):
                observed_size += len(chunk)
                if observed_size > member.size:
                    fail("source archive member exceeds its header size")
                hasher.update(chunk)
            if observed_size != member.size:
                fail("source archive member size mismatch")
            observed[value] = hasher.hexdigest()
            modes[value] = canonical_mode
    if observed != expected:
        fail("source archive hashes or exact membership differ from the manifest")
    for directory in directories:
        prefix = f"{directory}/"
        if not any(value.startswith(prefix) for value in expected):
            fail("source archive contains an unneeded directory")
    pathlib.Path(args.paths_output).write_text(
        "".join(f"{value}\n" for value in expected), encoding="utf-8"
    )
    pathlib.Path(args.modes_output).write_text(
        "".join(f"{modes[value]}\t{value}\n" for value in expected),
        encoding="utf-8",
    )


def validate_manifest(args: argparse.Namespace) -> None:
    entries = parse_checksum_manifest(
        pathlib.Path(args.manifest),
        expected_count=args.expected_count,
        source_scope=True,
    )
    if not REQUIRED_SOURCE_PATHS.issubset(value for value, _digest in entries):
        fail("source manifest omits a required runtime/dependency input")
    pathlib.Path(args.paths_output).write_text(
        "".join(f"{value}\n" for value, _digest in entries), encoding="utf-8"
    )


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("image bundle JSON contains a duplicate key")
        result[key] = value
    return result


def parse_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload,
            object_pairs_hook=unique_object,
            parse_constant=lambda _value: fail(
                f"{label} contains a non-standard JSON constant"
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail(f"{label} is not valid JSON")


def descriptor(
    value: Any,
    label: str,
    media_types: set[str],
    *,
    annotations: bool = False,
) -> tuple[str, int, str]:
    if not isinstance(value, dict):
        fail(f"{label} descriptor is not an object")
    allowed = {"mediaType", "digest", "size"}
    if annotations:
        allowed.add("annotations")
    if not {"mediaType", "digest", "size"}.issubset(value) or not set(
        value
    ).issubset(allowed):
        fail(f"{label} descriptor fields conflict")
    media_type, digest, size = value["mediaType"], value["digest"], value["size"]
    if media_type not in media_types:
        fail(f"{label} descriptor media type is unsupported")
    if not isinstance(digest, str) or SHA256_ID.fullmatch(digest) is None:
        fail(f"{label} descriptor digest is invalid")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_BLOB:
        fail(f"{label} descriptor size is invalid")
    if "annotations" in value:
        metadata = value["annotations"]
        if not isinstance(metadata, dict) or any(
            not isinstance(key, str) or not isinstance(item, str)
            for key, item in metadata.items()
        ):
            fail(f"{label} descriptor annotations are invalid")
    return digest, size, media_type


def validate_image(args: argparse.Namespace) -> None:
    expected_tag: str = args.expected_tag
    expected_image_id: str = args.expected_image_id
    if IMAGE_TAG.fullmatch(expected_tag) is None:
        fail("expected candidate tag is invalid")
    if SHA256_ID.fullmatch(expected_image_id) is None:
        fail("expected candidate image id is invalid")
    with readable_tar(args.bundle, label="image bundle") as archive:
        files: dict[str, tarfile.TarInfo] = {}
        directories: set[str] = set()
        seen: set[str] = set()
        total_size = 0
        for member in archive.getmembers():
            if member.isdir():
                value = safe_path(member.name, directory=True)
                if value in seen:
                    fail("image bundle contains a duplicate member")
                seen.add(value)
                directories.add(value)
            elif member.isfile():
                value = safe_path(member.name)
                if value in seen or not 0 <= member.size <= MAX_BLOB:
                    fail("image bundle member is duplicate or oversized")
                seen.add(value)
                total_size += member.size
                if total_size > MAX_TOTAL:
                    fail("image bundle total size is excessive")
                files[value] = member
            else:
                fail("image bundle contains a non-regular member")
        if len(seen) > 10_000:
            fail("image bundle member count is excessive")

        def read_member(value: str, limit: int, label: str) -> bytes:
            member = files.get(value)
            if member is None or member.size > limit:
                fail(f"{label} is absent or oversized")
            extracted = archive.extractfile(member)
            if extracted is None:
                fail(f"{label} is unreadable")
            payload = extracted.read(limit + 1)
            if len(payload) != member.size or len(payload) > limit:
                fail(f"{label} size conflicts with its tar member")
            return bytes(payload)

        def verify_blob(value: str, digest: str, size: int, label: str) -> bytes:
            member = files.get(value)
            if member is None or member.size != size:
                fail(f"{label} blob size mismatch")
            extracted = archive.extractfile(member)
            if extracted is None:
                fail(f"{label} blob is unreadable")
            hasher = hashlib.sha256()
            observed = 0
            chunks: list[bytes] | None = [] if size <= MAX_JSON else None
            while chunk := extracted.read(1024 * 1024):
                observed += len(chunk)
                if observed > size:
                    fail(f"{label} blob exceeds its descriptor size")
                hasher.update(chunk)
                if chunks is not None:
                    chunks.append(chunk)
            if observed != size or f"sha256:{hasher.hexdigest()}" != digest:
                fail(f"{label} blob digest or size mismatch")
            return b"" if chunks is None else b"".join(chunks)

        docker_manifest = parse_json(
            read_member("manifest.json", 1024 * 1024, "image manifest.json"),
            "image manifest.json",
        )
        if not isinstance(docker_manifest, list) or len(docker_manifest) != 1:
            fail("image bundle must contain exactly one image")
        entry = docker_manifest[0]
        if not isinstance(entry, dict) or set(entry) != {"Config", "RepoTags", "Layers"}:
            fail("image manifest.json fields conflict")
        if entry["RepoTags"] != [expected_tag]:
            fail("image bundle tag membership mismatch")
        if not isinstance(entry["Config"], str) or not isinstance(
            entry["Layers"], list
        ) or any(not isinstance(layer, str) for layer in entry["Layers"]):
            fail("image manifest references are invalid")
        config_path = safe_path(entry["Config"])
        layer_paths = [safe_path(layer) for layer in entry["Layers"]]
        if not layer_paths or len(layer_paths) != len(set(layer_paths)):
            fail("image layer references conflict")

        has_layout = "oci-layout" in files
        has_index = "index.json" in files
        if has_layout != has_index:
            fail("image archive format markers conflict")
        if has_layout:
            layout = parse_json(
                read_member("oci-layout", 4096, "OCI layout marker"),
                "OCI layout marker",
            )
            if layout != {"imageLayoutVersion": "1.0.0"}:
                fail("OCI layout marker is invalid")
            index = parse_json(
                read_member("index.json", 1024 * 1024, "OCI index"), "OCI index"
            )
            if not isinstance(index, dict) or set(index) != {
                "schemaVersion",
                "mediaType",
                "manifests",
            }:
                fail("OCI index fields conflict")
            if index["schemaVersion"] != 2 or index["mediaType"] != OCI_INDEX:
                fail("OCI index identity is invalid")
            if not isinstance(index["manifests"], list) or len(index["manifests"]) != 1:
                fail("OCI index must reference exactly one image")
            manifest_digest, manifest_size, manifest_media = descriptor(
                index["manifests"][0],
                "OCI image manifest",
                OCI_MANIFESTS,
                annotations=True,
            )
            if manifest_digest != expected_image_id:
                fail("OCI manifest descriptor is not the candidate image id")
            expected_annotations = {
                "io.containerd.image.name": f"docker.io/library/{expected_tag}",
                "org.opencontainers.image.ref.name": expected_tag.rsplit(":", 1)[1],
            }
            if index["manifests"][0].get("annotations") != expected_annotations:
                fail("OCI index annotations do not bind the isolated candidate tag")
            manifest_path = (
                f"blobs/sha256/{manifest_digest.removeprefix('sha256:')}"
            )
            manifest = parse_json(
                verify_blob(
                    manifest_path, manifest_digest, manifest_size, "OCI image manifest"
                ),
                "OCI image manifest",
            )
            if not isinstance(manifest, dict) or set(manifest) != {
                "schemaVersion",
                "mediaType",
                "config",
                "layers",
            }:
                fail("OCI image manifest fields conflict")
            if manifest["schemaVersion"] != 2 or manifest["mediaType"] != manifest_media:
                fail("OCI image manifest identity conflicts with its descriptor")
            config_digest, config_size, _config_media = descriptor(
                manifest["config"], "OCI image config", OCI_CONFIGS
            )
            if not isinstance(manifest["layers"], list) or not manifest["layers"]:
                fail("OCI image layers are absent")
            layers = [
                descriptor(item, f"OCI layer {position}", OCI_LAYERS)
                for position, item in enumerate(manifest["layers"])
            ]
            digests = [manifest_digest, config_digest, *(item[0] for item in layers)]
            if len(digests) != len(set(digests)):
                fail("OCI descriptor digests are duplicated")
            expected_config_path = (
                f"blobs/sha256/{config_digest.removeprefix('sha256:')}"
            )
            expected_layer_paths = [
                f"blobs/sha256/{digest.removeprefix('sha256:')}"
                for digest, _size, _media in layers
            ]
            if config_path != expected_config_path or layer_paths != expected_layer_paths:
                fail("manifest.json conflicts with OCI descriptor paths")
            config = parse_json(
                verify_blob(
                    config_path, config_digest, config_size, "OCI image config"
                ),
                "OCI image config",
            )
            if not isinstance(config, dict) or config.get("architecture") != "amd64" or config.get(
                "os"
            ) != "linux":
                fail("OCI image config is not the reviewed linux/amd64 target")
            rootfs = config.get("rootfs")
            if (
                not isinstance(rootfs, dict)
                or set(rootfs) != {"type", "diff_ids"}
                or rootfs["type"] != "layers"
                or not isinstance(rootfs["diff_ids"], list)
                or len(rootfs["diff_ids"]) != len(layers)
                or any(
                    not isinstance(item, str) or SHA256_ID.fullmatch(item) is None
                    for item in rootfs["diff_ids"]
                )
            ):
                fail("OCI rootfs does not map exactly to its layers")
            for position, ((digest, size, media), value) in enumerate(
                zip(layers, layer_paths, strict=True)
            ):
                verify_blob(value, digest, size, f"OCI layer {position}")
                extracted = archive.extractfile(files[value])
                if extracted is None:
                    fail("OCI layer is unreadable for diff-id verification")
                stream = (
                    gzip.GzipFile(fileobj=extracted, mode="rb")
                    if media in GZIP_LAYERS
                    else extracted
                )
                hasher = hashlib.sha256()
                uncompressed = 0
                try:
                    while chunk := stream.read(1024 * 1024):
                        uncompressed += len(chunk)
                        if uncompressed > MAX_BLOB:
                            fail("OCI layer uncompressed size is excessive")
                        hasher.update(chunk)
                except (EOFError, OSError, gzip.BadGzipFile):
                    fail("OCI layer compression is invalid")
                if f"sha256:{hasher.hexdigest()}" != rootfs["diff_ids"][position]:
                    fail("OCI layer diff-id conflicts with its config")
            required = {
                "manifest.json",
                "index.json",
                "oci-layout",
                manifest_path,
                config_path,
                *layer_paths,
            }
            if set(files) != required or directories != {"blobs", "blobs/sha256"}:
                fail("OCI image bundle has extra, missing, or dangling members")
        else:
            if any(value.startswith("blobs/sha256/") for value in files):
                fail("classic image archive contains ambiguous OCI blobs")
            config_payload = read_member(config_path, MAX_JSON, "classic image config")
            if f"sha256:{hashlib.sha256(config_payload).hexdigest()}" != expected_image_id:
                fail("classic config digest is not the candidate image id")
            config = parse_json(config_payload, "classic image config")
            if (
                not isinstance(config, dict)
                or config.get("architecture") != "amd64"
                or config.get("os") != "linux"
            ):
                fail("classic image config is not the reviewed linux/amd64 target")
            rootfs = config.get("rootfs")
            if (
                not isinstance(rootfs, dict)
                or set(rootfs) != {"type", "diff_ids"}
                or rootfs["type"] != "layers"
                or not isinstance(rootfs["diff_ids"], list)
                or len(rootfs["diff_ids"]) != len(layer_paths)
                or any(
                    not isinstance(item, str) or SHA256_ID.fullmatch(item) is None
                    for item in rootfs["diff_ids"]
                )
            ):
                fail("classic rootfs does not map exactly to its layers")
            for position, value in enumerate(layer_paths):
                member = files.get(value)
                if member is None or member.size <= 0:
                    fail(f"classic layer {position} is absent or empty")
                extracted = archive.extractfile(member)
                if extracted is None:
                    fail(f"classic layer {position} is unreadable")
                hasher = hashlib.sha256()
                observed = 0
                while chunk := extracted.read(1024 * 1024):
                    observed += len(chunk)
                    if observed > member.size:
                        fail(f"classic layer {position} exceeds its tar member size")
                    hasher.update(chunk)
                if (
                    observed != member.size
                    or f"sha256:{hasher.hexdigest()}" != rootfs["diff_ids"][position]
                ):
                    fail(f"classic layer {position} conflicts with its rootfs diff-id")
            required = {"manifest.json", config_path, *layer_paths}
            allowed_directories = {
                str(parent)
                for value in required
                for parent in pathlib.PurePosixPath(value).parents
                if str(parent) != "."
            }
            if set(files) != required or not directories.issubset(allowed_directories):
                fail("classic image bundle has extra, missing, or dangling members")


def validate_image_source(args: argparse.Namespace) -> None:
    def parse(path: pathlib.Path, label: str) -> list[tuple[str, str]]:
        entries = parse_checksum_manifest(
            path, expected_count=args.expected_count, source_scope=False
        )
        for value, _digest in entries:
            pure = pathlib.PurePosixPath(value)
            if value not in REQUIRED_IMAGE_PATHS and (
                len(pure.parts) < 2
                or pure.parts[0] not in IMAGE_SOURCE_ROOTS
                or pure.suffix not in IMAGE_SOURCE_SUFFIXES
            ):
                fail(f"{label} image source path is outside the exact scope")
        if not REQUIRED_IMAGE_PATHS.issubset(value for value, _digest in entries):
            fail(f"{label} image source manifest omits a root input")
        return entries

    expected = parse(pathlib.Path(args.expected), "expected")
    observed = parse(pathlib.Path(args.observed), "observed")
    if observed != expected:
        fail("candidate image source manifest differs from the reviewed manifest")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    source = commands.add_parser("source")
    source.add_argument("--archive", required=True)
    source.add_argument("--manifest", required=True)
    source.add_argument("--expected-count", required=True, type=int)
    source.add_argument("--paths-output", required=True)
    source.add_argument("--modes-output", required=True)
    source.set_defaults(handler=validate_source)
    manifest = commands.add_parser("manifest")
    manifest.add_argument("--manifest", required=True)
    manifest.add_argument("--expected-count", required=True, type=int)
    manifest.add_argument("--paths-output", required=True)
    manifest.set_defaults(handler=validate_manifest)
    image = commands.add_parser("image")
    image.add_argument("--bundle", required=True)
    image.add_argument("--expected-tag", required=True)
    image.add_argument("--expected-image-id", required=True)
    image.set_defaults(handler=validate_image)
    image_source = commands.add_parser("image-source")
    image_source.add_argument("--observed", required=True)
    image_source.add_argument("--expected", required=True)
    image_source.add_argument("--expected-count", required=True, type=int)
    image_source.set_defaults(handler=validate_image_source)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        args.handler(args)
    except ValueError as exc:
        print(f"artifact validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
