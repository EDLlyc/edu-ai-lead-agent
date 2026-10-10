"""Four-service cutover only. Root swaps frontend after two postcheck observations.

Run: python3 cutover.py
Recovery after later postcheck failure: python3 cutover.py --recover BACKUP_PATH
Never restore the database or rewrite draft journals during recovery.
"""

import argparse
import json
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

from common import (
    BASE,
    COMPOSE,
    DRAFT,
    MODELS,
    PG,
    ROOT,
    STAGE,
    TARGETS,
    atomic_text,
    config_hashes,
    content_manifest,
    db_state,
    digest,
    idle,
    inspect,
    mode_check,
    name,
    now,
    patch_compose,
    patch_release,
    preserved,
    quiet_window,
    render,
    require,
    rollback_draft_safe,
    run,
    safe_container,
    save,
    sha,
    verify_render_patch,
    verify_target_recreation,
)


def verify_archive(path, expected):
    """Read every regular tar member without extraction; compare content and metadata."""
    import hashlib

    result = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            relative = member.name.removeprefix("./")
            require(
                not Path(relative).is_absolute() and ".." not in Path(relative).parts,
                "unsafe_tar_path",
            )
            if member.isdir():
                continue
            require(
                member.isfile() and relative not in result, "unsupported_tar_member"
            )
            stream = archive.extractfile(member)
            require(stream is not None, "unreadable_tar_member")
            h = hashlib.sha256()
            for chunk in iter(lambda stream=stream: stream.read(1024 * 1024), b""):
                h.update(chunk)
            result[relative] = {
                "sha256": h.hexdigest(),
                "bytes": member.size,
                "mode": member.mode & 0o777,
                "uid": member.uid,
                "gid": member.gid,
            }
    require(result == expected, "archive_manifest_mismatch")
    return {
        "sha256": sha(path),
        "bytes": path.stat().st_size,
        "files": len(result),
        "contents_digest": digest(result),
    }


def backup_database(backup):
    dump = backup / "database.dump"
    with dump.open("wb") as output:
        result = subprocess.run(
            [
                "docker",
                "exec",
                PG,
                "sh",
                "-c",
                'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc',
            ],
            stdout=output,
            stderr=subprocess.PIPE,
            timeout=300,
            check=False,
        )
    dump.chmod(0o600)
    require(
        result.returncode == 0 and dump.stat().st_size > 1000, "database_backup_failed"
    )
    with dump.open("rb") as source:
        result = subprocess.run(
            ["docker", "exec", "-i", PG, "pg_restore", "--list"],
            stdin=source,
            capture_output=True,
            timeout=90,
            check=False,
        )
    require(
        result.returncode == 0 and b"TABLE DATA" in result.stdout,
        "database_restore_listing_failed",
    )
    for table in [
        "official_account_single_editions",
        "model_api_keys",
        "official_account_article_runs",
    ]:
        require(table.encode() in result.stdout, "database_backup_table_missing")
    (backup / "database.list").write_bytes(result.stdout)
    (backup / "database.list").chmod(0o600)
    return {
        "sha256": sha(dump),
        "bytes": dump.stat().st_size,
        "restore_listing_verified": True,
    }


def backups(backup, preflight, frozen):
    database = backup_database(backup)
    archives = {}
    for key, volume in preflight["volumes"].items():
        before = content_manifest(volume["source"])
        require(before == volume["files"], "volume_changed_before_backup")
        archive = backup / (key + ".tar.gz")
        run(
            [
                "tar",
                "--numeric-owner",
                "-czf",
                str(archive),
                "-C",
                volume["source"],
                ".",
            ],
            timeout=300,
        )
        archive.chmod(0o600)
        archives[key] = verify_archive(archive, before)
        require(
            content_manifest(volume["source"]) == before, "volume_changed_during_backup"
        )
    preserved(frozen, db_state())
    result = {"database": database, "volumes": archives, "frozen_state": frozen}
    save(backup / "backup-verification.json", result)
    return result


def graceful_stop(services):
    # -1 never escalates to SIGKILL. Admission is repeated immediately before this.
    # If shutdown stalls, command timeout raises and recovery fails closed; no force kill.
    run(COMPOSE + ["stop", "--timeout", "-1", *services], timeout=240)
    require(
        all(
            not item["State"]["Running"]
            for item in inspect([name(s) for s in services]).values()
        ),
        "service_did_not_stop",
    )


def start(services):
    run(
        COMPOSE + ["up", "-d", "--no-deps", "--no-build", "--pull", "never", *services],
        timeout=240,
    )


def running(services, image):
    for _ in range(20):
        values = inspect([name(s) for s in services])
        if all(
            item["State"]["Running"]
            and item["RestartCount"] == 0
            and item["Image"] == image
            for item in values.values()
        ):
            return values
        time.sleep(2)
    raise RuntimeError("target_start_failed")


