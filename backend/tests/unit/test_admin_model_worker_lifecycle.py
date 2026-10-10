"""Exercise actual worker loops with an in-flight fake job and registered SIGTERM callback."""

from __future__ import annotations

import asyncio
import importlib
import signal
from argparse import Namespace
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from app import governance_worker_main as governance
from app import official_account_weekly_dag_main as weekly
from app import official_account_worker_main as local
from app.core.config import Settings
from app.infrastructure import official_account_single_runtime as single


@pytest_asyncio.fixture
async def signals(monkeypatch):
    """Never signal the pytest process or replace its real OS handlers."""
    handlers = {}
    removed = []
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        loop, "add_signal_handler", lambda sig, callback: handlers.update({sig: callback})
    )
    monkeypatch.setattr(loop, "remove_signal_handler", lambda sig: removed.append(sig))
    return handlers, removed


class InFlight:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0
        self.events = []

    async def execute(self, *args, **kwargs):
        self.calls += 1
        self.events.append("started")
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.events.append("cancelled")
            raise
        self.events.append("finished")
        return True

    async def dispose(self):
        self.events.append("disposed")


async def _signal_and_drain(coroutine, operation, signals):
    task = asyncio.create_task(coroutine)
    try:
        await asyncio.wait_for(operation.entered.wait(), timeout=2)
        assert signal.SIGTERM in signals[0]
        signals[0][signal.SIGTERM]()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done(), "SIGTERM must await the in-flight operation"
        assert operation.events == ["started"]
        operation.release.set()
        await asyncio.wait_for(task, timeout=2)
        assert operation.calls == 1, "a stopped worker must not start another job"
        assert operation.events == ["started", "finished", "disposed"]
    finally:
        operation.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _engine(monkeypatch, module, operation):
    engine = SimpleNamespace(dispose=AsyncMock(side_effect=operation.dispose))
    monkeypatch.setattr(module, "create_engine", Mock(return_value=engine))
    monkeypatch.setattr(module, "create_session_factory", Mock(return_value=object()))
    return engine


@pytest.mark.asyncio
async def test_local_worker_registers_watcher_and_drains_inflight_article(monkeypatch, signals):
    operation = InFlight()
    settings = Settings(_env_file=None).model_copy(
        update={
            "official_account_local_enabled": True,
            "official_account_local_worker_enabled": True,
            "official_account_local_worker_concurrency": 1,
            "ai_provider_mode": "disabled",
        }
    )
    monkeypatch.setattr(local, "get_settings", Mock(return_value=settings))
    monkeypatch.setattr(local, "configure_logging", Mock())
    watch = Mock()
    monkeypatch.setattr(local, "start_model_key_watch", watch)
    _engine(monkeypatch, local, operation)
    executor = SimpleNamespace(execute_next=operation.execute)
    factory = Mock(return_value=executor)
    monkeypatch.setattr(local, "OfficialAccountLocalExecutor", factory)
    for name in (
        "PostgresOfficialAccountRepository",
        "PostgresVisualIndexRepository",
        "LocalOfficialAccountCatalogMediaProvider",
        "HybridOfficialAccountMediaSemanticRanker",
        "create_official_account_image_quality_auditor",
    ):
        monkeypatch.setattr(local, name, Mock())
    await _signal_and_drain(local.run_worker(), operation, signals)
    watch.assert_called_once_with(settings, service="official-account-local-worker")
    assert factory.call_args.kwargs["live_generator"] is None


@pytest.mark.asyncio
async def test_governance_worker_registers_watcher_and_drains_inflight_job(monkeypatch, signals):
    operation = InFlight()
    settings = Settings(_env_file=None).model_copy(
        update={
            "governance_enabled": True,
            "governance_worker_enabled": True,
            "governance_worker_concurrency": 1,
            "ai_provider_mode": "fake",
        }
    )
    monkeypatch.setattr(governance, "get_settings", Mock(return_value=settings))
    monkeypatch.setattr(governance, "configure_logging", Mock())
    watch = Mock()
    monkeypatch.setattr(governance, "start_model_key_watch", watch)
    _engine(monkeypatch, governance, operation)
    repository = SimpleNamespace(claim=AsyncMock(return_value=object()))
    monkeypatch.setattr(governance, "PostgresGovernanceRepository", Mock(return_value=repository))
    monkeypatch.setattr(governance, "PostgresGovernanceArtifactRepository", Mock())

    @asynccontextmanager
    async def models(_settings):
        assert _settings is settings
        yield object(), object()

    @asynccontextmanager
    async def saver():
        yield object()

    monkeypatch.setattr(governance, "governance_models", models)
    monkeypatch.setattr(
        governance,
        "PostgresGovernanceCheckpointer",
        Mock(return_value=SimpleNamespace(saver=saver)),
    )
    monkeypatch.setattr(governance, "build_governance_graph", Mock())
    monkeypatch.setattr(governance, "execute_claimed_governance_job", operation.execute)
    await _signal_and_drain(governance.run_governance_worker(), operation, signals)
    repository.claim.assert_awaited_once()
    watch.assert_called_once_with(settings, service="governance-worker")


@pytest.mark.asyncio
async def test_weekly_worker_registers_watcher_and_drains_current_batch(monkeypatch, signals):
    operation = InFlight()
    settings = Settings(_env_file=None)
    monkeypatch.setattr(weekly, "get_settings", Mock(return_value=settings))
    watch = Mock()
    monkeypatch.setattr(weekly, "start_model_key_watch", watch)
    _engine(monkeypatch, weekly, operation)
    for name in (
        "PostgresOfficialAccountWeeklyDagRepository",
        "PostgresExecutionGovernanceRepository",
        "PostgresOfficialAccountWeeklyDagGovernance",
        "_handler_registry",
    ):
        monkeypatch.setattr(weekly, name, Mock())

    async def process_once(**kwargs):
        await operation.execute(**kwargs)
        return None

    monkeypatch.setattr(
        weekly,
        "OfficialAccountWeeklyDagService",
        Mock(return_value=SimpleNamespace(process_once=process_once)),
    )
    args = weekly._parser().parse_args(["worker", "--concurrency", "1"])
    await _signal_and_drain(weekly._run(args), operation, signals)
    watch.assert_called_once_with(settings, service="official-account-weekly-dag-worker")
    assert set(signals[1]) == {signal.SIGINT, signal.SIGTERM}


@pytest.mark.asyncio
async def test_weekly_single_producer_starts_watcher_before_routing_and_drains(
    monkeypatch, signals
):
    operation = InFlight()
    settings = Settings(_env_file=None).model_copy(
        update={
            "official_account_single_enabled": True,
            "official_account_single_account_fingerprint": "a" * 64,
            "official_account_local_enabled": True,
            "official_account_local_worker_enabled": True,
        }
    )
    watch = Mock()
    monkeypatch.setattr(weekly, "get_settings", Mock(return_value=settings))
    monkeypatch.setattr(weekly, "start_model_key_watch", watch)
    monkeypatch.setattr(weekly, "create_engine", Mock(side_effect=AssertionError("legacy branch")))
    _engine(monkeypatch, single, operation)
    monkeypatch.setattr(single, "PostgresSingleEditionRepository", Mock())
    for module_name, name in (
        ("app.infrastructure.db.official_account_local", "PostgresOfficialAccountRepository"),
        (
            "app.infrastructure.db.official_account_weekly_production",
            "PostgresWeeklyProductionInputPlanner",
        ),
        ("app.infrastructure.official_account_media", "OfficialAccountLocalMediaResolver"),
        (
            "app.infrastructure.official_account_weekly_production",
            "LocalWeeklyProductionArtifactOwner",
        ),
        ("app.infrastructure.storage.minio_image_store", "MinioImageStore"),
        ("app.infrastructure.storage.minio_snapshot_store", "MinioSnapshotStore"),
        (
            "app.infrastructure.wechat_official_account.catalog_fallback_artifacts",
            "PreparedSingleDraftArtifactOwner",
        ),
    ):
        monkeypatch.setattr(importlib.import_module(module_name), name, Mock())

    def producer(**kwargs):
        watch.assert_called_once_with(settings, service="official-account-weekly-dag-worker")
        return SimpleNamespace(process_once=operation.execute)

    monkeypatch.setattr(
        importlib.import_module("app.application.services.official_account_single_edition"),
        "SingleEditionProducer",
        producer,
    )
    args = weekly._parser().parse_args(["worker"])
    await _signal_and_drain(weekly._run(args), operation, signals)
    assert set(signals[1]) == {signal.SIGINT, signal.SIGTERM}


@pytest.mark.asyncio
@pytest.mark.parametrize("single_enabled", [False, True])
@pytest.mark.parametrize(
    "command,once,drain",
    [
        ("worker", True, False),
        ("worker", False, True),
        ("status", False, False),
        ("single-status", False, False),
    ],
)
async def test_nonpersistent_weekly_commands_do_not_start_model_watcher(
    monkeypatch, single_enabled, command, once, drain
):
    settings = Settings(_env_file=None).model_copy(
        update={"official_account_single_enabled": single_enabled}
    )
    monkeypatch.setattr(weekly, "get_settings", Mock(return_value=settings))
    watch = Mock()
    monkeypatch.setattr(weekly, "start_model_key_watch", watch)
    routed_single = AsyncMock(return_value=0)
    monkeypatch.setattr(single, "run_single_runtime", routed_single)

    class ConstructionReached(Exception):
        pass

    monkeypatch.setattr(weekly, "create_engine", Mock(side_effect=ConstructionReached))
    args = Namespace(command=command, once=once, drain=drain)
    if single_enabled and command == "worker":
        assert await weekly._run(args) == 0
        routed_single.assert_awaited_once_with(settings, plane="producer", once=once)
    else:
        with pytest.raises(ConstructionReached):
            await weekly._run(args)
    watch.assert_not_called()
