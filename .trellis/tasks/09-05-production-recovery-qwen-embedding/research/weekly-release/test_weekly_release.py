"""Offline contracts only: no SSH, Docker daemon, provider, or production mutation."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("weekly_release", HERE / "weekly_release.py")
assert SPEC and SPEC.loader
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)
ROOT = Path("/root/projects/edu-ai-lead-agent")
LIBRARY = ROOT / R.LIB_PATH


@pytest.fixture
def lib():
    return R.load_lib(LIBRARY)


def test_library_is_pinned_and_never_calls_older_authority(tmp_path):
    bad = tmp_path / "library.py"
    bad.write_text("raise RuntimeError('credential-canary')")
    with pytest.raises(R.ReleaseError, match="validator_checksum_drift"):
        R.load_lib(bad)
    source = (HERE / "weekly_release.py").read_text()
    for forbidden in (
        "lib.validate_baseline(",
        "lib.validate_stage(",
        "lib.validate_release_window(",
        "lib.derive_candidate_environment(",
        "lib.activate_candidate_environment(",
    ):
        assert forbidden not in source
    valid = tmp_path / "pure_validator.py"
    valid.write_bytes(LIBRARY.read_bytes())
    before = {path.name for path in tmp_path.iterdir()}
    R.load_lib(valid)
    assert {path.name for path in tmp_path.iterdir()} == before


@pytest.mark.parametrize(
    "now,cutoff,valid",
    [
        (datetime(2026, 9, 7, 1, 30, tzinfo=UTC), "2026-09-07T03:00:00Z", True),
        (datetime(2026, 9, 7, 2, 44, 59, tzinfo=UTC), "2026-09-07T03:00:00Z", True),
        (datetime(2026, 9, 7, 2, 45, tzinfo=UTC), "2026-09-07T03:00:00Z", False),
        (datetime(2026, 9, 8, 1, 30, tzinfo=UTC), "2026-09-07T03:00:00Z", False),
        (datetime(2026, 9, 7, 1, 30, tzinfo=UTC), "2026-09-07T03:00:01Z", False),
        (datetime(2026, 9, 6, 8, 0, tzinfo=UTC), "2026-09-06T09:00:00Z", False),
    ],
)
def test_fixed_current_window(now, cutoff, valid):
    if valid:
        R.window(cutoff, now)
    else:
        with pytest.raises(R.ReleaseError):
            R.window(cutoff, now)


@pytest.mark.parametrize(
    "extra",
    [
        "M\tbackend/app/core/config.py",
        "M\tcompose.yaml",
        "M\tbackend/requirements/runtime.lock",
        "D\tbackend/tests/unit/test_official_account_weekly_production.py",
        "A\tbackend/tests/unit/unrelated.py",
        "M\t.trellis/spec/backend/unrelated.md",
    ],
)
def test_diff_rejects_expansion(monkeypatch, extra):
    output = "\n".join([*("M\t" + name for name in sorted(R.RUNTIME)), extra])
    monkeypatch.setattr(R, "git", lambda *args: output.encode() if args[1] == "diff" else b"")
    with pytest.raises(R.ReleaseError, match="unreviewed_diff"):
        R.allowed_diff(Path("/unused"), "a" * 40)


def test_diff_accepts_exact_tests_and_specs(monkeypatch):
    output = "\n".join(
        [
            *("M\t" + name for name in sorted(R.RUNTIME)),
            "A\tbackend/tests/unit/test_official_account_weekly_material_preflight.py",
            "A\t.trellis/spec/backend/weekly-production-source-preflight.md",
            "A\t" + R.TASK + "/research/weekly-release/usage.md",
        ]
    )
    monkeypatch.setattr(R, "git", lambda *args: output.encode() if args[1] == "diff" else b"")
    R.allowed_diff(Path("/unused"), "a" * 40)


def test_command_errors_are_redacted(capsys):
    with pytest.raises(R.ReleaseError, match="command_failed"):
        R.run(["/bin/sh", "-c", "printf 'credential-canary' >&2; exit 23"])
    output = capsys.readouterr().out
    assert "credential-canary" not in output
    assert '"stderr_bytes":17' in output and '"returncode":23' in output


def test_no_clobber_preserves_existing_bytes(tmp_path):
    path = tmp_path / "receipt"
    R.no_clobber(path, b"first")
    with pytest.raises(FileExistsError):
        R.no_clobber(path, b"second")
    assert path.read_bytes() == b"first"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_atomic_replacement_restores_private_mode_and_cleans_failed_temp(
    tmp_path, lib, monkeypatch
):
    path = tmp_path / "protected"
    path.write_bytes(b"private-old")
    path.chmod(0o600)
    original = R.file_identity(path, lib)[1]
    R.atomic_replace(path, b"candidate", original, lib)
    assert path.read_bytes() == b"candidate"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    R.atomic_replace(path, b"private-old", original, lib)
    assert R.file_identity(path, lib)[1] == original
    monkeypatch.setattr(R.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("canary")))
    with pytest.raises(OSError):
        R.atomic_replace(path, b"candidate", original, lib)
    assert path.read_bytes() == b"private-old"
    assert [p.name for p in tmp_path.iterdir()] == ["protected"]


def test_atomic_replacement_rejects_symlink(tmp_path, lib):
    target = tmp_path / "target"
    target.write_bytes(b"untouched")
    target.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        R.atomic_replace(link, b"candidate", R.file_identity(target, lib)[1], lib)
    assert target.read_bytes() == b"untouched"


def test_source_archive_normalizes_umask_and_preserves_all_files(tmp_path):
    rows = {
        "backend/app/value.py": (0o644, b"code"),
        "scripts/tool.sh": (0o755, b"script"),
    }
    R.write_source(tmp_path, rows)
    with tarfile.open(tmp_path / "source.tar.gz") as archive:
        observed = {m.name: (m.mode, m.isfile()) for m in archive}
    assert observed == {
        "backend": (0o755, False),
        "backend/app": (0o755, False),
        "backend/app/value.py": (0o644, True),
        "scripts": (0o755, False),
        "scripts/tool.sh": (0o755, True),
    }
    assert "backend/app/value.py" in (tmp_path / "source-manifest.tsv").read_text()


def test_image_probe_uses_one_complete_lf_delimited_projection(tmp_path):
    for name in (
        "alembic.ini",
        "pyproject.toml",
        "app/z.py",
        "app/a/b.py",
        "app/a.py",
        "alembic/env.py",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    (tmp_path / "app/ignored.txt").write_text("not image source")
    script = R.IMAGE_PROBE.replace("pathlib.Path('/app')", f"pathlib.Path({str(tmp_path)!r})")
    result = subprocess.run(["python3", "-B", "-c", script], check=True, capture_output=True)
    lines = result.stdout.decode().splitlines()
    assert len(lines) == 6 and "\\n" not in result.stdout.decode()
    names = [line.split("  ", 1)[1] for line in lines]
    assert names == sorted(names) and "alembic.ini" in names and "pyproject.toml" in names
    (tmp_path / "app/bad\nname.py").write_text("invalid")
    assert (
        subprocess.run(["python3", "-B", "-c", script], capture_output=True, check=False).returncode
        != 0
    )


@pytest.mark.parametrize(
    "argv",
    [
        ("up", "-d"),
        ("create",),
        ("run", "--build"),
        ("up", "--no-build", "--build=yes"),
    ],
)
def test_compose_forbids_all_build_surfaces(monkeypatch, argv):
    calls = []
    monkeypatch.setattr(R, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(R.ReleaseError):
        R.compose(*argv)
    assert calls == []


def test_compose_keeps_explicit_paths_and_no_env_leak(monkeypatch):
    calls = []
    monkeypatch.setattr(R, "run", lambda *args, **kwargs: calls.append((args, kwargs)) or b"")
    monkeypatch.setenv("AI_PLATFORM_API_KEY", "credential-canary")
    R.compose("up", "-d", "--no-deps", "--no-build", "content-worker")
    argv = calls[0][0][0]
    assert "--no-build" in argv and "--env-file" in argv
    assert calls[0][1]["env"] == R.SAFE_ENV
    assert "credential-canary" not in repr(calls)


def test_database_fences_use_actual_leases_and_hash_only_projection(monkeypatch):
    queries = []

    def execute(query):
        queries.append(query)
        if "version_num" in query:
            return R.HEAD.encode()
        return b"1"  # active work: stop before querying any history or writing anything

    monkeypatch.setattr(R, "sql", execute)
    with pytest.raises(R.ReleaseError, match="active_work_not_drained"):
        R.database_state()
    assert len(queries) == 2
    assert "lease_expires_at > statement_timestamp()" in queries[1]
    assert "source_fetch_leases" in queries[1]
    assert "UPDATE " not in "\n".join(queries)


def test_all_capture_queries_execute_on_isolated_postgresql(monkeypatch):
    """Execute the real generated SELECTs against freshly migrated local PostgreSQL."""
    queries = []
    monkeypatch.setattr(R, "sql", lambda query: queries.append(query) or b"")
    # Collection only: verdicts require incident rows, but SQL syntax/schema do not.
    monkeypatch.setattr(R, "require", lambda *args: None)
    R.database_state()
    assert len(queries) == 6
    assert "source_fetch_leases WHERE expires_at" in queries[1]
    assert "image_artifacts WHERE status = 'queued'" in queries[1]
    program = r"""
