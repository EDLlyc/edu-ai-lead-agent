from __future__ import annotations

import re
import struct
import unicodedata
import zlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.domain.value_objects import stable_key

DEFAULT_IMAGE_MAX_BYTES: Final[int] = 20 * 1024 * 1024
DEFAULT_IMAGE_MAX_DIMENSION: Final[int] = 8_192
DEFAULT_IMAGE_MAX_PIXELS: Final[int] = 32_000_000
DEFAULT_IMAGE_DIMENSIONS: Final[tuple[int, int]] = (1_024, 1_024)
IMAGE_REPAIR_PROMPT_VERSION: Final[str] = "image-repair-v1"
IMAGE_REPAIR_FINGERPRINT_VERSION: Final[str] = "image-repair-fingerprint-v1"

SUPPORTED_IMAGE_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {"image/png", "image/jpeg", "image/webp"}
)

_IMAGE_VALIDATION_CODE = re.compile(r"^[a-z][a-z0-9_:-]{0,79}$")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_REPAIR_ISSUE_CODE = re.compile(r"^[a-z][a-z0-9_:-]{0,63}$")
_MAX_VISUAL_TEXT_ITEMS = 8
_MAX_VISUAL_TEXT_LENGTH = 200


class ImageValidationCode(StrEnum):
    """Stable codes for deterministic image and visual-text validation failures."""

    INVALID_IMAGE_BYTES = "invalid_image_bytes"
    EMPTY_IMAGE = "empty_image"
    IMAGE_TOO_LARGE = "image_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    INVALID_RASTER_SIGNATURE = "invalid_raster_signature"
    MEDIA_TYPE_SIGNATURE_MISMATCH = "media_type_signature_mismatch"
    INVALID_RASTER = "invalid_raster"
    INVALID_DIMENSIONS = "invalid_dimensions"
    DIMENSION_LIMIT_EXCEEDED = "dimension_limit_exceeded"
    PIXEL_LIMIT_EXCEEDED = "pixel_limit_exceeded"
    DIMENSION_MISMATCH = "dimension_mismatch"
    REPORTED_DIMENSION_MISMATCH = "reported_dimension_mismatch"
    INVALID_EXPECTED_VISUAL_TEXT = "invalid_expected_visual_text"
    MISSING_VISUAL_TEXT = "missing_visual_text"
    UNEXPECTED_VISUAL_TEXT = "unexpected_visual_text"
    DUPLICATE_VISUAL_TEXT = "duplicate_visual_text"
    MISORDERED_VISUAL_TEXT = "misordered_visual_text"


class ImageQualityIssueSeverity(StrEnum):
    """Severity values accepted from a provider-neutral quality auditor."""

    WARNING = "warning"
    ERROR = "error"


def normalize_image_media_type(media_type: str) -> str:
    """Normalize a content type without allowing parameters to change its identity."""

    if not isinstance(media_type, str):
        raise ValueError("image media type must be text")
    normalized = media_type.split(";", 1)[0].strip().casefold()
    if not normalized:
        raise ValueError("image media type must not be blank")
    return normalized


@dataclass(frozen=True, slots=True)
class ImageValidationResult:
    """Content-free, deterministic result shared by hard and OCR validation."""

    passed: bool
    issue_codes: tuple[str, ...] = ()
    media_type: str | None = None
    byte_size: int | None = None
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        codes = tuple(dict.fromkeys(self.issue_codes))
        if any(
            not isinstance(code, str) or _IMAGE_VALIDATION_CODE.fullmatch(code) is None
            for code in codes
        ):
            raise ValueError("image validation issue codes must be safe identifiers")
        if self.passed and codes:
            raise ValueError("an accepted image validation result cannot contain issue codes")
        if self.byte_size is not None and self.byte_size < 0:
            raise ValueError("image validation byte size must not be negative")
        if self.width is not None and self.width < 1:
            raise ValueError("image validation width must be positive")
        if self.height is not None and self.height < 1:
            raise ValueError("image validation height must be positive")
        if self.media_type is not None:
            object.__setattr__(self, "media_type", normalize_image_media_type(self.media_type))
        object.__setattr__(self, "issue_codes", codes)

    @property
    def accepted(self) -> bool:
        return self.passed

    @property
    def valid(self) -> bool:
        """Compatibility spelling for consumers that call validation a validity check."""

        return self.passed

    @property
    def is_valid(self) -> bool:
        return self.passed

    @property
    def issues(self) -> tuple[str, ...]:
        return self.issue_codes

    def as_snapshot(self, configured: bool = True) -> dict[str, object]:
        """Return a safe JSON-compatible projection for durable package metadata."""

        return {
            "configured": configured,
            "passed": self.passed,
            "issue_codes": list(self.issue_codes),
            "media_type": self.media_type,
            "width": self.width,
            "height": self.height,
            "byte_size": self.byte_size,
        }


