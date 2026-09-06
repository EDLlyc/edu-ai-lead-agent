"""Provider-free release regressions; fixtures never contact a Docker daemon or host."""

from __future__ import annotations

import ast
import gzip
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
ARCHIVE = (
    ROOT
    / ".trellis/tasks/archive/2026-09/09-04-production-brand-embedding-hotfix/research"
)
VALIDATOR_PATH = HERE / "validate-substantive-release.py"
OPERATOR = HERE / "substantive-release-operator.sh"
BUILDER = HERE / "build-substantive-release.sh"
CAPTURE = HERE / "capture-substantive-production-baseline.sh"


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = load_module("substantive_validator", VALIDATOR_PATH)
# Reuse the archived graph/source fixtures and parametrized safety assertions,
# with their module globals explicitly redirected to THIS candidate validator.
# No archived source is modified, and operator tests below use the new shell.
LEGACY = load_module(
    "substantive_inherited_fixtures",
    ARCHIVE / "test-brand-embedding-hotfix-offline-release.py",
)
LEGACY.VALIDATOR = V
LEGACY.VALIDATOR_PATH = VALIDATOR_PATH
LEGACY.OPERATOR_PATH = OPERATOR
LEGACY.BUILDER_PATH = BUILDER
LEGACY.CAPTURE_PATH = CAPTURE
OLD_BASELINE = LEGACY._baseline
OLD_METADATA = LEGACY._metadata
OLD_GRAPH = LEGACY._oci_graph
OLD_SOURCE_ENTRIES = LEGACY._source_entries
NOW = datetime(2026, 9, 6, 6, 40, tzinfo=UTC)


def baseline(terminal_count: int = 18) -> dict:
    value = OLD_BASELINE(terminal_count)
    value.update(
        captured_at_utc=NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        business_date="2026-09-06",
        current_image_id=V.PRODUCTION_IMAGE_ID,
        current_image_reference=f"edu-ai-lead-agent-backend@{V.PRODUCTION_IMAGE_ID}",
        primary_env_sha256=V.PRODUCTION_PRIMARY_ENV_SHA256,
        release_env_sha256=V.PRODUCTION_RELEASE_ENV_SHA256,
        frozen_copy_job_sha256=V.FROZEN_COPY_JOB_SHA256,
    )
    value["effect_counts"].update(V.EXACT_EFFECT_COUNTS)
    return value


def metadata(stage: Path, manifest: str, config: str) -> dict:
    value = OLD_METADATA(stage, manifest, config)
    value["main_policy_commit"] = value.pop("main_fix_commit")
    value["main_tooling_commit"] = value.pop("main_operator_commit")
    value["scheduler_cutoff_utc"] = V.EARLIEST_PRODUCER_UTC
    value["transport_tag"] = (
        f"{LEGACY.REPOSITORY}:substantive-release-{LEGACY.RELEASE_COMMIT[:12]}"
    )
    return value


def graph(*args, **kwargs):
    raw, manifest, config = OLD_GRAPH(*args, **kwargs)
    entries = []
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive:
            stream = archive.extractfile(member) if member.isfile() else None
            value = stream.read() if stream is not None else None
            if member.name == "index.json" and value is not None:
                value = value.replace(
                    b":brand-embedding-", b":substantive-release-"
                ).replace(b'"brand-embedding-', b'"substantive-release-')
                member.size = len(value)
            entries.append((member, value))
    output = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as zipped,
        tarfile.open(fileobj=zipped, mode="w|") as archive,
    ):
        for member, value in entries:
            archive.addfile(member, io.BytesIO(value) if value is not None else None)
    return output.getvalue(), manifest, config


def source_entries():
    entries = {row[0]: row for row in OLD_SOURCE_ENTRIES()}
    for name in V.RUNTIME_DIFF:
        entries.setdefault(name, (name, "f", 0o644, b"# scoped fixture\n"))
        for parent in Path(name).parents:
            if str(parent) != ".":
                key = parent.as_posix()
                entries.setdefault(key, (key, "d", 0o755, None))
    return sorted(entries.values())


