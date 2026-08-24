from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath
from typing import Literal, TypeAlias

from PIL import Image, UnidentifiedImageError

from app.domain.image_similarity import perceptual_dhash
from app.domain.image_validation import validate_image_output

IP_ASSET_MAX_BYTES = 25 * 1024 * 1024
IP_ASSET_MAX_DIMENSION = 8_192
IP_ASSET_MAX_PIXELS = 32_000_000
IP_ASSET_MAX_FREE_TAGS = 20
IP_ASSET_MAX_ZIP_ITEMS = 50
IP_ASSET_MAX_ZIP_BYTES = 250 * 1024 * 1024
IP_ASSET_NAMING_VERSION = "ip-asset-name-v1"
IpAssetSearchVersion: TypeAlias = Literal["ip-asset-hybrid-v2"]
IP_ASSET_SEARCH_VERSION: IpAssetSearchVersion = "ip-asset-hybrid-v2"

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_SAFE_REF = re.compile(r"^ipa_[a-f0-9]{20}$")
_SAFE_GENERATION_REF = re.compile(r"^ipg_[a-f0-9]{20}$")
_SAFE_TAG = re.compile(r"^[^\x00-\x1f\x7f/\\]{1,40}$")
_SPACE = re.compile(r"\s+")
_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class IpAssetCharacter(StrEnum):
    SAI_XIANSHENG = "sai_xiansheng"
    XIAO_SAI = "xiao_sai"
    DUO = "duo"
    OTHER = "other"


class IpAssetType(StrEnum):
    IDENTITY_REFERENCE = "identity_reference"
    PORTRAIT_AVATAR = "portrait_avatar"
    FULL_BODY_ACTION = "full_body_action"
    EXPRESSION = "expression"
    MEME_STICKER = "meme_sticker"
    TRANSPARENT_CUTOUT = "transparent_cutout"
    SCENE_ILLUSTRATION = "scene_illustration"
    POSTER_ELEMENT = "poster_element"
    OTHER = "other"


class IpAssetSource(StrEnum):
    UPLOADED = "uploaded"
    GENERATED = "generated"
    SEED_IMPORT = "seed_import"


class IpAssetStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class IpAssetSemanticStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class IpAssetOrientation(StrEnum):
    SQUARE = "square"
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class IpAssetSearchMode(StrEnum):
    SEMANTIC = "semantic"
    DEGRADED_METADATA = "degraded_metadata"


_CHARACTER_LABELS = {
    IpAssetCharacter.SAI_XIANSHENG: "赛先生",
    IpAssetCharacter.XIAO_SAI: "小赛",
    IpAssetCharacter.DUO: "赛先生与小赛",
    IpAssetCharacter.OTHER: "其他IP",
}
_ASSET_TYPE_LABELS = {
    IpAssetType.IDENTITY_REFERENCE: "形象设定",
    IpAssetType.PORTRAIT_AVATAR: "头像",
    IpAssetType.FULL_BODY_ACTION: "全身动作",
    IpAssetType.EXPRESSION: "表情",
    IpAssetType.MEME_STICKER: "表情包",
    IpAssetType.TRANSPARENT_CUTOUT: "透明底素材",
    IpAssetType.SCENE_ILLUSTRATION: "场景插画",
    IpAssetType.POSTER_ELEMENT: "海报元素",
    IpAssetType.OTHER: "其他",
}


class IpAssetValidationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__("IP asset upload failed validation")
        self.code = code


@dataclass(frozen=True, slots=True)
class IpAssetMetadata:
    character: IpAssetCharacter
    asset_type: IpAssetType
    department: str = ""
    contributor: str = ""
    emotion: str = ""
    action: str = ""
    scene: str = ""
    intended_use: str = ""
    style: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name, maximum in (
            ("department", 80),
            ("contributor", 80),
            ("emotion", 40),
            ("action", 40),
            ("scene", 60),
            ("intended_use", 60),
            ("style", 40),
        ):
            value = normalize_optional_text(getattr(self, field_name), maximum=maximum)
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "tags", normalize_tags(self.tags))


@dataclass(frozen=True, slots=True)
class ValidatedIpAssetUpload:
    body: bytes
    media_type: str
    extension: str
    safe_original_filename: str
    byte_size: int
    width: int
    height: int
    has_alpha: bool
    orientation: IpAssetOrientation
    sha256: str
    perceptual_hash: str


def normalize_optional_text(value: str, *, maximum: int) -> str:
    normalized = _SPACE.sub(" ", unicodedata.normalize("NFKC", value)).strip()
    if len(normalized) > maximum or _CONTROL_CHARACTERS.search(normalized):
        raise ValueError("IP asset metadata is invalid")
    return normalized


