from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

import r16_real_host as real
from r16_forward_operator import (
    ALEMBIC_ONLY_COMMAND,
    BASE_IMAGE,
    BASE_REF,
    BASE_REVISION,
    BASE_SCHEMA,
    MIGRATION_CHAIN,
    PROTECTED_FILES,
    SERVICES,
    TARGET_SCHEMA,
    VOLUMES,
    ReleaseBlocked,
    sha,
    valid_backup,
    valid_fresh_clone,
    valid_quiescent,
)

EMPTY_MD5 = "d41d8cd98f00b204e9800998ecf8427e"
TABLES = ["alembic_version", "wecom_delivery_jobs"] + [f"table_{i}" for i in range(8)]


class FakeCommands:
    def __init__(self, volume_paths: dict[str, Path], candidate_image: str) -> None:
        self.volume_paths = volume_paths
        self.candidate_image = candidate_image
        self.calls: list[tuple[str, ...]] = []
        self.envs: list[dict[str, str] | None] = []
        self.stopped = False
        self.candidate_started = False
        self.clone_schema = BASE_SCHEMA
        self.production_schema = BASE_SCHEMA
        self.fail_code: str | None = None
        self.runtime_tree_sha = real.R15_RUNTIME_TREE_SHA256
        self.dispatcher_key = "fake-group-key"
        self.compose_help = b"--no-build --no-deps --pull --wait --wait-timeout"
        self.names = {
            f"{i + 1:012x}": name
            for i, name in enumerate((*SERVICES, "postgres", "minio"))
        }

    def _sql(self, sql: str, *, clone: bool) -> bytes:
        if sql == "SELECT version_num FROM alembic_version":
            return (self.clone_schema if clone else self.production_schema).encode()
        if sql.startswith("SELECT tablename FROM pg_tables"):
            if "tablename LIKE" in sql:
                return b"wecom_delivery_jobs\n"
            return ("\n".join(TABLES) + "\n").encode()
        if sql.startswith("SELECT count(*)"):
            return b"0\n"
        if sql.startswith("SELECT md5("):
            return (EMPTY_MD5 + "\n").encode()
        if sql == real.HISTORICAL_WORK_COHORT_SQL:
            return b"reviewed\n"
        raise AssertionError("unexpected SQL shape")

    def run(
        self,
        argv: tuple[str, ...],
        *,
        code: str,
        timeout: int = 60,
        input_file: Path | None = None,
        output_file: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> bytes:
        del timeout
        self.calls.append(argv)
        self.envs.append(dict(env) if env is not None else None)
        if code == self.fail_code:
            raise ReleaseBlocked(code)
        if output_file is not None:
            output_file.write_bytes(b"PGDMP" + b"x" * 2048)
            output_file.chmod(0o600)
            return b""
        if input_file is not None and "pg_restore" in argv and "--list" in argv:
            assert input_file.read_bytes().startswith(b"PGDMP")
            return b"TABLE DATA alembic_version\n"
        if input_file is not None and "pg_restore" in argv:
            assert input_file.read_bytes().startswith(b"PGDMP")
            self.clone_schema = BASE_SCHEMA
            return b""
        if argv[:3] == ("docker", "image", "inspect"):
            candidate = argv[3] != BASE_REF
            digest = self.candidate_image if candidate else BASE_IMAGE
            revision = "1" * 40 if candidate else BASE_REVISION
            return json.dumps(
                [
                    {
                        "Id": digest,
                        "RepoDigests": [argv[3]],
                        "Config": {
                            "Labels": {"org.opencontainers.image.revision": revision}
                        },
                    }
                ]
            ).encode()
        if argv[:3] == ("docker", "volume", "inspect"):
            name = argv[3]
            return json.dumps(
                [{"Name": name, "Mountpoint": str(self.volume_paths[name])}]
            ).encode()
        if argv == ("docker", "compose", "up", "--help"):
            return self.compose_help
        if argv[:3] == ("docker", "compose", "--project-name"):
            if "config" in argv:
                return b""
            if "ps" in argv:
                name = argv[-1]
                return next(
                    key for key, value in self.names.items() if value == name
                ).encode()
            if "exec" in argv:
                if "pg_restore" in argv:
                    return b"TABLE DATA alembic_version\n"
                return self._sql(argv[-1], clone=False)
            if "stop" in argv:
                self.stopped = True
                return b""
            if "up" in argv:
                self.candidate_started = True
                self.stopped = False
                return b""
        if argv[:2] == ("docker", "inspect"):
            name = self.names[argv[2]]
            app = name in SERVICES
            dependency_mounts = (
                [
                    {
                        "Type": "volume",
                        "Name": real.DEPENDENCY_VOLUMES[name],
                    }
                ]
                if not app
                else []
            )
            image = (
                self.candidate_image if app and self.candidate_started else BASE_IMAGE
            )
            ref = (
                "offline.local/edu-ai/edu-ai-lead-agent-backend@" + image
                if app and self.candidate_started
                else BASE_REF
            )
            return json.dumps(
                [
                    {
                        "Id": argv[2].ljust(64, "0"),
                        "Image": image if app else "sha256:" + "4" * 64,
                        "State": {
                            "Status": "exited" if app and self.stopped else "running",
                            "Health": {"Status": "healthy"},
                        },
                        "RestartCount": 0,
                        "Config": {
                            "Image": ref if app else real.DEPENDENCY_REFS[name],
                            "Cmd": ["python"],
                            "Env": [
                                "APP_ENV=production",
                                "DATABASE_URL=postgresql+asyncpg://edu_ai:fake-db-password@postgres:5432/edu_ai",
                                *(
                                    [
                                        "WECOM_DELIVERY_PROVIDER=group_webhook",
                                        "WECOM_GROUP_WEBHOOK_KEY="
                                        + self.dispatcher_key,
                                    ]
                                    if name == "wecom-dispatcher"
                                    else []
                                ),
                            ],
                        },
                        "Mounts": dependency_mounts,
                        "NetworkSettings": {
                            "Networks": {"edu-ai-lead-agent_default": {}}
                        },
                    }
                ]
            ).encode()
        if argv[:2] == ("docker", "ps"):
            return b""
        if argv[:2] == ("docker", "exec"):
            if len(argv) >= 6 and argv[3:5] == ("python", "-c"):
                return json.dumps(
                    {
                        "files": real.R15_RUNTIME_FILES,
                        "sha256": self.runtime_tree_sha,
                    }
                ).encode()
            if "pg_isready" in argv:
                return b"accepting connections"
            return self._sql(argv[-1], clone=True)
        if argv[:2] == ("docker", "run"):
            if "--entrypoint" in argv and "alembic" in argv:
                if any(arg.startswith("r16-net-") for arg in argv):
                    self.clone_schema = TARGET_SCHEMA
                else:
                    self.production_schema = TARGET_SCHEMA
            return b"container-id"
        if argv[:2] in (
            ("docker", "network"),
            ("docker", "volume"),
            ("docker", "load"),
            ("docker", "stop"),
        ):
            return b"ok"
        if argv[:2] == ("systemctl", "is-active"):
            return b"active\n"
        if argv[0] == "curl":
            return b'{"status":"ok","environment":"production"}'
        raise AssertionError(f"unexpected command family: {argv[:2]}")


def _fixture(
    tmp_path: Path,
) -> tuple[real.RealHostAdapter, FakeCommands, dict[str, Any]]:
    app = tmp_path / "app"
    app.mkdir()
    backup_root = tmp_path / "backups"
    backup_root.mkdir(mode=0o700)
    attempt = backup_root / "r16-forward-test1"
    attempt.mkdir(mode=0o700)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "backend-image.oci.tar.gz").write_bytes(b"archive")
    host_files = {
        "compose.yaml": b"name: edu-ai-lead-agent\n",
        "scripts/doctor.sh": b"#!/bin/sh\nexit 0\n",
        "deploy/release/migration-compatibility.json": json.dumps(
            {
                "reviewed": True,
                "alembic_head": TARGET_SCHEMA,
                "previous_application_compatible": False,
            }
        ).encode(),
    }
    for name, body in host_files.items():
        target = bundle / "host-files" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    for name in PROTECTED_FILES:
        target = app / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if name in (".release-commit", "RELEASE_COMMIT"):
            body = (BASE_REVISION + "\n").encode()
        elif name == ".release.env":
            body = ("APP_IMAGE=" + BASE_REF + "\n").encode()
        elif name == ".env":
            body = b"WECOM_DELIVERY_PROVIDER=group_webhook\nWECOM_GROUP_WEBHOOK_KEY=fake-group-key\nPOSTGRES_USER=edu_ai\nPOSTGRES_PASSWORD=fake-db-password\nPOSTGRES_DB=edu_ai\n"
        else:
            body = b"baseline-file\n"
        target.write_bytes(body)
        target.chmod(0o600)
    brand = app / "private/brand-materials"
    brand.mkdir(parents=True)
    (brand / "brand.txt").write_bytes(b"private-brand")
    for name in real.SOURCE_DIRS:
        source = app / name
        source.mkdir(exist_ok=True)
        (source / "source.txt").write_bytes(b"source")
    volumes = {name: tmp_path / name for name in VOLUMES}
    for volume in volumes.values():
        volume.mkdir()
        (volume / "content.bin").write_bytes(b"persisted")
    image = "sha256:" + "2" * 64
    manifest = {
        "revision": "1" * 40,
        "image": image,
        "archive_sha256": sha(b"archive"),
        "host_files": {name: sha(body) for name, body in host_files.items()},
    }
    commands = FakeCommands(volumes, image)
    adapter = real.RealHostAdapter(
        commands,
        real.HostPaths(app=app, backup_root=backup_root),
        attempt,
        manifest,
        bundle,
        require_production_paths=False,
    )
    return adapter, commands, manifest