LEGACY._baseline = baseline
LEGACY._metadata = metadata
LEGACY._oci_graph = graph
LEGACY._source_entries = source_entries

# These assertions execute the current validator against the proven adversarial
# OCI/source fixtures. Old incident-specific expected counters are not reused.
for inherited in (
    "test_valid_stage_binds_distinct_manifest_config_and_repository_digest",
    "test_stage_rejects_source_incompatible_with_production_before_image_validation",
    "test_stage_rejects_unexpected_python_bytecode_cache",
    "test_release_identity_drift_is_rejected",
    "test_production_weekly_command_is_exactly_bound",
    "test_complete_oci_graph_rejects_tamper",
    "test_containerd_reference_normalization_is_exact",
    "test_containerd_reference_normalization_rejects_ambiguous_input",
    "test_source_archive_requires_one_declared_alembic_head",
    "test_alembic_revision_requires_one_static_unmodified_declaration",
    "test_alembic_revision_ast_has_explicit_resource_bounds",
    "test_source_archive_bounds_alembic_revision_count",
    "test_image_source_rejects_a_partial_dynamic_migration_projection",
):
    globals()[inherited] = getattr(LEGACY, inherited)


def shell(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f"source {OPERATOR}\n{body}"],
        env={
            "PATH": os.environ["PATH"],
            "SUBSTANTIVE_RELEASE_OPERATOR_SOURCE_ONLY": "1",
            "SUBSTANTIVE_RELEASE_OPERATOR_TEST_ROOT": str(tmp_path),
        },
        text=True,
        capture_output=True,
        check=False,
    )


def write_protected(path: Path, value: bytes) -> None:
    path.write_bytes(value)
    path.chmod(0o600)
    os.chown(path, 1000, 1001)


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch):
    raw = (
        b"# private placeholders, never production credentials\nOTHER=untouched\n"
        + f"CONTENT_SCORING_VERSION={V.OLD_SCORING_VERSION}\n".encode()
        + f"CONTENT_SELECTION_PRIORITY_RULE_VERSION={V.PRIORITY_RULE_VERSION}\n".encode()
        + b"SECRET_PLACEHOLDER='x=y'\n"
    )
    monkeypatch.setattr(
        V, "PRODUCTION_PRIMARY_ENV_SHA256", hashlib.sha256(raw).hexdigest()
    )
    return raw


def test_environment_derivation_changes_exactly_one_value(environment):
    candidate = V.derive_candidate_environment(environment)
    assert candidate == environment.replace(
        V.OLD_SCORING_VERSION.encode(), V.NEW_SCORING_VERSION.encode(), 1
    )
    assert (
        candidate.replace(
            V.NEW_SCORING_VERSION.encode(), V.OLD_SCORING_VERSION.encode(), 1
        )
        == environment
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "export",
        "quoted",
        "spaces",
        "priority",
        "comment",
        "crlf",
        "nul",
        "unrelated",
        "duplicate-export",
    ],
)
def test_environment_derivation_rejects_ambiguity(environment, mutation):
    key = f"CONTENT_SCORING_VERSION={V.OLD_SCORING_VERSION}".encode()
    mutations = {
        "missing": environment.replace(key, b""),
        "duplicate": environment + key + b"\n",
        "duplicate-export": environment + b" export " + key + b"\n",
        "export": environment.replace(key, b"export " + key),
        "quoted": environment.replace(
            key, b'CONTENT_SCORING_VERSION="' + V.OLD_SCORING_VERSION.encode() + b'"'
        ),
        "spaces": environment.replace(key, b" " + key),
        "priority": environment.replace(V.PRIORITY_RULE_VERSION.encode(), b"moe-only"),
        "comment": environment.replace(key, key + b" # change"),
        "crlf": environment.replace(b"\n", b"\r\n"),
        "nul": environment + b"\x00",
        "unrelated": environment.replace(b"untouched", b"changed"),
    }
    with pytest.raises(ValueError):
        V.derive_candidate_environment(mutations[mutation])


