"""Frozen approved-reference footer, separate from generated body and news media."""

# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional reader copy.

from __future__ import annotations

from hashlib import sha256
from html import escape
from io import BytesIO
from typing import Final, Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from app.domain.official_account_editor_handoff import _leaf
from app.domain.official_account_local import ArticlePackage

XIAOSAI_FOOTER_PATH: Final = "assets/xiaosai-footer.jpg"


class XiaosaiFooterAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["official-account-xiaosai-final-cta-v1"] = (
        "official-account-xiaosai-final-cta-v1"
    )
    path: Literal["assets/xiaosai-footer.jpg"] = XIAOSAI_FOOTER_PATH
    role: Literal["footer"] = "footer"
    ordinal: Literal[0] = 0
    media_type: Literal["image/jpeg"] = "image/jpeg"
    alt_text: Literal["小赛，陪伴家庭开展科学探索"] = "小赛，陪伴家庭开展科学探索"
    byte_size: int = Field(gt=0, le=1024 * 1024 - 1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(ge=512, le=1536)
    height: int = Field(ge=512, le=1536)
    catalog_version: str = Field(min_length=1, max_length=80)
    catalog_asset_ref: str = Field(pattern=r"^[0-9a-f]{16}$")
    source_master_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    characters: tuple[Literal["xiao-sai"]] = ("xiao-sai",)
    approved: Literal[True] = True
    qr_state: Literal["pending"] = "pending"


def validate_xiaosai_footer(
    footer: XiaosaiFooterAsset, *, article: ArticlePackage, content: bytes
) -> None:
    """Bind to the already-frozen assignment, never a caller's character label alone."""
    selection = article.media_selection
    if selection is None or not selection.assignments:
        raise ValueError("Xiaosai footer reference selection is unavailable")
    first = selection.assignments[0]
    if (
        footer.catalog_version,
        footer.catalog_asset_ref,
        footer.source_master_sha256,
        footer.sha256,
    ) != (
        selection.catalog_version,
        first.candidate_ref,
        first.source_checksum,
        first.publication_checksum,
    ):
        raise ValueError("Xiaosai footer frozen reference changed")
    if len(content) != footer.byte_size or sha256(content).hexdigest() != footer.sha256:
        raise ValueError("Xiaosai footer publication bytes changed")
    with Image.open(BytesIO(content)) as image:
        if image.format != "JPEG" or image.size != (footer.width, footer.height):
            raise ValueError("Xiaosai footer image identity changed")
        image.load()


def render_xiaosai_footer(*, author: str, footer: XiaosaiFooterAsset) -> str:
    """One final signature/CTA; the QR reserve intentionally is not an image."""
    return (
        '<section style="margin:32px 20px 0;padding:24px 20px;background:#F3FBFF;'
        'border:1px solid #C7DDEF;border-radius:16px;text-align:center;">'
        '<p style="font-size:13px;color:#26364A;line-height:1.8;margin:0 0 14px;">'
        f"{_leaf(f'我是{author}，持续分享 AI 与科创教育的观察和实践。')}</p>"
        '<p style="font-size:17px;color:#0D57C8;font-weight:800;margin:0 0 12px;">'
        f"{_leaf('认识小赛，让科学走进日常')}</p>"
        '<section style="max-width:240px;margin:0 auto 16px;">'
        f'<img src="{footer.path}" alt="{escape(footer.alt_text, quote=True)}" '
        'style="max-width:100%;height:auto;display:block;margin:0 auto;border-radius:12px;">'
        '</section><p style="font-size:13px;color:#44546A;line-height:1.8;margin:0 0 14px;">'
        f"{_leaf('小赛陪伴中国家庭一起提问、观察和动手探索，记录生活里的科学发现。')}</p>"
        '<p style="font-size:14px;color:#0D57C8;font-weight:700;line-height:1.8;margin:0 0 20px;">'
        f"{_leaf('欢迎关注，继续阅读科学教育与家庭探究内容。')}</p>"
        '<section style="max-width:160px;margin:0 auto;padding:30px 12px;'
        'border:1px dashed #C7DDEF;border-radius:12px;background:#FFFFFF;">'
        '<p style="font-size:13px;color:#607086;margin:0;line-height:1.8;">'
        f"{_leaf('二维码待补')}</p></section>"
        '<p style="font-size:11px;color:#8291A5;line-height:1.7;margin:10px 0 0;">'
        f"{_leaf('关注或添加方式将在确认后补充。')}</p></section>"
    )