def untouched(preflight):
    names = [
        container
        for container in preflight["containers"]
        if container not in [name(s) for s in TARGETS]
    ]
    for container, item in inspect(names).items():
        original = preflight["containers"][container]
        require(
            item["Id"] == original["id"]
            and item["Image"] == original["image"]
            and item["RestartCount"] == original["restarts"]
            and item["State"]["Running"] == original["running"],
            "unrelated_container_changed",
        )


def recovery_decision(frozen, preflight):
    safe = False
    reason = "durable_state_changed"
    try:
        current = db_state()
        files = content_manifest(preflight["volumes"]["draft"]["source"])
        safe = rollback_draft_safe(
            frozen, current, preflight["volumes"]["draft"]["files"], files
        )
        idle(current)
        if safe:
            reason = "durable_state_unchanged"
    except Exception:  # noqa: BLE001 - every read/shape error must keep draft stopped.
        safe = False
        reason = "state_verification_failed"
    return safe, reason


def recover(backup):
    backup = Path(backup).resolve()
    require(
        backup.parent == Path("/var/backups/edu-ai")
        and backup.name.startswith("admin-pipeline-"),
        "invalid_recovery_backup",
    )
    preflight = json.loads((backup / "before.json").read_text())
    verified = preflight.get("effective_runtime", {})
    require(
        all(
            verified.get(service)
            == {"environment_matches": True, "command_and_image_defaults_match": True}
            for service in TARGETS
        ),
        "recovery_baseline_effective_runtime_unverified",
    )
    frozen = json.loads((backup / "frozen.json").read_text())
    # Stop candidate before deciding old-code compatibility. Fail closed on any read error.
    graceful_stop(TARGETS)
    safe, reason = recovery_decision(frozen, preflight)
    require(
        sha(ROOT / ".env") == preflight["config_hashes"][".env"], "recovery_env_drift"
    )
    # Original Compose globally renders APP_IMAGE=admin da052082, while these four
    # actually ran 83a41e41. A plain original-file restore would NOT restore old code.
    original_compose = (backup / "compose.yaml").read_text()
    rollback_compose = patch_compose(original_compose)
    # Old model workers must regain their original absence of MODEL_SECRET_KEY.
    for service in MODELS:
        import re

        pattern = re.compile(
            r"(?ms)^  " + re.escape(service) + r":\n.*?(?=^  [A-Za-z0-9_-]+:|\Z)"
        )
        match = pattern.search(rollback_compose)
        require(match is not None, "rollback_service_block_missing")
        block = match.group().replace(
            "      MODEL_SECRET_KEY: ${MODEL_SECRET_KEY:-}\n", "", 1
        )
        rollback_compose = (
            rollback_compose[: match.start()] + block + rollback_compose[match.end() :]
        )
    atomic_text(
        ROOT / "compose.yaml",
        rollback_compose,
        (backup / "compose.yaml").stat().st_mode & 0o777,
    )
    atomic_text(
        ROOT / ".release.env",
        patch_release((backup / ".release.env").read_text(), BASE),
    )
    expected = json.loads((backup / "render-safe-hashes.json").read_text())
    rendered = render()
    # Secret-free service hashes permit strict restoration checks without serializing config.
    for service, original_hash in expected.items():
        value = rendered["services"][service].copy()
        if service in TARGETS:
            value["image"] = "original-target-image-ignored"
        require(digest(value) == original_hash, "rollback_render_changed")
    services = TARGETS if safe else MODELS
    start(services)
    current_items = running(services, BASE)
    for service in services:
        require(
            safe_container(current_items[name(service)])["runtime_hash"]
            == preflight["containers"][name(service)]["runtime_hash"],
            "rollback_runtime_drift",
        )
    if not safe:
        require(
            not inspect([name(DRAFT)])[name(DRAFT)]["State"]["Running"],
            "unsafe_draft_not_stopped",
        )
    untouched(preflight)
    report = {
        "result": "ROLLBACK_OK" if safe else "ROLLBACK_FORWARD_FIX_REQUIRED",
        "at": now().isoformat(),
        "backup": str(backup),
        "draft_restarted": safe,
        "reason": reason,
        "old_image": BASE,
        "database_and_journals_restored": False,
        "frontend_action": "Root must retain/restore the matching previous frontend; this helper never swaps assets.",
    }
    save(backup / "recovery-result.json", report)
    print(json.dumps(report), flush=True)
    return report