def test_atomic_install_and_restore_preserve_exact_bytes_mode_owner(
    tmp_path, environment
):
    backup, active = tmp_path / "backup", tmp_path / ".env"
    write_protected(backup, environment)
    write_protected(active, environment)
    expected = hashlib.sha256(V.derive_candidate_environment(environment)).hexdigest()
    V.activate_candidate_environment(backup, active, expected)
    assert active.read_bytes() == V.derive_candidate_environment(environment)
    assert (
        active.stat().st_mode & 0o777,
        active.stat().st_uid,
        active.stat().st_gid,
    ) == (0o600, 1000, 1001)
    V.restore_production_environment(backup, active, expected)
    assert active.read_bytes() == environment
    assert not list(tmp_path.glob(".env.substantive-release.*"))


@pytest.mark.parametrize(
    "mutation",
    ["mode", "owner", "bytes", "symlink", "parent-symlink", "backup", "candidate-hash"],
)
def test_atomic_install_rejects_preexisting_drift(tmp_path, environment, mutation):
    backup, active = tmp_path / "backup", tmp_path / ".env"
    write_protected(backup, environment)
    write_protected(active, environment)
    expected = hashlib.sha256(V.derive_candidate_environment(environment)).hexdigest()
    if mutation == "mode":
        active.chmod(0o640)
    elif mutation == "owner":
        os.chown(active, 0, 0)
    elif mutation == "bytes":
        active.write_bytes(b"changed")
    elif mutation == "symlink":
        active.unlink()
        active.symlink_to(backup)
    elif mutation == "parent-symlink":
        link = tmp_path / "linked"
        link.symlink_to(tmp_path, target_is_directory=True)
        active = link / ".env"
    elif mutation == "backup":
        backup.write_bytes(b"changed")
    elif mutation == "candidate-hash":
        expected = "0" * 64
    before = active.read_bytes()
    with pytest.raises((ValueError, OSError)):
        V.activate_candidate_environment(backup, active, expected)
    assert active.read_bytes() == before


@pytest.mark.parametrize(
    "failure", ["replace", "inplace-race", "inode-race", "chown", "fsync"]
)
def test_atomic_install_failure_does_not_publish_partial_file(
    tmp_path, environment, monkeypatch, failure
):
    backup, active = tmp_path / "backup", tmp_path / ".env"
    write_protected(backup, environment)
    write_protected(active, environment)
    expected = hashlib.sha256(V.derive_candidate_environment(environment)).hexdigest()
    if failure == "replace":
        monkeypatch.setattr(
            V.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("injected"))
        )
    elif failure == "chown":
        monkeypatch.setattr(
            V.os, "fchown", lambda *args: (_ for _ in ()).throw(OSError("injected"))
        )
    elif failure == "fsync":
        monkeypatch.setattr(
            V.os, "fsync", lambda *args: (_ for _ in ()).throw(OSError("injected"))
        )
    else:
        original = V.stable_read_regular

        def raced(path, **kwargs):
            result = original(path, **kwargs)
            if path.name.startswith(".env.substantive-release."):
                if failure == "inode-race":
                    active.rename(tmp_path / "retired-inode")
                    write_protected(active, environment)
                else:
                    active.write_bytes(environment.replace(b"untouched", b"tampered!"))
            return result

        monkeypatch.setattr(V, "stable_read_regular", raced)
    with pytest.raises((ValueError, OSError)):
        V.activate_candidate_environment(backup, active, expected)
    assert active.read_bytes() != V.derive_candidate_environment(environment)
    assert not list(tmp_path.glob(".env.substantive-release.*"))


def test_restore_refuses_unrelated_current_environment(tmp_path, environment):
    backup, active = tmp_path / "backup", tmp_path / ".env"
    write_protected(backup, environment)
    write_protected(active, b"unreviewed")
    expected = hashlib.sha256(V.derive_candidate_environment(environment)).hexdigest()
    with pytest.raises(ValueError):
        V.restore_production_environment(backup, active, expected)
    assert active.read_bytes() == b"unreviewed"


