"""Load real copy runs as repair workspaces, read-only.

Used by the local repair MCP server (`--copy-run-id`) and by the production shadow job, which
replays the repair agent on drafts that production actually blocked and compares the result with
what production's full regeneration did. Every read runs in a READ ONLY transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.brand_knowledge import BrandEmbeddingRequest, BrandEmbeddingResult
from app.application.ports.copy_generation import StoredDraft
from app.application.services.copy_repair_tools import RepairWorkspace
from app.core.errors import NotFoundError
from app.domain.copy_generation import CopyVersionBundle
from app.infrastructure.db.agent_workbench import PostgresAgentKnowledgeReader
from app.infrastructure.db.copy_generation import _load_stored_drafts
from app.infrastructure.db.models import (
    ContentSlotSelectionModel,
    CopyDraftVersionModel,
    CopyGenerationRunModel,
)
from app.schemas.copy_generation import CopyIssue, MaterialDraft


class _NoBrandSearch:
    """Repair never searches brand text; it loads only the chunks a draft already cites."""

    async def embed_brand(self, request: BrandEmbeddingRequest) -> BrandEmbeddingResult:
        del request
        raise RuntimeError("brand search is not part of copy repair")


@dataclass(frozen=True, slots=True)
class ProductionRepair:
    """What production did with the blocked draft: one full regeneration (draft version 2)."""

    regenerated: bool
    passed: bool
    run_status: str


@dataclass(frozen=True, slots=True)
class BlockedCase:
    run_id: UUID
    business_date: date
    content_slot: str | None
    ordinal: int | None
    version_bundle: CopyVersionBundle
    workspace: RepairWorkspace
    blocking_issues: tuple[CopyIssue, ...]
    production: ProductionRepair


def brand_chunk_ids(draft: MaterialDraft) -> tuple[UUID, ...]:
    return tuple(dict.fromkeys(chunk for claim in draft.claims for chunk in claim.brand_chunk_ids))


def blocking_issues(draft: StoredDraft) -> tuple[CopyIssue, ...]:
    """Error issues from the rules and the audit, merged the way production merges them."""

    seen: set[tuple[str, str | None, str | None]] = set()
    issues: list[CopyIssue] = []
    audit_issues = draft.audit.issues if draft.audit is not None else ()
    for issue in (*draft.validation_issues, *audit_issues):
        key = (issue.code, issue.field, issue.claim_id)
        if issue.severity == "error" and key not in seen:
            seen.add(key)
            issues.append(issue)
    return tuple(issues)


def was_blocked(draft: StoredDraft) -> bool:
    return not draft.validation_passed or (draft.audit is not None and not draft.audit.accepted)


def passed(draft: StoredDraft) -> bool:
    return draft.validation_passed and draft.audit is not None and draft.audit.accepted


async def _read_only(session: AsyncSession) -> None:
    await session.execute(text("SET TRANSACTION READ ONLY"))


async def _workspace_for(
    session_factory: async_sessionmaker[AsyncSession], run_id: UUID, draft: StoredDraft
) -> RepairWorkspace:
    reader = PostgresAgentKnowledgeReader(
        session_factory,
        brand_embeddings=_NoBrandSearch(),
        brand_retrieval_version="not-used-by-copy-repair",
    )
    try:
        context = await reader.load_copy_validation_context(
            copy_run_id=run_id, brand_chunk_ids=brand_chunk_ids(draft.draft)
        )
    except NotFoundError:
        raise RuntimeError(
            "the run or a brand chunk its draft cites is not active on the run's date"
        ) from None
    return RepairWorkspace(
        topic=context.topic,
        brand_context=context.brand_context,
        rule_version=context.rule_version,
        draft=draft.draft,
    )


async def load_repair_workspace(
    session_factory: async_sessionmaker[AsyncSession], run_id: UUID
) -> RepairWorkspace:
    """The newest draft of one copy run as a repair workspace."""

    async with session_factory() as session:
        await _read_only(session)
        drafts = await _load_stored_drafts(session, run_id)
        await session.rollback()
    if not drafts:
        raise RuntimeError("the copy run has no draft")
    return await _workspace_for(session_factory, run_id, drafts[-1])


async def list_regenerated_runs(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    date_from: date,
    date_to: date,
    limit: int,
) -> tuple[UUID, ...]:
    """Selected copy runs in the date range that production repaired (a draft version 2)."""

    repaired = (
        select(CopyDraftVersionModel.run_id)
        .where(CopyDraftVersionModel.version == 2)
        .scalar_subquery()
    )
    statement = (
        select(CopyGenerationRunModel.id)
        .where(
            CopyGenerationRunModel.business_date >= date_from,
            CopyGenerationRunModel.business_date <= date_to,
            CopyGenerationRunModel.decision_kind == "selected",
            CopyGenerationRunModel.id.in_(repaired),
        )
        .order_by(CopyGenerationRunModel.created_at)
        .limit(limit)
    )
    async with session_factory() as session:
        await _read_only(session)
        run_ids = tuple((await session.scalars(statement)).all())
        await session.rollback()
    return run_ids


async def load_blocked_case(
    session_factory: async_sessionmaker[AsyncSession], run_id: UUID
) -> BlockedCase | None:
    """The first draft production blocked, its blocking issues and production's own repair.

    Returns None when draft 1 was not actually blocked (nothing to compare).
    """

    async with session_factory() as session:
        await _read_only(session)
        run = await session.get(CopyGenerationRunModel, run_id)
        if run is None:
            raise NotFoundError("copy generation run")
        slot = None
        if run.content_slot_selection_id is not None:
            slot = await session.get(ContentSlotSelectionModel, run.content_slot_selection_id)
        drafts = await _load_stored_drafts(session, run_id)
        business_date, run_status = run.business_date, run.status
        bundle = CopyVersionBundle.from_metadata(
            run.version_bundle, expected_fingerprint=run.version_fingerprint
        )
        content_slot = slot.content_slot if slot is not None else None
        ordinal = slot.ordinal if slot is not None else None
        await session.rollback()
    first = next((draft for draft in drafts if draft.version == 1), None)
    if first is None or not was_blocked(first):
        return None
    second = next((draft for draft in drafts if draft.version == 2), None)
    return BlockedCase(
        run_id=run_id,
        business_date=business_date,
        content_slot=content_slot,
        ordinal=ordinal,
        version_bundle=bundle,
        workspace=await _workspace_for(session_factory, run_id, first),
        blocking_issues=blocking_issues(first),
        production=ProductionRepair(
            regenerated=second is not None,
            passed=second is not None and passed(second),
            run_status=run_status,
        ),
    )
