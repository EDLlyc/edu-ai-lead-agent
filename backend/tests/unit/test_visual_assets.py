from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from app.domain.visual_assets import (
    AssetSelectionRequest,
    AssetSelector,
    VisualAsset,
    VisualAssetCatalog,
    VisualAssetCatalogError,
    VisualAssetCatalogLoader,
    VisualAssetError,
    VisualAssetKind,
    VisualAssetReferenceMode,
    VisualAssetRole,
    VisualAssetSelectionError,
)
from app.domain.visual_diversity import VISUAL_SELECTOR_V2_VERSION


def _png(*, width: int = 2, height: int = 3) -> bytes:
    import struct
    import zlib

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(ihdr))
        + b"IHDR"
        + ihdr
        + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
        + b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _asset(
    name: str,
    *,
    characters: tuple[str, ...] = ("xiao-sai", "sai-xiansheng"),
    roles: tuple[VisualAssetRole, ...] = (VisualAssetRole.IDENTITY_REFERENCE,),
    topics: tuple[str, ...] = (),
    poses: tuple[str, ...] = (),
    scene_tags: tuple[str, ...] = (),
    byte_size: int = 100,
    priority: int = 50,
    approved: bool = True,
    asset_kind: VisualAssetKind | None = None,
    variant_group: str | None = None,
) -> VisualAsset:
    digest = hashlib.sha256(name.encode()).hexdigest()
    return VisualAsset(
        asset_id=digest,
        relative_path=f"05-visual-assets/{name}.png",
        filename=f"{name}.png",
        category="visual-asset",
        byte_size=byte_size,
        media_type="image/png",
        width=100,
        height=100,
        has_alpha=True,
        asset_kind=asset_kind,
        variant_group=variant_group,
        characters=characters,
        roles=roles,
        topics=topics,
        poses=poses,
        scene_tags=scene_tags,
        priority=priority,
        approved=approved,
    )


def _catalog(*assets: VisualAsset) -> VisualAssetCatalog:
    return VisualAssetCatalog(
        schema_version="brand-visual-assets-v2",
        catalog_version="brand-visual-catalog-v1",
        assets=assets,
    )


def _manifest_entry(
    root: Path, relative_path: str, body: bytes, **overrides: object
) -> dict[str, object]:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    entry: dict[str, object] = {
        "asset_id": digest,
        "sha256": digest,
        "checksum": digest,
        "relative_path": relative_path,
        "category": "visual-asset",
        "filename": path.name,
        "byte_size": len(body),
        "media_type": "image/png",
        "width": 2,
        "height": 3,
        "has_alpha": True,
        "characters": ["xiao-sai", "sai-xiansheng"],
        "roles": ["identity_reference"],
        "topics": ["science"],
        "poses": [],
        "scene_tags": [],
        "priority": 50,
        "approved": True,
        "catalog_schema_version": "brand-visual-assets-v2",
    }
    entry.update(overrides)
    return entry


def _write_manifest(root: Path, entries: list[dict[str, object]]) -> Path:
    manifest = root / "visual-assets.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "brand-visual-assets-v2",
                "catalog_version": "brand-visual-catalog-v1",
                "private": True,
                "text_rag_eligible": False,
                "asset_count": len(entries),
                "assets": entries,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def test_robotics_selection_keeps_identity_and_action_roles_separate() -> None:
    identity_xiao = _asset(
        "robotics-identity-xiao",
        characters=("xiao-sai",),
        roles=(VisualAssetRole.IDENTITY_REFERENCE,),
        asset_kind=VisualAssetKind.IDENTITY,
        priority=100,
    )
    identity_sai = _asset(
        "robotics-identity-sai",
        characters=("sai-xiansheng",),
        roles=(VisualAssetRole.IDENTITY_REFERENCE,),
        asset_kind=VisualAssetKind.IDENTITY,
        priority=90,
    )
    action = _asset(
        "robotics-action",
        roles=(VisualAssetRole.ACTION_REFERENCE,),
        asset_kind=VisualAssetKind.ACTION,
        topics=("robotics", "ai", "experiment"),
        poses=("observe",),
        priority=40,
    )

    selection = AssetSelector(_catalog(action, identity_sai, identity_xiao)).select(
        AssetSelectionRequest(
            category="robotics",
            asset_tags=("robotics", "experiment"),
            poses=("observe",),
            reference_roles=(
                VisualAssetRole.IDENTITY_REFERENCE,
                VisualAssetRole.ACTION_REFERENCE,
            ),
        )
    )

    assert [item.filename for item in selection.selected_assets] == [
        "robotics-identity-xiao.png",
        "robotics-identity-sai.png",
        "robotics-action.png",
    ]
    assert selection.reference_mode == VisualAssetReferenceMode.BUDGETED_MULTI_REFERENCE
    assert selection.fallback_used is False
    assert [item.role for item in selection.selected_assets] == [
        VisualAssetRole.IDENTITY_REFERENCE,
        VisualAssetRole.IDENTITY_REFERENCE,
        VisualAssetRole.ACTION_REFERENCE,
    ]