def normalize_tags(tags: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    values: list[str] = []
    for raw in tags:
        value = normalize_optional_text(raw, maximum=40).casefold()
        if not value or _SAFE_TAG.fullmatch(value) is None:
            raise ValueError("IP asset tag is invalid")
        if value not in values:
            values.append(value)
    if len(values) > IP_ASSET_MAX_FREE_TAGS:
        raise ValueError("IP asset has too many tags")
    return tuple(sorted(values))


def parse_tags(value: str) -> tuple[str, ...]:
    return normalize_tags([item for item in re.split(r"[,\uFF0C\n]", value) if item.strip()])


def validate_asset_ref(value: str) -> str:
    normalized = value.strip().casefold()
    if _SAFE_REF.fullmatch(normalized) is None:
        raise ValueError("IP asset reference is invalid")
    return normalized


def validate_generation_ref(value: str) -> str:
    normalized = value.strip().casefold()
    if _SAFE_GENERATION_REF.fullmatch(normalized) is None:
        raise ValueError("IP asset generation reference is invalid")
    return normalized


def validate_ip_asset_upload(
    *, filename: str, declared_media_type: str | None, body: bytes
) -> ValidatedIpAssetUpload:
    media_type = (declared_media_type or "").split(";", 1)[0].strip().casefold()
    result = validate_image_output(
        body,
        media_type,
        expected_dimensions=None,
        max_bytes=IP_ASSET_MAX_BYTES,
        max_dimension=IP_ASSET_MAX_DIMENSION,
        max_pixels=IP_ASSET_MAX_PIXELS,
    )
    if not result.passed:
        raise IpAssetValidationError(
            result.issue_codes[0] if result.issue_codes else "invalid_raster"
        )
    try:
        Image.MAX_IMAGE_PIXELS = IP_ASSET_MAX_PIXELS
        with Image.open(io.BytesIO(body)) as opened:
            opened.seek(0)
            opened.load()
            width, height = opened.size
            has_alpha = "A" in opened.getbands() or "transparency" in opened.info
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as error:
        raise IpAssetValidationError("invalid_raster") from error
    if result.width != width or result.height != height:
        raise IpAssetValidationError("dimension_mismatch")
    if not _has_exact_raster_container_length(body, media_type):
        # Pillow intentionally tolerates bytes after a decoded raster. User uploads are durable
        # originals, so reject trailing payloads instead of accepting image/polyglot containers.
        raise IpAssetValidationError("invalid_raster")
    extensions = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
    extension = extensions.get(media_type)
    if extension is None:
        raise IpAssetValidationError("unsupported_media_type")
    original = safe_original_filename(filename, extension=extension)
    return ValidatedIpAssetUpload(
        body=body,
        media_type=media_type,
        extension=extension,
        safe_original_filename=original,
        byte_size=len(body),
        width=width,
        height=height,
        has_alpha=has_alpha,
        orientation=orientation_for(width, height),
        sha256=hashlib.sha256(body).hexdigest(),
        perceptual_hash=perceptual_dhash(body),
    )


def safe_original_filename(filename: str, *, extension: str) -> str:
    raw_name = PurePath(filename.replace("\\", "/")).name
    stem = PurePath(raw_name).stem
    normalized = unicodedata.normalize("NFKC", stem).strip()
    normalized = _CONTROL_CHARACTERS.sub("", normalized)
    normalized = normalized[:160].strip(" .") or "asset"
    return f"{normalized}.{extension}"


def orientation_for(width: int, height: int) -> IpAssetOrientation:
    ratio = width / height
    if 0.92 <= ratio <= 1.08:
        return IpAssetOrientation.SQUARE
    return IpAssetOrientation.LANDSCAPE if width > height else IpAssetOrientation.PORTRAIT


def canonical_name_base(
    metadata: IpAssetMetadata, orientation: IpAssetOrientation
) -> tuple[str, str]:
    semantic = metadata.emotion or metadata.action
    context = metadata.scene or metadata.intended_use
    format_label = {
        IpAssetOrientation.SQUARE: "方图",
        IpAssetOrientation.PORTRAIT: "竖图",
        IpAssetOrientation.LANDSCAPE: "横图",
    }[orientation]
    display_segments = [
        _CHARACTER_LABELS[metadata.character],
        _ASSET_TYPE_LABELS[metadata.asset_type],
        semantic,
        context,
        format_label,
    ]
    display = "-".join(value for value in display_segments if value)
    slug_parts = [
        metadata.character.value,
        metadata.asset_type.value,
        ascii_slug(semantic),
        ascii_slug(context),
        orientation.value,
    ]
    slug = "-".join(value for value in slug_parts if value)[:220].strip("-")
    name_key = hashlib.sha256(f"{IP_ASSET_NAMING_VERSION}\0{display}".encode()).hexdigest()
    return display, f"{name_key}:{slug}"


def versioned_canonical_name(display_base: str, slug: str, version: int) -> tuple[str, str]:
    if version < 1 or version > 999:
        raise ValueError("IP asset name version is invalid")
    suffix = f"v{version:03d}"
    return f"{display_base}-{suffix}", f"{slug}-{suffix}"


def canonical_download_filename(canonical_slug: str, media_type: str) -> str:
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(media_type)
    if extension is None:
        raise ValueError("IP asset media type is unsupported")
    safe = _FILENAME_UNSAFE.sub("-", canonical_slug).strip("-._")[:220]
    return f"{safe or 'ip-asset'}.{extension}"


def ascii_slug(value: str) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode().casefold()
    safe = _FILENAME_UNSAFE.sub("-", ascii_value).strip("-._")
    if safe:
        return safe[:48]
    return hashlib.sha256(value.encode()).hexdigest()[:10]


def _has_exact_raster_container_length(body: bytes, media_type: str) -> bool:
    if media_type == "image/png":
        # A valid PNG ends with the fixed-length IEND chunk. Full chunk/CRC validation remains
        # Pillow's responsibility; this fence ensures nothing follows the raster container.
        return len(body) >= 12 and body[-12:-8] == b"\x00\x00\x00\x00" and body[-8:-4] == b"IEND"
    if media_type == "image/jpeg":
        return body.endswith(b"\xff\xd9")
    if media_type == "image/webp":
        return (
            len(body) >= 12
            and body[:4] == b"RIFF"
            and int.from_bytes(body[4:8], "little") + 8 == len(body)
        )
    return False
