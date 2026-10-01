"""Operator review of a held human pick: check or save an edited hook/tags, then push it.

Only a push sends a human pick: it approves the package (the operator's decision is recorded in
`material_reviews`) and enqueues the formal WeCom delivery in the pick's own lane; the long
infographic follows as for any delivered slot package. Daily scheduled slots never pass through
here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.material_package import review_material_package
from app.application.services.wecom_delivery import enqueue_wecom_delivery
from app.core.config import Settings
from app.domain.human_pick_review import CopyRevision, revise_headline_hook_copy
from app.infrastructure.db.content_slot_human_picks import HumanPickRejectedError
from app.infrastructure.db.human_pick_review import (
    load_held_human_pick,
    load_review_context,
    require_editable,
    save_copy_revision,
)
from app.infrastructure.db.models import WeComDeliveryJobModel


@dataclass(frozen=True, slots=True)
class HumanPickCopyResult:
    revision: CopyRevision
    saved: bool
    push_deadline: datetime


async def revise_human_pick_copy(
    session: AsyncSession,
    *,
    run_id: UUID,
    hook: str,
    hashtags: tuple[str, ...],
    reviewer: str,
    dry_run: bool,
    now: datetime,
) -> HumanPickCopyResult:
    """Re-check an edited hook/tags; store it unless ``dry_run`` or it has an error."""

    pick = await load_held_human_pick(session, run_id, lock=not dry_run)
    require_editable(pick, now=now)
    topic, brand_context = await load_review_context(session, pick)
    revision = revise_headline_hook_copy(
        pick.draft.draft,
        topic=topic,
        brand_context=brand_context,
        rule_version=pick.draft_row.rule_version,
        hook=hook,
        hashtags=hashtags,
    )
    saved = False
    if not dry_run and revision.passed:
        await save_copy_revision(session, pick, revision, reviewer=reviewer, now=now)
        await session.commit()
        saved = True
    else:
        await session.rollback()
    return HumanPickCopyResult(revision, saved, pick.run.expires_at)


async def push_human_pick(
    session: AsyncSession,
    *,
    run_id: UUID,
    reviewer: str,
    note: str | None,
    settings: Settings,
    now: datetime,
) -> WeComDeliveryJobModel:
    """Approve the held package and send it to the formal WeCom group now."""

    pick = await load_held_human_pick(session, run_id, lock=True)
    require_editable(pick, now=now)
    if (
        not pick.draft_row.validation_passed
        or pick.package.validation_snapshot.get("passed") is not True
    ):
        raise HumanPickRejectedError(
            "human_pick_copy_invalid", "the copy has a rule error; fix it before pushing"
        )
    edits = pick.package.copy_snapshot.get("operator_edits")
    # Marks which text went out: the last edit if any, else the model's text unchanged.
    pick.package.copy_snapshot = {
        **pick.package.copy_snapshot,
        "operator_push": {
            "pushed_at": now.isoformat(),
            "reviewer": reviewer,
            "edited": bool(edits),
            "copywriting": pick.draft_row.copywriting,
        },
    }
    await review_material_package(
        session=session,
        package_id=pick.package.id,
        decision="approved",
        reviewer=reviewer,
        note=note,
    )
    # Approval alone already releases the package to the automatic sender; enqueueing here
    # returns the same idempotent job and surfaces a configuration problem to the operator.
    return await enqueue_wecom_delivery(
        session=session,
        package_id=pick.package.id,
        recipient_id="default",
        mode="formal",
        include_copy=True,
        include_image=True,
        settings=settings,
        now=now,
    )


__all__ = ["HumanPickCopyResult", "push_human_pick", "revise_human_pick_copy"]
