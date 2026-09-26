"""Provider-free exact-text overlay shared by local previews and formal posters.

The generated raster remains immutable. This prototype deliberately masks all
model-painted prose, including the decorative blackboard and book labels.
"""

# ruff: noqa: RUF001 -- frozen Chinese editorial copy and punctuation are exact.

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from app.application.services.news_infographic import PosterCopy, validate_poster_copy
from app.domain.news_infographic import ValidatedInfographicInput

OVERLAY_VERSION = "daily-news-infographic-exact-text-v1"
_GEOMETRY = (1152, 2048)
_MAX_RAW_BYTES = 24 * 1024 * 1024
_FONT_PATH = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
_REVIEWED_COPY_SHA256 = "f67e5ddc75bd6480694fc2dee8e197311ccf14a6e40d5507c862c7f5d05d52f0"
_REVIEWED_LINES = (
    ("小赛洞察",),
    ("教育部启动科学教育", "做中学领航行动"),
    (
        "教育部印发指南部署科学教育“做中学”",
        "领航行动，以学生为主体、实践为路径，聚焦",
        "真实问题开展跨学科探究，全面提升科学素养。",
    ),
    ("做中学：从真实问题出发",),
    (
        "领航行动聚焦真实问题，",
        "引导孩子关注生活实际，",
        "开展跨学科探究实践，",
        "掌握科学方法，发展科学思维能力，",
        "激发好奇心与探求欲。",
    ),
    ("怎样像科学家一样探究",),
    (
        "遇到生活现象先问为什么，",
        "再动手试一试。围绕问题意识设计",
        "小实验，观察记录结果并反思改进，",
        "在实践中验证自己的想法。",
    ),
    ("赛先生科学的教育理念",),
    (
        "赛先生科学以培养科学素养与创新能力",
        "为核心，让孩子成为真实问题的发现者",
        "与未知世界的探索者，",
        "像科学家一样思考，",
        "像工程师一样解决问题。",
    ),
)
_SEMANTIC_PHRASES = (
    "做中学",
    "领航行动",
    "真实问题",
    "孩子",
    "生活实际",
    "跨学科探究",
    "探究实践",
    "科学素养",
    "科学方法",
    "科学思维能力",
    "动手试一试",
    "问题意识",
    "小实验",
    "观察记录",
    "反思改进",
    "赛先生科学",
    "创新能力",
    "未知世界",
    "像科学家一样",
    "像工程师一样",
    "解决问题",
)


class TextOverlayError(ValueError):
    """The approved copy cannot be rendered exactly and legibly."""


@dataclass(frozen=True, slots=True)
class RenderedTextOverlay:
    image_bytes: bytes
    image_sha256: str
    font_sha256: str
    line_counts: tuple[int, ...]
    rendered_lines: tuple[tuple[str, ...], ...]


