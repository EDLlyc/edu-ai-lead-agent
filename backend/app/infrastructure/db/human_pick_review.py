"""Operator review of a held human pick: load it, save an edited hook/tags, push it.

A human pick's package is held (no automatic WeCom delivery, see `wecom_delivery`) until the
operator pushes it. Until then the operator may replace the hook sentence and hashtags; the
accepted draft, its deterministic validation and the package snapshot are updated together, so
the long infographic (which requires the draft and the package to agree) still works. The first
AI text and every edit are kept in `copy_snapshot["operator_edits"]`; the LLM audit is not
repeated for an edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.copy_generation import StoredDraft
from app.core.errors import NotFoundError
from app.domain.content_slots import HUMAN_PICK_TRIGGER
from app.domain.copy_generation import (
    ENGLISH_EVIDENCE_COPY_PIPELINE_VERSION,
    ActiveBrandContext,
    LockedTopicContext,
)
from app.domain.human_pick_review import CopyRevision
from app.domain.value_objects import stable_key
from app.infrastructure.db.content_slot_human_picks import HumanPickRejectedError
from app.infrastructure.db.copy_generation import (
    _add_issues,
    _load_stored_drafts,
    load_brand_context_by_chunk_ids,
    load_governed_event_evidence,
    load_locked_topic_origin,
)
from app.infrastructure.db.models import (
    ContentSlotRunModel,
    ContentSlotSelectionModel,
    CopyDraftVersionModel,
    CopyGenerationAttemptModel,
    CopyGenerationRunModel,
    CopyIssueModel,
    CopyValidationResultModel,
    EventClusterVersionModel,
    MaterialPackageModel,
    WeComDeliveryJobModel,
)

_READY_PACKAGE_STATUSES = ("awaiting_manual_use", "completed")


@dataclass(frozen=True, slots=True)
class HeldHumanPick:
    run: ContentSlotRunModel
    selection: ContentSlotSelectionModel
    copy_run: CopyGenerationRunModel
    draft: StoredDraft
    draft_row: CopyDraftVersionModel
    package: MaterialPackageModel
    pushed: bool


async def load_held_human_pick(
    session: AsyncSession, run_id: UUID, *, lock: bool = False
) -> HeldHumanPick:
    """The pick's accepted copy and ready package; ``lock`` takes the package row for update."""

    run = await session.get(ContentSlotRunModel, run_id)
    if run is None or run.trigger != HUMAN_PICK_TRIGGER:
        raise NotFoundError("human pick")
    selection = await session.scalar(
        select(ContentSlotSelectionModel).where(ContentSlotSelectionModel.run_id == run.id)
    )
    if selection is None:
        raise NotFoundError("human pick")
    copy_run = await session.scalar(
        select(CopyGenerationRunModel).where(
            CopyGenerationRunModel.content_slot_selection_id == selection.id
        )
    )
    if (
        copy_run is None
        or copy_run.status != "accepted"
        or copy_run.active_draft_version_id is None
    ):
        raise HumanPickRejectedError("human_pick_not_ready", "the copy is not ready yet")
    package_query = select(MaterialPackageModel).where(MaterialPackageModel.run_id == copy_run.id)
    if lock:
        package_query = package_query.with_for_update()
    package = await session.scalar(package_query)
    if package is None or package.status not in _READY_PACKAGE_STATUSES:
        raise HumanPickRejectedError("human_pick_not_ready", "the picture is not ready yet")
    draft_query = select(CopyDraftVersionModel).where(
        CopyDraftVersionModel.id == copy_run.active_draft_version_id
    )
    if lock:
        draft_query = draft_query.with_for_update()
    draft_row = await session.scalar(draft_query)
    draft = next(
        (
            stored
            for stored in await _load_stored_drafts(session, copy_run.id)
            if stored.id == copy_run.active_draft_version_id
        ),
        None,
    )
    if draft_row is None or draft is None or package.draft_version_id != draft_row.id:
        raise HumanPickRejectedError(
            "human_pick_not_ready", "the package does not match the accepted copy"
        )
    pushed = bool(
        await session.scalar(
            select(
                exists().where(
                    WeComDeliveryJobModel.material_package_id == package.id,
                    WeComDeliveryJobModel.mode == "formal",
                )
            )
        )
    )
    return HeldHumanPick(run, selection, copy_run, draft, draft_row, package, pushed)


def require_editable(pick: HeldHumanPick, *, now: datetime) -> None:
    """A pick may be edited or pushed only while held, reviewable and before its deadline."""

    if pick.pushed or pick.package.review_status == "approved":
        raise HumanPickRejectedError("human_pick_already_pushed", "the pick was already pushed")
    if pick.package.review_status == "rejected":
        raise HumanPickRejectedError("human_pick_rejected", "the pick was rejected")
    if now >= pick.run.expires_at:
        raise HumanPickRejectedError(
            "human_pick_expired", "held picks can be pushed until 22:30 on their day"
        )


