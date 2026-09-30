# ruff: noqa: RUF001  (Chinese operator-facing report text)
"""Turn the exhibit's human news reviews into labelled evaluation cases.

The exhibit records every operator decision (同意 AI / 改判入选 / 改判落选) in a local SQLite file.
This reads that file read-only and produces: one human label per news item, how often the AI's
selection agrees with the operator, and topic-golden candidates for the disagreements. These are
real human labels; nothing here is judged by a model.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

REPORT_VERSION = "human-review-export-v1"
Verdict = Literal["selected", "rejected"]
Decision = Literal["agree", "include", "exclude"]
_TIER_BY_LABEL = {"权威来源": "A", "可信来源": "B"}
_OPTIONAL_COLUMNS = (
    "source_url",
    "snippet",
    "tier_label",
    "ai_score",
    "ai_threshold",
    "ai_rank",
    "ai_reasons",
)
_SLOT_LABEL = {"morning": "早场", "noon": "午场", "evening": "晚场"}


@dataclass(frozen=True, slots=True)
class HumanLabel:
    """The operator's latest decision on one news item."""

    news_key: str
    title: str
    source_name: str | None
    source_url: str | None
    snippet: str | None
    tier_label: str | None
    business_date: str
    slot: str
    ai_verdict: Verdict
    ai_score: float | None
    ai_threshold: float | None
    ai_rank: int | None
    ai_reasons: tuple[str, ...]
    decision: Decision
    human_verdict: Verdict
    note: str | None
    reviewed_at: str

    @property
    def agrees_with_ai(self) -> bool:
        return self.human_verdict == self.ai_verdict


@dataclass(frozen=True, slots=True)
class Agreement:
    reviewed: int
    agreed: int
    # AI selected / human selected, AI selected / human rejected, and so on.
    both_selected: int
    ai_only: int
    human_only: int
    both_rejected: int

    @property
    def rate(self) -> float | None:
        return self.agreed / self.reviewed if self.reviewed else None

    @property
    def precision(self) -> float | None:
        """Of the news the AI selected, the share the operator would also push."""
        selected = self.both_selected + self.ai_only
        return self.both_selected / selected if selected else None

    @property
    def recall(self) -> float | None:
        """Of the news the operator would push, the share the AI selected."""
        wanted = self.both_selected + self.human_only
        return self.both_selected / wanted if wanted else None


def human_verdict(decision: str, ai_verdict: str) -> Verdict:
    if ai_verdict not in {"selected", "rejected"}:
        raise ValueError(f"unknown AI verdict {ai_verdict!r}")
    if decision == "include":
        return "selected"
    if decision == "exclude":
        return "rejected"
    if decision == "agree":
        return "selected" if ai_verdict == "selected" else "rejected"
    raise ValueError(f"unknown decision {decision!r}")


def load_labels(store: Path, *, since: date | None = None) -> tuple[HumanLabel, ...]:
    """Latest decision per news item, oldest review first. The store is opened read-only."""

    if not store.is_file():
        raise FileNotFoundError(f"review store not found: {store}")
    with closing(sqlite3.connect(f"file:{store}?mode=ro", uri=True, timeout=5)) as connection:
        connection.row_factory = sqlite3.Row
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(news_reviews)")}
        if not columns:
            return ()
        optional = ", ".join(
            column if column in columns else f"NULL AS {column}" for column in _OPTIONAL_COLUMNS
        )
        rows = connection.execute(
            "SELECT id, news_key, decision, note, title, source_name, ai_verdict, "
            f"business_date, slot, reviewed_at, {optional} FROM news_reviews ORDER BY id"
        ).fetchall()
    latest: dict[str, HumanLabel] = {}
    for row in rows:
        reviewed_at = datetime.fromisoformat(row["reviewed_at"])
        if since is not None and reviewed_at.date() < since:
            continue
        reasons = row["ai_reasons"]
        latest[row["news_key"]] = HumanLabel(
            news_key=row["news_key"],
            title=row["title"],
            source_name=row["source_name"],
            source_url=row["source_url"],
            snippet=row["snippet"],
            tier_label=row["tier_label"],
            business_date=row["business_date"],
            slot=row["slot"],
            ai_verdict=row["ai_verdict"],
            ai_score=row["ai_score"],
            ai_threshold=row["ai_threshold"],
            ai_rank=row["ai_rank"],
            ai_reasons=tuple(json.loads(reasons)) if reasons else (),
            decision=row["decision"],
            human_verdict=human_verdict(row["decision"], row["ai_verdict"]),
            note=row["note"],
            reviewed_at=reviewed_at.isoformat(),
        )
    return tuple(sorted(latest.values(), key=lambda label: label.reviewed_at))


def measure_agreement(labels: Sequence[HumanLabel]) -> Agreement:
    def count(ai: Verdict, human: Verdict) -> int:
        return sum(label.ai_verdict == ai and label.human_verdict == human for label in labels)

    return Agreement(
        reviewed=len(labels),
        agreed=sum(label.agrees_with_ai for label in labels),
        both_selected=count("selected", "selected"),
        ai_only=count("selected", "rejected"),
        human_only=count("rejected", "selected"),
        both_rejected=count("rejected", "rejected"),
    )