def poster_copy_fingerprint(copy: PosterCopy) -> str:
    canonical = json.dumps(
        copy.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _font_data() -> bytes:
    if _FONT_PATH.is_symlink() or not _FONT_PATH.is_file():
        raise TextOverlayError("approved CJK font is unavailable")
    try:
        data = _FONT_PATH.read_bytes()
    except OSError as exc:
        raise TextOverlayError("approved CJK font cannot be read") from exc
    if not data or len(data) > 32 * 1024 * 1024:
        raise TextOverlayError("approved CJK font is invalid")
    return data


def text_overlay_font_sha256() -> str:
    """Pin the actual installed CJK font in formal poster policy identity."""
    return sha256(_font_data()).hexdigest()


def _font(data: bytes, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(BytesIO(data), size)
    except OSError as exc:
        raise TextOverlayError("approved CJK font cannot be loaded") from exc


def _exact_lines(
    text: str, font: ImageFont.FreeTypeFont, width: int, max_lines: int
) -> tuple[str, ...]:
    if not text or any(ord(character) < 32 for character in text):
        raise TextOverlayError("approved poster text is invalid")
    if any(font.getlength(character) > width for character in text):
        raise TextOverlayError("a poster glyph exceeds its text panel")
    forbidden_start = "，。！？：；、）》”’"
    forbidden_end = "（《“‘"
    forbidden_splits: set[int] = set()
    for phrase in _SEMANTIC_PHRASES:
        search_from = 0
        while (found_at := text.find(phrase, search_from)) >= 0:
            forbidden_splits.update(range(found_at + 1, found_at + len(phrase)))
            search_from = found_at + 1
    for line_count in range(1, max_lines + 1):
        target_width = font.getlength(text) / line_count

        @cache
        def best(
            start: int, remaining: int, *, target: float = target_width
        ) -> tuple[float, tuple[str, ...]] | None:
            if remaining == 0:
                return (0.0, ()) if start == len(text) else None
            winner: tuple[float, tuple[str, ...]] | None = None
            for end in range(start + 1, len(text) - remaining + 2):
                part = text[start:end]
                part_width = font.getlength(part)
                if part_width > width:
                    break
                if (
                    (start and part[0] in forbidden_start)
                    or (end < len(text) and part[-1] in forbidden_end)
                    or (end < len(text) and end in forbidden_splits)
                ):
                    continue
                tail = best(end, remaining - 1)
                if tail is None:
                    continue
                cost = (part_width - target) ** 2 + tail[0]
                if winner is None or cost < winner[0]:
                    winner = (cost, (part, *tail[1]))
            return winner

        solution = best(0, line_count)
        if solution is not None:
            lines = solution[1]
            if "".join(lines) != text:
                raise TextOverlayError("approved poster text changed during layout")
            return lines
    raise TextOverlayError("approved poster text exceeds its fixed line budget")


def _balanced_title_lines(text: str, font: ImageFont.FreeTypeFont, width: int) -> tuple[str, ...]:
    if font.getlength(text) <= width:
        return (text,)
    semantic_break = text.find("做中学")
    if semantic_break > 0:
        semantic = (text[:semantic_break], text[semantic_break:])
        if all(font.getlength(line) <= width for line in semantic):
            return semantic
    choices = (
        (text[:index], text[index:])
        for index in range(1, len(text))
        if font.getlength(text[:index]) <= width and font.getlength(text[index:]) <= width
    )
    try:
        lines = min(
            choices, key=lambda parts: abs(font.getlength(parts[0]) - font.getlength(parts[1]))
        )
    except ValueError as exc:
        raise TextOverlayError("approved poster title exceeds its fixed line budget") from exc
    if "".join(lines) != text:
        raise TextOverlayError("approved poster title changed during layout")
    return lines


def _draw_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    box: tuple[int, int, int, int],
    font: ImageFont.FreeTypeFont,
    line_height: int,
    max_lines: int,
    fill: str,
    stroke_width: int = 0,
    balanced_title: bool = False,
    reviewed_lines: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    left, top, right, bottom = box
    if not text or any(ord(character) < 32 for character in text):
        raise TextOverlayError("approved poster text is invalid")
    line_width = right - left - 2 * stroke_width
    if reviewed_lines is not None:
        lines = reviewed_lines
    else:
        lines = (
            _balanced_title_lines(text, font, line_width)
            if balanced_title
            else _exact_lines(text, font, line_width, max_lines)
        )
    if "".join(lines) != text:
        raise TextOverlayError("reviewed line breaks do not equal approved copy")
    if len(lines) > max_lines:
        raise TextOverlayError("approved poster text exceeds its fixed line budget")
    for index, line in enumerate(lines):
        x = left + stroke_width
        y = top + stroke_width + index * line_height
        bounds = draw.textbbox((x, y), line, font=font, anchor="lt", stroke_width=stroke_width)
        if (
            bounds[0] < left
            or bounds[1] < top + index * line_height
            or bounds[2] > right
            or bounds[3] > bottom
        ):
            raise TextOverlayError("approved poster text would be clipped")
        draw.text(
            (x, y),
            line,
            font=font,
            anchor="lt",
            fill=fill,
            stroke_width=stroke_width,
        )
    return lines


def _paint(
    image: Image.Image,
    copy: PosterCopy,
    font_data: bytes,
    *,
    use_reviewed_lines: bool = True,
) -> tuple[tuple[str, ...], ...]:
    draw = ImageDraw.Draw(image)
    reviewed = (
        _REVIEWED_LINES
        if use_reviewed_lines and poster_copy_fingerprint(copy) == _REVIEWED_COPY_SHA256
        else None
    )
    # A complete opaque top panel replaces every model-painted headline/summary glyph.
    draw.rounded_rectangle((35, 42, 874, 520), radius=34, fill="#fffef9")
    draw.rounded_rectangle((53, 58, 312, 119), radius=28, fill="#066ee6")
    counts = [
        _draw_text(
            draw,
            "小赛洞察",
            box=(78, 65, 292, 112),
            font=_font(font_data, 43),
            line_height=48,
            max_lines=1,
            fill="#ffffff",
            stroke_width=1,
            reviewed_lines=reviewed[0] if reviewed else None,
        )
    ]
    counts.append(
        _draw_text(
            draw,
            copy.title,
            box=(61, 137, 850, 283),
            font=_font(font_data, 51),
            line_height=66,
            max_lines=2,
            fill="#123d80",
            stroke_width=1,
            balanced_title=True,
            reviewed_lines=reviewed[1] if reviewed else None,
        )
    )
    draw.rounded_rectangle((56, 292, 852, 304), radius=6, fill="#ffd44a")
    counts.append(
        _draw_text(
            draw,
            copy.news_summary,
            box=(61, 325, 850, 502),
            font=_font(font_data, 35),
            line_height=53,
            max_lines=4,
            fill="#143b77",
            reviewed_lines=reviewed[2] if reviewed else None,
        )
    )

    # These background labels were painted by the image model, not approved copy.
    # Mask them as plain decorative surfaces rather than allowing extra claims.
    draw.rounded_rectangle((995, 174, 1151, 453), radius=15, fill="#17475a")
    # Rebuild the three visible book spines without their invented labels.
    for top, bottom, color in (
        (772, 829, "#0865bd"),
        (832, 888, "#ba5c2b"),
        (890, 944, "#438d40"),
    ):
        draw.rounded_rectangle((994, top, 1151, bottom), radius=11, fill=color)
        draw.line((1011, top + 8, 1011, bottom - 8), fill="#f6d28a", width=4)
        draw.line((1135, top + 8, 1135, bottom - 8), fill="#ffffff", width=3)

    sections = (
        ((42, 950, 672, 1237), (59, 964, 657, 1032), 1046, 1234, 33, 38, "#086de5"),
        ((42, 1260, 672, 1532), (59, 1274, 657, 1342), 1358, 1517, 31, 41, "#079c79"),
        ((42, 1548, 672, 1848), (59, 1562, 657, 1630), 1645, 1840, 33, 40, "#6240df"),
    )
    for index, (
        card,
        (panel, header, body_top, body_bottom, body_size, body_leading, color),
    ) in enumerate(zip(copy.cards, sections, strict=True)):
        draw.rounded_rectangle(panel, radius=28, fill="#fffefa")
        draw.rounded_rectangle(header, radius=26, fill=color)
        counts.append(
            _draw_text(
                draw,
                card.heading,
                box=(77, header[1] + 9, 644, header[3] - 6),
                font=_font(font_data, 39),
                line_height=46,
                max_lines=1,
                fill="#ffffff",
                stroke_width=1,
                reviewed_lines=reviewed[3 + 2 * index] if reviewed else None,
            )
        )
        counts.append(
            _draw_text(
                draw,
                card.body,
                box=(70, body_top, 650, body_bottom),
                font=_font(font_data, body_size),
                line_height=body_leading,
                max_lines=5,
                fill="#173b75",
                reviewed_lines=reviewed[4 + 2 * index] if reviewed else None,
            )
        )
    return tuple(counts)


def preflight_text_overlay_layout(
    copy: PosterCopy, *, use_reviewed_lines: bool = True
) -> tuple[str, tuple[int, ...]]:
    """Check fixed readable sizes and exact line budgets without a provider call."""
    data = _font_data()
    canvas = Image.new("RGB", _GEOMETRY, "white")
    lines = _paint(canvas, copy, data, use_reviewed_lines=use_reviewed_lines)
    return sha256(data).hexdigest(), tuple(len(part) for part in lines)


def render_exact_text_overlay(
    raw_bytes: bytes,
    case: ValidatedInfographicInput,
    copy: PosterCopy,
    *,
    use_reviewed_lines: bool = True,
) -> RenderedTextOverlay:
    """Make a distinct PNG; the original generated raster is never altered."""
    validate_poster_copy(case, copy)
    font_hash, expected_counts = preflight_text_overlay_layout(
        copy, use_reviewed_lines=use_reviewed_lines
    )
    if not raw_bytes or len(raw_bytes) > _MAX_RAW_BYTES:
        raise TextOverlayError("original poster is missing or too large")
    try:
        with Image.open(BytesIO(raw_bytes)) as opened:
            if (
                opened.format != "PNG"
                or opened.size != _GEOMETRY
                or opened.mode not in {"RGB", "RGBA"}
                or getattr(opened, "n_frames", 1) != 1
            ):
                raise TextOverlayError("original poster format or geometry is unsupported")
            opened.load()
            image = opened.convert("RGB")
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        if isinstance(exc, TextOverlayError):
            raise
        raise TextOverlayError("original poster cannot be decoded") from exc
    render_font_data = _font_data()
    if sha256(render_font_data).hexdigest() != font_hash:
        raise TextOverlayError("approved CJK font changed after preflight")
    lines = _paint(image, copy, render_font_data, use_reviewed_lines=use_reviewed_lines)
    counts = tuple(len(part) for part in lines)
    if counts != expected_counts:
        raise TextOverlayError("poster layout changed between preflight and render")
    expected_texts = (
        "小赛洞察",
        copy.title,
        copy.news_summary,
        *(value for card in copy.cards for value in (card.heading, card.body)),
    )
    if tuple("".join(part) for part in lines) != expected_texts:
        raise TextOverlayError("rendered poster lines differ from approved copy")
    output = BytesIO()
    image.save(output, format="PNG", optimize=False)
    body = output.getvalue()
    return RenderedTextOverlay(body, sha256(body).hexdigest(), font_hash, counts, lines)