import asyncio,json,os,re,sys
from pathlib import Path
from uuid import uuid4
import asyncpg
from alembic import command
from alembic.config import Config
sys.path.insert(0,str(Path.cwd()/'backend'))
from app.core.config import get_settings
port=os.environ.get('WEEKLY_RELEASE_TEST_POSTGRES_PORT','25437')
assert re.fullmatch(r'[0-9]{2,5}',port) and 1024 <= int(port) <= 65535
name='edu_ai_release_test_'+uuid4().hex
assert re.fullmatch(r'edu_ai_release_test_[0-9a-f]{32}',name)
prefix=f'postgresql://edu_ai:edu_ai_local_change_me@127.0.0.1:{port}/'
async def create():
    connection=await asyncpg.connect(prefix+'postgres',timeout=10)
    try:
        await connection.execute('CREATE DATABASE "'+name+'"')
    finally:
        await connection.close()
async def check(queries):
    connection=await asyncpg.connect(prefix+name,timeout=10)
    count=0
    try:
        async with connection.transaction(readonly=True):
            await connection.execute("SET LOCAL statement_timeout='15s'")
            for query in queries:
                for statement in query.split(';'):
                    if statement.strip():
                        assert statement.lstrip().startswith('SELECT ')
                        await connection.fetch(statement)
                        count+=1
    finally:
        await connection.close()
    return count
