"""Project-owned Xiaosai theme tokens for the local WeChat editor handoff.

This module intentionally vendors only the deterministic component vocabulary used by
the application renderer. Runtime code never reads a personal Codex skill directory or
accepts a caller-supplied template.
"""

# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional content.

from __future__ import annotations

import json
from hashlib import sha256
from typing import Final, Literal

XIAOSAI_GZH_THEME_ID: Final[Literal["xiaosai-moyu-layout-v1"]] = "xiaosai-moyu-layout-v1"
XIAOSAI_GZH_THEME_SOURCE_SHA256: Final = (
    "2492a7dbab724ac60de92cdb0e4af7daa9a1d92eaeed85492d0f268858863688"
)

XIAOSAI_GZH_THEME: dict[str, object] = {
    "id": XIAOSAI_GZH_THEME_ID,
    "name": "小赛蓝（摸鱼绿原结构）",
    "source_sha256": XIAOSAI_GZH_THEME_SOURCE_SHA256,
    "layout": (
        "cover-breaking",
        "toc-scroll",
        "oneliner-card",
        "chapter-title",
        "prose-and-media",
        "source-card",
        "footer-cta",
    ),
    "palette": {
        "brand_blue": "#0D57C8",
        "bright_blue": "#285ACE",
        "cyan": "#22D7D6",
        "sky": "#29B6EE",
        "orange": "#FC9103",
        "pale_blue": "#EAF7FF",
        "border": "#C7DDEF",
        "text": "#26364A",
        "muted": "#607086",
        "paper": "#FFFFFF",
    },
    "typography": {
        "font_stack": (
            "-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB',"
            "'Microsoft YaHei',sans-serif"
        ),
        "body_px": 14,
        "body_line_height": 1.9,
        "max_width_px": 677,
    },
    "wechat_contract": {
        "pure_section_fragment": True,
        "inline_styles_only": True,
        "span_leaf_text": True,
        "image_style": "max-width:100%;height:auto;display:block;margin:0 auto",
    },
}

XIAOSAI_GZH_THEME_CANONICAL_JSON = json.dumps(
    XIAOSAI_GZH_THEME,
    ensure_ascii=False,
    separators=(",", ":"),
    sort_keys=True,
)
XIAOSAI_GZH_THEME_SHA256 = sha256(XIAOSAI_GZH_THEME_CANONICAL_JSON.encode("utf-8")).hexdigest()
