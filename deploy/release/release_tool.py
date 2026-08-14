#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import sys
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from contract import (
    BUNDLE_ALLOWED_PREFIXES,
    BUNDLE_REQUIRED_FILES,
    REQUIRED_GATES,
    SECRET_PATTERNS,
    BuildContract,
    BundleContract,
    ContractError,
    DatabaseContract,
    GateContract,
    ImageContract,
    ReleaseManifest,
    SourceContract,
    alembic_head_from_blobs,
    dump_release_manifest,
    git_blob,
    git_output,
    load_compatibility_declaration,
    load_release_manifest,
    parse_release_manifest,
    read_release_bundle,
    scan_secret_shaped_content,
    sha256_bytes,
    sha256_file,
    split_digest_image,
    validate_commit,
    validate_source_url,
    verify_release_bundle,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PREFIX = "backend/alembic/versions/"
PYTHON_BASE_RE = re.compile(rb"^ARG PYTHON_BASE=([^\s]+)$", re.MULTILINE)


@dataclass(frozen=True)
class GitEntry:
    path: str
    object_id: str
    mode: int
    content: bytes


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=True, sort_keys=True))


def _git_commit(repository: Path, value: str) -> str:
    validate_commit(value)
    resolved = git_output(repository, ["rev-parse", "--verify", f"{value}^{{commit}}"])
    if resolved.decode("ascii").strip() != value:
        raise ContractError("commit does not resolve to the exact requested object")
    return value


def _parse_ls_tree(value: bytes) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    for record in value.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ContractError("unexpected git ls-tree output") from exc
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ContractError(
                f"bundle source must be a regular committed file: {path}"
            )
        results.append((path, object_id, mode))
    return results


def collect_bundle_entries(repository: Path, commit: str) -> list[GitEntry]:
    _git_commit(repository, commit)
    pathspecs = [prefix.rstrip("/") for prefix in BUNDLE_ALLOWED_PREFIXES]
    raw = git_output(
        repository, ["ls-tree", "-rz", "--full-tree", commit, "--", *pathspecs]
    )
    entries: list[GitEntry] = []
    for path, object_id, mode in _parse_ls_tree(raw):
        content = git_output(repository, ["cat-file", "blob", object_id])
        scan_secret_shaped_content(path, content)
        entries.append(
            GitEntry(path, object_id, 0o755 if mode == "100755" else 0o644, content)
        )
    paths = {entry.path for entry in entries}
    if not BUNDLE_REQUIRED_FILES.issubset(paths):
        missing = sorted(BUNDLE_REQUIRED_FILES - paths)
        raise ContractError(
            f"committed release bundle inputs are incomplete: {missing}"
        )
    return sorted(entries, key=lambda item: item.path)


