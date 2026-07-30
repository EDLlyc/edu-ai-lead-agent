#!/usr/bin/env python3
"""Build a private manifest for visual assets without ingesting them into text RAG."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Any

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_WEDRIVE_MARKER = ":com.tencent.wedrive."
_MAX_ASSET_BYTES = 25 * 1024 * 1024
_MAX_ASSET_DIMENSION = 8_192
_MAX_ASSET_PIXELS = 32_000_000
_MAX_DISCOVERED_FILES = 10_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _png_metadata(path: Path) -> dict[str, Any] | None:
    with path.open("rb") as stream:
        header = stream.read(33)
        try:
            stream.seek(-12, 2)
        except OSError:
            return None
        trailer = stream.read(12)
    if (
        len(header) != 33
        or not header.startswith(_PNG_SIGNATURE)
        or header[8:12] != b"\x00\x00\x00\r"
        or header[12:16] != b"IHDR"
        or struct.unpack(">I", header[29:33])[0] != zlib.crc32(header[12:29])
        or header[24] not in {1, 2, 4, 8, 16}
        or header[25] not in {0, 2, 3, 4, 6}
        or header[26:29] != b"\x00\x00\x00"
        or trailer[:8] != b"\x00\x00\x00\x00IEND"
        or struct.unpack(">I", trailer[8:12])[0] != zlib.crc32(b"IEND")
    ):
        return None
    width, height = struct.unpack(">II", header[16:24])
    color_type = header[25]
    if (
        width < 1
        or height < 1
        or width > _MAX_ASSET_DIMENSION
        or height > _MAX_ASSET_DIMENSION
        or width * height > _MAX_ASSET_PIXELS
    ):
        return None
    return {
        "media_type": "image/png",
        "width": width,
        "height": height,
        "has_alpha": color_type in {4, 6},
    }


def _safe_relative_path(path: Path, root: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
        return resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None


def _character_tags(filename: str) -> list[str]:
    tags: list[str] = []
    if "\u5c0f\u8d5b" in filename:
        tags.append("xiao-sai")
    if "\u8d5b\u5148\u751f" in filename:
        tags.append("sai-xiansheng")
    return tags


def build_manifest(materials_root: Path) -> dict[str, Any]:
    materials_root = materials_root.resolve(strict=True)
    asset_roots = (
        ("image-example", materials_root / "03-image-examples"),
        ("visual-asset", materials_root / "05-visual-assets"),
    )
    assets: list[dict[str, Any]] = []
    skipped_sidecars = 0
    skipped_unsupported = 0
    discovered_files = 0
    for category, asset_root in asset_roots:
        if not asset_root.exists():
            continue
        for path in sorted(asset_root.rglob("*"), key=lambda item: item.as_posix()):
            discovered_files += 1
            if discovered_files > _MAX_DISCOVERED_FILES:
                raise ValueError(
                    "brand asset discovery exceeded the configured file limit"
                )
            if path.is_symlink():
                skipped_unsupported += 1
                continue
            relative_path = _safe_relative_path(path, materials_root)
            if relative_path is None or not path.is_file() or path.name == ".gitignore":
                continue
            if _WEDRIVE_MARKER in path.name:
                skipped_sidecars += 1
                continue
            try:
                byte_size = path.stat().st_size
            except OSError:
                skipped_unsupported += 1
                continue
            if byte_size < 33 or byte_size > _MAX_ASSET_BYTES:
                skipped_unsupported += 1
                continue
            metadata = _png_metadata(path)
            if metadata is None:
                skipped_unsupported += 1
                continue
            assets.append(
                {
                    "asset_id": _sha256(path),
                    "relative_path": relative_path.as_posix(),
                    "category": category,
                    "filename": path.name,
                    "byte_size": byte_size,
                    "characters": _character_tags(path.name),
                    **metadata,
                }
            )
    return {
        "schema_version": "brand-visual-assets-v1",
        "private": True,
        "text_rag_eligible": False,
        "asset_count": len(assets),
        "skipped_sidecar_count": skipped_sidecars,
        "skipped_unsupported_count": skipped_unsupported,
        "assets": assets,
    }


def resolve_manifest_output(
    materials_root: Path, requested_output: Path | None
) -> Path:
    materials_root = materials_root.resolve(strict=True)
    candidate = requested_output or materials_root / "visual-assets.manifest.json"
    if candidate.is_symlink():
        raise ValueError("manifest output must not be a symbolic link")
    output = candidate.resolve()
    try:
        output.relative_to(materials_root)
    except ValueError:
        raise ValueError(
            "manifest output must remain inside the materials root"
        ) from None
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--materials-root",
        type=Path,
        default=Path("private/brand-materials"),
    )
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    materials_root = arguments.materials_root.resolve()
    try:
        output = resolve_manifest_output(materials_root, arguments.output)
    except ValueError as error:
        parser.error(str(error))
    manifest = build_manifest(materials_root)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "asset_count": manifest["asset_count"],
                "skipped_sidecar_count": manifest["skipped_sidecar_count"],
                "skipped_unsupported_count": manifest["skipped_unsupported_count"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
