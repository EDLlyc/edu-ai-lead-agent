"""Pure deterministic renderer and preflight for local WeChat editor handoff artifacts."""

# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional rendered copy.

from __future__ import annotations

import json
import re
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Final, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from app.domain.official_account_editor_handoff_theme import (
    XIAOSAI_GZH_THEME,
    XIAOSAI_GZH_THEME_CANONICAL_JSON,
    XIAOSAI_GZH_THEME_ID,
    XIAOSAI_GZH_THEME_SHA256,
)
from app.domain.official_account_local import (
    ArticleBulletListBlock,
    ArticleImageBlock,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleQuoteBlock,
)

EDITOR_HANDOFF_RENDERER_VERSION: Final[Literal["wechat-editor-handoff-renderer-v1-gzh-xiaosai"]] = (
    "wechat-editor-handoff-renderer-v1-gzh-xiaosai"
)
EDITOR_HANDOFF_STYLE_VERSION: Final[Literal["wechat-editor-handoff-style-v1-xiaosai-blue"]] = (
    "wechat-editor-handoff-style-v1-xiaosai-blue"
)
EDITOR_HANDOFF_TEMPLATE_VERSION: Final[Literal["wechat-editor-handoff-template-v1-moyu-layout"]] = (
    "wechat-editor-handoff-template-v1-moyu-layout"
)
EDITOR_HANDOFF_BUNDLE_VERSION: Final[Literal["official-account-editor-handoff-bundle-v1"]] = (
    "official-account-editor-handoff-bundle-v1"
)
EDITOR_HANDOFF_PREFLIGHT_VERSION: Final[Literal["wechat-editor-handoff-preflight-v1"]] = (
    "wechat-editor-handoff-preflight-v1"
)
EDITOR_HANDOFF_RIGHTS_POLICY_VERSION: Final[
    Literal["editor-handoff-context-rights-v1-direct-use-disclosed"]
] = "editor-handoff-context-rights-v1-direct-use-disclosed"

_ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_MEDIA_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_FORBIDDEN_MARKUP = re.compile(
    r"(?is)<\s*(?:html|head|body|style|script|button|div|iframe|form|object|embed|link|base)\b"
)
_PLACEHOLDER = re.compile(r"(?:__OFFICIAL_ACCOUNT_|\{\{|\}\}|【插入|TODO|TBD)", re.I)
_PRIVATE_REFERENCE = re.compile(
    r"(?i)(?:/root/|/home/|private/brand-materials|s3://|minio://|object[_ -]?key|/api/)"
)
_UNSAFE_STYLE = re.compile(
    r"(?i)(?:url\s*\(|@import|@media|@keyframes|javascript:|expression\s*\(|"
    r"behavior\s*:|-moz-binding|image-set\s*\(|var\s*\(|"
    r"position\s*:\s*(?:fixed|absolute|sticky)|display\s*:\s*grid|float\s*:)"
)
_CJK_HALF_PUNCT = re.compile(r"([\u3400-\u9fff])([,;!?])")