@pytest.mark.parametrize("field", list(V.EXACT_EFFECT_COUNTS))
def test_baseline_rejects_drift_of_independently_observed_counters(tmp_path, field):
    payload = baseline()
    payload["effect_counts"][field] += 1
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        V.validate_baseline(path)


@pytest.mark.parametrize(
    "field",
    [
        "frozen_copy_job_sha256",
        "primary_env_sha256",
        "release_env_sha256",
        "current_image_id",
        "current_image_reference",
    ],
)
def test_baseline_rejects_same_shape_but_different_independent_identity(
    tmp_path, field
):
    payload = baseline()
    payload[field] = str(payload[field]).replace("5", "6")
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        V.validate_baseline(path)


@pytest.mark.parametrize(
    "delta,accepted",
    [
        (timedelta(), True),
        (timedelta(minutes=59), True),
        (timedelta(hours=1, seconds=1), False),
        (timedelta(seconds=-31), False),
        (timedelta(hours=2), False),
    ],
)
def test_window_requires_fresh_capture_and_no_rollover(delta, accepted):
    if accepted:
        V.validate_release_window(V.EARLIEST_PRODUCER_UTC, baseline(), now=NOW + delta)
    else:
        with pytest.raises(ValueError):
            V.validate_release_window(
                V.EARLIEST_PRODUCER_UTC, baseline(), now=NOW + delta
            )


def test_window_enforces_actual_cutoff_not_operator_extended_timestamp():
    with pytest.raises(ValueError):
        V.validate_release_window("2099-01-01T00:00:00Z", baseline(), now=NOW)
    value = baseline()
    value["business_date"] = "2026-09-07"
    value["captured_at_utc"] = "2026-09-06T08:40:00Z"
    with pytest.raises(ValueError):
        V.validate_release_window(
            V.EARLIEST_PRODUCER_UTC, value, now=datetime(2026, 9, 6, 8, 45, tzinfo=UTC)
        )


def test_diff_allowlists_are_exact_and_builder_matches_validator(tmp_path):
    source = BUILDER.read_text()
    python = source.split("\"$stage/audit-diff.tsv\" <<'PY'\n", 1)[1].split(
        "\nPY\n", 1
    )[0]
    declarations = {}
    for node in ast.parse(python).body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"runtime", "audit_exact"}
        ):
            declarations[node.targets[0].id] = ast.literal_eval(node.value)
    assert declarations == {"runtime": V.RUNTIME_DIFF, "audit_exact": V.AUDIT_EXACT}
    path = tmp_path / "audit.tsv"
    rows = {**V.AUDIT_EXACT, V.AUDIT_TASK_PREFIX + "prd.md": "A"}
    for added in (
        "backend/tests/unit/test_unrelated.py",
        ".trellis/spec/backend/unrelated.md",
    ):
        invalid = {**rows, added: "A"}
        path.write_text(
            "".join(f"{status}\t{name}\n" for name, status in sorted(invalid.items()))
        )
        with pytest.raises(ValueError):
            V.diff_rows(path, runtime=False)


@pytest.mark.parametrize("count", [0, 1, 2])
def test_zero_new_policy_work_fence_executes_current_shell(tmp_path, count):
    counts = ":".join(["0"] * 23 + [str(count), "0", "0", "0"])
    result = shell(
        tmp_path,
        f"current_business_date() {{ echo 2026-09-06; }}\neffect_counts() {{ echo {counts}; }}\nnew_policy_work_absent",
    )
    assert (result.returncode == 0) is (count == 0)


def test_rollback_stops_and_refuses_old_source_before_any_move_when_new_work_exists(
    tmp_path,
):
    events = tmp_path / "events"
    result = shell(
        tmp_path,
        f"""
events={events}
compose() {{ echo compose-stop >> "$events"; }}
require_safe_window() {{ return 0; }}
new_policy_work_absent() {{ echo new-work >> "$events"; return 1; }}
mv() {{ echo BAD-MOVE >> "$events"; }}
restore_primary_environment_from_backup() {{ echo BAD-ENV >> "$events"; }}
restore_previous_state
""",
    )
    assert result.returncode != 0
    assert events.read_text().splitlines() == ["compose-stop", "new-work"]