async def drop():
    connection=await asyncpg.connect(prefix+'postgres',timeout=10)
    try:
        await connection.execute('DROP DATABASE "'+name+'"')
    finally:
        await connection.close()
queries=json.load(sys.stdin)
asyncio.run(create())
try:
    os.environ['DATABASE_URL']=prefix.replace('postgresql://','postgresql+asyncpg://')+name
    get_settings.cache_clear()
    command.upgrade(Config('backend/alembic.ini'),'20260901_0042')
    count=asyncio.run(check(queries))
    print('validated_selects='+str(count))
finally:
    asyncio.run(drop())
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", program],
        cwd=HERE.parents[4],
        env={
            **R.SAFE_ENV,
            **{
                name: os.environ[name]
                for name in ("WEEKLY_RELEASE_TEST_POSTGRES_PORT",)
                if name in os.environ
            },
        },
        input=json.dumps(queries).encode(),
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "isolated_postgres_failed",
        result.returncode,
        len(result.stderr),
        R.digest(result.stderr),
    )
    assert result.stdout.strip() == b"validated_selects=24"


@pytest.fixture
def activation_fixture(tmp_path, monkeypatch, lib):
    app = tmp_path / "app"
    work = tmp_path / "attempt"
    stage = tmp_path / "stage"
    for path in (app, work, stage):
        path.mkdir(mode=0o700)
    monkeypatch.setattr(R, "APP", app)
    monkeypatch.setattr(
        R,
        "SOURCE_ROOTS",
        (
            "backend",
            "compose.yaml",
            "deploy",
            "infra",
            "scripts",
            ".env.example",
        ),
    )
    rows = {
        name: (0o644, b"fixture\n")
        for name in (
            *lib.RUNTIME_DIFF,
            "backend/alembic.ini",
            "backend/pyproject.toml",
            "backend/app/api_main.py",
            "backend/app/content_worker_main.py",
            "backend/app/infrastructure/ai/factory.py",
            "deploy/fixture",
            "infra/fixture",
        )
    }
    rows.update(
        {
            "backend/code.py": (0o644, b"old-code"),
            "compose.yaml": (0o644, b"old-compose"),
            "backend/alembic/versions/fixture.py": (0o644, b"revision = '20260901_0042'\n"),
        }
    )
    for name, (_mode, raw) in rows.items():
        destination = app / name
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination.write_bytes(raw)
        destination.chmod(0o600)
    for directory in app.rglob("*"):
        if directory.is_dir():
            directory.chmod(0o700)
    for name in R.PROTECTED:
        (app / name).write_bytes(b"original-" + name.encode())
        (app / name).chmod(0o600)
    os.chown(app / ".env", 1000, 1001)
    protected = {name: R.file_identity(app / name, lib)[1] for name in R.PROTECTED}
    old_services = {
        name: {"image": "sha256:" + "d" * 64, "restart_count": 0} for name in lib.APP_SERVICES
    }
    old_services.update(
        {
            name: {
                "image": name + "-image",
                "restart_count": 0,
                "container_id": name + "-container",
            }
            for name in ("postgres", "minio")
        }
    )
    state = {
        "protected": protected,
        "database": {"jobs": "unchanged"},
        "source": R.current_source(lib),
        "services": old_services,
    }
    metadata = {
        "release_commit": "a" * 40,
        "candidate_reference": "candidate@sha256:" + "b" * 64,
        "transport_tag": "candidate:transport",
        "cutoff": "2026-09-07T03:00:00Z",
    }
    events = []
    monkeypatch.setattr(
        R, "verify_compose", lambda *args, **kwargs: events.append("verify-compose")
    )
    monkeypatch.setattr(
        R, "docker", lambda *args, **kwargs: events.append("docker:" + args[0]) or b""
    )
    monkeypatch.setattr(R, "probe_image", lambda *args: "sha256:" + "b" * 64)
    monkeypatch.setattr(R, "window", lambda *args: events.append("window"))
    monkeypatch.setattr(R, "validate_stage", lambda *args: events.append("validate-stage"))
    monkeypatch.setattr(R, "run", lambda *args, **kwargs: events.append("backup") or b"backup")
    monkeypatch.setattr(R, "verify_backup", lambda *args: "20260907T013135Z")
    monkeypatch.setattr(R, "database_state", lambda: state["database"])
    monkeypatch.setattr(
        R, "services", lambda *args, **kwargs: events.append("services") or old_services
    )
    R.write_source(stage, {**rows, "backend/code.py": (0o644, b"new-code")})
    monkeypatch.setattr(
        R,
        "protected_state",
        lambda *args, **kwargs: {name: R.file_identity(app / name, lib)[1] for name in R.PROTECTED},
    )

    def compose(*args, **kwargs):
        events.append("compose:" + args[0])
        return b""

    monkeypatch.setattr(R, "compose", compose)
    operation = R.Activation(stage, {"state": state}, metadata, lib, work)
    return operation, events, app, work


