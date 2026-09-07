"""Lossless new-policy inline CSS compaction with pre-upload URL headroom.

The frozen V2 renderer remains unchanged. Only equivalent CSS spelling and exact
inherited-value duplicates are removed; no text, image, component or rule is dropped.
"""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser
from typing import Final

STRICT_LAYOUT_PROJECTION_VERSION: Final = "xiaosai-strict-inline-compact-v1"
STRICT_ESCAPED_UPLOAD_URL_MAX_CHARACTERS: Final = 256
_INHERITED: Final = frozenset(
    {
        "color",
        "font-size",
        "font-family",
        "font-weight",
        "line-height",
        "letter-spacing",
        "text-align",
    }
)


def _css_value(value: str) -> str:
    value = re.sub(
        r"#([0-9a-fA-F])\1([0-9a-fA-F])\2([0-9a-fA-F])\3\b",
        lambda match: "#" + match[1] + match[2] + match[3],
        value,
    )
    value = re.sub(r"(?<![\w.])0\.(\d+)", r".\1", value)
    return re.sub(r"\s*([,:;])\s*", r"\1", value).strip()


def _safe_inherited_duplicate(name: str, value: str) -> bool:
    # Equal relative specified values need not have equal computed values.
    if name in {"font-size", "letter-spacing"}:
        return bool(re.fullmatch(r"-?\d+(?:\.\d+)?px", value))
    if name == "line-height":
        return bool(re.fullmatch(r"\d+(?:\.\d+)?", value))
    if name == "font-weight":
        return value in {str(item) for item in range(100, 1000, 100)}
    if name == "color":
        return value.startswith(("#", "rgb(", "rgba("))
    return name in {"font-family", "text-align"} and value not in {
        "inherit",
        "initial",
        "unset",
        "revert",
        "match-parent",
    }


class _CompactInline(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.output: list[str] = []
        self.stack: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        original = self.get_starttag_text()
        if original is None:
            raise ValueError("strict inline start tag is missing")
        inherited = dict(self.stack[-1][1]) if self.stack else {}
        style = dict(attrs).get("style")
        if style is not None:
            declarations: list[str] = []
            seen: set[str] = set()
            for declaration in style.split(";"):
                if not declaration:
                    continue
                name, separator, value = declaration.partition(":")
                name, value = name.strip(), _css_value(value)
                if not separator or name in seen or name in {"font", "all"}:
                    raise ValueError("strict inline CSS shape is unsupported")
                seen.add(name)
                if not _safe_inherited_duplicate(name, value) or inherited.get(name) != value:
                    declarations.append(f"{name}:{value}")
                if name in _INHERITED:
                    inherited[name] = value
            replacement = 'style="' + escape(";".join(declarations), quote=True) + '"'
            original, count = re.subn(r'style="[^"]*"', lambda _match: replacement, original)
            if count != 1:
                raise ValueError("strict inline style attribute is ambiguous")
        self.output.append(original)
        if tag not in {"img", "br"}:
            self.stack.append((tag, inherited))

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack.pop()[0] != tag:
            raise ValueError("strict inline layout is unbalanced")
        self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.output.append(data)

    def handle_entityref(self, name: str) -> None:
        self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.output.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        raise ValueError("strict inline layout cannot contain comments")


def compact_strict_xiaosai_html(body_html: str) -> str:
    parser = _CompactInline()
    parser.feed(body_html)
    parser.close()
    if parser.stack:
        raise ValueError("strict inline layout is incomplete")
    return "".join(parser.output)


def validate_strict_upload_html_headroom(body_html: str, image_paths: tuple[str, ...]) -> None:
    if len(set(image_paths)) != len(image_paths):
        raise ValueError("strict upload image paths are duplicated")
    reserved = body_html
    for path in image_paths:
        needle = f'src="{path}"'
        if reserved.count(needle) != 1:
            raise ValueError("strict upload HTML binding is invalid")
        reserved = reserved.replace(
            needle, 'src="' + "x" * STRICT_ESCAPED_UPLOAD_URL_MAX_CHARACTERS + '"', 1
        )
    if len(reserved) > 19_999 or len(reserved.encode("utf-8")) > 1024 * 1024 - 1:
        raise ValueError("strict upload HTML has insufficient URL expansion headroom")


def strict_escaped_upload_url(url: str) -> str:
    escaped = escape(url, quote=True)
    if len(escaped) > STRICT_ESCAPED_UPLOAD_URL_MAX_CHARACTERS:
        raise ValueError("strict upload URL exceeds the frozen rendered bound")
    return escaped
