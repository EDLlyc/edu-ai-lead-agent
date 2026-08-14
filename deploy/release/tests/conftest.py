from __future__ import annotations

import sys
from pathlib import Path

import pytest

RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from contract import (
    REQUIRED_GATES,
    BuildContract,
    BundleContract,
    DatabaseContract,
    GateContract,
    ImageContract,
    ReleaseManifest,
    SourceContract,
)


@pytest.fixture
def release_manifest() -> ReleaseManifest:
    commit = "a" * 40
    digest = "sha256:" + "b" * 64
    repository = "registry.example.test/edu-ai/edu-ai-lead-agent"
    return ReleaseManifest(
        schema_version=1,
        source=SourceContract(
            commit, commit[:12], "https://codeup.example.test/org/repo.git"
        ),
        image=ImageContract(
            f"{repository}@{digest}", repository, digest, f"git-{commit[:12]}"
        ),
        build=BuildContract(
            created="2026-08-14T06:00:00Z",
            dockerfile_sha256="c" * 64,
            python_base="python:3.11-slim@sha256:" + "d" * 64,
            runtime_lock_sha256="e" * 64,
            dev_lock_sha256="f" * 64,
        ),
        bundle=BundleContract(f"release-bundle-{commit}.tar.gz", "1" * 64, "2" * 64),
        database=DatabaseContract(
            alembic_head="20260814_0020",
            compatibility_declaration_sha256="3" * 64,
            compatibility_reviewed=False,
            previous_application_compatible=False,
        ),
        gates=tuple(
            GateContract(name, "flow-run-1") for name in sorted(REQUIRED_GATES)
        ),
    )
