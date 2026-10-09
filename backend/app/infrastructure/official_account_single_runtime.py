"""Exclusive replacement loops on the existing scheduler/producer/consumer containers."""

from __future__ import annotations

import asyncio
import signal
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import structlog

from app.application.services.official_account_single_edition import failed_progress
from app.core.config import Settings
from app.domain.official_account_single_edition import due_single_edition
from app.infrastructure.db.official_account_single_edition import PostgresSingleEditionRepository
from app.infrastructure.db.session import create_engine, create_session_factory

logger = structlog.get_logger()


async def run_single_runtime(settings: Settings, *, plane: str, once: bool = False) -> int:
    if not settings.official_account_single_enabled or plane not in {
        "scheduler",
        "producer",
        "consumer",
    }:
        raise ValueError("single runtime disabled")
    account = settings.official_account_single_account_fingerprint
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    repository = PostgresSingleEditionRepository(sessions)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        if plane == "scheduler":
            from app.infrastructure.official_account_runtime import (
                official_account_identity_from_settings,
            )

            identity = official_account_identity_from_settings(
                settings, provider="zhipu", model=settings.ai_chat_model
            )
            minimum = settings.official_account_single_min_date
            assert minimum is not None
            while not stop.is_set():
                now = datetime.now(UTC)
                window = due_single_edition(
                    now,
                    minimum_date=minimum,
                    prepare_minutes=settings.official_account_single_prepare_minutes,
                    catchup_hours=settings.official_account_single_catchup_hours,
                )
                result = (
                    await repository.admit(
                        account=account,
                        window=window,
                        identity=identity,
                        max_attempts=settings.official_account_single_max_attempts,
                        retry_base_seconds=settings.official_account_single_retry_base_seconds,
                        now=now,
                    )
                    if window
                    else None
                )
                logger.info(
                    "official_account_single_scheduled",
                    due=window is not None,
                    admitted=result is not None,
                    status=result.status if result else None,
                )
                if once:
                    return 0
                await _wait(stop, 30)
        elif plane == "producer":
            from app.application.ports.official_account_single_edition import SingleEdition
            from app.application.services.official_account_single_edition import (
                SingleEditionProducer,
            )
            from app.domain.official_account_weekly_dag import WeeklyDagArtifact
            from app.infrastructure.db.official_account_local import (
                PostgresOfficialAccountRepository,
            )
            from app.infrastructure.db.official_account_weekly_production import (
                PostgresWeeklyProductionInputPlanner,
            )
            from app.infrastructure.official_account_catalog import (
                LocalOfficialAccountCatalogMediaProvider,
            )
            from app.infrastructure.official_account_media import OfficialAccountLocalMediaResolver
            from app.infrastructure.official_account_weekly_production import (
                LocalWeeklyProductionArtifactOwner,
            )
            from app.infrastructure.storage.minio_image_store import MinioImageStore
            from app.infrastructure.storage.minio_snapshot_store import MinioSnapshotStore
            from app.infrastructure.wechat_official_account.catalog_fallback_artifacts import (
                PreparedSingleDraftArtifactOwner,
            )

            if (
                not settings.official_account_local_enabled
                or not settings.official_account_local_worker_enabled
            ):
                raise ValueError("single producer requires the persisted article worker")
            root = Path(settings.official_account_weekly_artifact_root)
            artifacts = PreparedSingleDraftArtifactOwner(
                session_factory=sessions,
                resolver=OfficialAccountLocalMediaResolver(
                    image_asset_manifest=settings.image_asset_manifest,
                    image_store=MinioImageStore(settings),
                    snapshot_store=MinioSnapshotStore(settings),
                ),
                work_root=root / "prepared",
                inbox_root=Path(settings.wechat_mp_draft_weekly_inbox_root),
                max_image_bytes=settings.wechat_mp_max_image_bytes,
            )

            async def fallback(edition: SingleEdition, now: datetime) -> WeeklyDagArtifact:
                if settings.image_asset_manifest is None:
                    raise ValueError("single_catalog_fallback_catalog_unconfigured")
                artifact = await artifacts.build_fallback_child(
                    edition=edition,
                    now=now,
                    catalog=LocalOfficialAccountCatalogMediaProvider(settings.image_asset_manifest),
                )
                if not await repository.heartbeat(
                    edition, now=datetime.now(UTC), lease_seconds=900
                ):
                    raise ValueError("single_catalog_fallback_lease_lost")
                return artifact

            producer = SingleEditionProducer(
                repository=repository,
                planner=PostgresWeeklyProductionInputPlanner(sessions),
                article_repository=PostgresOfficialAccountRepository(sessions),
                artifacts=artifacts,
                fallback_builder=fallback,
                checkpoints=LocalWeeklyProductionArtifactOwner(root),
                account=account,
            )
            while not stop.is_set():
                worked = await producer.process_once()
                if once:
                    return 0
                await _wait(stop, 1 if worked else 5)
        else:
            # Credentials and HTTP client construction exist only in the publisher process.
            from app.application.ports.wechat_official_account_manual_draft import ManualDraftError
            from app.application.services.wechat_single_edition_delivery import deliver_single
            from app.domain.official_account_weekly_edition import WeeklyArticleRole
            from app.domain.wechat_official_account_draft_jobs import (
                wechat_draft_account_fingerprint,
            )
            from app.infrastructure.db.wechat_layout_templates import (
                layout_template_for_account,
            )
            from app.infrastructure.wechat_official_account.client import (
                WeChatOfficialAccountHttpClient,
            )
            from app.infrastructure.wechat_official_account.manual_journal import (
                LocalManualDraftJournal,
            )
            from app.infrastructure.wechat_official_account.prepared_artifacts import (
                load_prepared_draft_child,
            )

            if not settings.wechat_mp_draft_worker_enabled or settings.wechat_mp_app_id is None:
                raise ValueError("single consumer requires the acknowledged draft worker")
            if (
                wechat_draft_account_fingerprint(settings.wechat_mp_app_id.get_secret_value())
                != account
            ):
                raise ValueError("single consumer account mismatch")
            client = WeChatOfficialAccountHttpClient(settings)
            try:
                while not stop.is_set():
                    journal = None
                    try:
                        journal = LocalManualDraftJournal(
                            Path(settings.wechat_mp_draft_artifact_root), account
                        )
                        await repository.import_history(
                            account, journal.manual_history(account), now=datetime.now(UTC)
                        )
                        edition = await repository.claim(
                            account=account, delivery=True, now=datetime.now(UTC), lease_seconds=300
                        )
                        if edition is not None:
                            if not await repository.reserve_article(edition, now=datetime.now(UTC)):
                                await repository.save(
                                    replace(
                                        edition,
                                        status="failed",
                                        error_code="single_article_already_owned",
                                    ),
                                    now=datetime.now(UTC),
                                )
                                continue
                            assert (
                                edition.prepared_artifact is not None and edition.role is not None
                            )
                            try:
                                prepared = load_prepared_draft_child(
                                    edition.prepared_artifact,
                                    work_root=Path(
                                        settings.wechat_mp_draft_weekly_inbox_root
                                    ).parent
                                    / "weekly-production"
                                    / "prepared",
                                    role=WeeklyArticleRole(edition.role),
                                    max_image_bytes=settings.wechat_mp_max_image_bytes,
                                )
                            except (OSError, ValueError) as error:
                                await repository.save(
                                    failed_progress(
                                        edition,
                                        stage="artifact",
                                        error_code="single_prepared_artifact_invalid",
                                        retryable=isinstance(error, OSError),
                                        now=datetime.now(UTC),
                                    ),
                                    now=datetime.now(UTC),
                                )
                            else:
                                await deliver_single(
                                    repository=repository,
                                    edition=edition,
                                    prepared=prepared,
                                    journal=journal,
                                    client=client,
                                    layout_template_id=await layout_template_for_account(
                                        sessions, account
                                    ),
                                )
                    except (ManualDraftError, ValueError, OSError):
                        await repository.invalidate_history(account, now=datetime.now(UTC))
                        logger.warning(
                            "official_account_single_consumer_blocked",
                            error_code="single_history_or_artifact_invalid",
                        )
                    finally:
                        if journal is not None:
                            journal.close()
                    if once:
                        return 0
                    await _wait(stop, settings.wechat_mp_draft_poll_seconds)
            finally:
                await client.aclose()
        return 0
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
        await engine.dispose()


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass
