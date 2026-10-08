# ruff: noqa: RUF001
"""Keyword lists an operator maintains in the 运营后台, on top of the built-in rules.

- 关注词 (focus): an item whose title or summary contains one is ordered higher in its slot by
  `OPERATOR_FOCUS_BONUS`. It never makes an ineligible item eligible.
- 屏蔽词 (block): an item whose title or summary contains one is vetoed
  (`operator_blocked_term`).
- 文案禁用词 (copy banned): generated copy containing one fails the deterministic copy gate
  (`operator_banned_term`).

Matching is a plain case-insensitive substring test. The three lists are saved together as one
immutable version, and a content-slot run records the version it used, so every decision stays
explainable and replayable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

OPERATOR_FOCUS_BONUS = 0.08
OPERATOR_FOCUS_REASON = "operator_focus_term"
TERM_MAX_CHARS = 20
TERMS_PER_LIST = 200
# Blocking more than this share of last week's candidates needs an explicit confirmation.
WIDE_BLOCK_SHARE = 0.3

LIST_LABELS = {"focus": "关注词", "block": "屏蔽词", "copy_banned": "文案禁用词"}


class KeywordListError(ValueError):
    """A list broke a rule; the message is shown to the operator."""


def normalize_terms(values: Iterable[object], *, label: str) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise KeywordListError(f"{label}只能是文字")
        term = " ".join(raw.split())
        if not term:
            continue
        if len(term) > TERM_MAX_CHARS:
            raise KeywordListError(f"{label}「{term[:24]}」太长，每个词最多 {TERM_MAX_CHARS} 个字")
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        terms.append(term)
    if len(terms) > TERMS_PER_LIST:
        raise KeywordListError(f"{label}最多 {TERMS_PER_LIST} 个")
    return tuple(terms)


@dataclass(frozen=True, slots=True)
class OperatorKeywords:
    """One saved version of the three lists (`version` 0 means nothing saved yet)."""

    version: int
    focus: tuple[str, ...] = ()
    block: tuple[str, ...] = ()
    copy_banned: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"ops-kw-{self.version}"

    @property
    def is_empty(self) -> bool:
        return not (self.focus or self.block or self.copy_banned)


def build_keyword_lists(
    *, focus: Iterable[object], block: Iterable[object], copy_banned: Iterable[object]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    focus_terms = normalize_terms(focus, label=LIST_LABELS["focus"])
    block_terms = normalize_terms(block, label=LIST_LABELS["block"])
    banned_terms = normalize_terms(copy_banned, label=LIST_LABELS["copy_banned"])
    both = sorted(
        {term.casefold() for term in focus_terms} & {term.casefold() for term in block_terms}
    )
    if both:
        raise KeywordListError(f"这些词同时在关注词和屏蔽词里：{'、'.join(both)}")
    return focus_terms, block_terms, banned_terms


def matched_terms(text: str, terms: Iterable[str]) -> tuple[str, ...]:
    folded = text.casefold()
    return tuple(term for term in terms if term.casefold() in folded)


def keyword_diff(
    before: OperatorKeywords | None, after: OperatorKeywords
) -> dict[str, dict[str, list[str]]]:
    """Added and removed terms per list, for the audit log."""

    previous = before or OperatorKeywords(version=0)
    changes: dict[str, dict[str, list[str]]] = {}
    for name in ("focus", "block", "copy_banned"):
        old: tuple[str, ...] = getattr(previous, name)
        new: tuple[str, ...] = getattr(after, name)
        old_keys = {term.casefold() for term in old}
        new_keys = {term.casefold() for term in new}
        added = [term for term in new if term.casefold() not in old_keys]
        removed = [term for term in old if term.casefold() not in new_keys]
        if added or removed:
            changes[name] = {"added": added, "removed": removed}
    return changes


__all__ = [
    "LIST_LABELS",
    "OPERATOR_FOCUS_BONUS",
    "OPERATOR_FOCUS_REASON",
    "TERMS_PER_LIST",
    "TERM_MAX_CHARS",
    "WIDE_BLOCK_SHARE",
    "KeywordListError",
    "OperatorKeywords",
    "build_keyword_lists",
    "keyword_diff",
    "matched_terms",
    "normalize_terms",
]