def test_real_adapter_draft_has_no_apply_entry_point(tmp_path: Path) -> None:
    adapter, commands, _ = _fixture(tmp_path)
    assert not hasattr(real, "main")
    assert commands.calls == []
    with pytest.raises(ReleaseBlocked, match="capture_required"):
        adapter.migrate_forward(ALEMBIC_ONLY_COMMAND, MIGRATION_CHAIN)
    assert commands.calls == []


def test_only_exact_historical_work_cohort_is_exempted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, _, _ = _fixture(tmp_path)
    monkeypatch.setattr(real, "HISTORICAL_WORK_COHORT_SHA256", sha(b"reviewed"))
    state = {"extra_pending": False, "cohort": "reviewed"}

    def fake_sql(sql: str) -> str:
        if sql.startswith("SELECT tablename FROM pg_tables"):
            return (
                "copy_generation_jobs\ncopy_generation_runs\n"
                "official_account_article_runs\nwecom_delivery_jobs"
            )
        if sql == real.HISTORICAL_WORK_COHORT_SQL:
            return state["cohort"]
        if sql.startswith("SELECT count(*) FROM public."):
            table = sql.split("public.", 1)[1].split(" ", 1)[0]
            if "delivery_unknown" in sql:
                return "5" if table == "official_account_article_runs" else "0"
            if table in {"copy_generation_jobs", "copy_generation_runs"}:
                return "8" if state["extra_pending"] else "7"
            return "0"
        raise AssertionError("unexpected read-only SQL")

    monkeypatch.setattr(adapter, "_sql", fake_sql)
    assert adapter._work_counts() == (0, 0)
    state["extra_pending"] = True
    with pytest.raises(ReleaseBlocked, match="unreviewed_pending_or_unknown_work"):
        adapter._work_counts()
    state["extra_pending"] = False
    state["cohort"] = "changed"
    with pytest.raises(ReleaseBlocked, match="historical_work_cohort_drift"):
        adapter._work_counts()


