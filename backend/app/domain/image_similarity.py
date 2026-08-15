from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Final, cast

from PIL import Image, UnidentifiedImageError

from app.domain.visual_diversity import (
    IMAGE_PERCEPTUAL_HASH_VERSION,
    IMAGE_SIMILARITY_POLICY_VERSION,
)

DEFAULT_IMAGE_SIMILARITY_THRESHOLD: Final[int] = 6
_HASH_HEX_LENGTH = 16
_MAX_HASH_INPUT_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ImageSimilarityReference:
    artifact_id: str
    sha256: str
    perceptual_hash: str | None


@dataclass(frozen=True, slots=True)
class ImageSimilarityResult:
    sha256: str
    perceptual_hash: str
    nearest_artifact_id: str | None
    nearest_distance: int | None
    exact_duplicate: bool
    near_duplicate: bool
    threshold: int
    candidate_count: int
    hash_version: str = IMAGE_PERCEPTUAL_HASH_VERSION
    policy_version: str = IMAGE_SIMILARITY_POLICY_VERSION

    def as_metadata(self) -> dict[str, object]:
        return {
            "hash_version": self.hash_version,
            "policy_version": self.policy_version,
            "sha256": self.sha256,
            "perceptual_hash": self.perceptual_hash,
            "nearest_artifact_id": self.nearest_artifact_id,
            "nearest_distance": self.nearest_distance,
            "exact_duplicate": self.exact_duplicate,
            "near_duplicate": self.near_duplicate,
            "threshold": self.threshold,
            "candidate_count": self.candidate_count,
        }


def _validate_hash(value: str) -> str:
    if len(value) != _HASH_HEX_LENGTH:
        raise ValueError("perceptual hash must contain exactly 16 hexadecimal characters")
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError("perceptual hash must be lowercase hexadecimal") from error
    if value != value.lower():
        raise ValueError("perceptual hash must be lowercase hexadecimal")
    return value


def perceptual_dhash(image_bytes: bytes) -> str:
    if not image_bytes or len(image_bytes) > _MAX_HASH_INPUT_BYTES:
        raise ValueError("image similarity input bytes are empty or exceed the safe bound")
    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            opened.seek(0)
            grayscale = opened.convert("L")
            resized = grayscale.resize((9, 8), Image.Resampling.LANCZOS)
            pixels = cast(list[int], list(resized.get_flattened_data()))
    except (OSError, UnidentifiedImageError, ValueError) as error:
        raise ValueError("image similarity input is not a supported raster") from error
    bits = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            bits = (bits << 1) | int(pixels[offset + column] < pixels[offset + column + 1])
    return f"{bits:016x}"


def perceptual_hash_distance(left: str, right: str) -> int:
    left = _validate_hash(left)
    right = _validate_hash(right)
    return (int(left, 16) ^ int(right, 16)).bit_count()


def evaluate_image_similarity(
    image_bytes: bytes,
    *,
    references: tuple[ImageSimilarityReference, ...],
    threshold: int = DEFAULT_IMAGE_SIMILARITY_THRESHOLD,
) -> ImageSimilarityResult:
    if not 0 <= threshold <= 64:
        raise ValueError("image similarity threshold must be in [0, 64]")
    output_sha256 = hashlib.sha256(image_bytes).hexdigest()
    output_hash = perceptual_dhash(image_bytes)
    exact = next((item for item in references if item.sha256 == output_sha256), None)
    nearest_id: str | None = exact.artifact_id if exact is not None else None
    nearest_distance: int | None = 0 if exact is not None else None
    for reference in references:
        if reference.perceptual_hash is None:
            continue
        distance = perceptual_hash_distance(output_hash, reference.perceptual_hash)
        if nearest_distance is None or (distance, reference.artifact_id) < (
            nearest_distance,
            nearest_id or "",
        ):
            nearest_distance = distance
            nearest_id = reference.artifact_id
    return ImageSimilarityResult(
        sha256=output_sha256,
        perceptual_hash=output_hash,
        nearest_artifact_id=nearest_id,
        nearest_distance=nearest_distance,
        exact_duplicate=exact is not None,
        near_duplicate=exact is not None
        or (nearest_distance is not None and nearest_distance <= threshold),
        threshold=threshold,
        candidate_count=len(references),
    )
