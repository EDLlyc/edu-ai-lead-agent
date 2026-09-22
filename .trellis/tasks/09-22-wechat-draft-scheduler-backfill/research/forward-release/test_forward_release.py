"""Offline release contract tests. No real Docker, network, database or social API."""

from __future__ import annotations

import gzip
import importlib.util
import io
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

SPEC = importlib.util.spec_from_file_location(
    "forward_release", Path(__file__).with_name("forward_release.py")
)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


@pytest.fixture(autouse=True)
def no_real_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("unexpected real subprocess")

    monkeypatch.setattr(m.subprocess, "run", denied)


@pytest.fixture
def candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, Any]]:
    base_app = {"backend/app/old.py": b"old = True\n"}
    new_app = {
        "backend/app/old.py": b"old = False\n",
        "backend/app/new.py": b"fallback = True\n",
    }
    preserved_path = "infrastructure/ai/zhipu.py"
    repository_ocr = b"repository_ocr = True\n"
    live_ocr = b"frozen_live_ocr = True\n"
    base_app["backend/app/" + preserved_path] = repository_ocr
    new_app["backend/app/" + preserved_path] = repository_ocr
    monkeypatch.setattr(
        m,
        "PRESERVED_BASE_FILES",
        {
            preserved_path: {
                "runtime_sha256": m.sha(live_ocr),
                "runtime_size": len(live_ocr),
                "base_git_sha256": m.sha(repository_ocr),
                "candidate_git_sha256": m.sha(repository_ocr),
            }
        },
    )
    compatibility = m.canonical(
        {"alembic_head": m.SCHEMA, "previous_application_compatible": False}
    )
    hosts = {
        path: compatibility if index == 0 else b"reviewed\n"
        for index, path in enumerate(m.HOST_FILES)
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as layer:
        m.tar_member(layer, "app/app/old.py", base_app["backend/app/old.py"])
        m.tar_member(layer, "app/app/" + preserved_path, live_ocr)
    raw = buffer.getvalue()
    zipped = gzip.compress(raw, mtime=0)
    config = {
        "architecture": "amd64",
        "os": "linux",
        "config": {
            "Labels": {"org.opencontainers.image.revision": m.BASE_REVISION},
            "User": "999",
        },
        "rootfs": {"type": "layers", "diff_ids": ["sha256:" + m.sha(raw)]},
        "history": [],
    }
    config_body = m.canonical(config)
    manifest = {
        "schemaVersion": 2,
        "mediaType": m.OCI + "manifest.v1+json",
        "config": m.describe(config_body, m.OCI + "config.v1+json"),
        "layers": [m.describe(zipped, m.OCI + "layer.v1.tar+gzip")],
    }
    manifest_body = m.canonical(manifest)
    index = {
        "schemaVersion": 2,
        "mediaType": m.OCI + "index.v1+json",
        "manifests": [
            {
                **m.describe(manifest_body, m.OCI + "manifest.v1+json"),
                "platform": {"architecture": "amd64", "os": "linux"},
                "annotations": {
                    "io.containerd.image.name": m.REPOSITORY + ":fixture",
                    "org.opencontainers.image.ref.name": "fixture",
                },
            }
        ],
    }
    members = {
        "oci-layout": m.canonical({"imageLayoutVersion": "1.0.0"}),
        "index.json": m.canonical(index),
    }
    for body in (config_body, manifest_body, zipped):
        members["blobs/sha256/" + m.sha(body)] = body
    archive = m.archive_bytes(members)
    base = tmp_path / "base.tar.gz"
    base.write_bytes(archive)
    monkeypatch.setattr(m, "BASE_ID", "sha256:" + m.sha(manifest_body))
    monkeypatch.setattr(m, "BASE_REF", m.REPOSITORY + "@" + m.BASE_ID)
    monkeypatch.setattr(m, "BASE_ARCHIVE_SHA", m.sha(archive))
    revision = "a" * 40
    blobs = {}

    def fake_git(repo: Path, *args: str) -> bytes:
        if args[0] == "rev-parse":
            return revision.encode()
        if args[0] == "merge-base":
            return b""
        if args[0] == "diff":
            return (
                b"M\tbackend/app/old.py\nA\tbackend/app/new.py\nM\tscripts/doctor.sh\n"
            )
        if args[0] == "ls-tree":
            files = base_app if args[2] == m.BASE_REVISION else new_app
            if args[-1] == "backend/alembic":
                files = {
                    "backend/alembic/versions/0048.py": b"revision='20260916_0048'\n"
                }
            result = b""
            for path, body in files.items():
                blob = m.sha(body)
                blobs[blob] = body
                result += f"100644 blob {blob}\t{path}".encode() + b"\0"
            return result
        if args[0] == "cat-file":
            return blobs[args[2]]
        if args[0] == "show":
            name = args[1].split(":", 1)[1]
            if name == m.OPERATOR_PATH:
                return Path(m.__file__).read_bytes()
            return hosts.get(name, b"immutable")
        raise AssertionError(args)

    monkeypatch.setattr(m, "git", fake_git)
    # Workspace bytes deliberately disagree: the builder must ignore them.
    (tmp_path / "old.py").write_text("WORKSPACE SECRET MUST NEVER BE BUILT")
    output = tmp_path / "built"
    value = m.build(tmp_path, base, output, revision)
    return output, value


def test_committed_complete_overlay_and_strict_graph(
    candidate: tuple[Path, dict[str, Any]],
) -> None:
    output, value = candidate
    actual = m.validate_bundle(output / "candidate.json", m.sha(m.canonical(value)))
    assert actual["candidate_app_tree"] == {
        "old.py": m.sha(b"old = False\n"),
        "new.py": m.sha(b"fallback = True\n"),
        "infrastructure/ai/zhipu.py": m.sha(b"frozen_live_ocr = True\n"),
    }
    assert actual["preserved_base_files"] == m.PRESERVED_BASE_FILES
    assert "infrastructure/ai/zhipu.py" not in actual["files"]
    assert actual["schema"] == "20260916_0048"
    assert actual["migration_executed"] is False
    assert actual["standard_release_provenance"] == "incomplete"


@pytest.mark.parametrize(
    "field,bad",
    [
        ("schema", "20260914_0047"),
        ("base_revision", "b" * 40),
        ("base_image", "mutable:latest"),
        ("base_archive_sha256", "0" * 64),
    ],
)
def test_fixed_base_schema(
    candidate: tuple[Path, dict[str, Any]], field: str, bad: str
) -> None:
    output, value = candidate
    value[field] = bad
    (output / "candidate.json").write_bytes(m.canonical(value))
    with pytest.raises(RuntimeError, match="candidate_fixed_base"):
        m.validate_bundle(output / "candidate.json", m.sha(m.canonical(value)))


@pytest.mark.parametrize(
    "filename", ["backend-image.oci.tar.gz", "host-files.tar.gz", "forward_release.py"]
)
def test_artifact_tampering(
    candidate: tuple[Path, dict[str, Any]], filename: str
) -> None:
    output, value = candidate
    (output / filename).write_bytes(b"tampered")
    with pytest.raises(RuntimeError):
        m.validate_bundle(output / "candidate.json", m.sha(m.canonical(value)))


@pytest.mark.parametrize(
    "path",
    [
        "compose.yaml",
        "backend/Dockerfile",
        "backend/pyproject.toml",
        "backend/migrations/versions/0049.py",
        "backend/alembic/versions/0049.py",
        "backend/requirements/runtime.lock",
        "backend/requirements/dev.lock",
        "scripts/other.sh",
    ],
)
def test_forbidden_runtime_changes(
    candidate: tuple[Path, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    path: str,
) -> None:
    original = m.git

    def changed(repo: Path, *args: str) -> bytes:
        return f"M\t{path}\n".encode() if args[0] == "diff" else original(repo, *args)

    monkeypatch.setattr(m, "git", changed)
    with pytest.raises(
        RuntimeError, match="forbidden_runtime_change|unreviewed_host_change"
    ):
        m.build(tmp_path, tmp_path / "base.tar.gz", tmp_path / "forbidden", "a" * 40)


def test_env_only_changes_exact_policy_and_image_and_preserves_bytes() -> None:
    original = (
        b"# secret stays private\r\nTOKEN='private with spaces'\r\n"
        + f"{m.POLICY_KEY}={m.V3}\r\n".encode()
    )
    result = m.change_env(original, m.POLICY_KEY, m.V3, m.V4)
    assert result.replace(m.V4.encode(), m.V3.encode()) == original
    assert m.env_values(result)["TOKEN"] == "private with spaces"
    with pytest.raises(RuntimeError, match="environment_key"):
        m.change_env(
            original + f"{m.POLICY_KEY}={m.V3}\n".encode(), m.POLICY_KEY, m.V3, m.V4
        )
    with pytest.raises(RuntimeError, match="environment_value"):
        m.change_env(original, m.POLICY_KEY, "wrong", m.V4)


def test_atomic_install_keeps_protected_owner_mode_and_fails_on_drift(
    tmp_path: Path,
) -> None:
    target = tmp_path / "env"
    target.write_bytes(b"before")
    target.chmod(0o600)
    expected = m.metadata(target)
    m.replace_file(target, b"after", expected)
    assert target.read_bytes() == b"after"
    assert m.metadata(target)["mode"] == 0o600
    assert m.metadata(target)["uid"] == expected["uid"]
    with pytest.raises(RuntimeError, match="file_changed_before_replace"):
        m.replace_file(target, b"third", expected)


def test_stable_baseline_is_hash_bound_and_ignores_only_capture_time() -> None:
    baseline = {
        "schema": m.SCHEMA,
        "db": {"prepared_sha256": "a"},
        "captured_at": "before",
    }
    m.same_baseline(baseline, {**baseline, "captured_at": "after"})
    with pytest.raises(RuntimeError, match="baseline_drift"):
        m.same_baseline(baseline, {**baseline, "db": {"prepared_sha256": "b"}})


def test_backup_verifies_actual_archive_bytes_and_detects_source_race(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "journal.json").write_bytes(b"private receipt")
    before = m.tree_manifest(source)
    archive = tmp_path / "backup.tar.gz"
    with tarfile.open(archive, "w:gz") as out:
        out.add(source / "journal.json", arcname="journal.json")
    m.verify_backup_archive(archive, source, before)
    (source / "journal.json").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="backup_source_changed"):
        m.verify_backup_archive(archive, source, before)


def test_oci_rejects_unreachable_blob_and_duplicate_json(
    candidate: tuple[Path, dict[str, Any]],
) -> None:
    output, _ = candidate
    members = m.archive_members(output / "backend-image.oci.tar.gz")
    members["blobs/sha256/" + "f" * 64] = b"extra"
    with pytest.raises(RuntimeError, match="oci_extra_blob"):
        m.oci_graph(members)
    with pytest.raises(RuntimeError, match="duplicate_json_key"):
        m.strict_json(b'{"a":1,"a":2}')


@pytest.mark.parametrize("field", ["mediaType", "platform", "annotations"])
def test_oci_index_types_platform_and_tag_are_bound(
    candidate: tuple[Path, dict[str, Any]], field: str
) -> None:
    output, value = candidate
    members = m.archive_members(output / "backend-image.oci.tar.gz")
    index = m.strict_json(members["index.json"])
    if field == "mediaType":
        index[field] = "not-oci"
    elif field == "platform":
        index["manifests"][0][field]["architecture"] = "arm64"
    else:
        index["manifests"][0][field] = {
            "io.containerd.image.name": m.REPOSITORY + ":other",
            "org.opencontainers.image.ref.name": "other",
        }
    members["index.json"] = m.canonical(index)
    with pytest.raises(RuntimeError):
        m.oci_graph(members, expected_tag=value["candidate_tag"])


def test_uncommitted_operator_is_rejected(
    candidate: tuple[Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = m.git

    def changed(repo: Path, *args: str) -> bytes:
        if args[0] == "show" and args[1].endswith(":" + m.OPERATOR_PATH):
            return b"unreviewed operator"
        return original(repo, *args)

    monkeypatch.setattr(m, "git", changed)
    with pytest.raises(RuntimeError, match="uncommitted_operator"):
        m.build(tmp_path, tmp_path / "base.tar.gz", tmp_path / "rejected", "a" * 40)


def test_gzip_expansion_is_bounded() -> None:
    with pytest.raises(RuntimeError, match="gzip_expansion_limit"):
        m.bounded_gunzip(gzip.compress(b"x" * 500), limit=100)


@pytest.mark.parametrize(
    "change", ["hash", "extra_path", "git_projection", "size_type"]
)
def test_preserved_exception_contract_is_closed(
    candidate: tuple[Path, dict[str, Any]], change: str
) -> None:
    output, value = candidate
    path = "infrastructure/ai/zhipu.py"
    if change == "hash":
        value["preserved_base_files"][path]["runtime_sha256"] = "0" * 64
    elif change == "extra_path":
        value["preserved_base_files"]["unreviewed.py"] = dict(
            value["preserved_base_files"][path]
        )
    elif change == "size_type":
        value["preserved_base_files"][path]["runtime_size"] = float(
            value["preserved_base_files"][path]["runtime_size"]
        )
    else:
        value["base_app_tree"][path] = value["candidate_app_tree"][path] = value[
            "preserved_base_files"
        ][path]["base_git_sha256"]
    (output / "candidate.json").write_bytes(m.canonical(value))
    with pytest.raises(
        RuntimeError, match="preserved_base_contract|preserved_base_projection"
    ):
        m.validate_bundle(output / "candidate.json", m.sha(m.canonical(value)))


@pytest.mark.parametrize("change_base_too", [False, True])
def test_preserved_path_cannot_be_changed_in_git(
    candidate: tuple[Path, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change_base_too: bool,
) -> None:
    original = m.git_files

    def changed(repo: Path, revision: str, prefix: str) -> dict[str, bytes]:
        files = original(repo, revision, prefix)
        if prefix == "backend/app" and (change_base_too or revision != m.BASE_REVISION):
            files["backend/app/infrastructure/ai/zhipu.py"] = b"new out of scope OCR"
        return files

    monkeypatch.setattr(m, "git_files", changed)
    with pytest.raises(RuntimeError, match="preserved_file_git_changed"):
        m.build(tmp_path, tmp_path / "base.tar.gz", tmp_path / "changed_ocr", "a" * 40)


@pytest.mark.parametrize("last", ["correct", "wrong", "whiteout", "opaque"])
def test_preserved_base_uses_last_effective_layer(
    candidate: tuple[Path, dict[str, Any]], last: str
) -> None:
    members: dict[str, bytes] = {}
    descriptors = []
    path = "app/app/infrastructure/ai/zhipu.py"
    entries = [(path, b"repository_ocr = True\n"), (path, b"frozen_live_ocr = True\n")]
    if last == "wrong":
        entries.append((path, b"unexpected final layer"))
    elif last == "whiteout":
        entries.append(("app/app/infrastructure/ai/.wh.zhipu.py", b""))
    elif last == "opaque":
        entries.append(("app/app/infrastructure/.wh..wh..opq", b""))
    for name, body in entries:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as layer:
            m.tar_member(layer, name, body)
        zipped = gzip.compress(buffer.getvalue(), mtime=0)
        desc = m.describe(zipped, m.OCI + "layer.v1.tar+gzip")
        descriptors.append(desc)
        members["blobs/sha256/" + desc["digest"][7:]] = zipped
    if last == "correct":
        assert m.preserved_base_hashes(members, {"layers": descriptors}) == {
            "infrastructure/ai/zhipu.py": {
                "runtime_sha256": m.sha(b"frozen_live_ocr = True\n"),
                "runtime_size": len(b"frozen_live_ocr = True\n"),
            }
        }
    else:
        with pytest.raises(RuntimeError, match="preserved_base_bytes"):
            m.preserved_base_hashes(members, {"layers": descriptors})


def test_next_mwf_window() -> None:
    value = m.next_window(datetime(2026, 9, 22, 8, tzinfo=UTC))
    assert value == {
        "prepare_at": "2026-09-23T09:00:00+08:00",
        "upload_at": "2026-09-23T10:00:00+08:00",
        "expires_at": "2026-09-23T16:00:00+08:00",
    }


class FakeHost:
    def __init__(self, baseline: dict[str, Any]):
        self.calls: list[tuple[Any, ...]] = []
        self.baseline = baseline

    def compose(self, *args: Any, **kwargs: Any) -> bytes:
        self.calls.append(args)
        return b""

    def capture(self, manifest: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("capture",))
        return self.baseline


def fake_deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None = None
) -> tuple[Any, FakeHost]:
    baseline: dict[str, Any] = {"files": {}}
    host = FakeHost(baseline)
    operation = m.Deployment(
        host, tmp_path / "candidate.json", {"revision": "a" * 40}, baseline
    )
    operation.backup_dir = tmp_path / "backup"

    def record(name: str) -> Any:
        def step(*args: Any) -> Any:
            host.calls.append((name,))
            if name == "backup":
                operation.backup_dir.mkdir()
            if name == "activate":
                operation.activated = True
            if failure == name:
                raise RuntimeError("fixture_failure")
            return {"status": "deployed"}

        return step

    for name in ("plan", "load", "fence_stopped", "backup", "activate", "verify"):
        monkeypatch.setattr(operation, name, record(name))
    monkeypatch.setattr(m, "PROTECTED_FILES", ())
    monkeypatch.setattr(m.time, "sleep", lambda *_: None)
    moments = iter([0, 121, 122, 123])
    monkeypatch.setattr(m.time, "monotonic", lambda: next(moments))
    return operation, host


def test_apply_stops_before_backup_and_only_switches_12_apps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation, host = fake_deployment(tmp_path, monkeypatch)
    assert operation.apply()["status"] == "deployed"
    commands = [call[0] for call in host.calls]
    assert (
        commands.index("stop")
        < commands.index("backup")
        < commands.index("activate")
        < commands.index("up")
    )
    up = next(call for call in host.calls if call[0] == "up")
    assert "--no-build" in up and "--no-deps" in up and "--pull" in up and "never" in up
    assert set(up[-12:]) == set(m.SERVICES)
    assert "postgres" not in up and "minio" not in up and "backend-migrate" not in up


def test_activation_failure_never_restarts_old_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation, host = fake_deployment(tmp_path, monkeypatch, "verify")
    with pytest.raises(RuntimeError, match="fixture_failure"):
        operation.apply()
    assert not any(call[0] == "start" for call in host.calls)
    assert host.calls[-1][0] == "stop"
    assert set(host.calls[-1][-12:]) == set(m.SERVICES)
    assert not (operation.backup_dir / "activation-receipt.json").exists()


def test_pre_activation_failure_can_restart_unchanged_original_containers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation, host = fake_deployment(tmp_path, monkeypatch, "backup")
    with pytest.raises(RuntimeError, match="fixture_failure"):
        operation.apply()
    assert host.calls[-2:] == [("start", *m.SERVICES), ("capture",)]
    assert not any(call[0] == "activate" for call in host.calls)


def test_attempt_directory_blocks_replay(tmp_path: Path) -> None:
    operation = m.Deployment(
        FakeHost({}), tmp_path / "candidate.json", {"revision": "a" * 40}, {}
    )
    operation.backup_dir = tmp_path
    with pytest.raises(RuntimeError, match="attempt_already_exists_reconcile_only"):
        operation.plan()


def test_readonly_db_fingerprint_and_historical_unknown_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = m.Host()
    queries = []
    tables = [
        "official_account_single_editions",
        "official_account_draft_owners",
        "official_account_article_versions",
        "official_account_render_versions",
        "official_account_generated_visuals",
        "official_account_article_attempts",
        "wechat_mp_draft_jobs",
    ]

    def scalar(sql: str) -> str:
        queries.append(sql)
        if "alembic_version" in sql:
            return m.SCHEMA
        if "pg_tables" in sql:
            return "\n".join(tables)
        if "FROM copy_generation_jobs j JOIN" in sql:
            return m.HISTORICAL_COPY_COHORT_SHA
        if "json_build_object" in sql:
            return '{"count":3,"sha256":"' + "a" * 64 + '"}'
        return "0"

    monkeypatch.setattr(host, "scalar", scalar)
    assert set(host.db_snapshot()) == {*tables, "historical_preview_copy_jobs"}
    host.idle()
    assert all(sql.startswith("SELECT ") for sql in queries)
    assert any("to_jsonb(t)-'updated_at'" in sql for sql in queries)
    assert any(
        "'outcome_unknown','delivery_unknown','result_unknown'" in sql
        and "expires_at" in sql
        for sql in queries
    )
    with pytest.raises(RuntimeError, match="readonly_sql_only"):
        m.Host().scalar("UPDATE forbidden SET value=1")


def test_readonly_plan_issues_no_mutating_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup = tmp_path / "backups"
    backup.mkdir(mode=0o700)
    monkeypatch.setattr(m, "BACKUP_ROOT", backup)
    baseline = {"captured_at": datetime.now(UTC).isoformat()}
    host = FakeHost(baseline)
    operation = m.Deployment(
        host, tmp_path / "candidate.json", {"revision": "a" * 40}, baseline
    )
    operation.plan()
    assert host.calls == [("capture",)]
    assert not operation.backup_dir.exists()
