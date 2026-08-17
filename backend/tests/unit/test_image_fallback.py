from __future__ import annotations

from io import BytesIO

import pytest
from app.domain.image_fallback import (
    IMAGE_OUTPUT_REPRESENTATION_RECOVERY_VERSION,
    IMAGE_PROVIDER_REJECTION_PROMPT_VERSION,
    build_provider_rejection_retry_prompt,
    provider_output_recovery_fingerprint,
    provider_rejection_retry_fingerprint,
    render_catalog_fallback_image,
)
from app.domain.visual_brief import (
    CONTROLLED_VISUAL_BRIEF_VERSION,
    AcceptedVisualContext,
    build_visual_brief,
)
from PIL import Image


def test_provider_rejection_prompt_uses_only_allowlisted_visual_brief_values() -> None:
    brief = build_visual_brief(
        AcceptedVisualContext(
            topic_title="机器人新闻中的不应回传标题",
            topic_summary="不应回传的摘要",
            copywriting="不应回传的家长文案",
            image_prompt="不应回传的原始提示词",
        )
    )

    prompt = build_provider_rejection_retry_prompt(brief, ())

    assert IMAGE_PROVIDER_REJECTION_PROMPT_VERSION in prompt
    assert "不应回传" not in prompt
    assert provider_rejection_retry_fingerprint("a" * 64, prompt) != "a" * 64


def test_representation_recovery_fingerprint_is_distinct_replay_stable_and_prompt_bound() -> None:
    original = "面向家长的科学探索插画"

    first = provider_output_recovery_fingerprint(
        "a" * 64,
        original,
        "image_output_invalid",
    )

    assert IMAGE_OUTPUT_REPRESENTATION_RECOVERY_VERSION == "image-output-representation-retry-v1"
    assert first != "a" * 64
    assert first == provider_output_recovery_fingerprint(
        "a" * 64,
        original,
        "image_output_invalid",
    )
    assert first != provider_output_recovery_fingerprint(
        "a" * 64,
        "不同但仍受控的提示词",
        "image_output_invalid",
    )
    assert provider_output_recovery_fingerprint(
        "a" * 64,
        original,
        "image_provider_rejected",
    ) == provider_rejection_retry_fingerprint("a" * 64, original)


def test_controlled_provider_rejection_prompt_preserves_exact_text_hierarchy() -> None:
    brief = build_visual_brief(
        AcceptedVisualContext(topic_title="人工智能教育中的不应回传标题"),
        version=CONTROLLED_VISUAL_BRIEF_VERSION,
    )

    prompt = build_provider_rejection_retry_prompt(brief, ())

    assert "Brand signature (exact, smallest): 赛先生科学" in prompt
    assert "Main title (exact, largest): 人工智能" in prompt
    assert "Subtitle (exact, secondary): 理解智能如何学习与反馈" in prompt
    assert "Render exactly those three Chinese text lines" in prompt
    assert "Optional keywords" not in prompt
    assert "守护好奇心" not in prompt
    assert "不应回传" not in prompt


def test_catalog_fallback_renderer_preserves_asset_aspect_ratio_on_square_canvas() -> None:
    source = Image.new("RGB", (900, 300), (40, 90, 160))
    source_buffer = BytesIO()
    source.save(source_buffer, format="PNG")

    rendered = render_catalog_fallback_image(source_buffer.getvalue())

    with Image.open(BytesIO(rendered)) as image:
        assert image.format == "PNG"
        assert image.size == (1024, 1024)


def test_catalog_fallback_renderer_rejects_invalid_input() -> None:
    with pytest.raises(ValueError, match="approved catalog image cannot be decoded"):
        render_catalog_fallback_image(b"not-an-image")
