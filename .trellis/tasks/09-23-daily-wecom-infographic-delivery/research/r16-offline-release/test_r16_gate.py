from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name("r16_gate.py")
SPEC = importlib.util.spec_from_file_location("r16_gate", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def valid_blobs() -> dict[str, bytes]:
    return {
        next(iter(gate.MIGRATIONS)): (
            b'revision: str = "20260923_0049"\n'
            b'down_revision: str | None = "20260916_0048"\n'
        ),
        list(gate.MIGRATIONS)[1]: (
            b'revision: str = "20260926_0050"\n'
            b'down_revision: str | None = "20260923_0049"\n'
        ),
        "deploy/release/migration-compatibility.json": json.dumps(
            {
                "alembic_head": "20260926_0050",
                "reviewed": True,
                "previous_application_compatible": False,
            }
        ).encode(),
        "compose.yaml": (
            "\n".join(f"{name}: ${{{name}:-false}}" for name in gate.DEFAULT_OFF)
            + '\nprofiles: ["infographic"]\n'
            + 'command: ["python", "-m", "app.wecom_news_infographic_main"]\n'
        ).encode(),
        "backend/Dockerfile": b"RUN apt-get install fonts-noto-cjk\nCOPY alembic ./alembic\n",
    }


def test_valid_committed_contract() -> None:
    gate.validate_committed_contract(valid_blobs())


@pytest.mark.parametrize("field", ["reviewed", "previous_application_compatible"])
def test_migration_declaration_must_be_reviewed_and_forward_only(field: str) -> None:
    blobs = valid_blobs()
    value = json.loads(blobs["deploy/release/migration-compatibility.json"])
    value[field] = not value[field]
    blobs["deploy/release/migration-compatibility.json"] = json.dumps(value).encode()
    with pytest.raises(gate.GateError, match="compatibility_contract"):
        gate.validate_committed_contract(blobs)


def test_non_child_migration_is_rejected() -> None:
    blobs = valid_blobs()
    path = list(gate.MIGRATIONS)[1]
    blobs[path] = blobs[path].replace(b"20260923_0049", b"20260916_0048")
    with pytest.raises(gate.GateError, match="migration_lineage"):
        gate.validate_committed_contract(blobs)


def test_any_enabled_switch_is_rejected() -> None:
    blobs = valid_blobs()
    blobs["compose.yaml"] = blobs["compose.yaml"].replace(
        b"WECOM_INFOGRAPHIC_DELIVERY_ENABLED:-false",
        b"WECOM_INFOGRAPHIC_DELIVERY_ENABLED:-true",
    )
    with pytest.raises(gate.GateError, match="flag_not_default_off"):
        gate.validate_committed_contract(blobs)


def test_missing_font_requires_full_image() -> None:
    blobs = valid_blobs()
    blobs["backend/Dockerfile"] = b"COPY alembic ./alembic\n"
    with pytest.raises(gate.GateError, match="full_image_required"):
        gate.validate_committed_contract(blobs)


def test_r15_bundle_is_fixed_and_graph_verified() -> None:
    bundle = Path("/root/projects/edu-ai-lead-agent/output/moments-r15-36b24d6")
    if not bundle.exists():
        pytest.skip("private local R15 archive absent")
    gate.verify_r15_bundle(bundle)


def test_base_bundle_mutation_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "candidate.json").write_bytes(b"{}")
    (tmp_path / "backend-image.oci.tar.gz").write_bytes(b"test")
    with pytest.raises(gate.GateError, match="base_manifest_hash"):
        gate.verify_r15_bundle(tmp_path)
