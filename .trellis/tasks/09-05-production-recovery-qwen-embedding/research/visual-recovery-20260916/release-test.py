from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parent


def app_files(checksum: str = "d" * 64) -> dict[str, str]:
    return {path: checksum for path in C.ALLOWED_FILES}


def migration_files(checksum: str = "e" * 64) -> dict[str, str]:
    return {C.MIGRATION_FILE: checksum}


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


O = load("recovery_release_test_operator", ROOT / "release-deploy.py")
C, D, S = O.C, O.D, O.S
B = load("recovery_release_test_build", ROOT / "release-build.py")
V = load("recovery_release_test_validate", ROOT / "release-validate.py")
legacy_test = C.archived_path("deploy").with_name("test_no_source_link_release.py")
assert (
    C.digest(legacy_test.read_bytes())
    == "e380adf2cbce19727770e18b224cc3a2db1518b7e416598728153f1129569d1f"
)
H = load("recovery_release_archived_harness", legacy_test)


def snapshot() -> dict:
    return {
        "database": {
            "schema_head": C.PREVIOUS_SCHEMA,
            "body_checksum_index": C.BODY_CHECKSUM_INDEX_BASELINE,
        },
        "history": {
            name: {"count": 15 if name == "owners" else 1, "sha256": "a" * 64}
            for name in (*S.HISTORY_TABLES, "owners")
        },
        "target": {
            "edition_count": 1,
            "edition_id": C.EDITION,
            "business_date": C.BUSINESS_DATE,
            "status": "outcome_unknown",
            "lease_clear": True,
            "article_run_id": C.ARTICLE,
            "prepared_absent": True,
            "article_status": "result_unknown",
            "article_stage": "result_unknown",
            "article_version_id": C.VERSION,
            "article_lease_clear": True,
            "visual_count": 1,
            "visual_id": C.VISUAL,
            "visual_status": "result_unknown",
            "visual_version_id": C.VERSION,
            "visual_run_id": C.ARTICLE,
            "visual_error": "official_account_generated_visual_result_unknown",
            "owner_count": 1,
            "owner_valid": True,
            "event_id": C.EVENT,
        },
        "runtime_files": {
            name: {"sha256": "a" * 64, **S.RUNTIME_METADATA[name]}
            for name in (".env", "compose.yaml")
        },
    }


def manifest() -> dict:
    helpers = {
        name: C.digest((ROOT / name).read_bytes())
        for name in (
            "release-build.py",
            "release-common.py",
            "release-snapshot.py",
            "release-journal.py",
            "release-validate.py",
            "release-deploy.py",
        )
    }
    helpers.update(
        {"release-base-" + role + ".py": value[1] for role, value in C.ARCHIVED.items()}
    )
    return {
        "version": C.CHANGE,
        "revision": "a" * 40,
        "previous_revision": C.PREVIOUS_REVISION,
        "base_ref": C.BASE_REF,
        "base_archive_sha256": C.BASE_ARCHIVE_SHA256,
        "candidate_tag": C.REPOSITORY + ":visual-recovery-" + "a" * 12,
        "candidate_ref": C.REPOSITORY + "@sha256:" + "b" * 64,
        "candidate_image_id": "sha256:" + "b" * 64,
        "archive": "backend-image.oci.tar.gz",
        "archive_sha256": "c" * 64,
        "app_files": app_files(),
        "migration_files": migration_files(),
        "previous_schema": C.PREVIOUS_SCHEMA,
        "target_schema": C.TARGET_SCHEMA,
        "config_transition": {
            "key": C.VISUAL_POLICY_KEY,
            "from": C.PREVIOUS_VISUAL_POLICY,
            "to": C.TARGET_VISUAL_POLICY,
            "image_max_attempts": C.IMAGE_MAX_ATTEMPTS,
        },
        "validator": "release-validate.py",
        "validator_sha256": helpers["release-validate.py"],
        "helpers": helpers,
        "production_snapshot": snapshot(),
    }


