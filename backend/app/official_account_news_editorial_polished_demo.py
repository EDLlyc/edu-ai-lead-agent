# ruff: noqa: RUF001 -- Chinese editorial copy is intentional.
"""Provider-free high-rhythm editorial repackage for the inspected news/IP bundle.

The command validates the frozen v1 source through the v2 loader, builds a distinct v3
Article Package, and exports a local-only science-magazine preview. It never constructs
provider clients, fetches sources, or calls social distribution paths.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from app import official_account_news_editorial_demo as editorial_v2
from app.domain.official_account_local import (
    ArticleBulletListBlock,
    ArticleImageBlock,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleQuoteBlock,
    ArticleVersionBundle,
    article_body_character_count,
    article_package_fingerprint,
    body_media_placeholder,
    fingerprint,
)
from app.official_account_news_editorial_demo import (
    EditorialSourceBundle,
    load_source_bundle,
)

NEWS_URL = editorial_v2.NEWS_URL
PLAN_URL = editorial_v2.PLAN_URL
REFERENCE_URL = editorial_v2.REFERENCE_URL
SOURCE_REPORT_VERSION = editorial_v2.SOURCE_REPORT_VERSION
SOURCE_EVIDENCE_VERSION = editorial_v2.SOURCE_EVIDENCE_VERSION
BODY_IMAGE_NAMES = editorial_v2.BODY_IMAGE_NAMES
BODY_TARGET_MIN = 1_800
BODY_TARGET_MAX = 2_600

REPORT_VERSION = "official-account-news-editorial-polished-demo-v3"
ARTICLE_SCHEMA_VERSION = "official-account-news-editorial-schema-v3-science-magazine"
RENDERER_VERSION = "wechat-news-editorial-renderer-v3-science-magazine"
STYLE_VERSION = "wechat-news-editorial-style-v3-navy-cobalt-orange"
TEMPLATE_VERSION = "wechat-news-editorial-template-v3-high-rhythm-mobile"
REFERENCE_STUDY_VERSION = "wechat-public-reference-patterns-v2-form-rhythm"
DEFAULT_SOURCE_DIR = Path("output/official-account-news-ip-20260824-v1")
DEFAULT_OUTPUT_DIR = Path("output/official-account-news-ip-editorial-20260824-v3")

_EXPECTED_EVIDENCE_IDS = frozenset(UUID(value) for value in editorial_v2._EXPECTED_EVIDENCE_IDS)
_MODULE_MARKERS = (
    "hero",
    "opening-visual",
    "policy-tiles",
    "parent-question-cards",
    "learning-loop-rail",
    "ai-child-boundary",
    "action-timeline",
    "closing-takeaway",
)
_ALLOWED_EMPHASIS = (
    "创新能力和综合素养",
    "学科融合与实践导向",
    "问题、假设、行动、证据和复盘",
    "观察、判断和表达",
    "育人为本、素养为先、应用导向、智能向善",
)
_AI_ASSIST_ITEMS = (
    "整理孩子已经留下的观察记录，比较差异，并提示可能遗漏的观察角度。",
    "把孩子已经提出的问题分类，生成几个用于核对而非直接作答的新追问。",
)
_CHILD_OWNS_ITEMS = (
    "回到现场观察和测量，判断样本与变量是否足以支持自己的解释。",
    "用自己的语言说明证据、结论与局限，并决定下一次准备修改什么。",
)


def _versions() -> ArticleVersionBundle:
    return ArticleVersionBundle(
        generator_prompt_version="official-account-news-editorial-assembler-v3",
        article_schema_version=ARTICLE_SCHEMA_VERSION,
        auditor_prompt_version="official-account-news-editorial-audit-v3",
        audit_schema_version="official-account-news-editorial-audit-schema-v3",
        rule_version="official-account-news-editorial-rules-v3-evidence-bound-science-magazine",
        renderer_version=RENDERER_VERSION,
        style_version=STYLE_VERSION,
        template_version=TEMPLATE_VERSION,
        local_adapter_version="official-account-news-editorial-local-adapter-v3",
    )


def _module_shapes(article: ArticlePackage) -> tuple[tuple[type[object], ...], ...]:
    return tuple(tuple(type(block) for block in section.blocks) for section in article.sections)


def _validate_polished_article(article: ArticlePackage) -> None:
    if article.versions != _versions():
        raise ValueError("polished editorial Article Package version changed")
    if len(article.sections) != 6:
        raise ValueError("polished editorial Article Package must contain exactly six units")
    character_count = article_body_character_count(article)
    if not BODY_TARGET_MIN <= character_count <= BODY_TARGET_MAX:
        raise ValueError("polished editorial article is outside the approved target length")
    if article.content_fingerprint != article_package_fingerprint(article):
        raise ValueError("polished editorial Article Package fingerprint changed")

    expected_shapes = (
        (
            ArticleParagraphBlock,
            ArticleBulletListBlock,
            ArticleQuoteBlock,
            ArticleImageBlock,
        ),
        (
            ArticleParagraphBlock,
            ArticleParagraphBlock,
            ArticleParagraphBlock,
            ArticleQuoteBlock,
        ),
        (
            ArticleParagraphBlock,
            ArticleParagraphBlock,
            ArticleBulletListBlock,
            ArticleImageBlock,
        ),
        (ArticleParagraphBlock, ArticleBulletListBlock, ArticleQuoteBlock),
        (
            ArticleParagraphBlock,
            ArticleBulletListBlock,
            ArticleParagraphBlock,
            ArticleImageBlock,
        ),
        (ArticleParagraphBlock, ArticleParagraphBlock, ArticleQuoteBlock),
    )
    if _module_shapes(article) != expected_shapes:
        raise ValueError("polished editorial module shape changed")
    bullet_counts = tuple(
        len(block.items)
        for section in article.sections
        for block in section.blocks
        if isinstance(block, ArticleBulletListBlock)
    )
    if bullet_counts != (3, 4, 4, 5):
        raise ValueError("polished editorial structured module items changed")

    claim_ids = tuple(claim.id for claim in article.claims)
    known_claim_ids = set(claim_ids)
    referenced_claim_ids = {
        claim_ref
        for section in article.sections
        for block in section.blocks
        for claim_ref in block.claim_refs
    }
    if len(known_claim_ids) != len(claim_ids) or referenced_claim_ids != known_claim_ids:
        raise ValueError("polished editorial claim references must be unique and complete")
    source_evidence_ids = {source.evidence_id for source in article.sources}
    if source_evidence_ids != _EXPECTED_EVIDENCE_IDS:
        raise ValueError("polished editorial evidence identity set changed")
    news_evidence_id = article.sources[0].evidence_id
    plan_evidence_id = article.sources[1].evidence_id
    expected_claim_bindings = (
        ("news-direction", "external_fact", (news_evidence_id,), ()),
        ("plan-principle", "external_fact", (plan_evidence_id,), ()),
        ("plan-cross-disciplinary", "external_fact", (plan_evidence_id,), ()),
        ("parent-questions", "opinion", (), ()),
        ("learning-loop", "opinion", (), ()),
        ("ai-boundary", "opinion", (), ()),
        ("parent-role", "opinion", (), ()),
    )
    actual_claim_bindings = tuple(
        (claim.id, claim.kind, claim.evidence_ids, claim.brand_chunk_ids)
        for claim in article.claims
    )
    if actual_claim_bindings != expected_claim_bindings:
        raise ValueError("polished editorial fact and interpretation bindings changed")
    used_evidence_ids = {
        evidence_id
        for claim in article.claims
        if claim.kind == "external_fact"
        for evidence_id in claim.evidence_ids
    }
    if used_evidence_ids != source_evidence_ids:
        raise ValueError("polished editorial factual claims must use the exact source set")
    if tuple(source.source_url for source in article.sources) != (NEWS_URL, PLAN_URL):
        raise ValueError("polished editorial source set changed")

    image_placements = tuple(
        (section_index, block.slot_key)
        for section_index, section in enumerate(article.sections)
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    )
    if image_placements != ((0, "body-0"), (2, "body-1"), (4, "body-2")):
        raise ValueError("polished editorial image placements changed")
    actual_slots = tuple((slot.slot_key, slot.role, slot.ordinal) for slot in article.media_slots)
    if actual_slots != (
        ("body-0", "body", 0),
        ("body-1", "body", 1),
        ("body-2", "body", 2),
        ("cover-0", "cover", 0),
    ):
        raise ValueError("polished editorial media slots changed")


def build_polished_article(bundle: EditorialSourceBundle) -> ArticlePackage:
    """Assemble an original v3 identity from the already validated v2 editorial source."""

    baseline = editorial_v2.build_editorial_article(bundle)
    headings = (
        "新闻信号｜教育的评价尺，正在悄悄移动",
        "家长三问｜真正该抢跑的，是工具熟练度吗？",
        "学习闭环｜从听懂一个答案，到生成自己的理解",
        "AI与孩子｜谁来整理信息，谁来作出判断？",
        "今晚20分钟｜把一次好奇，变成一场小探究",
        "家长的位置｜少讲一个答案，多追问一条证据",
    )
    sections = tuple(
        section.model_copy(update={"heading": heading})
        for section, heading in zip(baseline.sections, headings, strict=True)
    )
    boundary = sections[3]
    boundary_items = ArticleBulletListBlock(
        kind="bullet_list",
        items=(*_AI_ASSIST_ITEMS, *_CHILD_OWNS_ITEMS),
        claim_refs=("ai-boundary", "learning-loop"),
    )
    sections = (
        *sections[:3],
        boundary.model_copy(
            update={"blocks": (boundary.blocks[0], boundary_items, boundary.blocks[2])}
        ),
        *sections[4:],
    )
    provisional = baseline.model_copy(
        update={
            "title": "别急着让孩子“学会AI”：教育正在重写真正的竞争力",
            "digest": "当知识进入真实问题，AI回到助手位置，孩子才真正站到学习中央。",
            "lead": (
                "当AI进入课堂，家长最容易先问工具：要不要学？从几岁开始？会不会落后？"
                "但两份教育部公开材料给出的线索，指向了一个更根本的问题——孩子能否把知识"
                "用于真实任务，能否提出问题、寻找证据并修正自己的解释。真正需要提前准备的，"
                "不是一张更长的软件清单，而是一套不轻易把思考外包的学习方式。"
            ),
            "topic_title": "AI教育行动与孩子的真实问题解决力",
            "sections": sections,
            "conclusion": (
                "新工具会不断出现，真正耐用的能力却始终落在孩子自己身上：看见现象，提出问题，"
                "用行动寻找证据，再用自己的语言解释结果。AI可以整理、比较和追问，小赛与赛先生"
                "也可以陪伴过程；但观察、判断和表达，不能被任何工具代劳。今晚不用完成一个完美"
                "项目，只需要让答案晚一点出现，让孩子的第一个问题真正开始生长。"
            ),
            "versions": _versions(),
            "content_fingerprint": "0" * 64,
        }
    )
    article = provisional.model_copy(
        update={"content_fingerprint": article_package_fingerprint(provisional)}
    )
    _validate_polished_article(article)
    return article


_STYLE = {
    "root": (
        "margin:0;padding:0 0 44px;background:#f7f2e7;color:#12233b;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
        "'Hiragino Sans GB','Microsoft YaHei',sans-serif;letter-spacing:.18px;overflow:hidden;"
    ),
    "hero": "padding:22px 19px 28px;background:#071b33;color:#fff;position:relative;",
    "hero_rule": "margin:0 0 21px;height:5px;background:#f2663a;line-height:0;",
    "eyebrow": (
        "margin:0 0 14px;color:#f5d34e;font-size:10px;line-height:1.5;font-weight:800;"
        "letter-spacing:2.4px;"
    ),
    "title": (
        "margin:0;color:#fffdf5;font-size:35px;line-height:1.2;font-weight:900;"
        "letter-spacing:-1.2px;"
    ),
    "deck": (
        "margin:19px 0 0;padding:15px 0 0;border-top:1px solid #ffffff38;color:#cad6e5;"
        "font-size:15px;line-height:1.85;font-weight:600;"
    ),
    "issue": ("margin:18px 0 0;color:#91a7c2;font-size:10px;line-height:1.5;letter-spacing:1.5px;"),
    "lead": "padding:25px 19px 19px;background:#fffdf7;",
    "lead_label": (
        "margin:0 0 12px;color:#1e5bff;font-size:11px;line-height:1.4;font-weight:900;"
        "letter-spacing:2px;"
    ),
    "lead_text": (
        "margin:0 0 10px;color:#253752;font-size:16px;line-height:1.95;text-align:justify;"
    ),
    "module": "margin:0;padding:35px 19px 0;",
    "module_alt": "margin:0;padding:35px 19px 0;background:#fffdf7;",
    "kicker": (
        "margin:0 0 8px;color:#f2663a;font-size:10px;line-height:1.4;font-weight:900;"
        "letter-spacing:2.1px;"
    ),
    "heading": (
        "margin:0 0 18px;color:#071b33;font-size:24px;line-height:1.35;font-weight:900;"
        "letter-spacing:-.35px;"
    ),
    "paragraph": (
        "margin:0 0 12px;color:#243750;font-size:16px;line-height:1.95;text-align:justify;"
    ),
    "emphasis": "color:#1e5bff;font-weight:800;",
    "full_bleed": "margin:0;background:#071b33;",
    "image": "display:block;width:100%;height:auto;border:0;aspect-ratio:3/2;object-fit:cover;",
    "caption_dark": (
        "margin:0;padding:10px 19px 12px;color:#aebdd0;font-size:10px;line-height:1.6;"
        "letter-spacing:.45px;"
    ),
    "policy_grid": "margin:21px 0 0;border-top:5px solid #1e5bff;",
    "policy_tile": (
        "margin:0;padding:17px 15px 17px 50px;border-bottom:1px solid #d9d1c4;background:#fffdf7;"
        "color:#1f334d;font-size:14px;line-height:1.75;"
    ),
    "policy_number": (
        "display:inline-block;width:35px;margin-left:-39px;color:#1e5bff;font-size:22px;"
        "line-height:1;font-weight:900;vertical-align:top;"
    ),
    "quote_band": (
        "margin:20px 0 0;padding:18px 17px;background:#f2663a;color:#fffaf1;"
        "box-shadow:7px 7px 0 #f5d34e;"
    ),
    "quote_text": "margin:0;font-size:17px;line-height:1.8;font-weight:800;",
    "question_card": (
        "margin:0 0 13px;padding:18px 16px 18px 54px;background:#fffdf7;"
        "border:1px solid #d8d1c6;box-shadow:4px 4px 0 #dce6ff;"
    ),
    "question_number": (
        "display:inline-block;width:39px;margin-left:-43px;color:#f2663a;font-size:25px;"
        "line-height:1;font-weight:900;vertical-align:top;"
    ),
    "question_text": "margin:0;color:#233650;font-size:15px;line-height:1.9;text-align:justify;",
    "boundary_note": (
        "margin:21px 0 0;padding:15px 16px;border-left:5px solid #f5d34e;background:#071b33;"
        "color:#dce6f2;font-size:13px;line-height:1.85;"
    ),
    "rail": "margin:21px 0 23px;padding:7px 0 0 25px;border-left:3px solid #1e5bff;",
    "rail_item": (
        "margin:0 0 14px;padding:0 0 14px 17px;border-bottom:1px solid #d6cec2;color:#203550;"
        "font-size:14px;line-height:1.75;"
    ),
    "rail_dot": (
        "display:inline-block;width:25px;height:25px;margin-left:-32px;margin-right:8px;"
        "border-radius:50%;background:#1e5bff;color:#fff;text-align:center;font-size:10px;"
        "line-height:25px;font-weight:900;vertical-align:top;"
    ),
    "framed_image": (
        "margin:25px -5px 0;padding:6px;background:#fff;border:1px solid #d5cbbd;"
        "box-shadow:7px 7px 0 #071b33;"
    ),
    "caption": "margin:9px 6px 3px;color:#667589;font-size:10px;line-height:1.6;",
    "boundary_panel": "margin:21px 0 0;border:1px solid #071b33;",
    "boundary_top": "padding:18px 16px;background:#071b33;color:#f8f5ed;",
    "boundary_bottom": "padding:18px 16px;background:#fffdf7;color:#233650;",
    "boundary_list": "margin:0;padding:0;list-style:none;",
    "boundary_item_dark": (
        "margin:0;padding:8px 0 8px 18px;border-top:1px solid #ffffff24;color:#e7edf5;"
        "font-size:14px;line-height:1.8;"
    ),
    "boundary_item_light": (
        "margin:0;padding:8px 0 8px 18px;border-top:1px solid #d8d1c6;color:#233650;"
        "font-size:14px;line-height:1.8;"
    ),
    "boundary_rule": (
        "margin:0;padding:14px 16px;background:#f5d34e;color:#071b33;font-size:15px;"
        "line-height:1.75;font-weight:800;"
    ),
    "timeline": "margin:21px 0 23px;",
    "timeline_item": (
        "margin:0;padding:0 0 17px 62px;color:#223650;font-size:14px;line-height:1.75;"
        "border-left:1px solid #c9c0b5;"
    ),
    "timeline_time": (
        "display:inline-block;width:49px;margin-left:-62px;margin-right:12px;padding:4px 5px;"
        "background:#f2663a;color:#fff;text-align:center;font-size:9px;line-height:1.35;"
        "font-weight:900;letter-spacing:.5px;vertical-align:top;"
    ),
    "closing_copy": (
        "margin:0 0 12px;color:#243750;font-size:16px;line-height:1.95;text-align:justify;"
    ),
    "closing_quote": (
        "margin:21px 0 0;padding:20px 17px;background:#1e5bff;color:#fff;font-size:17px;"
        "line-height:1.8;font-weight:800;"
    ),
    "takeaway": "margin:36px 0 0;padding:25px 19px 27px;background:#071b33;color:#fff;",
    "takeaway_label": (
        "margin:0 0 12px;color:#f5d34e;font-size:10px;line-height:1.4;font-weight:900;"
        "letter-spacing:2.2px;"
    ),
    "takeaway_text": "margin:0 0 11px;color:#f6f2e9;font-size:16px;line-height:1.95;",
    "sources": "margin:0;padding:28px 19px 0;color:#637086;font-size:11px;line-height:1.8;",
    "sources_heading": (
        "margin:0 0 10px;color:#071b33;font-size:12px;line-height:1.5;font-weight:900;"
        "letter-spacing:1.5px;"
    ),
    "source_item": "margin:0 0 8px;padding-left:2px;",
    "source_link": "color:#1e5bff;text-decoration:underline;word-break:break-all;",
    "footer_boundary": "margin:15px 0 0;color:#857567;font-size:10px;line-height:1.7;",
}


def _mobile_paragraphs(text: str, *, max_characters: int = 68) -> tuple[str, ...]:
    if len(text) <= max_characters:
        return (text,)
    punctuation = frozenset("。！？；")
    sentences: list[str] = []
    start = 0
    for index, character in enumerate(text):
        if character in punctuation:
            sentences.append(text[start : index + 1])
            start = index + 1
    if start < len(text):
        sentences.append(text[start:])
    if not sentences:
        return (text,)
    paragraphs: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_characters:
            paragraphs.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        paragraphs.append(current)
    return tuple(paragraphs)


def _emphasized_html(text: str) -> str:
    safe = escape(text)
    for phrase in sorted(_ALLOWED_EMPHASIS, key=len, reverse=True):
        safe_phrase = escape(phrase)
        safe = safe.replace(
            safe_phrase,
            f'<strong style="{_STYLE["emphasis"]}">{safe_phrase}</strong>',
        )
    return safe


def _paragraph_html(text: str, style: str) -> list[str]:
    return [f'<p style="{style}">{_emphasized_html(part)}</p>' for part in _mobile_paragraphs(text)]


def _safe_source_url(value: str) -> str:
    parsed = urlsplit(value)
    if value not in {NEWS_URL, PLAN_URL} or parsed.scheme != "https" or parsed.username:
        raise ValueError("polished editorial source URL is outside the pinned allowlist")
    return value


def _paragraph(block: object) -> ArticleParagraphBlock:
    if not isinstance(block, ArticleParagraphBlock):
        raise ValueError("polished editorial paragraph module changed")
    return block


def _bullet_list(block: object) -> ArticleBulletListBlock:
    if not isinstance(block, ArticleBulletListBlock):
        raise ValueError("polished editorial list module changed")
    return block


def _quote(block: object) -> ArticleQuoteBlock:
    if not isinstance(block, ArticleQuoteBlock):
        raise ValueError("polished editorial quote module changed")
    return block


def _image(block: object) -> ArticleImageBlock:
    if not isinstance(block, ArticleImageBlock):
        raise ValueError("polished editorial image module changed")
    return block


def _image_html(block: ArticleImageBlock, *, full_bleed: bool) -> str:
    ordinal = int(block.slot_key.removeprefix("body-"))
    alt = escape(block.alt_text, quote=True)
    if full_bleed:
        return (
            f'<section data-module="opening-visual" style="{_STYLE["full_bleed"]}">'
            f'<img src="{body_media_placeholder(ordinal)}" alt="{alt}" '
            f'style="{_STYLE["image"]}">'
            f'<p style="{_STYLE["caption_dark"]}">场景图 · {escape(block.alt_text)}</p>'
            "</section>"
        )
    return (
        f'<section style="{_STYLE["framed_image"]}">'
        f'<img src="{body_media_placeholder(ordinal)}" alt="{alt}" '
        f'style="{_STYLE["image"]}">'
        f'<p style="{_STYLE["caption"]}">场景图 · {escape(block.alt_text)}</p>'
        "</section>"
    )


def render_polished_html(article: ArticlePackage) -> str:
    _validate_polished_article(article)
    parts = [f'<section style="{_STYLE["root"]}">']
    parts.append(f'<section data-module="hero" style="{_STYLE["hero"]}">')
    parts.append(f'<p style="{_STYLE["hero_rule"]}"><br></p>')
    parts.append(f'<p style="{_STYLE["eyebrow"]}">SCIENCE · EDUCATION · FIELD GUIDE</p>')
    parts.append(f'<h1 style="{_STYLE["title"]}">{escape(article.title)}</h1>')
    parts.append(f'<p style="{_STYLE["deck"]}">{escape(article.digest)}</p>')
    parts.append(
        f'<p style="{_STYLE["issue"]}">{escape(article.author)} · 教育观察　/　本地草稿</p>'
    )
    parts.append("</section>")
    parts.append(f'<section style="{_STYLE["lead"]}">')
    parts.append(f'<p style="{_STYLE["lead_label"]}">从三个家长问题开始</p>')
    parts.extend(_paragraph_html(article.lead, _STYLE["lead_text"]))
    parts.append("</section>")

    policy = article.sections[0]
    policy_intro = _paragraph(policy.blocks[0])
    policy_items = _bullet_list(policy.blocks[1])
    policy_quote = _quote(policy.blocks[2])
    policy_image = _image(policy.blocks[3])
    parts.append(_image_html(policy_image, full_bleed=True))
    parts.append(f'<section data-module="policy-tiles" style="{_STYLE["module"]}">')
    parts.append(f'<p style="{_STYLE["kicker"]}">01 · 政策雷达</p>')
    parts.append(f'<h2 style="{_STYLE["heading"]}">{escape(policy.heading)}</h2>')
    parts.extend(_paragraph_html(policy_intro.text, _STYLE["paragraph"]))
    parts.append(f'<section style="{_STYLE["policy_grid"]}">')
    for index, item in enumerate(policy_items.items, start=1):
        parts.append(f'<p style="{_STYLE["policy_tile"]}">')
        parts.append(f'<span style="{_STYLE["policy_number"]}">{index:02d}</span>')
        parts.append(f"{_emphasized_html(item)}</p>")
    parts.append("</section>")
    parts.append(f'<blockquote style="{_STYLE["quote_band"]}">')
    parts.append(f'<p style="{_STYLE["quote_text"]}">{_emphasized_html(policy_quote.text)}</p>')
    parts.append("</blockquote></section>")

    questions = article.sections[1]
    parts.append(f'<section data-module="parent-question-cards" style="{_STYLE["module_alt"]}">')
    parts.append(f'<p style="{_STYLE["kicker"]}">02 · 家长三问</p>')
    parts.append(f'<h2 style="{_STYLE["heading"]}">{escape(questions.heading)}</h2>')
    for index, block in enumerate(questions.blocks[:3], start=1):
        question = _paragraph(block)
        parts.append(f'<section style="{_STYLE["question_card"]}">')
        parts.append(f'<span style="{_STYLE["question_number"]}">Q{index}</span>')
        parts.append(f'<p style="{_STYLE["question_text"]}">{_emphasized_html(question.text)}</p>')
        parts.append("</section>")
    boundary = _quote(questions.blocks[3])
    parts.append(f'<p style="{_STYLE["boundary_note"]}">{_emphasized_html(boundary.text)}</p>')
    parts.append("</section>")

    learning = article.sections[2]
    parts.append(f'<section data-module="learning-loop-rail" style="{_STYLE["module"]}">')
    parts.append(f'<p style="{_STYLE["kicker"]}">03 · 学习闭环</p>')
    parts.append(f'<h2 style="{_STYLE["heading"]}">{escape(learning.heading)}</h2>')
    for block in learning.blocks[:2]:
        parts.extend(_paragraph_html(_paragraph(block).text, _STYLE["paragraph"]))
    learning_steps = _bullet_list(learning.blocks[2])
    parts.append(f'<section style="{_STYLE["rail"]}">')
    for index, item in enumerate(learning_steps.items, start=1):
        parts.append(f'<p style="{_STYLE["rail_item"]}">')
        parts.append(f'<span style="{_STYLE["rail_dot"]}">{index}</span>')
        parts.append(f"{_emphasized_html(item)}</p>")
    parts.append("</section>")
    parts.append(_image_html(_image(learning.blocks[3]), full_bleed=False))
    parts.append("</section>")

    boundary_panel = article.sections[3]
    boundary_intro = _paragraph(boundary_panel.blocks[0])
    boundary_items = _bullet_list(boundary_panel.blocks[1])
    ai_items = boundary_items.items[: len(_AI_ASSIST_ITEMS)]
    child_items = boundary_items.items[len(_AI_ASSIST_ITEMS) :]
    parts.append(f'<section data-module="ai-child-boundary" style="{_STYLE["module_alt"]}">')
    parts.append(f'<p style="{_STYLE["kicker"]}">04 · AI × CHILD</p>')
    parts.append(f'<h2 style="{_STYLE["heading"]}">{escape(boundary_panel.heading)}</h2>')
    parts.extend(_paragraph_html(boundary_intro.text, _STYLE["paragraph"]))
    parts.append(f'<section style="{_STYLE["boundary_panel"]}">')
    parts.append(f'<section style="{_STYLE["boundary_top"]}">')
    parts.append(
        '<p style="margin:0 0 8px;color:#f5d34e;font-size:10px;font-weight:900;'
        'letter-spacing:1.8px">AI 可以协助</p>'
    )
    parts.append(f'<ul style="{_STYLE["boundary_list"]}">')
    parts.extend(
        f'<li style="{_STYLE["boundary_item_dark"]}">{_emphasized_html(item)}</li>'
        for item in ai_items
    )
    parts.append("</ul>")
    parts.append("</section>")
    parts.append(f'<section style="{_STYLE["boundary_bottom"]}">')
    parts.append(
        '<p style="margin:0 0 8px;color:#1e5bff;font-size:10px;font-weight:900;'
        'letter-spacing:1.8px">孩子必须完成</p>'
    )
    parts.append(f'<ul style="{_STYLE["boundary_list"]}">')
    parts.extend(
        f'<li style="{_STYLE["boundary_item_light"]}">{_emphasized_html(item)}</li>'
        for item in child_items
    )
    parts.append("</ul>")
    parts.append("</section>")
    parts.append(
        f'<p style="{_STYLE["boundary_rule"]}">'
        f"{_emphasized_html(_quote(boundary_panel.blocks[2]).text)}</p>"
    )
    parts.append("</section></section>")

    action = article.sections[4]
    action_times = ("STEP 01", "STEP 02", "STEP 03", "STEP 04", "STEP 05")
    parts.append(f'<section data-module="action-timeline" style="{_STYLE["module"]}">')
    parts.append(f'<p style="{_STYLE["kicker"]}">05 · 20 MINUTES</p>')
    parts.append(f'<h2 style="{_STYLE["heading"]}">{escape(action.heading)}</h2>')
    parts.extend(_paragraph_html(_paragraph(action.blocks[0]).text, _STYLE["paragraph"]))
    action_steps = _bullet_list(action.blocks[1])
    parts.append(f'<section style="{_STYLE["timeline"]}">')
    for time_label, item in zip(action_times, action_steps.items, strict=True):
        parts.append(f'<p style="{_STYLE["timeline_item"]}">')
        parts.append(f'<span style="{_STYLE["timeline_time"]}">{time_label}</span>')
        parts.append(f"{_emphasized_html(item)}</p>")
    parts.append("</section>")
    parts.extend(_paragraph_html(_paragraph(action.blocks[2]).text, _STYLE["paragraph"]))
    parts.append(_image_html(_image(action.blocks[3]), full_bleed=False))
    parts.append("</section>")

    closing = article.sections[5]
    parts.append(f'<section style="{_STYLE["module_alt"]}">')
    parts.append(f'<p style="{_STYLE["kicker"]}">06 · 家长的位置</p>')
    parts.append(f'<h2 style="{_STYLE["heading"]}">{escape(closing.heading)}</h2>')
    for block in closing.blocks[:2]:
        parts.extend(_paragraph_html(_paragraph(block).text, _STYLE["closing_copy"]))
    parts.append(
        f'<blockquote style="{_STYLE["closing_quote"]}">'
        f"{_emphasized_html(_quote(closing.blocks[2]).text)}</blockquote>"
    )
    parts.append("</section>")
    parts.append(f'<section data-module="closing-takeaway" style="{_STYLE["takeaway"]}">')
    parts.append(f'<p style="{_STYLE["takeaway_label"]}">TAKEAWAY · 留给孩子的能力</p>')
    parts.extend(_paragraph_html(article.conclusion, _STYLE["takeaway_text"]))
    parts.append("</section>")

    parts.append(f'<section style="{_STYLE["sources"]}">')
    parts.append(f'<p style="{_STYLE["sources_heading"]}">资料来源</p><ol>')
    for source in article.sources:
        url = _safe_source_url(source.source_url)
        parts.append(f'<li style="{_STYLE["source_item"]}">')
        parts.append(
            '<a rel="noopener noreferrer" referrerpolicy="no-referrer" '
            f'href="{escape(url, quote=True)}" style="{_STYLE["source_link"]}">'
            f"{escape(source.source_name)}</a></li>"
        )
    parts.append("</ol>")
    parts.append(
        f'<p style="{_STYLE["footer_boundary"]}">事实绑定上述权威来源；家庭建议为编辑性解释。'
        "本地草稿，未同步公众号，未发布。</p>"
    )
    parts.append("</section></section>")
    html = "".join(parts)
    if tuple(marker for marker in _MODULE_MARKERS if f'data-module="{marker}"' in html) != (
        _MODULE_MARKERS
    ):
        raise ValueError("polished editorial module markers changed")
    for ordinal in range(3):
        if html.count(body_media_placeholder(ordinal)) != 1:
            raise ValueError("polished editorial render placeholder set is invalid")
    return html


def _article_markdown(article: ArticlePackage) -> str:
    lines = [f"# {article.title}", "", f"> {article.digest}", "", article.lead, ""]
    for section in article.sections:
        lines.extend((f"## {section.heading}", ""))
        for block in section.blocks:
            if isinstance(block, ArticleParagraphBlock):
                lines.extend((block.text, ""))
            elif isinstance(block, ArticleBulletListBlock):
                lines.extend(f"- {item}" for item in block.items)
                lines.append("")
            elif isinstance(block, ArticleQuoteBlock):
                lines.extend((f"> {block.text}", ""))
            elif isinstance(block, ArticleImageBlock):
                ordinal = int(block.slot_key.removeprefix("body-"))
                lines.extend((f"![{block.alt_text}](assets/body-{ordinal:02d}.jpg)", ""))
    lines.extend(("## 写在最后", "", article.conclusion, "", "## 资料来源", ""))
    lines.extend(f"- [{source.source_name}]({source.source_url})" for source in article.sources)
    lines.extend(("", "事实绑定上述权威来源；家庭建议为编辑性解释。", ""))
    return "\n".join(lines)


def _preview_document(body: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'\">"
        "<title>公众号科学杂志型本地预览</title><style>"
        "*{box-sizing:border-box}html{background:#dfe4ec}body{margin:0}.frame{width:min(100%,430px);"
        "margin:28px auto;background:#f7f2e7;box-shadow:0 26px 80px #071b3330}"
        ".boundary{padding:10px 16px;"
        "background:#f5d34e;color:#071b33;font:800 10px/1.5 system-ui;letter-spacing:1.4px}"
        "@media(max-width:460px){.frame{margin:0;box-shadow:none}}"
        "@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}"
        '</style></head><body><main class="frame"><div class="boundary">'
        "LOCAL REVIEW · 证据已绑定 · 未同步公众号</div>"
        f"{body}</main></body></html>\n"
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(body: bytes) -> str:
    return sha256(body).hexdigest()


def _zip_bundle(root: Path, *, archive_root_name: str) -> Path:
    zip_path = root / f"{archive_root_name}.zip"
    files = tuple(
        sorted(
            (path for path in root.rglob("*") if path.is_file() and path.suffix != ".zip"),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            info = ZipInfo(f"{archive_root_name}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return zip_path


def export_polished_bundle(source_dir: Path, output_dir: Path) -> Path:
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("refusing to replace an existing polished editorial directory")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    bundle = load_source_bundle(source_dir)
    article = build_polished_article(bundle)
    canonical_html = render_polished_html(article)
    resolved_html = canonical_html
    for ordinal, image_name in enumerate(BODY_IMAGE_NAMES):
        placeholder = body_media_placeholder(ordinal)
        if resolved_html.count(placeholder) != 1:
            raise ValueError("polished editorial render placeholder set is invalid")
        resolved_html = resolved_html.replace(placeholder, f"assets/{image_name}")
    if "__OFFICIAL_ACCOUNT_BODY_MEDIA_" in resolved_html:
        raise ValueError("polished editorial render retains a media placeholder")
    render_fingerprint = fingerprint(
        REPORT_VERSION,
        RENDERER_VERSION,
        STYLE_VERSION,
        TEMPLATE_VERSION,
        canonical_html,
        bundle.image_checksums,
    )

    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        (temporary / "assets").mkdir()
        for name, body, checksum in zip(
            BODY_IMAGE_NAMES, bundle.image_bodies, bundle.image_checksums, strict=True
        ):
            if _sha256(body) != checksum:
                raise ValueError("source image changed during the polished repackage")
            (temporary / "assets" / name).write_bytes(body)
        (temporary / "article-body.html").write_text(resolved_html, encoding="utf-8")
        (temporary / "preview.html").write_text(_preview_document(resolved_html), encoding="utf-8")
        (temporary / "article.md").write_text(_article_markdown(article), encoding="utf-8")
        _write_json(
            temporary / "article-package.json",
            {"version": ARTICLE_SCHEMA_VERSION, "article": article.model_dump(mode="json")},
        )
        _write_json(
            temporary / "evidence.json",
            {
                "version": "official-account-news-editorial-evidence-v3",
                "source_snapshot_version": SOURCE_EVIDENCE_VERSION,
                "fact_brand_boundary": (
                    "external facts use evidence; family advice is interpretation"
                ),
                "sources": list(bundle.evidence_sources),
                "claims": [claim.model_dump(mode="json") for claim in article.claims],
            },
        )
        section_indexes = (0, 2, 4)
        visual_rows: list[dict[str, Any]] = []
        for ordinal, (source_row, checksum, section_index) in enumerate(
            zip(bundle.visual_rows, bundle.image_checksums, section_indexes, strict=True)
        ):
            image = next(
                block
                for block in article.sections[section_index].blocks
                if isinstance(block, ArticleImageBlock)
            )
            visual_rows.append(
                {
                    "ordinal": ordinal,
                    "section_index": section_index,
                    "section_heading": article.sections[section_index].heading,
                    "semantic_alt": image.alt_text,
                    "output_sha256": checksum,
                    "source_output_sha256": source_row["output"]["sha256"],
                    "reused_byte_exact": True,
                    "inherited_ip_visibility_assessment": source_row["ip_visibility_assessment"],
                    "inherited_reference_public_ref": source_row["reference_public_ref"],
                    "current_repackage_provider_calls": 0,
                }
            )
        _write_json(
            temporary / "visual-map.json",
            {
                "version": "official-account-news-editorial-visual-map-v3",
                "quality_status": "passed_inherited_local_inspection",
                "visuals": visual_rows,
            },
        )
        _write_json(
            temporary / "reference-learning.json",
            {
                "version": REFERENCE_STUDY_VERSION,
                "reference_url": REFERENCE_URL,
                "retained_source_content": False,
                "retained_source_html": False,
                "retained_source_images": False,
                "copied_reference_expression": False,
                "v2_gap": (
                    "paragraph rhythm was sufficient; repeated card forms weakened hierarchy"
                ),
                "applied_original_patterns": [
                    "news-led hero with an early full-width IP scene",
                    "one information form for each editorial job",
                    "policy tiles and parent question cards",
                    "learning-loop rail and AI-child responsibility boundary",
                    "bounded 20-minute action timeline",
                    "high-contrast closing takeaway",
                ],
                "module_markers": list(_MODULE_MARKERS),
            },
        )
        zero_calls = {
            "source_fetch_calls_in_repackage": 0,
            "article_provider_calls_in_repackage": 0,
            "embedding_provider_calls_in_repackage": 0,
            "image_provider_calls_in_repackage": 0,
            "comfly_calls_in_repackage": 0,
            "toapis_calls_in_repackage": 0,
            "wechat_calls": 0,
            "wecom_calls": 0,
            "publish_calls": 0,
        }
        _write_json(
            temporary / "run.json",
            {
                "version": REPORT_VERSION,
                "status": "ready",
                "simulation": True,
                "local_only": True,
                "copy_ready": False,
                "published": False,
                "manual_review_status": "pending",
                "article_body_character_count": article_body_character_count(article),
                "article_section_count": len(article.sections),
                "body_image_count": len(bundle.image_bodies),
                "content_fingerprint": article.content_fingerprint,
                "render_fingerprint": render_fingerprint,
                "renderer_version": RENDERER_VERSION,
                "style_version": STYLE_VERSION,
                "template_version": TEMPLATE_VERSION,
                "source_bundle_version": SOURCE_REPORT_VERSION,
                "source_bundle_content_fingerprint": bundle.source_content_fingerprint,
                "source_bundle_render_fingerprint": bundle.source_render_fingerprint,
                "source_bundle_run_id": bundle.source_run_id,
                "source_bundle_manifest_sha256": bundle.source_manifest_sha256,
                "inherited_historical_paid_image_calls": 3,
                **zero_calls,
            },
        )
        (temporary / "README.md").write_text(
            "# 教育部新闻 × 小赛 IP｜高节奏科学杂志版 v3\n\n"
            "本目录在 v2 的证据与图片边界上新增一套视觉层级：首图前置、政策卡、家长三问、"
            "学习闭环、AI/孩子边界、20 分钟行动线和结尾判断各使用不同的信息形态。没有复制"
            "参考文章的文字、HTML 或图片。\n\n"
            "- 色彩：深海军蓝、象牙白、钴蓝、橙色与克制黄色\n"
            "- 图片：三张既有小赛 IP JPEG 各使用一次，字节与 SHA-256 不变\n"
            "- 本次重排：新闻、文章模型、Embedding、生图、微信、企微、发布调用均为 0\n"
            "- 状态：ready / local-only / manual review pending / copy-ready false / "
            "unpublished\n\n"
            "打开 `preview.html` 查看 320--430 px 本地预览。\n",
            encoding="utf-8",
        )
        payload = tuple(
            sorted(
                (path for path in temporary.rglob("*") if path.is_file()),
                key=lambda path: path.relative_to(temporary).as_posix(),
            )
        )
        _write_json(
            temporary / "manifest.json",
            {
                "version": REPORT_VERSION,
                "status": "ready",
                "simulation": True,
                "local_only": True,
                "copy_ready": False,
                "published": False,
                "manual_review_status": "pending",
                "current_repackage_external_calls": 0,
                "inherited_historical_paid_image_calls": 3,
                "source_bundle_version": SOURCE_REPORT_VERSION,
                "source_bundle_run_id": bundle.source_run_id,
                "source_bundle_manifest_sha256": bundle.source_manifest_sha256,
                **zero_calls,
                "files": [
                    {
                        "path": path.relative_to(temporary).as_posix(),
                        "byte_size": path.stat().st_size,
                        "sha256": _sha256(path.read_bytes()),
                    }
                    for path in payload
                ],
            },
        )
        _zip_bundle(temporary, archive_root_name=output_dir.name)
        if output_dir.exists() or output_dir.is_symlink():
            raise FileExistsError("refusing to replace an existing polished editorial directory")
        temporary.rename(output_dir)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    output = export_polished_bundle(args.source_dir, args.output_dir)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