def test_activation_success_has_one_full_set_restart_and_no_migration(
    activation_fixture,
):
    operation, events, app, work = activation_fixture
    operation.execute("c" * 64)
    assert (app / "backend/code.py").read_bytes() == b"new-code"
    assert (work / "source.before/backend/code.py").read_bytes() == b"old-code"
    assert (app / ".env").read_bytes() == b"original-.env"
    assert events.count("compose:stop") == 1 and events.count("compose:up") == 1
    assert events.index("backup") > events.index("compose:stop")
    assert events.index("validate-stage") > events.index("backup")
    assert (work / "success.json").exists()
    assert "migration" not in repr(events)


@pytest.mark.parametrize("failure", ["first-stop", "backup", "source-second-rename", "post-start"])
def test_failures_restore_exact_files_and_both_markers(activation_fixture, monkeypatch, failure):
    operation, events, app, work = activation_fixture
    old_compose = R.compose
    if failure in {"first-stop", "post-start"}:
        fired = False

        def compose(*args, **kwargs):
            nonlocal fired
            if not fired and args[0] == ("stop" if failure == "first-stop" else "up"):
                fired = True
                raise R.ReleaseError("injected")
            return old_compose(*args, **kwargs)

        monkeypatch.setattr(R, "compose", compose)
    elif failure == "backup":
        monkeypatch.setattr(
            R,
            "verify_backup",
            lambda *args: (_ for _ in ()).throw(R.ReleaseError("injected")),
        )
    else:
        rename = os.rename
        fired = False

        def failing_rename(source, destination):
            nonlocal fired
            if not fired and source == work / "candidate/compose.yaml":
                fired = True
                raise OSError("injected")
            return rename(source, destination)

        monkeypatch.setattr(R.os, "rename", failing_rename)
    with pytest.raises((R.ReleaseError, OSError)):
        operation.execute("c" * 64)
    assert operation.armed
    operation.restore()
    assert (app / "backend/code.py").read_bytes() == b"old-code"
    assert (app / "compose.yaml").read_bytes() == b"old-compose"
    for name in R.PROTECTED:
        assert (app / name).read_bytes() == b"original-" + name.encode()
        assert stat.S_IMODE((app / name).stat().st_mode) == 0o600
    assert (
        json.loads((work / "rollback.json").read_bytes())["status"] == "previous_runtime_verified"
    )
    assert events[-2:] == ["services", "services"]
    assert R.current_source(operation.lib) == operation.state["source"]
    assert R.protected_state(operation.lib) == operation.state["protected"]


