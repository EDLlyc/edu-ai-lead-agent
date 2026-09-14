"""Frozen marketing framing, separate from generated body and news media."""

# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional reader copy.

from __future__ import annotations

from hashlib import sha256
from html import escape
from io import BytesIO
from typing import Final, Literal, TypeAlias

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from app.domain.official_account_editor_handoff import _leaf
from app.domain.official_account_local import ArticlePackage

LEGACY_XIAOSAI_FOOTER_PATH: Final = "assets/xiaosai-footer.jpg"
CHENGYUE_HEADER_MASTER_PATH: Final = "assets/chengyue-top-intro-master.png"
CHENGYUE_HEADER_PATH: Final = "assets/chengyue-top-intro.jpg"
XIAOSAI_FOOTER_MASTER_PATH: Final = "assets/xiaosai-marketing-footer-master.png"
XIAOSAI_FOOTER_PATH: Final = "assets/xiaosai-marketing-footer.jpg"
XIAOSAI_FOOTER_PATHS: Final = frozenset({LEGACY_XIAOSAI_FOOTER_PATH, XIAOSAI_FOOTER_PATH})
CHENGYUE_HEADER_MASTER_SHA256: Final = (
    "8821b4f367ea2aac7309a38171794c6dc4b3f90ee5a62a75510a3508d28169ee"
)
CHENGYUE_HEADER_PUBLICATION_SHA256: Final = (
    "bf3a505a4f61738132c869901f889a5f172d1291509b8963a6ce2d4785988223"
)
XIAOSAI_FOOTER_MASTER_SHA256: Final = (
    "f4026a63229b6239997e2b8d0bac540d9a06c1ead8a933ff8dd0365333556996"
)
XIAOSAI_FOOTER_PUBLICATION_SHA256: Final = (
    "9040f474f43e20289e26a0de52c385e7c86f7f2ea3aa1e287525160bf355c3b4"
)


class XiaosaiFooterAsset(BaseModel):
    """Legacy V1 catalog-bound footer descriptor retained for exact replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["official-account-xiaosai-final-cta-v1"] = (
        "official-account-xiaosai-final-cta-v1"
    )
    path: Literal["assets/xiaosai-footer.jpg"] = LEGACY_XIAOSAI_FOOTER_PATH
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


class ChengyueIntroductionHeaderAsset(BaseModel):
    """User-approved fixed Cheng Yue introduction banner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["official-account-chengyue-intro-header-v1"] = (
        "official-account-chengyue-intro-header-v1"
    )
    path: Literal["assets/chengyue-top-intro.jpg"] = CHENGYUE_HEADER_PATH
    role: Literal["header"] = "header"
    ordinal: Literal[0] = 0
    media_type: Literal["image/jpeg"] = "image/jpeg"
    alt_text: Literal["程岳，小赛AI星球001号数智人"] = "程岳，小赛AI星球001号数智人"
    byte_size: Literal[716140] = 716140
    sha256: Literal["bf3a505a4f61738132c869901f889a5f172d1291509b8963a6ce2d4785988223"] = (
        CHENGYUE_HEADER_PUBLICATION_SHA256
    )
    width: Literal[3840] = 3840
    height: Literal[1920] = 1920
    source_master_path: Literal["assets/chengyue-top-intro-master.png"] = (
        CHENGYUE_HEADER_MASTER_PATH
    )
    source_master_media_type: Literal["image/png"] = "image/png"
    source_master_byte_size: Literal[5882944] = 5882944
    source_master_sha256: Literal[
        "8821b4f367ea2aac7309a38171794c6dc4b3f90ee5a62a75510a3508d28169ee"
    ] = CHENGYUE_HEADER_MASTER_SHA256
    derivative_policy_version: Literal["official-account-upload-header-v1"] = (
        "official-account-upload-header-v1"
    )
    approved: Literal[True] = True
    purpose: Literal["introduce-chengyue-xiaosai-guide"] = "introduce-chengyue-xiaosai-guide"


