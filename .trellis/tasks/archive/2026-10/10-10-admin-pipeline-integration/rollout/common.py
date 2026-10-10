"""Task-specific, secret-safe host helpers for the four legacy pipeline consumers."""

import base64
import copy
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path("/opt/edu-ai-lead-agent")
STAGE = Path(__file__).resolve().parent
PROJECT = "edu-ai-lead-agent"
BASE = "sha256:83a41e414fee1636c8d4897ae175ee5549afd9a7d4b37df0897b838c9b714851"
ADMIN = "sha256:da05208214aa273084fd2bccb9ce86dbdc1c0ee2069a855706a5d058686e2df7"
MODELS = [
    "official-account-local-worker",
    "official-account-weekly-dag-worker",
    "governance-worker",
]
DRAFT = "wechat-official-account-draft-worker"
TARGETS = MODELS + [DRAFT]
CONSUMERS = ["acquisition-api", "content-worker", "wecom-infographic-producer"] + MODELS
COMPOSE = [
    "docker",
    "compose",
    "-p",
    PROJECT,
    "--env-file",
    ".env",
    "--env-file",
    ".release.env",
]
PG = PROJECT + "-postgres-1"
VOLUMES = {
    "draft": (DRAFT, "/app/output/wechat-mp-draft-artifacts"),
    "weekly": ("official-account-weekly-dag-worker", "/app/output"),
}
TABLES = [
    "governance_jobs",
    "governance_attempts",
    "official_account_article_runs",
    "official_account_article_attempts",
    "official_account_weekly_dag_runs",
    "official_account_weekly_dag_nodes",
    "official_account_weekly_dag_attempts",
    "wechat_mp_draft_jobs",
    "wechat_mp_draft_items",
    "wechat_mp_draft_attempts",
    "official_account_single_editions",
    "official_account_draft_owners",
    "model_api_keys",
    "execution_governed_runs",
    "execution_agent_allocations",
    "execution_budget_reservations",
    "execution_trace_events",
    "execution_artifacts",
]


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def now():
    return dt.datetime.now(dt.timezone.utc)


