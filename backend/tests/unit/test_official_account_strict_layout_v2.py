from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

import pytest
from app.application.services.wechat_official_account_draft import _DraftHtmlValidator
from app.domain.official_account_strict_layout import (
    STRICT_LAYOUT_PROJECTION_V2_VERSION,
    STRICT_LAYOUT_PROJECTION_VERSION,
    compact_strict_xiaosai_html,
    strict_layout_projection_version,
    validate_strict_upload_html_headroom,
)


def _v2(body: str) -> str:
    return compact_strict_xiaosai_html(body, version=STRICT_LAYOUT_PROJECTION_V2_VERSION)


class _TextStyles(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, str]] = []
        self.text: list[tuple[str, dict[str, str]]] = []
        self.tags: list[tuple[str, dict[str, str | None], dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        style = dict(self.stack[-1]) if self.stack else {}
        style.update(
            dict(item.split(":", 1) for item in (values.get("style") or "").split(";") if item)
        )
        self.tags.append((tag, values, dict(style)))
        if tag not in {"img", "br"}:
            self.stack.append(style)

    def handle_endtag(self, tag: str) -> None:
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.text.append((data, dict(self.stack[-1])))


def _parsed(body: str) -> _TextStyles:
    parser = _TextStyles()
    parser.feed(body)
    parser.close()
    return parser


def test_literal_compact_v1_serialization_is_unchanged() -> None:
    source = (
        "<section style=\"font-family:'PingFang SC';font-size:16px;color:#FFFFFF;"
        'line-height:1.75;letter-spacing:0.5px;">'
        '<p style="font-size:16px;color:#FFFFFF;line-height:1.75;">'
        '<span leaf="">原文&amp;&#x41;</span></p></section>'
    )
    expected = (
        '<section style="font-family:&#x27;PingFang SC&#x27;;font-size:16px;color:#FFF;'
        'line-height:1.75;letter-spacing:.5px">'
        '<p style=""><span leaf="">原文&amp;&#x41;</span></p></section>'
    )
    assert compact_strict_xiaosai_html(source) == expected
    assert compact_strict_xiaosai_html(source, version=STRICT_LAYOUT_PROJECTION_VERSION) == expected


@pytest.mark.parametrize("version", [None, "", "xiaosai-strict-inline-compact-v3", 2, True])
def test_unknown_or_missing_versions_never_select_a_default(version: Any) -> None:
    with pytest.raises(ValueError, match="version is unsupported"):
        strict_layout_projection_version(version)
    with pytest.raises(ValueError, match="version is unsupported"):
        compact_strict_xiaosai_html('<span leaf="">text</span>', version=version)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("font-size", "1.5em"),
        ("font-size", "120%"),
        ("line-height", "120%"),
        ("font-weight", "bolder"),
        ("letter-spacing", "normal"),
        ("padding", "2em"),
        ("color", "currentColor"),
        ("font-size", "calc(12px + 2px)"),
        ("font-size", "16px!important"),
    ],
)
def test_v2_does_not_factor_relative_or_unknown_css(name: str, value: str) -> None:
    color = ";color:#FFF" if name != "color" else ""
    source = (
        f'<section style="{name}:{value}{color}">'
        f'<p style="{name}:{value}{color}"><span leaf="">原文</span></p></section>'
    )
    assert _v2(source) == compact_strict_xiaosai_html(source)


def test_leading_decimal_absolute_spacing_does_not_disable_v2() -> None:
    source = (
        '<section style="letter-spacing:0.5px"><p style="letter-spacing:-0.5px;margin:0">'
        '<span style="border-bottom:2px solid #29B6EE;padding-bottom:1px">'
        '<span leaf="">保持强调</span></span></p></section>'
    )
    body = _v2(source)
    assert " leaf>" in body
    assert "letter-spacing:-.5px" in body
    assert "border-bottom:2px solid#29B6EE;padding:0 0 1px" in body
    assert [text for text, _ in _parsed(body).text] == ["保持强调"]


def test_factoring_retains_explicit_link_color_despite_matching_ancestor() -> None:
    source = (
        '<section style="color:#26364A"><p style="margin:0">'
        '<span style="color:#0D57C8"><span leaf="">来源:</span></span>'
        '<a href="https://example.com/source" style="color:#0D57C8;text-decoration:underline">'
        '<span leaf="">原始来源</span></a></p></section>'
    )
    result = _parsed(_v2(source))
    link = next(attrs for tag, attrs, _ in result.tags if tag == "a")
    assert "color:#0D57C8" in (link["style"] or "")
    assert "text-decoration:underline" in (link["style"] or "")