async def load_review_context(
    session: AsyncSession, pick: HeldHumanPick
) -> tuple[LockedTopicContext, tuple[ActiveBrandContext, ...]]:
    """The locked topic and brand context the draft was validated against at generation."""

    copy_run = pick.copy_run
    if copy_run.selected_event_version_id is None or copy_run.selected_event_id is None:
        raise HumanPickRejectedError("human_pick_not_ready", "the copy has no locked news item")
    version = await session.get(EventClusterVersionModel, copy_run.selected_event_version_id)
    if version is None or version.event_id != copy_run.selected_event_id:
        raise HumanPickRejectedError("human_pick_not_ready", "the locked news item is gone")
    evidence = await load_governed_event_evidence(
        session,
        version,
        include_governed_statement=(
            copy_run.pipeline_version == ENGLISH_EVIDENCE_COPY_PIPELINE_VERSION
        ),
    )
    raw_summary = version.summary_projection.get("summary")
    topic = LockedTopicContext(
        origin=await load_locked_topic_origin(session, copy_run),
        business_date=copy_run.business_date,
        timezone=copy_run.timezone,
        scoring_profile=copy_run.scoring_profile,
        decision_kind=copy_run.decision_kind,
        selected_event_id=copy_run.selected_event_id,
        selected_event_version_id=copy_run.selected_event_version_id,
        no_topic_code=None,
        title=version.representative_title,
        summary=raw_summary if isinstance(raw_summary, str) else None,
        evidence=evidence,
    )
    attempt = await session.scalar(
        select(CopyGenerationAttemptModel).where(
            CopyGenerationAttemptModel.draft_version_id == pick.draft_row.id,
            CopyGenerationAttemptModel.capability == "generation",
            CopyGenerationAttemptModel.status == "succeeded",
        )
    )
    raw_ids = attempt.safe_metadata.get("brand_chunk_ids") if attempt is not None else None
    brand_context = (
        await load_brand_context_by_chunk_ids(session, raw_ids)
        if isinstance(raw_ids, list) and raw_ids
        else ()
    )
    return topic, brand_context


def _issue_snapshot(revision: CopyRevision) -> list[dict[str, Any]]:
    return [
        {
            "code": issue.code,
            "severity": issue.severity,
            "field": issue.field,
            "claim_id": issue.claim_id,
            "message": issue.message,
        }
        for issue in revision.issues
    ]


async def save_copy_revision(
    session: AsyncSession,
    pick: HeldHumanPick,
    revision: CopyRevision,
    *,
    reviewer: str,
    now: datetime,
) -> None:
    """Store a passing operator edit on the accepted draft and the package, together."""

    if not revision.passed or revision.copywriting is None:
        raise ValueError("only a passing revision can be stored")
    draft_row, package = pick.draft_row, pick.package
    rule_version = draft_row.rule_version
    history = list(package.copy_snapshot.get("operator_edits") or [])
    history.append(
        {
            "edited_at": now.isoformat(),
            "reviewer": reviewer,
            "hook": revision.hook,
            "hashtags": list(revision.hashtags),
            "previous_copywriting": draft_row.copywriting,
            "llm_audit_repeated": False,
        }
    )
    fingerprint = stable_key(
        draft_row.id,
        rule_version,
        "operator-edit",
        now.isoformat(),
        *(f"{issue.code}:{issue.field}:{issue.claim_id}" for issue in revision.issues),
    )

    draft_row.copywriting = revision.copywriting
    draft_row.validation_passed = True
    await session.execute(
        delete(CopyIssueModel).where(
            CopyIssueModel.draft_version_id == draft_row.id,
            CopyIssueModel.stage == "deterministic",
        )
    )
    _add_issues(
        session, draft_version_id=draft_row.id, stage="deterministic", issues=revision.issues
    )
    validation = await session.scalar(
        select(CopyValidationResultModel)
        .where(CopyValidationResultModel.draft_version_id == draft_row.id)
        .with_for_update()
    )
    if validation is not None:
        validation.passed = True
        validation.result_fingerprint = fingerprint
    package.copy_snapshot = {
        **package.copy_snapshot,
        "copywriting": revision.copywriting,
        "operator_edits": history,
    }
    package.validation_snapshot = {
        **package.validation_snapshot,
        "passed": True,
        "rule_version": rule_version,
        "result_fingerprint": fingerprint,
        "issues": _issue_snapshot(revision),
        "operator_edited": True,
    }
    await session.flush()


__all__ = [
    "HeldHumanPick",
    "load_held_human_pick",
    "load_review_context",
    "require_editable",
    "save_copy_revision",
]