def owners() -> list:
    rows = H.owner_rows()
    rows.append(
        {
            "account_fingerprint": D.SINGLE_ACCOUNT,
            "key_kind": "event",
            "key_value": C.EVENT,
            "owner": C.EDITION,
            "status": "outcome_unknown",
            "provenance_fingerprint": "f" * 64,
            "created_at": "2026-09-16T01:00:12+00:00",
            "updated_at": "2026-09-16T01:04:46+00:00",
        }
    )
    return rows


def test_snapshot_accepts_exact_unknown_only():
    assert S.validate_snapshot(snapshot()) == snapshot()
    migrated = snapshot()
    migrated["database"] = {
        "schema_head": C.TARGET_SCHEMA,
        "body_checksum_index": None,
    }
    assert (
        S.validate_snapshot(migrated, expected_schema=C.TARGET_SCHEMA)["database"]
        == migrated["database"]
    )
    for key, value in (
        ("edition_id", "f" * 36),
        ("visual_error", "official_account_image_result_unknown"),
        ("event_id", "f" * 36),
        ("lease_clear", False),
        ("article_lease_clear", False),
        ("owner_valid", False),
        ("prepared_absent", False),
        ("edition_count", 0),
        ("visual_count", 2),
    ):
        changed = snapshot()
        changed["target"][key] = value
        with pytest.raises(RuntimeError):
            S.validate_snapshot(changed)


def test_snapshot_never_contains_raw_history():
    query = S.snapshot_query()
    assert "'sha256'" in query and "to_jsonb(t)-'updated_at'" in query
    assert not any(word in query.upper() for word in ("UPDATE ", "DELETE ", "INSERT "))
    bad = snapshot()
    bad["history"]["official_account_article_versions"]["body"] = "private"
    with pytest.raises(RuntimeError, match="history_value"):
        S.validate_snapshot(bad)


def test_manifest_binds_hash_all_helpers_and_scope(tmp_path):
    value = manifest()
    p = tmp_path / "candidate.json"
    p.write_bytes(C.canonical(value))
    assert C.manifest(p, C.digest(p.read_bytes())) == value
    with pytest.raises(RuntimeError, match="manifest_hash"):
        C.manifest(p, "0" * 64)
    changed_helpers = dict(value["helpers"])
    changed_helpers["release-build.py"] = "0" * 64
    changed = {**value, "helpers": changed_helpers}
    p.write_bytes(C.canonical(changed))
    with pytest.raises(RuntimeError, match="manifest_helper_changed"):
        C.manifest(p, C.digest(p.read_bytes()))
    for field, bad in (
        ("candidate_tag", "other"),
        ("previous_revision", "1" * 40),
        ("app_files", {"core/config.py": "a" * 64}),
        ("migration_files", {}),
        ("target_schema", C.PREVIOUS_SCHEMA),
        ("config_transition", {}),
        ("archive", "../../a.tar.gz"),
        ("helpers", {}),
        ("base_archive_sha256", "0" * 64),
    ):
        changed = {**value, field: bad}
        p.write_bytes(C.canonical(changed))
        with pytest.raises(RuntimeError):
            C.manifest(p, C.digest(p.read_bytes()))


