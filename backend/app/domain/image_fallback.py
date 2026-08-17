from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from typing import Literal

from PIL import Image, UnidentifiedImageError

from app.domain.image_generation import validate_image_prompt
from app.domain.value_objects import stable_key
from app.domain.visual_brief import (
    VisualBrief,
    VisualReferenceDescriptor,
    VisualRenderTextMode,
    controlled_visual_text_hierarchy,
)

IMAGE_PROVIDER_REJECTION_PROMPT_VERSION = "image-provider-rejection-retry-v1"
IMAGE_OUTPUT_REPRESENTATION_RECOVERY_VERSION = "image-output-representation-retry-v1"
IMAGE_CATALOG_FALLBACK_RENDERER_VERSION = "brand-catalog-square-v1"
_FALLBACK_CANVAS_SIZE = 1024
_FALLBACK_SUBJECT_MAX_SIZE = 896
_FALLBACK_BACKGROUND = (246, 250, 252, 255)

ProviderOutputRecoveryErrorCode = Literal[
    "image_provider_rejected",
    "image_output_invalid",
]


def build_provider_rejection_retry_prompt(
    brief: VisualBrief,
    references: Sequence[VisualReferenceDescriptor],
) -> str:
    """Build a topic-preserving recovery prompt without source or copy text.

    The visual brief is already deterministic and allowlisted. This intentionally does not reuse
    the original provider prompt, raw topic title, summary, or parent-facing copy that may have
    caused an upstream rejection.
    """

    ordered = tuple(references)
    reference_lines = (
        "No reference images are required."
        if not ordered
        else "Reference roles: "
        + ", ".join(f"{index}:{reference.role.value}" for index, reference in enumerate(ordered, 1))
        + "."
    )
    if brief.render_text_mode is VisualRenderTextMode.BRAND_SIGNATURE_TITLE_SUBTITLE:
        brand_signature, main_title, subtitle = controlled_visual_text_hierarchy(brief)
        prompt = "\n".join(
            (
                f"Recovery prompt version: {IMAGE_PROVIDER_REJECTION_PROMPT_VERSION}",
                "Create a square, parent-facing science education illustration.",
                "Use only the supplied approved reference images for Sai Xiansheng and Xiaosai "
                "visual identity. Preserve the unified polished 3D cartoon rendering.",
                reference_lines,
                f"Education category: {brief.category.value}.",
                f"Learning goal: {brief.learning_goal}.",
                f"Scene: {brief.scene}.",
                f"Main action: {brief.main_action}.",
                "Use a compact three-level text group in a restrained deep-science-blue rounded "
                "title card with one small orange accent. Keep it readable in reserved editorial "
                "space without covering a face, scientific object, or main action.",
                f"Brand signature (exact, smallest): {brand_signature}",
                f"Main title (exact, largest): {main_title}",
                f"Subtitle (exact, secondary): {subtitle}",
                "Render exactly those three Chinese text lines. Render no other text, pseudo-text, "
                "decorative glyph strings, labels, letters, numbers, logos, watermarks, QR codes, "
                "URLs, real children, product claims, or promotional promises.",
            )
        )
        return validate_image_prompt(prompt)
    keywords = ", ".join(brief.text_layer.keywords) or "none"
    brand_values = ", ".join(brief.text_layer.brand_values) or "none"
    prompt = "\n".join(
        (
            f"Recovery prompt version: {IMAGE_PROVIDER_REJECTION_PROMPT_VERSION}",
            "Create a square, parent-facing science education illustration.",
            "Use only the supplied approved reference images for Sai Xiansheng and Xiaosai "
            "visual identity.",
            reference_lines,
            f"Education category: {brief.category.value}.",
            f"Learning goal: {brief.learning_goal}.",
            f"Scene: {brief.scene}.",
            f"Main action: {brief.main_action}.",
            "Composition: clear focal subject, warm and trustworthy learning atmosphere, "
            "polished 3D illustration.",
            "Render no real children, product names, claims, logos, watermarks, QR codes, "
            "URLs, or extra text.",
            f"Optional editorial title: {brief.text_layer.title}.",
            f"Optional learning line: {brief.text_layer.learning_line or 'none'}.",
            f"Optional keywords: {keywords}.",
            f"Optional brand value: {brand_values}.",
        )
    )
    return validate_image_prompt(prompt)


def provider_rejection_retry_fingerprint(base_fingerprint: str, prompt: str) -> str:
    """Return a distinct provider idempotency key for the single recovery request."""

    return stable_key(
        "image-provider-rejection-retry",
        base_fingerprint,
        IMAGE_PROVIDER_REJECTION_PROMPT_VERSION,
        validate_image_prompt(prompt),
    )


def provider_output_recovery_fingerprint(
    base_fingerprint: str,
    prompt: str,
    initial_error_code: ProviderOutputRecoveryErrorCode,
) -> str:
    """Derive the replay-stable idempotency key for one provider-output recovery."""

    if initial_error_code == "image_provider_rejected":
        return provider_rejection_retry_fingerprint(base_fingerprint, prompt)
    if initial_error_code != "image_output_invalid":
        raise ValueError("unsupported provider-output recovery error code")
    return stable_key(
        "image-output-representation-retry",
        base_fingerprint,
        IMAGE_OUTPUT_REPRESENTATION_RECOVERY_VERSION,
        validate_image_prompt(prompt),
    )


def render_catalog_fallback_image(image_bytes: bytes) -> bytes:
    """Render one approved catalog PNG onto the fixed package canvas.

    The source asset remains checksum-verified by the catalog before this call. This renderer only
    normalizes its dimensions; it never synthesizes text, symbols, or additional subject matter.
    """

    try:
        with Image.open(BytesIO(image_bytes)) as source:
            source.load()
            normalized = source.convert("RGBA")
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError("approved catalog image cannot be decoded") from error

    normalized.thumbnail(
        (_FALLBACK_SUBJECT_MAX_SIZE, _FALLBACK_SUBJECT_MAX_SIZE), Image.Resampling.LANCZOS
    )
    canvas = Image.new("RGBA", (_FALLBACK_CANVAS_SIZE, _FALLBACK_CANVAS_SIZE), _FALLBACK_BACKGROUND)
    offset = (
        (_FALLBACK_CANVAS_SIZE - normalized.width) // 2,
        (_FALLBACK_CANVAS_SIZE - normalized.height) // 2,
    )
    canvas.alpha_composite(normalized, dest=offset)
    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()
