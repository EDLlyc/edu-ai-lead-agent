from __future__ import annotations

import hashlib
import json
import re
import struct
import zlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Self

from app.domain.visual_diversity import VISUAL_SELECTOR_V2_VERSION

VISUAL_ASSET_SCHEMA_VERSION = "brand-visual-assets-v2"
VISUAL_ASSET_CATALOG_VERSION = "brand-visual-catalog-v1"
VISUAL_ASSET_SELECTOR_VERSION = "visual-asset-selector-v1"
SUPPORTED_VISUAL_ASSET_SCHEMA_VERSIONS = frozenset(
    {"brand-visual-assets-v1", VISUAL_ASSET_SCHEMA_VERSION}
)
MAX_VISUAL_ASSET_BYTES = 25 * 1024 * 1024
MAX_VISUAL_ASSET_DIMENSION = 8_192
MAX_VISUAL_ASSET_PIXELS = 32_000_000
DEFAULT_MAX_REFERENCE_ASSETS = 3
DEFAULT_MAX_REFERENCE_BYTES = 20 * 1024 * 1024


class VisualAssetRole(StrEnum):
    IDENTITY_REFERENCE = "identity_reference"
    ACTION_REFERENCE = "action_reference"
    STYLE_REFERENCE = "style_reference"

    @classmethod
    def parse(cls, value: str) -> VisualAssetRole:
        aliases = {
            "identity": cls.IDENTITY_REFERENCE,
            "action": cls.ACTION_REFERENCE,
            "style": cls.STYLE_REFERENCE,
        }
        normalized = value.strip().casefold()
        try:
            return aliases.get(normalized, cls(normalized))
        except ValueError as error:
            raise ValueError(f"unsupported visual asset role: {value!r}") from error


class VisualAssetKind(StrEnum):
    """The single intended use of one private catalog asset."""

    IDENTITY = "identity"
    ACTION = "action"
    STYLE = "style"

    @classmethod
    def parse(cls, value: str) -> VisualAssetKind:
        try:
            return cls(value.strip().casefold())
        except ValueError as error:
            raise ValueError(f"unsupported visual asset kind: {value!r}") from error


class VisualAssetReferenceMode(StrEnum):
    SINGLE_REFERENCE = "single_reference"
    SINGLE_FALLBACK = "single_fallback"
    BUDGETED_MULTI_REFERENCE = "budgeted_multi_reference"


class VisualAssetError(ValueError):
    """Base error for invalid private-catalog metadata or selection input."""


class VisualAssetSelectionError(VisualAssetError):
    """Raised when a safe identity-preserving selection cannot be made."""


class VisualAssetCatalogError(VisualAssetError):
    """Raised when a private manifest or one of its files fails validation."""


