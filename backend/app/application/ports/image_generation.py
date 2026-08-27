from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.domain.image_generation import validate_image_prompt
from app.domain.image_provider_input import IMAGE_REFERENCE_INPUT_V1_PNG_ONLY


@dataclass(frozen=True, slots=True)
class ImageReference:
    """An ordered, private image input selected by the application layer."""

    role: str
    asset_id: str
    filename: str
    sha256: str
    image_bytes: bytes
    selection_reason: str = ""
    input_normalization_version: str = IMAGE_REFERENCE_INPUT_V1_PNG_ONLY
    provider_input_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ImageGenerationRequest:
    run_id: UUID
    draft_version_id: UUID
    prompt: str
    request_fingerprint: str
    reference_image: bytes | None = None
    reference_filename: str | None = None
    references: tuple[ImageReference, ...] = ()
    reference_mode: str = "legacy_single"
    provider_request_fingerprint: str | None = None
    unrestricted_prompt_length: bool = False


def validate_image_generation_request_prompt(request: ImageGenerationRequest) -> str:
    """Normalize one request prompt under its explicit application-level length policy."""

    if request.unrestricted_prompt_length:
        return validate_image_prompt(
            request.prompt,
            minimum_length=None,
            maximum_length=None,
        )
    return validate_image_prompt(request.prompt)


@dataclass(frozen=True, slots=True)
class ImageGenerationResult:
    provider: str
    model: str
    request_fingerprint: str
    provider_task_id: str | None
    provider_upload_id: str | None
    image_bytes: bytes
    media_type: str
    width: int
    height: int
    attempts: int


class ImageGenerator(Protocol):
    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult: ...
