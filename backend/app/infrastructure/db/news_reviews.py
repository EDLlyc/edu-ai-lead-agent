"""Postgres store for human news reviews made in the admin console.

Same contract as the exhibit's local SQLite store (`NewsReviewStore`): append-only rows, the newest
row per ``news_key`` is the current call. Rows are opinions only and never feed a run or delivery.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db.models import NewsReviewModel
from app.infrastructure.visitor_review_store import NewsReviewSubject, StoredNewsReview

_KEY_BATCH = 500


def _stored(row: NewsReviewModel) -> StoredNewsReview:
    return StoredNewsReview(
        news_key=row.news_key, decision=row.decision, note=row.note, reviewed_at=row.reviewed_at
    )


class PostgresNewsReviewStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def latest(self, keys: Iterable[str]) -> dict[str, StoredNewsReview]:
        unique = tuple(dict.fromkeys(keys))
        result: dict[str, StoredNewsReview] = {}
        if not unique:
            return result
        async with self._session_factory() as session:
            for start in range(0, len(unique), _KEY_BATCH):
                chunk = unique[start : start + _KEY_BATCH]
                rows = await session.scalars(
                    select(NewsReviewModel)
                    .where(NewsReviewModel.news_key.in_(chunk))
                    .distinct(NewsReviewModel.news_key)
                    .order_by(NewsReviewModel.news_key, NewsReviewModel.id.desc())
                )
                for row in rows:
                    result[row.news_key] = _stored(row)
        return result

    async def record(
        self,
        *,
        key: str,
        decision: str,
        note: str | None,
        subject: NewsReviewSubject,
        now: datetime | None = None,
        reviewer: str | None = None,
    ) -> StoredNewsReview:
        if reviewer is None:
            raise ValueError("a review made in the admin console needs its reviewer")
        reviewed_at = (now or datetime.now(UTC)).astimezone(UTC)
        async with self._session_factory() as session:
            session.add(
                NewsReviewModel(
                    news_key=key,
                    decision=decision,
                    note=note,
                    reviewer=reviewer,
                    title=subject.title,
                    source_name=subject.source_name,
                    ai_verdict=subject.ai_verdict,
                    business_date=subject.business_date,
                    slot=subject.slot,
                    source_url=subject.source_url,
                    snippet=subject.snippet,
                    tier_label=subject.tier_label,
                    ai_score=subject.ai_score,
                    ai_threshold=subject.ai_threshold,
                    ai_rank=subject.ai_rank,
                    ai_reasons=list(subject.ai_reasons),
                    reviewed_at=reviewed_at,
                )
            )
            await session.commit()
        return StoredNewsReview(news_key=key, decision=decision, note=note, reviewed_at=reviewed_at)

    async def daily_counts(
        self, days: tuple[date, ...], *, timezone: str
    ) -> dict[date, tuple[int, int]]:
        """Per local day: news items reviewed and how many disagree with the AI verdict."""
        result = {day: (0, 0) for day in days}
        for (day, _key), (decision, ai_verdict) in (
            await self._latest_per_day(days, ZoneInfo(timezone))
        ).items():
            reviewed, disagreements = result[day]
            disagrees = (decision == "include" and ai_verdict == "rejected") or (
                decision == "exclude" and ai_verdict == "selected"
            )
            result[day] = (reviewed + 1, disagreements + int(disagrees))
        return result

    async def daily_decisions(
        self, days: tuple[date, ...], *, timezone: str
    ) -> dict[date, dict[str, int]]:
        """Per local day, the last decision per item (agree / include / exclude override)."""
        result: dict[date, dict[str, int]] = {
            day: {"agree": 0, "include_override": 0, "exclude_override": 0} for day in days
        }
        for (day, _key), (decision, ai_verdict) in (
            await self._latest_per_day(days, ZoneInfo(timezone))
        ).items():
            if decision == "include" and ai_verdict == "rejected":
                result[day]["include_override"] += 1
            elif decision == "exclude" and ai_verdict == "selected":
                result[day]["exclude_override"] += 1
            else:
                result[day]["agree"] += 1
        return result

    async def _latest_per_day(
        self, days: tuple[date, ...], zone: ZoneInfo
    ) -> dict[tuple[date, str], tuple[str, str]]:
        if not days:
            return {}
        since = datetime.combine(min(days), datetime.min.time(), zone) - timedelta(days=1)
        async with self._session_factory() as session:
            rows = await session.execute(
                select(
                    NewsReviewModel.news_key,
                    NewsReviewModel.decision,
                    NewsReviewModel.ai_verdict,
                    NewsReviewModel.reviewed_at,
                )
                .where(NewsReviewModel.reviewed_at >= since.astimezone(UTC))
                .order_by(NewsReviewModel.id)
            )
            latest: dict[tuple[date, str], tuple[str, str]] = {}
            # The last decision per item on each day is that day's human call.
            for news_key, decision, ai_verdict, reviewed_at in rows:
                day = reviewed_at.astimezone(zone).date()
                if day in days:
                    latest[(day, news_key)] = (decision, ai_verdict)
            return latest


__all__ = ["PostgresNewsReviewStore"]
