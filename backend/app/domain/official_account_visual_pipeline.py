"""Frozen prospective visual policy, independent of legacy observational evaluation.

This module has no provider, storage, queue or social capability. A passing model review is
machine evidence only, never a human annotation or publication-rights assertion.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from app.domain.image_similarity import perceptual_dhash, perceptual_hash_distance
from app.domain.image_validation import validate_image_output
from app.domain.official_account_local import ArticlePackage

StrictVisualPipelineVersion = Literal["official-account-visual-pipeline-v1-native-strict"]
STRICT_VISUAL_PIPELINE_VERSION: StrictVisualPipelineVersion = (
    "official-account-visual-pipeline-v1-native-strict"
)
OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION = (
    "official-account-generated-visual-plan-v4-native-strict"
)
OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION = (
    "official-account-generated-visual-prompt-v4-native-strict"
)
OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_V4_VERSION = (
    "official-account-generated-body-jpeg-v2-native-strict"
)
STRICT_VISUAL_AUDIT_RUBRIC_VERSION = "official-account-final-upload-audit-v1"


@dataclass(frozen=True, slots=True)
class StrictVisualPolicy:
    version: StrictVisualPipelineVersion = STRICT_VISUAL_PIPELINE_VERSION
    generation_provider: Literal["comfly"] = "comfly"
    generation_model: Literal["gpt-image-2"] = "gpt-image-2"
    output_size: Literal["1536x1024"] = "1536x1024"
    native_width: int = 1536
    native_height: int = 1024
    minimum_reference_short_edge: int = 512
    scene_count: int = 5
    audit_count: int = 6
    audit_model: Literal["glm-5v-turbo"] = "glm-5v-turbo"
    audit_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    audit_endpoint: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    audit_rubric_version: str = STRICT_VISUAL_AUDIT_RUBRIC_VERSION
    # Literal threshold, not an alias to an independently evolving legacy policy.
    maximum_duplicate_distance: int = 6
    maximum_image_bytes: int = 12 * 1024 * 1024
    physical_posts_per_call: int = 1
    automatic_repairs: int = 0


STRICT_VISUAL_POLICY = StrictVisualPolicy()


def strict_visual_audit_criteria(
    *,
    article: ArticlePackage,
    section_index: int,
    block_context: str,
    cover: bool = False,
) -> tuple[str, ...]:
    """Eight bounded transient criteria for the actual final upload derivative."""
    if not 0 <= section_index < len(article.sections):
        raise ValueError("strict visual section is invalid")
    context = " ".join(block_context.split())[:480]
    if not context:
        raise ValueError("strict visual block context is empty")
    role = "cover" if cover else "body"
    return (
        (f"Role={role}. Article title: {article.title}. The image must explain this article.")[
            :200
        ],
        (f"Section: {article.sections[section_index].heading}. Match its specific idea.")[:200],
        f"Exact block context 1: {context[:170]}",
        f"Exact block context 2: {context[170:340] or '(continued above)'}",
        f"Exact block context 3: {context[340:480] or '(continued above)'}",
        "The approved reference character must be recognizable and central in a contextual "
        "science-education scene, not an isolated avatar or catalog composition.",
        "Reject words, letters, numbers, logos, watermarks, QR codes, anatomy defects, blur, "
        "unsupported science, or confusing child/parent interaction.",
        (
            "Final upload cover: article-relevant action and character survive cropping and "
            "compression; no cut face, isolated mascot, blur or misleading news photograph."
            if cover
            else "Final upload body scene: clear section-specific action, coherent composition, "
            "generous margins and sharp pixels; not a generic character pose."
        ),
    )


def strict_visual_audit_passes(
    *,
    accepted: bool,
    issues_present: bool,
    provider: str,
    model: str,
    request_fingerprint: str,
    expected_request_fingerprint: str,
) -> bool:
    """Identity and every issue are hard gates, distinct from non-blocking observe."""
    return bool(
        accepted is True
        and issues_present is False
        and provider == "openai-compatible"
        and model == STRICT_VISUAL_POLICY.audit_model
        and len(expected_request_fingerprint) == 64
        and all(char in "0123456789abcdef" for char in expected_request_fingerprint)
        and request_fingerprint == expected_request_fingerprint
    )


def strict_visual_batch_checks(
    body_images: tuple[bytes, ...], *, catalog_images: tuple[bytes, ...]
) -> tuple[str, ...]:
    """Validate all native publication scenes; return only bounded issue codes."""
    codes: set[str] = set()
    policy = STRICT_VISUAL_POLICY
    if len(body_images) != policy.scene_count:
        codes.add("strict_visual_body_count_invalid")
    if not catalog_images or len(catalog_images) > 41:
        codes.add("strict_visual_catalog_invalid")
    # Bound the work even when a caller bypasses the typed service's count gate.
    if len(body_images) > policy.scene_count or len(catalog_images) > 41:
        return tuple(sorted(codes))
    catalog_hashes: set[str] = set()
    catalog_perceptual: list[str] = []
    for image in catalog_images:
        check = validate_image_output(
            image, "image/jpeg", expected_dimensions=None, max_bytes=policy.maximum_image_bytes
        )
        if not check.passed:
            codes.add("strict_visual_catalog_invalid")
            continue
        catalog_hashes.add(sha256(image).hexdigest())
        catalog_perceptual.append(perceptual_dhash(image))
    hashes: set[str] = set()
    perceptual: list[str] = []
    for image in body_images:
        check = validate_image_output(
            image,
            "image/jpeg",
            expected_dimensions=(policy.native_width, policy.native_height),
            max_bytes=policy.maximum_image_bytes,
        )
        if not check.passed:
            codes.add("strict_visual_body_resolution_invalid")
            continue
        digest = sha256(image).hexdigest()
        dhash = perceptual_dhash(image)
        if digest in hashes:
            codes.add("strict_visual_exact_repetition")
        if any(
            perceptual_hash_distance(dhash, other) <= policy.maximum_duplicate_distance
            for other in perceptual
        ):
            codes.add("strict_visual_perceptual_repetition")
        if digest in catalog_hashes or any(
            perceptual_hash_distance(dhash, other) <= policy.maximum_duplicate_distance
            for other in catalog_perceptual
        ):
            codes.add("strict_visual_catalog_reuse")
        hashes.add(digest)
        perceptual.append(dhash)
    return tuple(sorted(codes))
