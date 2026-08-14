from __future__ import annotations

import gzip
import io
import json
import tarfile
from dataclasses import replace
from pathlib import Path

import pytest
from contract import (
    BUNDLE_REQUIRED_FILES,
    ContractError,
    ReleaseManifest,
    alembic_head_from_blobs,
    parse_release_manifest,
    read_release_bundle,
    sha256_bytes,
    sha256_file,
    split_digest_image,
    verify_release_bundle,
)


def _bundle(path: Path, extra: tuple[str, bytes] | None = None) -> bytes:
    files = {name: f"contents:{name}\n".encode() for name in BUNDLE_REQUIRED_FILES}
    files["deploy/release/migration-compatibility.json"] = (
        json.dumps(
            {
                "schema_version": 1,
                "alembic_head": "20260814_0020",
                "reviewed": False,
                "previous_application_compatible": False,
                "reason": "No backward compatibility is declared for this test release.",
            },
            sort_keys=True,
        ).encode()
        + b"\n"
    )
    files["backend/alembic/versions/20260814_0020_test.py"] = (
        b'revision = "20260814_0020"\ndown_revision = None\n'
    )
    if extra is not None:
        files[extra[0]] = extra[1]
    member_manifest = b"".join(
        f"{sha256_bytes(content)}  {name}\n".encode()
        for name, content in sorted(files.items())
    )
    with (
        path.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        for name, content in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(content))
        info = tarfile.TarInfo("RELEASE-MEMBERS.sha256")
        info.size = len(member_manifest)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(member_manifest))
    return member_manifest


def test_manifest_parser_accepts_complete_contract(
    release_manifest: ReleaseManifest,
) -> None:
    assert parse_release_manifest(release_manifest.as_dict()) == release_manifest


def test_manifest_parser_rejects_unknown_fields(
    release_manifest: ReleaseManifest,
) -> None:
    value = release_manifest.as_dict()
    value["credential"] = "must-not-exist"
    with pytest.raises(ContractError, match="keys mismatch"):
        parse_release_manifest(value)


def test_manifest_parser_rejects_unreviewed_compatibility(
    release_manifest: ReleaseManifest,
) -> None:
    value = release_manifest.as_dict()
    database = value["database"]
    assert isinstance(database, dict)
    database["previous_application_compatible"] = True
    with pytest.raises(ContractError, match="explicit review"):
        parse_release_manifest(value)


def test_tag_only_image_is_rejected() -> None:
    with pytest.raises(ContractError, match="digest-only"):
        split_digest_image("registry.example.test/edu-ai/app:latest")


def test_bundle_rejects_path_traversal(tmp_path: Path) -> None:
    path = tmp_path / "bundle.tar.gz"
    _bundle(path, ("../escape", b"bad"))
    with pytest.raises(ContractError, match="unsafe bundle member"):
        read_release_bundle(path)
    assert not (tmp_path / "escape").exists()


def test_bundle_rejects_checksum_mismatch(
    tmp_path: Path, release_manifest: ReleaseManifest
) -> None:
    path = tmp_path / release_manifest.bundle.file
    member_manifest = _bundle(path)
    manifest = replace(
        release_manifest,
        bundle=replace(
            release_manifest.bundle,
            sha256=sha256_file(path),
            member_manifest_sha256=sha256_bytes(member_manifest),
        ),
    )
    path.write_bytes(path.read_bytes() + b"corruption")
    with pytest.raises(ContractError, match="checksum mismatch"):
        verify_release_bundle(path, manifest)


def test_bundle_cross_checks_migration_contract(
    tmp_path: Path, release_manifest: ReleaseManifest
) -> None:
    path = tmp_path / release_manifest.bundle.file
    member_manifest = _bundle(path)
    members, _manifest = read_release_bundle(path)
    declaration = members["deploy/release/migration-compatibility.json"][0]
    manifest = replace(
        release_manifest,
        bundle=replace(
            release_manifest.bundle,
            sha256=sha256_file(path),
            member_manifest_sha256=sha256_bytes(member_manifest),
        ),
        database=replace(
            release_manifest.database,
            compatibility_declaration_sha256=sha256_bytes(declaration),
        ),
    )
    verify_release_bundle(path, manifest)
    mismatched = replace(
        manifest,
        database=replace(
            manifest.database,
            compatibility_declaration_sha256="0" * 64,
        ),
    )
    with pytest.raises(ContractError, match="declaration checksum mismatch"):
        verify_release_bundle(path, mismatched)


def test_alembic_head_is_derived_from_revision_graph() -> None:
    blobs = {
        "one.py": b'revision = "one"\ndown_revision = None\n',
        "two.py": b'revision: str = "two"\ndown_revision: str | None = "one"\n',
    }
    assert alembic_head_from_blobs(blobs) == "two"


def test_alembic_graph_rejects_duplicate_revisions() -> None:
    blobs = {
        "one.py": b'revision = "one"\ndown_revision = None\n',
        "duplicate.py": b'revision = "one"\ndown_revision = None\n',
    }
    with pytest.raises(ContractError, match="duplicate migration revision"):
        alembic_head_from_blobs(blobs)


def test_alembic_graph_rejects_missing_parent() -> None:
    blobs = {"one.py": b'revision = "one"\ndown_revision = "missing"\n'}
    with pytest.raises(ContractError, match="missing parents"):
        alembic_head_from_blobs(blobs)


def test_alembic_graph_rejects_disconnected_cycle() -> None:
    blobs = {
        "root.py": b'revision = "root"\ndown_revision = None\n',
        "head.py": b'revision = "head"\ndown_revision = "root"\n',
        "cycle_a.py": b'revision = "cycle_a"\ndown_revision = "cycle_b"\n',
        "cycle_b.py": b'revision = "cycle_b"\ndown_revision = "cycle_a"\n',
    }
    with pytest.raises(ContractError, match="disconnected"):
        alembic_head_from_blobs(blobs)
