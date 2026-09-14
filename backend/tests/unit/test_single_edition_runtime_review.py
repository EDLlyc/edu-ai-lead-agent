from __future__ import annotations

import importlib
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from app.application.ports.wechat_official_account import WeChatMpTransientError
from app.application.ports.wechat_official_account_manual_draft import ManualDraftError
from app.application.services.wechat_single_edition_delivery import deliver_single
from app.domain.official_account_weekly_dag import WeeklyDagArtifact
from app.domain.wechat_official_account_draft_jobs import wechat_draft_account_fingerprint
from app.infrastructure import official_account_single_runtime as runtime
from app.infrastructure.wechat_official_account.manual_journal import LocalManualDraftJournal
from pydantic import SecretStr
from test_official_account_single_edition import (
    ACCOUNT,
    NOW,
    Client,
    Repository,
    edition,
    prepared,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ValueError("bad child"), OSError("unavailable child")])
async def test_consumer_child_failure_is_bounded_and_does_not_invalidate_history(
    monkeypatch, tmp_path, failure
):
    account = wechat_draft_account_fingerprint("synthetic-account")
    value = edition(
        account=account,
        role="application_case",
        attempts={"artifact": 2},
        prepared_artifact=WeeklyDagArtifact(
            opaque_ref="test-artifact-v1:" + "a" * 64,
            fingerprint="a" * 64,
            media_type="application/json",
            byte_size=1,
        ),
    )
    repository = Repository()
    repository.import_history = AsyncMock()
    repository.claim = AsyncMock(return_value=value)
    repository.reserve_article = AsyncMock(return_value=True)
    repository.invalidate_history = AsyncMock()
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(runtime, "create_engine", Mock(return_value=engine))
    monkeypatch.setattr(runtime, "create_session_factory", Mock(return_value=object()))
    monkeypatch.setattr(runtime, "PostgresSingleEditionRepository", Mock(return_value=repository))
    client_module = importlib.import_module("app.infrastructure.wechat_official_account.client")
    client = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(client_module, "WeChatOfficialAccountHttpClient", Mock(return_value=client))
    artifact_module = importlib.import_module(
        "app.infrastructure.wechat_official_account.prepared_artifacts"
    )
    load = Mock(side_effect=failure)
    monkeypatch.setattr(artifact_module, "load_prepared_draft_child", load)
    settings = SimpleNamespace(
        official_account_single_enabled=True,
        official_account_single_account_fingerprint=account,
        wechat_mp_draft_worker_enabled=True,
        wechat_mp_app_id=SecretStr("synthetic-account"),
        wechat_mp_draft_artifact_root=str(tmp_path / "journal"),
        wechat_mp_draft_weekly_inbox_root=str(tmp_path / "input" / "weekly-inbox"),
        wechat_mp_max_image_bytes=1024,
    )
    assert await runtime.run_single_runtime(settings, plane="consumer", once=True) == 0
    repository.import_history.assert_awaited_once()
    repository.invalidate_history.assert_not_awaited()
    assert repository.value.status == "failed"
    assert repository.value.attempts["artifact"] == 3
    assert repository.value.error_code == "single_prepared_artifact_invalid"
    assert load.call_args.kwargs["work_root"] == tmp_path / "input/weekly-production/prepared"
    client.aclose.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "module_name,plane",
    [
        ("app.official_account_weekly_scheduler_main", "scheduler"),
        ("app.official_account_weekly_dag_main", "producer"),
        ("app.wechat_official_account_draft_main", "consumer"),
    ],
)
async def test_single_entrypoints_return_before_legacy_construction(
    monkeypatch, module_name, plane
):
    module = importlib.import_module(module_name)
    settings = SimpleNamespace(official_account_single_enabled=True, app_env="development")
    monkeypatch.setattr(module, "get_settings", Mock(return_value=settings))
    if hasattr(module, "configure_logging"):
        monkeypatch.setattr(module, "configure_logging", Mock())
    legacy_engine = Mock(side_effect=AssertionError("legacy constructor must be unreachable"))
    monkeypatch.setattr(module, "create_engine", legacy_engine)
    single = AsyncMock(return_value=0)
    monkeypatch.setattr(runtime, "run_single_runtime", single)
    if plane == "scheduler":
        await module.run_weekly_scheduler()
        single.assert_awaited_once_with(settings, plane=plane)
    else:
        assert await module._run(SimpleNamespace(command="worker", once=True)) == 0
        single.assert_awaited_once_with(settings, plane=plane, once=True)
    legacy_engine.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["enqueue-weekly", "reconcile"])
async def test_single_consumer_rejects_legacy_write_commands_without_client(monkeypatch, command):
    module = importlib.import_module("app.wechat_official_account_draft_main")
    monkeypatch.setattr(
        module,
        "get_settings",
        Mock(
            return_value=SimpleNamespace(
                official_account_single_enabled=True, app_env="development"
            )
        ),
    )
    monkeypatch.setattr(module, "configure_logging", Mock())
    engine = Mock(side_effect=AssertionError("legacy writer must be unreachable"))
    monkeypatch.setattr(module, "create_engine", engine)
    assert await module._run(SimpleNamespace(command=command)) == 3
    engine.assert_not_called()


@pytest.mark.parametrize("suffix", ["add-intent", "add-ack"])
def test_manual_orphan_add_receipt_never_becomes_empty_ready_history(tmp_path, suffix):
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        journal.write("d" * 64 + f"-{suffix}.json", {"synthetic": True})
        with pytest.raises(ManualDraftError, match="manual_history_orphan_receipt"):
            journal.manual_history(ACCOUNT)
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_semantic_rejection_budget_is_frozen_and_does_not_reupload_acknowledged_media(
    tmp_path,
):
    current = edition()
    repository = Repository()
    calls = []
    for attempt in range(current.max_attempts):
        client = Client(WeChatMpTransientError(endpoint="material_add_thumb", provider_code=-1))
        journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
        try:
            await deliver_single(
                repository=repository,
                edition=current,
                prepared=prepared(),
                journal=journal,
                client=client,
                clock=lambda: NOW,
            )
        finally:
            journal.close()
        calls.extend(client.calls)
        current = repository.value
        assert current.status == ("failed" if attempt == 2 else "delivering")
    assert calls == ["inline", "thumb", "thumb", "thumb"]
    assert current.attempts["delivery"] == 3
    # Even a caller retrying the terminal edition cannot bypass the per-step ledger cap.
    client = Client()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        await deliver_single(
            repository=repository,
            edition=current,
            prepared=prepared(),
            journal=journal,
            client=client,
            clock=lambda: NOW,
        )
    finally:
        journal.close()
    assert client.calls == []
    assert repository.value.status == "failed"


@pytest.mark.asyncio
async def test_unknown_add_never_repeats_even_on_following_day(tmp_path):
    client = Client()
    client.add_draft = AsyncMock(side_effect=WeChatMpTransientError(endpoint="draft_add"))
    repository = Repository()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        await deliver_single(
            repository=repository,
            edition=edition(),
            prepared=prepared(),
            journal=journal,
            client=client,
            clock=lambda: NOW,
        )
        assert repository.value.status == "outcome_unknown"
        client.add_draft.assert_awaited_once()
        fresh = Client()
        await deliver_single(
            repository=repository,
            edition=replace(repository.value, status="delivering"),
            prepared=prepared(),
            journal=journal,
            client=fresh,
            clock=lambda: edition().expires_at,
        )
        assert fresh.calls == []
        assert repository.value.status == "outcome_unknown"
    finally:
        journal.close()