def golden_candidates(
    labels: Sequence[HumanLabel], *, disagreements_only: bool = True
) -> tuple[list[dict[str, object]], list[str]]:
    """Topic-golden case stubs, and the titles skipped because a field is missing.

    A stub still needs a person to confirm the category and summary before it is appended to
    `evals/topic_golden/cases.v1.jsonl`.
    """

    cases: list[dict[str, object]] = []
    skipped: list[str] = []
    for label in labels:
        if disagreements_only and label.agrees_with_ai:
            continue
        tier = _TIER_BY_LABEL.get(label.tier_label or "")
        if tier is None or not label.snippet:
            skipped.append(label.title)
            continue
        day = label.reviewed_at[:10]
        cases.append(
            {
                "case_id": f"h{label.business_date.replace('-', '')}-{label.news_key[-8:]}",
                "label": "must_select"
                if label.human_verdict == "selected"
                else "should_not_select",
                "expect_priority": False,
                "category": "human_review",
                "label_source": f"operator {day} (展厅人工审核"
                + (f"：{label.note}" if label.note else "")
                + ")",
                "synthetic": False,
                "source_tiers": [tier],
                "topic_priority_policy": None,
                "title": label.title,
                "summary": label.snippet,
                "source_url": label.source_url,
                "facts": [],
                "categories": [],
            }
        )
    return cases, skipped


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def render_markdown(labels: Sequence[HumanLabel], agreement: Agreement) -> str:
    lines = ["# 人工审核与 AI 选题的一致性", ""]
    if not labels:
        lines += [
            "还没有人工审核记录。",
            "",
            "在展厅「新闻池」进入审核模式，对每条新闻选择 同意 AI / 改判入选 / 改判落选。"
            "建议每天审 10–20 条，入选和落选的都要看，持续一周后再运行本报告。",
            "",
        ]
        return "\n".join(lines)
    lines += [
        f"- 人工审核 {agreement.reviewed} 条新闻（同一条以最后一次决定为准）",
        f"- AI 与人工一致 {agreement.agreed}/{agreement.reviewed}（{_percent(agreement.rate)}）",
        f"- AI 入选的新闻里，人工也认为该推：{agreement.both_selected}/"
        f"{agreement.both_selected + agreement.ai_only}（{_percent(agreement.precision)}）",
        f"- 人工认为该推的新闻里，AI 选中了：{agreement.both_selected}/"
        f"{agreement.both_selected + agreement.human_only}（{_percent(agreement.recall)}）",
        "",
        "| | 人工：该推 | 人工：不该推 |",
        "|---|---|---|",
        f"| AI 入选 | {agreement.both_selected} | {agreement.ai_only} |",
        f"| AI 落选 | {agreement.human_only} | {agreement.both_rejected} |",
        "",
    ]
    if agreement.reviewed < 30:
        lines += [f"样本只有 {agreement.reviewed} 条，比例仅供参考；30 条以上再用于调整规则。", ""]
    for heading, ai, human in (
        ("AI 落选、人工认为该推", "rejected", "selected"),
        ("AI 入选、人工认为不该推", "selected", "rejected"),
    ):
        rows = [
            label for label in labels if label.ai_verdict == ai and label.human_verdict == human
        ]
        if not rows:
            continue
        lines += [f"## {heading}（{len(rows)} 条）", ""]
        for label in rows:
            slot = _SLOT_LABEL.get(label.slot, label.slot)
            reasons = f"；AI 理由：{'、'.join(label.ai_reasons)}" if label.ai_reasons else ""
            note = f"；人工备注：{label.note}" if label.note else ""
            lines.append(f"- {label.business_date} {slot}｜{label.title}{reasons}{note}")
        lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True, help="news-reviews.sqlite3")
    parser.add_argument("--since", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="also write labels.jsonl, golden-candidates.jsonl and report.md here",
    )
    parser.add_argument(
        "--all-candidates",
        action="store_true",
        help="golden candidates for every reviewed item, not only disagreements",
    )
    args = parser.parse_args(argv)
    try:
        labels = load_labels(args.store, since=args.since)
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 2
    agreement = measure_agreement(labels)
    report = render_markdown(labels, agreement)
    if args.output_dir is not None:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        cases, skipped = golden_candidates(labels, disagreements_only=not args.all_candidates)
        (args.output_dir / "labels.jsonl").write_text(
            "".join(json.dumps(asdict(label), ensure_ascii=False) + "\n" for label in labels),
            encoding="utf-8",
        )
        (args.output_dir / "golden-candidates.jsonl").write_text(
            "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n" for case in cases),
            encoding="utf-8",
        )
        (args.output_dir / "report.md").write_text(report, encoding="utf-8")
        print(
            f"{len(labels)} labels, {len(cases)} golden candidates"
            f" ({len(skipped)} skipped: no tier or snippet) -> {args.output_dir}",
            file=sys.stderr,
        )
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
