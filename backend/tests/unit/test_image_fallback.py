from __future__ import annotations

from io import BytesIO

import pytest
from app.domain.image_fallback import (
    IMAGE_PROVIDER_REJECTION_PROMPT_VERSION,
    build_provider_rejection_retry_prompt,
    provider_rejection_retry_fingerprint,
    render_catalog_fallback_image,
)
from app.domain.visual_brief import AcceptedVisualContext, build_visual_brief
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
