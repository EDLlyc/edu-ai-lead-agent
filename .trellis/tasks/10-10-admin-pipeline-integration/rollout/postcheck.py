"""Read-only runtime proof. Run --observation first, then final >60 s later.

No provider requests, authenticated HTTP sessions, key edits, worker --once,
queue mutations or frontend changes. Root finalizes frontend only after PASS.
"""

import argparse
import datetime as dt
import json
from pathlib import Path

from common import (
    CONSUMERS,
    DRAFT,
    STAGE,
    TARGETS,
    config_hashes,
    content_manifest,
    db_state,
    digest,
    environment,
    idle,
    inspect,
    mode_check,
    name,
    now,
    preserved,
    require,
    safe_container,
    save,
    source_hashes,
    sql_json,
)
from cutover import untouched

ERRORS = [
    "Traceback (most recent call last)",
    "console_model_keys_unavailable",
    "console_model_key_heartbeat_failed",
    "console_model_key_unreadable",
    "single_history_or_artifact_invalid",
    "single_catalog_fallback_lease_lost",
    "lease_lost",
    "lease_expired",
    "heartbeat_failed",
]


def parsed(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_heartbeat(service, item, heartbeat, versions, instant):
    require(heartbeat is not None, "heartbeat_missing_" + service)
    require(
        heartbeat["service"] == service
        and heartbeat["host"] == item["Config"]["Hostname"],
        "heartbeat_wrong_host_" + service,
    )
    require(
        heartbeat["versions"] is not None and heartbeat["versions"] == versions,
        "heartbeat_wrong_versions_" + service,
    )
    require(heartbeat["load_errors"] == {}, "heartbeat_load_errors_" + service)
    started = parsed(item["State"]["StartedAt"])
    process_started = parsed(heartbeat["started_at"])
    seen = parsed(heartbeat["seen_at"])
    require(
        -2 <= (process_started - started).total_seconds() < 120,
        "heartbeat_wrong_start_" + service,
    )
    require(
        seen >= process_started and -2 <= (instant - seen).total_seconds() < 150,
        "heartbeat_not_fresh_" + service,
    )
    return {
        "service": service,
        "host": heartbeat["host"],
        "container_id": item["Id"],
        "started_at": heartbeat["started_at"],
        "seen_at": heartbeat["seen_at"],
        "versions": heartbeat["versions"],
        "load_errors": heartbeat["load_errors"],
    }


def check(observation):
    candidate = json.loads((STAGE / "candidate.json").read_text())
    manifest = json.loads((STAGE / candidate["manifest"]).read_text())
    cutover = json.loads((STAGE / "cutover-result.json").read_text())
    backup = Path(cutover["backup"])
    before = json.loads((backup / "before.json").read_text())
    frozen = json.loads((backup / "frozen.json").read_text())
    require(config_hashes() == cutover["config_hashes"], "postcutover_config_drift")
    untouched(before)
    items = inspect([name(service) for service in set(TARGETS + CONSUMERS)])
    reference = environment(items[name("acquisition-api")]).get("MODEL_SECRET_KEY")
    require(bool(reference), "existing_model_secret_missing")
    for service in CONSUMERS:
        require(
            environment(items[name(service)]).get("MODEL_SECRET_KEY") == reference,
            "model_secret_not_shared_" + service,
        )
    for key in ["MODEL_SECRET_KEY", "ADMIN_SECRET_KEY"]:
        require(
            not environment(items[name(DRAFT)]).get(key), "draft_has_unnecessary_secret"
        )
    sources = {}
    for service in TARGETS:
        item = items[name(service)]
        require(
            item["Image"] == candidate["image"]
            and item["State"]["Running"]
            and item["RestartCount"] == 0,
            "target_unhealthy_" + service,
        )
        require(
            item["Id"] == cutover["containers"][name(service)]["id"],
            "target_recreated_during_check",
        )
        require(
            safe_container(item)["runtime_hash"]
            == before["containers"][name(service)]["runtime_hash"],
            "runtime_config_changed_" + service,
        )
        files = source_hashes(name(service))
        expected = dict(before["sources"][service]["all_app_files"])
        expected.update(manifest["overlay_sha256"])
        require(files == expected, "candidate_source_or_nonoverlay_drift_" + service)
        require(files == manifest["expected_file_sha256"], "candidate_manifest_drift")
        sources[service] = {
            "files": len(files),
            "manifest_digest": digest(files),
            "overlay_files": 12,
            "nonoverlay_unchanged": True,
        }
    mode = mode_check(items)
    state = db_state()
    idle(state)
    preserved(frozen, state)
    for volume in before["volumes"].values():
        require(
            content_manifest(volume["source"]) == volume["files"],
            "journal_or_prepared_artifact_changed",
        )
    # Query only safe heartbeat fields; no admin projection that can select an old host.
    beats = sql_json(
        {
            "beats": "SELECT COALESCE(json_agg(json_build_object('service',service,'host',host,'versions',versions,'load_errors',load_errors,'started_at',started_at,'seen_at',seen_at)),'[]') AS items FROM model_key_consumers"
        }
    )["beats"]["items"]
    instant = now()
    consumers = {}
    for service in CONSUMERS:
        item = items[name(service)]
        matching = [
            beat
            for beat in beats
            if beat["service"] == service and beat["host"] == item["Config"]["Hostname"]
        ]
        require(len(matching) == 1, "current_host_heartbeat_not_unique_" + service)
        consumers[service] = check_heartbeat(
            service, item, matching[0], state["latest_versions"]["versions"], instant
        )
    logs = {}
    for service in set(TARGETS + CONSUMERS):
        item = items[name(service)]
        since = item["State"]["StartedAt"] if service in TARGETS else cutover["at"]
        # Docker sends normal logs to stderr as well. Capture both without persistence.
        import subprocess

        captured = subprocess.run(
            ["docker", "logs", "--since", since, name(service)],
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        require(captured.returncode == 0, "log_read_failed_" + service)
        content = captured.stdout + "\n" + captured.stderr
        counts = {key: content.count(key) for key in ERRORS}
        require(not any(counts.values()), "new_runtime_errors_" + service)
        logs[service] = counts
    report = {
        "result": "POSTCHECK_OBSERVATION_OK",
        "observation": observation,
        "at": instant.isoformat(),
        "image": candidate["image"],
        "source_commit": candidate["source_commit"],
        "backup": str(backup),
        "consumers": consumers,
        "sources": sources,
        "modes": mode,
        "state_preserved": True,
        "journal_and_prepared_files_preserved": True,
        "logs": logs,
        "production_decryption_claim": "No stored keys: empty versions prove reads/fallback only"
        if not state["latest_versions"]["versions"]
        else "Stored latest versions verified loaded by current hosts",
        "provider_calls_or_mutations_by_check": False,
    }
    if observation == "final":
        first = json.loads((STAGE / "postcheck-first.json").read_text())
        require(
            first["image"] == report["image"]
            and first["source_commit"] == report["source_commit"],
            "first_observation_candidate_mismatch",
        )
        require(
            (instant - parsed(first["at"])).total_seconds() >= 60,
            "second_observation_too_early",
        )
        for service, current in consumers.items():
            old = first["consumers"][service]
            require(
                current["container_id"] == old["container_id"]
                and current["started_at"] == old["started_at"],
                "consumer_restarted_between_observations",
            )
            require(
                parsed(current["seen_at"]) > parsed(old["seen_at"]),
                "heartbeat_did_not_advance_" + service,
            )
        report["result"] = "POSTCHECK_PASS_FRONTEND_MAY_FINALIZE"
        report["observation_interval_seconds"] = (
            instant - parsed(first["at"])
        ).total_seconds()
    save(STAGE / ("postcheck-" + observation + ".json"), report)
    save(backup / ("postcheck-" + observation + ".json"), report)
    print(json.dumps(report), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation", choices=["first", "final"], required=True)
    arguments = parser.parse_args()
    check(arguments.observation)
