"""Maintained built-in phrase versions. Callers own the transaction."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.builtin_phrases import DEFAULT_ANXIETY, DEFAULT_MARKETING, BuiltinPhrases
from app.infrastructure.db.models import (
    BuiltinPhraseVersionModel,
    ContentSlotRunModel,
    ContentSlotSelectionModel,
    CopyGenerationRunModel,
)


def phrases_from_row(row: BuiltinPhraseVersionModel) -> BuiltinPhrases:
    return BuiltinPhrases(
        version=row.version,
        marketing=tuple(str(term) for term in row.marketing_terms),
        anxiety=tuple(str(term) for term in row.anxiety_terms),
    )


async def load_active_builtin_phrase_row(
    session: AsyncSession,
) -> BuiltinPhraseVersionModel | None:
    return await session.scalar(
        select(BuiltinPhraseVersionModel)
        .order_by(BuiltinPhraseVersionModel.version.desc())
        .limit(1)
    )


async def add_builtin_phrase_version(
    session: AsyncSession,
    *,
    marketing: tuple[str, ...],
    anxiety: tuple[str, ...],
    note: str | None,
    created_by: str,
    now: datetime,
) -> BuiltinPhraseVersionModel:
    latest = await session.scalar(select(func.max(BuiltinPhraseVersionModel.version)))
    row = BuiltinPhraseVersionModel(
        id=uuid4(),
        version=(latest or 0) + 1,
        marketing_terms=list(marketing),
        anxiety_terms=list(anxiety),
        note=note,
        created_by=created_by[:40],
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def list_builtin_phrase_rows(session: AsyncSession) -> Sequence[BuiltinPhraseVersionModel]:
    return (
        await session.scalars(
            select(BuiltinPhraseVersionModel).order_by(BuiltinPhraseVersionModel.version.desc())
        )
    ).all()


async def phrases_for_copy_run(
    session: AsyncSession, run: CopyGenerationRunModel
) -> BuiltinPhrases | None:
    """The phrase lists recorded on the slot run, or None to keep the code defaults."""

    if run.content_slot_selection_id is None:
        return None
    slot_run = await session.scalar(
        select(ContentSlotRunModel)
        .join(ContentSlotSelectionModel, ContentSlotSelectionModel.run_id == ContentSlotRunModel.id)
        .where(ContentSlotSelectionModel.id == run.content_slot_selection_id)
    )
    if slot_run is None or slot_run.builtin_phrase_version_id is None:
        return None
    row = await session.get(BuiltinPhraseVersionModel, slot_run.builtin_phrase_version_id)
    if row is None:
        raise RuntimeError("content slot run references a missing built-in phrase version")
    return phrases_from_row(row)


def defaults() -> BuiltinPhrases:
    return BuiltinPhrases(version=0, marketing=DEFAULT_MARKETING, anxiety=DEFAULT_ANXIETY)