def test_helper_tamper_fails_before_import(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ROOT", tmp_path)
    (tmp_path / "release-base-deploy.py").write_text(
        "raise Exception('must never execute')"
    )
    with pytest.raises(RuntimeError, match="archive_helper_hash"):
        C.archived("deploy")


def test_owner_only_exact_unknown_allowed_and_only_updated_at_ignored():
    rows = owners()
    checksum = O.validate_owners(rows, snapshot())
    changed = copy.deepcopy(rows)
    for row in changed:
        row["updated_at"] = "2026-09-16T08:00:00+00:00"
    assert O.validate_owners(changed, snapshot()) == checksum
    changed[-1]["provenance_fingerprint"] = "b" * 64
    assert O.validate_owners(changed, snapshot()) != checksum
    for field, value in (
        ("owner", "other"),
        ("status", "acknowledged"),
        ("key_value", "other"),
        ("updated_at", "2026-09-15T00:00:00+00:00"),
    ):
        changed = copy.deepcopy(rows)
        changed[-1][field] = value
        with pytest.raises(RuntimeError):
            O.validate_owners(changed, snapshot())
    rows[1]["status"] = "outcome_unknown"
    with pytest.raises(RuntimeError):
        O.validate_owners(rows, snapshot())


def idle_fixture(monkeypatch, future_count=0):
    operation = O.Deployment(Path("/tmp/candidate.json"), manifest())
    operation.primary_env = (
        (
            C.VISUAL_POLICY_KEY
            + "="
            + C.PREVIOUS_VISUAL_POLICY
            + "\nIMAGE_MAX_ATTEMPTS="
            + C.IMAGE_MAX_ATTEMPTS
            + "\n"
        ).encode(),
        SimpleNamespace(),
    )
    cohort = H.cohort_rows()
    digest = hashlib.sha256(
        json.dumps(
            cohort, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
    monkeypatch.setattr(D, "HISTORICAL_COHORT_SHA256", digest)
    db = snapshot()
    db.pop("runtime_files")
    replies = {
        D.BUSINESS_DATE_QUERY: C.BUSINESS_DATE,
        D.HISTORICAL_COHORT_QUERY: json.dumps(cohort),
        D.WECOM_ACTIVE_QUERY: H.wecom_snapshot(H.future_wecom_rows(future_count)),
        D.IDLE_QUERY: str(7 + future_count),
        D.OWNER_QUERY: json.dumps(owners()),
        S.snapshot_query(): json.dumps(db),
    }
    monkeypatch.setattr(operation, "scalar", lambda query: replies[query])
    runtime = copy.deepcopy(snapshot()["runtime_files"])
    runtime[".env"]["sha256"] = C.digest(operation.primary_env[0])
    monkeypatch.setattr(S, "runtime_files", lambda _root: runtime)
    return operation, replies


@pytest.mark.parametrize("future_count", [0, 2])
def test_idle_allows_one_frozen_terminal_edition_and_future_wecom(
    monkeypatch, future_count
):
    operation, replies = idle_fixture(monkeypatch, future_count)
    operation.idle()
    operation.idle()
    assert operation.future_wecom_count == future_count
    replies[D.IDLE_QUERY] = str(8 + future_count)
    with pytest.raises(RuntimeError, match="queue_or_owner_not_idle"):
        operation.idle()


@pytest.mark.parametrize("scope", ["history", "target", "date", "config"])
def test_idle_rejects_state_history_config_or_date_drift(monkeypatch, scope):
    operation, replies = idle_fixture(monkeypatch)
    operation.idle()
    if scope in {"target", "history"}:
        db = json.loads(replies[S.snapshot_query()])
        if scope == "history":
            db["history"]["official_account_article_attempts"]["sha256"] = "e" * 64
        else:
            db["target"]["status"] = "retry_scheduled"
        replies[S.snapshot_query()] = json.dumps(db)
    elif scope == "date":
        replies[D.BUSINESS_DATE_QUERY] = "2026-09-17"
    else:
        files = copy.deepcopy(snapshot()["runtime_files"])
        files[".env"]["sha256"] = "e" * 64
        monkeypatch.setattr(S, "runtime_files", lambda _root: files)
    with pytest.raises(RuntimeError):
        operation.idle()


def test_readonly_sql_hard_gate(monkeypatch):
    operation = O.Deployment(Path("/tmp/candidate.json"), manifest())
    calls = []
    monkeypatch.setattr(operation, "compose", lambda *args: calls.append(args) or "1")
    assert operation.scalar("SELECT 1") == "1"
    assert "default_transaction_read_only=on" in " ".join(calls[0])
    for query in (
        "UPDATE table SET status='queued'",
        "SELECT 1; DELETE FROM table",
        "INSERT INTO table DEFAULT VALUES",
    ):
        with pytest.raises(RuntimeError, match="readonly_query"):
            operation.scalar(query)


def test_env_patch_changes_only_v2_to_v3_and_keeps_outer_attempts_one():
    original = (
        b"APP_ENV=production\n"
        + C.VISUAL_POLICY_KEY.encode()
        + b"="
        + C.PREVIOUS_VISUAL_POLICY.encode()
        + b"\nIMAGE_MAX_ATTEMPTS=1\nUNCHANGED=value\n"
    )
    patched = O.patch_visual_policy(original, C.TARGET_VISUAL_POLICY)
    assert patched == original.replace(
        C.PREVIOUS_VISUAL_POLICY.encode(), C.TARGET_VISUAL_POLICY.encode(), 1
    )
    assert O.patch_visual_policy(patched, C.PREVIOUS_VISUAL_POLICY) == original
    for invalid in (
        original.replace(b"IMAGE_MAX_ATTEMPTS=1", b"IMAGE_MAX_ATTEMPTS=3"),
        original + b"IMAGE_MAX_ATTEMPTS=1\n",
        original.replace(C.PREVIOUS_VISUAL_POLICY.encode(), b"unreviewed"),
    ):
        with pytest.raises(RuntimeError):
            O.patch_visual_policy(invalid, C.TARGET_VISUAL_POLICY)


def test_database_backup_writes_validated_custom_dump(tmp_path, monkeypatch):
    operation = O.Deployment(tmp_path / "candidate.json", manifest())
    operation.backup_dir = tmp_path
    monkeypatch.setattr(D, "APP", tmp_path)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if "pg_dump" in " ".join(args):
            kwargs["stdout"].write(b"PGDMP-fixture")
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        return SimpleNamespace(returncode=0, stdout=b"validated-list", stderr=b"")

    monkeypatch.setattr(O.subprocess, "run", run)
    checksum = operation.database_backup()
    dump = tmp_path / "postgres-before-0048.dump"
    assert checksum == C.digest(b"PGDMP-fixture")
    assert stat.S_IMODE(dump.stat().st_mode) == 0o600
    assert any("pg_dump" in " ".join(call) for call in calls)
    assert any("pg_restore" in " ".join(call) for call in calls)
    assert any("--file=/dev/null" in call for call in calls)


def test_forward_recovery_keeps_0048_v2_and_stops_oa_writers_on_failed_health(
    tmp_path,
):
    operation = O.Deployment(tmp_path / "candidate.json", manifest())
    events = []
    operation.expected_schema = C.TARGET_SCHEMA
    operation.migration_attempted = True
    operation.stop = lambda: events.append("stop")
    operation.activate_candidate_v2 = lambda: (
        setattr(operation, "expected_visual_policy", C.PREVIOUS_VISUAL_POLICY),
        events.append("activate_v2"),
    )
    operation.scalar = lambda _query: C.TARGET_SCHEMA
    operation.verify_database_baseline = lambda: events.append("database_0048")
    operation.start = lambda _reference: events.append("start_candidate")
    operation.wait_ready = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("health_failed")
    )
    operation.stop_official_account_writers = lambda: events.append(
        "oa_writers_stopped"
    )
    with pytest.raises(RuntimeError, match="forward_recovery_incomplete"):
        operation.recover_forward()
    assert operation.expected_schema == C.TARGET_SCHEMA
    assert operation.expected_visual_policy == C.PREVIOUS_VISUAL_POLICY
    assert events == [
        "stop",
        "activate_v2",
        "database_0048",
        "start_candidate",
        "oa_writers_stopped",
    ]


class Fake(O.Deployment):
    def __init__(self, tmp_path, failure=None):
        super().__init__(tmp_path / "candidate.json", manifest())
        self.events, self.failure, self.failed = [], failure, False
        self.database_backup_sha256 = "f" * 64

    def step(self, name):
        self.events.append(name)
        if self.failure == name and not self.failed:
            self.failed = True
            raise RuntimeError("injected_failure")

    def log(self, phase):
        self.events.append("log:" + phase)

    def preflight(self):
        self.step("preflight")

    def validate_archive(self):
        self.step("validate")

    def fence(self):
        self.step("fence")

    def stop(self):
        self.step("stop")

    def post_quiescence_fence(self):
        self.step("post_fence")

    def backup(self):
        self.step("backup")

    def verify_database_baseline(self):
        self.step("database_baseline")

    def load_candidate(self):
        self.step("load")

    def migrate(self):
        self.migration_attempted = True
        self.step("migrate")
        self.expected_schema = C.TARGET_SCHEMA

    def activate(self):
        self.step("activate")
        self.expected_visual_policy = C.TARGET_VISUAL_POLICY

    def start(self, reference):
        self.step("start_old" if reference == C.BASE_REF else "start_new")

    def wait_ready(self, reference, image_id, **kwargs):
        self.step("ready_old" if reference == C.BASE_REF else "ready_new")

    def success_receipt(self):
        self.step("receipt")

    def rollback_before_migration(self):
        self.step("rollback_old")

    def recover_forward(self):
        self.step("recover_forward")


@pytest.mark.parametrize(
    "failure",
    [
        "preflight",
        "validate",
        "fence",
    ],
)
def test_pre_quiescence_failure_does_not_restart(tmp_path, failure):
    operation = Fake(tmp_path, failure)
    with pytest.raises(RuntimeError, match="injected_failure"):
        O.execute(operation)
    assert "stop" not in operation.events
    assert "rollback_old" not in operation.events
    assert "recover_forward" not in operation.events


@pytest.mark.parametrize(
    "failure",
    [
        "stop",
        "post_fence",
        "backup",
        "database_baseline",
        "load",
    ],
)
def test_pre_migration_failure_restores_prior_runtime(tmp_path, failure):
    operation = Fake(tmp_path, failure)
    with pytest.raises(RuntimeError, match="injected_failure"):
        O.execute(operation)
    assert operation.events.count("rollback_old") == 1
    assert "recover_forward" not in operation.events


@pytest.mark.parametrize(
    "failure",
    [
        "migrate",
        "activate",
        "start_new",
        "ready_new",
        "receipt",
    ],
)
def test_post_migration_attempt_failure_recovers_forward_only(tmp_path, failure):
    operation = Fake(tmp_path, failure)
    with pytest.raises(RuntimeError, match="deployment_failed_forward_recovered"):
        O.execute(operation)
    assert operation.events.count("recover_forward") == 1
    assert "rollback_old" not in operation.events


def test_success_orders_backup_load_migration_env_switch_and_start(tmp_path):
    operation = Fake(tmp_path)
    O.execute(operation)
    post_fences = [
        index for index, event in enumerate(operation.events) if event == "post_fence"
    ]
    assert len(post_fences) == 2
    assert (
        operation.events.index("stop")
        < post_fences[0]
        < operation.events.index("backup")
        < operation.events.index("load")
        < post_fences[1]
        < operation.events.index("migrate")
        < operation.events.index("activate")
        < operation.events.index("start_new")
        < operation.events.index("ready_new")
    )


def test_receipt_records_migration_backup_v3_and_no_external_calls(
    tmp_path, monkeypatch
):
    operation = O.Deployment(tmp_path / "candidate.json", manifest())
    operation.backup_dir = tmp_path
    operation.expected_schema = C.TARGET_SCHEMA
    operation.expected_visual_policy = C.TARGET_VISUAL_POLICY
    operation.database_backup_sha256 = "f" * 64
    monkeypatch.setattr(operation, "idle", lambda **kwargs: None)
    operation.success_receipt()
    receipt = json.loads((tmp_path / "result.json").read_bytes())
    assert (
        receipt["single_editions"] == 1 and receipt["target_state"] == "outcome_unknown"
    )
    assert receipt["migration_executed"] is True
    assert receipt["schema_head"] == C.TARGET_SCHEMA
    assert receipt["visual_pipeline_version"] == C.TARGET_VISUAL_POLICY
    assert receipt["image_max_attempts"] == "1"
    assert receipt["postgres_backup_sha256"] == "f" * 64
    assert receipt["model_calls"] == receipt["social_calls"] == 0


def git_call(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo).decode().strip()


def test_builder_uses_commit_blob_even_when_worktree_is_dirty(tmp_path, monkeypatch):
    git_call(tmp_path, "init", "-q")
    git_call(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_call(tmp_path, "config", "user.name", "Fixture")
    for relative in C.ALLOWED_FILES:
        path = tmp_path / "backend/app" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old = 1\n")
    example = tmp_path / ".env.example"
    example.write_text("# old documentation\n")
    git_call(tmp_path, "add", ".")
    git_call(tmp_path, "commit", "-qm", "base")
    base = git_call(tmp_path, "rev-parse", "HEAD")
    monkeypatch.setattr(B.C, "PREVIOUS_REVISION", base)
    for relative in C.ALLOWED_FILES:
        (tmp_path / "backend/app" / relative).write_text("new = 2\n")
    migration = tmp_path / "backend" / C.MIGRATION_FILE
    migration.parent.mkdir(parents=True, exist_ok=True)
    migration.write_text("revision = '20260916_0048'\n")
    example.write_text("# V3 documentation only\n")
    git_call(tmp_path, "add", ".")
    git_call(tmp_path, "commit", "-qm", "candidate")
    revision = git_call(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "backend/app/core/errors.py").write_text(
        "unrelated_dirty_content = 3\n"
    )
    sources, migrations = B.committed_sources(tmp_path, revision)
    assert sources == {relative: b"new = 2\n" for relative in C.ALLOWED_FILES}
    assert migrations == {C.MIGRATION_FILE: b"revision = '20260916_0048'\n"}
    unrelated = tmp_path / "backend/app/core/config.py"
    unrelated.write_text("unrelated = 4\n")
    git_call(tmp_path, "add", str(unrelated))
    git_call(tmp_path, "commit", "-qm", "unrelated")
    with pytest.raises(RuntimeError, match="unreviewed_app_file"):
        B.committed_sources(tmp_path, git_call(tmp_path, "rev-parse", "HEAD"))
    git_call(tmp_path, "rm", "-q", "backend/app/core/config.py")
    git_call(tmp_path, "commit", "-qm", "remove unrelated app")
    extra_migration = tmp_path / "backend/alembic/versions/20260916_0049_unreviewed.py"
    extra_migration.write_text("revision = '20260916_0049'\n")
    git_call(tmp_path, "add", str(extra_migration))
    git_call(tmp_path, "commit", "-qm", "unreviewed migration")
    with pytest.raises(RuntimeError, match="unreviewed_migration_file"):
        B.committed_sources(tmp_path, git_call(tmp_path, "rev-parse", "HEAD"))


def test_new_overlay_is_exact_and_rejects_added_sources():
    bodies = {relative: b"fixture = 1\n" for relative in C.ALLOWED_FILES}
    migrations = {C.MIGRATION_FILE: b"revision = '20260916_0048'\n"}
    raw, _zipped = B.build_layer(bodies, migrations)
    V.validate_overlay_layer(
        raw,
        app_files={key: C.digest(value) for key, value in bodies.items()},
        migration_files={key: C.digest(value) for key, value in migrations.items()},
    )
    extra_raw, _ = B.build_layer(
        {**bodies, "core/config.py": b"fixture = 2\n"}, migrations
    )
    with pytest.raises(RuntimeError, match="overlay_layer_member"):
        V.validate_overlay_layer(
            extra_raw,
            app_files={key: C.digest(value) for key, value in bodies.items()},
            migration_files={key: C.digest(value) for key, value in migrations.items()},
        )


def test_oci_validator_current_base_graph_and_tampered_metadata(monkeypatch):
    archive = Path(
        "/root/projects/edu-ai-lead-agent/output/no-source-links-01ff75eed1ed/backend-image.oci.tar.gz"
    )
    if not archive.is_file():
        pytest.skip("operator's checksum-bound current-base archive not available")
    assert B.B.file_digest(archive) == C.BASE_ARCHIVE_SHA256
    base_validator = C.archived("validate")
    original = base_validator.safe_members(archive)
    base = json.loads(original["blobs/sha256/" + C.BASE_MANIFEST[7:]])
    config = json.loads(original["blobs/sha256/" + base["config"]["digest"][7:]])
    bodies = {relative: b"fixture = 1\n" for relative in C.ALLOWED_FILES}
    migrations = {C.MIGRATION_FILE: b"revision = '20260916_0048'\n"}
    raw, compressed = B.build_layer(bodies, migrations)
    revision, created = "a" * 40, "2026-09-16T08:00:00Z"
    tag = C.REPOSITORY + ":visual-recovery-" + revision[:12]
    config["config"]["Labels"].update(
        {
            "org.opencontainers.image.revision": revision,
            "org.opencontainers.image.created": created,
            "edu.ai.change": C.CHANGE,
            "edu.ai.overlay.base": C.BASE_MANIFEST,
        }
    )
    config["rootfs"]["diff_ids"].append("sha256:" + C.digest(raw))
    config["history"].append(
        {
            "created": created,
            "created_by": C.HISTORY_COMMAND,
            "comment": "trellis exact-base offline overlay",
        }
    )

    def graph(configuration):
        cb = C.canonical(configuration)
        mb = C.canonical(
            {
                "schemaVersion": 2,
                "mediaType": B.B.OCI_MANIFEST,
                "config": B.B.descriptor(cb, B.B.OCI_CONFIG),
                "layers": [*base["layers"], B.B.descriptor(compressed, B.B.OCI_LAYER)],
            }
        )
        blobs = {
            "oci-layout": original["oci-layout"],
            "blobs/sha256/" + C.digest(cb): cb,
            "blobs/sha256/" + C.digest(mb): mb,
            "blobs/sha256/" + C.digest(compressed): compressed,
            "index.json": C.canonical(
                {
                    "schemaVersion": 2,
                    "mediaType": B.B.OCI_INDEX,
                    "manifests": [
                        {
                            **B.B.descriptor(mb, B.B.OCI_MANIFEST),
                            "annotations": {
                                "io.containerd.image.name": tag,
                                "org.opencontainers.image.ref.name": tag.rsplit(":", 1)[
                                    1
                                ],
                            },
                            "platform": {"architecture": "amd64", "os": "linux"},
                        }
                    ],
                }
            ),
        }
        for layer in base["layers"]:
            key = "blobs/sha256/" + layer["digest"][7:]
            blobs[key] = original[key]
        return blobs, C.REPOSITORY + "@sha256:" + C.digest(mb)

    blobs, reference = graph(config)
    # Supply the already validated in-memory tar members; avoid writing several
    # identical private-base archives just to alter public metadata fields.
    monkeypatch.setattr(base_validator, "safe_members", lambda _archive: blobs)
    monkeypatch.setattr(V.C, "archived", lambda _role: base_validator)
    kwargs = {
        "candidate_tag": tag,
        "candidate_ref": reference,
        "revision": revision,
        "app_files": {key: C.digest(value) for key, value in bodies.items()},
        "migration_files": {key: C.digest(value) for key, value in migrations.items()},
    }
    assert V.validate(archive, **kwargs)["status"] == "valid"
    for kind in ("runtime", "preserved_label", "history"):
        bad = copy.deepcopy(config)
        if kind == "runtime":
            bad["config"]["User"] = "root"
        elif kind == "preserved_label":
            bad["config"]["Labels"]["io.trellis.release.change"] = "tampered"
        else:
            bad["history"][0]["created_by"] = "tampered"
        blobs, kwargs["candidate_ref"] = graph(bad)
        with pytest.raises(RuntimeError):
            V.validate(archive, **kwargs)


def test_deploy_has_no_model_social_replay_or_downgrade_route():
    source = (ROOT / "release-deploy.py").read_text()
    for forbidden in (
        "/cgi-bin/",
        "draft/add",
        "draft/update",
        "open.bigmodel.cn",
        "comfly.org",
        "alembic downgrade",
        "visual_compensation",
    ):
        assert forbidden not in source
    assert '"upgrade",\n            C.TARGET_SCHEMA' in source
    assert "http://127.0.0.1:8000/healthz" in source
