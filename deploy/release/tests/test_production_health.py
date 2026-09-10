from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from contract import BUNDLE_ALLOWED_PREFIXES, BUNDLE_REQUIRED_FILES

from deploy import LONG_RUNNING_SERVICES

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT = PROJECT_ROOT / "scripts" / "edu-ai-production-check.sh"
IMAGE_REFERENCE = "registry.example.test/edu-ai/app@sha256:" + "b" * 64
RELEASE_COMMIT = "a" * 40
IMAGE_ID = "sha256:" + "9" * 64


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _fake_docker_source() -> str:
    services = (*LONG_RUNNING_SERVICES, "postgres", "minio")
    return f"""#!{sys.executable}
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

SERVICES = {services!r}
IMAGE = {IMAGE_REFERENCE!r}
COMMIT = {RELEASE_COMMIT!r}
IMAGE_ID = {IMAGE_ID!r}
IDS = {{hashlib.sha256(service.encode()).hexdigest(): service for service in SERVICES}}
args = sys.argv[1:]
with Path(os.environ["FAKE_DOCKER_CALLS"]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args, separators=(",", ":")) + "\\n")

profiles = []
for profile in (
    "governance",
    "content",
    "official-account-weekly-dag",
    "official-account-local",
    "wechat-official-account-draft",
    "wecom",
):
    profiles.extend(("--profile", profile))
compose_base = ["compose", "--env-file", ".env", "--env-file", ".release.env"]

if args[: len(compose_base)] == compose_base:
    rest = args[len(compose_base) :]
    if rest[: len(profiles)] == profiles:
        rest = rest[len(profiles) :]
    if len(rest) == 3 and rest[:2] == ["ps", "-q"] and rest[2] in SERVICES:
        service = rest[2]
        failure = os.environ.get("FAKE_SERVICE_FAILURE", "")
        if failure == service + ":missing":
            raise SystemExit(0)
        container_id = hashlib.sha256(service.encode()).hexdigest()
        print(container_id)
        if failure == service + ":duplicate":
            print("f" * 64)
        raise SystemExit(0)
    expected_exec = [
        "exec",
        "-T",
        "postgres",
        "sh",
        "-c",
        'printf %s "$1" | base64 -d | psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At',
        "sh",
    ]
    if len(rest) == len(expected_exec) + 1 and rest[:-1] == expected_exec:
        query = base64.b64decode(rest[-1], validate=True).decode("utf-8")
        with Path(os.environ["FAKE_SQL_CALLS"]).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(query) + "\\n")
        normalized = " ".join(query.split())
        if normalized == "SELECT version_num FROM alembic_version":
            print(os.environ.get("FAKE_SCHEMA_HEAD", "20260909_0045"))
            raise SystemExit(0)
        if normalized.startswith("SELECT concat_ws('|',") and normalized.endswith(
            ") FROM wecom_delivery_jobs"
        ):
            print(os.environ.get("FAKE_QUEUE_COUNTS", "0|0|0|0"))
            raise SystemExit(0)
    raise SystemExit(91)

if len(args) == 2 and args[0] == "inspect" and args[1] in IDS:
    service = IDS[args[1]]
    failure = os.environ.get("FAKE_SERVICE_FAILURE", "")
    state = {{"Status": "running", "Health": {{"Status": "healthy"}}}}
    restarts = 0
    configured_image = IMAGE
    image_id = IMAGE_ID
    if service not in ("postgres", "minio"):
        state.pop("Health")
    if failure == service + ":stopped":
        state["Status"] = "exited"
    elif failure == service + ":unhealthy":
        state["Health"] = {{"Status": "unhealthy"}}
    elif failure == service + ":restart":
        restarts = 1
    elif failure == service + ":image":
        configured_image = configured_image.replace("b" * 64, "c" * 64)
    elif failure == service + ":image-id":
        image_id = "sha256:" + "8" * 64
    print(json.dumps([{{
        "State": state,
        "RestartCount": restarts,
        "Image": image_id,
        "Config": {{"Image": configured_image}},
    }}]))
    raise SystemExit(0)

if args == ["image", "inspect", IMAGE]:
    image_id = IMAGE_ID
    revision = COMMIT
    failure = os.environ.get("FAKE_IMAGE_FAILURE", "")
    if failure == "image-id":
        image_id = "sha256:" + "7" * 64
    elif failure == "revision":
        revision = "d" * 40
    print(json.dumps([{{
        "Id": image_id,
        "Config": {{"Labels": {{"org.opencontainers.image.revision": revision}}}},
    }}]))
    raise SystemExit(0)

raise SystemExit(91)
"""