@dataclass(frozen=True, slots=True)
class ImageQualityAuditIssue:
    """A bounded audit diagnostic without provider-generated free-form content."""

    code: str
    severity: str

    def __post_init__(self) -> None:
        code = _normalize_issue_code(self.code, field_name="audit issue code")
        severity = self.severity.strip().casefold()
        if severity not in {item.value for item in ImageQualityIssueSeverity}:
            raise ValueError("audit issue severity must be warning or error")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "severity", severity)


def validate_image_output(
    image_bytes: bytes,
    media_type: str,
    *,
    expected_dimensions: tuple[int, int] | None = DEFAULT_IMAGE_DIMENSIONS,
    expected_width: int | None = None,
    expected_height: int | None = None,
    reported_dimensions: tuple[int, int] | None = None,
    max_bytes: int = DEFAULT_IMAGE_MAX_BYTES,
    max_dimension: int = DEFAULT_IMAGE_MAX_DIMENSION,
    max_pixels: int = DEFAULT_IMAGE_MAX_PIXELS,
) -> ImageValidationResult:
    """Validate an output's bytes, declared type, raster signature, and dimensions.

    The raster header is parsed independently of provider-supplied dimensions.  The default
    dimensions match the existing square image contract, while callers can pass ``None`` to
    validate a different bounded raster shape.  ``reported_dimensions`` is optional metadata from
    an adapter and is checked against the parsed header when provided.
    """

    if not isinstance(image_bytes, bytes):
        return ImageValidationResult(
            passed=False,
            issue_codes=(ImageValidationCode.INVALID_IMAGE_BYTES.value,),
        )
    if max_bytes < 1 or max_dimension < 1 or max_pixels < 1:
        raise ValueError("image validation bounds must be positive")
    target_dimensions = _resolve_dimensions(
        expected_dimensions, expected_width=expected_width, expected_height=expected_height
    )
    adapter_dimensions = _resolve_reported_dimensions(reported_dimensions)
    declared_media_type = _normalize_media_type_for_validation(media_type)
    byte_size = len(image_bytes)
    if byte_size == 0:
        return ImageValidationResult(
            passed=False,
            issue_codes=(ImageValidationCode.EMPTY_IMAGE.value,),
            media_type=declared_media_type,
            byte_size=byte_size,
        )
    if byte_size > max_bytes:
        return ImageValidationResult(
            passed=False,
            issue_codes=(ImageValidationCode.IMAGE_TOO_LARGE.value,),
            media_type=declared_media_type,
            byte_size=byte_size,
        )
    if declared_media_type not in SUPPORTED_IMAGE_MEDIA_TYPES:
        return ImageValidationResult(
            passed=False,
            issue_codes=(ImageValidationCode.UNSUPPORTED_MEDIA_TYPE.value,),
            media_type=declared_media_type,
            byte_size=byte_size,
        )

    try:
        detected_media_type = _detect_raster_media_type(image_bytes)
    except ValueError:
        return ImageValidationResult(
            passed=False,
            issue_codes=(ImageValidationCode.INVALID_RASTER_SIGNATURE.value,),
            media_type=declared_media_type,
            byte_size=byte_size,
        )
    if detected_media_type != declared_media_type:
        return ImageValidationResult(
            passed=False,
            issue_codes=(ImageValidationCode.MEDIA_TYPE_SIGNATURE_MISMATCH.value,),
            media_type=declared_media_type,
            byte_size=byte_size,
        )

    try:
        width, height = _raster_dimensions(image_bytes, detected_media_type)
    except ValueError:
        return ImageValidationResult(
            passed=False,
            issue_codes=(ImageValidationCode.INVALID_RASTER.value,),
            media_type=declared_media_type,
            byte_size=byte_size,
        )
    issues: list[str] = []
    if width > max_dimension or height > max_dimension:
        issues.append(ImageValidationCode.DIMENSION_LIMIT_EXCEEDED.value)
    if width * height > max_pixels:
        issues.append(ImageValidationCode.PIXEL_LIMIT_EXCEEDED.value)
    if target_dimensions is not None and (width, height) != target_dimensions:
        issues.append(ImageValidationCode.DIMENSION_MISMATCH.value)
    if adapter_dimensions is not None and (width, height) != adapter_dimensions:
        issues.append(ImageValidationCode.REPORTED_DIMENSION_MISMATCH.value)
    return ImageValidationResult(
        passed=not issues,
        issue_codes=tuple(issues),
        media_type=declared_media_type,
        byte_size=byte_size,
        width=width,
        height=height,
    )