def _bounded_text(value: object, *, field_name: str, maximum: int = 160) -> str:
    if not isinstance(value, str):
        raise VisualAssetError(f"visual asset {field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise VisualAssetError(f"visual asset {field_name} is blank or too long")
    return normalized


def _text_tuple(
    value: object,
    *,
    field_name: str,
    maximum_items: int = 20,
    maximum_item_length: int = 40,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise VisualAssetError(f"visual asset {field_name} must be a list")
    values: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise VisualAssetError(f"visual asset {field_name} contains a non-string value")
        normalized = item.strip()
        if not normalized or len(normalized) > maximum_item_length:
            raise VisualAssetError(f"visual asset {field_name} contains an invalid tag")
        if normalized not in values:
            values.append(normalized)
    if len(values) > maximum_items:
        raise VisualAssetError(f"visual asset {field_name} contains too many values")
    return tuple(sorted(values))


_SAFE_TAG = re.compile(r"^[^\x00-\x1f\x7f\s/\\]{1,40}$")
_SAFE_VARIANT_GROUP = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")


def _safe_tag_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    values = _text_tuple(value, field_name=field_name, maximum_item_length=40)
    if any(_SAFE_TAG.fullmatch(item) is None for item in values):
        raise VisualAssetError(f"visual asset {field_name} contains an unsafe tag")
    return values


def _safe_variant_group(value: object, *, field_name: str = "variant_group") -> str:
    normalized = _bounded_text(value, field_name=field_name, maximum=80)
    if _SAFE_VARIANT_GROUP.fullmatch(normalized) is None:
        raise VisualAssetError(f"visual asset {field_name} contains unsupported characters")
    return normalized


def _role_for_kind(kind: VisualAssetKind) -> VisualAssetRole:
    return {
        VisualAssetKind.IDENTITY: VisualAssetRole.IDENTITY_REFERENCE,
        VisualAssetKind.ACTION: VisualAssetRole.ACTION_REFERENCE,
        VisualAssetKind.STYLE: VisualAssetRole.STYLE_REFERENCE,
    }[kind]


def _infer_asset_kind(relative_path: str, roles: tuple[VisualAssetRole, ...]) -> VisualAssetKind:
    """Map v1/v2 manifests to the separated role model without trusting old role combinations."""

    if "logo_and_ip/" in relative_path:
        return VisualAssetKind.IDENTITY
    if VisualAssetRole.STYLE_REFERENCE in roles:
        return VisualAssetKind.STYLE
    if VisualAssetRole.ACTION_REFERENCE in roles:
        return VisualAssetKind.ACTION
    if VisualAssetRole.IDENTITY_REFERENCE in roles:
        return VisualAssetKind.IDENTITY
    return VisualAssetKind.ACTION


def _role_tuple(value: object) -> tuple[VisualAssetRole, ...]:
    values = _text_tuple(value, field_name="roles", maximum_item_length=40)
    roles = tuple(
        sorted({VisualAssetRole.parse(item) for item in values}, key=lambda item: item.value)
    )
    if len(roles) > 3:
        raise VisualAssetError("visual asset roles contain too many values")
    return roles


def validate_relative_asset_path(value: str) -> str:
    """Return a safe POSIX-relative manifest path or raise before filesystem access."""

    normalized = _bounded_text(value, field_name="relative_path", maximum=500)
    if "\\" in normalized:
        raise VisualAssetError("visual asset path must use POSIX separators")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise VisualAssetError("visual asset path must remain relative")
    return path.as_posix()


@dataclass(frozen=True, slots=True)
class VisualAsset:
    asset_id: str
    relative_path: str
    filename: str
    category: str
    byte_size: int
    media_type: str
    width: int
    height: int
    has_alpha: bool
    asset_kind: VisualAssetKind | str | None = None
    variant_group: str | None = None
    display_name: str | None = None
    selection_tags: tuple[str, ...] = ()
    characters: tuple[str, ...] = ()
    roles: tuple[VisualAssetRole, ...] = ()
    topics: tuple[str, ...] = ()
    poses: tuple[str, ...] = ()
    scene_tags: tuple[str, ...] = ()
    priority: int = 0
    approved: bool = False
    sha256: str | None = None
    catalog_schema_version: str = VISUAL_ASSET_SCHEMA_VERSION
    manual_review_note: str | None = None

    def __post_init__(self) -> None:
        relative_path = validate_relative_asset_path(self.relative_path)
        if relative_path != self.relative_path:
            object.__setattr__(self, "relative_path", relative_path)
        if PurePosixPath(relative_path).name != self.filename:
            raise VisualAssetError("visual asset filename must match relative_path")
        if len(self.asset_id) != 64 or any(
            character not in "0123456789abcdef" for character in self.asset_id
        ):
            raise VisualAssetError("visual asset id must be a lowercase SHA-256 digest")
        checksum = self.sha256 or self.asset_id
        if len(checksum) != 64 or any(
            character not in "0123456789abcdef" for character in checksum
        ):
            raise VisualAssetError("visual asset checksum must be a lowercase SHA-256 digest")
        if checksum != self.asset_id:
            raise VisualAssetError("visual asset id and checksum must agree")
        object.__setattr__(self, "sha256", checksum)
        if self.media_type != "image/png":
            raise VisualAssetError("only PNG visual assets are supported")
        if not 1 <= self.byte_size <= MAX_VISUAL_ASSET_BYTES:
            raise VisualAssetError("visual asset byte size is outside the safety bound")
        if not 1 <= self.width <= MAX_VISUAL_ASSET_DIMENSION:
            raise VisualAssetError("visual asset width is outside the safety bound")
        if not 1 <= self.height <= MAX_VISUAL_ASSET_DIMENSION:
            raise VisualAssetError("visual asset height is outside the safety bound")
        if self.width * self.height > MAX_VISUAL_ASSET_PIXELS:
            raise VisualAssetError("visual asset pixel count is outside the safety bound")
        if self.priority < 0 or self.priority > 1_000:
            raise VisualAssetError("visual asset priority is outside the safety bound")
        if self.catalog_schema_version not in SUPPORTED_VISUAL_ASSET_SCHEMA_VERSIONS:
            raise VisualAssetError("unsupported visual asset schema version")
        if self.manual_review_note is not None and len(self.manual_review_note) > 240:
            raise VisualAssetError("visual asset review note is too long")
        raw_roles = _role_tuple(self.roles)
        if self.asset_kind is None:
            asset_kind = _infer_asset_kind(relative_path, raw_roles)
        else:
            try:
                asset_kind = VisualAssetKind.parse(str(self.asset_kind))
            except ValueError as error:
                raise VisualAssetError("visual asset asset_kind is invalid") from error
            expected_role = _role_for_kind(asset_kind)
            if raw_roles and raw_roles != (expected_role,):
                raise VisualAssetError("visual asset roles do not match asset_kind")
        expected_role = _role_for_kind(asset_kind)
        object.__setattr__(self, "asset_kind", asset_kind)
        object.__setattr__(self, "roles", (expected_role,))
        variant_group = self.variant_group
        if variant_group is None:
            variant_group = f"{asset_kind.value}-{self.asset_id[:16]}"
        object.__setattr__(self, "variant_group", _safe_variant_group(variant_group))
        display_name = self.display_name or self.filename
        object.__setattr__(
            self,
            "display_name",
            _bounded_text(display_name, field_name="display_name", maximum=160),
        )
        object.__setattr__(
            self, "characters", _text_tuple(self.characters, field_name="characters")
        )
        object.__setattr__(self, "topics", _text_tuple(self.topics, field_name="topics"))
        object.__setattr__(self, "poses", _text_tuple(self.poses, field_name="poses"))
        object.__setattr__(
            self, "scene_tags", _text_tuple(self.scene_tags, field_name="scene_tags")
        )
        selection_tags = _safe_tag_tuple(self.selection_tags, field_name="selection_tags")
        if not selection_tags:
            selection_tags = _safe_tag_tuple(
                (*self.topics, *self.poses, *self.scene_tags),
                field_name="selection_tags",
            )
        object.__setattr__(self, "selection_tags", selection_tags)

    @property
    def checksum(self) -> str:
        assert self.sha256 is not None
        return self.sha256

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, object],
        *,
        catalog_schema_version: str = VISUAL_ASSET_SCHEMA_VERSION,
    ) -> Self:
        def required_string(key: str, maximum: int = 160) -> str:
            return _bounded_text(raw.get(key), field_name=key, maximum=maximum)

        asset_id = required_string("asset_id", 64)
        checksum_value = raw.get("checksum", raw.get("sha256", asset_id))
        checksum = _bounded_text(checksum_value, field_name="checksum", maximum=64)
        byte_size = raw.get("byte_size")
        width = raw.get("width")
        height = raw.get("height")
        priority = raw.get("priority", 0)
        byte_size = _required_int(byte_size, field_name="byte_size")
        width = _required_int(width, field_name="width")
        height = _required_int(height, field_name="height")
        priority = _required_int(priority, field_name="priority")
        has_alpha = raw.get("has_alpha")
        approved = raw.get("approved", False)
        if not isinstance(has_alpha, bool) or not isinstance(approved, bool):
            raise VisualAssetError("visual asset boolean metadata is invalid")
        note = raw.get("manual_review_note")
        if note is not None and not isinstance(note, str):
            raise VisualAssetError("visual asset review note must be a string")
        asset_kind = raw.get("asset_kind")
        if asset_kind is not None and not isinstance(asset_kind, str):
            raise VisualAssetError("visual asset asset_kind must be a string")
        variant_group = raw.get("variant_group")
        if variant_group is not None and not isinstance(variant_group, str):
            raise VisualAssetError("visual asset variant_group must be a string")
        display_name = raw.get("display_name")
        if display_name is not None and not isinstance(display_name, str):
            raise VisualAssetError("visual asset display_name must be a string")
        entry_schema = raw.get("catalog_schema_version")
        if entry_schema is not None and entry_schema != catalog_schema_version:
            raise VisualAssetError("visual asset entry schema version does not match manifest")
        return cls(
            asset_id=asset_id,
            relative_path=required_string("relative_path", 500),
            filename=required_string("filename", 240),
            category=required_string("category", 80),
            byte_size=byte_size,
            media_type=required_string("media_type", 80),
            width=width,
            height=height,
            has_alpha=has_alpha,
            asset_kind=asset_kind,
            variant_group=variant_group,
            display_name=display_name,
            selection_tags=_safe_tag_tuple(raw.get("selection_tags"), field_name="selection_tags"),
            characters=_text_tuple(raw.get("characters"), field_name="characters"),
            roles=_role_tuple(raw.get("roles")),
            topics=_text_tuple(raw.get("topics"), field_name="topics"),
            poses=_text_tuple(raw.get("poses"), field_name="poses"),
            scene_tags=_text_tuple(raw.get("scene_tags"), field_name="scene_tags"),
            priority=priority,
            approved=approved,
            sha256=checksum,
            catalog_schema_version=catalog_schema_version,
            manual_review_note=note,
        )


