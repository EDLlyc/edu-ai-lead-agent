"""Deterministic, local-only source footer for a generated news poster."""

# ruff: noqa: RUF001 -- exact Chinese source labels use native punctuation.

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from app.domain.news_infographic import ValidatedInfographicInput

FOOTER_VERSION = "daily-news-infographic-footer-v2"
# v5 (operator request 2026-09-29, 图片上不放链接): delivered images show the news date and source
# only; the original link stays in the Moments text.
DELIVERY_FOOTER_VERSION = "daily-news-infographic-footer-v5-no-link"
FOOTER_TOP = 1858
_GEOMETRY = (1152, 2048)
_FONT_PATH = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
_MAX_IMAGE_BYTES = 24 * 1024 * 1024


class FooterRenderError(ValueError):
    """The exact locked attribution cannot be safely rendered."""


@dataclass(frozen=True, slots=True)
class RenderedFooter:
    image_bytes: bytes
    image_sha256: str
    font_sha256: str
    source_url_lines: tuple[str, ...]


def _font_bytes() -> bytes:
    if _FONT_PATH.is_symlink() or not _FONT_PATH.is_file():
        raise FooterRenderError("approved local CJK font is missing")
    try:
        font_bytes = _FONT_PATH.read_bytes()
    except OSError as exc:
        raise FooterRenderError("approved local CJK font cannot be read") from exc
    if not font_bytes or len(font_bytes) > 32 * 1024 * 1024:
        raise FooterRenderError("approved local CJK font is invalid")
    return font_bytes


def footer_font_sha256() -> str:
    """Pin the CJK font used for formal citation pixels in the poster policy."""
    return sha256(_font_bytes()).hexdigest()