_ALLOWED_ATTRIBUTES: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "referrerpolicy", "rel", "style"}),
    "br": frozenset(),
    "img": frozenset({"alt", "src", "style"}),
    "p": frozenset({"style"}),
    "section": frozenset({"style"}),
    "span": frozenset({"leaf", "style"}),
}
_ALLOWED_STYLE_PROPERTIES = frozenset(
    {
        "-webkit-overflow-scrolling",
        "align-items",
        "background",
        "border",
        "border-bottom",
        "border-left",
        "border-radius",
        "border-top",
        "box-shadow",
        "color",
        "display",
        "flex",
        "flex-shrink",
        "font-family",
        "font-size",
        "font-weight",
        "gap",
        "height",
        "justify-content",
        "letter-spacing",
        "line-height",
        "margin",
        "margin-bottom",
        "margin-left",
        "margin-right",
        "margin-top",
        "max-width",
        "overflow",
        "overflow-x",
        "padding",
        "padding-bottom",
        "padding-left",
        "text-align",
        "text-decoration",
        "vertical-align",
        "white-space",
        "width",
    }
)
_VOID_TAGS = frozenset({"br", "img"})


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EditorHandoffIdentity(_FrozenModel):
    renderer_version: Literal["wechat-editor-handoff-renderer-v1-gzh-xiaosai"] = (
        EDITOR_HANDOFF_RENDERER_VERSION
    )
    style_version: Literal["wechat-editor-handoff-style-v1-xiaosai-blue"] = (
        EDITOR_HANDOFF_STYLE_VERSION
    )
    template_version: Literal["wechat-editor-handoff-template-v1-moyu-layout"] = (
        EDITOR_HANDOFF_TEMPLATE_VERSION
    )
    bundle_version: Literal["official-account-editor-handoff-bundle-v1"] = (
        EDITOR_HANDOFF_BUNDLE_VERSION
    )
    preflight_version: Literal["wechat-editor-handoff-preflight-v1"] = (
        EDITOR_HANDOFF_PREFLIGHT_VERSION
    )
    rights_policy_version: Literal["editor-handoff-context-rights-v1-direct-use-disclosed"] = (
        EDITOR_HANDOFF_RIGHTS_POLICY_VERSION
    )
    theme_id: Literal["xiaosai-moyu-layout-v1"] = XIAOSAI_GZH_THEME_ID
    theme_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", default=XIAOSAI_GZH_THEME_SHA256)


class EditorHandoffMediaAsset(_FrozenModel):
    path: str = Field(
        pattern=r"^assets/(?:body-0[0-4]|context-0[01]|cover-wide)\.(?:jpg|png|webp)$"
    )
    role: Literal["body", "context", "cover"]
    ordinal: int = Field(ge=0, le=49)
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    byte_size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    alt_text: str = Field(min_length=1, max_length=200)
    assigned_section_index: int | None = Field(default=None, ge=0, le=6)
    source_page_url: str | None = Field(default=None, max_length=2048)
    caption: str | None = Field(default=None, max_length=300)
    credit: str | None = Field(default=None, max_length=200)
    rights_status: Literal["publish_permission_unverified"] | None = None
    context_only_not_evidence: bool = False


class EditorHandoffCheck(_FrozenModel):
    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    severity: Literal["info", "warning", "error"]
    passed: bool
    field: str = Field(min_length=1, max_length=120)
    detail: str = Field(min_length=1, max_length=500)


class EditorHandoffPreflight(_FrozenModel):
    rule_version: Literal["wechat-editor-handoff-preflight-v1"] = EDITOR_HANDOFF_PREFLIGHT_VERSION
    passed: bool
    checks: tuple[EditorHandoffCheck, ...]
    blocking_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]


class RenderedEditorHandoff(_FrozenModel):
    body_html: str
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    theme_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def media_asset_path(
    role: Literal["body", "context", "cover"], ordinal: int, media_type: str
) -> str:
    try:
        extension = _MEDIA_EXTENSIONS[media_type]
    except KeyError as error:
        raise ValueError("editor handoff media type is unsupported") from error
    if role == "cover":
        if ordinal != 0:
            raise ValueError("editor handoff cover ordinal must be zero")
        return f"assets/cover-wide.{extension}"
    if role == "body" and 0 <= ordinal <= 4:
        return f"assets/body-{ordinal:02d}.{extension}"
    if role == "context" and 0 <= ordinal <= 1:
        return f"assets/context-{ordinal:02d}.{extension}"
    raise ValueError("editor handoff media role or ordinal is invalid")