def _tar_info(name: str, size: int, mode: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.size = size
    info.mode = mode
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    return info


def build_bundle(repository: Path, commit: str, output_dir: Path) -> tuple[Path, Path]:
    entries = collect_bundle_entries(repository, commit)
    member_manifest = b"".join(
        f"{sha256_bytes(entry.content)}  {entry.path}\n".encode() for entry in entries
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / f"release-bundle-{commit}.tar.gz"
    external_manifest_path = output_dir / f"release-bundle-{commit}.members.sha256"
    temporary = bundle_path.with_suffix(bundle_path.suffix + ".tmp")
    with (
        temporary.open("wb") as raw_handle,
        gzip.GzipFile(
            fileobj=raw_handle, mode="wb", filename="", mtime=0
        ) as gzip_handle,
        tarfile.open(
            fileobj=gzip_handle, mode="w", format=tarfile.PAX_FORMAT
        ) as archive,
    ):
        for entry in entries:
            archive.addfile(
                _tar_info(entry.path, len(entry.content), entry.mode),
                io.BytesIO(entry.content),
            )
        archive.addfile(
            _tar_info("RELEASE-MEMBERS.sha256", len(member_manifest), 0o644),
            io.BytesIO(member_manifest),
        )
    os.replace(temporary, bundle_path)
    external_manifest_path.write_bytes(member_manifest)
    emit(
        "release_bundle_built",
        commit=commit,
        file=bundle_path.name,
        member_count=len(entries),
        member_manifest_sha256=sha256_bytes(member_manifest),
        sha256=sha256_file(bundle_path),
    )
    return bundle_path, external_manifest_path


def _commit_paths(repository: Path, commit: str, prefix: str) -> list[str]:
    raw = git_output(
        repository, ["ls-tree", "-rz", "--name-only", commit, "--", prefix]
    )
    try:
        return [item.decode("utf-8") for item in raw.split(b"\0") if item]
    except UnicodeDecodeError as exc:
        raise ContractError("committed path is not UTF-8") from exc


def _migration_blobs(repository: Path, commit: str) -> dict[str, bytes]:
    paths = [
        path
        for path in _commit_paths(repository, commit, MIGRATION_PREFIX)
        if path.endswith(".py") and "/__" not in path
    ]
    if not paths:
        raise ContractError("release commit contains no Alembic migrations")
    return {path: git_blob(repository, commit, path) for path in paths}


def _python_base(dockerfile: bytes) -> str:
    match = PYTHON_BASE_RE.search(dockerfile)
    if match is None:
        raise ContractError("Dockerfile does not declare a pinned PYTHON_BASE")
    value = match.group(1).decode("ascii")
    if "@sha256:" not in value:
        raise ContractError("Dockerfile PYTHON_BASE is not digest-pinned")
    return value


def _parse_gate_arguments(values: Sequence[str]) -> tuple[GateContract, ...]:
    gates: list[GateContract] = []
    for value in values:
        if "=" not in value:
            raise ContractError("gate values must use NAME=RESULT_ID")
        name, result_id = value.split("=", 1)
        gates.append(GateContract(name=name, result_id=result_id))
    if {gate.name for gate in gates} != REQUIRED_GATES or len(gates) != len(
        REQUIRED_GATES
    ):
        raise ContractError(
            f"exactly these gates are required: {sorted(REQUIRED_GATES)}"
        )
    return tuple(sorted(gates, key=lambda item: item.name))


def create_manifest(args: argparse.Namespace) -> ReleaseManifest:
    repository = args.repository.resolve()
    commit = _git_commit(repository, args.commit)
    source_url = validate_source_url(args.source_url)
    repository_name, digest = split_digest_image(args.image)
    bundle_path = args.bundle.resolve()
    if bundle_path.name != f"release-bundle-{commit}.tar.gz":
        raise ContractError("release bundle filename must contain the full commit")
    _members, member_manifest = read_release_bundle(bundle_path)

    dockerfile = git_blob(repository, commit, "backend/Dockerfile")
    runtime_lock = git_blob(repository, commit, "backend/requirements/runtime.lock")
    dev_lock = git_blob(repository, commit, "backend/requirements/dev.lock")
    declaration = git_blob(
        repository, commit, "deploy/release/migration-compatibility.json"
    )
    alembic_head = alembic_head_from_blobs(_migration_blobs(repository, commit))
    reviewed, compatible = load_compatibility_declaration(declaration, alembic_head)

    manifest = ReleaseManifest(
        schema_version=1,
        source=SourceContract(commit, commit[:12], source_url),
        image=ImageContract(
            reference=args.image,
            repository=repository_name,
            digest=digest,
            readable_tag=f"git-{commit[:12]}",
        ),
        build=BuildContract(
            created=args.build_timestamp,
            dockerfile_sha256=sha256_bytes(dockerfile),
            python_base=_python_base(dockerfile),
            runtime_lock_sha256=sha256_bytes(runtime_lock),
            dev_lock_sha256=sha256_bytes(dev_lock),
        ),
        bundle=BundleContract(
            file=bundle_path.name,
            sha256=sha256_file(bundle_path),
            member_manifest_sha256=sha256_bytes(member_manifest),
        ),
        database=DatabaseContract(
            alembic_head=alembic_head,
            compatibility_declaration_sha256=sha256_bytes(declaration),
            compatibility_reviewed=reviewed,
            previous_application_compatible=compatible,
        ),
        gates=_parse_gate_arguments(args.gate),
    )
    validated = parse_release_manifest(manifest.as_dict())
    dump_release_manifest(validated, args.output)
    emit(
        "release_manifest_created",
        commit=commit,
        digest=digest,
        file=args.output.name,
        schema_version=validated.schema_version,
    )
    return validated


def verify_source(repository: Path, commit: str) -> None:
    _git_commit(repository, commit)
    head = git_output(repository, ["rev-parse", "HEAD"]).decode("ascii").strip()
    if head != commit:
        raise ContractError("checked-out HEAD does not match the requested commit")
    status = git_output(repository, ["status", "--porcelain", "--untracked-files=no"])
    if status:
        raise ContractError("tracked checkout contains uncommitted changes")
    emit("source_identity_verified", commit=commit)


def check_migration_compatibility(repository: Path, base: str, commit: str) -> None:
    _git_commit(repository, base)
    _git_commit(repository, commit)
    declaration = git_blob(
        repository, commit, "deploy/release/migration-compatibility.json"
    )
    head = alembic_head_from_blobs(_migration_blobs(repository, commit))
    reviewed, compatible = load_compatibility_declaration(declaration, head)
    changed = (
        git_output(
            repository,
            ["diff", "--name-only", f"{base}..{commit}", "--", MIGRATION_PREFIX],
        )
        .decode("utf-8")
        .splitlines()
    )
    migration_changed = any(path.endswith(".py") for path in changed)
    if migration_changed and not reviewed:
        raise ContractError(
            "migration files changed without a reviewed compatibility declaration"
        )
    emit(
        "migration_compatibility_checked",
        alembic_head=head,
        migration_changed=migration_changed,
        previous_application_compatible=compatible,
        reviewed=reviewed,
    )


def scan_committed_secrets(repository: Path, commit: str) -> None:
    _git_commit(repository, commit)
    raw = git_output(repository, ["ls-tree", "-rz", "--full-tree", commit])
    scanned = 0
    for path, object_id, _mode in _parse_ls_tree(raw):
        if path == "deploy/release/contract.py":
            continue
        content = git_output(repository, ["cat-file", "blob", object_id])
        if b"\0" in content:
            continue
        if "/tests/" in f"/{path}":
            # URL-policy fixtures intentionally contain authenticated test URLs. Continue to
            # scan tests for private keys and token-shaped credentials instead of excluding the
            # entire test tree from the release gate.
            for pattern in SECRET_PATTERNS[:-1]:
                if pattern.search(content) is not None:
                    raise ContractError(
                        f"secret-shaped content rejected in committed file: {path}"
                    )
        else:
            scan_secret_shaped_content(path, content)
        scanned += 1
    emit("committed_secret_scan_completed", commit=commit, file_count=scanned)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and verify immutable release artifacts"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bundle = subparsers.add_parser("build-bundle")
    bundle.add_argument("--commit", required=True)
    bundle.add_argument("--output-dir", type=Path, required=True)
    bundle.add_argument("--repository", type=Path, default=PROJECT_ROOT)

    create = subparsers.add_parser("create-manifest")
    create.add_argument("--commit", required=True)
    create.add_argument("--image", required=True)
    create.add_argument("--source-url", required=True)
    create.add_argument("--build-timestamp", required=True)
    create.add_argument("--bundle", type=Path, required=True)
    create.add_argument("--gate", action="append", default=[], required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--repository", type=Path, default=PROJECT_ROOT)

    verify = subparsers.add_parser("verify-bundle")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--expected-commit")
    verify.add_argument("--extract-to", type=Path)

    validate = subparsers.add_parser("validate-manifest")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--expected-commit")

    source = subparsers.add_parser("verify-source")
    source.add_argument("--commit", required=True)
    source.add_argument("--repository", type=Path, default=PROJECT_ROOT)

    migration = subparsers.add_parser("check-migration-compatibility")
    migration.add_argument("--base", required=True)
    migration.add_argument("--commit", required=True)
    migration.add_argument("--repository", type=Path, default=PROJECT_ROOT)

    secret_scan = subparsers.add_parser("scan-committed-secrets")
    secret_scan.add_argument("--commit", required=True)
    secret_scan.add_argument("--repository", type=Path, default=PROJECT_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "build-bundle":
            build_bundle(
                args.repository.resolve(), args.commit, args.output_dir.resolve()
            )
        elif args.command == "create-manifest":
            create_manifest(args)
        elif args.command == "verify-bundle":
            manifest = load_release_manifest(args.manifest)
            if args.expected_commit and manifest.source.commit != args.expected_commit:
                raise ContractError(
                    "release manifest commit does not match expected commit"
                )
            verify_release_bundle(args.bundle, manifest, args.extract_to)
            emit(
                "release_bundle_verified",
                commit=manifest.source.commit,
                digest=manifest.image.digest,
            )
        elif args.command == "validate-manifest":
            manifest = load_release_manifest(args.manifest)
            if args.expected_commit and manifest.source.commit != args.expected_commit:
                raise ContractError(
                    "release manifest commit does not match expected commit"
                )
            emit(
                "release_manifest_verified",
                commit=manifest.source.commit,
                digest=manifest.image.digest,
            )
        elif args.command == "verify-source":
            verify_source(args.repository.resolve(), args.commit)
        elif args.command == "check-migration-compatibility":
            check_migration_compatibility(
                args.repository.resolve(), args.base, args.commit
            )
        elif args.command == "scan-committed-secrets":
            scan_committed_secrets(args.repository.resolve(), args.commit)
        else:
            parser.error("unknown command")
    except ContractError as exc:
        emit("release_contract_failed", reason=str(exc))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