@pytest.mark.parametrize("head_ok,new_work", [(True, True), (False, False)])
def test_exit_recovery_never_assumes_unchanged_schema_is_enough(
    tmp_path, head_ok, new_work
):
    events = tmp_path / "events"
    result = shell(
        tmp_path,
        f"""
events={events}
recovery_armed=1
migration_attempted=0
database_head() {{ echo {V.ALEMBIC_HEAD if head_ok else "unexpected"}; }}
compose() {{ echo stop >> "$events"; }}
require_safe_window() {{ return 0; }}
new_policy_work_absent() {{ return {1 if new_work else 0}; }}
stop_writers_for_incident() {{ echo incident-stop >> "$events"; }}
trap on_exit EXIT
exit 17
""",
    )
    assert result.returncode == 17
    assert "incident-stop" in events.read_text()


def test_operator_orders_environment_and_full_post_quiesce_fences():
    body = (
        OPERATOR.read_text().split("run_activation() {", 1)[1].split("\nmain()", 1)[0]
    )
    ordered = [
        "verify_baseline",
        "capture_environment_plan",
        "prepare_roots_and_attempt",
        "prepare_candidate_source",
        "quiesce_and_backup",
        "verify_quiesced_baseline",
        "activate_source",
        "activate_primary_environment",
        "primary_env_matches_candidate",
        "backend-migrate",
        "compose up",
        "wait_for_candidate",
        "verify_runtime_settings",
        "write_evidence",
        "completed=1",
    ]
    position = -1
    for marker in ordered:
        position = body.index(marker, position + 1)
    assert "primary_env_unchanged=true" not in OPERATOR.read_text()
    assert "--no-build --no-deps" in body


def test_capture_and_operator_query_counter_projection_remains_in_sync():
    queries = []
    for path in (CAPTURE, OPERATOR):
        body = (
            path.read_text()
            .split("effect_counts() {", 1)[1]
            .split("\nfrozen_copy_cohort()", 1)[0]
        )
        queries.append(" ".join(body.split()))
    assert queries[0] == queries[1]
    assert "material_packages" in queries[0]
    assert queries[0].count("scoring-v1-preview.12-substantive-topic-scope") == 8


def runtime_environment(scoring):
    values = {
        "CONTENT_SCORING_VERSION": scoring,
        "CONTENT_SELECTION_PRIORITY_RULE_VERSION": V.PRIORITY_RULE_VERSION,
        "BUSINESS_TIMEZONE": "Asia/Shanghai",
        "CONTENT_SLOT_MODE_ENABLED": "true",
        "CONTENT_SLOT_PREPARE_LEAD_MINUTES": "90",
        "CONTENT_SLOT_DELIVERY_LATE_MINUTES": "60",
    }
    for slot, hour in (("MORNING", "7"), ("NOON", "12"), ("EVENING", "18")):
        values[f"CONTENT_{slot}_ENABLED"] = "true"
        values[f"CONTENT_{slot}_TARGET_HOUR"] = hour
        values[f"CONTENT_{slot}_TARGET_MINUTE"] = "30"
    return [f"{key}={value}" for key, value in values.items()]


