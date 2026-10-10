"""Read-only production admission; save only hashes, counts and container identities."""

import json
import shutil
from pathlib import Path

from common import (
    ADMIN,
    BASE,
    CONSUMERS,
    STAGE,
    TARGETS,
    config_hashes,
    content_manifest,
    db_state,
    digest,
    idle,
    inspect,
    mode_check,
    name,
    now,
    require,
    run,
    safe_container,
    save,
    source_hashes,
    volume_paths,
)


def collect():
    baseline = json.loads((STAGE / "live-research.json").read_text())
    items = inspect(list(baseline["containers"]))
    for service in TARGETS:
        item = items[name(service)]
        require(
            item["Image"] == BASE
            and item["State"]["Running"]
            and item["RestartCount"] == 0,
            "target_base_not_ready_" + service,
        )
    for service in CONSUMERS[:3]:
        require(items[name(service)]["Image"] == ADMIN, "existing_admin_image_drift")
    hashes = config_hashes()
    require(hashes == baseline["config_hashes"], "config_changed_since_research")
    for container, item in items.items():
        previous = baseline["containers"][container]
        require(
            item["Id"] == previous["id"] and item["Image"] == previous["image"],
            "container_changed_since_research",
        )
    modes = mode_check(items)
    state = db_state()
    idle(state)
    legacy = json.loads((STAGE / "legacy-all-hashes.json").read_text())
    sources = {}
    for service in TARGETS:
        actual = source_hashes(name(service))
        require(actual == legacy, "legacy_source_changed_" + service)
        sources[service] = {"all_app_files": actual, "manifest_digest": digest(actual)}
    volumes = {}
    for key, source in volume_paths(items).items():
        files = content_manifest(source)
        if key == "draft":
            require(
                not any(Path(path).name.endswith("-layout.json") for path in files),
                "legacy_baseline_has_layout_pin",
            )
        volumes[key] = {
            "source": source,
            "files": files,
            "bytes": sum(item["bytes"] for item in files.values()),
            "files_digest": digest(files),
        }
    target_bytes = sum(item["bytes"] for item in volumes.values())
    # Database size is an allowlisted scalar, not credentials or rows.
    output = run(
        [
            "docker",
            "exec",
            "-i",
            name("postgres"),
            "sh",
            "-c",
            'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq -v ON_ERROR_STOP=1',
        ],
        stdin="BEGIN READ ONLY; SELECT pg_database_size(current_database()); ROLLBACK;",
    )
    db_bytes = int(output.strip())
    backup_parent = Path("/var/backups/edu-ai")
    require(backup_parent.is_dir(), "backup_parent_missing")
    free = shutil.disk_usage(backup_parent).free
    require(
        free > 2 * (target_bytes + db_bytes) + 1024 * 1024 * 1024,
        "backup_space_insufficient",
    )
    return {
        "at": now().isoformat(),
        "containers": {k: safe_container(v) for k, v in items.items()},
        "config_hashes": hashes,
        "modes": modes,
        "state": state,
        "sources": sources,
        "volumes": volumes,
        "backup_capacity": {
            "free_bytes": free,
            "database_bytes": db_bytes,
            "volume_bytes": target_bytes,
        },
    }


if __name__ == "__main__":
    report = collect()
    save(STAGE / "preflight-state.json", report)
    print(
        json.dumps(
            {
                "result": "PREFLIGHT_OK",
                "at": report["at"],
                "containers": len(report["containers"]),
                "volumes": {
                    key: {"bytes": value["bytes"], "files": len(value["files"])}
                    for key, value in report["volumes"].items()
                },
                "state": report["state"],
                "backup_capacity": report["backup_capacity"],
            },
            ensure_ascii=False,
        )
    )