VisualAssetRecord = VisualAsset


@dataclass(frozen=True, slots=True)
class VisualAssetCatalog:
    schema_version: str
    catalog_version: str
    assets: tuple[VisualAsset, ...]

    def __post_init__(self) -> None:
        if self.schema_version not in SUPPORTED_VISUAL_ASSET_SCHEMA_VERSIONS:
            raise VisualAssetError("visual asset catalog schema version is invalid")
        if not self.catalog_version or len(self.catalog_version) > 80:
            raise VisualAssetError("visual asset catalog version is invalid")
        ids = [asset.asset_id for asset in self.assets]
        paths = [asset.relative_path for asset in self.assets]
        if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
            raise VisualAssetError("visual asset catalog contains duplicate assets")

    @property
    def asset_by_id(self) -> Mapping[str, VisualAsset]:
        return {asset.asset_id: asset for asset in self.assets}


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class VisualAssetCatalogLoader:
    """Load and revalidate a private visual manifest without returning image bytes."""

    def __init__(
        self,
        materials_root: Path,
        manifest_path: Path | None = None,
        *,
        max_asset_bytes: int = MAX_VISUAL_ASSET_BYTES,
    ) -> None:
        try:
            root = materials_root.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise VisualAssetCatalogError("visual asset materials root is unavailable") from error
        if not root.is_dir():
            raise VisualAssetCatalogError("visual asset materials root must be a directory")
        if max_asset_bytes < 1 or max_asset_bytes > MAX_VISUAL_ASSET_BYTES:
            raise VisualAssetCatalogError("visual asset byte bound is invalid")
        self._materials_root = root
        self._manifest_path = manifest_path or root / "visual-assets.manifest.json"
        self._max_asset_bytes = max_asset_bytes

    def load(self) -> VisualAssetCatalog:
        manifest_path = self._safe_manifest_path()
        try:
            raw_value: object = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise VisualAssetCatalogError("visual asset manifest is not valid JSON") from error
        if not isinstance(raw_value, Mapping):
            raise VisualAssetCatalogError("visual asset manifest must be an object")
        if raw_value.get("private") is not True or raw_value.get("text_rag_eligible") is not False:
            raise VisualAssetCatalogError("visual asset manifest privacy flags are invalid")
        schema_version = raw_value.get("schema_version")
        if (
            not isinstance(schema_version, str)
            or schema_version not in SUPPORTED_VISUAL_ASSET_SCHEMA_VERSIONS
        ):
            raise VisualAssetCatalogError("unsupported visual asset manifest schema version")
        catalog_version = raw_value.get("catalog_version")
        if not isinstance(catalog_version, str) or not catalog_version.strip():
            raise VisualAssetCatalogError("visual asset catalog version is missing")
        raw_assets = raw_value.get("assets")
        if not isinstance(raw_assets, list) or len(raw_assets) > 10_000:
            raise VisualAssetCatalogError("visual asset manifest assets are invalid")
        assets: list[VisualAsset] = []
        for raw_asset in raw_assets:
            if not isinstance(raw_asset, Mapping):
                raise VisualAssetCatalogError("visual asset manifest entry is invalid")
            try:
                asset = VisualAsset.from_mapping(
                    raw_asset,
                    catalog_schema_version=schema_version,
                )
            except VisualAssetError as error:
                raise VisualAssetCatalogError("visual asset manifest entry is unsafe") from error
            self._validate_asset_file(asset)
            assets.append(asset)
        asset_count = raw_value.get("asset_count")
        if asset_count is not None and asset_count != len(assets):
            raise VisualAssetCatalogError("visual asset manifest count is inconsistent")
        try:
            return VisualAssetCatalog(
                schema_version=schema_version,
                catalog_version=catalog_version,
                assets=tuple(assets),
            )
        except VisualAssetError as error:
            raise VisualAssetCatalogError("visual asset manifest contains duplicates") from error

    def read_asset(self, asset: VisualAsset) -> bytes:
        """Read one selected asset and verify its file has not changed since cataloging."""

        return self._read_asset_bytes(asset)

    def validate_asset(self, asset: VisualAsset) -> None:
        """Recheck path, signature, size, and checksum without exposing the body."""

        self._validate_asset_file(asset)

    def _safe_manifest_path(self) -> Path:
        candidate = self._manifest_path
        if candidate.is_symlink():
            raise VisualAssetCatalogError("visual asset manifest must not be a symbolic link")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self._materials_root)
        except (OSError, RuntimeError, ValueError) as error:
            raise VisualAssetCatalogError(
                "visual asset manifest must remain inside materials root"
            ) from error
        if not resolved.is_file():
            raise VisualAssetCatalogError("visual asset manifest must be a regular file")
        return resolved

    def _safe_asset_path(self, asset: VisualAsset) -> Path:
        try:
            relative_path = validate_relative_asset_path(asset.relative_path)
        except VisualAssetError as error:
            raise VisualAssetCatalogError("visual asset path is unsafe") from error
        candidate = self._materials_root.joinpath(*PurePosixPath(relative_path).parts)
        current = self._materials_root
        for part in PurePosixPath(relative_path).parts:
            current = current / part
            if current.is_symlink():
                raise VisualAssetCatalogError("visual asset path contains a symbolic link")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self._materials_root)
        except FileNotFoundError as error:
            raise VisualAssetCatalogError("visual asset file is missing") from error
        except (OSError, RuntimeError, ValueError) as error:
            raise VisualAssetCatalogError("visual asset path escapes materials root") from error
        if not resolved.is_file():
            raise VisualAssetCatalogError("visual asset file is missing")
        return resolved

    def _validate_asset_file(self, asset: VisualAsset) -> None:
        self._read_asset_bytes(asset)

    def _read_asset_bytes(self, asset: VisualAsset) -> bytes:
        path = self._safe_asset_path(asset)
        try:
            byte_size = path.stat().st_size
            if byte_size > self._max_asset_bytes:
                raise VisualAssetCatalogError("visual asset exceeds the configured byte bound")
            body = path.read_bytes()
        except OSError as error:
            raise VisualAssetCatalogError("visual asset file cannot be read") from error
        if byte_size != asset.byte_size or len(body) != asset.byte_size:
            raise VisualAssetCatalogError("visual asset byte size changed")
        digest = hashlib.sha256(body).hexdigest()
        if digest != asset.checksum:
            raise VisualAssetCatalogError("visual asset checksum changed")
        dimensions = _png_dimensions(body)
        if dimensions is None:
            raise VisualAssetCatalogError("visual asset PNG signature is invalid")
        if dimensions != (asset.width, asset.height):
            raise VisualAssetCatalogError("visual asset dimensions changed")
        return body