@pytest.mark.parametrize("version", [V.OLD_SCORING_VERSION, V.NEW_SCORING_VERSION])
def test_runtime_verification_accepts_only_actual_expected_schedule(version):
    V.validate_runtime_settings(
        runtime_environment(version), version, V.EARLIEST_PRODUCER_UTC, now=NOW
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "wrong-scoring",
        "earlier-prepare",
        "earlier-hour",
        "timezone",
        "disabled",
        "operator-cutoff",
        "before-noon-window",
        "active-window",
        "wrong-day",
    ],
)
def test_runtime_verification_rejects_unreviewed_producer_configuration(mutation):
    rows = runtime_environment(V.NEW_SCORING_VERSION)
    cutoff = V.EARLIEST_PRODUCER_UTC
    now = NOW
    replacements = {
        "wrong-scoring": (V.NEW_SCORING_VERSION, V.OLD_SCORING_VERSION),
        "earlier-prepare": (
            "CONTENT_SLOT_PREPARE_LEAD_MINUTES=90",
            "CONTENT_SLOT_PREPARE_LEAD_MINUTES=180",
        ),
        "earlier-hour": (
            "CONTENT_MORNING_TARGET_HOUR=7",
            "CONTENT_MORNING_TARGET_HOUR=5",
        ),
        "timezone": ("Asia/Shanghai", "UTC"),
        "disabled": ("CONTENT_MORNING_ENABLED=true", "CONTENT_MORNING_ENABLED=false"),
    }
    if mutation in replacements:
        old, new = replacements[mutation]
        rows = [row.replace(old, new) for row in rows]
    elif mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "operator-cutoff":
        cutoff = "2026-09-06T09:30:00Z"
    elif mutation == "before-noon-window":
        # At 09:55 CST the live-derived next preparation is 11:00, so the reviewed evening
        # transaction must not be usable early merely because its 17:00 cutoff is later.
        now = datetime(2026, 9, 6, 1, 55, tzinfo=UTC)
    elif mutation == "active-window":
        now = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)
    elif mutation == "wrong-day":
        now += timedelta(days=1)
    with pytest.raises(ValueError):
        V.validate_runtime_settings(rows, V.NEW_SCORING_VERSION, cutoff, now=now)


@pytest.mark.parametrize(
    "mutation",
    ["none", "minimum-week", "disabled", "reconcile", "domain-time", "domain-catchup"],
)
def test_weekly_actual_consumer_and_source_schedule_are_bound(mutation):
    rows = runtime_environment(V.NEW_SCORING_VERSION) + [
        "OFFICIAL_ACCOUNT_WEEKLY_PRODUCTION_ENABLED=true",
        "OFFICIAL_ACCOUNT_WEEKLY_SCHEDULER_ENABLED=true",
        "OFFICIAL_ACCOUNT_WEEKLY_MIN_WEEK_START=2026-09-07",
        "OFFICIAL_ACCOUNT_WEEKLY_RECONCILE_SECONDS=300",
    ]
    metadata = {
        "policy_version": "official-account-weekly-schedule-v1",
        "timezone": "Asia/Shanghai",
        "weekday": 0,
        "target_time": "09:00",
        "catchup_hours": 24,
        "unit": "one_weekly_batch_with_three_independent_articles",
    }
    if mutation == "minimum-week":
        rows = [row.replace("2026-09-07", "2026-08-31") for row in rows]
    elif mutation == "disabled":
        rows = [
            row.replace("SCHEDULER_ENABLED=true", "SCHEDULER_ENABLED=false")
            for row in rows
        ]
    elif mutation == "reconcile":
        rows = [row.replace("SECONDS=300", "SECONDS=30") for row in rows]
    elif mutation == "domain-time":
        metadata["target_time"] = "05:00"
    elif mutation == "domain-catchup":
        metadata["catchup_hours"] = 48

    def verify():
        V.validate_runtime_settings(
            rows,
            V.NEW_SCORING_VERSION,
            V.EARLIEST_PRODUCER_UTC,
            now=NOW,
            service="official-account-weekly-scheduler",
        )
        V.validate_weekly_schedule(metadata)

    if mutation == "none":
        verify()
    else:
        with pytest.raises(ValueError):
            verify()


