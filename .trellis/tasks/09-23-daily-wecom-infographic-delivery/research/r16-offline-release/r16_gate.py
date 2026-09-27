#!/usr/bin/env python3
"""Read-only, fixed-base source gate for a future R16 offline OCI release.

This is deliberately not an activation operator. It proves only committed
source ancestry and migration/flag shape; it never builds, migrates, sends,
backs up, or mutates a production host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

BASE_REVISION = "36b24d67b969a433f19c691bb9d12a3c13e00244"
BASE_IMAGE = "sha256:d740275be855c258d2dbaccb180b65e8a14e949070f8597fcca4b3fb984eeb1f"
BASE_ARCHIVE_SHA256 = "35d37e5aa2eb5a348475c8e9225c0a8a4953b842b4ffed51b582b9d3707a464e"
BASE_MANIFEST_SHA256 = (
    "139800ad92c79ecc418e60a38c241f4dc7a1b3f3edbed3119db9e727c878d04b"
)
BASE_SCHEMA = "20260916_0048"
CANDIDATE_SCHEMA = "20260926_0050"
MIGRATIONS = {
    "backend/alembic/versions/20260923_0049_wecom_news_infographics.py": (
        "20260923_0049",
        BASE_SCHEMA,
    ),
    "backend/alembic/versions/20260926_0050_infographic_advisory.py": (
        CANDIDATE_SCHEMA,
        "20260923_0049",
    ),
}
DEFAULT_OFF = (
    "WECOM_INFOGRAPHIC_PRODUCER_ENABLED",
    "WECOM_INFOGRAPHIC_DELIVERY_ENABLED",
    "WECOM_INFOGRAPHIC_TEST_ENABLED",
    "WECOM_INFOGRAPHIC_MORNING_ENABLED",
    "WECOM_INFOGRAPHIC_NOON_ENABLED",
    "WECOM_INFOGRAPHIC_EVENING_ENABLED",
)
SERVICE_FLAGS = {
    "wecom-dispatcher": DEFAULT_OFF[1:],
    "wecom-infographic-producer": (DEFAULT_OFF[0], *DEFAULT_OFF[3:]),
}
PINNED_PYTHON_BASE = (
    b"python:3.11.15-slim-bookworm@sha256:"
    b"d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3"
)


class GateError(RuntimeError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise GateError(code)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )
    require(result.returncode == 0, "git_contract")
    return result.stdout


def validate_committed_contract(blobs: dict[str, bytes]) -> None:
    for path, (revision, parent) in MIGRATIONS.items():
        body = blobs.get(path)
        require(body is not None, "missing_migration")
        assert body is not None
        for name, expected in (("revision", revision), ("down_revision", parent)):
            pattern = rf'(?m)^{name}:\s*str(?:\s*\|\s*None)?\s*=\s*["\']{re.escape(expected)}["\']\s*$'
            require(re.search(pattern.encode(), body) is not None, "migration_lineage")

    declaration = blobs.get("deploy/release/migration-compatibility.json")
    require(declaration is not None, "missing_compatibility")
    assert declaration is not None
    try:
        compatibility: Any = json.loads(declaration)
    except (TypeError, ValueError) as exc:
        raise GateError("compatibility_json") from exc
    require(
        isinstance(compatibility, dict)
        and compatibility.get("alembic_head") == CANDIDATE_SCHEMA
        and compatibility.get("reviewed") is True
        and compatibility.get("previous_application_compatible") is False,
        "compatibility_contract",
    )

    compose = blobs.get("compose.yaml")
    require(compose is not None, "missing_compose")
    assert compose is not None
    for service, names in SERVICE_FLAGS.items():
        match = re.search(
            rb"(?ms)^  " + service.encode() + rb":\s*\n(.*?)(?=^  [a-z][a-z0-9-]*:|\Z)",
            compose,
        )
        require(match is not None, "missing_wecom_service")
        assert match is not None
        body = match.group(1)
        for name in names:
            require(
                re.search(
                    rb"(?m)^      "
                    + name.encode()
                    + rb":\s*\$\{"
                    + name.encode()
                    + rb":-false\}\s*$",
                    body,
                )
                is not None,
                "flag_not_default_off",
            )
        if service == "wecom-infographic-producer":
            require(
                re.search(rb'(?m)^    profiles: \["infographic"\]\s*$', body)
                is not None
                and re.search(
                    rb'(?m)^    command: \["python", "-m", "app.wecom_news_infographic_main"\]\s*$',
                    body,
                )
                is not None,
                "producer_profile_contract",
            )

    dockerfile = blobs.get("backend/Dockerfile")
    require(dockerfile is not None, "missing_dockerfile")
    assert dockerfile is not None
    require(
        b"fonts-noto-cjk" in dockerfile and b"COPY alembic ./alembic" in dockerfile,
        "full_image_required",
    )
    require(
        re.search(rb"(?m)^ARG PYTHON_BASE=" + PINNED_PYTHON_BASE + rb"\s*$", dockerfile)
        is not None,
        "python_base_unpinned",
    )
    # A package name alone resolves against a mutable apt index. The full-image
    # release must use a dated Debian archive and an explicit font version; the
    # resulting image/font hashes are then sealed in the offline OCI manifest.
    require(
        re.search(rb"(?m)^ARG DEBIAN_SNAPSHOT=\d{8}T\d{6}Z\s*$", dockerfile) is not None
        and b"snapshot.debian.org/archive/debian/" in dockerfile,
        "debian_snapshot_unpinned",
    )
    snapshot_source = b"snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}"
    require(
        re.search(
            rb"(?m)^RUN rm(?: -f)? /etc/apt/sources.list.d/debian.sources"
            rb"[ \t]*\\\n[ \t]*&& printf [^\n#]*"
            + re.escape(snapshot_source)
            + rb"[^\n#]*> /etc/apt/sources.list"
            rb"[ \t]*\\\n[ \t]*&& apt-get update\b",
            dockerfile,
        )
        is not None,
        "debian_snapshot_not_applied",
    )
    require(
        re.search(rb"(?m)^ARG FONTS_NOTO_CJK_VERSION=[0-9][^\s]*\s*$", dockerfile)
        is not None
        and re.search(
            rb"(?m)^[ \t]*&& apt-get install --yes --no-install-recommends "
            rb'"fonts-noto-cjk=\$\{FONTS_NOTO_CJK_VERSION\}"',
            dockerfile,
        )
        is not None,
        "font_package_unpinned",
    )


def verify_r15_bundle(bundle: Path) -> None:
    manifest = bundle / "candidate.json"
    archive = bundle / "backend-image.oci.tar.gz"
    operator = bundle / "forward_release.py"
    require(file_sha256(manifest) == BASE_MANIFEST_SHA256, "base_manifest_hash")
    value = json.loads(manifest.read_bytes())
    # The bundle checker is executable code. Authenticate it and its imported
    # support before invoking it, even if the manifest/archive hashes match.
    for filename, key in (
        ("forward_release.py", "operator_sha256"),
        ("r14_support.py", "support_sha256"),
        ("forward_activate.py", "activator_sha256"),
    ):
        expected = value.get(key)
        require(
            isinstance(expected, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected) is not None
            and file_sha256(bundle / filename) == expected,
            "base_checker_hash",
        )
    require(file_sha256(archive) == BASE_ARCHIVE_SHA256, "base_archive_hash")
    require(
        value.get("revision") == BASE_REVISION
        and value.get("image") == BASE_IMAGE
        and value.get("schema") == BASE_SCHEMA
        and value.get("archive_sha256") == BASE_ARCHIVE_SHA256,
        "base_manifest_contract",
    )
    result = subprocess.run(
        [
            "python3",
            str(operator),
            "check",
            "--manifest",
            str(manifest),
            "--manifest-sha256",
            BASE_MANIFEST_SHA256,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=120,
    )
    require(result.returncode == 0, "base_oci_graph")


def check_source(repo: Path, revision: str) -> dict[str, object]:
    require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "revision_shape")
    require(
        git(repo, "rev-parse", revision + "^{commit}").decode().strip() == revision,
        "revision_missing",
    )
    git(repo, "merge-base", "--is-ancestor", BASE_REVISION, revision)
    require(git(repo, "rev-parse", "HEAD").decode().strip() == revision, "head_drift")
    require(git(repo, "status", "--porcelain") == b"", "dirty_release_worktree")
    changed = git(
        repo, "diff", "--name-status", "--no-renames", BASE_REVISION, revision
    )
    for line in changed.decode().splitlines():
        status, path = line.split("\t", 1)
        require(status in {"A", "M"}, "runtime_delete_or_rename")
        require(
            not path.startswith(("frontend/", "backend/requirements/"))
            and path not in {"backend/pyproject.toml", "backend/alembic.ini"},
            "unreviewed_dependency_or_frontend_change",
        )
    for migration in MIGRATIONS:
        require(migration.encode() in changed, "migration_change_missing")
    paths = (
        *MIGRATIONS,
        "deploy/release/migration-compatibility.json",
        "compose.yaml",
        "backend/Dockerfile",
    )
    blobs = {path: git(repo, "show", f"{revision}:{path}") for path in paths}
    validate_committed_contract(blobs)
    return {
        "base_revision": BASE_REVISION,
        "base_image": BASE_IMAGE,
        "base_schema": BASE_SCHEMA,
        "candidate_revision": revision,
        "candidate_schema": CANDIDATE_SCHEMA,
        "changed_files": len(changed.splitlines()),
        "source_gate": "passed",
        "deployment_ready": False,
        "reason": "source gate only; immutable full OCI, protected baseline, verified backup, quality and fixed-group receipts remain separate gates",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--r15-bundle", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify_r15_bundle(args.r15_bundle)
        result = check_source(args.repo, args.revision)
    except (GateError, OSError, subprocess.TimeoutExpired) as exc:
        print(
            json.dumps(
                {"source_gate": "blocked", "code": str(exc), "deployment_ready": False}
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