def cutover():
    os.umask(0o077)
    quiet_window()
    candidate = json.loads((STAGE / "candidate.json").read_text())
    require(
        candidate["legacy_image"] == BASE and candidate["image"] != BASE,
        "candidate_base_invalid",
    )
    manifest = json.loads((STAGE / candidate["manifest"]).read_text())
    require(
        manifest["source_commit"] == candidate["source_commit"]
        and manifest["legacy_image"] == BASE
        and len(manifest["overlay_sha256"]) == 12,
        "candidate_manifest_invalid",
    )
    require(
        json.loads(run(["docker", "image", "inspect", candidate["image"]]))[0]["Id"]
        == candidate["image"],
        "candidate_image_missing",
    )
    preflight = json.loads((STAGE / "preflight-state.json").read_text())
    require(
        (
            now() - __import__("datetime").datetime.fromisoformat(preflight["at"])
        ).total_seconds()
        < 300,
        "preflight_too_old",
    )
    require(config_hashes() == preflight["config_hashes"], "config_drift")
    items = inspect(list(preflight["containers"]))
    require(
        {key: safe_container(value) for key, value in items.items()}
        == preflight["containers"],
        "container_drift",
    )
    mode_check(items)
    initial = db_state()
    idle(initial)
    preserved(preflight["state"], initial)
    for volume in preflight["volumes"].values():
        require(content_manifest(volume["source"]) == volume["files"], "volume_drift")
    before_render = render()
    verify_target_recreation(items, before_render)
    original_compose = (ROOT / "compose.yaml").read_text()
    original_release = (ROOT / ".release.env").read_text()
    new_compose = patch_compose(original_compose)
    new_release = patch_release(original_release, candidate["image"])
    backup = Path("/var/backups/edu-ai") / (
        "admin-pipeline-" + now().strftime("%Y%m%dT%H%M%SZ")
    )
    backup.mkdir(mode=0o700)
    for filename in [".env", ".release.env", "compose.yaml"]:
        shutil.copy2(ROOT / filename, backup / filename)
        (backup / filename).chmod(0o600)
    save(backup / "before.json", preflight)
    # Save hashes only. Raw Compose render includes credentials and is never written.
    render_hashes = {}
    for service, value in before_render["services"].items():
        normalized = value.copy()
        if service in TARGETS:
            normalized["image"] = "original-target-image-ignored"
        render_hashes[service] = digest(normalized)
    save(backup / "render-safe-hashes.json", render_hashes)
    save(STAGE / "active-backup.json", {"backup": str(backup)})
    stopped = False
    try:
        quiet_window()
        preserved(initial, db_state())
        stopped = True
        graceful_stop(TARGETS)
        frozen = db_state()
        idle(frozen)
        preserved(initial, frozen)
        save(backup / "frozen.json", frozen)
        for volume in preflight["volumes"].values():
            require(
                content_manifest(volume["source"]) == volume["files"],
                "journal_changed_during_stop",
            )
        verified = backups(backup, preflight, frozen)
        print(
            json.dumps(
                {
                    "result": "BACKUP_VERIFIED",
                    "backup": str(backup),
                    "verification": verified,
                }
            ),
            flush=True,
        )
        # Recheck admission and all configuration before the first production mutation.
        quiet_window()
        preserved(frozen, db_state())
        require(
            config_hashes() == preflight["config_hashes"],
            "config_changed_during_backup",
        )
        atomic_text(
            ROOT / "compose.yaml",
            new_compose,
            (ROOT / "compose.yaml").stat().st_mode & 0o777,
        )
        atomic_text(ROOT / ".release.env", new_release)
        verified_patch = verify_render_patch(
            before_render, render(), candidate["image"]
        )
        require(sha(ROOT / ".env") == preflight["config_hashes"][".env"], "env_changed")
        start(TARGETS)
        current = running(TARGETS, candidate["image"])
        for service in TARGETS:
            require(
                safe_container(current[name(service)])["runtime_hash"]
                == preflight["containers"][name(service)]["runtime_hash"],
                "runtime_config_drift_" + service,
            )
        mode_check(current)
        untouched(preflight)
        preserved(frozen, db_state())
        for volume in preflight["volumes"].values():
            require(
                content_manifest(volume["source"]) == volume["files"],
                "journal_changed_after_restart",
            )
        result = {
            "result": "CUTOVER_STARTED_PENDING_POSTCHECK",
            "at": now().isoformat(),
            "backup": str(backup),
            "image": candidate["image"],
            "source_commit": candidate["source_commit"],
            "containers": {
                key: safe_container(value) for key, value in current.items()
            },
            "config_hashes": config_hashes(),
            "patch": verified_patch,
            "frontend_swapped": False,
        }
        save(STAGE / "cutover-result.json", result)
        save(backup / "cutover-result.json", result)
        print(json.dumps(result), flush=True)
    except Exception as exc:  # noqa: BLE001 - restore safe services for every cutover failure.
        print(
            json.dumps(
                {
                    "result": "CUTOVER_FAILED",
                    "error": str(exc)
                    if isinstance(exc, RuntimeError)
                    else type(exc).__name__,
                    "backup": str(backup),
                }
            ),
            flush=True,
        )
        if stopped:
            # Even if stop failed before frozen.json was written, preserve original
            # snapshot and let recovery stop/recheck without assuming side-effect freedom.
            if not (backup / "frozen.json").exists():
                save(backup / "frozen.json", initial)
            recover(backup)
        raise SystemExit(1) from None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--recover", type=Path)
    args = parser.parse_args()
    if args.recover:
        recover(args.recover)
    else:
        cutover()