def _load_font(font_bytes: bytes, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(BytesIO(font_bytes), size)
    except OSError as exc:
        raise FooterRenderError("approved local CJK font cannot be loaded") from exc


def _wrap_exact_url(
    url: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    *,
    first_line_width: int | None = None,
    prefer_path_boundary: bool = False,
) -> tuple[str, ...]:
    if not url or len(url) > 180 or any(ord(character) < 33 for character in url):
        raise FooterRenderError("source URL is unsafe or overlong")
    lines: list[str] = []
    remaining = url
    while remaining:
        if len(lines) == 2:
            raise FooterRenderError("exact source URL does not fit the footer")
        line_width = first_line_width if not lines and first_line_width is not None else max_width
        length = 0
        for index in range(1, len(remaining) + 1):
            if font.getlength(remaining[:index]) > line_width:
                break
            length = index
        if length == 0:
            raise FooterRenderError("exact source URL does not fit the footer")
        if prefer_path_boundary and not lines and length < len(remaining):
            for split_at in range(length, length // 2, -1):
                if (
                    remaining[split_at - 1] in "/?&"
                    and font.getlength(remaining[split_at:]) <= max_width
                ):
                    length = split_at
                    break
        lines.append(remaining[:length])
        remaining = remaining[length:]
    if "".join(lines) != url:
        raise FooterRenderError("exact source URL was changed")
    return tuple(lines)


def _draw_fitted(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    x: int,
    y: int,
    right: int,
    bottom: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    if not text or any(ord(character) < 32 for character in text):
        raise FooterRenderError("source footer contains invalid text")
    bbox = draw.textbbox((x, y), text, font=font, anchor="lt")
    if bbox[0] < x or bbox[1] < y or bbox[2] > right or bbox[3] > bottom:
        raise FooterRenderError("source footer text would be clipped")
    draw.text((x, y), text, font=font, fill=fill, anchor="lt")


FooterMode = Literal["local", "test", "formal"]


def delivery_footer_text(case: ValidatedInfographicInput, *, mode: FooterMode = "formal") -> str:
    """The exact text drawn in a delivered footer, for the footer OCR comparison."""

    text = f"新闻日期：{case.source_date.isoformat()}新闻来源：{case.source_name}"
    return f"{text}【测试消息】" if mode == "test" else text


def _draw_phone_readable_footer(
    draw: ImageDraw.ImageDraw,
    case: ValidatedInfographicInput,
    font_bytes: bytes,
    *,
    mode: Literal["test", "formal"],
) -> tuple[str, ...]:
    """News date and source, large enough for a phone; no link on delivered images."""
    metadata_font = _load_font(font_bytes, 34)
    notice_font = _load_font(font_bytes, 30)
    ink = "#164777"
    top = 1905 if mode == "test" else 1930
    _draw_fitted(
        draw,
        f"新闻日期：{case.source_date.isoformat()}",
        x=48,
        y=top,
        right=430,
        bottom=top + 42,
        font=metadata_font,
        fill=ink,
    )
    _draw_fitted(
        draw,
        f"新闻来源：{case.source_name}",
        x=450,
        y=top,
        right=1104,
        bottom=top + 42,
        font=metadata_font,
        fill=ink,
    )
    if mode == "test":
        _draw_fitted(
            draw,
            "【测试消息】",
            x=48,
            y=1965,
            right=1104,
            bottom=2002,
            font=notice_font,
            fill=ink,
        )
    return ()


def _draw_legacy_link_footer(
    draw: ImageDraw.ImageDraw,
    case: ValidatedInfographicInput,
    font_bytes: bytes,
    *,
    mode: Literal["test", "formal"],
) -> tuple[str, ...]:
    """footer-v4 (with the original link), kept only to verify posters produced before v5."""
    metadata_font = _load_font(font_bytes, 30)
    notice_font = _load_font(font_bytes, 29)
    label_font = _load_font(font_bytes, 28)
    url_font = _load_font(font_bytes, 34)
    url_x = 206 if mode == "test" else 48
    lines = _wrap_exact_url(
        case.source_url,
        url_font,
        1056,
        first_line_width=1104 - url_x,
        prefer_path_boundary=True,
    )
    ink = "#164777"
    _draw_fitted(
        draw,
        f"新闻日期：{case.source_date.isoformat()}",
        x=48,
        y=1870,
        right=398,
        bottom=1905,
        font=metadata_font,
        fill=ink,
    )
    _draw_fitted(
        draw,
        f"新闻来源：{case.source_name}",
        x=414,
        y=1870,
        right=1104,
        bottom=1905,
        font=metadata_font,
        fill=ink,
    )
    if mode == "test":
        _draw_fitted(
            draw,
            "【测试消息】",
            x=48,
            y=1909,
            right=1104,
            bottom=1939,
            font=notice_font,
            fill=ink,
        )
    _draw_fitted(
        draw,
        "原文链接：",
        x=48,
        y=1942 if mode == "test" else 1909,
        right=url_x - 6 if mode == "test" else 1104,
        bottom=1979 if mode == "test" else 1939,
        font=label_font,
        fill=ink,
    )
    for index, line in enumerate(lines):
        _draw_fitted(
            draw,
            line,
            x=url_x if index == 0 else 48,
            y=1940 + index * 45,
            right=1104,
            bottom=1983 + index * 45,
            font=url_font,
            fill="#075a9e",
        )
    return lines


def _draw_exact_source_footer(
    image: Image.Image,
    case: ValidatedInfographicInput,
    *,
    mode: FooterMode = "local",
    legacy_link: bool = False,
) -> tuple[str, tuple[str, ...]]:
    """Use one layout for both the paid-call preflight and the final raster."""
    if not case.source_url or not case.source_name:
        raise FooterRenderError("frozen source attribution is incomplete")
    font_bytes = _font_bytes()
    font_hash = sha256(font_bytes).hexdigest()
    large_font = _load_font(font_bytes, 27)
    label_font = _load_font(font_bytes, 24)
    url_font = _load_font(font_bytes, 25)
    note_font = _load_font(font_bytes, 20)
    lines = _wrap_exact_url(case.source_url, url_font, 1056) if mode == "local" else ()
    draw = ImageDraw.Draw(image)
    background = (255, 255, 255, 255) if image.mode == "RGBA" else (255, 255, 255)
    draw.rectangle((0, FOOTER_TOP, 1151, 2047), fill=background)
    draw.rectangle((0, FOOTER_TOP, 1151, FOOTER_TOP + 2), fill="#46bfe6")
    draw.rectangle((0, 2042, 1151, 2047), fill="#30afe1")
    if mode != "local":
        drawer = _draw_legacy_link_footer if legacy_link else _draw_phone_readable_footer
        return font_hash, drawer(draw, case, font_bytes, mode=mode)
    ink = "#164777"
    _draw_fitted(
        draw,
        f"新闻日期：{case.source_date.isoformat()}",
        x=48,
        y=1873,
        right=398,
        bottom=1909,
        font=large_font,
        fill=ink,
    )
    _draw_fitted(
        draw,
        f"新闻来源：{case.source_name}",
        x=414,
        y=1873,
        right=1104,
        bottom=1909,
        font=large_font,
        fill=ink,
    )
    _draw_fitted(
        draw,
        "原文链接：",
        x=48,
        y=1914,
        right=1104,
        bottom=1941,
        font=label_font,
        fill=ink,
    )
    for index, line in enumerate(lines):
        _draw_fitted(
            draw,
            line,
            x=48,
            y=1944 + index * 32,
            right=1104,
            bottom=1975 + index * 32,
            font=url_font,
            fill="#075a9e",
        )
    _draw_fitted(
        draw,
        "本地样稿 · 未发布",
        x=48,
        y=2010,
        right=1104,
        bottom=2039,
        font=note_font,
        fill=ink,
    )
    return font_hash, lines


def validate_exact_source_footer_layout(
    case: ValidatedInfographicInput, *, mode: FooterMode = "local"
) -> tuple[str, ...]:
    """Fail before a paid image call when the exact frozen footer cannot fit."""
    probe = Image.new("RGB", _GEOMETRY, "white")
    _, lines = _draw_exact_source_footer(probe, case, mode=mode)
    return lines


def render_exact_source_footer(
    original_bytes: bytes,
    case: ValidatedInfographicInput,
    *,
    mode: FooterMode = "local",
    legacy_link: bool = False,
) -> RenderedFooter:
    """Return a new PNG; the provider raster stays untouched and traceable."""
    if not original_bytes or len(original_bytes) > _MAX_IMAGE_BYTES:
        raise FooterRenderError("original image is missing or too large")
    try:
        with Image.open(BytesIO(original_bytes)) as opened:
            if opened.size != _GEOMETRY or opened.mode not in {"RGB", "RGBA"}:
                raise FooterRenderError("original image geometry or mode is unsupported")
            if getattr(opened, "n_frames", 1) != 1:
                raise FooterRenderError("animated original image is unsupported")
            opened.load()
            image = opened.copy()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        if isinstance(exc, FooterRenderError):
            raise
        raise FooterRenderError("original image cannot be decoded") from exc

    font_hash, lines = _draw_exact_source_footer(image, case, mode=mode, legacy_link=legacy_link)
    result = BytesIO()
    image.save(result, format="PNG", optimize=False)
    body = result.getvalue()
    return RenderedFooter(
        image_bytes=body,
        image_sha256=sha256(body).hexdigest(),
        font_sha256=font_hash,
        source_url_lines=lines,
    )


def render_delivery_footer_variants(
    original_bytes: bytes, case: ValidatedInfographicInput, *, mode: FooterMode = "formal"
) -> tuple[RenderedFooter, ...]:
    """The current delivered footer first, then footer-v4 for posters produced before v5.

    Send gates re-render a stored poster byte-for-byte; a poster produced with the linked v4
    footer on the day of the switch must still verify instead of being withheld.
    """

    return (
        render_exact_source_footer(original_bytes, case, mode=mode),
        render_exact_source_footer(original_bytes, case, mode=mode, legacy_link=True),
    )