def test_structured_asset_kind_rejects_combined_roles() -> None:
    with pytest.raises(VisualAssetError, match="roles"):
        _asset(
            "combined",
            asset_kind=VisualAssetKind.IDENTITY,
            roles=(
                VisualAssetRole.IDENTITY_REFERENCE,
                VisualAssetRole.ACTION_REFERENCE,
            ),
        )


@pytest.mark.parametrize(
    ("category", "asset_tags", "expected"),
    [
        ("astronomy", ("astronomy", "space"), "astronomy.png"),
        ("reading", ("reading",), "reading.png"),
    ],
)
def test_topic_selection_is_content_driven(
    category: str, asset_tags: tuple[str, ...], expected: str
) -> None:
    astronomy = _asset(
        "astronomy",
        topics=("astronomy", "space"),
        roles=(VisualAssetRole.IDENTITY_REFERENCE,),
        asset_kind=VisualAssetKind.IDENTITY,
        poses=("explore",),
    )
    reading = _asset(
        "reading",
        topics=("reading", "science"),
        roles=(VisualAssetRole.IDENTITY_REFERENCE,),
        asset_kind=VisualAssetKind.IDENTITY,
        poses=("read",),
    )

    selection = AssetSelector(_catalog(astronomy, reading)).select(
        AssetSelectionRequest(
            category=category,
            asset_tags=asset_tags,
            characters=("xiao-sai",),
            reference_roles=(VisualAssetRole.IDENTITY_REFERENCE,),
        )
    )

    assert selection.selected_assets[0].filename == expected


def test_v2_avoids_recent_action_asset_while_v1_replays_existing_ranking() -> None:
    identity = _asset(
        "duo-identity",
        roles=(VisualAssetRole.IDENTITY_REFERENCE,),
        asset_kind=VisualAssetKind.IDENTITY,
        priority=100,
    )
    dominant = _asset(
        "dominant-action",
        roles=(VisualAssetRole.ACTION_REFERENCE,),
        asset_kind=VisualAssetKind.ACTION,
        topics=("robotics", "experiment"),
        priority=100,
        variant_group="robot-action-dominant",
    )
    alternate = _asset(
        "alternate-action",
        roles=(VisualAssetRole.ACTION_REFERENCE,),
        asset_kind=VisualAssetKind.ACTION,
        topics=("robotics", "experiment"),
        priority=10,
        variant_group="robot-action-alternate",
    )
    request = AssetSelectionRequest(
        category="robotics",
        asset_tags=("robotics", "experiment"),
        reference_roles=(
            VisualAssetRole.IDENTITY_REFERENCE,
            VisualAssetRole.ACTION_REFERENCE,
        ),
        max_references=2,
        recent_action_asset_ids=(dominant.asset_id,),
        recent_variant_groups=("robot-action-dominant",),
    )

    v1 = AssetSelector(_catalog(identity, dominant, alternate)).select(request)
    v2 = AssetSelector(
        _catalog(identity, dominant, alternate), selector_version=VISUAL_SELECTOR_V2_VERSION
    ).select(request)

    assert v1.selected_assets[1].asset_id == dominant.asset_id
    assert v2.selected_assets[1].asset_id == alternate.asset_id
    assert "novelty exhausted" not in v2.selected_assets[1].reason


def test_v2_records_controlled_repeat_when_novelty_candidates_are_exhausted() -> None:
    identity = _asset(
        "solo-identity",
        characters=("xiao-sai",),
        roles=(VisualAssetRole.IDENTITY_REFERENCE,),
        asset_kind=VisualAssetKind.IDENTITY,
    )
    action = _asset(
        "only-action",
        characters=("xiao-sai",),
        roles=(VisualAssetRole.ACTION_REFERENCE,),
        asset_kind=VisualAssetKind.ACTION,
        topics=("science",),
    )
    selection = AssetSelector(
        _catalog(identity, action), selector_version=VISUAL_SELECTOR_V2_VERSION
    ).select(
        AssetSelectionRequest(
            category="science",
            characters=("xiao-sai",),
            reference_roles=(
                VisualAssetRole.IDENTITY_REFERENCE,
                VisualAssetRole.ACTION_REFERENCE,
            ),
            max_references=2,
            recent_action_asset_ids=(action.asset_id,),
        )
    )

    assert [item.role for item in selection.selected_assets] == [
        VisualAssetRole.IDENTITY_REFERENCE,
        VisualAssetRole.ACTION_REFERENCE,
    ]
    assert "novelty exhausted; controlled repeat" in selection.selected_assets[1].reason