@pytest.mark.parametrize(
    "boundary",
    [
        "success",
        "locked",
        "quiesce",
        "post-backup",
        "source",
        "environment",
        "migration",
        "start",
        "ready",
        "final-settings",
    ],
)
def test_complete_activation_path_and_failure_trap_are_executable(tmp_path, boundary):
    events = tmp_path / "events"
    result = shell(
        tmp_path,
        f"""
events={events}
boundary={boundary}
release_commit={"e" * 40}
candidate_reference=registry.example.test/app@sha256:{"c" * 64}
stage_dir=/unused
baseline_json=/unused
step() {{ echo "$1" >> "$events"; [[ "$boundary" != "$1" ]]; }}
verify_baseline() {{ step locked; }}
require_safe_window() {{ step window; }}
capture_environment_plan() {{ candidate_primary_env_sha256={"a" * 64}; step plan; }}
verify_candidate_source_compatibility() {{ step compatibility; }}
prepare_roots_and_attempt() {{
  mkdir -p "$BACKUP_ROOT/backup"; chmod 700 "$BACKUP_ROOT";
  backup_dir="$BACKUP_ROOT/backup"; step backup-identity;
}}
prepare_candidate_source() {{ step prepare-source; }}
quiesce_and_backup() {{ recovery_armed=1; step quiesce; }}
verify_quiesced_baseline() {{ step post-backup; }}
activate_source() {{ source_activated=1; step source; }}
verify_installed_source() {{ step verify-source; }}
write_candidate_release_env() {{ step release-env; }}
activate_primary_environment() {{ step environment; }}
primary_env_matches_candidate() {{ step candidate-env; }}
copy_state_matches_baseline() {{ step protected-state; }}
compose() {{
  case "$1" in run) step migration ;; up) step start ;; *) return 22 ;; esac
}}
database_head() {{ echo "$ALEMBIC_HEAD"; }}
wait_for_candidate() {{ step ready; }}
release_reference() {{ echo "$candidate_reference"; }}
verify_candidate_identity_markers() {{ step markers; }}
verify_runtime_settings() {{ step final-settings; }}
write_evidence() {{ step evidence; }}
restore_previous_state() {{ step restore; }}
stop_writers_for_incident() {{ step incident-stop; }}
run_activation
""",
    )
    observed = events.read_text().splitlines()
    assert (result.returncode == 0) is (boundary == "success")
    if boundary == "success":
        assert "restore" not in observed
        assert (
            observed.index("post-backup")
            < observed.index("environment")
            < observed.index("migration")
            < observed.index("start")
        )
        assert observed[-1] == "evidence"
    elif boundary == "locked":
        assert observed == ["locked"]
    else:
        assert "restore" in observed
        assert "evidence" not in observed
        assert "incident-stop" not in observed


@pytest.mark.parametrize("partial_first_rename", [False, True])
def test_complete_rollback_restores_files_markers_and_service_set(
    tmp_path, partial_first_rename
):
    app, backup = tmp_path / "app", tmp_path / "backup"
    (app / "backend").mkdir(parents=True)
    (backup / "source.before").mkdir(parents=True)
    (backup / "failed-candidate").mkdir()
    (backup / "activation-started").write_text("backend\n")
    if partial_first_rename:
        (app / "backend/value").write_text("old")
    else:
        (app / "backend/value").write_text("candidate")
        (backup / "source.before/backend").mkdir()
        (backup / "source.before/backend/value").write_text("old")
    payload = baseline()
    values = {
        "env.before": b"safe-env\n",
        "release.env.before": b"APP_IMAGE=old-digest\n",
        "release-commit.before": (V.PRODUCTION_COMMIT + "\n").encode(),
        "legacy-release-commit.before": V.LEGACY_PRODUCTION_COMMIT + b"\n",
    }
    for name, value in values.items():
        (backup / name).write_bytes(value)
        (backup / name).chmod(0o600)
    os.chown(backup / "legacy-release-commit.before", 1000, 1001)
    os.chown(backup / "env.before", 1000, 1001)
    payload["primary_env_sha256"] = hashlib.sha256(values["env.before"]).hexdigest()
    payload["release_env_sha256"] = hashlib.sha256(
        values["release.env.before"]
    ).hexdigest()
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(payload))
    events = tmp_path / "events"
    result = shell(
        tmp_path,
        f"""
backup_dir={backup}
baseline_json={baseline_path}
source_activated=1
events={events}
compose() {{ echo "$1:$*" >> "$events"; }}
require_safe_window() {{ return 0; }}
new_policy_work_absent() {{ echo zero-new >> "$events"; }}
copy_state_matches_baseline() {{ echo protected-state >> "$events"; }}
database_head() {{ echo "$ALEMBIC_HEAD"; }}
restore_primary_environment_from_backup() {{ cp -a "$backup_dir/env.before" "$PRIMARY_ENV"; }}
verify_current_source_baseline() {{ [[ "$(<"$APP_DIR/backend/value")" == old ]]; }}
verify_service_set() {{ [[ "$1" == {V.PRODUCTION_IMAGE_ID} && "$2" == baseline ]]; }}
verify_runtime_settings() {{ [[ "$1" == {V.OLD_SCORING_VERSION} ]]; }}
restore_previous_state
""",
    )
    assert result.returncode == 0, result.stderr
    assert (app / "backend/value").read_text() == "old"
    for name, backup_name in (
        (".env", "env.before"),
        (".release.env", "release.env.before"),
        (".release-commit", "release-commit.before"),
        ("RELEASE_COMMIT", "legacy-release-commit.before"),
    ):
        assert (app / name).read_bytes() == values[backup_name]
        assert (app / name).stat().st_mode & 0o777 == 0o600
    log = events.read_text()
    assert log.index("zero-new") < log.index("up:")
    assert log.count("protected-state") == 3
    for service in V.APP_SERVICES:
        assert service in log


