"""Approved six-service admin release; run on host as root after final gates and image smoke."""

import ctypes
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path("/opt/edu-ai-lead-agent")
STAGE = Path(__file__).resolve().parent
BASE = "sha256:24e967081b2e9b303a1f295e7e99eacd24ed96304d5cbb5bd3645270fe159249"
CANDIDATE = json.loads((STAGE / "candidate.json").read_text())
NEW = CANDIDATE["image"]
assert NEW.startswith("sha256:") and len(NEW) == 71 and NEW != BASE
STAMP = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
BACKUP = Path("/var/backups/edu-ai") / ("admin-history-" + STAMP)
BACKUP.mkdir(mode=0o700)
SERVICES = [
    "acquisition-api",
    "acquisition-worker",
    "content-scheduler",
    "content-worker",
    "wecom-infographic-producer",
    "wecom-dispatcher",
]
NAMES = ["edu-ai-lead-agent-" + s + "-1" for s in SERVICES]
PG = "edu-ai-lead-agent-postgres-1"
COMPOSE = [
    "docker",
    "compose",
    "-p",
    "edu-ai-lead-agent",
    "--env-file",
    ".env",
    "--env-file",
    ".release.env",
]
WEB = Path("/var/www/edu-ai-admin")
SWAP = Path("/var/www/edu-ai-admin.install-" + STAMP)
OLD_WEB = Path("/var/www/edu-ai-admin.before-" + STAMP)
stopped = installed = replaced = False
old_web_location = OLD_WEB


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save(name, value):
    path = BACKUP / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


def announce(name, value):
    print(name, json.dumps(value, ensure_ascii=False), flush=True)


def run(args, *, stdin=None, label="command", timeout=180):
    result = subprocess.run(
        args,
        input=stdin,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=timeout,
        check=False,
    )
    # Container and image inspection can both include environment data.
    # Keep only the allowlisted fields explicitly projected into release receipts.
    if args[:2] != ["docker", "inspect"] and args[:3] != ["docker", "image", "inspect"]:
        path = BACKUP / (label + ".log")
        path.write_text(result.stdout + "\n" + result.stderr)
        path.chmod(0o600)
    if result.returncode:
        raise RuntimeError(label + " failed; inspect root-only log")
    return result.stdout


def inspect(names):
    return json.loads(run(["docker", "inspect", *names], label="inspect"))


def db():
    queries = {
        "schema": "SELECT version_num FROM alembic_version",
        "acquisition_running": "SELECT count(*) FROM acquisition_jobs WHERE status='running'",
        "slots_active": "SELECT count(*) FROM content_slot_jobs WHERE status IN ('queued','running')",
        "copy_running": "SELECT count(*) FROM copy_generation_jobs WHERE status='running'",
        "infographic_active": "SELECT count(*) FROM news_infographic_jobs WHERE status IN ('queued','running')",
        "delivery_running": "SELECT count(*) FROM wecom_delivery_jobs WHERE status='running'",
        "sources_enabled": "SELECT count(*) FROM sources WHERE enabled",
        "seeds_enabled": "SELECT count(*) FROM sources WHERE enabled AND managed_by='seed'",
        "stored_model_keys": "SELECT count(*) FROM model_api_keys",
        "wechat_accounts": "SELECT count(*) FROM wechat_accounts",
        "publish_jobs": "SELECT count(*) FROM wechat_publish_jobs",
        "open_publish_jobs": "SELECT count(*) FROM wechat_publish_jobs WHERE status IN ('scheduled','submitting','publishing','outcome_unknown')",
        "occupied_conflicts": "SELECT count(*) FROM (SELECT 1 FROM wechat_publish_jobs WHERE status IN ('scheduled','submitting','publishing','outcome_unknown','succeeded') GROUP BY account_id,media_id HAVING count(*)>1) AS conflicts",
    }
    sql = (
        "BEGIN READ ONLY;\n"
        + "\n".join(query + ";" for query in queries.values())
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
            label="database",
            timeout=45,
        )
        .strip()
        .splitlines()
    )
    assert len(output) == len(queries), "Unexpected database result"
    return {
        key: value if key == "schema" else int(value)
        for key, value in zip(queries, output)
    }


