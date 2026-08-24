from __future__ import annotations

from hashlib import sha256
from html.parser import HTMLParser

import pytest
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_BODY_MEDIA_PLACEHOLDER,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V1_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V2_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V1_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V1_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V2_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V3_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V4_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V5_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V6_VERSION,
    OFFICIAL_ACCOUNT_RULE_V1_VERSION,
    OFFICIAL_ACCOUNT_RULE_V2_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V1_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V2_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V3_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V4_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V5_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V6_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V1_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V2_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V3_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V4_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V5_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V6_VERSION,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleQuoteBlock,
    _split_conclusion_cards,
    article_package_fingerprint,
    body_media_placeholder,
    render_wechat_html,
    resolve_body_media_placeholder,
    resolve_body_media_placeholders,
)
from test_official_account_article import (
    fixture_article,
    historical_fixture_article,
    historical_multi_fixture_article,
)

_ALLOWED_TAG_ATTRIBUTES = {
    "a": {"href", "referrerpolicy", "rel", "style"},
    "blockquote": {"style"},
    "br": set(),
    "em": set(),
    "h1": {"style"},
    "h2": {"style"},
    "img": {"alt", "src", "style"},
    "li": {"style"},
    "ol": {"style"},
    "p": {"style"},
    "section": {"style"},
    "span": {"style"},
    "strong": set(),
    "ul": {"style"},
}
_ALLOWED_STYLE_PROPERTIES = {
    "background",
    "background-color",
    "border",
    "border-bottom",
    "border-left",
    "border-radius",
    "border-top",
    "color",
    "display",
    "font-size",
    "font-weight",
    "height",
    "letter-spacing",
    "line-height",
    "margin",
    "margin-right",
    "margin-top",
    "max-width",
    "padding",
    "padding-left",
    "padding-top",
    "text-align",
    "text-decoration",
    "vertical-align",
    "width",
    "word-break",
}


class _OutputShapeParser(HTMLParser):
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        assert tag in _ALLOWED_TAG_ATTRIBUTES
        attribute_map = dict(attrs)
        assert set(attribute_map) <= _ALLOWED_TAG_ATTRIBUTES[tag]
        if tag == "a":
            assert (attribute_map.get("href") or "").startswith("https://")
            assert attribute_map.get("rel") == "noopener noreferrer"
            assert attribute_map.get("referrerpolicy") == "no-referrer"
        if tag == "img":
            assert attribute_map.get("src") in {
                body_media_placeholder(ordinal) for ordinal in range(5)
            }
        style = attribute_map.get("style")
        if style is None:
            return
        lowered = style.casefold()
        assert "url(" not in lowered
        assert "@import" not in lowered
        assert "javascript:" not in lowered
        properties = {
            declaration.split(":", 1)[0] for declaration in style.split(";") if declaration
        }
        assert properties <= _ALLOWED_STYLE_PROPERTIES


