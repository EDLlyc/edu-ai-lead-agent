"""V5 reader-facing notice suppression must never erase source or rights facts."""

from __future__ import annotations

import re
from dataclasses import replace
from html import unescape

import pytest
from app.application.services.official_account_strict_prepared import (
    StrictPreparedProjection,
    build_strict_prepared_projection,
    validate_strict_prepared_projection,
)
from app.domain.official_account_editor_handoff_v2 import render_editor_handoff_v2_body
from app.domain.official_account_local import ArticleParagraphBlock, article_package_fingerprint
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION as V5,
)
from test_official_account_body_caption_visibility import (
    _IMAGE_SECTION,
    CONTEXT_NOTICE,
    _before_signature,
    _inputs,
    _with_v5_footer,
    _without_body_captions,
    _without_context_notices,
)
from test_official_account_native_observe import observe_projection  # noqa: F401
from test_official_account_strict_prepared import strict_projection  # noqa: F401
from test_official_account_visual_preview import captured  # noqa: F401


@pytest.mark.parametrize("observed", [False, True])
@pytest.mark.parametrize("no_context", [False, True])
def test_actual_v5_notice_projection_preserves_all_provenance_and_same_article_prose(
    strict_projection: StrictPreparedProjection,  # noqa: F811
    observe_projection: StrictPreparedProjection,  # noqa: F811
    observed: bool,
    no_context: bool,
) -> None:
    inputs = _inputs(observe_projection if observed else strict_projection)
    article = inputs["article"]
    first = article.sections[0]
    article = article.model_copy(
        update={
            "sections": (
                first.model_copy(
                    update={
                        "blocks": (
                            *first.blocks,
                            ArticleParagraphBlock(kind="paragraph", text=CONTEXT_NOTICE),
                        )
                    }
                ),
                *article.sections[1:],
            )
        }
    )
    if no_context:
        article = article.model_copy(
            update={
                "news_context_media": article.news_context_media.model_copy(
                    update={"status": "not_present", "items": ()}
                )
            }
        )
        inputs["media"] = tuple(item for item in inputs["media"] if item.role != "context")
        inputs["files"] = {item.path: inputs["files"][item.path] for item in inputs["media"]}
        inputs["context_originals"] = {}
    inputs["article"] = article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(article)}
    )
    old = build_strict_prepared_projection(**inputs)
    inputs["evidence"] = tuple(replace(item, prompt_version=V5) for item in inputs["evidence"])
    _with_v5_footer(inputs)
    new = build_strict_prepared_projection(**inputs)
    old_html = old.files["article-body.html"].decode()
    new_html = new.files["article-body.html"].decode()
    assert _before_signature(new_html, inputs["article"].author) == _before_signature(
        _without_context_notices(_without_body_captions(old_html)), inputs["article"].author
    )
    assert re.findall(r"<img [^>]+>", old_html) == re.findall(r"<img [^>]+>", new_html)[:-1]
    assert unescape(re.sub(r"<[^>]+>", "", new_html)).count(CONTEXT_NOTICE) == 1
    assert new.manifest["media"][:-1] == old.manifest["media"]
    for field in ("article", "context_derivatives", "placements", "recipe", "renderer"):
        assert new.manifest[field] == old.manifest[field]
    assert {
        key: value
        for key, value in new.files.items()
        if key not in {"article-body.html", inputs["footer"].path}
    } == {key: value for key, value in old.files.items() if key != "article-body.html"}
    contexts = [item for item in inputs["media"] if item.role == "context"]
    assert bool(contexts) is not no_context
    for item in contexts:
        before = next(
            match for match in _IMAGE_SECTION.finditer(old_html) if match["path"] == item.path
        )
        assert before["caption"] in new_html
        assert item.credit and item.credit in unescape(new_html)
        assert item.source_page_url and item.context_only_not_evidence
    validate_strict_prepared_projection(new.manifest, new.files)


def test_pure_renderer_context_option_is_separate_from_body_caption_option(
    strict_projection: StrictPreparedProjection,  # noqa: F811
) -> None:
    inputs = _inputs(strict_projection)
    kwargs = {name: inputs[name] for name in ("article", "media")}
    default = render_editor_handoff_v2_body(**kwargs)
    explicit_default = render_editor_handoff_v2_body(**kwargs, hide_context_rights_notice=False)
    hidden = render_editor_handoff_v2_body(**kwargs, hide_context_rights_notice=True)
    assert default == explicit_default
    assert hidden.body_html == _without_context_notices(default.body_html)
    assert (
        sum(
            match["path"].startswith("assets/body-")
            for match in _IMAGE_SECTION.finditer(hidden.body_html)
        )
        == 5
    )
    assert hidden.recipe == default.recipe and hidden.placements == default.placements
    assert hidden.emphasis == default.emphasis


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rights_status", "permission_assumed"),
        ("context_only_not_evidence", False),
        ("source_page_url", "https://example.org/changed-source"),
        ("credit", "Changed credit"),
    ],
)
def test_v5_notice_suppression_does_not_bypass_news_provenance_guard(
    strict_projection: StrictPreparedProjection,  # noqa: F811
    field: str,
    value: object,
) -> None:
    inputs = _inputs(strict_projection)
    inputs["evidence"] = tuple(replace(item, prompt_version=V5) for item in inputs["evidence"])
    _with_v5_footer(inputs)
    inputs["media"] = tuple(
        item.model_copy(update={field: value}) if item.role == "context" else item
        for item in inputs["media"]
    )
    with pytest.raises(ValueError, match="news provenance changed"):
        build_strict_prepared_projection(**inputs)