def validate_exact_visual_text(
    recognized_lines: Sequence[str],
    expected_text: str | Sequence[str],
    *,
    require_order: bool = False,
) -> ImageValidationResult:
    """Require OCR output to contain exactly the bounded allowlisted text set.

    Blank OCR lines are ignored. Historical callers retain order-insensitive set comparison because
    OCR engines can return blocks in different reading orders. Controlled visual-text callers can
    additionally require the approved signature/title/subtitle hierarchy in exact reading order.
    Missing, unexpected, duplicated, and (when requested) reordered non-blank lines are failures.
    """

    try:
        observed = _normalize_visual_text_values(recognized_lines, field_name="recognized lines")
        expected = _normalize_visual_text_values(expected_text, field_name="expected visual text")
    except ValueError:
        return ImageValidationResult(
            passed=False,
            issue_codes=(ImageValidationCode.INVALID_EXPECTED_VISUAL_TEXT.value,),
        )
    if not expected or len(expected) > _MAX_VISUAL_TEXT_ITEMS:
        return ImageValidationResult(
            passed=False,
            issue_codes=(ImageValidationCode.INVALID_EXPECTED_VISUAL_TEXT.value,),
        )
    issues: list[str] = []
    if len(expected) != len(set(expected)):
        issues.append(ImageValidationCode.INVALID_EXPECTED_VISUAL_TEXT.value)
    if len(observed) != len(set(observed)):
        issues.append(ImageValidationCode.DUPLICATE_VISUAL_TEXT.value)
    expected_set = set(expected)
    observed_set = set(observed)
    if expected_set - observed_set:
        issues.append(ImageValidationCode.MISSING_VISUAL_TEXT.value)
    if observed_set - expected_set:
        issues.append(ImageValidationCode.UNEXPECTED_VISUAL_TEXT.value)
    if require_order and not issues and observed != expected:
        issues.append(ImageValidationCode.MISORDERED_VISUAL_TEXT.value)
    return ImageValidationResult(
        passed=not issues,
        issue_codes=tuple(dict.fromkeys(issues)),
    )


def build_image_repair_prompt(prompt: str, issue_codes: Iterable[str]) -> str:
    """Build one bounded repair instruction from safe issue identifiers only."""

    normalized_prompt = _normalize_bounded_text(
        prompt, field_name="image repair prompt", maximum=1_650
    )
    codes = _normalize_repair_issue_codes(issue_codes)
    suffix = (
        "[Targeted image repair, version "
        + IMAGE_REPAIR_PROMPT_VERSION
        + "] Correct only these validated issue codes: "
        + ", ".join(codes)
        + ". Preserve the approved subject, characters, composition, palette, and exact "
        + "allowlisted visual text. Do not add extra text, logos, watermarks, QR codes, or "
        + "unrelated characters."
    )
    repaired_prompt = f"{normalized_prompt}\n\n{suffix}"
    if len(repaired_prompt) > 2_000:
        raise ValueError("image repair prompt exceeds the provider prompt limit")
    return repaired_prompt


def image_repair_fingerprint(base_fingerprint: str, repair_count: int, prompt: str) -> str:
    """Return a deterministic id for the only permitted image repair attempt."""

    base = _normalize_bounded_text(
        base_fingerprint, field_name="base image fingerprint", maximum=256
    )
    if not isinstance(repair_count, int) or repair_count not in {0, 1}:
        raise ValueError("image repair count must be 0 or 1")
    normalized_prompt = _normalize_bounded_text(
        prompt, field_name="image repair prompt", maximum=2_000
    )
    return stable_key(
        IMAGE_REPAIR_FINGERPRINT_VERSION,
        base,
        repair_count,
        normalized_prompt,
    )


def _resolve_dimensions(
    dimensions: tuple[int, int] | None,
    *,
    expected_width: int | None,
    expected_height: int | None,
) -> tuple[int, int] | None:
    if (expected_width is None) != (expected_height is None):
        raise ValueError("expected width and height must be provided together")
    resolved = (
        (expected_width, expected_height)
        if expected_width is not None and expected_height is not None
        else dimensions
    )
    if resolved is not None and (len(resolved) != 2 or min(resolved) < 1):
        raise ValueError("expected image dimensions must be positive")
    return resolved


def _resolve_reported_dimensions(
    dimensions: tuple[int, int] | None,
) -> tuple[int, int] | None:
    if dimensions is not None and (len(dimensions) != 2 or min(dimensions) < 1):
        raise ValueError("reported image dimensions must be positive")
    return dimensions


