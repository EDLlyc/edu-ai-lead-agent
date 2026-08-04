from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.application.ports.image_generation import ImageReference
from app.domain.visual_assets import (
    AssetSelectionRequest,
    AssetSelector,
    SelectedVisualAsset,
    VisualAsset,
    VisualAssetCatalog,
    VisualAssetError,
    VisualAssetSelection,
)

_MAX_MANIFEST_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class LoadedVisualCatalog:
    catalog: VisualAssetCatalog
    materials_root: Path


def load_visual_catalog(manifest_path: str | Path) -> LoadedVisualCatalog:
    """Load a private catalog without allowing paths or symlinks to escape its root."""

    path = Path(manifest_path)
    if path.is_symlink() or not path.is_file():
        raise VisualAssetError("visual asset manifest is unavailable")
    resolved_manifest = path.resolve(strict=True)
    materials_root = resolved_manifest.parent
    if resolved_manifest.stat().st_size > _MAX_MANIFEST_BYTES:
        raise VisualAssetError("visual asset manifest is too large")
    try:
        raw_value: object = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise VisualAssetError("visual asset manifest is invalid") from error
    if not isinstance(raw_value, dict):
        raise VisualAssetError("visual asset manifest must be an object")
    if raw_value.get("private") is not True or raw_value.get("text_rag_eligible") is not False:
        raise VisualAssetError("visual asset manifest privacy flags are invalid")
    raw_assets = raw_value.get("assets")
    if not isinstance(raw_assets, list):
        raise VisualAssetError("visual asset manifest assets must be a list")
    schema_version = raw_value.get("schema_version")
    catalog_version = raw_value.get("catalog_version")
    if not isinstance(schema_version, str) or not isinstance(catalog_version, str):
        raise VisualAssetError("visual asset manifest versions are invalid")
    assets = tuple(
        VisualAsset.from_mapping(
            item,
            catalog_schema_version=schema_version,
        )
        for item in raw_assets
        if isinstance(item, dict)
    )
    if len(assets) != len(raw_assets):
        raise VisualAssetError("visual asset manifest contains an invalid asset")
    catalog = VisualAssetCatalog(
        schema_version=schema_version,
        catalog_version=catalog_version,
        assets=assets,
    )
    return LoadedVisualCatalog(catalog=catalog, materials_root=materials_root)


def select_visual_assets(
    loaded: LoadedVisualCatalog,
    request: AssetSelectionRequest,
    *,
    selector_version: str,
    max_references: int,
    max_reference_bytes: int,
) -> VisualAssetSelection:
    selector = AssetSelector(
        loaded.catalog,
        selector_version=selector_version,
        max_references=max_references,
        max_reference_bytes=max_reference_bytes,
    )
    return selector.select(
        request,
        max_references=max_references,
        max_reference_bytes=max_reference_bytes,
    )


def read_selected_reference(
    loaded: LoadedVisualCatalog,
    selected: SelectedVisualAsset,
) -> ImageReference:
    """Recheck the immutable private input immediately before provider use."""

    asset = selected.asset
    asset_path = (loaded.materials_root / asset.relative_path).resolve(strict=True)
    try:
        asset_path.relative_to(loaded.materials_root)
    except ValueError:
        raise VisualAssetError("visual asset path escapes the private materials root") from None
    if asset_path.is_symlink() or not asset_path.is_file():
        raise VisualAssetError("selected visual asset is unavailable")
    body = asset_path.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    if digest != asset.checksum or len(body) != asset.byte_size:
        raise VisualAssetError("selected visual asset checksum changed")
    if len(body) < 24 or body[:8] != b"\x89PNG\r\n\x1a\n" or body[12:16] != b"IHDR":
        raise VisualAssetError("selected visual asset is not a PNG")
    return ImageReference(
        role=selected.role.value,
        asset_id=asset.asset_id,
        filename=asset.filename,
        sha256=asset.checksum,
        image_bytes=body,
        selection_reason=selected.reason,
    )


def visual_asset_summary(selected: SelectedVisualAsset) -> dict[str, Any]:
    asset = selected.asset
    return {
        "asset_id": asset.asset_id,
        "filename": asset.filename,
        "role": selected.role.value,
        "sha256": asset.checksum,
        "byte_size": asset.byte_size,
        "selection_reason": selected.reason,
        "matched_tags": list(selected.matched_tags),
        "fallback": selected.fallback,
    }
