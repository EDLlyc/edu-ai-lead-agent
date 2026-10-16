"""Editorial phrase lists the copy gate refuses, and the lists an operator may maintain.

营销承诺 and 焦虑话术 start as the lists below. An operator can add or remove those words in the
console; a content-slot run records the version it used. The safety lists (prompt injection,
unsafe images, operating WeChat for the reader) stay in code and are not editable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.domain.operator_keywords import KeywordListError, normalize_terms

DEFAULT_MARKETING: tuple[str, ...] = (
    "保证提分",
    "确保提分",
    "绝对领先",
    "行业第一",
    "第一品牌",
    "领导品牌",
    "百分之百",
    "100%",
    "保送资格",
    "必然成功",
    "最权威",
)
DEFAULT_ANXIETY: tuple[str, ...] = (
    "再不学就晚了",
    "输在起跑线",
    "注定落后",
    "被时代淘汰",
    "落后别人家孩子",
    "错过就来不及",
)

# Shown in the console and still enforced from code. An operator save cannot change them.
LOCKED_PHRASE_LISTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "提示词注入",
        ("忽略之前的指令", "忽略系统提示", "system prompt", "developer message", "越过审核"),
    ),
    (
        "不安全画面",
        ("未成年人真人正脸", "儿童真实正脸", "学生身份证", "裸露儿童", "血腥", "武器伤害"),
    ),
    ("代操作微信", ("自动发布", "代发朋友圈", "登录微信", "点击发布", "发布到朋友圈")),
)


@dataclass(frozen=True, slots=True)
class BuiltinPhrases:
    """One saved version. ``version`` 0 means the code defaults, nothing saved yet."""

    version: int
    marketing: tuple[str, ...]
    anxiety: tuple[str, ...]


def parse_builtin_phrases(
    *, marketing: Iterable[object], anxiety: Iterable[object]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        marketing_terms = normalize_terms(marketing, label="营销承诺")
        anxiety_terms = normalize_terms(anxiety, label="焦虑话术")
    except KeywordListError:
        raise
    return marketing_terms, anxiety_terms


__all__ = [
    "DEFAULT_ANXIETY",
    "DEFAULT_MARKETING",
    "LOCKED_PHRASE_LISTS",
    "BuiltinPhrases",
    "parse_builtin_phrases",
]
