"""Closed vocabularies, the labelling prompt, strict output validation and scoring.

The fields are the ones a person decides when a brand image is added to the private catalog
(`scripts/build_brand_asset_manifest.py` and `visual-assets.metadata.json`): whether it is an
identity sheet or an action image, which characters it shows, and for action images the main
prop, the poses and the scene tags. Prop ids are the selector v3 vocabulary
(`SUBJECT_ALLOWED_PROPS`); pose and scene ids are the ones the catalog uses.
"""

# ruff: noqa: RUF001, E501

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CHARACTERS = ("xiao-sai", "sai-xiansheng")
PROPS = (
    "astronaut",
    "book",
    "brand_team",
    "detector",
    "explorer",
    "microscope",
    "specimen",
    "telescope",
    "time_machine",
)
POSES = (
    "astronaut",
    "discover",
    "discuss",
    "explore",
    "microscope",
    "observe",
    "point",
    "question",
    "read",
    "run",
    "teach",
    "think",
    "welcome",
)
SCENE_TAGS = (
    "brand",
    "classroom",
    "editorial",
    "experiment",
    "reading",
    "robotics_lab",
    "space",
    "space_station",
    "teamwork",
)

Character = Literal["xiao-sai", "sai-xiansheng"]
Prop = Literal[
    "astronaut",
    "book",
    "brand_team",
    "detector",
    "explorer",
    "microscope",
    "specimen",
    "telescope",
    "time_machine",
]
Pose = Literal[
    "astronaut",
    "discover",
    "discuss",
    "explore",
    "microscope",
    "observe",
    "point",
    "question",
    "read",
    "run",
    "teach",
    "think",
    "welcome",
]
SceneTag = Literal[
    "brand",
    "classroom",
    "editorial",
    "experiment",
    "reading",
    "robotics_lab",
    "space",
    "space_station",
    "teamwork",
]

LABEL_GUIDE = """你是品牌素材标注员。给一张品牌卡通图打标签，只输出一个 JSON 对象，不要任何解释或代码块。

角色（characters，可多选，只写图里真正出现的）：
- xiao-sai：白色和蓝色的机器人猫头鹰，蓝色耳羽，胸前常有 "AI" 标志，有时披蓝色披风、拿盾牌。
- sai-xiansheng：棕色羽毛的猫头鹰科学家，戴橙色护目镜，常穿白大褂或探险/西装等服装。
前两张图分别是 xiao-sai 和 sai-xiansheng 的参考形象；最后一张是要标注的图。

asset_kind：
- identity：角色单独的形象设定图（站立、展示全身或头像、徽章），没有具体在做的事或场景道具。
- action：角色在做一件事（讨论、看书、做实验、探测、太空等），或带有明确道具/场景。

props（只对 action 填；identity 填空列表）：画面主要围绕的道具，没有就填空列表，最多 2 个：
- telescope 望远镜；microscope 显微镜；book 打开阅读的书；time_machine 时光机舱/载具（在时光机里看书也只算 time_machine）；
- detector 手持探测器/扫描仪；specimen 手里展示的自然标本或样品（坚果、石头、叶子、化石等）；
- astronaut 穿宇航服或身在太空；explorer 探险装扮（背包、地图、探险服）；brand_team 多个角色穿正装组成团队。

poses（只对 action 填，1–3 个）：explore, astronaut, teach, point, read, think, discuss, observe,
welcome, discover, question, microscope, run。identity 填空列表。

scene_tags（1–2 个）：identity 固定填 ["brand"]；action 从 space, space_station, classroom, reading,
editorial, robotics_lab, experiment, teamwork 里选。

输出格式：
{"asset_kind": "identity|action", "characters": [...], "props": [...], "poses": [...],
 "scene_tags": [...], "note": "不超过 40 字的依据"}"""


class AssetLabels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_kind: Literal["identity", "action"]
    characters: list[Character] = Field(min_length=1, max_length=2)
    props: list[Prop] = Field(default_factory=list, max_length=2)
    poses: list[Pose] = Field(default_factory=list, max_length=3)
    scene_tags: list[SceneTag] = Field(default_factory=list, max_length=2)
    note: str = Field(default="", max_length=120)

    def normalized(self) -> AssetLabels:
        """Identity sheets carry no props or poses and the brand scene, as the catalog does."""

        if self.asset_kind == "identity":
            return self.model_copy(update={"props": [], "poses": [], "scene_tags": ["brand"]})
        return self