def idle(counts):
    assert all(
        counts[key] == 0
        for key in [
            "acquisition_running",
            "slots_active",
            "copy_running",
            "infographic_active",
            "delivery_running",
            "open_publish_jobs",
            "occupied_conflicts",
        ]
    ), "Jobs active/conflicting: no cutover"


def atomic_release(content):
    tmp = ROOT / (".release.env.install-" + STAMP)
    tmp.write_text(content)
    tmp.chmod(0o600)
    os.replace(tmp, ROOT / ".release.env")


def exchange_directories(left, right):
    """Atomically exchange two directories on the same Linux filesystem."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise RuntimeError("Atomic directory exchange is unavailable")
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    # AT_FDCWD; RENAME_EXCHANGE. Neither live path is absent during the swap.
    if rename(-100, os.fsencode(left), -100, os.fsencode(right), 2) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def verify_directory_exchange(parent):
    # Test the actual target filesystem before stopping a service or replacing assets.
    with tempfile.TemporaryDirectory(
        prefix=".admin-exchange-probe-", dir=parent
    ) as temporary:
        left, right = Path(temporary) / "left", Path(temporary) / "right"
        left.mkdir()
        right.mkdir()
        (left / "identity").write_text("left")
        (right / "identity").write_text("right")
        exchange_directories(left, right)
        assert (left / "identity").read_text() == "right"
        assert (right / "identity").read_text() == "left"


def rollback_publication_count():
    # Row JSON works both before and after 0060 adds reconciled_by. Never downgrade
    # or restart the old publisher when it cannot explain newly recorded provenance.
    sql = "BEGIN READ ONLY; SELECT count(*) FROM wechat_publish_jobs j WHERE status='outcome_unknown' OR to_jsonb(j)->>'reconciled_by' IS NOT NULL; ROLLBACK;"
    output = run(
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
        label="rollback-publication-check",
        timeout=45,
    )
    return int(output.strip())


def health(expected, names=NAMES):
    for _ in range(36):
        current = inspect(names)
        ready = all(
            x["Image"] == expected and x["State"]["Running"] and x["RestartCount"] == 0
            for x in current
        )
        if NAMES[0] in names:
            ready = (
                ready
                and next(x for x in current if x["Name"].lstrip("/") == NAMES[0])[
                    "State"
                ]
                .get("Health", {})
                .get("Status")
                == "healthy"
            )
        if ready:
            return current
        time.sleep(3)
    raise RuntimeError("Service health timed out")


try:
    now = datetime.datetime.now(ZoneInfo("Asia/Shanghai"))
    minute = now.hour * 60 + now.minute
    assert not any(
        start <= minute < end for start, end in [(360, 510), (660, 810), (1020, 1170)]
    ), "Inside push window"
    preflight = json.loads((STAGE / "preflight-state.json").read_text())
    assert all(
        sha(ROOT / name) == expected
        for name, expected in preflight["config_hashes"].items()
    ), "Config drift"
    before = inspect(list(preflight["containers"]))
    for item in before:
        name = item["Name"].lstrip("/")
        previous = preflight["containers"][name]
        assert item["Id"] == previous["id"] and item["Image"] == previous["image"], (
            "Container drift: " + name
        )
        if name in NAMES:
            assert item["Image"] == BASE and item["State"]["Running"]
    # The freshly smoked image and staged frontend must match their recorded identities.
    assert json.loads(run(["docker", "image", "inspect", NEW]))[0]["Id"] == NEW
    for name, expected in CANDIDATE["frontend"].items():
        assert sha(STAGE / "dist-admin" / name) == expected, "Frontend staging mismatch"
    verify_directory_exchange(WEB.parent)
    manifest = {}
    for line in (STAGE / "files.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            name, old, _ = [x.strip() for x in line.split("|")]
            manifest[name] = old
    code = (
        "import hashlib,json\nfrom pathlib import Path\nm="
        + repr(manifest)
        + "\na={n:hashlib.sha256((Path('/app')/n).read_bytes()).hexdigest() if (Path('/app')/n).is_file() else 'absent' for n in m}\nassert a==m,'Base source drift'\nprint('base verified')"
    )
    run(
        ["docker", "exec", "-i", NAMES[0], "python", "-"],
        stdin=code,
        label="base-hashes",
    )
    counts = db()
    idle(counts)
    assert counts["schema"] == "20261009_0059"
    for name in [".env", ".release.env", "compose.yaml"]:
        shutil.copy2(ROOT / name, BACKUP / name)
        (BACKUP / name).chmod(0o600)
    shutil.copytree(WEB, BACKUP / "frontend")
    save(
        "before.json",
        {
            "at": now.isoformat(),
            "counts": counts,
            "containers": preflight["containers"],
            "config_hashes": preflight["config_hashes"],
        },
    )
    shutil.copytree(STAGE / "dist-admin", SWAP)
    stopped = True
    run(COMPOSE + ["stop", "--timeout", "60", *SERVICES], label="stop-six", timeout=180)
    assert all(not x["State"]["Running"] for x in inspect(NAMES)), (
        "Target service still running"
    )
    frozen = db()
    idle(frozen)
    assert frozen["schema"] == "20261009_0059"
    for key in [
        "sources_enabled",
        "seeds_enabled",
        "stored_model_keys",
        "wechat_accounts",
        "publish_jobs",
    ]:
        assert frozen[key] == counts[key], "Business state changed before backup"
    dump = BACKUP / "database.dump"
    with dump.open("wb") as output, (BACKUP / "pg-dump.log").open("wb") as error:
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
            stderr=error,
            timeout=240,
            check=False,
        )
    dump.chmod(0o600)
    assert result.returncode == 0 and dump.stat().st_size > 1000, "Backup failed"
    with dump.open("rb") as source:
        checked = subprocess.run(
            ["docker", "exec", "-i", PG, "pg_restore", "--list"],
            stdin=source,
            capture_output=True,
            timeout=60,
            check=False,
        )
    assert checked.returncode == 0 and b"TABLE DATA" in checked.stdout, (
        "Backup listing failed"
    )
    (BACKUP / "database.list").write_bytes(checked.stdout)
    (BACKUP / "database.list").chmod(0o600)
    save(
        "backup.json",
        {"sha256": sha(dump), "bytes": dump.stat().st_size, "quiescent_counts": frozen},
    )
    idle(db())
    announce(
        "BACKUP_VERIFIED",
        {"path": str(BACKUP), "bytes": dump.stat().st_size, "schema": frozen["schema"]},
    )
    text = (BACKUP / ".release.env").read_text().splitlines()
    assert sum(x.startswith("APP_IMAGE=") for x in text) == 1
    atomic_release(
        "\n".join(
            "APP_IMAGE=offline.local/edu-ai/edu-ai-lead-agent-backend@" + NEW
            if x.startswith("APP_IMAGE=")
            else x
            for x in text
        )
        + "\n"
    )
    installed = True
    run(
        COMPOSE + ["--profile", "*", "config", "--quiet"],
        label="compose-check",
        timeout=30,
    )
    run(
        COMPOSE + ["run", "--rm", "--no-deps", "-T", "backend-migrate"],
        label="migration",
        timeout=240,
    )
    migrated = db()
    assert migrated["schema"] == "20261010_0061"
    idle(migrated)
    for key in [
        "sources_enabled",
        "seeds_enabled",
        "stored_model_keys",
        "wechat_accounts",
        "publish_jobs",
    ]:
        assert migrated[key] == frozen[key], "Migration changed business counts"
    run(
        COMPOSE + ["up", "-d", "--no-deps", "--no-build", "--pull", "never", *SERVICES],
        label="recreate-six",
        timeout=240,
    )
    current = health(NEW)
    untouched = [name for name in preflight["containers"] if name not in NAMES]
    for item in inspect(untouched):
        name = item["Name"].lstrip("/")
        old = preflight["containers"][name]
        assert item["Id"] == old["id"] and item["Image"] == old["image"], (
            "Unexpected non-target change"
        )
    for name in [".env", "compose.yaml"]:
        assert sha(ROOT / name) == preflight["config_hashes"][name], (
            "Unrelated config changed"
        )
    http = {}
    for path, expected in [
        ("/healthz", 200),
        ("/api/v1/admin/auth/me", 401),
        ("/api/v1/admin/models", 401),
        ("/api/v1/admin/wechat/publish-jobs", 401),
        ("/api/v1/admin/accounts", 401),
    ]:
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8000" + path, timeout=10
            ) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        http[path] = status
        assert status == expected, "HTTP check failed"
    exchange_directories(WEB, SWAP)
    replaced = True
    old_web_location = SWAP
    SWAP.rename(OLD_WEB)
    old_web_location = OLD_WEB
    for name, expected in CANDIDATE["frontend"].items():
        assert sha(WEB / name) == expected
    final_counts = db()
    assert final_counts["schema"] == "20261010_0061", "Schema drift after restart"
    for key in [
        "sources_enabled",
        "seeds_enabled",
        "stored_model_keys",
        "wechat_accounts",
        "publish_jobs",
    ]:
        assert final_counts[key] == frozen[key], (
            "Business state changed during cutover: " + key
        )
    assert final_counts["occupied_conflicts"] == 0, (
        "Occupied-draft conflict after restart"
    )
    report = {
        "finished_at": datetime.datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "image": NEW,
        "backup": str(BACKUP),
        "schema": migrated["schema"],
        "counts": final_counts,
        "http": http,
        "services": {
            x["Name"].lstrip("/"): {
                "image": x["Image"],
                "running": x["State"]["Running"],
                "restarts": x["RestartCount"],
            }
            for x in current
        },
        "untouched": untouched,
        "frontend": CANDIDATE["frontend"],
        "previous_frontend": str(OLD_WEB),
    }
    save("cutover-result.json", report)
    announce("CUTOVER_OK", report)
except Exception as exc:
    announce(
        "CUTOVER_FAILED",
        {"type": type(exc).__name__, "message": str(exc), "backup": str(BACKUP)},
    )
    if stopped:
        try:
            run(
                COMPOSE + ["stop", "--timeout", "60", *SERVICES],
                label="rollback-stop-six",
                timeout=180,
            )
            publication_check_error = False
            try:
                unsafe_publications = rollback_publication_count()
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                unsafe_publications = None
                publication_check_error = True
            freeze_publishing = publication_check_error or unsafe_publications != 0
            if installed:
                atomic_release((BACKUP / ".release.env").read_text())
            if replaced:
                exchange_directories(WEB, old_web_location)
                old_web_location.rename(Path("/var/www/edu-ai-admin.failed-" + STAMP))
            rollback_services = SERVICES[1:] if freeze_publishing else SERVICES
            run(
                COMPOSE
                + [
                    "up",
                    "-d",
                    "--no-deps",
                    "--no-build",
                    "--pull",
                    "never",
                    *rollback_services,
                ],
                label="rollback-services",
                timeout=240,
            )
            health(BASE, NAMES[1:] if freeze_publishing else NAMES)
            if freeze_publishing:
                assert not inspect([NAMES[0]])[0]["State"]["Running"], (
                    "Publisher must remain stopped"
                )
                announce(
                    "ROLLBACK_FORWARD_FIX_REQUIRED",
                    {
                        "schema": "additive migrations retained",
                        "backup": str(BACKUP),
                        "publisher": "acquisition-api remains stopped",
                        "unresolved_or_reconciled_jobs": unsafe_publications,
                        "publication_check_failed": publication_check_error,
                    },
                )
            else:
                announce(
                    "ROLLBACK_OK",
                    {"schema": "additive migrations retained", "backup": str(BACKUP)},
                )
        except Exception as rollback:
            announce(
                "ROLLBACK_FAILED",
                {"type": type(rollback).__name__, "message": str(rollback)},
            )
            raise SystemExit(1) from rollback
    raise SystemExit(1) from exc
