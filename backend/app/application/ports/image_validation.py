from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.application.ports.image_generation import ImageReference
from app.domain.image_validation import (
    SUPPORTED_IMAGE_MEDIA_TYPES,
    ImageQualityAuditIssue,
    ImageValidationResult,
    normalize_image_media_type,
)
from app.domain.visual_brief import VisualBrief


@dataclass(frozen=True, slots=True)
class ImageTextRecognitionRequest:
    """Bounded OCR input and the exact text allowlist for one image."""

    image_bytes: bytes
    request_fingerprint: str = ""
    expected_text: tuple[str, ...] = ()
    media_type: str = "image/png"
    language: str = "zh-CN"

    def __post_init__(self) -> None:
        _validate_image_input(self.image_bytes, self.media_type)
        _validate_fingerprint(self.request_fingerprint)
        _validate_lines(self.expected_text, field_name="expected text")
        _validate_text(self.language, field_name="OCR language", maximum=40)
        object.__setattr__(self, "media_type", normalize_image_media_type(self.media_type))
        object.__setattr__(self, "expected_text", tuple(self.expected_text))


@dataclass(frozen=True, slots=True)
class ImageTextRecognitionResult:
    recognized_lines: tuple[str, ...]
    provider: str = ""
    model: str = ""
    request_fingerprint: str = ""

    def __post_init__(self) -> None:
        _validate_lines(self.recognized_lines, field_name="recognized lines")
        _validate_text(self.provider, field_name="OCR provider", maximum=80, required=False)
        _validate_text(self.model, field_name="OCR model", maximum=160, required=False)
        _validate_fingerprint(self.request_fingerprint)
        object.__setattr__(self, "recognized_lines", tuple(self.recognized_lines))


class ImageTextRecognizer(Protocol):
    async def recognize(
        self, request: ImageTextRecognitionRequest
    ) -> ImageTextRecognitionResult: ...


@dataclass(frozen=True, slots=True)
class ImageQualityAuditRequest:
    """Provider-neutral visual audit input with references kept as typed metadata."""

    image_bytes: bytes
    request_fingerprint: str = ""
    visual_brief: VisualBrief | None = None
    references: tuple[ImageReference, ...] = ()
    media_type: str = "image/png"

    def __post_init__(self) -> None:
        _validate_image_input(self.image_bytes, self.media_type)
        _validate_fingerprint(self.request_fingerprint)
        if len(self.references) > 8:
            raise ValueError("image quality audit references are too numerous")
        if any(not reference.image_bytes for reference in self.references):
            raise ValueError("image quality audit references must contain bytes")
        object.__setattr__(self, "media_type", normalize_image_media_type(self.media_type))
        object.__setattr__(self, "references", tuple(self.references))


@dataclass(frozen=True, slots=True)
class ImageQualityAuditResult:
    """Safe audit projection; provider prose is deliberately not represented."""

    accepted: bool
    provider: str = ""
    model: str = ""
    request_fingerprint: str = ""
    issues: tuple[ImageQualityAuditIssue, ...] = ()

    def __post_init__(self) -> None:
        _validate_text(self.provider, field_name="audit provider", maximum=80, required=False)
        _validate_text(self.model, field_name="audit model", maximum=160, required=False)
        _validate_fingerprint(self.request_fingerprint)
        issues = tuple(self.issues)
        if len(issues) > 16:
            raise ValueError("image quality audit issues are too numerous")
        if self.accepted and any(issue.severity == "error" for issue in issues):
            raise ValueError("accepted image audit cannot contain error issues")
        if len({issue.code for issue in issues}) != len(issues):
            raise ValueError("image quality audit issue codes must be unique")
        object.__setattr__(self, "issues", issues)

    @property
    def issue_codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues)

    @property
    def audit_accepted(self) -> bool:
        return self.accepted


class ImageQualityAuditor(Protocol):
    async def audit(self, request: ImageQualityAuditRequest) -> ImageQualityAuditResult: ...


def _validate_image_input(image_bytes: bytes, media_type: str) -> None:
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ValueError("image validation input must contain bytes")
    normalized_media_type = normalize_image_media_type(media_type)
    if normalized_media_type not in SUPPORTED_IMAGE_MEDIA_TYPES:
        raise ValueError("unsupported image validation media type")


def _validate_fingerprint(value: str) -> None:
    _validate_text(value, field_name="request fingerprint", maximum=256, required=False)


def _validate_lines(values: tuple[str, ...], *, field_name: str) -> None:
    if len(values) > 8:
        raise ValueError(f"{field_name} contains too many lines")
    for value in values:
        _validate_text(value, field_name=field_name, maximum=200)


def _validate_text(
    value: str,
    *,
    field_name: str,
    maximum: int,
    required: bool = True,
) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    normalized = " ".join(value.split())
    if required and not normalized:
        raise ValueError(f"{field_name} must not be blank")
    if len(normalized) > maximum:
        raise ValueError(f"{field_name} is too long")


__all__ = [
    "ImageQualityAuditIssue",
    "ImageQualityAuditRequest",
    "ImageQualityAuditResult",
    "ImageQualityAuditor",
    "ImageTextRecognitionRequest",
    "ImageTextRecognitionResult",
    "ImageTextRecognizer",
    "ImageValidationResult",
]