def load_visual_asset_catalog(
    manifest_path: Path,
    materials_root: Path | None = None,
    *,
    max_asset_bytes: int = MAX_VISUAL_ASSET_BYTES,
) -> VisualAssetCatalog:
    """Convenience entry point for callers that do not need repeated asset reads."""

    root = materials_root or manifest_path.parent
    return VisualAssetCatalogLoader(
        root,
        manifest_path,
        max_asset_bytes=max_asset_bytes,
    ).load()


def _png_dimensions(body: bytes) -> tuple[int, int] | None:
    if len(body) < 45 or not body.startswith(_PNG_SIGNATURE):
        return None
    header = body[:33]
    trailer = body[-12:]
    try:
        width, height = struct.unpack(">II", header[16:24])
        bit_depth = header[24]
        color_type = header[25]
        ihdr_crc = struct.unpack(">I", header[29:33])[0]
        iend_crc = struct.unpack(">I", trailer[8:12])[0]
    except struct.error:
        return None
    if not (
        header[8:12] == b"\x00\x00\x00\r"
        and header[12:16] == b"IHDR"
        and ihdr_crc == zlib.crc32(header[12:29])
        and bit_depth in {1, 2, 4, 8, 16}
        and color_type in {0, 2, 3, 4, 6}
        and 1 <= width <= MAX_VISUAL_ASSET_DIMENSION
        and 1 <= height <= MAX_VISUAL_ASSET_DIMENSION
        and width * height <= MAX_VISUAL_ASSET_PIXELS
        and trailer[:8] == b"\x00\x00\x00\x00IEND"
        and iend_crc == zlib.crc32(b"IEND")
    ):
        return None
    return width, height