class XiaosaiMarketingFooterAsset(BaseModel):
    """User-approved fixed QR banner and its deterministic upload derivative."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["official-account-xiaosai-final-cta-v2"] = (
        "official-account-xiaosai-final-cta-v2"
    )
    path: Literal["assets/xiaosai-marketing-footer.jpg"] = XIAOSAI_FOOTER_PATH
    role: Literal["footer"] = "footer"
    ordinal: Literal[0] = 0
    media_type: Literal["image/jpeg"] = "image/jpeg"
    alt_text: Literal["小赛AI星球关注二维码与青少年AI创意学习社区介绍"] = (
        "小赛AI星球关注二维码与青少年AI创意学习社区介绍"
    )
    byte_size: Literal[383664] = 383664
    sha256: Literal["9040f474f43e20289e26a0de52c385e7c86f7f2ea3aa1e287525160bf355c3b4"] = (
        XIAOSAI_FOOTER_PUBLICATION_SHA256
    )
    width: Literal[2048] = 2048
    height: Literal[1152] = 1152
    source_master_path: Literal["assets/xiaosai-marketing-footer-master.png"] = (
        XIAOSAI_FOOTER_MASTER_PATH
    )
    source_master_media_type: Literal["image/png"] = "image/png"
    source_master_byte_size: Literal[2092946] = 2092946
    source_master_sha256: Literal[
        "f4026a63229b6239997e2b8d0bac540d9a06c1ead8a933ff8dd0365333556996"
    ] = XIAOSAI_FOOTER_MASTER_SHA256
    derivative_policy_version: Literal["official-account-upload-footer-v1"] = (
        "official-account-upload-footer-v1"
    )
    characters: tuple[Literal["xiao-sai"]] = ("xiao-sai",)
    approved: Literal[True] = True
    qr_state: Literal["ready"] = "ready"
    purpose: Literal["follow-xiaosai-official-account"] = "follow-xiaosai-official-account"


OfficialAccountXiaosaiFooterAsset: TypeAlias = XiaosaiFooterAsset | XiaosaiMarketingFooterAsset


def parse_chengyue_header_asset(value: object) -> ChengyueIntroductionHeaderAsset:
    """Parse the sealed header without accepting structurally similar media."""
    return ChengyueIntroductionHeaderAsset.model_validate(value)


def parse_xiaosai_footer_asset(value: object) -> OfficialAccountXiaosaiFooterAsset:
    """Parse both frozen generations without silently upgrading historical artifacts."""
    if not isinstance(value, dict):
        raise ValueError("Xiaosai footer descriptor is invalid")
    if value.get("version") == "official-account-xiaosai-final-cta-v1":
        return XiaosaiFooterAsset.model_validate(value)
    if value.get("version") == "official-account-xiaosai-final-cta-v2":
        return XiaosaiMarketingFooterAsset.model_validate(value)
    raise ValueError("Xiaosai footer version is unsupported")


def validate_xiaosai_footer(
    footer: OfficialAccountXiaosaiFooterAsset,
    *,
    article: ArticlePackage | None,
    content: bytes,
) -> None:
    """Validate exact legacy catalog or current packaged publication identity."""
    if isinstance(footer, XiaosaiMarketingFooterAsset):
        if len(content) != footer.byte_size or sha256(content).hexdigest() != footer.sha256:
            raise ValueError("Xiaosai marketing footer publication bytes changed")
        with Image.open(BytesIO(content)) as image:
            if image.format != "JPEG" or image.size != (footer.width, footer.height):
                raise ValueError("Xiaosai marketing footer image identity changed")
            image.load()
        return

    # The legacy descriptor was bound to assignment zero. Keep that historical
    # reconstruction literal even though new owners no longer use the catalog.
    if article is None:
        raise ValueError("legacy Xiaosai footer requires its frozen Article")
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


def validate_chengyue_header(
    header: ChengyueIntroductionHeaderAsset,
    *,
    content: bytes,
) -> None:
    """Validate the exact approved publication bytes and decoded identity."""
    if len(content) != header.byte_size or sha256(content).hexdigest() != header.sha256:
        raise ValueError("Cheng Yue introduction header publication bytes changed")
    with Image.open(BytesIO(content)) as image:
        if image.format != "JPEG" or image.size != (header.width, header.height):
            raise ValueError("Cheng Yue introduction header image identity changed")
        image.load()


def render_chengyue_header(*, header: ChengyueIntroductionHeaderAsset) -> str:
    """Render the banner as a caption-free, WeChat-safe first content block."""
    return (
        '<section style="margin:0;">'
        f'<img src="{header.path}" alt="{escape(header.alt_text, quote=True)}" '
        'style="max-width:100%;height:auto;display:block;margin:0 auto;">'
        "</section>"
    )


def render_xiaosai_footer(*, author: str, footer: OfficialAccountXiaosaiFooterAsset) -> str:
    """Render either the literal V1 CTA or the current single-banner final region."""
    if isinstance(footer, XiaosaiMarketingFooterAsset):
        return (
            '<section style="margin:32px 20px 20px;padding:18px 20px;background:#F3FBFF;'
            'border:1px solid #C7DDEF;border-radius:16px;text-align:center;">'
            '<p style="font-size:13px;color:#26364A;line-height:1.8;margin:0;">'
            f"{_leaf(f'我是{author}，持续分享 AI 与科创教育的观察和实践。')}</p></section>"
            '<section style="margin:0;">'
            f'<img src="{footer.path}" alt="{escape(footer.alt_text, quote=True)}" '
            'style="max-width:100%;height:auto;display:block;margin:0 auto;">'
            "</section>"
        )

    # Do not change a byte of the legacy V1 rendering: persisted children rebuild
    # through this branch during validation/replay.
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
