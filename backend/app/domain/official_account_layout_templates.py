# ruff: noqa: RUF001
"""公众号排版模板: colour schemes applied to a rendered article body before it becomes a draft.

The renderer (Editor Handoff V2, theme `xiaosai-moyu-layout-v1`) writes a fixed set of colours
into inline styles. A template maps each of those colours to its own, so layout, typography,
images and wording stay exactly as rendered and only the scheme changes. The default template
is the identity, so an account without a choice gets byte-identical drafts.

Header and footer banners are images and keep their colours.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LAYOUT_TEMPLATE_VERSION = "official-account-layout-template-v1"
DEFAULT_LAYOUT_TEMPLATE_ID = "xiaosai-blue"

# Every colour the V2 renderer and the strict compaction emit (sampled from a real body).
RENDERER_COLOURS = (
    "#0D57C8",  # brand: headings, chapter titles, links
    "#285ACE",  # bright brand
    "#22D7D6",  # cyan gradient end
    "#29B6EE",  # sky accents
    "#C7DDEF",  # borders
    "#DCEAF5",  # light borders
    "#EAF7FF",  # pale card background
    "#F3FBFF",  # lighter card background
    "#F7FBFE",  # page tint
    "#B85A00",  # emphasis accent
    "#26364A",  # body text
    "#607086",  # muted text
)

_HEX = re.compile(r"#[0-9A-Fa-f]{6}(?![0-9A-Fa-f])")


@dataclass(frozen=True, slots=True)
class LayoutTemplate:
    id: str
    name: str
    description: str
    colours: dict[str, str] = field(default_factory=dict)

    def colour(self, original: str) -> str:
        return self.colours.get(original.upper(), original)

    @property
    def swatches(self) -> tuple[str, ...]:
        return tuple(self.colour(original) for original in RENDERER_COLOURS[:4])


LAYOUT_TEMPLATES: tuple[LayoutTemplate, ...] = (
    LayoutTemplate(
        id=DEFAULT_LAYOUT_TEMPLATE_ID,
        name="小赛蓝（默认）",
        description="现在一直在用的蓝色版式，科技感、品牌色最统一。",
    ),
    LayoutTemplate(
        id="jade-green",
        name="青绿",
        description="青绿色为主，清爽自然，适合科普、自然、实验类内容。",
        colours={
            "#0D57C8": "#0B7A64",
            "#285ACE": "#11806A",
            "#22D7D6": "#3CCFB0",
            "#29B6EE": "#2BB39A",
            "#C7DDEF": "#C3E4D8",
            "#DCEAF5": "#D6EEE5",
            "#EAF7FF": "#EAF8F2",
            "#F3FBFF": "#F2FBF7",
            "#F7FBFE": "#F6FCF9",
        },
    ),
    LayoutTemplate(
        id="warm-orange",
        name="暖橙",
        description="暖橙色为主，亲切温暖，适合亲子、活动、节日类内容。",
        colours={
            "#0D57C8": "#B4450F",
            "#285ACE": "#B04A16",
            "#22D7D6": "#F2A541",
            "#29B6EE": "#E88D3A",
            "#C7DDEF": "#F0D6C2",
            "#DCEAF5": "#F5E3D3",
            "#EAF7FF": "#FDF3EA",
            "#F3FBFF": "#FEF8F2",
            "#F7FBFE": "#FFFBF7",
            "#B85A00": "#1E6091",
        },
    ),
    LayoutTemplate(
        id="ink",
        name="墨黑简约",
        description="黑灰为主，克制沉稳，适合政策解读、深度分析类内容。",
        colours={
            "#0D57C8": "#1F2A37",
            "#285ACE": "#374151",
            "#22D7D6": "#9CA3AF",
            "#29B6EE": "#6B7280",
            "#C7DDEF": "#D7DCE1",
            "#DCEAF5": "#E5E7EB",
            "#EAF7FF": "#F3F4F6",
            "#F3FBFF": "#F7F8F9",
            "#F7FBFE": "#FAFAFB",
            "#B85A00": "#B45309",
        },
    ),
)

_BY_ID = {template.id: template for template in LAYOUT_TEMPLATES}


def layout_template(template_id: str | None) -> LayoutTemplate:
    """The template for an id; an unknown or missing id falls back to the default."""

    return _BY_ID.get(template_id or DEFAULT_LAYOUT_TEMPLATE_ID, _BY_ID[DEFAULT_LAYOUT_TEMPLATE_ID])


def is_layout_template(template_id: str) -> bool:
    return template_id in _BY_ID


def apply_layout_template(html: str, template_id: str | None) -> str:
    template = layout_template(template_id)
    if not template.colours:
        return html
    return _HEX.sub(lambda match: template.colour(match.group(0)), html)


__all__ = [
    "DEFAULT_LAYOUT_TEMPLATE_ID",
    "LAYOUT_TEMPLATES",
    "LAYOUT_TEMPLATE_VERSION",
    "RENDERER_COLOURS",
    "LayoutTemplate",
    "apply_layout_template",
    "is_layout_template",
    "layout_template",
]
