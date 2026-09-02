"""Build the reviewed, provider-free grounded IP retrieval seed artifacts."""

# ruff: noqa: RUF001 - Chinese evaluation queries intentionally use Chinese punctuation.

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .assets import build_safe_asset_snapshot
from .dataset import DEFAULT_ASSETS_PATH, DEFAULT_QUERIES_PATH, DEFAULT_SEED_PATH
from .models import (
    EVALUATOR_VERSION,
    QUERY_SCHEMA_VERSION,
    RUBRIC_VERSION,
    SEED_SCHEMA_VERSION,
    GroundedQuery,
    GroundedQueryCategory,
    GroundedRelevanceGrade,
    GroundedSeedMatrix,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST_PATH = REPO_ROOT / "private/brand-materials/visual-assets.manifest.json"

# Visual-review order from the approved 41-image contact sheets. Only safe public refs are kept.
REF_BY_INDEX = (
    "fb10f2470cff475b",
    "91d8302fbf315a6e",
    "4c992d7cd76219c7",
    "08748e267dee9298",
    "e48a22e08f8656ca",
    "3dd6220e183175d7",
    "ca2e24107433e6c0",
    "0121c4aed51e0312",
    "029ee20bb1ff26c3",
    "16c48b11da0dbb7f",
    "079e5e02b1769f2a",
    "a283092c9925185c",
    "79a03fd2f16a3d65",
    "855ae0641e07fa64",
    "c8fab17a7a9a2b0b",
    "12086739c0e77148",
    "33586a916bbbfbf1",
    "46c0563d628633f0",
    "b9c3b0d98233e3cc",
    "1bb84f2abb140b8f",
    "a6e127fcd6a16314",
    "5c2a29bbec16ca4f",
    "bff22728598b948f",
    "bab27fe77a8edff4",
    "948f9af52f3bfadb",
    "be4694535c6259cf",
    "89dc2182a28f031f",
    "3c073cebb5d756c3",
    "9f91d951cce9412e",
    "cd6c32292792352f",
    "b680c2412f0672c6",
    "c3b8b212acd4f34a",
    "e533d4b5c0547c0d",
    "6954687fbdae4366",
    "c5ac14daf0b33357",
    "f2bcf802196b4bd8",
    "09c8fd9470cb5502",
    "471bf408e572a3e0",
    "80d316bf7d4b753a",
    "68dd45e5ac814f20",
    "fe2cd5da478b39d5",
)


def _refs(*indices: int) -> frozenset[str]:
    return frozenset(REF_BY_INDEX[index - 1] for index in indices)


def _range_refs(start: int, end: int) -> frozenset[str]:
    return _refs(*range(start, end + 1))


XIAO_IDENTITY = _range_refs(1, 7)
SAI_IDENTITY = _range_refs(8, 15)
DUO = _refs(19, 20, 21, 22, 29, 37, 38, 39)
XIAO_SOLO_ACTION = _refs(17, 18, 23, 24, 25, 26, 28)
SAI_SOLO_ACTION = _refs(16, 27, 30, 31, 32, 33, 34, 35, 36, 40, 41)
XIAO_SOLO = XIAO_IDENTITY | XIAO_SOLO_ACTION
SAI_SOLO = SAI_IDENTITY | SAI_SOLO_ACTION
ALL_SOLO = XIAO_SOLO | SAI_SOLO
TRANSPARENT = _refs(
    1,
    2,
    8,
    10,
    13,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    23,
    24,
    25,
    26,
    27,
    28,
    29,
    31,
    32,
    33,
    34,
    35,
    36,
    37,
    38,
    40,
    41,
)
LANDSCAPE = _refs(30, 37, 38, 39)
PORTRAIT = _refs(3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 31, 32, 33, 34)
SQUARE = frozenset(REF_BY_INDEX) - LANDSCAPE - PORTRAIT


@dataclass(frozen=True, slots=True)
class _AuthoredQuery:
    query_ref: str
    category: GroundedQueryCategory
    split: Literal["dev", "holdout"]
    text: str
    expected_answer_kind: Literal["has_relevant", "no_answer"]
    grade3: frozenset[str]
    grade2: frozenset[str]
    grade1: frozenset[str]

    def __post_init__(self) -> None:
        groups = (self.grade3, self.grade2, self.grade1)
        if any(left & right for index, left in enumerate(groups) for right in groups[index + 1 :]):
            raise ValueError(f"authored grades overlap for {self.query_ref}")
        if not set().union(*groups).issubset(REF_BY_INDEX):
            raise ValueError(f"authored query uses an unknown asset for {self.query_ref}")
        if self.expected_answer_kind == "no_answer" and (self.grade3 or self.grade2):
            raise ValueError(f"no-answer authored query has a usable asset: {self.query_ref}")
        if self.expected_answer_kind == "has_relevant" and not (self.grade3 or self.grade2):
            raise ValueError(f"answerable authored query has no usable asset: {self.query_ref}")


def _q(
    category: GroundedQueryCategory,
    ordinal: int,
    text: str,
    *,
    grade3: Iterable[str] = (),
    grade2: Iterable[str] = (),
    grade1: Iterable[str] = (),
    holdout: bool = False,
    no_answer: bool = False,
) -> _AuthoredQuery:
    return _AuthoredQuery(
        query_ref=f"{category.value.replace('_', '-')}-{ordinal:02d}",
        category=category,
        split="holdout" if holdout else "dev",
        text=text,
        expected_answer_kind="no_answer" if no_answer else "has_relevant",
        grade3=frozenset(grade3),
        grade2=frozenset(grade2),
        grade1=frozenset(grade1),
    )


def authored_queries() -> tuple[_AuthoredQuery, ...]:
    c = GroundedQueryCategory
    queries = (
        # Character — 10
        _q(
            c.CHARACTER,
            1,
            "只要小赛单人形象",
            grade3=(XIAO_SOLO - _refs(1)),
            grade2=_refs(1),
            grade1=DUO,
        ),
        _q(
            c.CHARACTER,
            2,
            "只看赛先生单人形象",
            grade3=(SAI_SOLO - _refs(8, 30)),
            grade2=_refs(8, 30),
            grade1=DUO,
        ),
        _q(c.CHARACTER, 3, "小赛和赛先生同框", grade3=DUO, grade1=_refs(30)),
        _q(c.CHARACTER, 4, "两位IP一起出现", grade3=DUO, grade2=_refs(30)),
        _q(
            c.CHARACTER,
            5,
            "小赛头像",
            grade3=_refs(1),
            grade2=_refs(2, 3, 4, 5, 6, 7),
            holdout=True,
        ),
        _q(c.CHARACTER, 6, "赛先生头像", grade3=_refs(8), grade2=_refs(9, 10, 11, 12, 13, 14, 15)),
        _q(
            c.CHARACTER,
            7,
            "小赛完整全身",
            grade3=(XIAO_SOLO - _refs(1)),
            grade2=_refs(19, 20, 22, 29, 37, 38, 39),
        ),
        _q(
            c.CHARACTER,
            8,
            "赛先生完整全身",
            grade3=(SAI_SOLO - _refs(8, 30)),
            grade2=_refs(19, 20, 22, 29, 30, 37, 38, 39),
        ),
        _q(
            c.CHARACTER,
            9,
            "只出现一个角色，不要同框",
            grade3=(ALL_SOLO - _refs(30)),
            grade1=_refs(30),
        ),
        _q(
            c.CHARACTER,
            10,
            "双角色横版画面",
            grade3=_refs(37, 38, 39),
            grade2=_refs(19, 20, 22, 29),
            grade1=_refs(21),
            holdout=True,
        ),
        # Asset type — 8
        _q(
            c.ASSET_TYPE,
            1,
            "找头像或圆形IP图标",
            grade3=_refs(1, 8),
            grade2=_refs(2, 3, 5, 7, 9, 10, 11, 12, 14, 15),
        ),
        _q(
            c.ASSET_TYPE,
            2,
            "找完整角色全身图",
            grade3=((ALL_SOLO - _refs(1, 8, 30)) | _refs(37, 38)),
            grade2=_refs(19, 20, 22, 29, 30, 39),
        ),
        _q(
            c.ASSET_TYPE,
            3,
            "找有明确动作的角色插画",
            grade3=_range_refs(16, 41),
            grade2=(_range_refs(2, 15) - _refs(8)),
            grade1=_refs(1, 8),
        ),
        _q(
            c.ASSET_TYPE,
            4,
            "品牌IP标志图",
            grade3=_refs(1, 8),
            grade2=_refs(2, 3, 5, 7, 9, 11, 14),
            holdout=True,
        ),
        _q(
            c.ASSET_TYPE,
            5,
            "找一张完整场景插画",
            grade3=_refs(19, 21, 22, 29, 39),
            grade2=_refs(16, 27, 30, 36, 37, 38),
            grade1=_refs(20, 24, 35),
        ),
        _q(
            c.ASSET_TYPE,
            6,
            "适合作为海报主视觉的画面",
            grade3=_refs(13, 30, 37, 38, 39),
            grade2=_refs(19, 21, 22, 29, 32, 33, 34, 35),
        ),
        _q(
            c.ASSET_TYPE,
            7,
            "公众号正文里的IP插图",
            grade3=_refs(19, 20, 21, 22, 27, 29, 36, 39),
            grade2=_refs(16, 23, 24, 25, 26, 28, 35, 37, 38, 40, 41),
        ),
        _q(
            c.ASSET_TYPE,
            8,
            "适合演示文稿封面的图片",
            grade3=_refs(30, 37, 38, 39),
            grade2=_refs(13, 19, 21, 22, 29, 32, 33, 34, 35),
            holdout=True,
        ),
        # Emotion — 8
        _q(
            c.EMOTION,
            1,
            "开心微笑的小赛",
            grade3=_refs(2, 3, 7, 23),
            grade2=_refs(4, 5, 6, 17, 18, 24, 28),
            grade1=_refs(25, 26),
        ),
        _q(
            c.EMOTION,
            2,
            "专注思考的角色",
            grade3=_refs(20, 25, 26),
            grade2=_refs(7, 12, 24, 27, 36),
            grade1=_refs(11, 22, 28, 41),
        ),
        _q(
            c.EMOTION,
            3,
            "疑惑又好奇的小赛",
            grade3=_refs(25, 26),
            grade2=_refs(17, 24),
            grade1=_refs(7, 20),
        ),
        _q(
            c.EMOTION,
            4,
            "自信专业的赛先生",
            grade3=_refs(9, 10, 11, 12, 14, 15, 30, 31),
            grade2=_refs(13, 16, 27, 32, 33, 34, 35, 36, 40, 41),
            holdout=True,
        ),
        _q(
            c.EMOTION,
            5,
            "友好欢迎的角色",
            grade3=_refs(3, 23, 31, 40),
            grade2=_refs(2, 11, 14, 18, 33, 41),
        ),
        _q(
            c.EMOTION,
            6,
            "严谨认真的科学家形象",
            grade3=_refs(9, 10, 11, 12, 15, 27, 30, 36),
            grade2=_refs(16, 24, 32, 33, 34, 35, 41),
        ),
        _q(
            c.EMOTION,
            7,
            "充满探索欲的角色",
            grade3=_refs(12, 16, 24, 27, 32, 33, 34, 35, 36, 39),
            grade2=_refs(9, 10, 11, 15, 19, 21, 22, 29, 37, 38),
        ),
        _q(
            c.EMOTION,
            8,
            "两位角色开心结伴",
            grade3=_refs(37, 38, 39),
            grade2=_refs(19, 22, 29),
            grade1=_refs(20, 21),
            holdout=True,
        ),
        # Action — 12
        _q(
            c.ACTION,
            1,
            "角色指向上方讲解",
            grade3=_refs(4, 11, 14, 18, 31),
            grade2=_refs(6, 23, 28, 40, 41),
        ),
        _q(
            c.ACTION,
            2,
            "挥手打招呼",
            grade3=_refs(3, 23, 31, 33, 40),
            grade2=_refs(2, 11, 14, 18, 41),
        ),
        _q(
            c.ACTION,
            3,
            "两位角色一起看书",
            grade3=_refs(19, 21, 29),
            grade2=_refs(20, 27),
            grade1=_refs(22),
        ),
        _q(
            c.ACTION,
            4,
            "角色正在讨论交流",
            grade3=_refs(20, 22, 28, 41),
            grade2=_refs(37, 38, 39),
            grade1=_refs(19, 29),
        ),
        _q(
            c.ACTION,
            5,
            "小赛提出问题",
            grade3=_refs(25, 26),
            grade2=_refs(17, 20, 24),
            grade1=_refs(7),
        ),
        _q(
            c.ACTION,
            6,
            "使用工具观察实验",
            grade3=_refs(9, 12, 16, 24, 27, 36),
            grade2=_refs(10, 11, 15, 22, 35),
            holdout=True,
        ),
        _q(
            c.ACTION,
            7,
            "赛先生在用显微镜",
            grade3=_refs(36),
            grade2=_refs(12, 27),
            grade1=_refs(9, 16, 24),
        ),
        _q(
            c.ACTION,
            8,
            "宇航员在太空探索",
            grade3=_refs(32, 33, 34, 39),
            grade2=_refs(16, 35),
            grade1=_refs(13, 15),
        ),
        _q(c.ACTION, 9, "两位角色一起奔跑", grade3=_refs(37, 38, 39), grade1=_refs(19, 22, 29)),
        _q(
            c.ACTION,
            10,
            "角色外出探险",
            grade3=_refs(15, 32, 33, 34, 35, 39),
            grade2=_refs(16, 24, 37, 38),
        ),
        _q(
            c.ACTION,
            11,
            "团队协作向前",
            grade3=_refs(37, 38, 39),
            grade2=_refs(22, 30),
            grade1=_refs(19, 20, 29),
        ),
        _q(
            c.ACTION,
            12,
            "手里拿着科技设备",
            grade3=_refs(9, 10, 11, 15, 24),
            grade2=_refs(6, 22, 28, 31, 41),
            holdout=True,
        ),
        # Scene — 12
        _q(
            c.SCENE,
            1,
            "小赛和赛先生在空间站",
            grade3=_refs(39),
            grade2=_refs(32, 33, 34),
            grade1=_refs(16, 35, 37, 38),
        ),
        _q(
            c.SCENE,
            2,
            "太空和天文主题",
            grade3=_refs(16, 32, 33, 34, 39),
            grade2=_refs(35),
            grade1=_refs(13, 15),
        ),
        _q(
            c.SCENE,
            3,
            "科学实验室场景",
            grade3=_refs(9, 11, 12, 22, 24, 36),
            grade2=_refs(10, 15, 28, 41),
            grade1=_refs(16, 25, 26),
        ),
        _q(
            c.SCENE,
            4,
            "课堂教学场景",
            grade3=_refs(3, 4, 6, 11, 14, 18, 23, 28, 31, 40, 41),
            grade2=_refs(17, 20, 22, 25, 26),
        ),
        _q(
            c.SCENE,
            5,
            "阅读和书本主题",
            grade3=_refs(19, 21, 27, 29),
            grade2=_refs(20),
            grade1=_refs(22, 25, 26),
        ),
        _q(
            c.SCENE,
            6,
            "时光机里的阅读画面",
            grade3=_refs(19, 29),
            grade2=_refs(21),
            grade1=_refs(20, 27),
            holdout=True,
        ),
        _q(
            c.SCENE,
            7,
            "人工智能与机器人实验",
            grade3=_refs(6, 10, 11, 15, 22, 24, 28, 41),
            grade2=_refs(9, 12, 36),
        ),
        _q(
            c.SCENE,
            8,
            "专业团队合影",
            grade3=_refs(30),
            grade2=_refs(37, 38),
            grade1=_refs(20, 22, 39),
        ),
        _q(
            c.SCENE,
            9,
            "伙伴携手奔跑的户外感画面",
            grade3=_refs(37, 38),
            grade2=_refs(39),
            grade1=_refs(35),
        ),
        _q(
            c.SCENE,
            10,
            "观察植物的科学场景",
            grade3=_refs(12),
            grade2=_refs(36),
            grade1=_refs(9, 24, 27, 35),
        ),
        _q(
            c.SCENE,
            11,
            "显微镜实验场景",
            grade3=_refs(36),
            grade2=_refs(12),
            grade1=_refs(9, 22, 24),
        ),
        _q(
            c.SCENE,
            12,
            "纯角色素材，不要完整背景",
            grade3=TRANSPARENT,
            grade2=_refs(3, 4, 5, 6, 7, 9, 11, 12, 14, 15),
            grade1=_refs(30, 39),
            holdout=True,
        ),
        # Intended use — 10
        _q(
            c.INTENDED_USE,
            1,
            "社群欢迎通知配图",
            grade3=_refs(3, 23, 31, 40),
            grade2=_refs(2, 11, 14, 18, 37, 38),
        ),
        _q(
            c.INTENDED_USE,
            2,
            "公众号科学文章正文插图",
            grade3=_refs(19, 21, 22, 27, 29, 36, 39),
            grade2=_refs(16, 20, 24, 25, 26, 35, 37, 38),
        ),
        _q(
            c.INTENDED_USE,
            3,
            "文章中的思考提问小节",
            grade3=_refs(20, 25, 26),
            grade2=_refs(7, 17, 22, 24, 27),
        ),
        _q(
            c.INTENDED_USE,
            4,
            "课程开场欢迎页",
            grade3=_refs(11, 14, 18, 23, 31, 40),
            grade2=_refs(3, 4, 6, 28, 41),
        ),
        _q(
            c.INTENDED_USE,
            5,
            "人工智能主题宣传图",
            grade3=_refs(6, 10, 11, 15, 22, 24, 28, 41),
            grade2=_refs(9, 12, 30, 36),
            holdout=True,
        ),
        _q(
            c.INTENDED_USE,
            6,
            "天文科普文章配图",
            grade3=_refs(16, 32, 33, 34, 39),
            grade2=_refs(35),
        ),
        _q(
            c.INTENDED_USE,
            7,
            "团队合作活动海报",
            grade3=_refs(30, 37, 38, 39),
            grade2=_refs(20, 22, 29),
        ),
        _q(
            c.INTENDED_USE,
            8,
            "社交账号头像",
            grade3=_refs(1, 8),
            grade2=_refs(2, 3, 5, 7, 9, 10, 11, 12, 14),
        ),
        _q(
            c.INTENDED_USE,
            9,
            "可叠加到排版中的角色元素",
            grade3=TRANSPARENT,
            grade2=_refs(3, 4, 5, 6, 7, 9, 11, 12, 14, 15),
            grade1=_refs(30, 39),
        ),
        _q(
            c.INTENDED_USE,
            10,
            "专业汇报PPT封面",
            grade3=_refs(30, 39),
            grade2=_refs(11, 15, 22, 37, 38),
            grade1=_refs(13, 19, 21, 29),
            holdout=True,
        ),
        # Transparent background — 8
        _q(
            c.TRANSPARENT_BACKGROUND,
            1,
            "小赛透明底素材",
            grade3=(TRANSPARENT & XIAO_SOLO),
            grade2=_refs(3, 4, 5, 6, 7),
            grade1=(TRANSPARENT & DUO),
        ),
        _q(
            c.TRANSPARENT_BACKGROUND,
            2,
            "赛先生透明背景角色图",
            grade3=(TRANSPARENT & SAI_SOLO),
            grade2=_refs(9, 11, 12, 14, 15),
            grade1=(TRANSPARENT & DUO),
        ),
        _q(
            c.TRANSPARENT_BACKGROUND,
            3,
            "两位IP透明底同框",
            grade3=(TRANSPARENT & DUO),
            grade2=_refs(39),
        ),
        _q(
            c.TRANSPARENT_BACKGROUND,
            4,
            "透明底全身动作",
            grade3=(TRANSPARENT - _refs(1, 8)),
            grade2=_refs(3, 4, 5, 6, 7, 9, 11, 12, 14, 15),
            grade1=_refs(30, 39),
        ),
        _q(
            c.TRANSPARENT_BACKGROUND,
            5,
            "方形透明背景IP图",
            grade3=(TRANSPARENT & SQUARE),
            grade2=(TRANSPARENT & PORTRAIT),
            grade1=_refs(39),
        ),
        _q(
            c.TRANSPARENT_BACKGROUND,
            6,
            "无背景的教学动作",
            grade3=_refs(18, 23, 28, 31, 40, 41),
            grade2=_refs(16, 17, 20, 22, 25, 26, 36),
            grade1=_refs(4, 6, 11, 14),
        ),
        _q(
            c.TRANSPARENT_BACKGROUND,
            7,
            "透明底科学探索角色",
            grade3=_refs(16, 24, 27, 32, 33, 34, 35, 36),
            grade2=_refs(10, 19, 21, 22, 29, 37, 38),
        ),
        _q(
            c.TRANSPARENT_BACKGROUND,
            8,
            "透明底横版双角色",
            grade3=_refs(37, 38),
            grade2=_refs(19, 20, 22, 29),
            grade1=_refs(39),
            holdout=True,
        ),
        # Combined constraints — 16
        _q(
            c.COMBINED_CONSTRAINTS,
            1,
            "小赛开心挥手的透明底图",
            grade3=_refs(2, 23),
            grade2=_refs(18),
            grade1=_refs(3, 7, 28),
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            2,
            "赛先生透明底教学动作",
            grade3=_refs(31, 40, 41),
            grade2=_refs(16, 27, 36),
            grade1=_refs(11, 14),
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            3,
            "双角色在空间站的横版场景",
            grade3=_refs(39),
            grade2=_refs(37, 38),
            grade1=_refs(32, 33, 34),
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            4,
            "两位角色透明底一起看书",
            grade3=_refs(19, 29),
            grade2=_refs(21),
            grade1=_refs(20, 27),
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            5,
            "赛先生透明底显微镜实验",
            grade3=_refs(36),
            grade2=_refs(12, 27),
            grade1=_refs(9, 24),
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            6,
            "小赛透明底疑问表情",
            grade3=_refs(25, 26),
            grade2=_refs(17),
            grade1=_refs(7, 20),
            holdout=True,
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            7,
            "两位IP透明底携手奔跑",
            grade3=_refs(37, 38),
            grade2=_refs(39),
            grade1=_refs(22),
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            8,
            "小赛竖版AI科技形象",
            grade3=_refs(6),
            grade2=_refs(3, 4, 5),
            grade1=_refs(10, 11, 15),
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            9,
            "赛先生透明底宇航员",
            grade3=_refs(32, 33, 34),
            grade2=_refs(16, 35),
            grade1=_refs(39),
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            10,
            "赛先生专业团队横版",
            grade3=_refs(30),
            grade2=_refs(37, 38),
            grade1=_refs(9, 10, 11, 15),
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            11,
            "赛先生透明底拿地图探险",
            grade3=_refs(35),
            grade2=_refs(32, 33, 34),
            grade1=_refs(15, 16),
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            12,
            "小赛和赛先生透明底讨论",
            grade3=_refs(20, 22),
            grade2=_refs(37, 38),
            grade1=_refs(19, 29, 41),
            holdout=True,
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            13,
            "小赛透明底向上指",
            grade3=_refs(18),
            grade2=_refs(23, 28),
            grade1=_refs(4, 6),
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            14,
            "赛先生透明底欢迎动作",
            grade3=_refs(31, 40),
            grade2=_refs(33, 41),
            grade1=_refs(11, 14),
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            15,
            "双角色横版团队合作",
            grade3=_refs(37, 38, 39),
            grade2=_refs(20, 22, 29),
            grade1=_refs(19, 21),
        ),
        _q(
            c.COMBINED_CONSTRAINTS,
            16,
            "有完整背景的太空双角色",
            grade3=_refs(39),
            grade2=_refs(19, 29),
            grade1=_refs(32, 33, 34, 37, 38),
            holdout=True,
        ),
        # Paraphrase — 6
        _q(
            c.PARAPHRASE,
            1,
            "蓝白色机器人猫头鹰",
            grade3=(XIAO_SOLO - _refs(1)),
            grade2=(DUO - _refs(21)),
            grade1=_refs(1),
        ),
        _q(
            c.PARAPHRASE,
            2,
            "戴橙色护目镜的博士猫头鹰",
            grade3=(SAI_SOLO - _refs(8)),
            grade2=DUO,
            grade1=_refs(8),
        ),
        _q(c.PARAPHRASE, 3, "两个猫头鹰伙伴的合照", grade3=DUO, grade2=_refs(30)),
        _q(
            c.PARAPHRASE,
            4,
            "太空舱里两位伙伴一起跑",
            grade3=_refs(39),
            grade2=_refs(37, 38),
            grade1=_refs(32, 33, 34),
        ),
        _q(c.PARAPHRASE, 5, "穿越时空一起读书", grade3=_refs(19, 21, 29), grade2=_refs(20, 27)),
        _q(
            c.PARAPHRASE,
            6,
            "拿放大镜趴在书本旁研究",
            grade3=_refs(27),
            grade2=_refs(12, 36),
            grade1=_refs(9, 24),
            holdout=True,
        ),
        # Noisy aliases — 4
        _q(
            c.NOISY_ALIAS,
            1,
            "小塞的图片",
            grade3=(XIAO_SOLO - _refs(1)),
            grade2=DUO,
            grade1=_refs(1),
        ),
        _q(
            c.NOISY_ALIAS,
            2,
            "赛生先 科学家",
            grade3=(SAI_SOLO - _refs(8)),
            grade2=DUO,
            grade1=_refs(8),
        ),
        _q(c.NOISY_ALIAS, 3, "小赛+赛先生 合照", grade3=DUO, grade2=_refs(30)),
        _q(
            c.NOISY_ALIAS,
            4,
            "Dr.S 博士形象",
            grade3=(SAI_SOLO - _refs(8)),
            grade2=DUO,
            grade1=_refs(8),
            holdout=True,
        ),
        # No answer — 6
        _q(c.NO_ANSWER, 1, "第三个熊猫IP角色", no_answer=True),
        _q(c.NO_ANSWER, 2, "小赛和赛先生在深海潜水", grade1=_refs(39), no_answer=True),
        _q(c.NO_ANSWER, 3, "角色在厨房做饭", no_answer=True, holdout=True),
        _q(c.NO_ANSWER, 4, "两位角色打篮球", grade1=_refs(37, 38, 39), no_answer=True),
        _q(c.NO_ANSWER, 5, "红色愤怒表情包", grade1=_refs(13, 15, 26), no_answer=True),
        _q(
            c.NO_ANSWER,
            6,
            "办公室会议桌旁开会",
            grade1=_refs(20, 22, 30),
            no_answer=True,
            holdout=True,
        ),
    )
    if len(queries) != 100:
        raise ValueError("grounded authoring must define exactly 100 queries")
    return tuple(sorted(queries, key=lambda item: item.query_ref))


def build_query_records() -> tuple[GroundedQuery, ...]:
    return tuple(
        GroundedQuery(
            schema_version=QUERY_SCHEMA_VERSION,
            query_ref=item.query_ref,
            category=item.category,
            split=item.split,
            query=item.text,
            expected_answer_kind=item.expected_answer_kind,
        )
        for item in authored_queries()
    )


def build_seed_records() -> tuple[GroundedSeedMatrix, ...]:
    records: list[GroundedSeedMatrix] = []
    for item in authored_queries():
        grades = tuple(
            GroundedRelevanceGrade(
                catalog_ref=ref,
                grade=(
                    3
                    if ref in item.grade3
                    else 2
                    if ref in item.grade2
                    else 1
                    if ref in item.grade1
                    else 0
                ),
            )
            for ref in sorted(REF_BY_INDEX)
        )
        records.append(
            GroundedSeedMatrix(
                schema_version=SEED_SCHEMA_VERSION,
                query_ref=item.query_ref,
                label_source="codex_seed",
                evaluator_version=EVALUATOR_VERSION,
                rubric_version=RUBRIC_VERSION,
                grades=grades,
            )
        )
    return tuple(records)


def _jsonl(records: Iterable[GroundedQuery | GroundedSeedMatrix]) -> str:
    return "".join(
        json.dumps(
            record.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for record in records
    )


def _assets_json(manifest_path: Path) -> str:
    snapshot = build_safe_asset_snapshot(manifest_path)
    if {asset.catalog_ref for asset in snapshot.assets} != set(REF_BY_INDEX):
        raise ValueError("visual-review public refs do not match the approved manifest")
    return (
        json.dumps(
            snapshot.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


def _artifacts(manifest_path: Path) -> dict[Path, str]:
    return {
        DEFAULT_ASSETS_PATH: _assets_json(manifest_path),
        DEFAULT_QUERIES_PATH: _jsonl(build_query_records()),
        DEFAULT_SEED_PATH: _jsonl(build_seed_records()),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    args = parser.parse_args(argv)
    artifacts = _artifacts(args.manifest)
    if args.write:
        for path, body in artifacts.items():
            path.write_text(body, encoding="utf-8")
        print("Grounded IP retrieval authoring artifacts written: 100 queries, 4,100 grades")
        return 0
    drifted = [
        path.name
        for path, body in artifacts.items()
        if not path.is_file() or path.read_text(encoding="utf-8") != body
    ]
    if drifted:
        print("Grounded IP retrieval authoring artifacts drifted: " + ", ".join(drifted))
        return 1
    print("Grounded IP retrieval authoring artifacts match: 100 queries, 4,100 grades")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
