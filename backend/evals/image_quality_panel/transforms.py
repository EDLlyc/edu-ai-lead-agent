"""Deterministic stdlib-and-Pillow image recipes for model-panel pairs."""

from __future__ import annotations

import io
import os
import random
import stat
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import cast

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .models import ImageArtifact

MAX_EDGE = 1024
JPEG_QUALITY = 88


class ImagePanelTransformError(ValueError):
    """A deterministic transform destination or source violated its contract."""


def render_artifact(
    *,
    source_path: Path,
    destination: Path,
    artifact_ref: str,
    recipe: str,
    seed_material: str,
) -> ImageArtifact:
    try:
        with Image.open(source_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
            transformed = _recipe(recipe)(image, _seed(seed_material))
    except OSError as exc:
        raise ImagePanelTransformError("image recipe source could not be decoded") from exc
    payload = _jpeg_bytes(transformed)
    _write_private_exclusive(destination, payload)
    return ImageArtifact(
        artifact_ref=artifact_ref,
        media_type="image/jpeg",
        byte_size=len(payload),
        sha256=sha256(payload).hexdigest(),
    )


def _recipe(name: str) -> Callable[[Image.Image, int], Image.Image]:
    recipes: dict[str, Callable[[Image.Image, int], Image.Image]] = {
        "clean": _clean,
        "mild-a": _mild_a,
        "mild-b": _mild_b,
        "semantic-occlusion": _semantic_occlusion,
        "identity-corruption": _identity_corruption,
        "visible-text-mutation": _visible_text_mutation,
        "artifact-degradation": _artifact_degradation,
        "unsafe-crop": _unsafe_crop,
    }
    try:
        return recipes[name]
    except KeyError as exc:
        raise ImagePanelTransformError("unknown deterministic image recipe") from exc


def _clean(image: Image.Image, _: int) -> Image.Image:
    return image.copy()


def _mild_a(image: Image.Image, seed: int) -> Image.Image:
    factor = 0.97 + (seed % 5) / 100
    return ImageEnhance.Color(image).enhance(factor)


def _mild_b(image: Image.Image, seed: int) -> Image.Image:
    factor = 1.01 + (seed % 4) / 100
    return ImageEnhance.Sharpness(image).enhance(factor)


def _semantic_occlusion(image: Image.Image, seed: int) -> Image.Image:
    result = image.copy()
    width, height = result.size
    randomizer = random.Random(seed)
    box_width = max(48, width // 3)
    box_height = max(48, height // 3)
    left = width // 2 - box_width // 2 + randomizer.randint(-width // 16, width // 16)
    top = height // 2 - box_height // 2 + randomizer.randint(-height // 16, height // 16)
    left = max(0, min(width - box_width, left))
    top = max(0, min(height - box_height, top))
    sample = cast(
        tuple[int, int, int],
        image.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0)),
    )
    result.paste(sample, (left, top, left + box_width, top + box_height))
    return result


def _identity_corruption(image: Image.Image, seed: int) -> Image.Image:
    result = image.copy()
    width, height = result.size
    inset_x, inset_y = width // 5, height // 6
    patch = result.crop((inset_x, inset_y, width - inset_x, height - inset_y))
    patch = ImageOps.mirror(patch)
    channels = patch.split()
    if seed % 2:
        patch = Image.merge("RGB", (channels[1], channels[2], channels[0]))
    else:
        patch = Image.merge("RGB", (channels[2], channels[0], channels[1]))
    result.paste(patch, (inset_x, inset_y))
    return result


def _visible_text_mutation(image: Image.Image, seed: int) -> Image.Image:
    result = image.copy()
    width, height = result.size
    band_height = max(40, height // 5)
    top = height - band_height if seed % 2 else 0
    band = result.crop((0, top, width, top + band_height))
    band = ImageOps.invert(band)
    shift = max(8, width // 20)
    shifted = Image.new("RGB", band.size)
    shifted.paste(band, (shift, 0))
    shifted.paste(band.crop((width - shift, 0, width, band_height)), (0, 0))
    result.paste(shifted, (0, top))
    return result


def _artifact_degradation(image: Image.Image, _: int) -> Image.Image:
    width, height = image.size
    small = image.resize(
        (max(64, width // 7), max(64, height // 7)),
        Image.Resampling.BILINEAR,
    )
    blurred = small.filter(ImageFilter.GaussianBlur(radius=1.4))
    return blurred.resize((width, height), Image.Resampling.NEAREST)


def _unsafe_crop(image: Image.Image, seed: int) -> Image.Image:
    width, height = image.size
    horizontal = max(1, width // (5 if seed % 2 else 6))
    vertical = max(1, height // 8)
    cropped = image.crop((horizontal, vertical, width - horizontal, height - vertical))
    return cropped.resize((width, height), Image.Resampling.LANCZOS)


def _jpeg_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=JPEG_QUALITY,
        subsampling=2,
        optimize=False,
        progressive=False,
    )
    return output.getvalue()


def _seed(value: str) -> int:
    return int.from_bytes(sha256(value.encode("utf-8")).digest()[:8], "big")


def _write_private_exclusive(path: Path, payload: bytes) -> None:
    if not payload or len(payload) > 16 * 1024 * 1024:
        raise ImagePanelTransformError("derived artifact has an invalid byte length")
    try:
        metadata = path.parent.stat(follow_symlinks=False)
    except OSError as exc:
        raise ImagePanelTransformError("derived artifact directory is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ImagePanelTransformError("derived artifact directory must have mode 0700")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise ImagePanelTransformError("derived artifacts are immutable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
