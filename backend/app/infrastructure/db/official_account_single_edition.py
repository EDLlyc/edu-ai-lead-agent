"""Short, conflict-safe transactions; no provider or filesystem work in a claim."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.official_account_local import OfficialAccountVersionIdentity
from app.application.ports.official_account_single_edition import SingleEdition
from app.application.ports.official_account_weekly_production import (
    WeeklyProductionInputItem,
    weekly_article_identity_from_snapshot,
)
from app.domain.official_account_single_edition import (
    SINGLE_EDITION_TIMEZONE,
    SINGLE_EDITION_VERSION,
    SingleEditionWindow,
    single_edition_id,
)
from app.domain.official_account_weekly_dag import WeeklyDagArtifact
from app.infrastructure.db.models import (
    CopyGenerationRunModel,
    MaterialPackageModel,
    OfficialAccountArticleRunModel,
    OfficialAccountArticleVersionModel,
    WeChatOfficialAccountDraftItemModel,
    WeChatOfficialAccountDraftJobModel,
)
from app.infrastructure.db.models import (
    OfficialAccountDraftOwnerModel as Owner,
)
from app.infrastructure.db.models import (
    OfficialAccountSingleEditionModel as Row,
)


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def _artifact(value: dict[str, Any] | None) -> WeeklyDagArtifact | None:
    return WeeklyDagArtifact(**value) if value is not None else None


def _snapshot(row: Row) -> SingleEdition:
    return SingleEdition(
        id=row.id,
        account=row.account_fingerprint,
        business_date=row.business_date,
        prepare_at=row.prepare_at,
        deliver_at=row.deliver_at,
        expires_at=row.expires_at,
        identity=weekly_article_identity_from_snapshot(row.article_identity),
        max_attempts=int(row.retry_policy["max_attempts"]),
        retry_base_seconds=int(row.retry_policy["retry_base_seconds"]),
        status=row.status,
        attempts=dict(row.stage_attempts),
        available_at=row.available_at,
        lease_token=row.lease_token,
        selection_artifact=_artifact(row.selection_artifact),
        material_package_id=row.material_package_id,
        event_id=row.event_id,
        article_run_id=row.article_run_id,
        prepared_artifact=_artifact(row.prepared_artifact),
        role=row.role,
        article_fingerprint=row.article_fingerprint,
        content_fingerprint=row.content_fingerprint,
        receipt_fingerprint=row.receipt_fingerprint,
        error_code=row.error_code,
    )


class PostgresSingleEditionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def admit(
        self,
        *,
        account: str,
        window: SingleEditionWindow,
        identity: OfficialAccountVersionIdentity,
        max_attempts: int,
        retry_base_seconds: int,
        now: datetime,
    ) -> SingleEdition | None:
        if not window.prepare_at <= now < window.expires_at:
            return None
        async with self._sessions() as session, session.begin():
            barrier = await session.get(Owner, (account, "history", "import-v1"))
            if (
                barrier is None
                or barrier.status != "ready"
                or barrier.updated_at < now - timedelta(seconds=60)
            ):
                return None
            ident = single_edition_id(account, window.business_date)
            await session.execute(
                insert(Row)
                .values(
                    id=ident,
                    account_fingerprint=account,
                    business_date=window.business_date,
                    timezone=SINGLE_EDITION_TIMEZONE,
                    version=SINGLE_EDITION_VERSION,
                    prepare_at=window.prepare_at,
                    deliver_at=window.deliver_at,
                    expires_at=window.expires_at,
                    article_identity=asdict(identity),
                    retry_policy={
                        "max_attempts": max_attempts,
                        "retry_base_seconds": retry_base_seconds,
                    },
                    status="admitted",
                    stage_attempts={},
                    available_at=now,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing()
            )
            row = await session.get(Row, ident)
            assert row is not None
            # A restart/settings change observes the original frozen date, never rewrites it.
            return _snapshot(row)

    async def claim(
        self, *, account: str, delivery: bool, now: datetime, lease_seconds: int
    ) -> SingleEdition | None:
        async with self._sessions() as session, session.begin():
            if not delivery:
                barrier = await session.get(Owner, (account, "history", "import-v1"))
                if (
                    barrier is None
                    or barrier.status != "ready"
                    or barrier.updated_at < now - timedelta(seconds=60)
                ):
                    return None
            await session.execute(
                update(Row)
                .where(
                    Row.account_fingerprint == account,
                    Row.expires_at <= now,
                    Row.status.in_(("admitted", "generating", "preparing", "ready")),
                    or_(Row.lease_token.is_(None), Row.lease_expires_at <= now),
                )
                .values(
                    status="expired",
                    error_code="single_window_expired",
                    lease_token=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            )
            statuses = (
                ("ready", "delivering") if delivery else ("admitted", "generating", "preparing")
            )
            row = await session.scalar(
                select(Row)
                .where(
                    Row.account_fingerprint == account,
                    Row.status.in_(statuses),
                    Row.available_at <= now,
                    or_(Row.lease_token.is_(None), Row.lease_expires_at <= now),
                    or_(Row.status == "delivering", Row.expires_at > now),
                    Row.deliver_at <= now if delivery else Row.prepare_at <= now,
                )
                .order_by(Row.business_date)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return None
            row.lease_token = uuid4()
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            row.updated_at = now
            if delivery:
                row.status = "delivering"
            return _snapshot(row)

    async def heartbeat(self, edition: SingleEdition, *, now: datetime, lease_seconds: int) -> bool:
        async with self._sessions() as session, session.begin():
            row = await self._owned(session, edition, now)
            if row is None:
                return False
            barrier = await session.get(Owner, (edition.account, "history", "import-v1"))
            if barrier is None or barrier.status != "ready":
                return False
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            return True

    async def _owned(
        self, session: AsyncSession, edition: SingleEdition, now: datetime
    ) -> Row | None:
        return cast(
            Row | None,
            await session.scalar(
                select(Row)
                .where(
                    Row.id == edition.id,
                    Row.lease_token == edition.lease_token,
                    Row.lease_token.is_not(None),
                    Row.lease_expires_at > now,
                )
                .with_for_update()
            ),
        )

    async def save(self, edition: SingleEdition, *, now: datetime) -> bool:
        async with self._sessions() as session, session.begin():
            row = await self._owned(session, edition, now)
            if row is None:
                return False
            row.status = edition.status
            row.stage_attempts = edition.attempts
            row.available_at = edition.available_at
            row.article_run_id = edition.article_run_id
            row.prepared_artifact = (
                asdict(edition.prepared_artifact) if edition.prepared_artifact else None
            )
            row.article_fingerprint = edition.article_fingerprint
            row.content_fingerprint = edition.content_fingerprint
            row.receipt_fingerprint = edition.receipt_fingerprint
            row.error_code = edition.error_code
            row.lease_token = None
            row.lease_expires_at = None
            row.updated_at = now
            if edition.status in {"delivered", "outcome_unknown"}:
                owners = (
                    await session.scalars(
                        select(Owner)
                        .where(
                            Owner.account_fingerprint == edition.account,
                            Owner.owner == str(edition.id),
                        )
                        .with_for_update()
                    )
                ).all()
                for owner in owners:
                    owner.status = (
                        "acknowledged" if edition.status == "delivered" else "outcome_unknown"
                    )
                    owner.updated_at = now
            return True

    async def excluded_events(self, account: str) -> frozenset[UUID]:
        async with self._sessions() as session:
            values = await session.scalars(
                select(Owner.key_value).where(
                    Owner.account_fingerprint == account, Owner.key_kind == "event"
                )
            )
            return frozenset(UUID(value) for value in values)

    async def select(
        self,
        edition: SingleEdition,
        item: WeeklyProductionInputItem,
        artifact: WeeklyDagArtifact,
        *,
        now: datetime,
    ) -> bool:
        async with self._sessions() as session, session.begin():
            row = await self._owned(session, edition, now)
            if row is None:
                return False
            barrier = await session.get(Owner, (edition.account, "history", "import-v1"))
            if (
                barrier is None
                or barrier.status != "ready"
                or barrier.updated_at < now - timedelta(seconds=60)
            ):
                return False
            if not await _reserve(
                session,
                edition.account,
                "event",
                str(item.event_id),
                str(edition.id),
                artifact.fingerprint,
                "reserved",
                now,
            ):
                return False
            row.selection_artifact = asdict(artifact)
            row.material_package_id = item.material_package_id
            row.event_id = item.event_id
            row.role = item.role.value
            row.status = "generating"
            row.lease_token = None
            row.lease_expires_at = None
            row.updated_at = now
            return True

    async def reserve_article(self, edition: SingleEdition, *, now: datetime) -> bool:
        if edition.article_fingerprint is None:
            raise ValueError("single edition article missing")
        async with self._sessions() as session, session.begin():
            if await self._owned(session, edition, now) is None:
                return False
            event = await session.get(Owner, (edition.account, "event", str(edition.event_id)))
            if event is None or event.owner != str(edition.id) or event.status == "conflict":
                return False
            return await _reserve(
                session,
                edition.account,
                "article",
                edition.article_fingerprint,
                str(edition.id),
                fingerprint(str(edition.id)),
                "reserved",
                now,
            )

    async def import_history(
        self, account: str, manual: tuple[tuple[str, str, bool], ...], *, now: datetime
    ) -> None:
        """Consumer-only: opaque verified article/receipt hashes, never private IDs."""
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:account, 479))"),
                {"account": account},
            )
            old = (
                await session.execute(
                    select(
                        WeChatOfficialAccountDraftItemModel.article_fingerprint,
                        WeChatOfficialAccountDraftItemModel.job_id,
                        WeChatOfficialAccountDraftItemModel.status,
                    )
                    .join(WeChatOfficialAccountDraftJobModel)
                    .where(WeChatOfficialAccountDraftJobModel.account_fingerprint == account)
                )
            ).all()
            rows = [
                (fp, f"legacy:{job}", fingerprint([str(job), fp]), status == "succeeded")
                for fp, job, status in old
            ]
            rows.extend(
                (fp, f"manual:{fp}", receipt, acknowledged) for fp, receipt, acknowledged in manual
            )
            for fp, owner, receipt, acknowledged in rows:
                event_ids = (
                    await session.scalars(
                        select(CopyGenerationRunModel.selected_event_id)
                        .join(
                            MaterialPackageModel,
                            MaterialPackageModel.run_id == CopyGenerationRunModel.id,
                        )
                        .join(
                            OfficialAccountArticleRunModel,
                            OfficialAccountArticleRunModel.material_package_id
                            == MaterialPackageModel.id,
                        )
                        .join(
                            OfficialAccountArticleVersionModel,
                            OfficialAccountArticleVersionModel.run_id
                            == OfficialAccountArticleRunModel.id,
                        )
                        .where(OfficialAccountArticleVersionModel.content_fingerprint == fp)
                    )
                ).all()
                events = {event for event in event_ids if event is not None}
                if len(events) != 1:
                    raise ValueError("single_history_event_mapping_unresolved")
                for kind, key in (("article", fp), ("event", str(next(iter(events))))):
                    if not await _reserve(
                        session,
                        account,
                        kind,
                        key,
                        owner,
                        receipt,
                        "acknowledged" if acknowledged else "outcome_unknown",
                        now,
                    ):
                        existing = await session.get(Owner, (account, kind, key))
                        assert existing is not None
                        # Preserve every reservation. Duplicate historical routes remain excluded.
                        existing.status = "conflict"
            barrier = await session.get(Owner, (account, "history", "import-v1"))
            if barrier is None:
                await _reserve(
                    session,
                    account,
                    "history",
                    "import-v1",
                    "history-import-v1",
                    fingerprint(rows),
                    "ready",
                    now,
                )
            else:
                barrier.updated_at = now
                barrier.provenance_fingerprint = fingerprint(rows)
                barrier.status = "ready"

    async def invalidate_history(self, account: str, *, now: datetime) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(Owner)
                .where(
                    Owner.account_fingerprint == account,
                    Owner.key_kind == "history",
                    Owner.key_value == "import-v1",
                )
                .values(status="conflict", updated_at=now)
            )


async def _reserve(
    session: AsyncSession,
    account: str,
    kind: str,
    key: str,
    owner: str,
    provenance: str,
    status: str,
    now: datetime,
) -> bool:
    await session.execute(
        insert(Owner)
        .values(
            account_fingerprint=account,
            key_kind=kind,
            key_value=key,
            owner=owner,
            status=status,
            provenance_fingerprint=provenance,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing()
    )
    row = await session.get(Owner, (account, kind, key), with_for_update=True)
    return row is not None and row.owner == owner and row.status != "conflict"
