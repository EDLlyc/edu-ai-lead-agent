"""Operator human picks: one already-decided news item that runs the full slot pipeline.

A pick is persisted as a one-item slot run (`trigger='human'`) with a copy of the AI score row and
one selection. The existing reconcilers then generate copy and the image/material package; the
package also enters the single-edition candidate scan. Since 2026-09-30 the package is held for
the operator (review, optional hook/tag edit, push; `human_pick_review`): only a pushed pick gets
its WeCom delivery in its own lane and then the long infographic. Nothing here calls a provider.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.domain.content_slots import HUMAN_PICK_POLICY_VERSION, HUMAN_PICK_TRIGGER
from app.infrastructure.db.content_slots import _lock_business_date
from app.infrastructure.db.models import (
    ContentSlotRunModel,
    ContentSlotScoreModel,
    ContentSlotSelectionModel,
    CopyGenerationRunModel,
    MaterialPackageModel,
    WeComDeliveryJobModel,
)

# A held pick waits for the operator and can be pushed until 22:30 business time. Downstream
# reconcilers only look at the current business date, and the long infographic follows the push
# by a few minutes, so the whole pick must finish that day. Picks close at the same time.
HUMAN_PICK_PUSH_DEADLINE_LOCAL_TIME = time(22, 30)
HUMAN_PICK_LATEST_LOCAL_TIME = HUMAN_PICK_PUSH_DEADLINE_LOCAL_TIME
_BLOCKING_DELIVERY_STATUSES = ("queued", "running", "partial", "delivery_unknown", "delivered")
_BLOCKING_CHILD_STATUSES = ("running", "delivered", "unknown")
_SCORE_OVERRIDES = frozenset(
    {
        "id",
        "run_id",
        "created_at",
        "rank",
        "deterministic_rank",
        "selected_ordinal",
        "eligible",
        "veto_codes",
        "same_day_excluded",
        "same_day_exclusion_reason",
    }
)


class HumanPickRejectedError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 409)


@dataclass(frozen=True, slots=True)
class HumanPickResult:
    run: ContentSlotRunModel
    selection: ContentSlotSelectionModel
    created: bool


async def create_human_pick(
    session: AsyncSession,
    *,
    source_run_id: UUID,
    event_id: UUID,
    note: str | None,
    now: datetime,
    timezone: str,
    scoring_profile: str,
) -> HumanPickResult:
    if now.tzinfo is None:
        raise ValueError("human pick time must be timezone-aware")
    local_now = now.astimezone(ZoneInfo(timezone))
    business_date = local_now.date()
    await _lock_business_date(session, business_date, timezone)

    existing = await _existing_pick(session, business_date, timezone, event_id)
    if existing is not None:
        return existing
    if local_now.time() >= HUMAN_PICK_LATEST_LOCAL_TIME:
        raise HumanPickRejectedError(
            "human_pick_too_late", "human picks close at 22:30 business time"
        )

    source = await session.scalar(
        select(ContentSlotScoreModel).where(
            ContentSlotScoreModel.run_id == source_run_id,
            ContentSlotScoreModel.event_id == event_id,
        )
    )
    source_run = await session.get(ContentSlotRunModel, source_run_id)
    if source is None or source_run is None:
        raise NotFoundError("content slot candidate")

    selected_today = await session.scalar(
        select(ContentSlotSelectionModel.id)
        .where(
            ContentSlotSelectionModel.business_date == business_date,
            ContentSlotSelectionModel.timezone == timezone,
            ContentSlotSelectionModel.selected_event_id == event_id,
        )
        .limit(1)
    )
    if selected_today is not None:
        raise HumanPickRejectedError(
            "human_pick_already_selected", "the news item is already selected today"
        )
    if await _has_formal_delivery(session, event_id):
        raise HumanPickRejectedError(
            "human_pick_already_delivered", "the news item already has a formal WeCom delivery"
        )
    busy = await session.scalar(
        select(ContentSlotRunModel.id)
        .where(
            ContentSlotRunModel.business_date == business_date,
            ContentSlotRunModel.timezone == timezone,
            ContentSlotRunModel.trigger != HUMAN_PICK_TRIGGER,
            ContentSlotRunModel.status.in_(("queued", "running")),
        )
        .limit(1)
    )
    if busy is not None:
        # The scheduled executor rechecks same-day state under the lock and fails the whole slot
        # on a late conflict, so never race it.
        raise HumanPickRejectedError(
            "human_pick_slot_busy", "scheduled topic selection is running; retry in a minute"
        )
    base = await session.scalar(
        select(ContentSlotRunModel)
        .where(
            ContentSlotRunModel.business_date == business_date,
            ContentSlotRunModel.timezone == timezone,
            ContentSlotRunModel.scoring_profile == scoring_profile,
            ContentSlotRunModel.trigger != HUMAN_PICK_TRIGGER,
            ContentSlotRunModel.status == "succeeded",
        )
        .order_by(ContentSlotRunModel.target_at.desc(), ContentSlotRunModel.created_at.desc())
        .limit(1)
    )
    if base is None:
        raise HumanPickRejectedError(
            "human_pick_no_lineage",
            "no scheduled slot selection has succeeded today yet",
        )

    run_id = uuid4()
    policy_snapshot = _policy_snapshot(
        base=base, source_run=source_run, source=source, note=note, now=now
    )
    run = ContentSlotRunModel(
        id=run_id,
        trigger=HUMAN_PICK_TRIGGER,
        business_date=business_date,
        timezone=timezone,
        content_slot=base.content_slot,
        scoring_profile=scoring_profile,
        acquisition_run_id=base.acquisition_run_id,
        governance_run_id=base.governance_run_id,
        governed_event_cutoff=base.governed_event_cutoff,
        config_id=base.config_id,
        config_fingerprint=base.config_fingerprint,
        config_snapshot=base.config_snapshot,
        rerank_config_fingerprint=base.rerank_config_fingerprint,
        rerank_config_snapshot=base.rerank_config_snapshot,
        slot_policy_version=HUMAN_PICK_POLICY_VERSION,
        slot_policy_fingerprint=_fingerprint(policy_snapshot),
        slot_policy_snapshot=policy_snapshot,
        preparation_at=now - timedelta(seconds=1),
        target_at=now,
        expires_at=human_pick_push_deadline(business_date, timezone),
        item_limit=1,
        status="succeeded",
        total_scores=1,
        eligible_scores=1,
        selected_count=1,
        unfilled_count=0,
        unfilled_reason_codes=[],
        started_at=now,
        completed_at=now,
        operator_keyword_version_id=base.operator_keyword_version_id,
    )
    score_values: dict[str, Any] = {
        column.key: getattr(source, column.key)
        for column in ContentSlotScoreModel.__table__.columns
        if column.key not in _SCORE_OVERRIDES
    }
    # The operator overrides the AI verdict for this one item; the original verdict stays in the
    # AI run and in the pick's policy snapshot.
    score = ContentSlotScoreModel(
        **score_values,
        id=uuid4(),
        run_id=run_id,
        rank=1,
        deterministic_rank=1,
        selected_ordinal=1,
        eligible=True,
        veto_codes=[],
        same_day_excluded=False,
        same_day_exclusion_reason=None,
    )
    selection = ContentSlotSelectionModel(
        id=uuid4(),
        run_id=run_id,
        score_id=score.id,
        business_date=business_date,
        timezone=timezone,
        content_slot=base.content_slot,
        ordinal=1,
        selected_event_id=source.event_id,
        selected_event_version_id=source.event_version_id,
    )
    session.add(run)
    await session.flush()
    session.add(score)
    await session.flush()
    session.add(selection)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raced = await _existing_pick(session, business_date, timezone, event_id)
        if raced is None:
            raise HumanPickRejectedError(
                "human_pick_already_selected", "the news item is already selected today"
            ) from None
        return raced
    return HumanPickResult(run=run, selection=selection, created=True)


async def _existing_pick(
    session: AsyncSession, business_date: Any, timezone: str, event_id: UUID
) -> HumanPickResult | None:
    row = (
        await session.execute(
            select(ContentSlotRunModel, ContentSlotSelectionModel)
            .join(
                ContentSlotSelectionModel,
                ContentSlotSelectionModel.run_id == ContentSlotRunModel.id,
            )
            .where(
                ContentSlotRunModel.trigger == HUMAN_PICK_TRIGGER,
                ContentSlotSelectionModel.business_date == business_date,
                ContentSlotSelectionModel.timezone == timezone,
                ContentSlotSelectionModel.selected_event_id == event_id,
            )
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return HumanPickResult(run=row[0], selection=row[1], created=False)


async def _has_formal_delivery(session: AsyncSession, event_id: UUID) -> bool:
    job_id = await session.scalar(
        select(WeComDeliveryJobModel.id)
        .join(
            MaterialPackageModel,
            MaterialPackageModel.id == WeComDeliveryJobModel.material_package_id,
        )
        .join(CopyGenerationRunModel, CopyGenerationRunModel.id == MaterialPackageModel.run_id)
        .where(
            CopyGenerationRunModel.selected_event_id == event_id,
            WeComDeliveryJobModel.mode == "formal",
            or_(
                WeComDeliveryJobModel.status.in_(_BLOCKING_DELIVERY_STATUSES),
                WeComDeliveryJobModel.text_status.in_(_BLOCKING_CHILD_STATUSES),
                WeComDeliveryJobModel.image_status.in_(_BLOCKING_CHILD_STATUSES),
            ),
        )
        .limit(1)
    )
    return job_id is not None


def _policy_snapshot(
    *,
    base: ContentSlotRunModel,
    source_run: ContentSlotRunModel,
    source: ContentSlotScoreModel,
    note: str | None,
    now: datetime,
) -> dict[str, Any]:
    return {
        "policy_version": HUMAN_PICK_POLICY_VERSION,
        # Kept so any reader that parses a slot ranking policy still finds a valid bound.
        "maximum_affinity": base.slot_policy_snapshot.get("maximum_affinity", 0.25),
        "lineage_run_id": str(base.id),
        "picked_at": now.isoformat(),
        "note": note,
        "source": {
            "run_id": str(source_run.id),
            "business_date": source_run.business_date.isoformat(),
            "content_slot": source_run.content_slot,
            "score_id": str(source.id),
            "rank": source.rank,
            "selected_ordinal": source.selected_ordinal,
        },
        "ai_verdict": {
            "total": source.total,
            "threshold": source.threshold,
            "passes_threshold": source.passes_threshold,
            "eligible": source.eligible,
            "veto_codes": list(source.veto_codes),
            "same_day_excluded": source.same_day_excluded,
            "same_day_exclusion_reason": source.same_day_exclusion_reason,
        },
    }


def human_pick_push_deadline(business_date: date, timezone: str) -> datetime:
    """The last moment a held pick of ``business_date`` may be pushed (22:30 business time)."""

    return datetime.combine(
        business_date, HUMAN_PICK_PUSH_DEADLINE_LOCAL_TIME, tzinfo=ZoneInfo(timezone)
    ).astimezone(UTC)


def _fingerprint(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "HUMAN_PICK_PUSH_DEADLINE_LOCAL_TIME",
    "HumanPickRejectedError",
    "HumanPickResult",
    "create_human_pick",
    "human_pick_push_deadline",
]