def _fake_curl_source() -> str:
    return f"""#!{sys.executable}
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
with Path(os.environ["FAKE_CURL_CALLS"]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args, separators=(",", ":")) + "\\n")
expected = [
    "--fail",
    "--silent",
    "--max-time",
    "5",
    "--max-filesize",
    "65536",
    "http://127.0.0.1:8000/healthz",
]
if args != expected:
    raise SystemExit(91)
print(os.environ.get("FAKE_API_RESPONSE", '{{"status":"ok","environment":"production"}}'))
"""


@pytest.fixture
def runtime_fixture(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    app_dir = tmp_path / "application"
    fake_bin = tmp_path / "fake-bin"
    (app_dir / "deploy" / "release").mkdir(parents=True)
    (app_dir / "scripts").mkdir()
    fake_bin.mkdir()
    (app_dir / ".env").write_text("APP_ENV=production\n", encoding="utf-8")
    (app_dir / ".release.env").write_text(
        f"APP_IMAGE={IMAGE_REFERENCE}\n", encoding="utf-8"
    )
    (app_dir / ".release-commit").write_text(f"{RELEASE_COMMIT}\n", encoding="utf-8")
    (app_dir / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (app_dir / "deploy" / "release" / "migration-compatibility.json").write_text(
        json.dumps({"alembic_head": "20260909_0045"}) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(
        PROJECT_ROOT / "scripts" / "edu-ai-release-common.sh",
        app_dir / "scripts" / "edu-ai-release-common.sh",
    )
    for command in ("awk", "base64", "bash", "python3", "tr"):
        target = shutil.which(command)
        assert target is not None
        (fake_bin / command).symlink_to(target)
    _write_executable(fake_bin / "docker", _fake_docker_source())
    _write_executable(fake_bin / "curl", _fake_curl_source())
    environment = {
        "PATH": str(fake_bin),
        "EDU_AI_PRODUCTION_CHECK_APP_DIR": str(app_dir),
        "FAKE_DOCKER_CALLS": str(tmp_path / "docker-calls.jsonl"),
        "FAKE_CURL_CALLS": str(tmp_path / "curl-calls.jsonl"),
        "FAKE_SQL_CALLS": str(tmp_path / "sql-calls.jsonl"),
    }
    return app_dir, environment


def _run_check(
    runtime_fixture: tuple[Path, dict[str, str]], **overrides: str
) -> subprocess.CompletedProcess[str]:
    _app_dir, environment = runtime_fixture
    process_environment = os.environ.copy()
    process_environment.update(environment)
    process_environment.update(overrides)
    return subprocess.run(
        [str(CHECK_SCRIPT)],
        cwd=PROJECT_ROOT,
        env=process_environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _json_lines(path: Path) -> list[object]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_runtime_check_is_bundled_and_executable() -> None:
    relative = "scripts/edu-ai-production-check.sh"
    assert relative in BUNDLE_ALLOWED_PREFIXES
    assert relative in BUNDLE_REQUIRED_FILES
    assert CHECK_SCRIPT.stat().st_mode & 0o111


def test_healthy_offline_runtime_needs_no_node_and_reports_incomplete_provenance(
    runtime_fixture: tuple[Path, dict[str, str]],
) -> None:
    _app_dir, environment = runtime_fixture
    result = _run_check(runtime_fixture)
    assert result.returncode == 0, result.stderr
    assert "runtime_health=ok" in result.stdout
    assert "service_health=ok service_count=12" in result.stdout
    assert "schema_alignment=ok" in result.stdout
    assert "api_health=ok" in result.stdout
    assert "queue_state=idle queued=0 live_running=0 stale_running=0 ambiguous=0" in (
        result.stdout
    )
    assert "standard_release_provenance=incomplete" in result.stdout
    assert "node" not in "\n".join(
        json.dumps(call) for call in _json_lines(Path(environment["FAKE_DOCKER_CALLS"]))
    )

    docker_calls = _json_lines(Path(environment["FAKE_DOCKER_CALLS"]))
    observed_services = {
        call[-1]
        for call in docker_calls
        if isinstance(call, list) and len(call) >= 3 and call[-3:-1] == ["ps", "-q"]
    }
    assert observed_services == {*LONG_RUNNING_SERVICES, "postgres", "minio"}
    sql_calls = _json_lines(Path(environment["FAKE_SQL_CALLS"]))
    assert len(sql_calls) == 2
    assert all(
        isinstance(query, str) and query.lstrip().startswith("SELECT")
        for query in sql_calls
    )
    assert all(
        word not in " ".join(query.split()).upper()
        for query in sql_calls
        for word in ("INSERT ", "UPDATE ", "DELETE ", "ALTER ", "DROP ")
    )
    assert not any(
        command in call
        for call in docker_calls
        if isinstance(call, list)
        for command in ("up", "run", "create", "stop", "restart", "logs")
    )


def test_queued_or_live_work_is_activity_not_failure(
    runtime_fixture: tuple[Path, dict[str, str]],
) -> None:
    result = _run_check(runtime_fixture, FAKE_QUEUE_COUNTS="2|1|0|0")
    assert result.returncode == 0, result.stderr
    assert "queue_state=active queued=2 live_running=1 stale_running=0 ambiguous=0" in (
        result.stdout
    )


@pytest.mark.parametrize(
    ("overrides", "failure"),
    [
        ({"FAKE_SCHEMA_HEAD": "20260908_0044"}, "reason=schema_head_mismatch"),
        ({"FAKE_QUEUE_COUNTS": "0|0|1|0"}, "reason=stale_or_ambiguous"),
        ({"FAKE_QUEUE_COUNTS": "0|0|0|1"}, "reason=stale_or_ambiguous"),
        (
            {"FAKE_SERVICE_FAILURE": "official-account-local-worker:stopped"},
            "reason=not_running_official-account-local-worker",
        ),
        (
            {"FAKE_SERVICE_FAILURE": "wechat-official-account-draft-worker:duplicate"},
            "reason=container_count_wechat-official-account-draft-worker",
        ),
        ({"FAKE_IMAGE_FAILURE": "revision"}, "reason=revision_label_mismatch"),
        ({"FAKE_API_RESPONSE": "not-json"}, "reason=invalid_response"),
    ],
)
def test_material_runtime_failures_are_closed_and_redacted(
    runtime_fixture: tuple[Path, dict[str, str]],
    overrides: dict[str, str],
    failure: str,
) -> None:
    app_dir, _environment = runtime_fixture
    result = _run_check(runtime_fixture, **overrides)
    assert result.returncode == 1
    assert failure in result.stderr
    combined = result.stdout + result.stderr
    assert str(app_dir) not in combined
    assert "APP_ENV" not in combined
    assert "POSTGRES_PASSWORD" not in combined
    assert "provider" not in combined.casefold()
    assert "title" not in combined.casefold()


def test_script_has_no_mutation_or_environment_dump_surface() -> None:
    script = CHECK_SCRIPT.read_text(encoding="utf-8")
    assert "source .env" not in script
    assert "source .release.env" not in script
    assert "docker logs" not in script
    assert "printenv" not in script
    assert "env |" not in script
    assert "mktemp" not in script
    assert "INSERT " not in script
    assert "UPDATE " not in script
    assert "DELETE " not in script
