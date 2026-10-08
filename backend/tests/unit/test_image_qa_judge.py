# ruff: noqa: RUF001
"""Image QA judge: strict verdict parsing, one format retry, scoring against labels."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from evals.asset_labels.client import ChatResult
from evals.image_qa.judge import InvalidVerdict, judge_image, parse_verdict, render, score
from PIL import Image

GOOD = {
    "characters_seen": ["xiaosai"],
    "cast_ok": True,
    "broken": False,
    "broken_reasons": [],
    "usable": True,
    "note": "小赛在操作机械臂",
}


class Fake:
    name = "fake-vl"

    def __init__(self, texts: Sequence[str]) -> None:
        self.texts = list(texts)
        self.contents: list[Sequence[Mapping[str, Any]]] = []

    def complete(self, content: Sequence[Mapping[str, Any]]) -> ChatResult:
        self.contents.append(content)
        return ChatResult(self.texts.pop(0), 1_000, 60, 1.5)


def _png(path: Path) -> Path:
    Image.new("RGBA", (64, 64), (0, 120, 255, 255)).save(path)
    return path


def test_a_verdict_is_parsed_from_prose_and_strictly_validated() -> None:
    wrapped = "结果如下：\n```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```"

    assert parse_verdict(wrapped).cast_ok is True
    with pytest.raises(InvalidVerdict):
        parse_verdict(json.dumps({**GOOD, "characters_seen": ["dog"]}))
    with pytest.raises(InvalidVerdict):
        parse_verdict(json.dumps({**GOOD, "extra": 1}))
    with pytest.raises(InvalidVerdict):
        parse_verdict("看起来没问题")


def test_the_judge_sends_references_then_the_image_and_retries_once(tmp_path: Path) -> None:
    refs = [_png(tmp_path / "a.png"), _png(tmp_path / "b.png")]
    model = Fake(["不是 JSON", json.dumps(GOOD, ensure_ascii=False)])

    judged = judge_image(
        model,
        image=_png(tmp_path / "gen.png"),
        references=refs,
        cast="xiaosai_solo",
        subject="robot_arm",
    )

    assert judged.verdict is not None and judged.calls == 2
    assert judged.prompt_tokens == 2_000 and judged.error is None
    first = model.contents[0]
    assert [part["type"] for part in first] == ["image_url", "image_url", "image_url", "text"]
    assert "只有小赛" in first[-1]["text"] and "robot_arm" in first[-1]["text"]
    assert "只输出 JSON" in model.contents[1][-1]["text"]


def test_two_bad_answers_leave_no_verdict(tmp_path: Path) -> None:
    judged = judge_image(
        Fake(["?", "??"]),
        image=_png(tmp_path / "gen.png"),
        references=[_png(tmp_path / "a.png")],
        cast="duo",
        subject="robot_arm",
    )

    assert judged.verdict is None and judged.calls == 2 and judged.error


def test_scoring_counts_problems_caught_missed_and_false_alarms() -> None:
    labels = [
        {"image": "a", "cast": "wrong", "broken": "no", "usable": "no"},
        {"image": "b", "cast": "ok", "broken": "yes", "usable": "no"},
        {"image": "c", "cast": "ok", "broken": "no", "usable": "yes"},
        {"image": "d", "cast": "ok", "broken": "no"},  # usable unanswered
    ]
    verdicts = {
        "a": {**GOOD, "cast_ok": False, "usable": False},
        "b": {**GOOD},  # missed the broken image
        "c": {**GOOD, "broken": True, "usable": False},  # false alarm
        "d": {**GOOD},
    }

    table = score(labels, verdicts)

    assert (table["cast"].tp, table["cast"].fp, table["cast"].fn, table["cast"].tn) == (1, 0, 0, 3)
    assert (table["broken"].tp, table["broken"].fp, table["broken"].fn) == (0, 1, 1)
    assert (
        table["unusable"].tp,
        table["unusable"].fp,
        table["unusable"].fn,
        table["unusable"].tn,
    ) == (
        1,
        1,
        1,
        0,
    )
    report = render(
        labels,
        {
            "fake": {
                "verdicts": verdicts,
                "usage": {
                    "calls": 4,
                    "prompt_tokens": 4_000,
                    "completion_tokens": 200,
                    "seconds": 6.0,
                    "invalid": 0,
                },
            }
        },
    )
    assert "| 人物不对 | 1 | 1 | 0 | 100% | 100% | 0% | 4/4 |" in report
    assert "## fake" in report
