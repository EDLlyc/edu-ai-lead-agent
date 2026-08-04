from __future__ import annotations

import re
from hashlib import sha256

from app.domain.value_objects import stable_key

IMAGE_MODEL = "gpt-image-2"
IMAGE_SIZE = "1:1"
IMAGE_RESOLUTION = "1k"
IMAGE_WIDTH = 1024
IMAGE_HEIGHT = 1024
IMAGE_PROMPT_VERSION = "image-prompt-v1"
IMAGE_PIPELINE_VERSION = "image-pipeline-v1"
IMAGE_REFERENCE_BUDGET_BYTES = 3 * 1024 * 1024
_PROMPT_LIMIT = 2_000
_UNSAFE_PROMPT = re.compile(
    r"(?:未成年人真人正脸|儿童真实正脸|裸露儿童|血腥|武器伤害|学生身份证|水印|二维码|仿制|重绘logo|重新绘制标志)",
    re.IGNORECASE,
)


def validate_image_prompt(prompt: str) -> str:
    value = " ".join(prompt.split())
    if not 8 <= len(value) <= _PROMPT_LIMIT:
        raise ValueError("image prompt must be between 8 and 2000 characters")
    if _UNSAFE_PROMPT.search(value):
        raise ValueError("image prompt contains a prohibited visual instruction")
    return value


def image_request_fingerprint(
    *,
    run_id: object,
    draft_version_id: object,
    prompt: str,
    provider: str = "toapis",
    model: str = IMAGE_MODEL,
    prompt_version: str = IMAGE_PROMPT_VERSION,
    pipeline_version: str = IMAGE_PIPELINE_VERSION,
    reference_sha256: str | None = None,
    reference_sha256s: tuple[str, ...] = (),
    visual_brief_fingerprint: str = "no-visual-brief",
    catalog_version: str = "no-catalog",
    selector_version: str = "no-selector",
) -> str:
    """Derive the durable business id for one accepted image request.

    Provider/model and input-version identity are part of the key.  Otherwise changing a
    provider configuration could silently reuse an artifact produced under a different contract.
    Ordered reference digests and visual-selection versions are included because the approved
    character assets are inputs to the image request even though their transient upload URLs are
    never persisted.
    """
    digests = reference_sha256s or ((reference_sha256,) if reference_sha256 else ())
    return stable_key(
        "image",
        run_id,
        draft_version_id,
        provider,
        model,
        prompt_version,
        pipeline_version,
        "|".join(digests) or "no-reference",
        visual_brief_fingerprint,
        catalog_version,
        selector_version,
        validate_image_prompt(prompt),
    )


def image_content_key(sha256_hex: str, media_type: str = "image/png") -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", sha256_hex):
        raise ValueError("image checksum must be a lowercase SHA-256 digest")
    extensions = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
    extension = extensions.get(media_type)
    if extension is None:
        raise ValueError("unsupported generated image media type")
    return f"generated-images/sha256/{sha256_hex[:2]}/{sha256_hex}.{extension}"


def image_checksum(body: bytes) -> str:
    return sha256(body).hexdigest()
