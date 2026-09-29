"""Precision/recall of the same-topic headline rule on labelled real headline pairs.

Only the headline clause is evaluated here: the embedding clause needs stored article vectors
(see `evals.selection_replay` for the production-data view). v3 strips numbers and boilerplate
shared by unrelated news before matching; v2 is the previous production clause.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.domain.content_slots import _SAME_TOPIC_TITLE_OVERLAP, _share_title_phrase

FEATURE_ROOT = Path(__file__).resolve().parent
PAIRS_PATH = FEATURE_ROOT / "pairs.v1.jsonl"
CANONICAL_JSON_PATH = FEATURE_ROOT / "canonical-report.json"
CANONICAL_MARKDOWN_PATH = FEATURE_ROOT / "canonical-report.md"
REPORT_VERSION = "same-topic-golden-v1"


@dataclass(frozen=True, slots=True)
class TopicPair:
    pair_id: str
    same_topic: bool
    left: str
    right: str
    label_source: str


def load_pairs(path: Path = PAIRS_PATH) -> tuple[TopicPair, ...]:
    pairs = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw.get("same_topic"), bool):
            raise ValueError(f"line {line_number}: same_topic must be true or false")
        pairs.append(
            TopicPair(
                pair_id=raw["pair_id"],
                same_topic=raw["same_topic"],
                left=raw["left"],
                right=raw["right"],
                label_source=raw["label_source"],
            )
        )
    if len({pair.pair_id for pair in pairs}) != len(pairs):
        raise ValueError("pair IDs must be unique")
    return tuple(pairs)


def v2_rule(left: str, right: str) -> bool:
    return left == right or _share_title_phrase(left, right, _SAME_TOPIC_TITLE_OVERLAP)


def v3_rule(left: str, right: str) -> bool:
    return left == right or _share_title_phrase(left, right, _SAME_TOPIC_TITLE_OVERLAP, strict=True)


RULES: dict[str, Callable[[str, str], bool]] = {
    "slot-ranking-v2": v2_rule,
    "slot-ranking-v3": v3_rule,
}


def evaluate_rule(
    pairs: Sequence[TopicPair], rule: Callable[[str, str], bool]
) -> dict[str, object]:
    tp = fp = fn = tn = 0
    errors = []
    for pair in pairs:
        predicted = rule(pair.left, pair.right)
        if predicted and pair.same_topic:
            tp += 1
        elif predicted:
            fp += 1
            errors.append({"pair_id": pair.pair_id, "error": "false_same_topic"})
        elif pair.same_topic:
            fn += 1
            errors.append({"pair_id": pair.pair_id, "error": "missed_same_topic"})
        else:
            tn += 1
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "errors": errors,
    }


def build_report(pairs: Sequence[TopicPair]) -> dict[str, object]:
    return {
        "report_version": REPORT_VERSION,
        "pairs_sha256": hashlib.sha256(PAIRS_PATH.read_bytes()).hexdigest(),
        "pair_count": len(pairs),
        "same_topic_count": sum(pair.same_topic for pair in pairs),
        "rules": {name: evaluate_rule(pairs, rule) for name, rule in RULES.items()},
    }


def render_markdown(report: dict[str, object], pairs: Sequence[TopicPair]) -> str:
    by_id = {pair.pair_id: pair for pair in pairs}
    rules = report["rules"]
    assert isinstance(rules, dict)
    lines = [
        "# Same-topic headline rule",
        "",
        f"- Pairs: {report['pair_count']} ({report['same_topic_count']} same topic), real "
        "production headlines",
        "- Headline clause only; missed pairs may still be caught by the embedding clause.",
        "",
        "| Rule | Precision | Recall | False same-topic | Missed |",
        "|---|---|---|---|---|",
    ]
    for name, result in rules.items():
        lines.append(
            f"| `{name}` | {result['precision']} | {result['recall']} | "
            f"{result['false_positive']} | {result['false_negative']} |"
        )
    for name, result in rules.items():
        if result["errors"]:
            lines += ["", f"## `{name}` errors", ""]
            for error in result["errors"]:
                pair = by_id[error["pair_id"]]
                lines.append(f"- `{pair.pair_id}` {error['error']}: {pair.left} ~ {pair.right}")
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fail on drift from the canonical copy")
    mode.add_argument("--write-canonical", action="store_true")
    args = parser.parse_args(argv)
    pairs = load_pairs()
    report = build_report(pairs)
    generated_json = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    generated_markdown = render_markdown(report, pairs)
    if args.write_canonical:
        CANONICAL_JSON_PATH.write_text(generated_json, encoding="utf-8")
        CANONICAL_MARKDOWN_PATH.write_text(generated_markdown, encoding="utf-8")
    elif args.check:
        if CANONICAL_JSON_PATH.read_text(encoding="utf-8") != generated_json:
            print("same-topic report drifted; review, then run --write-canonical", file=sys.stderr)
            return 1
    else:
        print(generated_markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
