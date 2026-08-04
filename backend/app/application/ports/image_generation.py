from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ImageReference:
    """An ordered, private image input selected by the application layer."""

    role: str
    asset_id: str
    filename: str
    sha256: str
    image_bytes: bytes
    selection_reason: str = ""


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
