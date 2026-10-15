"""Read-only problem signals for the exhibit's 「复盘提升」 screen.

Each signal is a bounded ``SELECT … GROUP BY`` over the last two Beijing weeks: stages that
stopped or failed, keyed by the stage's own safe error code. The screen compares this week with
last week and with the day each optimization went live. Nothing here writes or calls a provider.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import (
    AcquisitionJobModel,
    AcquisitionRunModel,
    ContentSlotRunModel,
    CopyGenerationCheckpointModel,
    CopyGenerationRunModel,
    NewsInfographicJobModel,
    WeComDeliveryJobModel,
)
from app.infrastructure.db.visitor_report import REPORT_TIMEZONE, _local_day

IMPROVEMENT_DAYS = 14
_SLOT_RUN_SCAN_LIMIT = IMPROVEMENT_DAYS * 3 * 6
# At most nine selections a day reach copy; retries and replays stay well below this.
_COPY_RUN_SCAN_LIMIT = IMPROVEMENT_DAYS * 60
_RULES_PER_RUN = 3
_WECOM_BAD_STATUSES = ("partial", "failed", "delivery_unknown")
_INFOGRAPHIC_BAD_STATUSES = ("failed", "result_unknown")


@dataclass(frozen=True, slots=True)
class VisitorIssueSignal:
    """``count`` occurrences of one problem ``code`` on one local ``day``."""

    code: str
    day: date
    count: int


def improvement_window(today: date) -> tuple[date, ...]:
    return tuple(today - timedelta(days=offset) for offset in range(IMPROVEMENT_DAYS - 1, -1, -1))


async def load_issue_signals(
    session: AsyncSession, *, today: date
) -> tuple[VisitorIssueSignal, ...]:
    days = improvement_window(today)
    first, last = days[0], days[-1]
    counts: defaultdict[tuple[str, date], int] = defaultdict(int)

    # A copy stopped for review names its rule(s) in the checkpoint (e.g. unverified_superlative);
    # the run's own error code is often generic (repair_validation_failed), so prefer the rules.
    for day, status, error_code, issue_codes in (
        await session.execute(
            select(
                CopyGenerationRunModel.business_date,
                CopyGenerationRunModel.status,
                CopyGenerationRunModel.error_code,
                CopyGenerationCheckpointModel.issue_codes,
            )
            .outerjoin(
                CopyGenerationCheckpointModel,
                CopyGenerationCheckpointModel.run_id == CopyGenerationRunModel.id,
            )
            .where(
                CopyGenerationRunModel.business_date.between(first, last),
                CopyGenerationRunModel.status.in_(("review_required", "failed")),
            )
            .limit(_COPY_RUN_SCAN_LIMIT)
        )
    ).all():
        rules = [
            code
            for code in (issue_codes if isinstance(issue_codes, list) else [])
            if isinstance(code, str) and code
        ][:_RULES_PER_RUN]
        for code in rules or [error_code or status]:
            counts[(f"copy:{code}", day)] += 1

    wecom_day = _local_day(WeComDeliveryJobModel.completed_at)
    for day, status, error_code, count in (
        await session.execute(
            select(
                wecom_day,
                WeComDeliveryJobModel.status,
                WeComDeliveryJobModel.last_error_code,
                func.count(),
            )
            .where(
                WeComDeliveryJobModel.mode == "formal",
                WeComDeliveryJobModel.status.in_(_WECOM_BAD_STATUSES),
                WeComDeliveryJobModel.completed_at.is_not(None),
                wecom_day.between(first, last),
            )
            .group_by(
                wecom_day, WeComDeliveryJobModel.status, WeComDeliveryJobModel.last_error_code
            )
        )
    ).all():
        counts[(f"wecom:{error_code or status}", day)] += int(count)

    for day, status, error_code, count in (
        await session.execute(
            select(
                NewsInfographicJobModel.business_date,
                NewsInfographicJobModel.status,
                NewsInfographicJobModel.safe_error_code,
                func.count(),
            )
            .where(
                NewsInfographicJobModel.business_date.between(first, last),
                NewsInfographicJobModel.status.in_(_INFOGRAPHIC_BAD_STATUSES),
            )
            .group_by(
                NewsInfographicJobModel.business_date,
                NewsInfographicJobModel.status,
                NewsInfographicJobModel.safe_error_code,
            )
        )
    ).all():
        counts[(f"infographic:{error_code or status}", day)] += int(count)

    acquisition_day = func.coalesce(
        AcquisitionRunModel.business_date, _local_day(AcquisitionJobModel.created_at)
    )
    for day, error_code, count in (
        await session.execute(
            select(acquisition_day, AcquisitionJobModel.error_code, func.count())
            .join(AcquisitionRunModel, AcquisitionRunModel.id == AcquisitionJobModel.run_id)
            .where(
                AcquisitionJobModel.status == "failed",
                acquisition_day.between(first, last),
            )
            .group_by(acquisition_day, AcquisitionJobModel.error_code)
        )
    ).all():
        counts[(f"acquisition:{error_code or 'failed'}", day)] += int(count)

    # A slot's result is its newest regular run, as the news pool and report show it.
    seen: set[tuple[date, str]] = set()
    for run in await session.scalars(
        select(ContentSlotRunModel)
        .where(
            ContentSlotRunModel.trigger.in_(("scheduled", "manual")),
            ContentSlotRunModel.status.in_(("succeeded", "failed")),
            ContentSlotRunModel.business_date.between(first, last),
        )
        .order_by(
            ContentSlotRunModel.target_at.desc(),
            ContentSlotRunModel.created_at.desc(),
            ContentSlotRunModel.id.desc(),
        )
        .limit(_SLOT_RUN_SCAN_LIMIT)
    ):
        identity = (run.business_date, run.content_slot)
        if identity in seen:
            continue
        seen.add(identity)
        if run.status == "failed":
            counts[("slot:failed", run.business_date)] += 1
        elif run.selected_count == 0:
            counts[("slot:empty", run.business_date)] += 1

    for day, count in (
        await session.execute(
            select(ContentSlotRunModel.business_date, func.count())
            .where(
                ContentSlotRunModel.trigger == "human",
                ContentSlotRunModel.business_date.between(first, last),
            )
            .group_by(ContentSlotRunModel.business_date)
        )
    ).all():
        counts[("human:pick", day)] += int(count)

    return tuple(
        VisitorIssueSignal(code=code, day=day, count=count)
        for (code, day), count in sorted(counts.items(), key=lambda item: (item[0][1], item[0][0]))
        if count > 0
    )


__all__ = [
    "IMPROVEMENT_DAYS",
    "REPORT_TIMEZONE",
    "VisitorIssueSignal",
    "improvement_window",
    "load_issue_signals",
]
