"""Versioned, lossless strict projections of the unchanged Xiaosai V2 renderer.

V1 keeps its literal spelling/inheritance transform. V2 additionally consolidates
neutral wrappers and shares bounded absolute typography between adjacent paragraphs.
Text, leaf markers, media, source links and visible emphasis are retained.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache
from html import escape
from html.parser import HTMLParser
from typing import Final, Literal

STRICT_LAYOUT_PROJECTION_VERSION: Final = "xiaosai-strict-inline-compact-v1"
STRICT_LAYOUT_PROJECTION_V2_VERSION: Final = "xiaosai-strict-inline-compact-v2"
StrictLayoutProjectionVersion = Literal[
    "xiaosai-strict-inline-compact-v1", "xiaosai-strict-inline-compact-v2"
]


def strict_layout_projection_version(value: object) -> StrictLayoutProjectionVersion:
    if type(value) is not str:
        raise ValueError("strict layout projection version is unsupported")
    if value == STRICT_LAYOUT_PROJECTION_VERSION:
        return STRICT_LAYOUT_PROJECTION_VERSION
    if value == STRICT_LAYOUT_PROJECTION_V2_VERSION:
        return STRICT_LAYOUT_PROJECTION_V2_VERSION
    raise ValueError("strict layout projection version is unsupported")


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


def compact_strict_xiaosai_html(
    body_html: str,
    *,
    version: StrictLayoutProjectionVersion = STRICT_LAYOUT_PROJECTION_VERSION,
) -> str:
    version = strict_layout_projection_version(version)
    parser = _CompactInline()
    parser.feed(body_html)
    parser.close()
    if parser.stack:
        raise ValueError("strict inline layout is incomplete")
    compact_v1 = "".join(parser.output)
    if version == STRICT_LAYOUT_PROJECTION_VERSION:
        return compact_v1
    return _compact_v2(compact_v1)


@dataclass(slots=True)
class _LayoutNode:
    tag: str
    attrs: dict[str, str | None]
    children: list[_LayoutNode | str] = field(default_factory=list)

    def css(self) -> dict[str, str]:
        return dict(
            declaration.split(":", 1)
            for declaration in (self.attrs.get("style") or "").split(";")
            if declaration
        )

    def set_css(self, css: dict[str, str]) -> None:
        if css:
            self.attrs["style"] = ";".join(f"{name}:{value}" for name, value in css.items())
        else:
            self.attrs.pop("style", None)


class _LayoutTree(HTMLParser):
    """Parse the already validated frozen renderer; never parse user-supplied CSS."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.root = _LayoutNode("root", {})
        self.stack = [self.root]
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.count += 1
        if (
            tag not in {"section", "p", "span", "a", "img", "br"}
            or len(attrs) != len(dict(attrs))
            or self.count > 4096
            or len(self.stack) > 32
        ):
            raise ValueError("strict compact-v2 renderer shape is unsupported")
        node = _LayoutNode(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {"img", "br"}:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        if len(self.stack) < 2 or self.stack.pop().tag != tag:
            raise ValueError("strict compact-v2 renderer is unbalanced")

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")


def _serialize_layout(node: _LayoutNode) -> str:
    # Double quotes delimit every valued attribute. Apostrophes need no entity here.
    attrs = "".join(
        " leaf"
        if name == "leaf" and value in {None, ""}
        else f' {name}="{escape(value or "", quote=False).replace(chr(34), "&quot;")}"'
        for name, value in node.attrs.items()
    )
    start = f"<{node.tag}{attrs}>" if node.tag != "root" else ""
    end = f"</{node.tag}>" if node.tag not in {"root", "img", "br"} else ""
    return (
        start
        + "".join(
            _serialize_layout(child) if isinstance(child, _LayoutNode) else child
            for child in node.children
        )
        + end
    )


def _merge_layout_wrappers(node: _LayoutNode) -> None:
    for child in node.children:
        if isinstance(child, _LayoutNode):
            _merge_layout_wrappers(child)
    if len(node.children) != 1 or not isinstance(node.children[0], _LayoutNode):
        return
    child = node.children[0]
    if (
        node.tag == "span"
        and set(node.attrs) == {"style"}
        and child.tag == "span"
        and child.attrs == {"leaf": ""}
    ):
        # Keep the sole leaf and its inline decoration, not two identical inline boxes.
        node.attrs["leaf"] = ""
        node.children = child.children
    elif node.tag == "section" and set(node.attrs) == set(child.attrs) == {"style"}:
        parent_css, child_css = node.css(), child.css()
        if (
            child.tag == "section"
            and parent_css == {"margin-top": "48px", "margin-bottom": "24px", "padding": "0 20px"}
            and child_css == {"display": "flex", "align-items": "center", "gap": "16px"}
        ):
            node.set_css({**parent_css, **child_css})
            node.children = child.children
        elif (
            child.tag == "p"
            and child_css.get("margin") == "0"
            and set(parent_css)
            in (
                {"flex", "border-left", "padding-left"},
                {"margin", "padding", "background", "border-left", "border-radius"},
            )
        ):
            # These frozen heading/introduction boxes have one zero-margin paragraph.
            # Preserve the outer margin and use the p's explicit zero for other margins.
            node.tag = "p"
            node.set_css(
                {
                    **parent_css,
                    **{
                        key: value
                        for key, value in child_css.items()
                        if key != "margin" or "margin" not in parent_css
                    },
                }
            )
            node.children = child.children


def _group_body_paragraphs(root: _LayoutNode) -> None:
    # Only direct adjacent body paragraphs under the frozen article root. The new
    # normal-flow section has no box styling, so existing p margins collapse exactly
    # as before. Never group headings, figures, links, flex items or mixed components.
    if len(root.children) != 1 or not isinstance(root.children[0], _LayoutNode):
        return
    article_root = root.children[0]
    if article_root.tag != "section" or article_root.css().get("max-width") != "677px":
        return
    output: list[_LayoutNode | str] = []
    pending: list[_LayoutNode] = []

    def flush() -> None:
        if len(pending) > 1:
            output.append(_LayoutNode("section", {}, list(pending)))
        else:
            output.extend(pending)
        pending.clear()

    for child in article_root.children:
        if (
            isinstance(child, _LayoutNode)
            and child.tag == "p"
            and set(child.attrs) == {"style"}
            and child.css()
            == {
                "font-size": "14px",
                "line-height": "1.9",
                "margin": "0 20px 18px",
                "text-align": "justify",
            }
        ):
            pending.append(child)
        else:
            flush()
            output.append(child)
    flush()
    article_root.children = output


_FACTORED_TYPOGRAPHY: Final = (
    "color",
    "font-size",
    "line-height",
    "text-align",
    "font-weight",
    "letter-spacing",
)


def _supports_typography_factoring(node: _LayoutNode) -> bool:
    """Relative metrics and CSS-wide/UA defaults are not an optimization input.

    Frozen Xiaosai uses absolute px fonts/spacing and unitless line heights. Leave
    unfamiliar future CSS unchanged instead of treating equal relative values as
    equal computed values, or resolving host defaults to invented absolute values.
    """
    for name, value in node.css().items():
        safe_value = (
            bool(re.fullmatch(r"-?(?:\d+(?:\.\d+)?|\.\d+)px", value))
            if name in {"font-size", "letter-spacing"}
            else _safe_inherited_duplicate(name, value)
        )
        if name in _FACTORED_TYPOGRAPHY and not safe_value:
            return False
        if name != "font-family" and re.search(
            r"(?:\b(?:inherit|initial|unset|revert|var|calc|currentcolor)\b|[\d.](?:em|rem|ex|ch|lh|rlh|cap|ic)\b|!)",
            value,
            re.IGNORECASE,
        ):
            return False
    if node.tag == "a" and "color" not in node.css():
        return False
    return all(
        _supports_typography_factoring(child)
        for child in node.children
        if isinstance(child, _LayoutNode)
    )


def _factor_typography(root: _LayoutNode, name: str) -> None:
    """Minimum serialized declaration cost on this bounded frozen-renderer tree.

    Every text-bearing/void node retains its specified effective value. None means
    the unknown host default: it cannot be restored by inventing an `initial` value.
    No rules are shared outside this article and no class/style sheet is introduced.
    """
    nodes: list[_LayoutNode] = []
    children: list[list[int]] = []
    required: dict[int, str | None] = {}
    forced: set[int] = set()
    values: set[str] = set()

    def visit(node: _LayoutNode, inherited: str | None) -> int:
        index = len(nodes)
        nodes.append(node)
        children.append([])
        value = node.css().get(name, inherited)
        if value is not None:
            values.add(value)
        if (
            any(isinstance(child, str) for child in node.children)
            or node.tag in {"img", "br"}
            or (
                name in {"font-size", "line-height"}
                and (
                    node.tag == "p"
                    or any(
                        isinstance(child, _LayoutNode) and child.tag in {"span", "a"}
                        for child in node.children
                    )
                )
            )
        ):
            required[index] = value
        if name == "color" and node.tag == "a":
            # UA :link/:visited has its own color. Inheritance alone cannot restore
            # the renderer's explicit link/underline color, even when parent matches.
            required[index] = value
            forced.add(index)
        for child in node.children:
            if isinstance(child, _LayoutNode):
                children[index].append(visit(child, value))
        return index

    visit(root, None)
    if len(values) > 32:
        raise ValueError("strict compact-v2 typography variants exceed the bound")
    candidates = sorted(values)

    @cache
    def best(index: int, inherited: str | None) -> tuple[int, str | None]:
        choices = [inherited, *(value for value in candidates if value != inherited)]
        if index in required:
            choices = [value for value in choices if value == required[index]]
        if nodes[index].tag == "root":
            choices = [inherited]
        winner = (10**9, inherited)
        for value in choices:
            cost = 0
            if value is not None and (value != inherited or index in forced):
                cost = len(name) + len(value) + 2
                if not (set(nodes[index].css()) - {name}):
                    cost += 8
            cost += sum(best(child, value)[0] for child in children[index])
            if cost < winner[0]:
                winner = cost, value
        return winner

    def apply(index: int, inherited: str | None) -> None:
        _, value = best(index, inherited)
        css = nodes[index].css()
        if value == inherited and index not in forced:
            css.pop(name, None)
        elif value is not None:
            css[name] = value
        for child in children[index]:
            apply(child, value)
        nodes[index].set_css(css)

    apply(0, None)


def _shorten_layout_values(node: _LayoutNode) -> None:
    css = node.css()
    if (
        css.get("margin-top") == "48px"
        and css.get("margin-bottom") == "24px"
        and not (set(css) & {"margin", "margin-left", "margin-right"})
    ):
        css = {
            key: value for key, value in css.items() if key not in {"margin-top", "margin-bottom"}
        }
        css = {"margin": "48px 0 24px", **css}
    if (
        node.tag == "span"
        and css.get("padding-bottom") == "1px"
        and not (set(css) & {"padding", "padding-top", "padding-left", "padding-right"})
    ):
        css = {key: "0 0 1px" if key == "padding-bottom" else value for key, value in css.items()}
        css = {"padding" if key == "padding-bottom" else key: value for key, value in css.items()}
    for name, value in css.items():
        if name in {"border", "border-left", "border-bottom", "border-top"}:
            css[name] = re.sub(r"^([\d.]+px) solid (#[0-9a-fA-F]{3,6})$", r"\1 solid\2", value)
        elif name == "background" and value == "linear-gradient(to right,#0D57C8,#22D7D6)":
            css[name] = "linear-gradient(90deg,#0D57C8,#22D7D6)"
    node.set_css(css)
    for child in node.children:
        if isinstance(child, _LayoutNode):
            _shorten_layout_values(child)


def _compact_v2(compact_v1: str) -> str:
    if len(compact_v1.encode("utf-8")) >= 1024 * 1024:
        raise ValueError("strict compact-v2 renderer exceeds the bound")
    tree = _LayoutTree()
    tree.feed(compact_v1)
    tree.close()
    if len(tree.stack) != 1:
        raise ValueError("strict compact-v2 renderer is incomplete")
    if not _supports_typography_factoring(tree.root):
        return compact_v1
    _merge_layout_wrappers(tree.root)
    _group_body_paragraphs(tree.root)
    for name in _FACTORED_TYPOGRAPHY:
        _factor_typography(tree.root, name)
    _shorten_layout_values(tree.root)
    return _serialize_layout(tree.root)


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