def run(args, *, stdin=None, timeout=120):
    # Never persist stdout/stderr wholesale: inspect/config/logs can contain secrets.
    try:
        result = subprocess.run(
            args,
            input=stdin,
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("command_timeout_" + args[0]) from None
    require(result.returncode == 0, "command_failed_" + args[0])
    return result.stdout


def name(service):
    return PROJECT + "-" + service + "-1"


def inspect(names):
    return {
        x["Name"].lstrip("/"): x for x in json.loads(run(["docker", "inspect", *names]))
    }


def environment(item):
    return dict(entry.split("=", 1) for entry in item["Config"]["Env"])


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def save(path, value):
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    path.chmod(0o600)


def atomic_text(path, text, mode=0o600):
    temporary = path.with_name(path.name + ".pipeline-install")
    require(not temporary.exists(), "temporary_config_exists")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def safe_container(item):
    return {
        "id": item["Id"],
        "image": item["Image"],
        "running": item["State"]["Running"],
        "restarts": item["RestartCount"],
        "started_at": item["State"]["StartedAt"],
        "host": item["Config"]["Hostname"],
        "runtime_hash": runtime_hash(item),
    }


def runtime_hash(item):
    config = {
        key: item["Config"].get(key)
        for key in [
            "Cmd",
            "Entrypoint",
            "WorkingDir",
            "User",
            "StopSignal",
            "ExposedPorts",
            "Healthcheck",
        ]
    }
    config["environment"] = {
        key: value
        for key, value in environment(item).items()
        if key != "MODEL_SECRET_KEY"
    }
    config["host"] = {
        key: item["HostConfig"].get(key)
        for key in [
            "RestartPolicy",
            "Memory",
            "NanoCpus",
            "CpusetCpus",
            "ReadonlyRootfs",
            "Privileged",
            "SecurityOpt",
            "CapAdd",
            "CapDrop",
            "NetworkMode",
            "PortBindings",
        ]
    }
    config["mounts"] = sorted(
        (
            {
                key: m.get(key)
                for key in ["Type", "Source", "Destination", "RW", "Propagation"]
            }
            for m in item["Mounts"]
        ),
        key=lambda m: m["Destination"],
    )
    return digest(config)


def quiet_window():
    local = now().astimezone(ZoneInfo("Asia/Shanghai"))
    minute = local.hour * 60 + local.minute
    require(
        not any(
            start <= minute < end
            for start, end in [(360, 510), (660, 810), (1020, 1170)]
        ),
        "inside_push_window",
    )
    # Reserve ten minutes before the next scheduled window; no stopping on its edge.
    require(
        not any(0 <= start - minute <= 10 for start in [360, 660, 1020]),
        "push_window_too_close",
    )


def config_hashes():
    return {p: sha(ROOT / p) for p in [".env", ".release.env", "compose.yaml"]}


def render():
    return json.loads(run(COMPOSE + ["--profile", "*", "config", "--format", "json"]))


PIPELINE_IMAGE_LINE = "    image: ${ADMIN_PIPELINE_IMAGE:-${APP_IMAGE:-edu-ai-lead-agent-backend:local}}\n"
IMAGE_REPOSITORY = "offline.local/edu-ai/edu-ai-lead-agent-backend@"
PRESERVED_LEGACY_ENV = {
    "CONTENT_SCORING_VERSION": "scoring-v1-preview.11-qualified-authoritative-priority",
    "CONTENT_SLOT_RANKING_VERSION": "slot-ranking-v1",
}


def verify_effective_runtime(item, rendered_service, image_config):
    """Compare actual runtime to recreation inputs before stopping, without storing values."""
    desired = dict(entry.split("=", 1) for entry in image_config.get("Env", []))
    for key, value in rendered_service.get("environment", {}).items():
        if value is None:
            desired.pop(key, None)
        else:
            desired[key] = value
    actual = environment(item)
    different = sorted(
        key
        for key in actual.keys() | desired.keys()
        if actual.get(key) != desired.get(key) or (key in actual) != (key in desired)
    )
    require(not different, "effective_environment_drift:" + ",".join(different))
    for compose_key, inspect_key in [
        ("command", "Cmd"),
        ("entrypoint", "Entrypoint"),
        ("working_dir", "WorkingDir"),
        ("user", "User"),
    ]:
        desired_value = rendered_service.get(compose_key)
        if desired_value is None:
            desired_value = image_config.get(inspect_key)
        require(
            item["Config"].get(inspect_key) == desired_value,
            "effective_runtime_drift:" + inspect_key,
        )
    return {"environment_matches": True, "command_and_image_defaults_match": True}


def verify_target_recreation(items, rendered):
    image_config = json.loads(run(["docker", "image", "inspect", BASE]))[0]["Config"]
    result = {}
    for service in TARGETS:
        result[service] = verify_effective_runtime(
            items[name(service)], rendered["services"][service], image_config
        )
        require(
            all(
                environment(items[name(service)]).get(key) == value
                for key, value in PRESERVED_LEGACY_ENV.items()
            ),
            "legacy_version_not_preserved_" + service,
        )
    return result


def patch_compose(text):
    """Accept the original baseline or the exact restored BASE override; preserve all values."""
    result = text
    existing_pins = 0
    for service in TARGETS:
        pattern = re.compile(
            r"(?ms)^  " + re.escape(service) + r":\n.*?(?=^  [A-Za-z0-9_-]+:|\Z)"
        )
        matches = list(pattern.finditer(result))
        require(len(matches) == 1, "service_block_not_unique_" + service)
        block = matches[0].group()
        anchor = "    <<: *app-runtime\n"
        require(block.count(anchor) == 1, "runtime_anchor_" + service)
        image_lines = re.findall(r"^    image:.*\n", block, re.MULTILINE)
        if image_lines:
            require(
                image_lines == [PIPELINE_IMAGE_LINE]
                and block.count("ADMIN_PIPELINE_IMAGE") == 1,
                "existing_image_override_" + service,
            )
            replacement = block
            existing_pins += 1
        else:
            require(
                "ADMIN_PIPELINE_IMAGE" not in block,
                "existing_image_override_" + service,
            )
            replacement = block.replace(anchor, anchor + PIPELINE_IMAGE_LINE, 1)
        if service in MODELS:
            require(
                "MODEL_SECRET_KEY" not in block, "existing_model_mapping_" + service
            )
            require(
                block.count("    environment:\n") == 1, "environment_block_" + service
            )
            replacement = replacement.replace(
                "    environment:\n",
                "    environment:\n      MODEL_SECRET_KEY: ${MODEL_SECRET_KEY:-}\n",
                1,
            )
        result = result[: matches[0].start()] + replacement + result[matches[0].end() :]
    require(existing_pins in (0, 4), "partial_pipeline_override")
    return result


def patch_release(text, image):
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", image) is not None, "invalid_image_id")
    lines = text.splitlines(keepends=True)
    require(
        sum(line.startswith("APP_IMAGE=") for line in lines) == 1,
        "app_image_not_unique",
    )
    existing = [line for line in lines if line.startswith("ADMIN_PIPELINE_IMAGE=")]
    if existing:
        require(
            len(existing) == 1
            and existing[0].rstrip("\n")
            == "ADMIN_PIPELINE_IMAGE=" + IMAGE_REPOSITORY + BASE,
            "pipeline_pin_not_original_base",
        )
        return "".join(
            "ADMIN_PIPELINE_IMAGE=" + IMAGE_REPOSITORY + image + "\n"
            if line.startswith("ADMIN_PIPELINE_IMAGE=")
            else line
            for line in lines
        )
    return (
        text.rstrip("\n") + "\nADMIN_PIPELINE_IMAGE=" + IMAGE_REPOSITORY + image + "\n"
    )


def verify_render_patch(before, after, image):
    expected = copy.deepcopy(before)
    reference = before["services"]["acquisition-api"]["environment"]["MODEL_SECRET_KEY"]
    require(bool(reference), "existing_model_key_missing")
    require(
        len(
            base64.urlsafe_b64decode(
                reference.strip() + "=" * (-len(reference.strip()) % 4)
            )
        )
        == 32,
        "model_key_format_invalid",
    )
    for service in TARGETS:
        expected["services"][service]["image"] = (
            "offline.local/edu-ai/edu-ai-lead-agent-backend@" + image
        )
        if service in MODELS:
            require(
                "MODEL_SECRET_KEY" not in before["services"][service]["environment"],
                "unexpected_existing_model_mapping",
            )
            expected["services"][service]["environment"]["MODEL_SECRET_KEY"] = reference
    require(expected == after, "rendered_config_changed_outside_allowlist")
    require(
        not after["services"][DRAFT]["environment"].get("MODEL_SECRET_KEY"),
        "draft_gained_model_secret",
    )
    require(
        not after["services"][DRAFT]["environment"].get("ADMIN_SECRET_KEY"),
        "draft_gained_admin_secret",
    )
    return {"render_allowlist_verified": True, "model_key_matches_existing": True}


def mode_check(items):
    weekly = environment(items[name(MODELS[1])])
    draft = environment(items[name(DRAFT)])
    require(
        weekly.get("OFFICIAL_ACCOUNT_SINGLE_ENABLED", "").lower() == "true",
        "weekly_not_single_mode",
    )
    require(
        draft.get("OFFICIAL_ACCOUNT_SINGLE_ENABLED", "").lower() == "true",
        "draft_not_single_mode",
    )
    for env, key in [
        (weekly, "OFFICIAL_ACCOUNT_WEEKLY_WORKER_ENABLED"),
        (weekly, "OFFICIAL_ACCOUNT_WEEKLY_SCHEDULER_ENABLED"),
        (draft, "WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED"),
    ]:
        require(
            env.get(key, "false").lower() == "false", "legacy_processing_enabled_" + key
        )
    require(
        weekly.get("OFFICIAL_ACCOUNT_SINGLE_ACCOUNT_FINGERPRINT")
        == draft.get("OFFICIAL_ACCOUNT_SINGLE_ACCOUNT_FINGERPRINT"),
        "single_account_mismatch",
    )
    require(
        re.fullmatch(
            "[0-9a-f]{64}", draft.get("OFFICIAL_ACCOUNT_SINGLE_ACCOUNT_FINGERPRINT", "")
        )
        is not None,
        "single_account_invalid",
    )
    return {
        "single_enabled": True,
        "legacy_auto_processing_disabled": True,
        "account_binding_matches": True,
    }


def sql_json(queries):
    sql = (
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\nSET LOCAL statement_timeout = '30s';\n"
        + "\n".join(
            "SELECT row_to_json(q) FROM (" + query + ") q;"
            for query in queries.values()
        )
        + "\nROLLBACK;"
    )
    output = (
        run(
            [
                "docker",
                "exec",
                "-i",
                PG,
                "sh",
                "-c",
                'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq -v ON_ERROR_STOP=1',
            ],
            stdin=sql,
            timeout=60,
        )
        .strip()
        .splitlines()
    )
    require(len(output) == len(queries), "database_result_shape")
    return {key: json.loads(line) for key, line in zip(queries, output)}


def db_state():
    queries = {"schema": "SELECT version_num AS version FROM alembic_version"}
    for table in TABLES:
        # The single consumer refreshes only the history-barrier timestamp while idle.
        row = (
            "CASE WHEN j->>'key_kind'='history' THEN j-'updated_at' ELSE j END"
            if table == "official_account_draft_owners"
            else "j"
        )
        predicate = ""
        if table.startswith("execution_"):
            field = "id" if table == "execution_governed_runs" else "run_id"
            predicate = (
                " WHERE "
                + field
                + " IN (SELECT id FROM official_account_weekly_dag_runs)"
            )
        queries[table] = (
            "SELECT count(*) AS count, md5(COALESCE(string_agg(md5(("
            + row
            + ")::text), '' ORDER BY md5(("
            + row
            + ")::text)),'')) AS digest FROM (SELECT to_jsonb(t) j FROM "
            + table
            + " t"
            + predicate
            + ") rows"
        )
    active = {
        "governance": "SELECT count(*) AS count FROM governance_jobs WHERE status IN ('queued','running','retry_scheduled') OR lease_token IS NOT NULL OR lease_expires_at IS NOT NULL",
        "articles": "SELECT count(*) AS count FROM official_account_article_runs WHERE status IN ('queued','running') OR lease_token IS NOT NULL OR lease_expires_at IS NOT NULL",
        "single": "SELECT count(*) AS count FROM official_account_single_editions WHERE status IN ('admitted','generating','preparing','ready','delivering') OR lease_token IS NOT NULL OR lease_expires_at IS NOT NULL",
        "weekly": "SELECT count(*) AS count FROM official_account_weekly_dag_nodes n JOIN official_account_weekly_dag_runs r ON r.id=n.run_id WHERE n.lease_expires_at IS NOT NULL OR n.status='running' OR r.status NOT IN ('terminal_failed','ready')",
        "draft": "SELECT count(*) AS count FROM wechat_mp_draft_jobs WHERE status IN ('queued','running','retryable_failed') OR lease_expires_at IS NOT NULL",
        "current_single_unknown": "SELECT count(*) AS count FROM official_account_single_editions WHERE status='outcome_unknown' AND (expires_at > now() OR updated_at >= '2026-10-10T06:05:57Z')",
        "new_article_unknown": "SELECT count(*) AS count FROM official_account_article_runs WHERE status='result_unknown' AND updated_at >= '2026-10-10T06:05:57Z'",
        "allocations": "SELECT count(*) AS count FROM execution_agent_allocations WHERE status='running' AND run_id IN (SELECT id FROM official_account_weekly_dag_runs)",
        "reservations": "SELECT count(*) AS count FROM execution_budget_reservations WHERE status='reserved' AND run_id IN (SELECT id FROM official_account_weekly_dag_runs)",
    }
    queries.update({"active_" + key: value for key, value in active.items()})
    queries["latest_versions"] = (
        "SELECT COALESCE(jsonb_object_agg(provider, version),'{}'::jsonb) AS versions FROM (SELECT DISTINCT ON (provider) provider,version FROM model_api_keys ORDER BY provider,version DESC) latest"
    )
    queries["account_binding"] = (
        "SELECT count(*) AS count, md5(COALESCE(string_agg((to_jsonb(a)-'stats_synced_on'-'stats_sync_error'-'updated_at')::text,'' ORDER BY id),'')) AS digest FROM wechat_accounts a"
    )
    result = sql_json(queries)
    return result


def idle(state):
    require(state["schema"]["version"] == "20261010_0061", "schema_drift")
    require(
        all(
            value["count"] == 0
            for key, value in state.items()
            if key.startswith("active_")
        ),
        "target_work_not_idle",
    )


def volume_paths(items):
    output = {}
    for key, (service, destination) in VOLUMES.items():
        matches = [
            m for m in items[name(service)]["Mounts"] if m["Destination"] == destination
        ]
        require(
            len(matches) == 1 and matches[0]["Type"] == "volume" and matches[0]["RW"],
            "volume_mount_shape_" + key,
        )
        source = Path(matches[0]["Source"])
        require(
            source.is_dir()
            and not source.is_symlink()
            and str(source).startswith("/var/lib/docker/volumes/"),
            "volume_source_invalid",
        )
        output[key] = str(source)
    return output


def content_manifest(root):
    root = Path(root)
    output = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "unexpected_volume_symlink")
        if path.is_file():
            before = path.stat()
            value = {
                "sha256": sha(path),
                "bytes": before.st_size,
                "mode": before.st_mode & 0o777,
                "uid": before.st_uid,
                "gid": before.st_gid,
            }
            after = path.stat()
            require(
                (before.st_mtime_ns, before.st_size)
                == (after.st_mtime_ns, after.st_size),
                "volume_changed_while_hashing",
            )
            output[str(path.relative_to(root))] = value
        else:
            require(path.is_dir(), "unexpected_volume_special_file")
    return output


def source_hashes(container):
    code = "import hashlib,json\nfrom pathlib import Path\np=Path('/app')\nprint(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in [*(p/'app').rglob('*'),*(p/'alembic').rglob('*'),p/'pyproject.toml',p/'alembic.ini'] if f.is_file() and '__pycache__' not in f.parts and f.suffix != '.pyc'},sort_keys=True))"
    return json.loads(
        run(["docker", "exec", "-i", container, "python", "-"], stdin=code)
    )


def preserved(before, after):
    require(before == after, "business_state_changed")


def rollback_draft_safe(frozen_state, current_state, frozen_files, current_files):
    # Any durable change, including a new pin, add intent, receipt or unknown state,
    # requires compatible code/forward repair. Query/read failure is handled by caller.
    if any(Path(path).name.endswith("-layout.json") for path in frozen_files):
        return False
    return (
        all(
            frozen_state[key] == current_state[key]
            for key in [
                "official_account_single_editions",
                "official_account_draft_owners",
                "wechat_mp_draft_jobs",
                "wechat_mp_draft_items",
                "wechat_mp_draft_attempts",
            ]
        )
        and frozen_files == current_files
    )
