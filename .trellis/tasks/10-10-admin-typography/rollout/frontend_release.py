"""Bounded frontend-only release; never modifies containers or configuration."""

import ctypes
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

STAGE = Path(__file__).resolve().parent
WEB = Path("/var/www/edu-ai-admin")
APP = Path("/opt/edu-ai-lead-agent")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(root):
    require(root.is_dir() and not root.is_symlink(), "invalid asset directory")
    result = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "asset symlink forbidden")
        if path.is_file():
            result[str(path.relative_to(root))] = sha(path)
        else:
            require(path.is_dir(), "special asset file forbidden")
    require("admin/index.html" in result and len(result) >= 3, "missing bundle")
    return result


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def invariant():
    ids = run(
        "docker",
        "ps",
        "-aq",
        "--filter",
        "label=com.docker.compose.project=edu-ai-lead-agent",
    ).splitlines()
    require(len(ids) == 16, "unexpected project container count")
    # Select only nonsecret fields; never capture raw inspect or environment values.
    fmt = "|".join(
        "{{json ." + field + "}}"
        for field in ["Id", "Name", "Image", "RestartCount", "State.StartedAt"]
    )
    lines = run("docker", "inspect", "--format", fmt, *ids).splitlines()
    containers = sorted(
        [json.loads(part) for part in line.split("|")] for line in lines
    )
    configs = {
        name: sha(APP / name) for name in [".env", ".release.env", "compose.yaml"]
    }
    return {"containers": containers, "configuration_hashes": configs}


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def exchange(left, right):
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    require(
        rename(-100, os.fsencode(left), -100, os.fsencode(right), 2) == 0,
        "atomic exchange failed",
    )


def install():
    baseline = json.loads((STAGE / "baseline.json").read_text())
    candidate = json.loads((STAGE / "candidate.json").read_text())
    require(candidate["gate"].startswith("predeploy gate PASS @ "), "gate missing")
    require(candidate["source_commit"][:7] in candidate["gate"], "gate source mismatch")
    require(hashes(WEB) == baseline["frontend"], "live frontend changed")
    require(invariant() == baseline["invariant"], "backend/configuration changed")
    require(hashes(STAGE / "dist-admin") == candidate["frontend"], "candidate changed")
    suffix = STAGE.name.removeprefix("edu-admin-typography-")
    require(suffix != STAGE.name and suffix.isalnum(), "unexpected stage name")
    backup = Path("/var/backups/edu-ai") / ("admin-typography-" + suffix)
    previous = WEB.with_name(WEB.name + ".before-" + suffix)
    require(not backup.exists() and not previous.exists(), "backup path exists")
    backup.mkdir(mode=0o700)
    shutil.copytree(WEB, backup / "frontend")
    require(hashes(backup / "frontend") == baseline["frontend"], "backup mismatch")
    save(backup / "baseline.json", baseline)
    shutil.copytree(STAGE / "dist-admin", previous)
    for path in [previous, *previous.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    require(hashes(previous) == candidate["frontend"], "prepared assets changed")
    require(
        hashes(WEB) == baseline["frontend"], "live assets changed during preparation"
    )
    require(invariant() == baseline["invariant"], "runtime changed during preparation")
    exchange(WEB, previous)
    try:
        require(hashes(WEB) == candidate["frontend"], "installed assets mismatch")
        require(hashes(previous) == baseline["frontend"], "previous assets mismatch")
        require(invariant() == baseline["invariant"], "backend/configuration changed")
    except Exception:
        exchange(WEB, previous)
        raise
    receipt = {
        "result": "FRONTEND_INSTALLED",
        "source_commit": candidate["source_commit"],
        "frontend": candidate["frontend"],
        "backup": str(backup),
        "previous_frontend": str(previous),
        "atomic_exchange": True,
        "backend_configuration_unchanged": True,
        "container_count": 16,
    }
    save(STAGE / "frontend-result.json", receipt)
    save(backup / "frontend-result.json", receipt)
    print(json.dumps(receipt))


def main():
    os.umask(0o077)
    require(
        len(sys.argv) == 2 and sys.argv[1] in {"baseline", "install"}, "invalid mode"
    )
    with Path("/var/lock/edu-ai-admin-assets.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if sys.argv[1] == "baseline":
            require(not (STAGE / "baseline.json").exists(), "baseline already exists")
            value = {"frontend": hashes(WEB), "invariant": invariant()}
            save(STAGE / "baseline.json", value)
            print(
                json.dumps(
                    {
                        "result": "BASELINE_RECORDED",
                        "frontend": value["frontend"],
                        "container_count": len(value["invariant"]["containers"]),
                    }
                )
            )
        else:
            install()


if __name__ == "__main__":
    main()