def test_readonly_sql_allows_only_exact_historical_cohort_cte(tmp_path: Path) -> None:
    adapter, commands, _ = _fixture(tmp_path)
    assert adapter._sql(real.HISTORICAL_WORK_COHORT_SQL) == "reviewed"
    prior = list(commands.calls)
    with pytest.raises(ReleaseBlocked, match="readonly_sql"):
        adapter._sql("WITH changed AS (DELETE FROM jobs) SELECT * FROM changed")
    assert commands.calls == prior


def test_compose_ignores_ambient_feature_and_image_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, commands, _ = _fixture(tmp_path)
    monkeypatch.setenv("WECOM_INFOGRAPHIC_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("APP_IMAGE", "unreviewed:image")
    adapter.capture()
    compose_envs = [
        env
        for call, env in zip(commands.calls, commands.envs, strict=True)
        if call[:3] == ("docker", "compose", "--project-name")
    ]
    assert compose_envs
    assert all(
        env is not None
        and "WECOM_INFOGRAPHIC_DELIVERY_ENABLED" not in env
        and "APP_IMAGE" not in env
        for env in compose_envs
    )


def test_live_runtime_tree_must_match_frozen_r15_bundle(tmp_path: Path) -> None:
    adapter, commands, _ = _fixture(tmp_path)
    commands.runtime_tree_sha = "f" * 64
    with pytest.raises(ReleaseBlocked, match="live_runtime_tree_drift"):
        adapter.capture()
    assert not any("stop" in call for call in commands.calls)


def test_running_dispatcher_recipient_must_match_protected_config(
    tmp_path: Path,
) -> None:
    adapter, commands, _ = _fixture(tmp_path)
    commands.dispatcher_key = "different-group"
    with pytest.raises(ReleaseBlocked, match="live_recipient_config_drift"):
        adapter.capture()
    assert not any("stop" in call for call in commands.calls)


def test_external_recipient_anchor_must_match_live_group(tmp_path: Path) -> None:
    adapter, _, _ = _fixture(tmp_path)
    adapter._trusted_recipient_fingerprint = "f" * 64
    with pytest.raises(ReleaseBlocked, match="trusted_recipient_mismatch"):
        adapter.capture()


def test_external_raw_key_hash_must_match_live_group(tmp_path: Path) -> None:
    adapter, _, _ = _fixture(tmp_path)
    adapter._trusted_recipient_fingerprint = sha(b"group_webhook\0fake-group-key")
    adapter._trusted_recipient_key_sha256 = "f" * 64
    with pytest.raises(ReleaseBlocked, match="trusted_recipient_key_mismatch"):
        adapter.capture()


def test_review_lockout_blocks_real_host_mutation_even_by_import(
    tmp_path: Path,
) -> None:
    adapter, commands, _ = _fixture(tmp_path)
    assert adapter._mutation_armed is False
    adapter._production_paths = True
    with pytest.raises(ReleaseBlocked, match="real_host_mutation_unarmed"):
        adapter.stop_writers()
    assert commands.calls == []


def test_real_host_cannot_arm_without_durable_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, commands, manifest = _fixture(tmp_path)
    baseline = adapter.capture()
    adapter._production_paths = True
    adapter.runner = real.SubprocessRunner()
    monkeypatch.setattr(real, "valid_production_manifest", lambda _manifest: None)
    with pytest.raises(ReleaseBlocked, match="mutation_intent_missing"):
        adapter.arm_production_mutation(manifest, baseline, "d" * 64)
    assert adapter._mutation_armed is False
    assert not any("stop" in call for call in commands.calls)


def test_capture_backup_clone_and_default_off_fake_host(tmp_path: Path) -> None:
    adapter, commands, manifest = _fixture(tmp_path)
    baseline = adapter.capture()
    assert baseline["schema"] == BASE_SCHEMA
    assert baseline["recipient_fingerprint"] == sha(b"group_webhook\0fake-group-key")
    adapter.stop_writers()
    assert adapter.verify_writers_stopped()
    quiet = adapter.capture_quiescent()
    valid_quiescent(quiet, baseline)
    backup = adapter.backup()
    valid_backup(backup, baseline)
    assert stat.S_IMODE((adapter.attempt_dir / "postgres.dump").stat().st_mode) == 0o600
    assert len(list(adapter.attempt_dir.glob("*.tar.gz"))) == 4
    assert adapter.stage_candidate_image(manifest) == manifest["image"]
    clone = adapter.rehearse_clone(str(backup["pg_dump_sha256"]))
    valid_fresh_clone(clone, baseline, backup)
    assert not any(
        "minio-init" in call or "backend-migrate" in call for call in commands.calls
    )
    assert sum("alembic" in call for call in commands.calls) == 1
    adapter.migrate_forward(ALEMBIC_ONLY_COMMAND, MIGRATION_CHAIN)
    assert sum("alembic" in call for call in commands.calls) == 2
    adapter.install_candidate(manifest)
    adapter.start_default_off(SERVICES)
    start = next(
        call for call in commands.calls if "up" in call and "--help" not in call
    )
    assert {"--no-build", "--no-deps", "never", "--wait"}.issubset(start)
    assert adapter.verify_candidate(manifest)
    assert (adapter.paths.app / ".env").read_bytes().count(b"fake-group-key") == 1
    assert (adapter.paths.app / ".release-commit").read_text().strip() == manifest[
        "revision"
    ]


def test_clone_rejects_different_dump_bytes_before_docker_mutation(
    tmp_path: Path,
) -> None:
    adapter, commands, manifest = _fixture(tmp_path)
    adapter.capture()
    adapter.stop_writers()
    backup = adapter.backup()
    adapter.stage_candidate_image(manifest)
    before = list(commands.calls)
    with pytest.raises(ReleaseBlocked, match="clone_dump_bytes"):
        adapter.rehearse_clone("f" * 64)
    assert commands.calls == before
    assert backup["pg_dump_sha256"] != "f" * 64


def test_clone_restore_failure_never_reaches_production_migration(
    tmp_path: Path,
) -> None:
    adapter, commands, manifest = _fixture(tmp_path)
    adapter.capture()
    adapter.stop_writers()
    backup = adapter.backup()
    adapter.stage_candidate_image(manifest)
    commands.fail_code = "clone_restore"
    with pytest.raises(ReleaseBlocked, match="clone_restore"):
        adapter.rehearse_clone(str(backup["pg_dump_sha256"]))
    assert not adapter._clone_verified
    assert not any("alembic" in call for call in commands.calls)
    with pytest.raises(ReleaseBlocked, match="production_migration_gate"):
        adapter.migrate_forward(ALEMBIC_ONLY_COMMAND, MIGRATION_CHAIN)


def test_bad_host_bundle_stops_before_any_protected_replacement(
    tmp_path: Path,
) -> None:
    adapter, _, manifest = _fixture(tmp_path)
    baseline = adapter.capture()
    adapter.stop_writers()
    backup = adapter.backup()
    adapter.stage_candidate_image(manifest)
    adapter.rehearse_clone(str(backup["pg_dump_sha256"]))
    adapter.migrate_forward(ALEMBIC_ONLY_COMMAND, MIGRATION_CHAIN)
    (adapter.bundle_dir / "host-files/compose.yaml").write_bytes(b"tampered")
    with pytest.raises(ReleaseBlocked, match="host_file_sha256"):
        adapter.install_candidate(manifest)
    for name in PROTECTED_FILES:
        assert (
            real._metadata(adapter.paths.app / name)["sha256"]
            == baseline["protected_files"][name]["sha256"]
        )


def test_symlinked_host_bundle_file_refused_before_replace(tmp_path: Path) -> None:
    adapter, _, manifest = _fixture(tmp_path)
    baseline = adapter.capture()
    adapter.stop_writers()
    backup = adapter.backup()
    adapter.stage_candidate_image(manifest)
    adapter.rehearse_clone(str(backup["pg_dump_sha256"]))
    adapter.migrate_forward(ALEMBIC_ONLY_COMMAND, MIGRATION_CHAIN)
    source = adapter.bundle_dir / "host-files/compose.yaml"
    target = adapter.bundle_dir / "same-bytes.yaml"
    target.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(target)
    with pytest.raises(ReleaseBlocked, match="unsafe_file_type"):
        adapter.install_candidate(manifest)
    assert all(
        real._metadata(adapter.paths.app / name)["sha256"]
        == baseline["protected_files"][name]["sha256"]
        for name in PROTECTED_FILES
    )


def test_tampered_bundle_refused_during_readonly_capture(tmp_path: Path) -> None:
    adapter, commands, _ = _fixture(tmp_path)
    (adapter.bundle_dir / "host-files/compose.yaml").write_bytes(b"tampered")
    with pytest.raises(ReleaseBlocked, match="host_file_sha256"):
        adapter.capture()
    assert commands.calls == []


def test_candidate_compose_syntax_blocks_before_any_stop(tmp_path: Path) -> None:
    adapter, commands, _ = _fixture(tmp_path)
    commands.fail_code = "candidate_compose_config"
    with pytest.raises(ReleaseBlocked, match="candidate_compose_config"):
        adapter.capture()
    assert not any("stop" in call for call in commands.calls)


def test_missing_compose_wait_capability_blocks_before_any_stop(tmp_path: Path) -> None:
    adapter, commands, _ = _fixture(tmp_path)
    commands.compose_help = b"--no-build --no-deps --pull"
    with pytest.raises(ReleaseBlocked, match="compose_up_capabilities"):
        adapter.capture()
    assert not any("stop" in call for call in commands.calls)


def test_flag_on_blocks_default_off_start(tmp_path: Path) -> None:
    adapter, commands, manifest = _fixture(tmp_path)
    adapter.capture()
    adapter.stop_writers()
    backup = adapter.backup()
    adapter.stage_candidate_image(manifest)
    adapter.rehearse_clone(str(backup["pg_dump_sha256"]))
    adapter.migrate_forward(ALEMBIC_ONLY_COMMAND, MIGRATION_CHAIN)
    adapter.install_candidate(manifest)
    with (adapter.paths.app / ".env").open("ab") as stream:
        stream.write(b"WECOM_INFOGRAPHIC_DELIVERY_ENABLED=true\n")
    before = list(commands.calls)
    with pytest.raises(ReleaseBlocked, match="default_off_start_gate"):
        adapter.start_default_off(SERVICES)
    assert not any("up" in call for call in commands.calls[len(before) :])


def test_archive_readback_and_symlink_refusal(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"hello")
    archive = tmp_path / "a.tar.gz"
    digest, manifest = real._archive_tree(source, archive)
    assert digest == real._metadata(archive)["sha256"]
    assert manifest["a.txt"]["sha256"] == sha(b"hello")
    assert manifest["."]["type"] == "dir"
    empty = source / "empty"
    empty.mkdir()
    second_digest, second_manifest = real._archive_tree(source, tmp_path / "c.tar.gz")
    assert second_digest != digest
    assert second_manifest["empty"]["type"] == "dir"
    (source / "link").symlink_to(source / "a.txt")
    with pytest.raises(ReleaseBlocked, match="unsafe_file_type"):
        real._archive_tree(source, tmp_path / "b.tar.gz")


def test_subprocess_error_redacts_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(real, "APP", tmp_path)
    with pytest.raises(ReleaseBlocked, match="safe_code") as info:
        real.SubprocessRunner().run(
            (sys.executable, "-c", "import sys; print('secret-value'); sys.exit(2)"),
            code="safe_code",
        )
    assert "secret-value" not in str(info.value)


def test_subprocess_explicit_env_does_not_inherit_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(real, "APP", tmp_path)
    monkeypatch.setenv("WECOM_INFOGRAPHIC_DELIVERY_ENABLED", "true")
    body = real.SubprocessRunner().run(
        (
            sys.executable,
            "-c",
            "import os; print(os.getenv('WECOM_INFOGRAPHIC_DELIVERY_ENABLED', 'absent'))",
        ),
        code="test_env",
        env={"PATH": "/usr/bin:/bin"},
    )
    assert body.strip() == b"absent"


def test_subprocess_default_env_pins_local_docker_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(real, "APP", tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "tcp://wrong-daemon:2375")
    monkeypatch.setenv("DOCKER_CONTEXT", "remote")
    body = real.SubprocessRunner().run(
        (
            sys.executable,
            "-c",
            "import os; print(os.getenv('DOCKER_HOST'), os.getenv('DOCKER_CONTEXT'))",
        ),
        code="test_docker_env",
    )
    assert body.strip() == b"unix:///var/run/docker.sock None"


def test_production_constructor_rejects_test_paths(tmp_path: Path) -> None:
    adapter, commands, manifest = _fixture(tmp_path)
    with pytest.raises(ReleaseBlocked, match="host_paths|root_required"):
        real.RealHostAdapter(
            commands,
            adapter.paths,
            adapter.attempt_dir,
            manifest,
            adapter.bundle_dir,
        )


def test_too_long_clone_suffix_blocks_before_capture(tmp_path: Path) -> None:
    adapter, commands, manifest = _fixture(tmp_path)
    with pytest.raises(ReleaseBlocked, match="attempt_name"):
        real.RealHostAdapter(
            commands,
            adapter.paths,
            adapter.paths.backup_root / ("r16-forward-" + "x" * 33),
            manifest,
            adapter.bundle_dir,
            require_production_paths=False,
        )
    assert commands.calls == []


def test_test_paths_cannot_pair_with_real_docker_runner(tmp_path: Path) -> None:
    adapter, _, manifest = _fixture(tmp_path)
    with pytest.raises(ReleaseBlocked, match="test_paths_real_runner_forbidden"):
        real.RealHostAdapter(
            real.SubprocessRunner(),
            adapter.paths,
            adapter.attempt_dir,
            manifest,
            adapter.bundle_dir,
            require_production_paths=False,
        )
    # A later accidental runner swap must not bypass the second lockout.
    adapter.runner = real.SubprocessRunner()
    with pytest.raises(ReleaseBlocked, match="real_host_mutation_unarmed"):
        adapter.stop_writers()
