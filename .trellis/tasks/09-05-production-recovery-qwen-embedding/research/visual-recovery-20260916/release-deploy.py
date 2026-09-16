#!/usr/bin/env python3
"""Exact-base V3 release with one additive migration and fail-forward recovery."""

from __future__ import annotations

import argparse
import copy
import fcntl
import importlib.util
import json
import os
import re
import signal
import stat
import subprocess
from datetime import datetime
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "visual_release_common", Path(__file__).with_name("release-common.py")
)
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)
D = C.archived("deploy")
S = C.source_module("snapshot")
D.PREVIOUS_REVISION = D.PREVIOUS_LEGACY_REVISION = C.PREVIOUS_REVISION
D.PREVIOUS_ID, D.PREVIOUS_REF = C.BASE_MANIFEST, C.BASE_REF
D.BASE_ARCHIVE_SHA256 = C.BASE_ARCHIVE_SHA256
OA_WRITERS = (
    "official-account-weekly-scheduler",
    "official-account-weekly-dag-worker",
    "official-account-local-worker",
    "wechat-official-account-draft-worker",
)


def patch_visual_policy(body: bytes, target: str) -> bytes:
    C.require(
        target in {C.PREVIOUS_VISUAL_POLICY, C.TARGET_VISUAL_POLICY}
        and b"\r" not in body
        and len(body) <= 2 * 1024 * 1024,
        "visual_policy_patch_input",
    )
    lines = body.splitlines(keepends=True)
    visual_prefix = (C.VISUAL_POLICY_KEY + "=").encode()
    attempts_prefix = b"IMAGE_MAX_ATTEMPTS="
    visual = [
        index for index, line in enumerate(lines) if line.startswith(visual_prefix)
    ]
    attempts = [line for line in lines if line.startswith(attempts_prefix)]
    C.require(
        len(visual) == 1
        and len(attempts) == 1
        and attempts[0].removesuffix(b"\n")
        == attempts_prefix + C.IMAGE_MAX_ATTEMPTS.encode(),
        "protected_image_attempts_changed",
    )
    index = visual[0]
    original = lines[index].removesuffix(b"\n")
    C.require(
        original
        in {
            visual_prefix + C.PREVIOUS_VISUAL_POLICY.encode(),
            visual_prefix + C.TARGET_VISUAL_POLICY.encode(),
        },
        "visual_policy_source_changed",
    )
    newline = b"\n" if lines[index].endswith(b"\n") else b""
    lines[index] = visual_prefix + target.encode() + newline
    patched = b"".join(lines)
    C.require(
        len(patched.splitlines()) == len(body.splitlines())
        and patch_visual_policy_fields(patched)
        == {
            C.VISUAL_POLICY_KEY: target,
            "IMAGE_MAX_ATTEMPTS": C.IMAGE_MAX_ATTEMPTS,
        },
        "visual_policy_patch_changed_other_fields",
    )
    return patched


