"""Independent review regressions; all processes and production access are denied."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import runpy
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

SPEC = importlib.util.spec_from_file_location(
    "reviewed_forward_release", Path(__file__).with_name("forward_release.py")
)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


@pytest.fixture(autouse=True)
def deny_external_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("review must not execute external processes")

    monkeypatch.setattr(m.subprocess, "run", denied)


def test_stable_file_rejects_path_replacement_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "protected"
    replacement = tmp_path / "replacement"
    target.write_bytes(b"identical")
    replacement.write_bytes(b"identical")
    original = os.fstat
    calls = 0

    def racing(fd: int) -> os.stat_result:
        nonlocal calls
        result = original(fd)
        calls += 1
        if calls == 2:
            os.replace(replacement, target)
        return result

    monkeypatch.setattr(m.os, "fstat", racing)
    with pytest.raises(RuntimeError, match="file_read_race"):
        m.metadata(target)


def test_failed_atomic_replace_preserves_original_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "protected"
    target.write_bytes(b"before")
    target.chmod(0o600)
    expected = m.metadata(target)

    def failed(*args: Any) -> None:
        raise OSError("fixture failure")

    monkeypatch.setattr(m.os, "replace", failed)
    with pytest.raises(OSError):
        m.replace_file(target, b"after", expected)
    assert m.metadata(target) == expected
    assert sorted(path.name for path in tmp_path.iterdir()) == ["protected"]


@pytest.mark.parametrize(
    "name,key,value",
    [
        (".env", "uid", 0),
        (".release.env", "uid", 1000),
        ("scripts/edu-ai-release-common.sh", "mode", 0o755),
        (".release-commit", "uid", False),
    ],
)
def test_capture_rejects_unreviewed_protected_metadata_before_any_process(
    monkeypatch: pytest.MonkeyPatch, name: str, key: str, value: Any
) -> None:
    def metadata(path: Path) -> dict[str, Any]:
        relative = path.relative_to(m.APP).as_posix()
        result = {**m.PROTECTED_METADATA[relative], "size": 3, "sha256": "a" * 64}
        if relative == name:
            result[key] = value
        return result

    monkeypatch.setattr(m, "metadata", metadata)
    monkeypatch.setattr(m.os, "geteuid", lambda: 0)
    with pytest.raises(RuntimeError, match="protected_metadata_policy"):
        m.Host().capture({})


def test_first_capture_cannot_bless_changed_historical_cohort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = (
        "official_account_single_editions",
        "official_account_draft_owners",
        "official_account_article_versions",
        "official_account_render_versions",
        "official_account_generated_visuals",
        "official_account_article_attempts",
        "wechat_mp_draft_jobs",
    )
    host = m.Host()
    cohort = m.HISTORICAL_COPY_COHORT_SHA

    def scalar(sql: str) -> str:
        assert sql.startswith("SELECT ")
        if "alembic_version" in sql:
            return m.SCHEMA
        if "pg_tables" in sql:
            return "\n".join(names)
        if "FROM copy_generation_jobs j JOIN" in sql:
            return cohort
        return '{"count":7,"sha256":"fixture"}'

    monkeypatch.setattr(host, "scalar", scalar)
    assert host.db_snapshot()["historical_preview_copy_jobs"] == cohort
    cohort = "b" * 64
    with pytest.raises(RuntimeError, match="historical_copy_cohort_drift"):
        host.db_snapshot()


def test_idle_rejects_orphaned_expired_lease_before_pending_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = m.Host()
    calls = []

    def scalar(sql: str) -> str:
        calls.append(sql)
        if "pg_tables" in sql:
            return "wechat_mp_draft_jobs"
        assert "v->>'lease_token' IS NOT NULL" in sql
        assert "v->>'lease_expires_at' IS NOT NULL" in sql
        return "1"

    monkeypatch.setattr(host, "scalar", scalar)
    with pytest.raises(RuntimeError, match="active_or_unknown_work"):
        host.idle()
    assert len(calls) == 2


def test_minio_control_rotation_does_not_hide_business_drift(tmp_path: Path) -> None:
    source = tmp_path / "minio"
    (source / "bucket").mkdir(parents=True)
    (source / ".minio.sys").mkdir()
    (source / "bucket/object").write_bytes(b"frozen object")
    control = source / ".minio.sys/control"
    control.write_bytes(b"before")
    before = m.tree_manifest(source, minio_business=True)
    archive = tmp_path / "minio.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source, arcname=".")
    control.write_bytes(b"rotated")
    m.verify_backup_archive(archive, source, before, minio_business=True)
    (source / "bucket/object").write_bytes(b"unexpected business mutation")
    with pytest.raises(RuntimeError, match="backup_source_changed"):
        m.verify_backup_archive(archive, source, before, minio_business=True)


@pytest.mark.parametrize("valid_dump", [True, False])
def test_actual_backup_covers_all_scopes_and_requires_dump_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_dump: bool
) -> None:
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(m, "APP", app)
    for name in ("backend", "deploy", "scripts", "infra", "private/brand-materials"):
        root = app / name
        root.mkdir(parents=True, exist_ok=True)
        (root / "fixture.txt").write_bytes(b"private fixture")
    (app / "private/brand-materials/小赛 AI 品牌资料.docx").write_bytes(
        b"private document"
    )
    for name in m.PROTECTED_FILES:
        path = app / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"protected fixture")
        path.chmod(0o600)
    volumes = {}
    for name in (
        "edu-ai-lead-agent_minio_data",
        "edu-ai-lead-agent_wechat_mp_draft_artifacts",
        "edu-ai-lead-agent_official_account_weekly_dag_output",
    ):
        root = tmp_path / name
        root.mkdir()
        (root / "fixture.bin").write_bytes(b"frozen data")
        volumes[name] = str(root)
    calls = []

    class BackupHost:
        def compose(self, *args: Any, **kwargs: Any) -> bytes:
            calls.append(args)
            if args == (
                "exec",
                "-T",
                "postgres",
                "sh",
                "-c",
                'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc',
            ):
                kwargs["output"].write(b"PGDMP" + b"x" * 2048)
                return b""
            assert args == ("exec", "-T", "postgres", "pg_restore", "--list")
            assert kwargs["input_data"].startswith(b"PGDMP")
            return b"TABLE DATA alembic_version" if valid_dump else b"incomplete"

    def local_tar(args: list[str], **kwargs: Any) -> bytes:
        assert args[:3] == ["tar", "--create", "--gzip"]
        assert args[3] == "--file" and args[5] == "--directory" and args[7] == "."
        with tarfile.open(args[4], "w:gz") as bundle:
            bundle.add(args[6], arcname=".")
        return b""

    monkeypatch.setattr(m, "run", local_tar)
    operation = m.Deployment(
        BackupHost(),
        tmp_path / "candidate.json",
        {"revision": "a" * 40},
        {"volumes": volumes},
    )
    operation.backup_dir = tmp_path / "backup"
    if not valid_dump:
        with pytest.raises(RuntimeError, match="postgres_dump_unverified"):
            operation.backup()
        assert not (operation.backup_dir / "backup-verified.json").exists()
        return
    operation.backup()
    receipt = m.strict_json(
        (operation.backup_dir / "backup-verified.json").read_bytes()
    )
    assert receipt["verified"] is True
    assert set(receipt["sha256"]) == {
        "postgres.dump",
        "runtime-config.tar.gz",
        "brand-materials.tar.gz",
        *(name + ".tar.gz" for name in volumes),
    }
    assert len(calls) == 2
    for name, digest in receipt["sha256"].items():
        path = operation.backup_dir / name
        assert m.sha(path.read_bytes()) == digest
        assert path.stat().st_mode & 0o777 == 0o600
    runtime = m.archive_members(operation.backup_dir / "runtime-config.tar.gz")
    assert all(name in runtime for name in m.PROTECTED_FILES)
    assert all(
        name + "/fixture.txt" in runtime
        for name in ("backend", "deploy", "scripts", "infra")
    )


def operation_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, list[Any]]:
    calls: list[Any] = []
    baseline: dict[str, Any] = {"files": {}}

    class ApplyHost:
        def compose(self, *args: Any, **kwargs: Any) -> bytes:
            calls.append(args)
            return b""

        def capture(self, manifest: dict[str, Any]) -> dict[str, Any]:
            calls.append(("capture",))
            return baseline

    operation = m.Deployment(
        ApplyHost(), tmp_path / "candidate.json", {"revision": "a" * 40}, baseline
    )
    operation.backup_dir = tmp_path / "backup"
    monkeypatch.setattr(m, "PROTECTED_FILES", ())
    for name in ("plan", "load", "fence_stopped"):
        monkeypatch.setattr(operation, name, lambda name=name: calls.append((name,)))

    def backup() -> None:
        operation.backup_dir.mkdir()
        calls.append(("backup",))

    def activate() -> None:
        operation.activated = True
        calls.append(("activate",))

    monkeypatch.setattr(operation, "backup", backup)
    monkeypatch.setattr(operation, "activate", activate)
    monkeypatch.setattr(
        m.time, "sleep", lambda seconds: calls.append(("sleep", seconds))
    )
    monkeypatch.setattr(m.time, "monotonic", lambda: 0)
    return operation, calls


def test_preactivation_drift_is_fenced_before_any_original_writer_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation, calls = operation_fixture(tmp_path, monkeypatch)

    def backup_failed() -> None:
        raise RuntimeError("backup_failure")

    fence_count = 0

    def fence() -> None:
        nonlocal fence_count
        fence_count += 1
        if fence_count == 2:
            raise RuntimeError("historical_database_drift")

    monkeypatch.setattr(operation, "backup", backup_failed)
    monkeypatch.setattr(operation, "fence_stopped", fence)
    with pytest.raises(RuntimeError, match="historical_database_drift"):
        operation.apply()
    assert fence_count == 2
    assert not any(call[0] == "start" for call in calls)
    assert calls[-1] == ("stop", "-t", "60", *m.SERVICES)


def test_historical_drift_stops_immediately_without_readiness_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation, calls = operation_fixture(tmp_path, monkeypatch)

    def verify() -> None:
        calls.append(("verify",))
        raise RuntimeError("historical_database_changed")

    monkeypatch.setattr(operation, "verify", verify)
    with pytest.raises(RuntimeError, match="historical_database_changed"):
        operation.apply()
    assert calls.count(("verify",)) == 1
    assert not any(call[0] in {"sleep", "start"} for call in calls)
    assert calls[-1] == ("stop", "-t", "60", *m.SERVICES)


def test_starting_can_converge_without_repeating_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation, calls = operation_fixture(tmp_path, monkeypatch)
    outcomes = iter(("candidate_service_not_ready", "history_barrier_not_ready", None))

    def verify() -> dict[str, str]:
        code = next(outcomes)
        if code:
            raise RuntimeError(code)
        return {"status": "deployed"}

    monkeypatch.setattr(operation, "verify", verify)
    assert operation.apply() == {"status": "deployed"}
    assert calls.count(("activate",)) == 1
    assert calls.count(("sleep", 3)) == 2


@pytest.mark.parametrize(
    "hour,minute,allowed", [(0, 39, True), (0, 40, False), (1, 1, False)]
)
def test_plan_cannot_cross_next_preparation_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hour: int,
    minute: int,
    allowed: bool,
) -> None:
    moment = datetime(2026, 9, 23, hour, minute, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return moment if tz is None else moment.astimezone(tz)

    baseline = {"captured_at": moment.isoformat()}

    class PlanHost:
        def capture(self, manifest: Any) -> dict[str, Any]:
            return baseline

    backup_root = tmp_path / "backups"
    backup_root.mkdir(mode=0o700)
    monkeypatch.setattr(m, "BACKUP_ROOT", backup_root)
    monkeypatch.setattr(m, "datetime", Clock)
    operation = m.Deployment(
        PlanHost(), tmp_path / "candidate.json", {"revision": "a" * 40}, baseline
    )
    if allowed:
        operation.plan()
    else:
        with pytest.raises(
            RuntimeError, match="schedule_too_near|release_window_elapsed"
        ):
            operation.plan()


def test_actual_source_probe_argv_is_offline_and_detects_extra_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / "a.py").write_bytes(b"a = 1\n")
    (root / "extra.html").write_bytes(b"<p>extra</p>")

    def execute_probe(args: list[str], **kwargs: Any) -> bytes:
        assert args[:10] == [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
        ]
        assert args[10:14] == [
            "--security-opt",
            "no-new-privileges",
            "--entrypoint",
            "python",
        ]
        assert args[-3:-1] == ["-B", "-c"]
        assert args[-1] == m.APP_PROBE
        output = io.StringIO()
        program = args[-1].replace("'/app/app'", repr(str(root)))
        probe_file = tmp_path / "reviewed_probe.py"
        probe_file.write_text(program)
        with contextlib.redirect_stdout(output):
            runpy.run_path(str(probe_file))
        return output.getvalue().encode()

    monkeypatch.setattr(m, "run", execute_probe)
    actual = m.Host().app_tree("fixture@sha256:" + "a" * 64)
    assert actual == {"a.py": m.sha(b"a = 1\n"), "extra.html": m.sha(b"<p>extra</p>")}
    (root / "escape.py").symlink_to(root / "a.py")
    with pytest.raises(RuntimeError, match="app_symlink"):
        m.Host().app_tree("fixture@sha256:" + "a" * 64)