def test_selector_tie_breaks_by_asset_id_after_score_and_priority() -> None:
    lower_id = _asset("tie-a", characters=("xiao-sai",), priority=10, topics=("robotics",))
    higher_id = _asset("tie-b", characters=("xiao-sai",), priority=10, topics=("robotics",))

    selection = AssetSelector(_catalog(higher_id, lower_id)).select(
        AssetSelectionRequest(
            category="robotics",
            asset_tags=("robotics",),
            characters=("xiao-sai",),
            reference_roles=(VisualAssetRole.IDENTITY_REFERENCE,),
        )
    )

    assert selection.selected_assets[0].asset_id == min(lower_id.asset_id, higher_id.asset_id)


def test_unapproved_asset_is_never_selected() -> None:
    unapproved = _asset(
        "unapproved",
        characters=("xiao-sai",),
        topics=("robotics",),
        priority=1_000,
        approved=False,
    )
    approved = _asset(
        "approved",
        characters=("xiao-sai",),
        topics=("robotics",),
        priority=1,
    )

    selection = AssetSelector(_catalog(unapproved, approved)).select(
        AssetSelectionRequest(
            category="robotics",
            characters=("xiao-sai",),
            reference_roles=(VisualAssetRole.IDENTITY_REFERENCE,),
        )
    )

    assert selection.selected_assets[0].asset_id == approved.asset_id


def test_selector_adds_approved_style_reference_after_identity_and_action() -> None:
    identity_action = _asset(
        "robotics-identity",
        characters=("xiao-sai", "sai-xiansheng"),
        roles=(VisualAssetRole.IDENTITY_REFERENCE,),
        asset_kind=VisualAssetKind.IDENTITY,
        topics=("robotics",),
        byte_size=50,
    )
    action = _asset(
        "robotics-action",
        characters=(),
        roles=(VisualAssetRole.ACTION_REFERENCE,),
        asset_kind=VisualAssetKind.ACTION,
        topics=("robotics",),
        byte_size=50,
    )
    style = _asset(
        "robotics-style",
        characters=(),
        roles=(VisualAssetRole.STYLE_REFERENCE,),
        topics=("robotics",),
        scene_tags=("robotics",),
        byte_size=50,
    )

    selection = AssetSelector(_catalog(identity_action, action, style)).select(
        AssetSelectionRequest(
            category="robotics",
            reference_roles=(
                VisualAssetRole.IDENTITY_REFERENCE,
                VisualAssetRole.ACTION_REFERENCE,
                VisualAssetRole.STYLE_REFERENCE,
            ),
            max_reference_bytes=200,
        )
    )

    assert [item.role for item in selection.selected_assets] == [
        VisualAssetRole.IDENTITY_REFERENCE,
        VisualAssetRole.ACTION_REFERENCE,
        VisualAssetRole.STYLE_REFERENCE,
    ]
    assert selection.reference_mode == VisualAssetReferenceMode.BUDGETED_MULTI_REFERENCE
    assert selection.fallback_used is False


def test_missing_optional_style_does_not_mark_selection_as_fallback() -> None:
    identity = _asset(
        "robotics-identity",
        roles=(VisualAssetRole.IDENTITY_REFERENCE,),
        asset_kind=VisualAssetKind.IDENTITY,
        topics=("robotics",),
    )
    action = _asset(
        "robotics-action",
        characters=(),
        roles=(VisualAssetRole.ACTION_REFERENCE,),
        asset_kind=VisualAssetKind.ACTION,
        topics=("robotics",),
    )

    selection = AssetSelector(_catalog(identity, action)).select(
        AssetSelectionRequest(
            category="robotics",
            characters=("xiao-sai", "sai-xiansheng"),
            reference_roles=(
                VisualAssetRole.IDENTITY_REFERENCE,
                VisualAssetRole.ACTION_REFERENCE,
                VisualAssetRole.STYLE_REFERENCE,
            ),
        )
    )

    assert [item.role for item in selection.selected_assets] == [
        VisualAssetRole.IDENTITY_REFERENCE,
        VisualAssetRole.ACTION_REFERENCE,
    ]
    assert selection.reference_mode == VisualAssetReferenceMode.BUDGETED_MULTI_REFERENCE
    assert selection.fallback_used is False