def patch_visual_policy_fields(body: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in body.splitlines():
        for key in (C.VISUAL_POLICY_KEY, "IMAGE_MAX_ATTEMPTS"):
            prefix = (key + "=").encode()
            if raw.startswith(prefix):
                C.require(key not in result, "protected_config_duplicate")
                result[key] = raw[len(prefix) :].decode("utf-8")
    return result


def validate_owners(rows: object, snapshot: dict) -> str:
    C.require(
        isinstance(rows, list)
        and len(rows) == snapshot["history"]["owners"]["count"] == 15,
        "owner_count",
    )
    target = [
        row for row in rows if isinstance(row, dict) and row.get("owner") == C.EDITION
    ]
    C.require(len(target) == 1, "target_owner_count")
    row = target[0]
    C.require(
        row.get("key_kind") == "event"
        and row.get("key_value") == C.EVENT
        and row.get("account_fingerprint") == D.SINGLE_ACCOUNT
        and row.get("status") == "outcome_unknown"
        and isinstance(row.get("provenance_fingerprint"), str)
        and re.fullmatch(r"[0-9a-f]{64}", row["provenance_fingerprint"]) is not None,
        "target_owner",
    )
    try:
        created, updated = (
            datetime.fromisoformat(row[k]) for k in ("created_at", "updated_at")
        )
        C.require(
            created.utcoffset() is not None
            and updated.utcoffset() is not None
            and updated >= created,
            "owner_timestamp",
        )
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("owner_timestamp") from None
    D.validate_owner_rows([item for item in rows if item is not row])
    return C.digest(
        C.canonical(
            [{k: v for k, v in item.items() if k != "updated_at"} for item in rows]
        )
    )


class Deployment(D.Deployment):
    def __init__(self, manifest_path: Path, manifest: dict):
        super().__init__(manifest_path, manifest)
        self.backup_dir = D.BACKUP_ROOT / (
            "visual-recovery-" + manifest["revision"][:12]
        )
        self.snapshot = S.validate_snapshot(manifest["production_snapshot"])
        D.FILES = C.validate_files(manifest["app_files"])
        self.expected_schema = C.PREVIOUS_SCHEMA
        self.expected_visual_policy = C.PREVIOUS_VISUAL_POLICY
        self.migration_attempted = False
        self.runtime_snapshot: dict | None = None
        self.database_backup_sha256: str | None = None

    def expected_primary_env(self) -> bytes:
        C.require(self.primary_env is not None, "missing_environment_backup")
        assert self.primary_env is not None
        return patch_visual_policy(self.primary_env[0], self.expected_visual_policy)

    def expected_snapshot(self) -> dict:
        value = copy.deepcopy(self.snapshot)
        value["database"] = {
            "schema_head": self.expected_schema,
            "body_checksum_index": (
                C.BODY_CHECKSUM_INDEX_BASELINE
                if self.expected_schema == C.PREVIOUS_SCHEMA
                else None
            ),
        }
        value["runtime_files"][".env"]["sha256"] = C.digest(self.expected_primary_env())
        return value

    def log(self, phase: str) -> None:
        print("visual_recovery_deploy phase=" + phase, flush=True)

    def scalar(self, query: str) -> str:
        # Every SQL statement in this deployment is SELECT. Database writes are
        # explicitly prohibited even if a later operator change introduces one.
        C.require(
            query.lstrip().upper().startswith("SELECT ") and ";" not in query,
            "readonly_query",
        )
        return self.compose(
            "exec",
            "-T",
            "postgres",
            "sh",
            "-c",
            'export PGOPTIONS="-c default_transaction_read_only=on"; exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"',
            "sh",
            query,
        ).strip()

    def idle(
        self, *, minimum_wecom_lead_seconds: int = D.MIN_WECOM_QUIESCE_LEAD_SECONDS
    ) -> None:
        C.require(
            self.scalar(D.BUSINESS_DATE_QUERY) == C.BUSINESS_DATE,
            "recovery_business_date_changed",
        )
        snapshot_before = S.validate_snapshot(
            json.loads(self.scalar(S.snapshot_query())),
            database_only=True,
            expected_schema=self.expected_schema,
        )
        snapshot_before["runtime_files"] = S.runtime_files(D.APP)
        historical_before = D.validate_historical_cohort(
            json.loads(self.scalar(D.HISTORICAL_COHORT_QUERY)), C.BUSINESS_DATE
        )
        wecom_before = D.validate_future_wecom_jobs(
            json.loads(self.scalar(D.WECOM_ACTIVE_QUERY)),
            minimum_lead_seconds=minimum_wecom_lead_seconds,
        )
        count = self.scalar(D.IDLE_QUERY)
        historical_after = D.validate_historical_cohort(
            json.loads(self.scalar(D.HISTORICAL_COHORT_QUERY)), C.BUSINESS_DATE
        )
        wecom_after = D.validate_future_wecom_jobs(
            json.loads(self.scalar(D.WECOM_ACTIVE_QUERY)),
            minimum_lead_seconds=minimum_wecom_lead_seconds,
        )
        owner_before = validate_owners(
            json.loads(self.scalar(D.OWNER_QUERY)), self.snapshot
        )
        owner_after = validate_owners(
            json.loads(self.scalar(D.OWNER_QUERY)), self.snapshot
        )
        snapshot_after = S.validate_snapshot(
            json.loads(self.scalar(S.snapshot_query())),
            database_only=True,
            expected_schema=self.expected_schema,
        )
        snapshot_after["runtime_files"] = S.runtime_files(D.APP)
        expected = self.expected_snapshot()
        if self.owner_sha256 is None:
            self.owner_sha256 = owner_before
        if self.future_wecom_count is None:
            self.future_wecom_count, self.future_wecom_sha256 = wecom_before
        C.require(
            snapshot_before == snapshot_after == expected,
            "protected_history_changed",
        )
        C.require(
            historical_before == historical_after
            and count == str(len(historical_before) + wecom_before[0])
            and wecom_before
            == wecom_after
            == (self.future_wecom_count, self.future_wecom_sha256)
            and owner_before == owner_after == self.owner_sha256,
            "queue_or_owner_not_idle",
        )

    def config(self, reference: str) -> dict:
        value = json.loads(self.compose("config", "--format", "json", image=reference))
        C.require(
            isinstance(value, dict)
            and isinstance(value.get("services"), dict)
            and all(
                value["services"][name]["image"] == reference for name in D.SERVICES
            ),
            "compose_image",
        )
        policy_consumers = 0
        attempt_consumers = 0
        for service in value["services"].values():
            environment = service.get("environment", {})
            if C.VISUAL_POLICY_KEY in environment:
                policy_consumers += 1
                C.require(
                    str(environment[C.VISUAL_POLICY_KEY])
                    == self.expected_visual_policy,
                    "visual_policy_config_changed",
                )
            if "IMAGE_MAX_ATTEMPTS" in environment:
                attempt_consumers += 1
                C.require(
                    str(environment["IMAGE_MAX_ATTEMPTS"]) == C.IMAGE_MAX_ATTEMPTS,
                    "image_max_attempts_changed",
                )
        C.require(
            policy_consumers >= 1 and attempt_consumers >= 1, "visual_config_not_wired"
        )
        if self.base_config is not None and reference != C.BASE_REF:
            normalized = copy.deepcopy(value)
            normalized = D.replace_json_value(normalized, reference, C.BASE_REF)
            for service in normalized["services"].values():
                environment = service.get("environment", {})
                if C.VISUAL_POLICY_KEY in environment:
                    environment[C.VISUAL_POLICY_KEY] = C.PREVIOUS_VISUAL_POLICY
            C.require(normalized == self.base_config, "compose_non_release_changed")
        return value

    def verify(
        self,
        reference: str,
        image_id: str,
        *,
        minimum_wecom_lead_seconds: int = D.MIN_WECOM_READY_LEAD_SECONDS,
    ) -> None:
        # Same health/image/config gates as the archived operator, but there is
        # already one terminal edition. No future-min-date/zero-edition gate.
        for name in D.SERVICES:
            item = self.service(name)
            C.require(
                item["Config"]["Image"] == reference and item["Image"] == image_id,
                "service_image",
            )
            C.require(
                item["State"]["Status"] == "running" and item["RestartCount"] == 0,
                "service_state",
            )
            C.require(
                item["State"].get("Health", {}).get("Status", "healthy") == "healthy",
                "service_health",
            )
        for name, identity in self.dependencies.items():
            item = self.service(name)
            C.require(
                item["Id"] == identity
                and item["State"]["Status"] == "running"
                and item["RestartCount"] == 0
                and item["State"].get("Health", {}).get("Status") == "healthy",
                "dependency_changed",
            )
        C.require(
            self.scalar("SELECT version_num FROM alembic_version")
            == self.expected_schema,
            "schema_changed",
        )
        health = json.loads(
            self.command(
                [
                    "curl",
                    "--fail",
                    "--silent",
                    "--max-time",
                    "5",
                    "--max-filesize",
                    "65536",
                    "http://127.0.0.1:8000/healthz",
                ]
            )
        )
        C.require(
            health.get("status") == "ok" and health.get("environment") == "production",
            "api_health",
        )
        self.verify_config_metadata()
        self.config(reference)
        for filename, (original, details) in self.before.items():
            expected = (
                D.replace_image(original, reference)
                if filename == ".release.env"
                else original
                if reference == C.BASE_REF
                else (self.manifest["revision"] + "\n").encode()
            )
            path = D.APP / filename
            C.require(D.safe_file(path) == expected, "active_marker_changed")
            current = path.stat()
            C.require(
                (current.st_uid, current.st_gid, stat.S_IMODE(current.st_mode))
                == (details.st_uid, details.st_gid, stat.S_IMODE(details.st_mode)),
                "marker_metadata_changed",
            )
        self.idle(minimum_wecom_lead_seconds=minimum_wecom_lead_seconds)

    def verify_config_metadata(self) -> None:
        C.require(
            self.primary_env is not None and self.compose_snapshot is not None,
            "missing_environment_backup",
        )
        for filename, (body, details) in (
            (".env", self.primary_env),
            ("compose.yaml", self.compose_snapshot),
        ):
            path = D.APP / filename
            current = path.stat()
            C.require(
                D.safe_file(path)
                == (self.expected_primary_env() if filename == ".env" else body)
                and (current.st_uid, current.st_gid, stat.S_IMODE(current.st_mode))
                == (details.st_uid, details.st_gid, stat.S_IMODE(details.st_mode)),
                "protected_config_changed",
            )

    def current_index(self) -> object:
        return json.loads(
            self.scalar(
                "SELECT COALESCE(" + S.INDEX_SNAPSHOT_QUERY + ",'null'::jsonb)::text"
            )
        )

    def verify_database_baseline(self) -> None:
        C.require(
            self.scalar("SELECT version_num FROM alembic_version")
            == self.expected_schema,
            "schema_changed",
        )
        expected_index = (
            C.BODY_CHECKSUM_INDEX_BASELINE
            if self.expected_schema == C.PREVIOUS_SCHEMA
            else None
        )
        C.require(self.current_index() == expected_index, "body_checksum_index_changed")

    def preflight(self) -> None:
        super().preflight()
        C.require(
            self.manifest["previous_schema"] == C.PREVIOUS_SCHEMA
            and self.manifest["target_schema"] == C.TARGET_SCHEMA,
            "release_schema_changed",
        )
        C.require(
            patch_visual_policy_fields(self.primary_env[0] if self.primary_env else b"")
            == {
                C.VISUAL_POLICY_KEY: C.PREVIOUS_VISUAL_POLICY,
                "IMAGE_MAX_ATTEMPTS": C.IMAGE_MAX_ATTEMPTS,
            },
            "protected_visual_config_changed",
        )
        self.verify_database_baseline()
        self.runtime_snapshot = {
            "version": "visual-resilient-runtime-before-v1",
            "base_revision": C.PREVIOUS_REVISION,
            "base_ref": C.BASE_REF,
            "base_image_id": C.BASE_MANIFEST,
            "schema_head": C.PREVIOUS_SCHEMA,
            "body_checksum_index": C.BODY_CHECKSUM_INDEX_BASELINE,
            "service_ids": {name: self.service(name)["Id"] for name in D.SERVICES},
            "dependency_ids": self.dependencies,
            "runtime_files": self.snapshot["runtime_files"],
        }

    def validate_archive(self) -> dict:
        for filename, checksum in self.manifest["helpers"].items():
            C.require(
                D.file_hash(self.manifest_path.parent / filename) == checksum,
                "helper_changed",
            )
        archive = self.manifest_path.parent / self.manifest["archive"]
        C.require(
            D.file_hash(archive) == self.manifest["archive_sha256"], "archive_hash"
        )
        result = C.source_module("validate").validate(
            archive,
            candidate_tag=self.manifest["candidate_tag"],
            candidate_ref=self.manifest["candidate_ref"],
            revision=self.manifest["revision"],
            app_files=self.manifest["app_files"],
            migration_files=self.manifest["migration_files"],
        )
        C.require(
            result["manifest_digest"] == self.manifest["candidate_image_id"],
            "archive_identity",
        )
        C.require(
            D.file_hash(archive) == self.manifest["archive_sha256"], "archive_changed"
        )
        return result

    def smoke(self, reference: str, current: bool) -> dict:
        result = super().smoke(reference, current)
        # Load all overlay modules in the same network-disabled, unconfigured
        # container as the preserved no-source-links/banner smoke.
        if current:
            smoke = """
import hashlib,importlib,json,sys
payload=json.loads(sys.argv[1])
for relative in payload['app_files']:
    importlib.import_module('app.' + relative.removesuffix('.py').replace('/','.'))
for relative,checksum in payload['migration_files'].items():
    body=open('/app/'+relative,'rb').read()
    assert hashlib.sha256(body).hexdigest() == checksum
from app.core.errors import ImageGenerationFailure
v=ImageGenerationFailure(error_code='provider_unavailable',disposition='not_applied_retryable',reason='connect_failed')
assert ImageGenerationFailure.from_safe_metadata(v.safe_metadata()['image_failure']) == v
print('visual_recovery_imports_ok')
"""
            value = self.command(
                [
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
                    "--security-opt",
                    "no-new-privileges",
                    "--entrypoint",
                    "python",
                    reference,
                    "-B",
                    "-c",
                    smoke,
                    json.dumps(
                        {
                            "app_files": self.manifest["app_files"],
                            "migration_files": self.manifest["migration_files"],
                        }
                    ),
                ],
                timeout=60,
            )
            C.require(value.strip() == "visual_recovery_imports_ok", "recovery_smoke")
        return result

    def backup(self) -> None:
        super().backup()
        C.require(self.runtime_snapshot is not None, "missing_runtime_snapshot")
        C.archived("build").write_mode_600(
            self.backup_dir / "protected-history.json", C.canonical(self.snapshot)
        )
        C.archived("build").write_mode_600(
            self.backup_dir / "runtime-before.json", C.canonical(self.runtime_snapshot)
        )
        self.database_backup_sha256 = self.database_backup()
        C.archived("build").write_mode_600(
            self.backup_dir / "postgres-before-0048.sha256",
            (self.database_backup_sha256 + "  postgres-before-0048.dump\n").encode(),
        )
        directory = os.open(
            self.backup_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def compose_argv(self, *args: str) -> list[str]:
        command = [
            "docker",
            "compose",
            "--project-name",
            "edu-ai-lead-agent",
            "-f",
            str(D.APP / "compose.yaml"),
            "--env-file",
            str(D.APP / ".env"),
            "--env-file",
            str(D.APP / ".release.env"),
        ]
        for profile in D.PROFILES:
            command.extend(("--profile", profile))
        return [*command, *args]

    def database_backup(self) -> str:
        path = self.backup_dir / "postgres-before-0048.dump"
        environment = {
            key: value
            for key, value in os.environ.items()
            if key != "APP_IMAGE" and not key.startswith("COMPOSE_")
        }
        with path.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            result = subprocess.run(
                self.compose_argv(
                    "exec",
                    "-T",
                    "postgres",
                    "sh",
                    "-c",
                    'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
                    "--format=custom --no-owner --no-privileges",
                ),
                cwd=D.APP,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.PIPE,
                timeout=900,
                check=False,
            )
            stream.flush()
            os.fsync(stream.fileno())
        C.require(
            result.returncode == 0 and path.stat().st_size > 0,
            "postgres_backup_failed",
        )
        validations = (
            (("pg_restore", "--list"), True),
            (("pg_restore", "--file=/dev/null"), False),
        )
        for restore_args, requires_output in validations:
            with path.open("rb") as stream:
                checked = subprocess.run(
                    self.compose_argv("exec", "-T", "postgres", *restore_args),
                    cwd=D.APP,
                    env=environment,
                    stdin=stream,
                    capture_output=True,
                    timeout=300,
                    check=False,
                )
            C.require(
                checked.returncode == 0
                and (not requires_output or bool(checked.stdout.strip())),
                "postgres_backup_invalid",
            )
        return D.file_hash(path)

    def post_quiescence_fence(self) -> None:
        for filename, (body, _details) in self.before.items():
            C.require(D.safe_file(D.APP / filename) == body, "post_stop_marker_drift")
        self.verify_config_metadata()
        self.verify_database_baseline()
        self.idle(minimum_wecom_lead_seconds=D.MIN_WECOM_QUIESCE_LEAD_SECONDS)

    def migrate(self) -> None:
        self.migration_attempted = True
        self.compose(
            "run",
            "--rm",
            "--no-deps",
            "backend-migrate",
            "alembic",
            "-c",
            "alembic.ini",
            "upgrade",
            C.TARGET_SCHEMA,
            timeout=300,
            image=self.manifest["candidate_ref"],
        )
        self.expected_schema = C.TARGET_SCHEMA
        self.verify_database_baseline()

    def activate(self) -> None:
        self.expected_visual_policy = C.TARGET_VISUAL_POLICY
        super().activate()
        C.require(self.primary_env is not None, "missing_environment_backup")
        assert self.primary_env is not None
        D.atomic_restore(
            D.APP / ".env",
            patch_visual_policy(self.primary_env[0], C.TARGET_VISUAL_POLICY),
            self.primary_env[1],
        )

    def activate_candidate_v2(self) -> None:
        self.expected_visual_policy = C.PREVIOUS_VISUAL_POLICY
        super().activate()
        C.require(self.primary_env is not None, "missing_environment_backup")
        assert self.primary_env is not None
        D.atomic_restore(D.APP / ".env", self.primary_env[0], self.primary_env[1])

    def rollback_before_migration(self) -> None:
        self.log("rollback_before_migration_started")
        failures: list[str] = []
        try:
            self.stop()
        except BaseException:  # noqa: BLE001 -- finish exact prior-state recovery
            failures.append("stop")
        for filename, (body, details) in self.before.items():
            try:
                D.atomic_restore(D.APP / filename, body, details)
            except BaseException:  # noqa: BLE001 -- continue recovery sequence
                failures.append("marker_restore")
        if self.primary_env is not None:
            try:
                D.atomic_restore(D.APP / ".env", *self.primary_env)
            except BaseException:  # noqa: BLE001 -- continue recovery sequence
                failures.append("config_restore")
        self.expected_schema = C.PREVIOUS_SCHEMA
        self.expected_visual_policy = C.PREVIOUS_VISUAL_POLICY
        try:
            self.start(C.BASE_REF)
            self.wait_ready(C.BASE_REF, C.BASE_MANIFEST, minimum_wecom_lead_seconds=0)
        except BaseException:  # noqa: BLE001 -- fail closed after rollback failure
            failures.append("restart")
            try:
                self.stop()
            except BaseException:  # noqa: BLE001 -- preserve original failure
                failures.append("incident_stop")
        C.require(not failures, "rollback_incomplete")
        self.log("rollback_before_migration_completed")

    def stop_official_account_writers(self) -> None:
        self.compose("stop", "-t", "30", *OA_WRITERS, timeout=120)

    def recover_forward(self) -> None:
        self.log("forward_recovery_started")
        try:
            self.stop()
            self.activate_candidate_v2()
            schema = self.scalar("SELECT version_num FROM alembic_version")
            if schema == C.PREVIOUS_SCHEMA:
                self.migrate()
            else:
                C.require(schema == C.TARGET_SCHEMA, "forward_schema_unknown")
                self.expected_schema = C.TARGET_SCHEMA
                self.verify_database_baseline()
            self.start(self.manifest["candidate_ref"])
            self.wait_ready(
                self.manifest["candidate_ref"],
                self.manifest["candidate_image_id"],
                minimum_wecom_lead_seconds=0,
            )
            C.archived("build").write_mode_600(
                self.backup_dir / "forward-recovery.json",
                C.canonical(
                    {
                        "status": "recovered_forward",
                        "schema_head": C.TARGET_SCHEMA,
                        "visual_pipeline_version": C.PREVIOUS_VISUAL_POLICY,
                        "official_account_writers_stopped": False,
                        "model_calls": 0,
                        "social_calls": 0,
                    }
                ),
            )
        except BaseException:  # noqa: BLE001 -- never downgrade after a migration attempt
            writer_stop_failed = False
            try:
                self.stop_official_account_writers()
            except BaseException:  # noqa: BLE001 -- report the fail-closed incident
                writer_stop_failed = True
            raise RuntimeError(
                "forward_recovery_writers_not_stopped"
                if writer_stop_failed
                else "forward_recovery_incomplete"
            ) from None
        self.log("forward_recovery_completed")

    def success_receipt(self) -> None:
        C.require(
            self.expected_schema == C.TARGET_SCHEMA
            and self.expected_visual_policy == C.TARGET_VISUAL_POLICY
            and isinstance(self.database_backup_sha256, str),
            "release_not_fully_activated",
        )
        self.idle(minimum_wecom_lead_seconds=D.MIN_WECOM_READY_LEAD_SECONDS)
        value = {
            "status": "deployed",
            "revision": self.manifest["revision"],
            "previous_revision": C.PREVIOUS_REVISION,
            "image_reference": self.manifest["candidate_ref"],
            "image_id": self.manifest["candidate_image_id"],
            "archive_sha256": self.manifest["archive_sha256"],
            "app_files": self.manifest["app_files"],
            "migration_files": self.manifest["migration_files"],
            "previous_schema_head": C.PREVIOUS_SCHEMA,
            "schema_head": C.TARGET_SCHEMA,
            "removed_index": C.BODY_CHECKSUM_INDEX,
            "application_service_count": len(D.SERVICES),
            "model_calls": 0,
            "social_calls": 0,
            "migration_executed": True,
            "postgres_backup_sha256": self.database_backup_sha256,
            "visual_pipeline_version": C.TARGET_VISUAL_POLICY,
            "image_max_attempts": C.IMAGE_MAX_ATTEMPTS,
            "compensation_authorized": False,
            "compensation_executed": False,
            "preserved_historical_copy_jobs": 7,
            "historical_cohort_sha256": D.HISTORICAL_COHORT_SHA256,
            "protected_history_sha256": C.digest(C.canonical(self.snapshot)),
            "single_editions": 1,
            "target_edition": C.EDITION,
            "target_state": "outcome_unknown",
            "draft_owner_rows": 15,
            "draft_owner_sha256": self.owner_sha256,
            "future_nonclaimable_wecom_jobs": self.future_wecom_count,
            "future_nonclaimable_wecom_sha256": self.future_wecom_sha256,
            "standard_release_provenance": "incomplete",
        }
        C.archived("build").write_mode_600(
            self.backup_dir / "result.json", C.canonical(value)
        )


def execute(operation: Deployment) -> None:
    operation.log("validate_archive_before_preflight")
    operation.validate_archive()
    operation.log("preflight")
    operation.preflight()
    operation.fence()
    quiesce_attempted = False
    try:
        operation.log("quiesce")
        quiesce_attempted = True
        operation.stop()
        operation.post_quiescence_fence()
        operation.log("backup_before_migration")
        operation.backup()
        operation.verify_database_baseline()
        operation.log("load_and_smoke_candidate")
        operation.load_candidate()
        operation.log("post_load_quiescence_fence")
        operation.post_quiescence_fence()
        operation.log("migrate_to_0048")
        operation.migrate()
        operation.log("activate_v3")
        operation.activate()
        operation.log("start_candidate")
        operation.start(operation.manifest["candidate_ref"])
        operation.wait_ready(
            operation.manifest["candidate_ref"],
            operation.manifest["candidate_image_id"],
        )
        operation.success_receipt()
        operation.log("completed")
    except BaseException:
        if quiesce_attempted:
            if operation.migration_attempted:
                operation.recover_forward()
                raise RuntimeError("deployment_failed_forward_recovered") from None
            operation.rollback_before_migration()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        C.require(os.geteuid() == 0, "root_required")
        path = args.manifest.absolute()
        value = C.manifest(path, args.manifest_sha256)
        C.require(path.parent == C.ROOT, "operator_bundle_directory")
        operation = Deployment(path, value)
        if not args.execute:
            operation.validate_archive()
            operation.log("manifest_validated_no_execution")
            return 0
        fd = os.open(
            D.LOCK, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
        )
        with os.fdopen(fd, "w") as lock:
            info = os.fstat(lock.fileno())
            C.require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_uid == info.st_gid == 0
                and stat.S_IMODE(info.st_mode) == 0o600,
                "unsafe_deployment_lock",
            )
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

            def interrupted(_signal: int, _frame: object) -> None:
                raise RuntimeError("deployment_interrupted")

            signal.signal(signal.SIGTERM, interrupted)
            execute(operation)
    except BaseException as exc:  # noqa: BLE001 -- sanitize cancellation/rollback diagnostics
        code = (
            str(exc)
            if type(exc) is RuntimeError and re.fullmatch(r"[a-z_]+", str(exc))
            else "operation_failed"
        )
        print("visual_recovery_deploy phase=failed code=" + code, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
