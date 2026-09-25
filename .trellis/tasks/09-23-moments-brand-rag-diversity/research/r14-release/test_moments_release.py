"""Closed R14 release tests; never call real Docker, DB, SSH or providers."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
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
        "backend/app/application/services/wechat_official_account_draft.py",
        "backend/app/core/config.py",
        "backend/app/domain/copy_generation.py",
        "backend/app/domain/official_account_editor_handoff.py",
        "backend/app/schemas/copy_generation.py",
    }
    assert m.NOTICE_REVISION == "a9db34f8937effda32a2a58358d2b849268700a5"
    assert m.NOTICE_SERVICE == "wechat-official-account-draft-worker"
    assert m.NOTICE_IMAGE_ID.startswith("sha256:c3f26a9d3523")
    assert len(m.NOTICE_APP_HASHES) == 2
    assert m.HOST_FILES == ()
    assert m.BASE_COPY_VERSIONS != m.CANDIDATE_COPY_VERSIONS


def test_known_notice_image_has_exact_identity_lineage_and_runtime_config() -> None:
    base = {
        "Id": m.BASE_ID,
        "RootFS": {"Layers": ["base-1", "base-2"]},
        "Config": {"Cmd": ["python", "-m", "app"], "Labels": {"revision": "base"}},
    }
    notice = {
        "Id": m.NOTICE_IMAGE_ID,
        "RepoTags": [m.NOTICE_IMAGE_TAG],
        "RootFS": {"Layers": ["base-1", "base-2", "notice-1", "notice-2"]},
        "Config": {
            "Cmd": ["python", "-m", "app"],
            "Labels": {"org.opencontainers.image.revision": m.NOTICE_LABEL_REVISION},
        },
    }
    m.check_notice_image(base, notice)
    for field, value, code in (
        ("Id", m.BASE_ID, "notice_image_identity"),
        ("RepoTags", ["unrelated:tag"], "notice_image_identity"),
        (
            "RootFS",
            {"Layers": ["other", "base-2", "notice-1", "notice-2"]},
            "notice_image_lineage",
        ),
        (
            "Config",
            {**notice["Config"], "Cmd": ["unexpected"]},
            "notice_runtime_config",
        ),
    ):
        changed = {**notice, field: value}
        with pytest.raises(RuntimeError, match=code):
            m.check_notice_image(base, changed)
    wrong_label = {
        **notice,
        "Config": {
            **notice["Config"],
            "Labels": {"org.opencontainers.image.revision": "unreviewed"},
        },
    }
    with pytest.raises(RuntimeError, match="notice_image_identity"):
        m.check_notice_image(base, wrong_label)


def test_mixed_baseline_is_bound_to_one_service_and_compose_base() -> None:
    base = {"Image": m.BASE_ID, "Config": {"Image": m.BASE_REF}}
    notice = {"Image": m.NOTICE_IMAGE_ID, "Config": {"Image": m.NOTICE_IMAGE_TAG}}
    m.check_baseline_service_image("acquisition-api", base, m.BASE_REF)
    m.check_baseline_service_image(m.NOTICE_SERVICE, notice, m.BASE_REF)
    for name, item, rendered in (
        ("acquisition-api", notice, m.BASE_REF),  # wrong role
        (m.NOTICE_SERVICE, base, m.BASE_REF),  # silently lost live patch
        (m.NOTICE_SERVICE, {**notice, "Image": "sha256:" + "0" * 64}, m.BASE_REF),
        (m.NOTICE_SERVICE, notice, m.NOTICE_IMAGE_TAG),  # Compose drift
    ):
        with pytest.raises(RuntimeError, match="baseline_service_image"):
            m.check_baseline_service_image(name, item, rendered)


def test_notice_tree_contains_only_the_two_pinned_source_changes() -> None:
    base_tree = {**{path: "old" for path in m.NOTICE_APP_HASHES}, "other.py": "same"}
    expected = {**base_tree, **m.NOTICE_APP_HASHES}
    assert m.notice_tree(base_tree) == expected
    m.check_notice_app_tree(expected, m.notice_tree(base_tree))
    with pytest.raises(RuntimeError, match="notice_app_tree"):
        m.check_notice_app_tree({**expected, "unreviewed.py": "unexpected"}, expected)
    with pytest.raises(RuntimeError, match="notice_app_tree"):
        m.check_notice_app_tree(
            {**expected, next(iter(m.NOTICE_APP_HASHES)): "wrong"}, expected
        )
    with pytest.raises(RuntimeError, match="notice_source_paths"):
        m.notice_tree({"other.py": "same"})


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


@pytest.mark.parametrize(
    "destination",
    ["/app", "/app/app", "/app/app/domain", "/app/alembic", "/app/alembic.ini"],
)
def test_mounts_cannot_shadow_verified_application(
    destination: str,
) -> None:
    with pytest.raises(RuntimeError, match="application_mount_shadow"):
        m.check_application_mounts([{"Destination": destination}])
    m.check_application_mounts([{"Destination": "/app/private/brand-materials"}])


def test_fixed_base_operator_rejects_standard_release_markers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = tmp_path / "current.json"
    monkeypatch.setattr(m, "STANDARD_RELEASE_MARKERS", (str(marker),))
    assert m.standard_release_markers_absent() == {str(marker): True}
    marker.symlink_to(tmp_path / "missing")
    assert m.standard_release_markers_absent() == {str(marker): False}


def test_backup_space_is_checked_before_stopping_services(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = tmp_path / "app"
    for name in ("private/brand-materials", "backend", "deploy", "scripts", "infra"):
        (app / name).mkdir(parents=True)
    postgres = tmp_path / "postgres"
    postgres.mkdir()
    volume = tmp_path / "volume"
    volume.mkdir()
    monkeypatch.setattr(m, "APP", app)
    monkeypatch.setattr(m, "BACKUP_ROOT", tmp_path)
    baseline = {
        "services": {
            "postgres": {
                "mounts": [
                    {
                        "Type": "volume",
                        "Name": "edu-ai-lead-agent_postgres_data",
                        "Source": str(postgres),
                    }
                ]
            }
        },
        "volumes": {"edu-ai-lead-agent_minio_data": str(volume)},
    }
    monkeypatch.setattr(
        m.shutil, "disk_usage", lambda _path: SimpleNamespace(free=1024 * 1024)
    )
    with pytest.raises(RuntimeError, match="backup_space"):
        m.check_backup_space(baseline)
    monkeypatch.setattr(
        m.shutil, "disk_usage", lambda _path: SimpleNamespace(free=1024**3)
    )
    m.check_backup_space(baseline)


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
    monkeypatch.setattr(m, "check_backup_space", lambda _baseline: None)
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
    baseline["captured_at"] = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
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
    monkeypatch.setattr(m, "check_backup_space", lambda _baseline: None)
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
    monkeypatch.setattr(m, "check_backup_space", lambda _baseline: None)
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


def test_failed_activation_intent_write_never_restarts_old_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    actions: list[tuple[str, ...]] = []
    baseline = {"captured_at": "x", "files": {name: {} for name in m.PROTECTED_FILES}}

    class FakeHost:
        def compose(self, *args: str, **_kwargs: Any) -> bytes:
            actions.append(args)
            return b""

        def capture(self, _manifest: dict[str, Any]) -> dict[str, Any]:
            return dict(baseline)

    monkeypatch.setattr(m, "BACKUP_ROOT", tmp_path)
    monkeypatch.setattr(m, "check_backup_space", lambda _baseline: None)
    deployment = m.Deployment(
        FakeHost(),
        tmp_path / "candidate.json",
        {
            "revision": "a" * 40,
            "candidate_ref": "offline.local/candidate@sha256:" + "b" * 64,
        },
        baseline,
    )
    monkeypatch.setattr(deployment, "plan", lambda: None)
    monkeypatch.setattr(deployment, "load", lambda: None)
    monkeypatch.setattr(deployment, "fence_stopped", lambda: None)
    monkeypatch.setattr(deployment, "backup", lambda: None)
    deployment.backup_dir.mkdir()

    def failed_intent(path: Path, _body: bytes) -> None:
        assert path.name == "activation-intent.json"
        path.touch()
        raise RuntimeError("intent_write_uncertain")

    monkeypatch.setattr(m, "write_new", failed_intent)
    with pytest.raises(RuntimeError, match="intent_write_uncertain"):
        deployment.apply()
    assert ("stop", "-t", "60", *m.SERVICES) in actions
    assert not any(action[0] == "start" for action in actions)


def test_same_baseline_does_not_ignore_business_identity() -> None:
    before = {
        "captured_at": "a",
        "brand_identity": "x",
        "db": "y",
        "services": {m.NOTICE_SERVICE: {"image": m.NOTICE_IMAGE_ID}},
    }
    m.same_baseline(before, {**before, "captured_at": "b"})
    with pytest.raises(RuntimeError, match="baseline_drift"):
        m.same_baseline(before, {**before, "brand_identity": "z"})
    with pytest.raises(RuntimeError, match="baseline_drift"):
        m.same_baseline(
            before,
            {
                **before,
                "services": {m.NOTICE_SERVICE: {"image": m.BASE_ID}},
            },
        )