def test_v2_never_invents_unknown_ua_link_color() -> None:
    source = '<section><a href="https://example.com"><span leaf="">来源</span></a></section>'
    assert _v2(source) == compact_strict_xiaosai_html(source)


def test_factoring_preserves_block_strut_font_and_line_height() -> None:
    source = (
        '<section style="font-size:16px;line-height:1.75"><p style="font-size:30px;'
        'line-height:2;margin:0"><span style="font-size:10px;line-height:1">'
        '<span leaf="">Small text in tall line</span></span></p></section>'
    )
    before = _parsed(compact_strict_xiaosai_html(source))
    after = _parsed(_v2(source))
    for tag in ("p",):
        old_style = next(style for found, _, style in before.tags if found == tag)
        new_style = next(style for found, _, style in after.tags if found == tag)
        assert (new_style["font-size"], new_style["line-height"]) == (
            old_style["font-size"],
            old_style["line-height"],
        )
    assert after.text[0][1]["font-size"] == "10px"
    assert after.text[0][1]["line-height"] == "1"


def _body_groups() -> str:
    paragraph = (
        '<p style="font-size:14px;color:#26364A;line-height:1.9;margin:0 20px 18px;'
        'text-align:justify"><span leaf="">观察事实与原始新闻。</span>'
        '<span style="border-bottom:2px solid #29B6EE;padding-bottom:1px">'
        '<span leaf="">保留强调</span></span></p>'
    )
    return (
        '<section style="max-width:677px;margin:0 auto;color:#26364A;line-height:1.75;'
        'letter-spacing:0.5px">'
        + "".join(
            paragraph * 3 + f'<section><img src="assets/body-0{index}.jpg" alt="插画"></section>'
            for index in range(5)
        )
        + "</section>"
    )


def test_adjacent_body_groups_preserve_text_leaves_media_and_typography() -> None:
    original = compact_strict_xiaosai_html(_body_groups())
    result = _v2(_body_groups())
    before, after = _parsed(original), _parsed(result)
    assert len(result) < len(original) - 400
    assert [text for text, _ in before.text] == [text for text, _ in after.text]
    for (_, old), (_, new) in zip(before.text, after.text, strict=True):
        assert {
            key: old.get(key) for key in ("font-size", "line-height", "color", "text-align")
        } == {key: new.get(key) for key in ("font-size", "line-height", "color", "text-align")}
    assert sum("leaf" in attrs for _, attrs, _ in before.tags) == sum(
        "leaf" in attrs for _, attrs, _ in after.tags
    )
    assert [attrs for tag, attrs, _ in before.tags if tag == "img"] == [
        attrs for tag, attrs, _ in after.tags if tag == "img"
    ]


def test_compaction_recovers_dense_html_without_changing_final_reserve() -> None:
    source = _body_groups()
    v1 = compact_strict_xiaosai_html(source)
    image_paths = tuple(f"assets/body-0{index}.jpg" for index in range(5))
    # Add only synthetic visible text, to exercise a formerly failing full envelope.
    reserved_v1 = len(v1) + sum(256 - len(path) for path in image_paths)
    filler = "x" * (20_100 - reserved_v1)
    source = source.replace("观察事实与原始新闻。", "观察事实与原始新闻。" + filler, 1)
    with pytest.raises(ValueError, match="headroom"):
        validate_strict_upload_html_headroom(compact_strict_xiaosai_html(source), image_paths)
    validate_strict_upload_html_headroom(_v2(source), image_paths)


@pytest.mark.parametrize("allow_bare", [False, True])
@pytest.mark.parametrize("attribute", ['leaf=""', "leaf", 'leaf="invalid"'])
def test_bare_leaf_support_is_explicit_and_does_not_relax_other_values(
    allow_bare: bool, attribute: str
) -> None:
    parser = _DraftHtmlValidator(allow_bare_leaf=allow_bare)
    parser.feed(f'<p><span {attribute}>原文</span></p><img src="assets/a.jpg" alt="插画">')
    if attribute == 'leaf=""' or (allow_bare and attribute == "leaf"):
        assert parser.finish() == ("assets/a.jpg",)
    else:
        with pytest.raises(ValueError):
            parser.finish()


def test_bare_non_leaf_attribute_remains_invalid() -> None:
    parser = _DraftHtmlValidator(allow_bare_leaf=True)
    parser.feed('<span style leaf>原文</span><img src="assets/a.jpg" alt="插画">')
    with pytest.raises(ValueError):
        parser.finish()


def test_v2_tree_is_bounded_and_rejects_unsupported_elements() -> None:
    for body in ("<section>" * 34 + "</section>" * 34, "<table></table>"):
        with pytest.raises(ValueError, match="shape is unsupported"):
            _v2(body)
