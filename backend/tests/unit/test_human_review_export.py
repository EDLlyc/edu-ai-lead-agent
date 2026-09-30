# ruff: noqa: RUF001  (Chinese fixture text)
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from evals.human_review.runner import (
    golden_candidates,
    human_verdict,
    load_labels,
    main,
    measure_agreement,
    render_markdown,
)

_NEW_SCHEMA = (
    "CREATE TABLE news_reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, news_key TEXT NOT NULL, "
    "decision TEXT NOT NULL, note TEXT, title TEXT NOT NULL, source_name TEXT, "
    "ai_verdict TEXT NOT NULL, business_date TEXT NOT NULL, slot TEXT NOT NULL, "
    "reviewed_at TEXT NOT NULL, source_url TEXT, snippet TEXT, tier_label TEXT, ai_score REAL, "
    "ai_threshold REAL, ai_rank INTEGER, ai_reasons TEXT)"
)


def _store(path: Path, rows: list[tuple[object, ...]], *, schema: str = _NEW_SCHEMA) -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute(schema)
        connection.executemany(
            "INSERT INTO news_reviews (news_key, decision, note, title, source_name, ai_verdict, "
            "business_date, slot, reviewed_at, source_url, snippet, tier_label, ai_score, "
            "ai_threshold, ai_rank, ai_reasons) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return path


def _row(
    key: str,
    decision: str,
    ai: str,
    *,
    title: str = "高校分类改革意见印发",
    at: str = "2026-09-29T02:00:00+00:00",
    note: str | None = None,
    tier: str | None = "权威来源",
    snippet: str | None = "教育部发布意见。",
) -> tuple[object, ...]:
    return (
        key,
        decision,
        note,
        title,
        "教育部",
        ai,
        "2026-09-29",
        "noon",
        at,
        "https://www.moe.gov.cn/a.html",
        snippet,
        tier,
        0.41,
        0.59,
        5,
        json.dumps(["below_threshold"]),
    )


def test_human_verdict_follows_the_decision() -> None:
    assert human_verdict("agree", "selected") == "selected"
    assert human_verdict("agree", "rejected") == "rejected"
    assert human_verdict("include", "rejected") == "selected"
    assert human_verdict("exclude", "selected") == "rejected"
    with pytest.raises(ValueError):
        human_verdict("publish", "selected")
    with pytest.raises(ValueError):
        human_verdict("agree", "maybe")


def test_latest_decision_per_item_and_agreement(tmp_path: Path) -> None:
    store = _store(
        tmp_path / "reviews.sqlite3",
        [
            _row("vn1_a", "exclude", "rejected", at="2026-09-29T01:00:00+00:00"),
            # The operator changed their mind: the later decision is the label.
            _row("vn1_a", "include", "rejected", at="2026-09-29T03:00:00+00:00", note="家长关心"),
            _row("vn1_b", "agree", "selected", title="人工智能通识教育"),
            _row("vn1_c", "exclude", "selected", title="某地发生事故", note="负面事件"),
            _row("vn1_d", "agree", "rejected", title="企业融资消息"),
        ],
    )
    labels = load_labels(store)
    assert [label.news_key for label in labels] == ["vn1_b", "vn1_c", "vn1_d", "vn1_a"]
    changed = labels[-1]
    assert (changed.decision, changed.human_verdict, changed.note) == (
        "include",
        "selected",
        "家长关心",
    )
    assert changed.ai_reasons == ("below_threshold",)

    agreement = measure_agreement(labels)
    assert (agreement.reviewed, agreement.agreed) == (4, 2)
    assert (
        agreement.both_selected,
        agreement.ai_only,
        agreement.human_only,
        agreement.both_rejected,
    ) == (1, 1, 1, 1)
    assert agreement.rate == 0.5
    assert agreement.precision == 0.5
    assert agreement.recall == 0.5

    report = render_markdown(labels, agreement)
    assert "AI 与人工一致 2/4（50%）" in report
    assert "样本只有 4 条" in report
    assert "## AI 落选、人工认为该推（1 条）" in report
    assert "高校分类改革意见印发；AI 理由：below_threshold；人工备注：家长关心" in report
    assert "## AI 入选、人工认为不该推（1 条）" in report
    assert load_labels(store, since=date(2026, 9, 30)) == ()


def test_golden_candidates_cover_disagreements_with_complete_context(tmp_path: Path) -> None:
    store = _store(
        tmp_path / "reviews.sqlite3",
        [
            _row("vn1_aaaaaaaa", "include", "rejected", note="家长关心"),
            _row("vn1_bbbbbbbb", "exclude", "selected", title="某地发生事故"),
            _row("vn1_cccccccc", "agree", "selected", title="人工智能通识教育"),
            _row("vn1_dddddddd", "include", "rejected", title="缺少来源等级", tier=None),
            _row("vn1_eeeeeeee", "include", "rejected", title="一般来源", tier="一般来源"),
        ],
    )
    labels = load_labels(store)
    cases, skipped = golden_candidates(labels)
    assert [(case["case_id"], case["label"]) for case in cases] == [
        ("h20260929-aaaaaaaa", "must_select"),
        ("h20260929-bbbbbbbb", "should_not_select"),
    ]
    assert cases[0]["label_source"] == "operator 2026-09-29 (展厅人工审核：家长关心)"
    assert cases[0]["source_tiers"] == ["A"]
    assert cases[0]["synthetic"] is False
    assert skipped == ["缺少来源等级", "一般来源"]
    everything, _ = golden_candidates(labels, disagreements_only=False)
    assert len(everything) == 3


def test_old_store_without_context_columns_and_empty_store(tmp_path: Path) -> None:
    old = tmp_path / "old.sqlite3"
    with sqlite3.connect(old) as connection:
        connection.execute(
            "CREATE TABLE news_reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "news_key TEXT NOT NULL, decision TEXT NOT NULL, note TEXT, title TEXT NOT NULL, "
            "source_name TEXT, ai_verdict TEXT NOT NULL, business_date TEXT NOT NULL, "
            "slot TEXT NOT NULL, reviewed_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO news_reviews (news_key, decision, title, ai_verdict, business_date, slot, "
            "reviewed_at) VALUES ('vn1_old', 'include', '旧记录', 'rejected', '2026-09-28', "
            "'morning', '2026-09-28T01:00:00+00:00')"
        )
    labels = load_labels(old)
    assert labels[0].snippet is None and labels[0].ai_reasons == ()
    assert golden_candidates(labels) == ([], ["旧记录"])

    empty = _store(tmp_path / "empty.sqlite3", [])
    assert load_labels(empty) == ()
    assert "还没有人工审核记录" in render_markdown((), measure_agreement(()))
    with pytest.raises(FileNotFoundError):
        load_labels(tmp_path / "missing.sqlite3")


def test_cli_writes_outputs_and_never_modifies_the_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _store(tmp_path / "reviews.sqlite3", [_row("vn1_aaaaaaaa", "include", "rejected")])
    before = store.read_bytes()
    output = tmp_path / "out"
    assert main(["--store", str(store), "--output-dir", str(output)]) == 0
    assert store.read_bytes() == before
    assert json.loads((output / "labels.jsonl").read_text("utf-8"))["human_verdict"] == "selected"
    assert json.loads((output / "golden-candidates.jsonl").read_text("utf-8"))["label"] == (
        "must_select"
    )
    assert "人工审核 1 条新闻" in (output / "report.md").read_text("utf-8")
    assert "人工审核 1 条新闻" in capsys.readouterr().out
    assert main(["--store", str(tmp_path / "missing.sqlite3")]) == 2
