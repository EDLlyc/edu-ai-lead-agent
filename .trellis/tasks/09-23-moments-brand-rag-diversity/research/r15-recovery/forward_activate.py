#!/usr/bin/env python3
"""One-attempt forward activation over the already running R14 candidate.

No data recovery, replay, provider invocation, old-image rollback or social send.
All receipts stay root-owned on the production host and are never printed.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import stat
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from forward_release import OLD_IMAGE, OLD_REVISION, check, support

APP = Path("/opt/edu-ai-lead-agent")
BACKUP = Path("/opt/edu-ai-release-backups/moments-r15-20260925")
ATTEMPT = BACKUP / "forward-attempt"
OLD_REF = "offline.local/edu-ai/edu-ai-lead-agent-backend@" + OLD_IMAGE
LOCK = Path("/var/lock/edu-ai-deploy.lock")
BACKUP_LOCK = Path("/var/lock/edu-ai-backup.lock")


COHORT_SQL = """SELECT row_to_json(result)::text FROM (
WITH batch AS (
 SELECT r.id AS run_id, r.status AS run_status, r.error_code AS run_error,
  r.content_slot_selection_id AS selection_id,
  r.selected_event_id, r.selected_event_version_id,
  r.active_draft_version_id AS draft_id,
  j.id AS job_id, j.status AS job_status, j.error_code AS job_error,
  j.attempt_count AS job_attempt_count,
  j.lease_owner, j.lease_token, j.lease_expires_at,
  c.stage AS checkpoint_stage, c.issue_codes,
  old.id AS prior_run_id, old.status AS prior_status,
  (s.id IS NOT NULL AND s.business_date=r.business_date AND s.timezone=r.timezone
   AND s.selected_event_id=r.selected_event_id
   AND s.selected_event_version_id=r.selected_event_version_id) AS lineage_ok,
  (SELECT count(*) FROM copy_draft_versions d WHERE d.run_id=r.id) AS draft_count,
  (SELECT count(*) FROM copy_generation_attempts a WHERE a.job_id=j.id) AS attempt_records
 FROM copy_generation_runs r
 JOIN copy_generation_jobs j ON j.run_id=r.id
 JOIN copy_generation_checkpoints c ON c.run_id=r.id
 LEFT JOIN content_slot_selections s ON s.id=r.content_slot_selection_id
 LEFT JOIN copy_generation_runs old
  ON old.content_slot_selection_id=r.content_slot_selection_id
  AND old.id<>r.id AND old.created_at<TIMESTAMPTZ '2026-09-25 10:50:00+00'
 WHERE r.business_date=DATE '2026-09-25'
  AND r.created_at>=TIMESTAMPTZ '2026-09-25 10:50:00+00'
  AND r.created_at<TIMESTAMPTZ '2026-09-25 11:05:00+00'
  AND r.version_fingerprint='d9c80c4ce74939400dd56c02c7331d1d537d7a93c2e577a6cb7259c2a646e021'
), agg AS (
 SELECT count(*) AS total,
  count(*) FILTER (WHERE run_status='failed' AND job_status='cancelled'
   AND run_error='release_duplicate_suppressed'
   AND job_error='release_duplicate_suppressed'
   AND checkpoint_stage='failed'
   AND issue_codes='["release_duplicate_suppressed"]'::jsonb
   AND job_attempt_count=0 AND attempt_records=0 AND draft_count=0
   AND draft_id IS NULL AND lease_owner IS NULL AND lease_token IS NULL
   AND lease_expires_at IS NULL AND lineage_ok) AS suppressed_queued,
  count(*) FILTER (WHERE run_status='review_required' AND job_status='succeeded'
   AND run_error='release_duplicate_suppressed'
   AND checkpoint_stage='review_required'
   AND issue_codes='["release_duplicate_suppressed"]'::jsonb
   AND job_attempt_count=1 AND attempt_records=2 AND draft_count=1
   AND draft_id IS NOT NULL AND lease_owner IS NULL AND lease_token IS NULL
   AND lease_expires_at IS NULL AND lineage_ok) AS suppressed_draft,
  count(*) FILTER (WHERE prior_status='accepted') AS prior_accepted,
  count(*) FILTER (WHERE prior_status='failed') AS prior_failed,
  count(DISTINCT selection_id) AS distinct_selections,
  encode(sha256(convert_to(COALESCE(jsonb_agg(to_jsonb(batch) ORDER BY run_id),
   '[]'::jsonb)::text,'UTF8')),'hex') AS identity_sha256
 FROM batch
)
SELECT agg.*,
 (SELECT count(*) FROM image_artifacts i WHERE i.run_id IN
  (SELECT run_id FROM batch)) AS image_count,
 (SELECT count(*) FROM material_packages p WHERE p.run_id IN
  (SELECT run_id FROM batch)) AS package_count
FROM agg
) result"""


def cohort(host: Any, s: Any) -> dict[str, Any]:
    row = s.strict_json(host.scalar(COHORT_SQL).encode())
    s.require(
        isinstance(row, dict)
        and {
            key: row.get(key)
            for key in (
                "total",
                "suppressed_queued",
                "suppressed_draft",
                "prior_accepted",
                "prior_failed",
                "distinct_selections",
                "image_count",
                "package_count",
            )
        }
        == {
            "total": 9,
            "suppressed_queued": 8,
            "suppressed_draft": 1,
            "prior_accepted": 8,
            "prior_failed": 1,
            "distinct_selections": 9,
            "image_count": 0,
            "package_count": 0,
        }
        and isinstance(row.get("identity_sha256"), str)
        and len(row["identity_sha256"]) == 64,
        "suppressed_cohort_drift",
    )
    return cast(dict[str, Any], row)


def counters(host: Any, s: Any) -> dict[str, int]:
    row = s.strict_json(
        host.scalar(
            "SELECT json_build_object("
            "'copy_runs',(SELECT count(*) FROM copy_generation_runs),"
            "'copy_jobs',(SELECT count(*) FROM copy_generation_jobs),"
            "'drafts',(SELECT count(*) FROM copy_draft_versions),"
            "'images',(SELECT count(*) FROM image_artifacts),"
            "'packages',(SELECT count(*) FROM material_packages),"
            "'wecom_jobs',(SELECT count(*) FROM wecom_delivery_jobs),"
            "'wecom_attempts',(SELECT count(*) FROM wecom_delivery_attempts),"
            "'wechat_jobs',(SELECT count(*) FROM wechat_mp_draft_jobs)"
            ")::text"
        ).encode()
    )
    s.require(
        isinstance(row, dict) and all(type(x) is int for x in row.values()),
        "counter_shape",
    )
    return cast(dict[str, int], row)


def capture(host: Any, s: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    s.require(os.geteuid() == 0, "root_required")
    s.require(
        host.scalar("SELECT version_num FROM alembic_version") == manifest["schema"],
        "schema_drift",
    )
    s.require(
        s.read_file(APP / ".release-commit") == (OLD_REVISION + "\n").encode()
        and s.read_file(APP / "RELEASE_COMMIT") == (OLD_REVISION + "\n").encode(),
        "revision_marker_drift",
    )
    release = s.env_values(s.read_file(APP / ".release.env"))
    s.require(release.get("APP_IMAGE") == OLD_REF, "old_image_env_drift")
    old_image = host.inspect(OLD_REF, image=True)
    s.require(
        old_image["Id"] == OLD_IMAGE
        and old_image["Config"]["Labels"]["org.opencontainers.image.revision"]
        == OLD_REVISION,
        "old_image_identity",
    )
    services = {}
    for name in s.SERVICES:
        item = host.service(name)
        s.require(
            item["Image"] == OLD_IMAGE
            and item["Config"]["Image"] == OLD_REF
            and item["State"]["Status"] == "running"
            and item["State"].get("Health", {}).get("Status", "healthy") == "healthy"
            and item["RestartCount"] == 0,
            "old_service_identity",
        )
        services[name] = {
            "id": item["Id"],
            "mounts": s.normalized_mounts(item["Mounts"]),
            "env": s.sha(s.canonical(sorted(item["Config"]["Env"]))),
            "command": item["Config"]["Cmd"],
        }
    host.idle()
    cohort(host, s)
    files = {name: s.metadata(APP / name) for name in s.PROTECTED_FILES}
    for name, expected in s.PROTECTED_METADATA.items():
        s.require(
            all(files[name][key] == value for key, value in expected.items()),
            "protected_file_metadata",
        )
    s.require(
        s.run(["systemctl", "is-active", "edu-ai-backup.timer"]).strip() == b"active",
        "backup_timer",
    )
    return {
        "candidate": manifest["candidate_ref"],
        "files": files,
        "services": services,
        "db": host.db_snapshot(),
        "brand": host.brand_identity(),
        "copy_identity": host.copy_identity("edu-ai-lead-agent-content-worker-1"),
        "counters": counters(host, s),
        "cohort": cohort(host, s),
        "window": s.next_window(datetime.now(UTC)),
    }


def backup(host: Any, s: Any) -> None:
    target = BACKUP / "post-suppression.dump"
    s.require(not target.exists(), "backup_already_exists")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        s.run(
            [
                "docker",
                "exec",
                "edu-ai-lead-agent-postgres-1",
                "sh",
                "-c",
                'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc',
            ],
            output=stream,
            timeout=300,
        )
        stream.flush()
        os.fsync(stream.fileno())
    s.require(target.stat().st_size > 1024, "backup_empty")
    s.run(
        ["docker", "exec", "-i", "edu-ai-lead-agent-postgres-1", "pg_restore", "-l"],
        input_data=s.read_file(target),
        timeout=120,
    )
    s.write_new(
        BACKUP / "post-suppression-sha256.txt",
        (s.sha(s.read_file(target)) + "\n").encode(),
    )


def verify(
    host: Any, s: Any, manifest: dict[str, Any], baseline: dict[str, Any]
) -> None:
    s.require(
        s.read_file(APP / ".release-commit") == (manifest["revision"] + "\n").encode()
        and s.read_file(APP / "RELEASE_COMMIT")
        == (manifest["revision"] + "\n").encode(),
        "new_revision_marker",
    )
    expected_release = s.change_env(
        s.read_file(BACKUP / "original-release.env"),
        "APP_IMAGE",
        OLD_REF,
        manifest["candidate_ref"],
    )
    s.require(s.read_file(APP / ".release.env") == expected_release, "new_release_env")
    for name in s.PROTECTED_FILES:
        if name not in (".release.env", ".release-commit", "RELEASE_COMMIT"):
            s.require(
                s.metadata(APP / name) == baseline["files"][name],
                "protected_file_drift",
            )
    config = s.strict_json(host.compose("config", "--format", "json"))
    for name in s.SERVICES:
        item = host.service(name)
        old = baseline["services"][name]
        s.require(
            config["services"][name]["image"] == manifest["candidate_ref"]
            and item["Image"] == manifest["image"]
            and item["Config"]["Image"] == manifest["candidate_ref"]
            and item["State"]["Status"] == "running"
            and item["State"].get("Health", {}).get("Status", "healthy") == "healthy"
            and item["RestartCount"] == 0
            and s.normalized_mounts(item["Mounts"]) == old["mounts"]
            and s.sha(s.canonical(sorted(item["Config"]["Env"]))) == old["env"]
            and item["Config"]["Cmd"] == old["command"],
            "new_service_identity",
        )
    s.require(host.db_snapshot() == baseline["db"], "database_drift")
    s.require(host.brand_identity() == baseline["brand"], "brand_drift")
    s.require(
        host.copy_identity("edu-ai-lead-agent-content-worker-1")
        == baseline["copy_identity"],
        "copy_config_drift",
    )
    s.require(
        counters(host, s) == baseline["counters"]
        and cohort(host, s) == baseline["cohort"],
        "business_replay",
    )
    host.idle()
    s.require(s.next_window(datetime.now(UTC)) == baseline["window"], "schedule_drift")


def apply(
    host: Any, s: Any, manifest: dict[str, Any], baseline: dict[str, Any]
) -> None:
    s.require(capture(host, s, manifest) == baseline, "baseline_drift")
    s.require(not ATTEMPT.exists(), "attempt_exists")
    ATTEMPT.mkdir(mode=0o700, parents=False, exist_ok=False)
    s.write_new(ATTEMPT / "baseline.json", s.canonical(baseline))
    s.write_new(BACKUP / "original-release.env", s.read_file(APP / ".release.env"))
    archive = Path(manifest["_manifest_path"]).parent / "backend-image.oci.tar.gz"
    s.run(["docker", "load", "-i", str(archive)], timeout=300)
    image = host.inspect(manifest["tag"], image=True)
    by_ref = host.inspect(manifest["candidate_ref"], image=True)
    s.require(
        image["Id"] == by_ref["Id"] == manifest["image"]
        and host.app_tree(manifest["candidate_ref"]) == manifest["app_tree"],
        "loaded_candidate",
    )
    host.app_tree(manifest["candidate_ref"], probe=s.RUNTIME_PROBE)
    s.require(capture(host, s, manifest) == baseline, "post_load_drift")
    backup(host, s)
    s.require(capture(host, s, manifest) == baseline, "post_backup_drift")
    s.write_new(
        ATTEMPT / "stop-intent.json",
        s.canonical(
            {"candidate": manifest["candidate_ref"], "stop_may_be_partial": True}
        ),
    )
    completed = False
    try:
        host.compose("stop", *s.SERVICES, timeout=180)
        s.require(
            all(
                host.service(name)["State"]["Status"] == "exited" for name in s.SERVICES
            ),
            "writers_not_stopped",
        )
        s.require(
            host.db_snapshot() == baseline["db"]
            and counters(host, s) == baseline["counters"],
            "stopped_state_drift",
        )
        s.write_new(
            ATTEMPT / "activation-intent.json",
            s.canonical(
                {
                    "candidate": manifest["candidate_ref"],
                    "old_image_restart_forbidden": True,
                }
            ),
        )
        new_env = s.change_env(
            s.read_file(APP / ".release.env"),
            "APP_IMAGE",
            OLD_REF,
            manifest["candidate_ref"],
        )
        s.replace_file(APP / ".release.env", new_env, baseline["files"][".release.env"])
        for name in (".release-commit", "RELEASE_COMMIT"):
            s.replace_file(
                APP / name,
                (manifest["revision"] + "\n").encode(),
                baseline["files"][name],
            )
        host.compose(
            "up",
            "-d",
            "--no-build",
            "--no-deps",
            "--pull",
            "never",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "150",
            *s.SERVICES,
            timeout=240,
        )
        verify(host, s, manifest, baseline)
        # Observe a complete bounded scheduler/worker idle cycle, not only
        # the first instant at which Compose reports healthy containers.
        time.sleep(8)
        verify(host, s, manifest, baseline)
        s.write_new(
            ATTEMPT / "activation-receipt.json",
            s.canonical(
                {
                    "candidate": manifest["candidate_ref"],
                    "verified_at": datetime.now(UTC).isoformat(),
                    "cohort": baseline["cohort"],
                    "new_business_work": False,
                }
            ),
        )
        completed = True
    finally:
        if not completed:
            host.compose("stop", *s.SERVICES, timeout=180)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("capture", "apply"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-sha256")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    s = support(args.manifest.parent / "r14_support.py")
    manifest = check(args.manifest, args.manifest_sha256)
    s.require(
        s.sha(Path(__file__).read_bytes()) == manifest["activator_sha256"],
        "activator_hash",
    )
    manifest["_manifest_path"] = str(args.manifest)
    host = s.Host()
    if args.action == "capture":
        if not args.baseline:
            parser.error("capture requires baseline path")
        state = capture(host, s, manifest)
        s.write_new(args.baseline, s.canonical(state))
        print(
            json.dumps(
                {
                    "phase": "capture",
                    "sha256": s.sha(s.canonical(state)),
                    "services": len(state["services"]),
                    "cohort": state["cohort"],
                }
            )
        )
        return 0
    if not (
        args.apply and args.baseline and args.baseline_sha256 and os.geteuid() == 0
    ):
        parser.error("apply requires root, --apply and hash-bound baseline")
    baseline = s.bound_json(args.baseline, args.baseline_sha256)
    deploy_fd = os.open(LOCK, os.O_RDWR | os.O_NOFOLLOW)
    backup_fd = os.open(BACKUP_LOCK, os.O_RDWR | os.O_NOFOLLOW)
    with (
        os.fdopen(deploy_fd, "r+b") as deploy_lock,
        os.fdopen(backup_fd, "r+b") as backup_lock,
    ):
        for handle in (deploy_lock, backup_lock):
            info = os.fstat(handle.fileno())
            s.require(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == 0
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_nlink == 1,
                "lock_identity",
            )
        fcntl.flock(deploy_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(backup_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        apply(host, s, manifest, baseline)
    print(
        json.dumps(
            {
                "phase": "applied",
                "revision": manifest["revision"],
                "services": len(s.SERVICES),
                "new_business_work": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