def render_editor_handoff_body(
    *,
    article: ArticlePackage,
    media: tuple[EditorHandoffMediaAsset, ...],
) -> RenderedEditorHandoff:
    body_by_ordinal = {item.ordinal: item for item in media if item.role == "body"}
    context_by_section: dict[int, list[EditorHandoffMediaAsset]] = {}
    for item in media:
        if item.role == "context" and item.assigned_section_index is not None:
            context_by_section.setdefault(item.assigned_section_index, []).append(item)

    sections: list[str] = [_global_open(), _cover(article), _toc(article)]
    sections.append(_lead_card(article.lead))
    for section_index, section in enumerate(article.sections):
        sections.append(_chapter_heading(section_index, section.heading))
        for context in sorted(
            context_by_section.get(section_index, []), key=lambda item: item.ordinal
        ):
            sections.append(_image(context, disclose_rights=True))
        for block in section.blocks:
            if isinstance(block, ArticleParagraphBlock):
                sections.append(_paragraph(block.text))
            elif isinstance(block, ArticleBulletListBlock):
                sections.extend(_bullet(item) for item in block.items)
            elif isinstance(block, ArticleQuoteBlock):
                sections.append(_quote(block.text))
            elif isinstance(block, ArticleImageBlock):
                ordinal = int(block.slot_key.removeprefix("body-"))
                asset = body_by_ordinal.get(ordinal)
                if asset is None:
                    raise ValueError("article image block has no verified handoff asset")
                sections.append(_image(asset, disclose_rights=False))
            else:  # pragma: no cover - discriminated ArticleBlock is exhaustive
                raise TypeError("unsupported article block")
    sections.append(_conclusion(article.conclusion))
    sections.append(_sources(article))
    sections.append(_signature(article.author))
    sections.append("</section>")
    body_html = "".join(sections)
    return RenderedEditorHandoff(
        body_html=body_html,
        body_sha256=sha256(body_html.encode("utf-8")).hexdigest(),
        theme_sha256=XIAOSAI_GZH_THEME_SHA256,
    )


