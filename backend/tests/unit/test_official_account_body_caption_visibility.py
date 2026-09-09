"""Independent presentation regressions: hide body captions, never media or attribution."""

from __future__ import annotations

import re
from dataclasses import replace
from hashlib import sha256
from html import unescape
from typing import Any
from uuid import UUID

import pytest
from app.application.ports.official_account_strict_visual import (
    ObserveVisualMediaEvidence,
    StrictVisualMediaEvidence,
)
from app.application.services.official_account_strict_prepared import (
    StrictPreparedProjection,
    build_strict_prepared_projection,
    validate_strict_prepared_projection,
)
from app.domain.official_account_editor_handoff import EditorHandoffMediaAsset
from app.domain.official_account_editor_handoff_v2 import render_editor_handoff_v2_body
from app.domain.official_account_local import (
    ArticlePackage,
    ArticleParagraphBlock,
    article_package_fingerprint,
)
from app.domain.official_account_strict_layout import STRICT_LAYOUT_PROJECTION_V2_VERSION
from app.domain.official_account_visual_pipeline import OBSERVE_VISUAL_PIPELINE_VERSION
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION as V4,
)
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION as V5,
)
from app.domain.official_account_xiaosai_footer import XiaosaiFooterAsset
from pydantic import TypeAdapter
from test_official_account_native_observe import observe_projection  # noqa: F401
from test_official_account_strict_prepared import (
    _reproject_layout,
    strict_projection,  # noqa: F401
)
from test_official_account_visual_preview import _image, captured  # noqa: F401

_IMAGE_SECTION = re.compile(
    r'<section style="[^"]+">'
    r'(?P<image><img src="(?P<path>[^"]+)"[^>]+>)'
    r"(?P<caption><p[^>]*>.*?</p>)(?P<rest>.*?)</section>"
)
CONTEXT_NOTICE = "按当前本地策略直接使用，发布权未验证；仅作上下文参考，不是事实证据。"  # noqa: RUF001


def _inputs(projection: StrictPreparedProjection) -> dict[str, Any]:
    raw = projection.manifest
    media = tuple(EditorHandoffMediaAsset.model_validate(item) for item in raw["media"])
    evidence_type = (
        ObserveVisualMediaEvidence
        if raw["visual_pipeline_version"] == OBSERVE_VISUAL_PIPELINE_VERSION
        else StrictVisualMediaEvidence
    )
    return {
        "run_id": UUID(str(raw["run_id"])),
        "article_version_id": UUID(str(raw["article_version_id"])),
        "render_version_id": UUID(str(raw["render_version_id"])),
        "role": raw["role"],
        "article": ArticlePackage.model_validate(raw["article"]),
        "media": media,
        "evidence": tuple(
            TypeAdapter(evidence_type).validate_python(item) for item in raw["visual_evidence"]
        ),
        "files": {item.path: projection.files[item.path] for item in media},
        "context_originals": {
            item["ordinal"]: projection.files[item["source_path"]]
            for item in raw["context_derivatives"]
        },
        "layout_projection_version": raw["layout_projection_version"],
        "visual_pipeline_version": raw["visual_pipeline_version"],
    }


def _with_v5_footer(inputs: dict[str, Any]) -> None:
    """Reuse the captured approved-reference bytes, not a sixth generated image."""
    selection = inputs["article"].media_selection
    first = selection.assignments[0]
    content = next(
        body
        for index in range(5)
        if sha256(body := _image(index)).hexdigest() == first.publication_checksum
    )
    footer = XiaosaiFooterAsset(
        byte_size=len(content),
        sha256=first.publication_checksum,
        width=512,
        height=512,
        catalog_version=selection.catalog_version,
        catalog_asset_ref=first.candidate_ref,
        source_master_sha256=first.source_checksum,
    )
    inputs["footer"] = footer
    inputs["files"] = {**inputs["files"], footer.path: content}


def _before_signature(html: str, author: str) -> str:
    position = html.index(f"我是{author}")
    start = html.rfind("<section", 0, position)
    assert start > 0
    return html[:start]


def _without_body_captions(html: str) -> str:
    """Test oracle removes exact body image caption nodes, not their text elsewhere."""
    count = 0

    def omit(match: re.Match[str]) -> str:
        nonlocal count
        if not match["path"].startswith("assets/body-"):
            return match[0]
        count += 1
        start, end = match.span("caption")
        return match[0][: start - match.start()] + match[0][end - match.start() :]

    result = _IMAGE_SECTION.sub(omit, html)
    assert count == 5
    return result


def _without_context_notices(html: str) -> str:
    """Remove only a context image's exact trailing notice, retaining its caption."""

    def omit(match: re.Match[str]) -> str:
        if not match["path"].startswith("assets/context-"):
            return match[0]
        assert unescape(re.sub(r"<[^>]+>", "", match["rest"])) == CONTEXT_NOTICE
        start, end = match.span("rest")
        return match[0][: start - match.start()] + match[0][end - match.start() :]

    return _IMAGE_SECTION.sub(omit, html)


