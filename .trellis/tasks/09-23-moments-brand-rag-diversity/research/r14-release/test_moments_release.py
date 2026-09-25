"""Closed R14 release tests; never call real Docker, DB, SSH or providers."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

SPEC = importlib.util.spec_from_file_location(
    "moments_release", Path(__file__).with_name("moments_release.py")
)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


@pytest.fixture(autouse=True)
def no_real_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("unexpected real subprocess")

    monkeypatch.setattr(m.subprocess, "run", denied)


def test_fixed_base_and_exact_application_allowlist() -> None:
    assert m.BASE_REVISION == "3e62b33fcc62582240cb73ede9b12756eda029c5"
    assert (
        m.BASE_ID
        == "sha256:2b3a9a7c5e35a3a7173a129a3bd7e0d5322caaeef2c125b9a4d63146e77c9d1a"
    )
    assert (
        m.BASE_ARCHIVE_SHA
        == "651dbc6c08efc38ba405f133b630f4af077c45101de71f3777eab3a22827a80e"
    )
    assert m.SCHEMA == "20260916_0048"
    assert m.ALLOWED_APP_FILES == {
        "backend/app/application/services/copy_generation.py",
        "backend/app/core/config.py",
        "backend/app/domain/copy_generation.py",
        "backend/app/schemas/copy_generation.py",
    }
    assert m.HOST_FILES == ()
    assert m.BASE_COPY_VERSIONS != m.CANDIDATE_COPY_VERSIONS


@pytest.mark.parametrize(
    "changes,code",
    [
        ("M\tbackend/app/infrastructure/db/models.py\n", "app_allowlist"),
        ("M\tbackend/app/core/config.py\n", "incomplete_app_port"),
        ("M\tbackend/alembic/versions/0049.py\n", "forbidden_runtime_change"),
        ("M\tdeploy/release/deploy.py\n", "unreviewed_source_change"),
        (
            "M\tbackend/app/application/services/copy_generation.py\n",
            "incomplete_app_port",
        ),
    ],
)
def test_build_rejects_unscoped_or_partial_port(
    changes: str, code: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    revision = "a" * 40

    def fake_git(_repo: Path, *args: str) -> bytes:
        if args[0] == "rev-parse":
            return revision.encode()
        if args[0] == "merge-base":
            return b""
        if args[0] == "diff":
            return changes.encode()
        raise AssertionError(args)

    monkeypatch.setattr(m, "git", fake_git)
    with pytest.raises(RuntimeError, match=code):
        m.build(tmp_path, tmp_path / "base", tmp_path / "out", revision)


def test_next_window_is_dynamic_and_mwf() -> None:
    friday = datetime(2026, 9, 25, 10, tzinfo=UTC)
    window = m.next_window(friday)
    assert window["prepare_at"] == "2026-09-28T09:00:00+08:00"
    assert window["upload_at"] == "2026-09-28T10:00:00+08:00"
    assert window["expires_at"] == "2026-09-28T16:00:00+08:00"


def test_brand_identity_requires_active_ready_zhipu_and_returns_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = m.Host()
    calls: list[str] = []

    def scalar(sql: str) -> str:
        calls.append(sql)
        return json.dumps({"active_count": 11, "wrong_provider": 0, "sha256": "a" * 64})

    monkeypatch.setattr(host, "scalar", scalar)
    assert host.brand_identity()["active_count"] == 11
    assert calls and calls[0].startswith("SELECT ")
    assert "brand_documents" in calls[0] and "embedding_model" in calls[0]
    monkeypatch.setattr(
        host,
        "scalar",
        lambda _sql: json.dumps(
            {"active_count": 11, "wrong_provider": 1, "sha256": "a" * 64}
        ),
    )
    with pytest.raises(RuntimeError, match="brand_identity"):
        host.brand_identity()


def test_offline_copy_probe_has_no_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: Any) -> bytes:
        seen.append(argv)
        return b"{}"

    monkeypatch.setattr(m, "run", fake_run)
    assert m.Host().copy_identity("candidate", running=False) == {}
    assert seen[0][:8] == [
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        "--read-only",
    ]


def test_capture_baseline_comparison_and_expiration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline = {
        "captured_at": datetime.now(UTC).isoformat(),
        "schedule_window": m.next_window(datetime.now(UTC)),
        "brand_identity": {"sha256": "a" * 64},
    }
    live = dict(baseline)

    class CaptureHost:
        def capture(self, _manifest: dict[str, Any]) -> dict[str, Any]:
            return dict(live)

    backup_root = tmp_path / "backups"
    backup_root.mkdir(mode=0o700)
    monkeypatch.setattr(m, "BACKUP_ROOT", backup_root)
    deployment = m.Deployment(
        CaptureHost(), tmp_path / "candidate.json", {"revision": "a" * 40}, baseline
    )
    deployment.plan()
    live["brand_identity"] = {"sha256": "b" * 64}
    with pytest.raises(RuntimeError, match="baseline_drift"):
        deployment.plan()
    live["brand_identity"] = {"sha256": "a" * 64}
    baseline["captured_at"] = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    live["captured_at"] = baseline["captured_at"]
    with pytest.raises(RuntimeError, match="baseline_expired"):
        deployment.plan()


def test_activation_only_switches_image_and_commit_markers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installed: dict[str, bytes] = {}
    before = b"APP_IMAGE=" + m.BASE_REF.encode() + b"\n"
    monkeypatch.setattr(m, "read_file", lambda _path: before)
    monkeypatch.setattr(
        m,
        "replace_file",
        lambda path, body, _meta: installed.__setitem__(path.name, body),
    )
    monkeypatch.setattr(m, "write_new", lambda _path, _body: None)
    monkeypatch.setattr(m, "BACKUP_ROOT", tmp_path)
    manifest = {
        "revision": "a" * 40,
        "candidate_ref": "offline.local/candidate@sha256:" + "b" * 64,
    }
    baseline = {"files": {name: {} for name in m.PROTECTED_FILES}}
    deployment = m.Deployment(m.Host(), tmp_path / "candidate.json", manifest, baseline)
    deployment.activate()
    assert set(installed) == {".release.env", ".release-commit", "RELEASE_COMMIT"}
    assert manifest["candidate_ref"].encode() in installed[".release.env"]
    assert deployment.activated is True


@pytest.mark.parametrize("activation", [False, True])
def test_failure_recovery_never_blindly_restarts_old_after_activation(
    activation: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    actions: list[tuple[str, ...]] = []

    class FakeHost:
        def compose(self, *args: str, **_kwargs: Any) -> bytes:
            actions.append(args)
            return b""

        def capture(self, _manifest: dict[str, Any]) -> dict[str, Any]:
            return {"captured_at": "x"}

    monkeypatch.setattr(m, "BACKUP_ROOT", tmp_path)
    baseline = {"captured_at": "x", "files": {name: {} for name in m.PROTECTED_FILES}}
    deployment = m.Deployment(
        FakeHost(), tmp_path / "candidate.json", {"revision": "a" * 40}, baseline
    )
    monkeypatch.setattr(deployment, "plan", lambda: None)
    monkeypatch.setattr(deployment, "load", lambda: None)
    monkeypatch.setattr(deployment, "fence_stopped", lambda: None)
    monkeypatch.setattr(deployment, "backup", lambda: None)

    def fail_activate() -> None:
        deployment.activated = activation
        raise RuntimeError("injected_failure")

    monkeypatch.setattr(deployment, "activate", fail_activate)
    monkeypatch.setattr(m, "metadata", lambda _path: {})
    monkeypatch.setattr(FakeHost, "capture", lambda _self, _manifest: dict(baseline))
    with pytest.raises(RuntimeError, match="injected_failure"):
        deployment.apply()
    assert ("stop", "-t", "60", *m.SERVICES) in actions
    if activation:
        assert not any(action[0] == "start" for action in actions)
    else:
        assert ("start", *m.SERVICES) in actions


def test_same_baseline_does_not_ignore_business_identity() -> None:
    before = {"captured_at": "a", "brand_identity": "x", "db": "y"}
    m.same_baseline(before, {**before, "captured_at": "b"})
    with pytest.raises(RuntimeError, match="baseline_drift"):
        m.same_baseline(before, {**before, "brand_identity": "z"})