def test_selection_seed_is_stable_and_rotates_equal_variants() -> None:
    first = _asset(
        "variant-a",
        characters=("xiao-sai",),
        roles=(VisualAssetRole.IDENTITY_REFERENCE,),
        asset_kind=VisualAssetKind.IDENTITY,
        variant_group="identity-xiao",
        priority=10,
    )
    second = _asset(
        "variant-b",
        characters=("xiao-sai",),
        roles=(VisualAssetRole.IDENTITY_REFERENCE,),
        asset_kind=VisualAssetKind.IDENTITY,
        variant_group="identity-xiao",
        priority=10,
    )
    selector = AssetSelector(_catalog(first, second))

    def choose(seed: str) -> str:
        return (
            selector.select(
                AssetSelectionRequest(
                    characters=("xiao-sai",),
                    reference_roles=(VisualAssetRole.IDENTITY_REFERENCE,),
                    selection_seed=seed,
                )
            )
            .selected_assets[0]
            .filename
        )

    assert choose("run-1") == choose("run-1")
    assert choose("run-1") != choose("run-2")
    assert (
        selector.select(
            AssetSelectionRequest(
                characters=("xiao-sai",),
                reference_roles=(VisualAssetRole.IDENTITY_REFERENCE,),
                selection_seed="run-1",
            )
        ).selection_seed
        == "run-1"
    )


def test_byte_budget_records_explicit_single_reference_fallback() -> None:
    identity = _asset("identity", byte_size=70)
    action = _asset(
        "action",
        characters=("xiao-sai",),
        roles=(VisualAssetRole.ACTION_REFERENCE,),
        topics=("robotics",),
        byte_size=50,
    )

    selection = AssetSelector(
        _catalog(identity, action),
        max_reference_bytes=100,
    ).select(
        AssetSelectionRequest(
            category="robotics",
            reference_roles=(
                VisualAssetRole.IDENTITY_REFERENCE,
                VisualAssetRole.ACTION_REFERENCE,
            ),
            max_reference_bytes=100,
        )
    )

    assert len(selection.selected_assets) == 1
    assert selection.total_byte_size <= 100
    assert selection.reference_mode == VisualAssetReferenceMode.SINGLE_FALLBACK
    assert selection.fallback_used is True


def test_missing_asset_is_rejected_by_catalog_loader(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    root.mkdir()
    body = _png()
    entry = _manifest_entry(root, "05-visual-assets/missing.png", body)
    (root / "05-visual-assets/missing.png").unlink()
    manifest = _write_manifest(root, [entry])

    with pytest.raises(VisualAssetCatalogError, match=r"missing|file"):
        VisualAssetCatalogLoader(root, manifest).load()


def test_checksum_change_is_rejected_on_read_after_catalog_load(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    root.mkdir()
    original = _png(width=2, height=3)
    entry = _manifest_entry(root, "05-visual-assets/changed.png", original)
    manifest = _write_manifest(root, [entry])
    loader = VisualAssetCatalogLoader(root, manifest)
    catalog = loader.load()
    assert loader.read_asset(catalog.assets[0]) == original
    path = root / "05-visual-assets/changed.png"
    path.write_bytes(_png(width=3, height=2))

    with pytest.raises(VisualAssetCatalogError, match="checksum"):
        loader.read_asset(catalog.assets[0])


def test_manifest_dimensions_must_match_png_header(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    root.mkdir()
    body = _png(width=2, height=3)
    entry = _manifest_entry(root, "05-visual-assets/mismatched.png", body)
    entry["width"] = 3
    manifest = _write_manifest(root, [entry])

    with pytest.raises(VisualAssetCatalogError, match="dimensions"):
        VisualAssetCatalogLoader(root, manifest).load()


def test_path_escape_and_symlink_are_rejected_before_selection(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    root.mkdir()
    body = _png()
    outside = tmp_path / "outside.png"
    outside.write_bytes(body)
    escaping = _manifest_entry(root, "../outside.png", body)
    manifest = _write_manifest(root, [escaping])
    with pytest.raises(VisualAssetCatalogError, match=r"unsafe|relative"):
        VisualAssetCatalogLoader(root, manifest).load()

    valid_entry = _manifest_entry(root, "05-visual-assets/real.png", body)
    alias = root / "05-visual-assets/alias.png"
    alias.symlink_to(root / "05-visual-assets/real.png")
    valid_entry["relative_path"] = "05-visual-assets/alias.png"
    valid_entry["filename"] = "alias.png"
    symlink_manifest = _write_manifest(root, [valid_entry])
    with pytest.raises(VisualAssetCatalogError, match="symbolic"):
        VisualAssetCatalogLoader(root, symlink_manifest).load()


def test_selector_rejects_requests_without_identity_role() -> None:
    asset = _asset("identity", characters=("xiao-sai",))

    with pytest.raises(VisualAssetSelectionError, match="identity"):
        AssetSelector(_catalog(asset)).select(
            AssetSelectionRequest(
                characters=("xiao-sai",),
                reference_roles=(VisualAssetRole.STYLE_REFERENCE,),
            )
        )