@dataclass(frozen=True, slots=True)
class AssetSelectionRequest:
    category: str = ""
    topic: str = ""
    asset_tags: tuple[str, ...] = ()
    characters: tuple[str, ...] = ("xiao-sai", "sai-xiansheng")
    main_action: str = ""
    poses: tuple[str, ...] = ()
    reference_roles: tuple[VisualAssetRole, ...] = (
        VisualAssetRole.IDENTITY_REFERENCE,
        VisualAssetRole.ACTION_REFERENCE,
        VisualAssetRole.STYLE_REFERENCE,
    )
    max_references: int = DEFAULT_MAX_REFERENCE_ASSETS
    max_reference_bytes: int = DEFAULT_MAX_REFERENCE_BYTES
    selection_seed: str = ""
    scene: str = ""
    subject: str = ""
    cast: str = ""
    recent_action_asset_ids: tuple[str, ...] = ()
    recent_style_asset_ids: tuple[str, ...] = ()
    recent_variant_groups: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_references < 1 or self.max_references > 3:
            raise VisualAssetError("visual asset reference count must be in [1, 3]")
        if self.max_reference_bytes < 1 or self.max_reference_bytes > 100 * 1024 * 1024:
            raise VisualAssetError("visual asset reference byte budget is invalid")
        roles = tuple(dict.fromkeys(self.reference_roles))
        if VisualAssetRole.IDENTITY_REFERENCE not in roles:
            raise VisualAssetSelectionError("an identity reference is required")
        object.__setattr__(self, "reference_roles", roles)
        object.__setattr__(self, "selection_seed", _normalize_selection_seed(self.selection_seed))
        object.__setattr__(
            self, "asset_tags", _text_tuple(self.asset_tags, field_name="asset_tags")
        )
        object.__setattr__(
            self,
            "characters",
            _text_tuple(self.characters, field_name="characters") or ("xiao-sai", "sai-xiansheng"),
        )
        object.__setattr__(self, "poses", _text_tuple(self.poses, field_name="poses"))
        for field_name in (
            "recent_action_asset_ids",
            "recent_style_asset_ids",
            "recent_variant_groups",
        ):
            maximum_item_length = 128 if field_name.endswith("asset_ids") else 80
            object.__setattr__(
                self,
                field_name,
                _text_tuple(
                    getattr(self, field_name),
                    field_name=field_name,
                    maximum_items=100,
                    maximum_item_length=maximum_item_length,
                ),
            )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> Self:
        def text_value(*keys: str) -> str:
            for key in keys:
                value = raw.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return ""

        raw_roles = raw.get("reference_roles")
        if raw_roles is None:
            roles: tuple[VisualAssetRole, ...] = (
                VisualAssetRole.IDENTITY_REFERENCE,
                VisualAssetRole.ACTION_REFERENCE,
                VisualAssetRole.STYLE_REFERENCE,
            )
        elif not isinstance(raw_roles, (list, tuple)) or not all(
            isinstance(item, str) for item in raw_roles
        ):
            raise VisualAssetError("visual asset reference_roles must be strings")
        else:
            roles = tuple(VisualAssetRole.parse(item) for item in raw_roles)
        return cls(
            category=text_value("category", "visual_category"),
            topic=text_value("topic"),
            asset_tags=_object_string_tuple(raw.get("asset_tags")),
            characters=_object_string_tuple(raw.get("characters")) or ("xiao-sai", "sai-xiansheng"),
            main_action=text_value("main_action", "action"),
            poses=_object_string_tuple(raw.get("poses", raw.get("pose_tags"))),
            reference_roles=roles,
            max_references=_bounded_positive_int(
                raw.get("max_references"),
                default=DEFAULT_MAX_REFERENCE_ASSETS,
                field_name="max_references",
                maximum=3,
            ),
            max_reference_bytes=_bounded_positive_int(
                raw.get("max_reference_bytes"),
                default=DEFAULT_MAX_REFERENCE_BYTES,
                field_name="max_reference_bytes",
                maximum=100 * 1024 * 1024,
            ),
            selection_seed=_normalize_selection_seed(raw.get("selection_seed")),
            scene=text_value("scene"),
            subject=text_value("subject"),
            cast=text_value("cast"),
            recent_action_asset_ids=_object_string_tuple(raw.get("recent_action_asset_ids")),
            recent_style_asset_ids=_object_string_tuple(raw.get("recent_style_asset_ids")),
            recent_variant_groups=_object_string_tuple(raw.get("recent_variant_groups")),
        )


