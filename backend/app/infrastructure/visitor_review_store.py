"""Operator-local record of human news reviews for the visitor exhibit.

Reviews are opinions only: they live in a local SQLite file next to the adapter and never
reach the production database, a model provider, a WeChat draft or a WeCom delivery.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_SCHEMA = """
CREATE TABLE IF NOT EXISTS news_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_key TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('agree', 'include', 'exclude')),
    note TEXT,
    title TEXT NOT NULL,
    source_name TEXT,
    ai_verdict TEXT NOT NULL CHECK (ai_verdict IN ('selected', 'rejected')),
    business_date TEXT NOT NULL,
    slot TEXT NOT NULL,
    reviewed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_news_reviews_key ON news_reviews (news_key, id);
"""
# What the AI showed when the operator decided. Nullable and added to older files on start, so a
# review can later become a labelled evaluation case without reading production again.
_CONTEXT_COLUMNS = {
    "source_url": "TEXT",
    "snippet": "TEXT",
    "tier_label": "TEXT",
    "ai_score": "REAL",
    "ai_threshold": "REAL",
    "ai_rank": "INTEGER",
    "ai_reasons": "TEXT",
}
_KEY_BATCH = 500


@dataclass(frozen=True, slots=True)
class StoredNewsReview:
    news_key: str
    decision: str
    note: str | None
    reviewed_at: datetime


@dataclass(frozen=True, slots=True)
class NewsReviewSubject:
    """What the operator saw when deciding, kept so the local file is self-describing."""

    title: str
    source_name: str | None
    ai_verdict: str
    business_date: date
    slot: str
    source_url: str | None = None
    snippet: str | None = None
    tier_label: str | None = None
    ai_score: float | None = None
    ai_threshold: float | None = None
    ai_rank: int | None = None
    ai_reasons: tuple[str, ...] = ()


class VisitorReviewStore:
    """Append-only history; the newest row per key is the current human decision."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def initialize(self) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.executescript(_SCHEMA)
            existing = {row[1] for row in connection.execute("PRAGMA table_info(news_reviews)")}
            for column, kind in _CONTEXT_COLUMNS.items():
                if column not in existing:
                    connection.execute(f"ALTER TABLE news_reviews ADD COLUMN {column} {kind}")
        self._path.chmod(0o600)

    async def latest(self, keys: Iterable[str]) -> dict[str, StoredNewsReview]:
        unique = tuple(dict.fromkeys(keys))
        if not unique:
            return {}
        return await asyncio.to_thread(self._latest, unique)

    async def record(
        self,
        *,
        key: str,
        decision: str,
        note: str | None,
        subject: NewsReviewSubject,
        now: datetime | None = None,
    ) -> StoredNewsReview:
        reviewed_at = (now or datetime.now(UTC)).astimezone(UTC)
        await asyncio.to_thread(self._insert, key, decision, note, subject, reviewed_at)
        return StoredNewsReview(news_key=key, decision=decision, note=note, reviewed_at=reviewed_at)

    async def daily_counts(
        self, days: tuple[date, ...], *, timezone: str
    ) -> dict[date, tuple[int, int]]:
        """Per local day: news items reviewed and how many disagree with the AI verdict."""
        if not days:
            return {}
        return await asyncio.to_thread(self._daily_counts, days, ZoneInfo(timezone))

    def _daily_counts(self, days: tuple[date, ...], zone: ZoneInfo) -> dict[date, tuple[int, int]]:
        result = {day: (0, 0) for day in days}
        for (day, _key), (decision, ai_verdict) in self._latest_per_day(days, zone).items():
            reviewed, disagreements = result[day]
            disagrees = (decision == "include" and ai_verdict == "rejected") or (
                decision == "exclude" and ai_verdict == "selected"
            )
            result[day] = (reviewed + 1, disagreements + int(disagrees))
        return result

    async def daily_decisions(
        self, days: tuple[date, ...], *, timezone: str
    ) -> dict[date, dict[str, int]]:
        """Per local day, the day's last decision per item by kind.

        ``include_override`` = AI rejected, human would include; ``exclude_override`` = AI
        selected, human would drop; ``agree`` covers explicit agreement and same-direction calls.
        """
        if not days:
            return {}
        return await asyncio.to_thread(self._daily_decisions, days, ZoneInfo(timezone))

    def _daily_decisions(
        self, days: tuple[date, ...], zone: ZoneInfo
    ) -> dict[date, dict[str, int]]:
        result: dict[date, dict[str, int]] = {
            day: {"agree": 0, "include_override": 0, "exclude_override": 0} for day in days
        }
        for (day, _key), (decision, ai_verdict) in self._latest_per_day(days, zone).items():
            if decision == "include" and ai_verdict == "rejected":
                result[day]["include_override"] += 1
            elif decision == "exclude" and ai_verdict == "selected":
                result[day]["exclude_override"] += 1
            else:
                result[day]["agree"] += 1
        return result

    def _latest_per_day(
        self, days: tuple[date, ...], zone: ZoneInfo
    ) -> dict[tuple[date, str], tuple[str, str]]:
        since = datetime.combine(min(days), datetime.min.time(), zone) - timedelta(days=1)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT news_key, decision, ai_verdict, reviewed_at FROM news_reviews "
                "WHERE reviewed_at >= ? ORDER BY id",
                (since.astimezone(UTC).isoformat(),),
            ).fetchall()
        # The last decision per item on each day is that day's human call.
        latest: dict[tuple[date, str], tuple[str, str]] = {}
        for news_key, decision, ai_verdict, reviewed_at in rows:
            day = datetime.fromisoformat(reviewed_at).astimezone(zone).date()
            if day in days:
                latest[(day, news_key)] = (decision, ai_verdict)
        return latest

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=5)

    def _latest(self, keys: tuple[str, ...]) -> dict[str, StoredNewsReview]:
        result: dict[str, StoredNewsReview] = {}
        with closing(self._connect()) as connection:
            for start in range(0, len(keys), _KEY_BATCH):
                chunk = keys[start : start + _KEY_BATCH]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    "SELECT news_key, decision, note, reviewed_at FROM news_reviews "
                    "WHERE id IN (SELECT MAX(id) FROM news_reviews "
                    f"WHERE news_key IN ({placeholders}) GROUP BY news_key)",
                    chunk,
                ).fetchall()
                for news_key, decision, note, reviewed_at in rows:
                    result[news_key] = StoredNewsReview(
                        news_key=news_key,
                        decision=decision,
                        note=note,
                        reviewed_at=datetime.fromisoformat(reviewed_at),
                    )
        return result

    def _insert(
        self,
        key: str,
        decision: str,
        note: str | None,
        subject: NewsReviewSubject,
        reviewed_at: datetime,
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO news_reviews (news_key, decision, note, title, source_name, "
                "ai_verdict, business_date, slot, reviewed_at, source_url, snippet, tier_label, "
                "ai_score, ai_threshold, ai_rank, ai_reasons) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    decision,
                    note,
                    subject.title,
                    subject.source_name,
                    subject.ai_verdict,
                    subject.business_date.isoformat(),
                    subject.slot,
                    reviewed_at.isoformat(),
                    subject.source_url,
                    subject.snippet,
                    subject.tier_label,
                    subject.ai_score,
                    subject.ai_threshold,
                    subject.ai_rank,
                    json.dumps(list(subject.ai_reasons), ensure_ascii=False),
                ),
            )


__all__ = ["NewsReviewSubject", "StoredNewsReview", "VisitorReviewStore"]
