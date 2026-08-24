from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

IMAGE_REFERENCE_INPUT_V1_PNG_ONLY = "image-reference-input-v1-png-only"
IMAGE_REFERENCE_INPUT_V2 = "image-reference-input-v2-png-preserve-jpeg-normalize"

_MAX_REFERENCE_SOURCE_BYTES = 10 * 1024 * 1024
_MAX_REFERENCE_OUTPUT_BYTES = 10 * 1024 * 1024
_MAX_EDGE = 8_192
_MAX_PIXELS = 32_000_000


@dataclass(frozen=True, slots=True)
class NormalizedImageProviderInput:
    """A bounded provider-ready PNG plus its replay-safe identity.

    Existing valid PNG bytes are deliberately returned byte-for-byte. JPEG inputs are decoded,
    orientation-normalized, converted to RGB/RGBA pixels and encoded as a metadata-free PNG.
    """

    version: str
    image_png: bytes
    sha256: str
    width: int
    height: int


def normalize_image_provider_reference(
    source: bytes,
    *,
    version: str = IMAGE_REFERENCE_INPUT_V2,
) -> NormalizedImageProviderInput:
    if version != IMAGE_REFERENCE_INPUT_V2:
        raise ValueError("image provider reference normalization version is unsupported")
    if not 24 <= len(source) <= _MAX_REFERENCE_SOURCE_BYTES:
        raise ValueError("image provider reference bytes are outside bounds")

    # This fast path is a compatibility contract: historical callers that already supplied a
    # valid PNG produce the exact same provider request bytes after opting into v2.
    if source[:8] == b"\x89PNG\r\n\x1a\n" and source[12:16] == b"IHDR":
        width, height = _validated_raster(source, expected_format="PNG")
        return NormalizedImageProviderInput(
            version=version,
            image_png=source,
            sha256=sha256(source).hexdigest(),
            width=width,
            height=height,
        )

    try:
        with Image.open(BytesIO(source)) as opened:
            if opened.format != "JPEG":
                raise ValueError("image provider reference must be PNG or JPEG")
            opened.load()
            transposed = ImageOps.exif_transpose(opened)
            image = transposed.convert("RGBA" if "A" in transposed.getbands() else "RGB")
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError("image provider reference cannot be decoded") from error

    width, height = image.size
    _validate_dimensions(width, height)
    output = BytesIO()
    image.save(output, format="PNG", compress_level=9, optimize=False)
    normalized = output.getvalue()
    if not 24 <= len(normalized) <= _MAX_REFERENCE_OUTPUT_BYTES:
        raise ValueError("normalized image provider reference is outside bounds")
    _validated_raster(normalized, expected_format="PNG")
    return NormalizedImageProviderInput(
        version=version,
        image_png=normalized,
        sha256=sha256(normalized).hexdigest(),
        width=width,
        height=height,
    )


def _validated_raster(source: bytes, *, expected_format: str) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(source)) as opened:
            if opened.format != expected_format:
                raise ValueError("image provider reference signature does not match")
            opened.verify()
        with Image.open(BytesIO(source)) as opened:
            width, height = opened.size
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError("image provider reference cannot be decoded") from error
    _validate_dimensions(width, height)
    return width, height


def _validate_dimensions(width: int, height: int) -> None:
    if (
        width < 1
        or height < 1
        or width > _MAX_EDGE
        or height > _MAX_EDGE
        or width * height > _MAX_PIXELS
    ):
        raise ValueError("image provider reference dimensions are outside bounds")