def _contrast_ratio(foreground: str, background: str) -> float:
    def luminance(value: str) -> float:
        channels = [int(value[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    first, second = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (first + 0.05) / (second + 0.05)


def _with_render_versions(
    article: ArticlePackage,
    *,
    renderer_version: str,
    style_version: str,
    template_version: str,
    legacy_generation_versions: bool = False,
    generator_prompt_version: str | None = None,
    rule_version: str | None = None,
) -> ArticlePackage:
    updates = {
        "renderer_version": renderer_version,
        "style_version": style_version,
        "template_version": template_version,
    }
    if legacy_generation_versions:
        updates.update(
            {
                "generator_prompt_version": OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V1_VERSION,
                "rule_version": OFFICIAL_ACCOUNT_RULE_V1_VERSION,
                "local_adapter_version": OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V1_VERSION,
            }
        )
    if generator_prompt_version is not None:
        updates["generator_prompt_version"] = generator_prompt_version
    if rule_version is not None:
        updates["rule_version"] = rule_version
    versions = article.versions.model_copy(update=updates)
    provisional = article.model_copy(update={"versions": versions, "content_fingerprint": "0" * 64})
    return provisional.model_copy(
        update={"content_fingerprint": article_package_fingerprint(provisional)}
    )


async def test_renderer_is_deterministic_and_escapes_model_text() -> None:
    _, _, article = await fixture_article()
    unsafe = article.model_copy(update={"title": '<script onload="boom">标题</script>'})

    first = render_wechat_html(unsafe)
    second = render_wechat_html(unsafe)

    assert first == second
    assert [
        first.canonical_html.count(body_media_placeholder(ordinal)) for ordinal in range(5)
    ] == [1, 1, 1, 0, 0]
    assert "<script" not in first.canonical_html
    assert "<script onload=" not in first.canonical_html
    assert "&lt;script onload=&quot;boom&quot;&gt;" in first.canonical_html
    assert "javascript:" not in first.canonical_html
    assert "data:" not in first.canonical_html
    assert "内容边界说明（不提供外链）" in first.canonical_html  # noqa: RUF001
    assert "脱敏演示来源" not in first.canonical_html
    assert "example.invalid" not in first.canonical_html


async def test_renderer_refuses_an_unsafe_source_projection_even_if_validation_was_bypassed() -> (
    None
):
    _, _, article = await fixture_article()
    unsafe_source = article.sources[0].model_copy(
        update={"source_url": 'javascript:alert(1)" onclick="boom'}
    )
    unsafe = article.model_copy(update={"sources": (unsafe_source,)})

    with pytest.raises(ValueError, match="source URL must be safe HTTPS"):
        render_wechat_html(unsafe)


async def test_science_field_guide_v4_uses_governed_map_and_semantic_cards() -> None:
    _, _, article = await historical_fixture_article()

    rendered = render_wechat_html(article)
    encoded = rendered.canonical_html.encode("utf-8")

    assert rendered.renderer_version == OFFICIAL_ACCOUNT_RENDERER_V4_VERSION
    assert rendered.style_version == OFFICIAL_ACCOUNT_STYLE_V4_VERSION
    assert rendered.template_version == OFFICIAL_ACCOUNT_TEMPLATE_V4_VERSION
    assert article.content_fingerprint == (
        "2fbc390d9c1622081b5ab456c0da031016a812653115dd415a0d9c2af8d3ab05"
    )
    assert len(encoded) == 16_589
    assert sha256(encoded).hexdigest() == (
        "c098c0e99addd8df40444be467c61d15296d27f0cb219526cc884f50d320c1a8"
    )
    assert rendered.render_fingerprint == (
        "62b2984f263c0e92855461a8907a565ac81ac097a1304727871de9b1e591f12e"
    )
    assert "SCIENCE FIELD GUIDE · 科学教育观察" in rendered.canonical_html
    assert ">先看核心判断</p>" in rendered.canonical_html
    assert ">家长先看</p>" in rendered.canonical_html
    assert ">PART 01 · FIELD NOTE</p>" in rendered.canonical_html
    assert ">家庭实践</p>" in rendered.canonical_html
    assert ">给家长的三句话</p>" in rendered.canonical_html
    assert ">资料来源与适用边界</h2>" in rendered.canonical_html
    assert "font-size:15px;line-height:1.88" in rendered.canonical_html
    assert "background-color:#fbf8f1" in rendered.canonical_html
    assert "border-top:5px solid #163c5a" in rendered.canonical_html
    assert "background-color:#e3f5f6" in rendered.canonical_html
    assert "background-color:#fff1c9" in rendered.canonical_html
    assert "#b9573f" not in rendered.canonical_html
    assert "#ad4f39" not in rendered.canonical_html
    assert "#d82821" not in rendered.canonical_html
    assert "gradient" not in rendered.canonical_html.casefold()
    assert f'src="{OFFICIAL_ACCOUNT_BODY_MEDIA_PLACEHOLDER}"' in rendered.canonical_html
    assert "example.invalid" not in rendered.canonical_html
    for section in article.sections[:5]:
        assert rendered.canonical_html.count(section.heading) == 2
    assert "".join(_split_conclusion_cards(article.conclusion)) == article.conclusion
    assert 1 <= len(_split_conclusion_cards(article.conclusion)) <= 3
    assert rendered.canonical_html.count('<p style="margin:0 0 17px') == 16

    parser = _OutputShapeParser()
    parser.feed(rendered.canonical_html)
    parser.close()


async def test_science_field_guide_v5_is_exact_and_uses_all_planned_slots() -> None:
    _, _, article = await historical_multi_fixture_article()

    rendered = render_wechat_html(article)
    encoded = rendered.canonical_html.encode("utf-8")

    assert article.content_fingerprint == (
        "471730aa3dcee9b33abe1fb164c1981787db7c8080c68e226b697df28339f27b"
    )
    assert rendered.renderer_version == OFFICIAL_ACCOUNT_RENDERER_V5_VERSION
    assert rendered.style_version == OFFICIAL_ACCOUNT_STYLE_V5_VERSION
    assert rendered.template_version == OFFICIAL_ACCOUNT_TEMPLATE_V5_VERSION
    assert len(encoded) == 17_619
    assert sha256(encoded).hexdigest() == (
        "d0c780b96a7fc842a0ea9e9b0501975a5f82565f64a1c67f33c4436779744217"
    )
    assert rendered.render_fingerprint == (
        "54e442b8f89a9119661edb6b5624f242665288d6e09045bb83d5897881f125cb"
    )
    assert [
        rendered.canonical_html.count(body_media_placeholder(ordinal)) for ordinal in range(5)
    ] == [1, 1, 1, 0, 0]

    media = tuple(
        (
            ordinal,
            f"/api/v1/official-account-local/media/local-media-body-{ordinal}",
        )
        for ordinal in range(3)
    )
    resolved = resolve_body_media_placeholders(rendered.canonical_html, media)
    assert all(url in resolved for _ordinal, url in media)
    assert not any(body_media_placeholder(ordinal) in resolved for ordinal in range(5))


async def test_science_field_guide_v6_is_semantic_and_reader_clean() -> None:
    _, _, article = await fixture_article()

    rendered = render_wechat_html(article)

    assert rendered.renderer_version == OFFICIAL_ACCOUNT_RENDERER_V6_VERSION
    assert rendered.style_version == OFFICIAL_ACCOUNT_STYLE_V6_VERSION
    assert rendered.template_version == OFFICIAL_ACCOUNT_TEMPLATE_V6_VERSION
    assert article.content_fingerprint == (
        "37040e36c4df436090f34ac58baf3e6ed7544a2015e6ae9041c86368fdfe6a05"
    )
    encoded = rendered.canonical_html.encode("utf-8")
    assert len(encoded) == 17_318
    assert sha256(encoded).hexdigest() == (
        "14b34d9469d9f2d6986c637b309f7c040c6a49e0d4e7e75490095fa9db3704e6"
    )
    assert rendered.render_fingerprint == (
        "b72c7f84b739dcfcb0c3076c3a9888b47af96d202045652ec82022132b821989"
    )
    assert [
        rendered.canonical_html.count(body_media_placeholder(ordinal)) for ordinal in range(5)
    ] == [1, 1, 1, 0, 0]
    assert "孩子用放大镜观察叶片，把最初的好奇变成可以描述的问题" in rendered.canonical_html  # noqa: RUF001
    assert "孩子和家长一起完成小实验，用一次只改变一个条件来核对猜想" in rendered.canonical_html  # noqa: RUF001
    assert "孩子整理观察记录并讲述变化，在复盘中允许自己修正原来的解释" in rendered.canonical_html  # noqa: RUF001
    forbidden = (
        "脱敏示例材料",
        "可靠事实与品牌表达",
        "本地正文配图",
        "schema",
        "provider",
        "media-plan",
    )
    assert not any(value in rendered.canonical_html for value in forbidden)


async def test_science_field_guide_v4_labels_quotes_as_key_judgments() -> None:
    _, _, article = await historical_fixture_article()
    first_section = article.sections[0]
    first_block = first_section.blocks[0]
    assert isinstance(first_block, ArticleParagraphBlock)
    judgment = ArticleQuoteBlock(
        kind="quote",
        text=first_block.text,
        claim_refs=first_block.claim_refs,
    )
    section = first_section.model_copy(update={"blocks": (judgment, *first_section.blocks[1:])})
    updated = article.model_copy(update={"sections": (section, *article.sections[1:])})

    rendered = render_wechat_html(updated)

    assert ">关键判断</p>" in rendered.canonical_html
    assert first_block.text in rendered.canonical_html


def test_v4_small_text_palette_meets_normal_text_contrast() -> None:
    assert _contrast_ratio("#237482", "#fbf8f1") >= 4.5
    assert _contrast_ratio("#237482", "#e3f5f6") >= 4.5
    assert _contrast_ratio("#7c5206", "#fff1c9") >= 4.5
    assert _contrast_ratio("#fbf8f1", "#163c5a") >= 4.5


async def test_v1_renderer_remains_byte_compatible_for_existing_fixture() -> None:
    _, _, current_article = await historical_fixture_article()
    article = _with_render_versions(
        current_article,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_V1_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_V1_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_V1_VERSION,
        legacy_generation_versions=True,
    )

    rendered = render_wechat_html(
        article,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_V1_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_V1_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_V1_VERSION,
    )

    encoded = rendered.canonical_html.encode("utf-8")
    assert len(encoded) == 8_984
    assert sha256(encoded).hexdigest() == (
        "a875de3673056246e3e8d71ae6b3e4bd268afe0512cca63eb6f29cd427344d0b"
    )
    assert rendered.render_fingerprint == (
        "13be83049cf5291fe05da4516a9e6b04949793ddb1ae3dd13e345245b86bb28e"
    )


async def test_v2_renderer_remains_byte_compatible_for_existing_fixture() -> None:
    _, _, current_article = await historical_fixture_article()
    article = _with_render_versions(
        current_article,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_V2_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_V2_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_V2_VERSION,
        legacy_generation_versions=True,
    )

    rendered = render_wechat_html(article)
    encoded = rendered.canonical_html.encode("utf-8")

    assert article.content_fingerprint == (
        "b917b63f638ce12d9229cc307f1f426f35ccf148ecb416ca80b52ad6690bbe95"
    )
    assert len(encoded) == 13_798
    assert sha256(encoded).hexdigest() == (
        "b2720fe2839072306c44864a513ee072829e27ae45ff875854e17bbc5fab07ac"
    )
    assert rendered.render_fingerprint == (
        "2ff4b0b77e5b5394c5e3ad0ad20bc44393f922c5fb2aa60cc574790938fda749"
    )
    assert "SCIENCE NOTES · 教育观察" in rendered.canonical_html
    assert "border-top:5px solid #b9573f" in rendered.canonical_html


async def test_v3_renderer_remains_byte_compatible_for_existing_fixture() -> None:
    _, _, current_article = await historical_fixture_article()
    article = _with_render_versions(
        current_article,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_V3_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_V3_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_V3_VERSION,
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V2_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_V2_VERSION,
    )

    rendered = render_wechat_html(article)
    encoded = rendered.canonical_html.encode("utf-8")

    assert article.content_fingerprint == (
        "d01e37a3f4a0821923dde4e23861fc113a60cee95659ab2ab68a9cba333ea915"
    )
    assert len(encoded) == 16_279
    assert sha256(encoded).hexdigest() == (
        "5e8071e0d530743c5a0b38b39df65e26a7600cda77e70212804cd21eb74bc641"
    )
    assert rendered.render_fingerprint == (
        "2a7406eb37afb87111c45614ba49dbf44433c2de67144c772fd7c165d0703ab9"
    )
    assert "SCIENCE EXPLORER · 家庭探究手册" in rendered.canonical_html


async def test_renderer_rejects_mismatched_or_unknown_version_bundles() -> None:
    _, _, article = await fixture_article()

    with pytest.raises(ValueError, match="must match the article package"):
        render_wechat_html(
            article,
            renderer_version=OFFICIAL_ACCOUNT_RENDERER_V1_VERSION,
            style_version=OFFICIAL_ACCOUNT_STYLE_V1_VERSION,
            template_version=OFFICIAL_ACCOUNT_TEMPLATE_V1_VERSION,
        )

    unknown = _with_render_versions(
        article,
        renderer_version="wechat-html-renderer-v99",
        style_version="wechat-inline-style-v99",
        template_version="wechat-fragment-template-v99",
    )
    with pytest.raises(ValueError, match="version bundle is unsupported"):
        render_wechat_html(unknown)


async def test_media_resolution_accepts_only_controlled_local_url() -> None:
    _, _, article = await historical_fixture_article()
    rendered = render_wechat_html(article)
    media_url = "/api/v1/official-account-local/media/local-media-body-safe"

    resolved = resolve_body_media_placeholder(rendered.canonical_html, media_url)

    assert OFFICIAL_ACCOUNT_BODY_MEDIA_PLACEHOLDER not in resolved
    assert f'src="{media_url}"' in resolved


async def test_media_resolution_rejects_external_or_missing_placeholder() -> None:
    _, _, article = await historical_fixture_article()
    rendered = render_wechat_html(article)

    try:
        resolve_body_media_placeholder(rendered.canonical_html, "https://example.invalid/image")
    except ValueError as error:
        assert "controlled API path" in str(error)
    else:
        raise AssertionError("external media URL was accepted")

    try:
        resolve_body_media_placeholder(
            rendered.canonical_html.replace(OFFICIAL_ACCOUNT_BODY_MEDIA_PLACEHOLDER, "missing"),
            "/api/v1/official-account-local/media/local-media-body-safe",
        )
    except ValueError as error:
        assert "placeholder count" in str(error)
    else:
        raise AssertionError("missing placeholder was accepted")