class InvalidLabels(ValueError):
    pass


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_labels(text: str) -> AssetLabels:
    """Strict: one JSON object with only the closed vocabularies (code fences tolerated)."""

    body = _FENCE.sub("", text.strip()).strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise InvalidLabels("no JSON object")
    try:
        raw = json.loads(body[start : end + 1])
    except json.JSONDecodeError as error:
        raise InvalidLabels(f"invalid JSON: {error.msg}") from None
    try:
        labels = AssetLabels.model_validate(raw)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in item['loc'])}: {item['type']}" for item in error.errors()
        )
        raise InvalidLabels(problems[:300]) from None
    return labels.normalized()


@dataclass(frozen=True, slots=True)
class Truth:
    asset_kind: str
    characters: frozenset[str]
    props: frozenset[str]
    poses: frozenset[str]
    scene_tags: frozenset[str]

    @classmethod
    def from_manifest(cls, asset: Mapping[str, Any]) -> Truth:
        return cls(
            asset_kind=str(asset.get("asset_kind")),
            characters=frozenset(asset.get("characters") or ()),
            props=frozenset(asset.get("props") or ()),
            poses=frozenset(asset.get("poses") or ()),
            scene_tags=frozenset(asset.get("scene_tags") or ()),
        )


@dataclass(slots=True)
class SetScore:
    true_positive: Counter[str] = field(default_factory=Counter)
    false_positive: Counter[str] = field(default_factory=Counter)
    false_negative: Counter[str] = field(default_factory=Counter)
    exact: int = 0
    total: int = 0

    def add(self, predicted: Iterable[str], truth: Iterable[str]) -> None:
        p, t = set(predicted), set(truth)
        self.total += 1
        self.exact += p == t
        for value in p & t:
            self.true_positive[value] += 1
        for value in p - t:
            self.false_positive[value] += 1
        for value in t - p:
            self.false_negative[value] += 1

    def micro(self) -> tuple[float, float]:
        tp = sum(self.true_positive.values())
        fp = sum(self.false_positive.values())
        fn = sum(self.false_negative.values())
        return (tp / (tp + fp) if tp + fp else 1.0, tp / (tp + fn) if tp + fn else 1.0)

    def per_value(self, values: Sequence[str]) -> dict[str, tuple[int, int, int]]:
        return {
            v: (self.true_positive[v], self.false_positive[v], self.false_negative[v])
            for v in values
            if self.true_positive[v] or self.false_positive[v] or self.false_negative[v]
        }


@dataclass(slots=True)
class Scorecard:
    kind_correct: int = 0
    kind_total: int = 0
    characters: SetScore = field(default_factory=SetScore)
    props: SetScore = field(default_factory=SetScore)
    poses: SetScore = field(default_factory=SetScore)
    scene_tags: SetScore = field(default_factory=SetScore)
    invalid: int = 0

    def add(self, labels: AssetLabels | None, truth: Truth) -> None:
        if labels is None:
            self.invalid += 1
            return
        self.kind_total += 1
        self.kind_correct += labels.asset_kind == truth.asset_kind
        self.characters.add(labels.characters, truth.characters)
        if truth.asset_kind == "action":
            # Props, poses and scenes are decided for action images only.
            self.props.add(labels.props, truth.props)
            self.poses.add(labels.poses, truth.poses)
            self.scene_tags.add(labels.scene_tags, truth.scene_tags)


def score(results: Iterable[tuple[AssetLabels | None, Truth]]) -> Scorecard:
    card = Scorecard()
    for labels, truth in results:
        card.add(labels, truth)
    return card


def metadata_draft(labels: AssetLabels, *, model: str) -> dict[str, Any]:
    """A `visual-assets.metadata.json` entry for a person to confirm (approved stays false)."""

    entry: dict[str, Any] = {
        "asset_kind": labels.asset_kind,
        "characters": list(labels.characters),
        "poses": list(labels.poses),
        "scene_tags": list(labels.scene_tags),
        "approved": False,
        "manual_review_note": f"drafted by {model}; confirm characters and props before approving",
    }
    if labels.asset_kind == "action":
        entry["props"] = list(labels.props)
    return entry