def _normalize_media_type_for_validation(media_type: str) -> str:
    try:
        return normalize_image_media_type(media_type)
    except ValueError:
        return ""


def _detect_raster_media_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("unsupported raster signature")


def _raster_dimensions(image_bytes: bytes, media_type: str) -> tuple[int, int]:
    if media_type == "image/png":
        return _png_dimensions(image_bytes)
    if media_type == "image/jpeg":
        return _jpeg_dimensions(image_bytes)
    if media_type == "image/webp":
        return _webp_dimensions(image_bytes)
    raise ValueError("unsupported raster media type")


def _png_dimensions(image_bytes: bytes) -> tuple[int, int]:
    if len(image_bytes) < 33 or image_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("truncated PNG")
    index = 8
    first_chunk = True
    saw_idat = False
    saw_iend = False
    dimensions: tuple[int, int] | None = None
    while index < len(image_bytes):
        if index + 8 > len(image_bytes):
            raise ValueError("truncated PNG chunk")
        chunk_length = struct.unpack(">I", image_bytes[index : index + 4])[0]
        chunk_end = index + 12 + chunk_length
        if chunk_end > len(image_bytes):
            raise ValueError("truncated PNG chunk data")
        chunk_type = image_bytes[index + 4 : index + 8]
        data_start = index + 8
        data_end = data_start + chunk_length
        data = image_bytes[data_start:data_end]
        crc = struct.unpack(">I", image_bytes[data_end : data_end + 4])[0]
        if zlib.crc32(chunk_type + data) & 0xFFFFFFFF != crc:
            raise ValueError("invalid PNG chunk checksum")
        if first_chunk:
            if chunk_type != b"IHDR" or chunk_length != 13:
                raise ValueError("PNG must start with IHDR")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", data
            )
            if (
                width < 1
                or height < 1
                or bit_depth not in {1, 2, 4, 8, 16}
                or color_type not in {0, 2, 3, 4, 6}
                or compression != 0
                or filtering != 0
                or interlace not in {0, 1}
            ):
                raise ValueError("invalid PNG IHDR")
            dimensions = (width, height)
            first_chunk = False
        elif chunk_type == b"IHDR":
            raise ValueError("PNG contains duplicate IHDR")
        if chunk_type == b"IDAT":
            saw_idat = True
        if chunk_type == b"IEND":
            if chunk_length != 0 or saw_iend or chunk_end != len(image_bytes):
                raise ValueError("invalid PNG IEND")
            saw_iend = True
        index = chunk_end
    if dimensions is None or not saw_idat or not saw_iend:
        raise ValueError("PNG raster chunks are incomplete")
    return dimensions