def test_rollback_state_drift_never_restarts_old_writers(activation_fixture, monkeypatch):
    operation, events, _app, _work = activation_fixture
    monkeypatch.setattr(R, "database_state", lambda: {"jobs": "changed"})
    with pytest.raises(R.ReleaseError, match="rollback_database_drift"):
        operation.restore()
    assert "compose:up" not in events


def test_no_provider_or_database_write_command_surfaces():
    source = (HERE / "weekly_release.py").read_text()
    for forbidden in (
        "alembic upgrade",
        "alembic downgrade",
        "pg_restore",
        "UPDATE official_account",
        "draft/add",
        "freepublish",
        "message/mass",
        "substantive-release-operator.sh",
    ):
        assert forbidden not in source


@pytest.mark.parametrize("extra", [b"", b"\nAPP_IMAGE: changed\n"])
def test_compose_change_is_exactly_one_inbox_field(extra):
    original = b"services:\n      WECHAT_MP_DRAFT_WEEKLY_INBOX_ROOT: /app/input/weekly-inbox\n"
    candidate = original.replace(
        b"/app/input/weekly-inbox", b"/app/input/official-account-weekly-editions/weekly-inbox"
    )
    if extra:
        with pytest.raises(R.ReleaseError, match="compose_change_outside_inbox_path"):
            R.validate_compose_change(original, candidate + extra)
    else:
        R.validate_compose_change(original, candidate)


def test_backup_uses_verified_source_script(activation_fixture, monkeypatch):
    operation, _events, app, _work = activation_fixture
    calls = []
    monkeypatch.setattr(R, "run", lambda argv, **kwargs: calls.append(argv) or b"backup")
    operation.execute("c" * 64)
    assert calls == [["bash", str(app / "scripts/edu-ai-backup.sh")]]
    assert "scripts" in R.SOURCE_ROOTS
