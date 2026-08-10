from __future__ import annotations

import importlib.util
import struct
import zlib
from pathlib import Path
from types import ModuleType

import pytest


def _load_builder() -> ModuleType:
    path = Path(__file__).parents[3] / "scripts" / "build_brand_asset_manifest.py"
    spec = importlib.util.spec_from_file_location("build_brand_asset_manifest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _png(*, width: int = 2, height: int = 3, color_type: int = 6) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(ihdr))
        + b"IHDR"
        + ihdr
        + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
        + b"\x00\x00\x00\x00IEND\xaeB\x60\x82"
    )


def test_manifest_indexes_png_and_skips_sidecars_symlinks_and_invalid_files(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    materials = tmp_path / "materials"
    visual = materials / "05-visual-assets"
    image_examples = materials / "03-image-examples"
    visual.mkdir(parents=True)
    image_examples.mkdir(parents=True)
    asset = visual / "小赛与赛先生.png"
    asset.write_bytes(_png())
    (visual / "小赛.png:com.tencent.wedrive.fileid").write_text("sidecar")
    (visual / "renamed.png").write_bytes(b"not a png")
    (image_examples / "linked.png").symlink_to(asset)

    manifest = builder.build_manifest(materials)

    assert manifest["private"] is True
    assert manifest["text_rag_eligible"] is False
    assert manifest["schema_version"] == "brand-visual-assets-v2"
    assert manifest["catalog_version"] == "brand-visual-catalog-v1"
    assert manifest["asset_count"] == 1
    assert manifest["skipped_sidecar_count"] == 1
    assert manifest["skipped_unsupported_count"] == 2
    indexed = manifest["assets"][0]
    assert indexed["relative_path"] == "05-visual-assets/小赛与赛先生.png"
    assert indexed["width"] == 2
    assert indexed["height"] == 3
    assert indexed["has_alpha"] is True
    assert indexed["characters"] == ["xiao-sai", "sai-xiansheng"]
    assert indexed["checksum"] == indexed["asset_id"]
    assert indexed["asset_kind"] == "action"
    assert indexed["roles"] == ["action_reference"]
    assert indexed["variant_group"] == "action-science"
    assert indexed["display_name"] == "小赛与赛先生"
    assert indexed["selection_tags"] == ["science", "education", "editorial"]
    assert indexed["approved"] is True
    assert indexed["catalog_schema_version"] == "brand-visual-assets-v2"


def test_manifest_rejects_oversized_dimensions(tmp_path: Path) -> None:
    builder = _load_builder()
    materials = tmp_path / "materials"
    visual = materials / "05-visual-assets"
    visual.mkdir(parents=True)
    (visual / "too-wide.png").write_bytes(_png(width=8_193, height=1))

    manifest = builder.build_manifest(materials)

    assert manifest["asset_count"] == 0
    assert manifest["skipped_unsupported_count"] == 1


def test_manifest_metadata_overrides_are_typed_and_role_consistent(tmp_path: Path) -> None:
    builder = _load_builder()
    materials = tmp_path / "materials"
    visual = materials / "05-visual-assets"
    visual.mkdir(parents=True)
    asset = visual / "scene.png"
    asset.write_bytes(_png())
    (materials / "visual-assets.metadata.json").write_text(
        '{"assets": {"05-visual-assets/scene.png": {'
        '"asset_kind": "identity", "characters": ["xiao-sai"], '
        '"variant_group": "identity-xiao", "display_name": "Xiao", '
        '"selection_tags": ["robotics", "approved"]}}}\n',
        encoding="utf-8",
    )

    indexed = builder.build_manifest(materials)["assets"][0]

    assert indexed["asset_kind"] == "identity"
    assert indexed["roles"] == ["identity_reference"]
    assert indexed["characters"] == ["xiao-sai"]
    assert indexed["variant_group"] == "identity-xiao"
    assert indexed["display_name"] == "Xiao"
    assert indexed["selection_tags"] == ["robotics", "approved"]

    rule_only = builder.build_manifest(materials, include_metadata=False)["assets"][0]
    assert rule_only["asset_kind"] == "action"
    assert rule_only["roles"] == ["action_reference"]
    assert rule_only["topics"] == ["science", "education"]


def test_manifest_metadata_rejects_unsafe_selection_tags(tmp_path: Path) -> None:
    builder = _load_builder()
    materials = tmp_path / "materials"
    visual = materials / "05-visual-assets"
    visual.mkdir(parents=True)
    (visual / "scene.png").write_bytes(_png())
    (materials / "visual-assets.metadata.json").write_text(
        '{"05-visual-assets/scene.png": {"selection_tags": ["robotics/unsafe"]}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="selection_tags"):
        builder.build_manifest(materials)


def test_manifest_output_must_stay_private_and_reject_symbolic_links(tmp_path: Path) -> None:
    builder = _load_builder()
    materials = tmp_path / "materials"
    materials.mkdir()
    outside = tmp_path / "outside.json"
    linked_output = materials / "linked.json"
    linked_output.symlink_to(outside)

    assert builder.resolve_manifest_output(materials, None) == (
        materials / "visual-assets.manifest.json"
    )
    try:
        builder.resolve_manifest_output(materials, outside)
    except ValueError as error:
        assert "inside" in str(error)
    else:
        raise AssertionError("outside manifest output must be rejected")
    try:
        builder.resolve_manifest_output(materials, linked_output)
    except ValueError as error:
        assert "symbolic link" in str(error)
    else:
        raise AssertionError("symbolic-link manifest output must be rejected")