def _object_string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise VisualAssetError("visual asset selection tags must be strings")
    return tuple(value)


def _required_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VisualAssetError(f"visual asset {field_name} must be an integer")
    return value


def _bounded_positive_int(
    value: object,
    *,
    default: int,
    field_name: str,
    maximum: int,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise VisualAssetError(f"visual asset {field_name} is invalid")
    return value


def _normalize_selection_seed(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise VisualAssetError("visual asset selection_seed must be a string")
    normalized = value.strip()
    if len(normalized) > 128 or any(
        character in "\r\n\x00" or character.isspace() for character in normalized
    ):
        raise VisualAssetError("visual asset selection_seed is invalid")
    return normalized


@dataclass(frozen=True, slots=True)
class SelectedVisualAsset:
    asset: VisualAsset
    role: VisualAssetRole
    score: int
    reason: str
    fallback: bool = False
    matched_tags: tuple[str, ...] = ()

    @property
    def asset_id(self) -> str:
        return self.asset.asset_id

    @property
    def filename(self) -> str:
        return self.asset.filename


@dataclass(frozen=True, slots=True)
class VisualAssetSelection:
    catalog_version: str
    selector_version: str
    selection_seed: str
    selected_assets: tuple[SelectedVisualAsset, ...]
    reference_mode: VisualAssetReferenceMode
    total_byte_size: int
    fallback_used: bool

    @property
    def assets(self) -> tuple[VisualAsset, ...]:
        return tuple(item.asset for item in self.selected_assets)

    @property
    def references(self) -> tuple[SelectedVisualAsset, ...]:
        return self.selected_assets

    @property
    def selected(self) -> tuple[SelectedVisualAsset, ...]:
        return self.selected_assets

    @property
    def total_bytes(self) -> int:
        return self.total_byte_size


@dataclass(frozen=True, slots=True)
class _RankedCandidate:
    asset: VisualAsset
    score: int
    matched_tags: tuple[str, ...]
    novelty_repeated: bool = False


_ACTION_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("\u673a\u5668\u4eba", ("robotics", "ai")),
    ("\u5177\u8eab\u667a\u80fd", ("robotics", "ai")),
    ("\u4eba\u5de5\u667a\u80fd", ("ai",)),
    ("\u5929\u6587", ("astronomy", "space")),
    ("\u5b87\u5b99", ("astronomy", "space")),
    ("\u7a7a\u95f4\u7ad9", ("space", "space_station")),
    ("\u9605\u8bfb", ("reading",)),
    ("\u770b\u4e66", ("reading",)),
    ("\u601d\u8003", ("thinking",)),
    ("\u89c2\u5bdf", ("observe",)),
    ("\u63a2\u6d4b", ("observe", "explore")),
    ("\u5b9e\u9a8c", ("experiment",)),
)


class AssetSelector:
    """Select approved private assets with stable scoring and explicit budget fallback."""

    def __init__(
        self,
        catalog: VisualAssetCatalog | Sequence[VisualAsset],
        *,
        selector_version: str = VISUAL_ASSET_SELECTOR_VERSION,
        max_references: int = DEFAULT_MAX_REFERENCE_ASSETS,
        max_reference_bytes: int = DEFAULT_MAX_REFERENCE_BYTES,
    ) -> None:
        if isinstance(catalog, VisualAssetCatalog):
            self._catalog = catalog
        else:
            self._catalog = VisualAssetCatalog(
                schema_version=VISUAL_ASSET_SCHEMA_VERSION,
                catalog_version=VISUAL_ASSET_CATALOG_VERSION,
                assets=tuple(catalog),
            )
        if not selector_version.strip() or len(selector_version) > 80:
            raise VisualAssetError("visual asset selector version is invalid")
        if max_references < 1 or max_references > 3:
            raise VisualAssetError("visual asset reference count must be in [1, 3]")
        if max_reference_bytes < 1:
            raise VisualAssetError("visual asset reference byte budget must be positive")
        self._selector_version = selector_version
        self._max_references = max_references
        self._max_reference_bytes = max_reference_bytes

    def select(
        self,
        request: AssetSelectionRequest | Mapping[str, object] | object | None = None,
        **overrides: object,
    ) -> VisualAssetSelection:
        selection_request = self._coerce_request(request, overrides)
        selection_request = replace(
            selection_request,
            max_references=min(selection_request.max_references, self._max_references),
            max_reference_bytes=min(
                selection_request.max_reference_bytes,
                self._max_reference_bytes,
            ),
        )
        selected: list[SelectedVisualAsset] = []
        remaining_bytes = selection_request.max_reference_bytes
        fallback_used = False
        required_characters = set(selection_request.characters)
        covered_characters: set[str] = set()

        while required_characters - covered_characters:
            ranked = self._rank(
                selection_request,
                VisualAssetRole.IDENTITY_REFERENCE,
                required_characters - covered_characters,
            )
            candidate = self._first_fitting(ranked, selected, remaining_bytes)
            if candidate is None:
                raise VisualAssetSelectionError(
                    "approved identity references cannot cover the requested characters "
                    "within the byte budget"
                )
            selected.append(
                self._selected(candidate, VisualAssetRole.IDENTITY_REFERENCE, fallback=False)
            )
            remaining_bytes -= candidate.asset.byte_size
            covered_characters.update(set(candidate.asset.characters) & required_characters)
            if (
                len(selected) >= selection_request.max_references
                and required_characters - covered_characters
            ):
                raise VisualAssetSelectionError(
                    "reference limit cannot cover the requested characters"
                )

        if VisualAssetRole.ACTION_REFERENCE in selection_request.reference_roles:
            action_satisfied = any(
                VisualAssetRole.ACTION_REFERENCE in item.asset.roles
                and self._action_match_score(item.asset, selection_request) > 0
                for item in selected
            )
            if not action_satisfied and len(selected) < selection_request.max_references:
                ranked = self._rank(selection_request, VisualAssetRole.ACTION_REFERENCE, set())
                candidate = self._first_fitting(ranked, selected, remaining_bytes)
                action_fallback = False
                if candidate is None:
                    fallback_used = True
                else:
                    action_fallback = (
                        not self._action_match_score(candidate.asset, selection_request) > 0
                    )
                    selected.append(
                        self._selected(
                            candidate,
                            VisualAssetRole.ACTION_REFERENCE,
                            fallback=action_fallback,
                        )
                    )
                    remaining_bytes -= candidate.asset.byte_size
                    fallback_used = fallback_used or action_fallback
            elif not action_satisfied:
                fallback_used = True

        if VisualAssetRole.STYLE_REFERENCE in selection_request.reference_roles:
            if len(selected) < selection_request.max_references:
                ranked = self._rank(selection_request, VisualAssetRole.STYLE_REFERENCE, set())
                candidate = self._first_fitting(ranked, selected, remaining_bytes)
                if candidate is not None:
                    selected.append(
                        self._selected(candidate, VisualAssetRole.STYLE_REFERENCE, fallback=False)
                    )
                    remaining_bytes -= candidate.asset.byte_size

        total_byte_size = sum(item.asset.byte_size for item in selected)
        requested_roles = set(selection_request.reference_roles)
        required_roles = requested_roles - {VisualAssetRole.STYLE_REFERENCE}
        covered_roles = {item.role for item in selected}
        if (
            len(selected) == 1
            and len(requested_roles) > 1
            and (fallback_used or not required_roles.issubset(covered_roles))
        ):
            reference_mode = VisualAssetReferenceMode.SINGLE_FALLBACK
        elif len(selected) > 1:
            reference_mode = VisualAssetReferenceMode.BUDGETED_MULTI_REFERENCE
        else:
            reference_mode = VisualAssetReferenceMode.SINGLE_REFERENCE
        return VisualAssetSelection(
            catalog_version=self._catalog.catalog_version,
            selector_version=self._selector_version,
            selection_seed=selection_request.selection_seed,
            selected_assets=tuple(selected),
            reference_mode=reference_mode,
            total_byte_size=total_byte_size,
            fallback_used=fallback_used,
        )

    @staticmethod
    def _coerce_request(
        request: AssetSelectionRequest | Mapping[str, object] | object | None,
        overrides: Mapping[str, object],
    ) -> AssetSelectionRequest:
        if request is None:
            raw: dict[str, object] = dict(overrides)
            return AssetSelectionRequest.from_mapping(raw)
        if isinstance(request, AssetSelectionRequest):
            if not overrides:
                return request
            raw = {
                "category": request.category,
                "topic": request.topic,
                "asset_tags": request.asset_tags,
                "characters": request.characters,
                "main_action": request.main_action,
                "poses": request.poses,
                "reference_roles": request.reference_roles,
                "selection_seed": request.selection_seed,
                "scene": request.scene,
                "subject": request.subject,
                "cast": request.cast,
                "recent_action_asset_ids": request.recent_action_asset_ids,
                "recent_style_asset_ids": request.recent_style_asset_ids,
                "recent_variant_groups": request.recent_variant_groups,
            }
            raw.update(overrides)
            return AssetSelectionRequest.from_mapping(raw)
        if isinstance(request, Mapping):
            raw = dict(request)
            raw.update(overrides)
            return AssetSelectionRequest.from_mapping(raw)
        raw = {
            key: getattr(request, key)
            for key in (
                "category",
                "visual_category",
                "topic",
                "asset_tags",
                "characters",
                "main_action",
                "poses",
                "reference_roles",
                "selection_seed",
                "scene",
                "subject",
                "cast",
                "recent_action_asset_ids",
                "recent_style_asset_ids",
                "recent_variant_groups",
            )
            if hasattr(request, key)
        }
        raw.update(overrides)
        return AssetSelectionRequest.from_mapping(raw)

    def _approved_candidates(self, role: VisualAssetRole) -> tuple[VisualAsset, ...]:
        return tuple(
            asset
            for asset in self._catalog.assets
            if asset.approved
            and role in asset.roles
            and asset.media_type == "image/png"
            and asset.byte_size <= MAX_VISUAL_ASSET_BYTES
        )

    def _rank(
        self,
        request: AssetSelectionRequest,
        role: VisualAssetRole,
        missing_characters: set[str],
    ) -> tuple[_RankedCandidate, ...]:
        requested_tags = self._requested_tags(request)
        candidates: list[_RankedCandidate] = []
        for asset in self._approved_candidates(role):
            character_overlap = set(asset.characters) & set(request.characters)
            missing_overlap = set(asset.characters) & missing_characters
            if (
                role == VisualAssetRole.IDENTITY_REFERENCE
                and missing_characters
                and not missing_overlap
            ):
                continue
            matched_tags = tuple(
                sorted(
                    requested_tags
                    & (
                        set(asset.selection_tags)
                        | set(asset.topics)
                        | set(asset.poses)
                        | set(asset.scene_tags)
                    )
                )
            )
            topic_matches = requested_tags & set(asset.topics)
            action_match_score = self._action_match_score(asset, request)
            score = 1_000
            score += len(character_overlap) * 250
            score += len(matched_tags) * 100
            score += len(topic_matches) * 400
            if request.category and request.category in asset.topics:
                score += 2_000
            if request.topic and request.topic in asset.topics:
                score += 1_800
            if role == VisualAssetRole.IDENTITY_REFERENCE:
                if missing_characters and missing_characters.issubset(set(asset.characters)):
                    score += 1_800
                if len(request.characters) > 1 and set(request.characters).issubset(
                    set(asset.characters)
                ):
                    score += 350
            elif role == VisualAssetRole.ACTION_REFERENCE:
                score += action_match_score * 80
            elif role == VisualAssetRole.STYLE_REFERENCE:
                if request.category and request.category in asset.scene_tags:
                    score += 120
            novelty_repeated = False
            if self._selector_version == VISUAL_SELECTOR_V2_VERSION:
                if role == VisualAssetRole.ACTION_REFERENCE:
                    novelty_repeated = asset.asset_id in request.recent_action_asset_ids
                elif role == VisualAssetRole.STYLE_REFERENCE:
                    novelty_repeated = asset.asset_id in request.recent_style_asset_ids
                if asset.variant_group and asset.variant_group in request.recent_variant_groups:
                    novelty_repeated = True
                if novelty_repeated:
                    score -= 20_000
            candidates.append(
                _RankedCandidate(
                    asset=asset,
                    score=score,
                    matched_tags=matched_tags,
                    novelty_repeated=novelty_repeated,
                )
            )
        return tuple(
            sorted(
                candidates,
                key=lambda item: (
                    -item.score,
                    -item.asset.priority,
                    self._variant_sort_key(item.asset, request.selection_seed),
                    item.asset.asset_id,
                ),
            )
        )

    def _variant_sort_key(self, asset: VisualAsset, selection_seed: str) -> str:
        if not selection_seed:
            return asset.asset_id
        return hashlib.sha256(
            f"{self._selector_version}\0{selection_seed}\0"
            f"{asset.variant_group}\0{asset.asset_id}".encode()
        ).hexdigest()

    @staticmethod
    def _first_fitting(
        ranked: Iterable[_RankedCandidate],
        selected: Sequence[SelectedVisualAsset],
        remaining_bytes: int,
    ) -> _RankedCandidate | None:
        selected_ids = {item.asset.asset_id for item in selected}
        return next(
            (
                candidate
                for candidate in ranked
                if candidate.asset.asset_id not in selected_ids
                and candidate.asset.byte_size <= remaining_bytes
            ),
            None,
        )

    @staticmethod
    def _selected(
        candidate: _RankedCandidate,
        role: VisualAssetRole,
        *,
        fallback: bool,
    ) -> SelectedVisualAsset:
        reason_parts = [f"{role.value} selected"]
        if candidate.matched_tags:
            reason_parts.append("matched tags=" + ",".join(candidate.matched_tags))
        if len(candidate.asset.characters) > 1:
            reason_parts.append("combined-character preference")
        if fallback:
            reason_parts.append("controlled fallback")
        if candidate.novelty_repeated:
            reason_parts.append("novelty exhausted; controlled repeat")
        return SelectedVisualAsset(
            asset=candidate.asset,
            role=role,
            score=candidate.score,
            reason="; ".join(reason_parts),
            fallback=fallback,
            matched_tags=candidate.matched_tags,
        )

    @staticmethod
    def _requested_tags(request: AssetSelectionRequest) -> set[str]:
        tags = set(request.asset_tags)
        if request.category:
            tags.add(request.category)
        if request.topic:
            tags.add(request.topic)
        for marker, aliases in _ACTION_ALIASES:
            if marker in request.main_action:
                tags.update(aliases)
        tags.update(request.poses)
        tags.update(value for value in (request.scene, request.subject, request.cast) if value)
        return tags

    @staticmethod
    def _action_match_score(asset: VisualAsset, request: AssetSelectionRequest) -> int:
        requested_tags = AssetSelector._requested_tags(request)
        return len(
            requested_tags
            & (
                set(asset.selection_tags)
                | set(asset.topics)
                | set(asset.poses)
                | set(asset.scene_tags)
            )
        )


VisualAssetSelector = AssetSelector