def run_editor_handoff_preflight(
    *,
    body_html: str,
    preview_html: str,
    media: tuple[EditorHandoffMediaAsset, ...],
    approved: bool,
    extra_checks: tuple[EditorHandoffCheck, ...] = (),
) -> EditorHandoffPreflight:
    checks = list(extra_checks)

    def add(code: str, passed: bool, field: str, detail: str, *, warning: bool = False) -> None:
        checks.append(
            EditorHandoffCheck(
                code=code,
                severity="info" if passed else ("warning" if warning else "error"),
                passed=passed,
                field=field,
                detail=detail,
            )
        )

    add("immutable_review_approved", approved, "manual_review", "不可变人工审稿已批准")
    inspector = _HandoffHtmlInspector()
    inspector.feed(body_html)
    inspector.close()
    root_shape = (
        body_html.startswith("<section ")
        and body_html.endswith("</section>")
        and inspector.root_count == 1
        and inspector.root_tag == "section"
        and not inspector.stack
        and not inspector.structure_errors
    )
    add("pure_section_fragment", root_shape, "article_body", "正文是单一 section 片段")
    add(
        "forbidden_markup_absent",
        _FORBIDDEN_MARKUP.search(body_html) is None,
        "article_body",
        "正文不包含文档外壳、脚本或交互标签",
    )
    add(
        "placeholder_absent",
        _PLACEHOLDER.search(body_html) is None,
        "article_body",
        "正文不包含未解析占位符",
    )
    add(
        "private_reference_absent",
        _PRIVATE_REFERENCE.search(body_html) is None,
        "article_body",
        "正文不包含私有路径或 API 图片地址",
    )

    add(
        "wechat_markup_allowlist",
        not inspector.errors,
        "article_body",
        "标签、属性、样式和链接均在固定白名单内",
    )
    add(
        "span_leaf_complete",
        inspector.unwrapped_text_count == 0 and inspector.leaf_count > 0,
        "article_body",
        "所有可见文字均由 span leaf 包裹",
    )
    declared_paths = {item.path for item in media if item.role != "cover"}
    add(
        "controlled_relative_images",
        set(inspector.image_sources) == declared_paths
        and len(inspector.image_sources) == len(declared_paths),
        "article_body.images",
        "正文图片只引用交接包内受控相对资源",
    )
    body_items = tuple(item for item in media if item.role == "body")
    cover_items = tuple(item for item in media if item.role == "cover")
    add(
        "body_image_count_valid",
        1 <= len(body_items) <= 5,
        "media.body",
        "正文包含一至五张图片",
    )
    add(
        "body_images_unique",
        len({item.sha256 for item in body_items}) == len(body_items),
        "media.body",
        "正文图片内容互异",
    )
    add(
        "media_images_unique",
        len({item.sha256 for item in media}) == len(media),
        "media",
        "正文图、新闻上下文图与封面内容互异",
    )
    cover_ok = (
        len(cover_items) == 1 and abs(cover_items[0].width / cover_items[0].height - 2.35) <= 0.08
    )
    add("cover_ratio_valid", cover_ok, "media.cover", "封面满足 2.35:1 比例")
    add(
        "asset_paths_unique",
        len({item.path for item in media}) == len(media),
        "media",
        "全部交接资源路径唯一",
    )
    preview_body = _extract_copy_root(preview_html)
    add(
        "preview_body_exact_match",
        preview_body == body_html,
        "preview",
        "预览复制节点与纯正文逐字节一致",
    )
    for item in media:
        if item.rights_status == "publish_permission_unverified":
            checks.append(
                EditorHandoffCheck(
                    code="context_image_rights_unverified_direct_use",
                    severity="warning",
                    passed=False,
                    field=item.path,
                    detail="按当前本地策略直接使用，发布权未验证",
                )
            )
    checks.append(
        EditorHandoffCheck(
            code="mobile_browser_validation_not_run",
            severity="warning",
            passed=False,
            field="mobile_validation",
            detail="当前运行时未伪造 320px/430px 浏览器验收结果",
        )
    )
    blocking = tuple(item.code for item in checks if item.severity == "error" and not item.passed)
    warnings = tuple(item.code for item in checks if item.severity == "warning" and not item.passed)
    return EditorHandoffPreflight(
        passed=not blocking,
        checks=tuple(checks),
        blocking_codes=blocking,
        warning_codes=warnings,
    )