@pytest.mark.parametrize("path", [OPERATOR, BUILDER, CAPTURE])
def test_shell_syntax(path):
    result = subprocess.run(["bash", "-n", str(path)], capture_output=True, check=False)
    assert result.returncode == 0


def test_operator_serializes_with_normal_production_deployer():
    assert "operator_lock=/var/lock/edu-ai-deploy.lock\n" in OPERATOR.read_text()
    assert (
        "/var/lock/edu-ai-deploy.lock"
        in (ROOT / "deploy/release/deploy.py").read_text()
    )


def test_reserved_workspace_scan_error_fails_before_attempt_or_backup(tmp_path):
    (tmp_path / "app").mkdir()
    result = shell(
        tmp_path,
        f"""
release_commit={"e" * 40}
find() {{ return 23; }}
prepare_roots_and_attempt
""",
    )
    assert result.returncode != 0
    assert "could not be scanned safely" in result.stderr
    assert not list((tmp_path / "attempts").iterdir())


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "root-symlink",
        "ancestor-symlink",
        "root-replaced",
        "root-mode",
        "workspace-symlink",
        "wrong-prefix",
    ],
)
def test_cleanup_is_bound_to_original_physical_root_and_exact_owned_child(
    tmp_path, mutation
):
    (tmp_path / "app").mkdir()
    root = tmp_path / "backups"
    root.mkdir(mode=0o700)
    child = root / ".substantive-release-tmp.abc123"
    child.mkdir(mode=0o700)
    (child / "generated").write_text("owned")
    identity = f"{root.stat().st_dev}:{root.stat().st_ino}"
    if mutation in {"root-symlink", "root-replaced"}:
        root.rename(tmp_path / "old-root")
        if mutation == "root-symlink":
            root.symlink_to(tmp_path / "old-root", target_is_directory=True)
        else:
            root.mkdir(mode=0o700)
            child.mkdir(mode=0o700)
            (child / "unowned").write_text("preserve")
    elif mutation == "ancestor-symlink":
        link = tmp_path / "ancestor"
        link.symlink_to(tmp_path, target_is_directory=True)
        # SOURCE_ONLY derives both trust roots from this linked ancestor.
        tmp_path = link
        root = tmp_path / "backups"
        child = root / child.name
    elif mutation == "root-mode":
        root.chmod(0o755)
    elif mutation == "workspace-symlink":
        child.rename(root / "saved-child")
        child.symlink_to(root / "saved-child", target_is_directory=True)
    elif mutation == "wrong-prefix":
        child.rename(root / "backup-retained")
        child = root / "backup-retained"
    result = shell(
        tmp_path,
        f"backup_root_identity={identity}\nworkspace={child}\ncleanup_workspace",
    )
    assert result.returncode == 0
    assert child.exists() is (mutation != "none")
