"""Operator keyword versions: the active set, the version a slot run used, and the impact check.

Callers own the transaction: these functions add and flush, they never commit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.operator_keywords import OperatorKeywords, matched_terms
from app.infrastructure.db.models import (
    ContentSlotRunModel,
    ContentSlotScoreModel,
    ContentSlotSelectionModel,
    CopyGenerationRunModel,
    EventClusterVersionModel,
    OperatorKeywordVersionModel,
)


def keywords_from_row(row: OperatorKeywordVersionModel) -> OperatorKeywords:
    return OperatorKeywords(
        version=row.version,
        focus=tuple(str(term) for term in row.focus_terms),
        block=tuple(str(term) for term in row.block_terms),
        copy_banned=tuple(str(term) for term in row.copy_banned_terms),
    )


async def load_active_keyword_row(session: AsyncSession) -> OperatorKeywordVersionModel | None:
    row: OperatorKeywordVersionModel | None = await session.scalar(
        select(OperatorKeywordVersionModel)
        .order_by(OperatorKeywordVersionModel.version.desc())
        .limit(1)
    )
    return row


async def load_keyword_row(
    session: AsyncSession, *, version: int
) -> OperatorKeywordVersionModel | None:
    row: OperatorKeywordVersionModel | None = await session.scalar(
        select(OperatorKeywordVersionModel).where(OperatorKeywordVersionModel.version == version)
    )
    return row


async def list_keyword_rows(session: AsyncSession) -> Sequence[OperatorKeywordVersionModel]:
    return (
        await session.scalars(
            select(OperatorKeywordVersionModel).order_by(OperatorKeywordVersionModel.version.desc())
        )
    ).all()


async def add_keyword_version(
    session: AsyncSession,
    *,
    focus: tuple[str, ...],
    block: tuple[str, ...],
    copy_banned: tuple[str, ...],
    note: str | None,
    created_by: str,
    now: datetime,
) -> OperatorKeywordVersionModel:
    latest = await session.scalar(select(func.max(OperatorKeywordVersionModel.version)))
    row = OperatorKeywordVersionModel(
        id=uuid4(),
        version=(latest or 0) + 1,
        focus_terms=list(focus),
        block_terms=list(block),
        copy_banned_terms=list(copy_banned),
        note=note,
        created_by=created_by[:40],
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def keywords_for_slot_run(
    session: AsyncSession, run: ContentSlotRunModel
) -> OperatorKeywords | None:
    if run.operator_keyword_version_id is None:
        return None
    row = await session.get(OperatorKeywordVersionModel, run.operator_keyword_version_id)
    if row is None:
        raise RuntimeError("content slot run references a missing keyword version")
    return keywords_from_row(row)


async def copy_banned_terms_for_copy_run(
    session: AsyncSession, run: CopyGenerationRunModel
) -> tuple[str, ...]:
    """文案禁用词 recorded by the slot run a copy run came from (empty for legacy daily runs)."""

    if run.content_slot_selection_id is None:
        return ()
    slot_run = await session.scalar(
        select(ContentSlotRunModel)
        .join(ContentSlotSelectionModel, ContentSlotSelectionModel.run_id == ContentSlotRunModel.id)
        .where(ContentSlotSelectionModel.id == run.content_slot_selection_id)
    )
    if slot_run is None:
        return ()
    keywords = await keywords_for_slot_run(session, slot_run)
    return () if keywords is None else keywords.copy_banned


@dataclass(frozen=True, slots=True)
class RecentCandidate:
    event_version_id: UUID
    title: str
    summary: str
    selected: bool


async def recent_slot_candidates(
    session: AsyncSession, *, now: datetime, days: int = 7
) -> list[RecentCandidate]:
    """Distinct event versions scored by scheduled slot runs in the last `days` days."""

    rows = (
        await session.execute(
            select(
                ContentSlotScoreModel.event_version_id,
                func.bool_or(ContentSlotScoreModel.selected_ordinal.is_not(None)),
            )
            .join(ContentSlotRunModel, ContentSlotRunModel.id == ContentSlotScoreModel.run_id)
            .where(
                ContentSlotRunModel.created_at >= now - timedelta(days=days),
                ContentSlotRunModel.trigger != "human",
            )
            .group_by(ContentSlotScoreModel.event_version_id)
        )
    ).all()
    if not rows:
        return []
    selected_by_version = {version_id: bool(selected) for version_id, selected in rows}
    versions = (
        await session.scalars(
            select(EventClusterVersionModel).where(
                EventClusterVersionModel.id.in_(list(selected_by_version))
            )
        )
    ).all()
    candidates: list[RecentCandidate] = []
    for version in versions:
        summary = version.summary_projection.get("summary")
        candidates.append(
            RecentCandidate(
                event_version_id=version.id,
                title=version.representative_title,
                summary=summary if isinstance(summary, str) else "",
                selected=selected_by_version[version.id],
            )
        )
    return candidates


@dataclass(frozen=True, slots=True)
class KeywordImpact:
    candidate_count: int
    blocked: tuple[tuple[str, tuple[str, ...], bool], ...]
    focused: tuple[tuple[str, tuple[str, ...]], ...]
    per_block_term: dict[str, int]

    @property
    def blocked_share(self) -> float:
        return len(self.blocked) / self.candidate_count if self.candidate_count else 0.0


def keyword_impact(
    candidates: Sequence[RecentCandidate], *, focus: tuple[str, ...], block: tuple[str, ...]
) -> KeywordImpact:
    blocked: list[tuple[str, tuple[str, ...], bool]] = []
    focused: list[tuple[str, tuple[str, ...]]] = []
    per_term = dict.fromkeys(block, 0)
    for candidate in candidates:
        text = f"{candidate.title}\n{candidate.summary}"
        block_hits = matched_terms(text, block)
        if block_hits:
            blocked.append((candidate.title, block_hits, candidate.selected))
            for term in block_hits:
                per_term[term] += 1
            continue
        focus_hits = matched_terms(text, focus)
        if focus_hits:
            focused.append((candidate.title, focus_hits))
    blocked.sort(key=lambda item: (not item[2], item[0]))
    return KeywordImpact(
        candidate_count=len(candidates),
        blocked=tuple(blocked),
        focused=tuple(sorted(focused)),
        per_block_term=per_term,
    )


__all__ = [
    "KeywordImpact",
    "RecentCandidate",
    "add_keyword_version",
    "copy_banned_terms_for_copy_run",
    "keyword_impact",
    "keywords_for_slot_run",
    "keywords_from_row",
    "list_keyword_rows",
    "load_active_keyword_row",
    "load_keyword_row",
    "recent_slot_candidates",
]