@pytest.mark.parametrize("observed", [False, True])
def test_actual_v5_prepared_caller_removes_only_body_captions_and_internal_notices(
    strict_projection: StrictPreparedProjection,  # noqa: F811
    observe_projection: StrictPreparedProjection,  # noqa: F811
    observed: bool,
) -> None:
    source = observe_projection if observed else strict_projection
    original_files = dict(source.files)
    original_manifest = repr(source.manifest)
    inputs = _inputs(source)
    article_before = inputs["article"].model_dump_json()
    media_before = tuple(item.model_dump_json() for item in inputs["media"])
    inputs["evidence"] = tuple(replace(item, prompt_version=V5) for item in inputs["evidence"])
    _with_v5_footer(inputs)
    new = build_strict_prepared_projection(**inputs)
    old_html = source.files["article-body.html"].decode()
    new_html = new.files["article-body.html"].decode()
    assert _before_signature(new_html, inputs["article"].author) == _before_signature(
        _without_context_notices(_without_body_captions(old_html)), inputs["article"].author
    )
    assert re.findall(r"<img [^>]+>", new_html)[:-1] == re.findall(r"<img [^>]+>", old_html)
    assert new.manifest["media"][:-1] == source.manifest["media"]
    for name in ("article", "context_derivatives", "placements", "recipe", "renderer"):
        assert new.manifest[name] == source.manifest[name]
    assert {
        key: value
        for key, value in new.files.items()
        if key not in {"article-body.html", inputs["footer"].path}
    } == {key: value for key, value in source.files.items() if key != "article-body.html"}
    assert inputs["article"].model_dump_json() == article_before
    assert tuple(item.model_dump_json() for item in inputs["media"]) == media_before
    assert source.files == original_files and repr(source.manifest) == original_manifest
    validate_strict_prepared_projection(new.manifest, new.files)


def test_renderer_option_preserves_same_prose_and_news_caption_metadata(
    strict_projection: StrictPreparedProjection,  # noqa: F811
) -> None:
    inputs = _inputs(strict_projection)
    media = inputs["media"]
    body = next(item for item in media if item.role == "body")
    article = inputs["article"]
    section = article.sections[0]
    article = article.model_copy(
        update={
            "sections": (
                section.model_copy(
                    update={
                        "blocks": (
                            *section.blocks,
                            ArticleParagraphBlock(kind="paragraph", text=body.alt_text),
                        )
                    }
                ),
                *article.sections[1:],
            )
        }
    )
    article = article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(article)}
    )
    # A context image with identical caption/alt wording is still a news image.
    media = tuple(
        item.model_copy(update={"alt_text": body.alt_text, "caption": body.alt_text})
        if item.role == "context"
        else item
        for item in media
    )
    old = render_editor_handoff_v2_body(article=article, media=media)
    new = render_editor_handoff_v2_body(article=article, media=media, hide_body_captions=True)
    assert new.body_html == _without_body_captions(old.body_html)
    visible = unescape(re.sub(r"<[^>]+>", "", new.body_html))
    assert body.alt_text in visible
    for match in _IMAGE_SECTION.finditer(old.body_html):
        if "context-" in match["path"]:
            assert match[0] in new.body_html
    assert old.placements == new.placements
    assert old.recipe == new.recipe
    assert old.emphasis == new.emphasis


def test_v4_and_default_renderer_remain_literal_golden(
    strict_projection: StrictPreparedProjection,  # noqa: F811
) -> None:
    inputs = _inputs(strict_projection)
    default = render_editor_handoff_v2_body(article=inputs["article"], media=inputs["media"])
    explicit = render_editor_handoff_v2_body(
        article=inputs["article"], media=inputs["media"], hide_body_captions=False
    )
    assert default == explicit
    assert sha256(default.body_html.encode()).hexdigest() == (
        "d0922b6e3dbb4667c6ace85e5e0b2478ac37437e88bfbd0b8875f73f7066def7"
    )
    assert build_strict_prepared_projection(**inputs) == strict_projection
    assert sha256(strict_projection.files["article-body.html"]).hexdigest() == (
        "567c7623f89ad2c26e682aa7f77d67daa9503f8ec588ad31dc678ae3a05e1868"
    )
    compact = _reproject_layout(strict_projection, STRICT_LAYOUT_PROJECTION_V2_VERSION)
    assert sha256(compact.files["article-body.html"]).hexdigest() == (
        "d3d7bf3bb53f2b230030bbc5c2e364d64bac49f57cdb77d0e426b925f991ce3d"
    )
    assert compact.manifest["article"] == strict_projection.manifest["article"]
    validate_strict_prepared_projection(compact.manifest, compact.files)
    assert len(_IMAGE_SECTION.findall(default.body_html)) >= 5


@pytest.mark.parametrize("changed_index", [0, 4, 5])
def test_prepared_caption_option_does_not_accept_mixed_generation_versions(
    strict_projection: StrictPreparedProjection,  # noqa: F811
    changed_index: int,
) -> None:
    inputs = _inputs(strict_projection)
    inputs["evidence"] = tuple(
        replace(item, prompt_version=V4 if index == changed_index else V5)
        for index, item in enumerate(inputs["evidence"])
    )
    with pytest.raises(ValueError, match="prompt bundle is mixed"):
        build_strict_prepared_projection(**inputs)