def handoff_fingerprint(*parts: object) -> str:
    payload = json.dumps(
        parts,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def canonical_theme_projection() -> dict[str, object]:
    return json.loads(XIAOSAI_GZH_THEME_CANONICAL_JSON)


def _global_open() -> str:
    font = XIAOSAI_GZH_THEME["typography"]
    assert isinstance(font, dict)
    return (
        '<section style="max-width:677px;margin:0 auto;background:#FFFFFF;'
        f"font-family:{font['font_stack']};color:#26364A;line-height:1.75;"
        'letter-spacing:0.5px;overflow-x:hidden;">'
    )


def _cover(article: ArticlePackage) -> str:
    return (
        '<section style="margin:0 0 32px;background:#FFFFFF;border:1.5px solid '
        "rgba(13,87,200,0.15);border-radius:20px;overflow:hidden;box-shadow:0 4px 20px "
        'rgba(0,0,0,0.06);width:100%;">'
        '<section style="padding:32px 28px 28px;">'
        '<p style="font-size:11px;font-weight:700;letter-spacing:3px;color:#0D57C8;'
        f'margin:0 0 20px;"><span leaf="">XIAOSAI AI · FIELD NOTES</span></p>'
        '<p style="font-size:26px;font-weight:900;color:#0D57C8;margin:0 0 16px;'
        f'line-height:1.25;letter-spacing:-1px;">{_leaf(article.title)}</p>'
        '<section style="width:48px;height:3px;background:linear-gradient(to right,#0D57C8,'
        '#22D7D6);border-radius:2px;margin-bottom:12px;"><span leaf=""><br></span></section>'
        f'<p style="font-size:13px;color:#607086;margin:0;line-height:1.7;">'
        f"{_leaf(article.digest)}</p>"
        '</section><section style="background:linear-gradient(135deg,#0D57C8,#285ACE);'
        'padding:12px 28px;display:flex;align-items:center;justify-content:space-between;">'
        '<p style="font-size:12px;color:#FFFFFF;margin:0;font-weight:600;">'
        '<span leaf="">小赛 AI · 科创教育观察</span></p>'
        '<p style="font-size:10px;color:#FFFFFF;margin:0;">'
        '<span leaf="">深度 · 方法 · 实践</span></p>'
        "</section></section>"
    )


def _toc(article: ArticlePackage) -> str:
    cards: list[str] = []
    for index, section in enumerate(article.sections[:3]):
        active = index == 0
        background = "linear-gradient(135deg,#0D57C8,#285ACE)" if active else "#FFFFFF"
        color = "#FFFFFF" if active else "#0D57C8"
        border = "0" if active else "1px solid #DCEAF5"
        cards.append(
            '<section style="display:inline-block;white-space:normal;vertical-align:top;'
            f"width:110px;background:{background};border:{border};border-radius:12px;"
            'padding:12px;margin-right:8px;">'
            f'<p style="font-size:9px;font-weight:700;color:{color};letter-spacing:1px;'
            'margin:0 0 5px;">'
            f"{_leaf(f'PART {index + 1:02d}')}</p>"
            f'<p style="font-size:13px;font-weight:800;color:{color};margin:0;">'
            f"{_leaf(section.heading)}</p></section>"
        )
    return (
        '<section style="margin:0 20px 32px;">'
        '<section style="display:flex;align-items:center;justify-content:space-between;'
        'margin-bottom:10px;">'
        f'<p style="font-size:10px;color:#607086;margin:0;letter-spacing:2px;font-weight:600;">'
        f"{_leaf(f'精选 {len(cards)} 个核心章节')}</p>"
        f'<p style="font-size:10px;color:#607086;margin:0;">{_leaf("👉 滑动")}</p></section>'
        '<section style="overflow-x:scroll;-webkit-overflow-scrolling:touch;white-space:nowrap;'
        f'padding-bottom:8px;">{"".join(cards)}</section></section>'
    )


def _lead_card(text: str) -> str:
    return (
        '<section style="margin:0 20px 36px;padding:20px 22px;background:#EAF7FF;'
        'border-left:4px solid #0D57C8;border-radius:0 14px 14px 0;">'
        f'<p style="font-size:16px;color:#0D57C8;font-weight:700;line-height:1.8;margin:0;">'
        f"{_emphasized(text)}</p></section>"
    )


def _chapter_heading(index: int, heading: str) -> str:
    return (
        '<section style="margin-top:48px;margin-bottom:24px;padding:0 20px;">'
        '<section style="display:flex;align-items:center;gap:16px;">'
        '<section style="text-align:center;flex-shrink:0;">'
        '<p style="margin:0;font-size:28px;font-weight:900;color:#0D57C8;line-height:1;">'
        f"{_leaf(f'{index + 1:02d}')}</p>"
        f'<p style="margin:4px 0 0;font-size:9px;color:#607086;letter-spacing:1px;">'
        f"{_leaf('PART')}</p></section>"
        '<section style="flex:1;border-left:1px solid #C7DDEF;padding-left:16px;">'
        f'<p style="font-size:19px;font-weight:800;color:#0D57C8;margin:0;line-height:1.4;">'
        f"{_leaf(heading)}</p></section></section></section>"
    )


def _paragraph(text: str) -> str:
    return (
        '<p style="font-size:14px;color:#26364A;line-height:1.9;margin:0 20px 18px;'
        f'text-align:justify;">{_emphasized(text)}</p>'
    )


def _bullet(text: str) -> str:
    return (
        '<section style="margin:0 20px 12px;padding:13px 16px;background:#F3FBFF;'
        'border-radius:10px;display:flex;gap:10px;align-items:flex-start;">'
        '<span style="color:#FC9103;font-weight:900;"><span leaf="">●</span></span>'
        f'<p style="font-size:14px;color:#26364A;line-height:1.8;margin:0;flex:1;">'
        f"{_emphasized(text)}</p></section>"
    )


def _quote(text: str) -> str:
    return (
        '<section style="margin:22px 20px;padding:18px 20px;background:#0D57C8;'
        'border-radius:14px;">'
        f'<p style="font-size:15px;color:#FFFFFF;line-height:1.8;margin:0;font-weight:700;">'
        f"{_leaf(text)}</p></section>"
    )


def _image(asset: EditorHandoffMediaAsset, *, disclose_rights: bool) -> str:
    caption = asset.caption or asset.alt_text
    credit = f" · {asset.credit}" if asset.credit else ""
    warning = (
        '<p style="font-size:11px;color:#B85A00;line-height:1.7;margin:6px 0 0;">'
        f"{_leaf('按当前本地策略直接使用，发布权未验证；仅作上下文参考，不是事实证据。')}</p>"
        if disclose_rights
        else ""
    )
    return (
        '<section style="margin:24px 20px 30px;">'
        f'<img src="{escape(asset.path, quote=True)}" '
        f'alt="{escape(_typography(asset.alt_text), quote=True)}" '
        'style="max-width:100%;height:auto;display:block;margin:0 auto;border-radius:14px;">'
        '<p style="font-size:11px;color:#607086;text-align:center;line-height:1.7;'
        'margin:8px 0 0;">'
        f"{_leaf(caption + credit)}</p>{warning}</section>"
    )


def _conclusion(text: str) -> str:
    return (
        '<section style="margin:44px 20px 24px;padding:24px;background:linear-gradient(135deg,'
        '#EAF7FF,#F3FBFF);border-radius:16px;border:1px solid #C7DDEF;">'
        '<p style="font-size:10px;color:#0D57C8;font-weight:800;letter-spacing:2px;'
        'margin:0 0 10px;">'
        f"{_leaf('LAST · 写在最后')}</p>"
        f'<p style="font-size:15px;color:#26364A;line-height:1.9;margin:0;">{_emphasized(text)}</p>'
        "</section>"
    )


def _sources(article: ArticlePackage) -> str:
    rows = []
    for index, source in enumerate(article.sources):
        rows.append(
            '<p style="font-size:11px;color:#607086;line-height:1.7;margin:0 0 8px;">'
            f"{_leaf(f'{index + 1:02d} · {source.source_name} · ')}"
            f'<a href="{escape(source.source_url, quote=True)}" rel="noopener noreferrer" '
            'referrerpolicy="no-referrer" style="color:#0D57C8;text-decoration:underline;">'
            f"{_leaf('查看权威原文')}</a></p>"
        )
    return (
        '<section style="margin:28px 20px;padding:18px 20px;background:#F7FBFE;'
        'border-radius:12px;border:1px solid #DCEAF5;">'
        f'<p style="font-size:12px;color:#0D57C8;font-weight:800;margin:0 0 12px;">'
        f"{_leaf('来源与事实边界')}</p>{''.join(rows)}</section>"
    )


def _signature(author: str) -> str:
    return (
        '<section style="margin:36px 20px 0;padding:24px 20px;text-align:center;'
        'border-top:1px solid #C7DDEF;">'
        f'<p style="font-size:13px;color:#26364A;line-height:1.8;margin:0 0 8px;">'
        f"{_leaf(f'我是{author}，持续分享 AI 与科创教育的观察和实践。')}</p>"
        f'<p style="font-size:13px;color:#0D57C8;font-weight:700;line-height:1.8;margin:0;">'
        f"{_leaf('如果你觉得今天这篇有收获，欢迎点赞、在看、转发，我们下篇见。')}</p>"
        "</section>"
    )


def _leaf(text: str) -> str:
    return f'<span leaf="">{escape(_typography(text), quote=False)}</span>'


def _emphasized(text: str) -> str:
    normalized = _typography(text)
    match = re.search(r"[\u3400-\u9fffA-Za-z0-9][^，。！？；：]{3,13}", normalized)
    if match is None:
        return _leaf(normalized)
    start, end = match.span()
    pieces = []
    if start:
        pieces.append(_leaf(normalized[:start]))
    pieces.append(
        '<span style="border-bottom:2px solid #29B6EE;padding-bottom:1px;">'
        f"{_leaf(normalized[start:end])}</span>"
    )
    if end < len(normalized):
        pieces.append(_leaf(normalized[end:]))
    return "".join(pieces)


def _typography(text: str) -> str:
    normalized = text.replace('"', "“").replace("'", "’")
    return _CJK_HALF_PUNCT.sub(
        lambda item: item.group(1) + {",": "，", ";": "；", "!": "！", "?": "？"}[item.group(2)],
        normalized,
    )


def _extract_copy_root(preview_html: str) -> str | None:
    start_marker = '<main id="copy-root">'
    end_marker = "</main>"
    start = preview_html.find(start_marker)
    end = preview_html.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        return None
    return preview_html[start + len(start_marker) : end]


class _HandoffHtmlInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.errors: list[str] = []
        self.structure_errors: list[str] = []
        self.image_sources: list[str] = []
        self.unwrapped_text_count = 0
        self.leaf_count = 0
        self.root_count = 0
        self.root_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.stack:
            self.root_count += 1
            if self.root_tag is None:
                self.root_tag = tag
        allowed = _ALLOWED_ATTRIBUTES.get(tag)
        attributes = dict(attrs)
        if allowed is None:
            self.errors.append(f"tag:{tag}")
        elif len(attributes) != len(attrs):
            self.errors.append(f"duplicate-attrs:{tag}")
        elif set(attributes) - allowed:
            self.errors.append(f"attrs:{tag}")
        style = attributes.get("style") or ""
        if _UNSAFE_STYLE.search(style):
            self.errors.append(f"style:{tag}")
        if style and not _style_is_allowlisted(style):
            self.errors.append(f"style-allowlist:{tag}")
        if tag == "span" and attributes.get("leaf") == "":
            self.leaf_count += 1
        elif tag == "span" and "leaf" in attributes:
            self.errors.append("leaf:span")
        if tag == "a":
            href = attributes.get("href") or ""
            parsed = urlsplit(href)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
                or attributes.get("rel") != "noopener noreferrer"
                or attributes.get("referrerpolicy") != "no-referrer"
            ):
                self.errors.append("href:a")
        if tag == "img":
            source = attributes.get("src") or ""
            try:
                path = PurePosixPath(source)
                safe = (
                    not path.is_absolute()
                    and path.parts
                    and path.parts[0] == "assets"
                    and ".." not in path.parts
                    and "." not in path.parts
                )
            except ValueError:
                safe = False
            if not safe:
                self.errors.append("src:img")
            self.image_sources.append(source)
        if tag not in _VOID_TAGS:
            self.stack.append((tag, tag == "span" and attributes.get("leaf") == ""))

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1][0] != tag:
            self.structure_errors.append(f"end:{tag}")
            return
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        if data.strip() and not any(leaf for _tag, leaf in self.stack):
            self.unwrapped_text_count += 1


def _style_is_allowlisted(style: str) -> bool:
    declarations = tuple(part.strip() for part in style.split(";") if part.strip())
    if not declarations:
        return False
    for declaration in declarations:
        property_name, separator, value = declaration.partition(":")
        if (
            not separator
            or property_name.strip().lower() not in _ALLOWED_STYLE_PROPERTIES
            or not value.strip()
        ):
            return False
    return True
