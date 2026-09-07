"""Pure, versioned final upload derivatives prepared before strict visual audit.

This module has no provider, database, filesystem or social capability. The legacy
draft normalizers deliberately remain untouched: these are new policy identities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
from typing import Final, Literal

from PIL import Image, ImageOps, UnidentifiedImageError

OFFICIAL_ACCOUNT_UPLOAD_BODY_POLICY_VERSION: Final = "official-account-upload-body-v1"
OFFICIAL_ACCOUNT_UPLOAD_COVER_POLICY_VERSION: Final = "official-account-upload-cover-v1"
OFFICIAL_ACCOUNT_UPLOAD_CONTEXT_POLICY_VERSION: Final = "official-account-upload-context-v1"
_MAX_SOURCE_BYTES: Final = 10 * 1024 * 1024
_MAX_INLINE_BYTES: Final = 1024 * 1024 - 1
_MAX_THUMB_BYTES: Final = 64 * 1024 - 1


@dataclass(frozen=True, slots=True)
class OfficialAccountUploadDerivative:
    content: bytes = field(repr=False)
    mime_type: Literal["image/jpeg", "image/png"]
    width: int
    height: int
    sha256: str
    source_sha256: str
    policy_version: str

    @property
    def byte_size(self) -> int:
        return len(self.content)


def _decode(content: bytes) -> tuple[Image.Image, str, bool]:
    if not 8 <= len(content) <= _MAX_SOURCE_BYTES:
        raise ValueError("upload source byte bound is invalid")
    try:
        with Image.open(BytesIO(content)) as opened:
            if (
                opened.format not in {"JPEG", "PNG", "WEBP"}
                or not 1 <= opened.width <= 8192
                or not 1 <= opened.height <= 8192
                or opened.width * opened.height > 20_000_000
                or getattr(opened, "n_frames", 1) != 1
            ):
                raise ValueError("upload source raster is invalid")
            opened.load()
            clean = not opened.getexif() and not any(
                name in opened.info
                for name in ("comment", "icc_profile", "xmp", "XML:com.adobe.xmp")
            )
            return opened.convert("RGB"), opened.format, clean
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise ValueError("upload source raster is invalid") from None


def _jpeg(image: Image.Image, *, maximum: int) -> bytes:
    for quality in (90, 84, 78, 72, 66, 60, 54, 48, 42, 36, 30):
        output = BytesIO()
        image.save(output, format="JPEG", quality=quality, optimize=True, subsampling=2)
        content = output.getvalue()
        if 8 <= len(content) <= maximum:
            return content
    raise ValueError("upload derivative cannot meet the fixed byte bound")


def _result(
    original: bytes,
    content: bytes,
    *,
    mime_type: Literal["image/jpeg", "image/png"],
    size: tuple[int, int],
    policy_version: str,
) -> OfficialAccountUploadDerivative:
    return OfficialAccountUploadDerivative(
        content=content,
        mime_type=mime_type,
        width=size[0],
        height=size[1],
        sha256=sha256(content).hexdigest(),
        source_sha256=sha256(original).hexdigest(),
        policy_version=policy_version,
    )


def normalize_official_account_upload_body(content: bytes) -> OfficialAccountUploadDerivative:
    """Keep native scene geometry; quality-step only if final JPEG needs compression."""
    image, image_format, clean = _decode(content)
    if image.size != (1536, 1024):
        raise ValueError("strict body upload requires native landscape geometry")
    final = (
        content
        if image_format == "JPEG" and clean and len(content) <= _MAX_INLINE_BYTES
        else _jpeg(image, maximum=_MAX_INLINE_BYTES)
    )
    return _result(
        content,
        final,
        mime_type="image/jpeg",
        size=image.size,
        policy_version=OFFICIAL_ACCOUNT_UPLOAD_BODY_POLICY_VERSION,
    )


def normalize_official_account_upload_cover(content: bytes) -> OfficialAccountUploadDerivative:
    """Derive exactly 1175x500 once, before its independently owned final-byte audit."""
    image, _image_format, _clean = _decode(content)
    if image.width < 1175 or image.height < 500:
        raise ValueError("strict cover source is too small")
    cropped = ImageOps.fit(image, (1175, 500), method=Image.Resampling.LANCZOS)
    return _result(
        content,
        _jpeg(cropped, maximum=_MAX_THUMB_BYTES),
        mime_type="image/jpeg",
        size=cropped.size,
        policy_version=OFFICIAL_ACCOUNT_UPLOAD_COVER_POLICY_VERSION,
    )


def normalize_official_account_upload_context(content: bytes) -> OfficialAccountUploadDerivative:
    """Preserve eligible news JPEG/PNG exactly; caller retains original if converted."""
    image, image_format, _clean = _decode(content)
    preserve = image_format in {"JPEG", "PNG"} and len(content) <= _MAX_INLINE_BYTES
    final = content if preserve else _jpeg(image, maximum=_MAX_INLINE_BYTES)
    return _result(
        content,
        final,
        mime_type="image/png" if preserve and image_format == "PNG" else "image/jpeg",
        size=image.size,
        policy_version=OFFICIAL_ACCOUNT_UPLOAD_CONTEXT_POLICY_VERSION,
    )