def _jpeg_dimensions(image_bytes: bytes) -> tuple[int, int]:
    if len(image_bytes) < 4 or image_bytes[:2] != b"\xff\xd8":
        raise ValueError("invalid JPEG signature")
    index = 2
    sof_markers = {
        *range(0xC0, 0xC4),
        *range(0xC5, 0xC8),
        *range(0xC9, 0xCC),
        *range(0xCD, 0xD0),
    }
    standalone_markers = {0x01, *range(0xD0, 0xD9)}
    while index < len(image_bytes):
        if image_bytes[index] != 0xFF:
            raise ValueError("invalid JPEG marker")
        while index < len(image_bytes) and image_bytes[index] == 0xFF:
            index += 1
        if index >= len(image_bytes):
            raise ValueError("truncated JPEG marker")
        marker = image_bytes[index]
        index += 1
        if marker == 0x00:
            raise ValueError("invalid JPEG marker stuffing")
        if marker in standalone_markers:
            continue
        if index + 2 > len(image_bytes):
            raise ValueError("truncated JPEG segment")
        segment_length = int.from_bytes(image_bytes[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(image_bytes):
            raise ValueError("invalid JPEG segment length")
        if marker in sof_markers:
            if segment_length < 7:
                raise ValueError("truncated JPEG frame header")
            height = int.from_bytes(image_bytes[index + 3 : index + 5], "big")
            width = int.from_bytes(image_bytes[index + 5 : index + 7], "big")
            if width < 1 or height < 1:
                raise ValueError("invalid JPEG dimensions")
            return width, height
        index += segment_length
    raise ValueError("JPEG frame header is missing")


def _webp_dimensions(image_bytes: bytes) -> tuple[int, int]:
    if len(image_bytes) < 20 or image_bytes[:4] != b"RIFF" or image_bytes[8:12] != b"WEBP":
        raise ValueError("invalid WebP signature")
    riff_size = int.from_bytes(image_bytes[4:8], "little")
    if riff_size < 4 or riff_size + 8 > len(image_bytes):
        raise ValueError("invalid WebP RIFF length")
    index = 12
    while index + 8 <= len(image_bytes):
        chunk_type = image_bytes[index : index + 4]
        chunk_size = int.from_bytes(image_bytes[index + 4 : index + 8], "little")
        data_start = index + 8
        data_end = data_start + chunk_size
        padded_end = data_end + (chunk_size & 1)
        if padded_end > len(image_bytes):
            raise ValueError("truncated WebP chunk")
        data = image_bytes[data_start:data_end]
        if chunk_type == b"VP8X":
            if chunk_size < 10:
                raise ValueError("truncated WebP extended header")
            width = 1 + int.from_bytes(data[4:7], "little")
            height = 1 + int.from_bytes(data[7:10], "little")
            return width, height
        if chunk_type == b"VP8 " and len(data) >= 10 and data[3:6] == b"\x9d\x01\x2a":
            width = int.from_bytes(data[6:8], "little") & 0x3FFF
            height = int.from_bytes(data[8:10], "little") & 0x3FFF
            if width and height:
                return width, height
        if chunk_type == b"VP8L" and len(data) >= 5 and data[0] == 0x2F:
            packed = int.from_bytes(data[1:5], "little")
            width = 1 + (packed & 0x3FFF)
            height = 1 + ((packed >> 14) & 0x3FFF)
            if width and height:
                return width, height
        index = padded_end
    raise ValueError("WebP frame dimensions are missing")


def _normalize_visual_text_values(
    values: str | Iterable[str], *, field_name: str
) -> tuple[str, ...]:
    if isinstance(values, str):
        raw_values: Iterable[str] = values.splitlines() or (values,)
    else:
        raw_values = values
    normalized: list[str] = []
    for raw_value in raw_values:
        if not isinstance(raw_value, str):
            raise ValueError(f"{field_name} must contain text values")
        parts = raw_value.splitlines() or (raw_value,)
        for part in parts:
            value = _normalize_bounded_text(
                part,
                field_name=field_name,
                maximum=_MAX_VISUAL_TEXT_LENGTH,
                required=False,
            )
            if value:
                normalized.append(value)
    if len(normalized) > _MAX_VISUAL_TEXT_ITEMS:
        raise ValueError(f"{field_name} contains too many lines")
    return tuple(normalized)


def _normalize_issue_code(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    normalized = value.strip().casefold()
    if _IMAGE_VALIDATION_CODE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} is not a safe identifier")
    return normalized


def _normalize_repair_issue_codes(issue_codes: Iterable[str]) -> tuple[str, ...]:
    if isinstance(issue_codes, str):
        raise ValueError("repair issue codes must be a sequence")
    normalized: set[str] = set()
    for issue_code in issue_codes:
        if not isinstance(issue_code, str):
            raise ValueError("repair issue codes must contain text values")
        value = issue_code.strip().casefold()
        if _REPAIR_ISSUE_CODE.fullmatch(value) is None:
            raise ValueError("repair issue codes must be safe identifiers")
        normalized.add(value)
    if not normalized:
        raise ValueError("at least one repair issue code is required")
    if len(normalized) > 8:
        raise ValueError("too many repair issue codes")
    return tuple(sorted(normalized))


def _normalize_bounded_text(
    value: str,
    *,
    field_name: str,
    maximum: int,
    required: bool = True,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    if _CONTROL_CHARACTER.search(value):
        raise ValueError(f"{field_name} contains a control character")
    normalized = unicodedata.normalize("NFKC", " ".join(value.strip().split()))
    if required and not normalized:
        raise ValueError(f"{field_name} must not be blank")
    if len(normalized) > maximum:
        raise ValueError(f"{field_name} is too long")
    return normalized


__all__ = [
    "DEFAULT_IMAGE_DIMENSIONS",
    "DEFAULT_IMAGE_MAX_BYTES",
    "DEFAULT_IMAGE_MAX_DIMENSION",
    "DEFAULT_IMAGE_MAX_PIXELS",
    "IMAGE_REPAIR_FINGERPRINT_VERSION",
    "IMAGE_REPAIR_PROMPT_VERSION",
    "SUPPORTED_IMAGE_MEDIA_TYPES",
    "ImageQualityAuditIssue",
    "ImageQualityIssueSeverity",
    "ImageValidationCode",
    "ImageValidationResult",
    "build_image_repair_prompt",
    "image_repair_fingerprint",
    "normalize_image_media_type",
    "validate_exact_visual_text",
    "validate_image_output",
]
