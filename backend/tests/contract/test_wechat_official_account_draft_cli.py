from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app import wechat_official_account_draft_main as cli
from app.application.services.official_account_weekly_edition import (
    WeeklyEditionLiveProvenanceError,
)
from app.core.config import Settings
from pydantic import SecretStr


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        ["enqueue-weekly", "/private/live-weekly"],
        ["reconcile", "--once"],
        ["worker", "--once"],
    ],
)
async def test_mutating_commands_fail_closed_before_database_or_http_construction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))

    def fail_engine(_settings: Settings) -> None:
        raise AssertionError("disabled command constructed the database engine")

    monkeypatch.setattr(cli, "create_engine", fail_engine)

    exit_code = await cli._run(cli._parser().parse_args(arguments))

    assert exit_code == 3
    assert json.loads(capsys.readouterr().out) == {
        "error_code": "wechat_mp_draft_automation_disabled",
        "ok": False,
    }


@pytest.mark.asyncio
async def test_explicit_fixture_enqueue_returns_only_stable_provenance_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        wechat_mp_enabled=True,
        wechat_mp_app_id=SecretStr("wx-test-app"),
        wechat_mp_app_secret=SecretStr("test-secret"),
        wechat_mp_draft_worker_enabled=True,
    )
    engine = _Engine()
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "create_engine", lambda _settings: engine)
    monkeypatch.setattr(cli, "create_session_factory", lambda _engine: object())
    monkeypatch.setattr(
        cli,
        "PostgresWeChatOfficialAccountDraftJobRepository",
        lambda _factory: object(),
    )
    monkeypatch.setattr(cli, "LocalWeChatDraftArtifactStore", lambda **_kwargs: object())

    class _FixtureRejectingService:
        async def enqueue_weekly(self, _directory: object) -> None:
            raise WeeklyEditionLiveProvenanceError("private fixture detail")

    monkeypatch.setattr(cli, "_job_service", lambda **_kwargs: _FixtureRejectingService())

    exit_code = await cli._run(cli._parser().parse_args(["enqueue-weekly", "/private/live-weekly"]))

    output = capsys.readouterr().out
    assert exit_code == 4
    assert json.loads(output) == {
        "error_code": "weekly_edition_live_provenance_required",
        "ok": False,
    }
    assert "/private" not in output
    assert engine.disposed is True


@pytest.mark.asyncio
async def test_status_json_uses_only_repository_safe_projection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine = _Engine()
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(cli, "create_engine", lambda _settings: engine)
    monkeypatch.setattr(cli, "create_session_factory", lambda _engine: object())

    job_id = uuid4()
    projection = {
        "job_id": str(job_id),
        "status": "ready",
        "items": [{"role": "official_anchor", "draft_created": True}],
    }

    class _Repository:
        async def get_status(self, requested_id: object) -> SimpleNamespace:
            assert requested_id == job_id
            return SimpleNamespace(as_dict=lambda: projection)

    monkeypatch.setattr(
        cli,
        "PostgresWeChatOfficialAccountDraftJobRepository",
        lambda _factory: _Repository(),
    )

    exit_code = await cli._run(cli._parser().parse_args(["status", str(job_id)]))

    output = capsys.readouterr().out
    assert exit_code == 0
    assert json.loads(output) == {"ok": True, **projection}
    assert "secret" not in output.casefold()
    assert "media_id" not in output
    assert "/private" not in output
    assert engine.disposed is True
