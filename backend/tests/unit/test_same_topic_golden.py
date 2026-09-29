from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.same_topic_golden.runner import (
    build_report,
    load_pairs,
    main,
    v2_rule,
    v3_rule,
)


def test_canonical_report_is_current() -> None:
    assert main(["--check"]) == 0


def test_v3_rule_removes_boilerplate_false_positives_without_losing_recall() -> None:
    rules = build_report(load_pairs())["rules"]
    assert isinstance(rules, dict)

    assert rules["slot-ranking-v3"]["false_positive"] < rules["slot-ranking-v2"]["false_positive"]
    assert rules["slot-ranking-v3"]["recall"] == rules["slot-ranking-v2"]["recall"]


def test_rules_on_known_examples() -> None:
    opening = (
        "张国清出席第五届北斗规模应用国际峰会开幕式并致辞",
        "李强出席2026年世界技能大会开幕式并致辞",
    )
    assert v2_rule(*opening)
    assert not v3_rule(*opening)
    assert v3_rule("古基因组“讲述”新疆东天山两千年人群融合史", "研究揭示新疆东天山人群遗传历史")


def test_unlabelled_pairs_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "pairs.jsonl"
    path.write_text(
        json.dumps(
            {"pair_id": "x", "same_topic": "yes", "left": "a", "right": "b", "label_source": "s"}
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="same_topic"):
        load_pairs(path)
