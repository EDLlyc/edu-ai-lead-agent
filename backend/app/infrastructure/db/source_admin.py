"""News sources as the 运营后台 sees them, and the rows an operator source is made of.

Callers own the transaction: these functions add and flush, they never commit.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import JobStatus
from app.domain.source_admin import (
    GENERIC_CONNECTOR_VERSION,
    GENERIC_PARSER_VERSION,
    OPERATOR_RATE_LIMIT_SECONDS,
    OPERATOR_RELEVANCE_RULE_VERSION,
    OperatorSourceDraft,
    operator_version_fingerprint,
)
from app.infrastructure.db.models import AcquisitionJobModel, SourceModel, SourceVersionModel

_TERMINAL_JOB_STATUSES = (JobStatus.SUCCEEDED.value, JobStatus.FAILED.value)


@dataclass(frozen=True, slots=True)
class LatestJob:
    status: str
    outcome: str | None
    error_code: str | None
    new_count: int
    filtered_count: int
    duplicate_count: int
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class AdminSourceRow:
    source: SourceModel
    version: SourceVersionModel
    latest_job: LatestJob | None
    new_last_7_days: int


async def list_admin_sources(
    session: AsyncSession, *, now: datetime, include_archived: bool = False
) -> list[AdminSourceRow]:
    latest = (
        select(
            AcquisitionJobModel.source_id,
            AcquisitionJobModel.status,
            AcquisitionJobModel.outcome,
            AcquisitionJobModel.error_code,
            AcquisitionJobModel.new_count,
            AcquisitionJobModel.filtered_count,
            AcquisitionJobModel.duplicate_count,
            AcquisitionJobModel.completed_at,
            func.row_number()
            .over(
                partition_by=AcquisitionJobModel.source_id,
                order_by=AcquisitionJobModel.completed_at.desc(),
            )
            .label("row_number"),
        )
        .where(
            AcquisitionJobModel.status.in_(_TERMINAL_JOB_STATUSES),
            AcquisitionJobModel.completed_at.is_not(None),
        )
        .subquery()
    )
    recent = (
        select(
            AcquisitionJobModel.source_id,
            func.coalesce(func.sum(AcquisitionJobModel.new_count), 0).label("new_count"),
        )
        .where(AcquisitionJobModel.completed_at >= now - timedelta(days=7))
        .group_by(AcquisitionJobModel.source_id)
        .subquery()
    )
    statement = (
        select(
            SourceModel,
            SourceVersionModel,
            latest.c.status,
            latest.c.outcome,
            latest.c.error_code,
            latest.c.new_count,
            latest.c.filtered_count,
            latest.c.duplicate_count,
            latest.c.completed_at,
            recent.c.new_count.label("recent_new_count"),
        )
        .join(SourceVersionModel, SourceVersionModel.id == SourceModel.active_version_id)
        .outerjoin(latest, and_(latest.c.source_id == SourceModel.id, latest.c.row_number == 1))
        .outerjoin(recent, recent.c.source_id == SourceModel.id)
        .order_by(
            SourceModel.archived_at.is_not(None),
            SourceModel.managed_by,
            SourceVersionModel.trust_tier,
            SourceModel.display_name,
        )
    )
    if not include_archived:
        statement = statement.where(SourceModel.archived_at.is_(None))
    rows = (await session.execute(statement)).tuples().all()
    result: list[AdminSourceRow] = []
    for (
        source,
        version,
        status,
        outcome,
        error_code,
        new_count,
        filtered_count,
        duplicate_count,
        completed_at,
        recent_new_count,
    ) in rows:
        job = (
            None
            if status is None
            else LatestJob(
                status=status,
                outcome=outcome,
                error_code=error_code,
                new_count=new_count,
                filtered_count=filtered_count,
                duplicate_count=duplicate_count,
                completed_at=completed_at,
            )
        )
        result.append(
            AdminSourceRow(
                source=source,
                version=version,
                latest_job=job,
                new_last_7_days=int(recent_new_count or 0),
            )
        )
    return result


async def load_source_for_update(
    session: AsyncSession, source_id: UUID
) -> tuple[SourceModel, SourceVersionModel | None] | None:
    source = await session.scalar(
        select(SourceModel).where(SourceModel.id == source_id).with_for_update()
    )
    if source is None:
        return None
    version = (
        None
        if source.active_version_id is None
        else await session.get(SourceVersionModel, source.active_version_id)
    )
    return source, version


async def _unique_slug(session: AsyncSession, host: str) -> str:
    base = "ops-" + re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")[:60]
    for _ in range(5):
        slug = f"{base}-{secrets.token_hex(2)}"
        if await session.scalar(select(SourceModel.id).where(SourceModel.slug == slug)) is None:
            return slug
    raise RuntimeError("could not allocate a unique source slug")


async def ensure_operator_version(
    session: AsyncSession,
    *,
    source: SourceModel,
    draft: OperatorSourceDraft,
    robots_status: str,
    now: datetime,
) -> tuple[SourceVersionModel, bool]:
    """The version for these settings: an existing one with the same fingerprint, or a new one."""

    fingerprint = operator_version_fingerprint(
        draft, robots_status=robots_status, rate_limit_seconds=OPERATOR_RATE_LIMIT_SECONDS
    )
    existing = await session.scalar(
        select(SourceVersionModel).where(
            SourceVersionModel.source_id == source.id,
            SourceVersionModel.config_fingerprint == fingerprint,
        )
    )
    if existing is not None:
        return existing, False
    latest = await session.scalar(
        select(func.max(SourceVersionModel.version)).where(
            SourceVersionModel.source_id == source.id
        )
    )
    version = SourceVersionModel(
        id=uuid5(source.id, fingerprint),
        source_id=source.id,
        version=(latest or 0) + 1,
        trust_tier=draft.tier,
        connector_key=draft.config.connector_key,
        entry_url=draft.entry_url,
        allowed_hosts=[draft.host],
        allowed_path_prefixes=["/"],
        cadence="daily",
        timezone="Asia/Shanghai",
        language="zh-CN",
        robots_status=robots_status,
        terms_reviewed_at=now,
        rate_limit_seconds=OPERATOR_RATE_LIMIT_SECONDS,
        connector_version=GENERIC_CONNECTOR_VERSION,
        parser_version=GENERIC_PARSER_VERSION,
        relevance_rule_version=OPERATOR_RELEVANCE_RULE_VERSION,
        allow_http_fallback=False,
        topic_priority_policy=None,
        connector_config=draft.config.to_json(),
        config_fingerprint=fingerprint,
        created_at=now,
    )
    session.add(version)
    await session.flush()
    return version, True


async def add_operator_source(
    session: AsyncSession,
    *,
    draft: OperatorSourceDraft,
    robots_status: str,
    owner: str,
    now: datetime,
) -> tuple[SourceModel, SourceVersionModel]:
    """A new operator source; it starts disabled until the operator turns it on."""

    source = SourceModel(
        id=uuid4(),
        slug=await _unique_slug(session, draft.host),
        display_name=draft.display_name,
        organization_type=draft.organization_type,
        enabled=False,
        owner=owner,
        managed_by="operator",
        enabled_set_by="operator",
        created_at=now,
        updated_at=now,
    )
    session.add(source)
    await session.flush()
    version, _ = await ensure_operator_version(
        session, source=source, draft=draft, robots_status=robots_status, now=now
    )
    source.active_version_id = version.id
    await session.flush()
    return source, version


__all__ = [
    "AdminSourceRow",
    "LatestJob",
    "add_operator_source",
    "ensure_operator_version",
    "list_admin_sources",
    "load_source_for_update",
]
