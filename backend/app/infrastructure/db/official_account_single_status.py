"""Read-only, bounded production status without credentials, payloads or remote clients."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.official_account_single_edition import edition_window
from app.domain.official_account_visual_pipeline import NATIVE_VISUAL_PIPELINE_VERSIONS
from app.infrastructure.db.models import OfficialAccountArticleRunModel as Run
from app.infrastructure.db.models import OfficialAccountDraftOwnerModel as Owner
from app.infrastructure.db.models import OfficialAccountSingleEditionModel as Edition


async def single_edition_status(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    now: datetime,
) -> dict[str, object]:
    if now.utcoffset() is None:
        raise ValueError("single status clock must be aware")
    account = settings.official_account_single_account_fingerprint
    async with sessions() as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        queue = {
            status: count
            for status, count in (
                await session.execute(
                    select(Edition.status, func.count())
                    .where(Edition.account_fingerprint == account)
                    .group_by(Edition.status)
                )
            ).all()
        }
        active = await session.scalar(
            select(func.count())
            .select_from(Edition)
            .where(
                Edition.account_fingerprint == account,
                Edition.lease_token.is_not(None),
                Edition.lease_expires_at > now,
            )
        )
        stale = await session.scalar(
            select(func.count())
            .select_from(Edition)
            .where(
                Edition.account_fingerprint == account,
                Edition.lease_token.is_not(None),
                Edition.lease_expires_at <= now,
            )
        )
        rows = (
            await session.execute(
                select(Edition, Run.status, Run.error_code)
                .outerjoin(Run, Run.id == Edition.article_run_id)
                .where(Edition.account_fingerprint == account)
                .order_by(Edition.business_date.desc())
                .limit(10)
            )
        ).all()
        barrier = await session.get(Owner, (account, "history", "import-v1"))
        history_ready = (
            barrier is not None
            and barrier.status == "ready"
            and barrier.updated_at >= now - timedelta(seconds=60)
        )
        today = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
        minimum = settings.official_account_single_min_date
        day = max(today, minimum) if minimum else today
        next_window = None
        for offset in range(8):
            target = day + timedelta(days=offset)
            if target.weekday() not in {0, 2, 4} or any(
                row.business_date == target for row, _, _ in rows
            ):
                continue
            window = edition_window(
                target,
                prepare_minutes=settings.official_account_single_prepare_minutes,
                catchup_hours=settings.official_account_single_catchup_hours,
            )
            if window.expires_at <= now:
                continue
            next_window = {
                "business_date": target.isoformat(),
                "prepare_at": window.prepare_at.isoformat(),
                "deliver_at": window.deliver_at.isoformat(),
                "expires_at": window.expires_at.isoformat(),
            }
            break
        enabled = settings.official_account_single_enabled
        return {
            "version": "single-edition-readonly-status-v1",
            "as_of": now.isoformat(),
            "single_enabled": enabled,
            "contract_scope": "local_automation_not_remote_publication_readback",
            "configured_visual_pipeline_version": (
                settings.official_account_local_visual_pipeline_version
            ),
            "configuration_scope": "current_process_environment",
            "configured_planes": {
                "scheduler": enabled,
                "producer": enabled
                and settings.official_account_local_enabled
                and settings.official_account_local_worker_enabled,
                "consumer": enabled and settings.wechat_mp_draft_worker_enabled,
            },
            "legacy_mutual_exclusion": not (
                settings.official_account_weekly_scheduler_enabled
                or settings.official_account_weekly_worker_enabled
                or settings.wechat_mp_draft_auto_enqueue_enabled
            ),
            "next_window": next_window if enabled else None,
            "visual_pipeline_version": settings.official_account_local_visual_pipeline_version,
            "history_ready": history_ready,
            "queue": queue,
            "leases": {"active": active, "stale": stale},
            "recent": [
                {
                    "business_date": row.business_date.isoformat(),
                    "status": row.status,
                    "error_code": row.error_code,
                    "article_status": article_status,
                    "article_error_code": article_error,
                    "visual_origin": "approved_catalog_fallback"
                    if row.prepared_artifact
                    and row.prepared_artifact.get("media_type")
                    == "application/vnd.wechat.approved-catalog-fallback-child+directory"
                    else "generated"
                    if row.prepared_artifact
                    and row.prepared_artifact.get("media_type")
                    == "application/vnd.wechat.prepared-draft-child+directory"
                    and row.article_identity.get("visual_pipeline_version")
                    in NATIVE_VISUAL_PIPELINE_VERSIONS
                    else None,
                    "receipt_acknowledged": row.receipt_fingerprint is not None,
                }
                for row, article_status, article_error in rows
            ],
            "draft_only": True,
            "publication_state": "not_checked",
            "publishing_capability": False,
            "readonly": True,
        }
