from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Final, Literal

from PIL import Image, ImageOps, UnidentifiedImageError

from app.domain.ip_assets import (
    IpAssetCharacter,
    IpAssetType,
    ValidatedIpAssetUpload,
    normalize_optional_text,
    normalize_tags,
)

IP_ASSET_RECOGNITION_POLICY_VERSION: Final[str] = "ip-asset-recognition-v1"
IP_ASSET_RECOGNITION_MAX_IMAGE_BYTES: Final[int] = 8 * 1024 * 1024
IP_ASSET_RECOGNITION_MAX_EDGE: Final[int] = 1_568

_NORMALIZATION_EDGE_SCHEDULE: Final[tuple[int, ...]] = (1_568, 1_280, 1_024, 768, 512)
_SAFE_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")


@dataclass(frozen=True, slots=True)
class IpAssetRecognitionRequest:
    """Transient, metadata-free raster prepared for one vision request."""

    image_bytes: bytes
    media_type: Literal["image/png", "image/jpeg"]
    width: int
    height: int

    def __post_init__(self) -> None:
        if not 1 <= len(self.image_bytes) <= IP_ASSET_RECOGNITION_MAX_IMAGE_BYTES:
            raise ValueError("IP asset recognition image bytes are outside bounds")
        if (
            self.width < 1
            or self.height < 1
            or self.width > IP_ASSET_RECOGNITION_MAX_EDGE
            or self.height > IP_ASSET_RECOGNITION_MAX_EDGE
        ):
            raise ValueError("IP asset recognition image dimensions are outside bounds")


@dataclass(frozen=True, slots=True)
class IpAssetRecognitionSuggestion:
    """Provider-neutral advisory values; the later upload remains authoritative."""

    character: IpAssetCharacter
    asset_type: IpAssetType
    emotion: str = ""
    action: str = ""
    scene: str = ""
    intended_use: str = ""
    style: str = ""
    tags: tuple[str, ...] = ()
    provider: str = ""
    model: str = ""

    def __post_init__(self) -> None:
        for field_name, maximum in (
            ("emotion", 40),
            ("action", 40),
            ("scene", 60),
            ("intended_use", 60),
            ("style", 40),
        ):
            object.__setattr__(
                self,
                field_name,
                normalize_optional_text(getattr(self, field_name), maximum=maximum),
            )
        object.__setattr__(self, "tags", normalize_tags(self.tags))
        for field_name in ("provider", "model"):
            value = getattr(self, field_name).strip()
            if _SAFE_IDENTITY.fullmatch(value) is None:
                raise ValueError("IP asset recognition identity is invalid")
            object.__setattr__(self, field_name, value)


def normalize_ip_asset_recognition_request(
    upload: ValidatedIpAssetUpload,
) -> IpAssetRecognitionRequest:
    """Render pixels only, dropping source metadata before the provider call."""

    try:
        with Image.open(io.BytesIO(upload.body)) as opened:
            opened.seek(0)
            opened.load()
            transposed = ImageOps.exif_transpose(opened)
            has_alpha = "A" in transposed.getbands() or "transparency" in transposed.info
            raster = transposed.convert("RGBA" if has_alpha else "RGB")
    except (Image.DecompressionBombError, OSError, UnidentifiedImageError, ValueError) as error:
        raise ValueError("IP asset recognition image cannot be normalized") from error

    for maximum_edge in _NORMALIZATION_EDGE_SCHEDULE:
        scale = min(1.0, maximum_edge / max(raster.width, raster.height))
        target_size = (
            max(1, round(raster.width * scale)),
            max(1, round(raster.height * scale)),
        )
        candidate = (
            raster.copy()
            if target_size == raster.size
            else raster.resize(target_size, Image.Resampling.LANCZOS, reducing_gap=3.0)
        )
        candidate.info.clear()
        output = io.BytesIO()
        media_type: Literal["image/png", "image/jpeg"]
        if candidate.mode == "RGBA":
            media_type = "image/png"
            candidate.save(output, format="PNG", optimize=False, compress_level=9)
        else:
            media_type = "image/jpeg"
            candidate.save(output, format="JPEG", quality=88, optimize=True, progressive=False)
        body = output.getvalue()
        if len(body) <= IP_ASSET_RECOGNITION_MAX_IMAGE_BYTES:
            return IpAssetRecognitionRequest(
                image_bytes=body,
                media_type=media_type,
                width=target_size[0],
                height=target_size[1],
            )
    raise ValueError("IP asset recognition image cannot fit the provider input bound")
