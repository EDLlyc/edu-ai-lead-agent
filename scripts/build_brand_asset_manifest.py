#!/usr/bin/env python3
"""Build a private manifest for visual assets without ingesting them into text RAG."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_WEDRIVE_MARKER = ":com.tencent.wedrive."
_MAX_ASSET_BYTES = 25 * 1024 * 1024
_MAX_ASSET_DIMENSION = 8_192
_MAX_ASSET_PIXELS = 32_000_000
_MAX_DISCOVERED_FILES = 10_000
_MANIFEST_SCHEMA_VERSION = "brand-visual-assets-v2"
_CATALOG_VERSION = "brand-visual-catalog-v1"
_METADATA_FILENAME = "visual-assets.metadata.json"

_IDENTITY_ROLE = "identity_reference"
_ACTION_ROLE = "action_reference"
_STYLE_ROLE = "style_reference"
_ASSET_KINDS = {"identity", "action", "style"}
_SAFE_TAG = re.compile(r"^[^\x00-\x1f\x7f\s/\\]{1,40}$")
_ALLOWED_METADATA_FIELDS = {
    "asset_kind",
    "variant_group",
    "display_name",
    "selection_tags",
    "roles",
    "characters",
    "topics",
    "poses",
    "scene_tags",
    "priority",
    "approved",
    "manual_review_note",
}

# These labels are deliberately small and human-readable. The manifest is a private catalog, so
# the filename rules are only a safe default; a colocated metadata override can narrow or extend
# them after a human review without ever exposing the image bytes to text retrieval.
_KNOWN_METADATA: dict[str, dict[str, Any]] = {
    "天文-赛先生.png": {
        "topics": ["astronomy", "space", "science"],
        "poses": ["explore", "astronaut"],
        "scene_tags": ["space"],
        "priority": 82,
    },
    "小赛举个例子.png": {
        "topics": ["science", "education", "experiment"],
        "poses": ["teach", "point"],
        "scene_tags": ["classroom"],
        "priority": 68,
    },
    "小赛向上指.png": {
        "topics": ["science", "education"],
        "poses": ["point", "teach"],
        "scene_tags": ["classroom"],
        "priority": 66,
    },
    "小赛和赛先生在时光机里看书.png": {
        "topics": ["reading", "science", "education"],
        "poses": ["read", "explore"],
        "scene_tags": ["reading", "editorial"],
        "priority": 88,
    },
    "小赛和赛先生思考.png": {
        "topics": ["reading", "thinking", "science", "education"],
        "poses": ["think", "discuss"],
        "scene_tags": ["reading", "editorial"],
        "priority": 100,
    },
    "小赛和赛先生时光穿越书.png": {
        "topics": ["reading", "science", "education"],
        "poses": ["read", "explore"],
        "scene_tags": ["reading", "editorial"],
        "priority": 86,
    },
    "小赛和赛先生讨论.png": {
        "topics": ["robotics", "ai", "experiment", "science"],
        "poses": ["discuss", "observe"],
        "scene_tags": ["robotics_lab", "experiment"],
        "priority": 96,
    },
    "小赛开课欢迎.png": {
        "topics": ["science", "education"],
        "poses": ["welcome", "teach"],
        "scene_tags": ["classroom"],
        "priority": 64,
    },
    "小赛探测.png": {
        "topics": ["robotics", "ai", "experiment", "science"],
        "poses": ["observe", "explore", "discover"],
        "scene_tags": ["robotics_lab", "experiment"],
        "priority": 92,
    },
    "小赛疑惑.png": {
        "topics": ["science", "experiment", "thinking"],
        "poses": ["question", "think"],
        "scene_tags": ["experiment"],
        "priority": 58,
    },
    "小赛疑问.png": {
        "topics": ["science", "experiment", "thinking"],
        "poses": ["question", "think"],
        "scene_tags": ["experiment"],
        "priority": 56,
    },
    "小赛看书.png": {
        "topics": ["reading", "science", "education"],
        "poses": ["read", "think"],
        "scene_tags": ["reading"],
        "priority": 78,
    },
    "小赛讨论（朝右）.png": {
        "topics": ["robotics", "ai", "science", "education"],
        "poses": ["discuss", "observe"],
        "scene_tags": ["robotics_lab", "classroom"],
        "priority": 84,
    },
    "小赛赛先生时光机.png": {
        "topics": ["reading", "science", "education"],
        "poses": ["read", "explore"],
        "scene_tags": ["reading", "editorial"],
        "priority": 84,
    },
    "赛先生-专业团队.png": {
        "topics": ["science", "education", "brand"],
        "poses": ["teach", "welcome"],
        "scene_tags": ["classroom", "editorial"],
        "priority": 62,
    },
    "赛先生-伸手指.png": {
        "topics": ["science", "education", "experiment"],
        "poses": ["point", "teach"],
        "scene_tags": ["classroom", "experiment"],
        "priority": 70,
    },
    "赛先生-宇航员1.png": {
        "topics": ["astronomy", "space", "science"],
        "poses": ["astronaut", "explore"],
        "scene_tags": ["space"],
        "priority": 86,
    },
    "赛先生-宇航员2.PNG": {
        "topics": ["astronomy", "space", "science"],
        "poses": ["astronaut", "explore"],
        "scene_tags": ["space"],
        "priority": 80,
    },
    "赛先生-宇航员地球仪.png": {
        "topics": ["astronomy", "space", "science"],
        "poses": ["astronaut", "explore"],
        "scene_tags": ["space"],
        "priority": 90,
    },
    "赛先生-探险.png": {
        "topics": ["science", "astronomy", "space", "experiment"],
        "poses": ["explore", "discover"],
        "scene_tags": ["space", "experiment"],
        "priority": 76,
    },
    "赛先生-显微镜.png": {
        "topics": ["robotics", "ai", "experiment", "science"],
        "poses": ["observe", "microscope"],
        "scene_tags": ["robotics_lab", "experiment"],
        "priority": 91,
    },
    "赛先生小赛-双向奔赴.png": {
        "topics": ["science", "education", "teamwork"],
        "poses": ["discuss", "explore"],
        "scene_tags": ["teamwork", "editorial"],
        "priority": 74,
    },
    "赛先生小赛-携手奔跑.png": {
        "topics": ["science", "education", "teamwork"],
        "poses": ["run", "explore"],
        "scene_tags": ["teamwork"],
        "priority": 72,
    },
    "赛先生小赛-空间站.png": {
        "topics": ["astronomy", "space", "science"],
        "poses": ["astronaut", "explore"],
        "scene_tags": ["space_station", "space"],
        "priority": 98,
    },
    "赛先生开课欢迎.png": {
        "topics": ["science", "education"],
        "poses": ["welcome", "teach"],
        "scene_tags": ["classroom"],
        "priority": 63,
    },
    "赛先生讨论（朝左）.png": {
        "topics": ["robotics", "ai", "science", "education"],
        "poses": ["discuss", "observe"],
        "scene_tags": ["robotics_lab", "classroom"],
        "priority": 82,
    },
}


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


def _default_asset_kind(category: str, relative_path: str) -> str:
    if category == "image-example":
        return "style"
    if "logo_and_ip/" in relative_path:
        return "identity"
    return "action"


def _default_variant_group(
    *, asset_kind: str, filename: str, characters: list[str], topics: list[str]
) -> str:
    if asset_kind == "style":
        return "style-default"
    if asset_kind == "identity" and len(characters) == 1:
        return f"identity-{characters[0]}"
    if topics:
        return f"{asset_kind}-{topics[0]}"
    stem = Path(filename).stem.casefold()
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return f"{asset_kind}-{stem or 'default'}"[:80]


def _display_name(filename: str) -> str:
    return Path(filename).stem


def _tag_list(value: object, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"visual asset {field_name} must be a list")
    tags: list[str] = []
    for raw_tag in value:
        if not isinstance(raw_tag, str):
            raise TypeError(f"visual asset {field_name} contains a non-string value")
        tag = raw_tag.strip()
        if tag and tag not in tags:
            if _SAFE_TAG.fullmatch(tag) is None:
                raise ValueError(f"visual asset {field_name} contains an unsafe tag")
            tags.append(tag)
    if len(tags) > 20 or any(len(tag) > 40 for tag in tags):
        raise ValueError(f"visual asset {field_name} is too large")
    return tags


def _metadata_overrides(materials_root: Path) -> dict[str, dict[str, Any]]:
    path = materials_root / _METADATA_FILENAME
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise ValueError("visual asset metadata must be a regular private file")
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("visual asset metadata is not valid JSON") from error
    if not isinstance(raw, Mapping):
        raise TypeError("visual asset metadata must be an object")
    entries = raw.get("assets", raw)
    if not isinstance(entries, Mapping):
        raise TypeError("visual asset metadata assets must be an object")
    overrides: dict[str, dict[str, Any]] = {}
    for raw_path, raw_metadata in entries.items():
        if not isinstance(raw_path, str) or not isinstance(raw_metadata, Mapping):
            raise TypeError("visual asset metadata entries are invalid")
        relative = Path(raw_path)
        if relative.is_absolute() or ".." in relative.parts or "\\" in raw_path:
            raise ValueError("visual asset metadata path must remain relative")
        unknown_fields = set(raw_metadata) - _ALLOWED_METADATA_FIELDS
        if unknown_fields:
            raise ValueError("visual asset metadata contains unsupported fields")
        overrides[relative.as_posix()] = dict(raw_metadata)
    return overrides


def _asset_metadata(
    *,
    category: str,
    filename: str,
    relative_path: str,
    characters: list[str],
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    asset_kind = _default_asset_kind(category, relative_path)
    if asset_kind == "style":
        metadata: dict[str, Any] = {
            "topics": ["science", "education"],
            "poses": [],
            "scene_tags": ["editorial"],
            "priority": 0,
            "approved": False,
        }
    elif asset_kind == "identity":
        metadata = {
            "topics": ["science", "education", "brand"],
            "poses": [],
            "scene_tags": ["brand"],
            "priority": 110 if filename in {"小赛.png", "赛先生.png"} else 96,
            "approved": True,
        }
    else:
        metadata = {
            "topics": ["science", "education"],
            "poses": [],
            "scene_tags": ["editorial"],
            "priority": 50,
            "approved": True,
        }
    metadata.update(_KNOWN_METADATA.get(filename, {}))
    metadata.update(overrides)
    asset_kind = metadata.get("asset_kind", asset_kind)
    if not isinstance(asset_kind, str) or asset_kind not in _ASSET_KINDS:
        raise ValueError("visual asset asset_kind is not allowlisted")
    metadata["asset_kind"] = asset_kind
    expected_role = {
        "identity": _IDENTITY_ROLE,
        "action": _ACTION_ROLE,
        "style": _STYLE_ROLE,
    }[asset_kind]
    roles = metadata.get("roles")
    if roles is not None:
        role_values = _tag_list(roles, field_name="roles")
        if role_values and role_values != [expected_role]:
            raise ValueError("visual asset roles must match asset_kind")
    metadata["roles"] = [expected_role]
    metadata["roles"] = _tag_list(metadata.get("roles"), field_name="roles")
    metadata["topics"] = _tag_list(metadata.get("topics"), field_name="topics")
    metadata["poses"] = _tag_list(metadata.get("poses"), field_name="poses")
    metadata["scene_tags"] = _tag_list(
        metadata.get("scene_tags"), field_name="scene_tags"
    )
    priority = metadata.get("priority", 0)
    if (
        isinstance(priority, bool)
        or not isinstance(priority, int)
        or not 0 <= priority <= 1_000
    ):
        raise ValueError("visual asset priority must be an integer in [0, 1000]")
    approved = metadata.get("approved", False)
    if not isinstance(approved, bool):
        raise TypeError("visual asset approval must be boolean")
    note = metadata.get("manual_review_note")
    if note is not None and (not isinstance(note, str) or len(note) > 240):
        raise ValueError("visual asset review note is invalid")
    metadata["priority"] = priority
    metadata["approved"] = approved
    metadata["manual_review_note"] = note
    metadata["characters"] = _tag_list(
        metadata.get("characters", characters), field_name="characters"
    )
    characters = metadata["characters"]
    variant_group = metadata.get("variant_group")
    if variant_group is None:
        variant_group = _default_variant_group(
            asset_kind=asset_kind,
            filename=filename,
            characters=characters,
            topics=metadata["topics"],
        )
    if not isinstance(variant_group, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", variant_group
    ):
        raise ValueError("visual asset variant_group is invalid")
    metadata["variant_group"] = variant_group
    display_name = metadata.get("display_name", _display_name(filename))
    if (
        not isinstance(display_name, str)
        or not display_name.strip()
        or len(display_name) > 160
    ):
        raise ValueError("visual asset display_name is invalid")
    metadata["display_name"] = display_name.strip()
    selection_tags = metadata.get("selection_tags")
    if selection_tags is None:
        selection_tags = [
            *metadata["topics"],
            *metadata["poses"],
            *metadata["scene_tags"],
        ]
    metadata["selection_tags"] = _tag_list(selection_tags, field_name="selection_tags")
    return metadata


def build_manifest(
    materials_root: Path, *, include_metadata: bool = True
) -> dict[str, Any]:
    materials_root = materials_root.resolve(strict=True)
    overrides = _metadata_overrides(materials_root) if include_metadata else {}
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
            digest = _sha256(path)
            relative_path_string = relative_path.as_posix()
            labels = _asset_metadata(
                category=category,
                filename=path.name,
                relative_path=relative_path_string,
                characters=_character_tags(path.name),
                overrides=overrides.get(relative_path_string, {}),
            )
            assets.append(
                {
                    "asset_id": digest,
                    "sha256": digest,
                    "checksum": digest,
                    "relative_path": relative_path_string,
                    "category": category,
                    "filename": path.name,
                    "byte_size": byte_size,
                    "catalog_schema_version": _MANIFEST_SCHEMA_VERSION,
                    **labels,
                    **metadata,
                }
            )
    return {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "catalog_version": _CATALOG_VERSION,
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
