"""Install reviewed assets only after the two runtime observations passed."""

import ctypes
import json
import os
import shutil
import tempfile
from pathlib import Path

from common import STAGE, require, save, sha


def hashes(root):
    require(root.is_dir() and not root.is_symlink(), "frontend_directory_invalid")
    result = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "frontend_symlink_invalid")
        if path.is_file():
            result[str(path.relative_to(root))] = sha(path)
        else:
            require(path.is_dir(), "frontend_special_file_invalid")
    return result


def exchange(left, right):
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    require(rename is not None, "atomic_exchange_unavailable")
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
        "atomic_exchange_failed",
    )


def main():
    os.umask(0o077)
    candidate = json.loads((STAGE / "candidate.json").read_text())
    final = json.loads((STAGE / "postcheck-final.json").read_text())
    require(
        final["result"] == "POSTCHECK_PASS_FRONTEND_MAY_FINALIZE",
        "runtime_not_accepted",
    )
    require(
        final["image"] == candidate["image"]
        and final["source_commit"] == candidate["source_commit"],
        "frontend_candidate_mismatch",
    )
    backup = Path(final["backup"])
    require(
        backup.parent == Path("/var/backups/edu-ai") and backup.is_dir(),
        "backup_missing",
    )
    web = Path("/var/www/edu-ai-admin")
    staged = STAGE / "dist-admin"
    require(hashes(staged) == candidate["frontend"], "staged_frontend_mismatch")
    original = hashes(web)
    previous = web.with_name(
        web.name + ".before-" + backup.name.removeprefix("admin-pipeline-")
    )
    require(not previous.exists(), "frontend_backup_path_exists")
    with tempfile.TemporaryDirectory(
        prefix=".pipeline-exchange-", dir=web.parent
    ) as temp:
        left, right = Path(temp) / "left", Path(temp) / "right"
        left.mkdir()
        right.mkdir()
        (left / "identity").write_text("left")
        (right / "identity").write_text("right")
        exchange(left, right)
        require(
            (left / "identity").read_text() == "right"
            and (right / "identity").read_text() == "left",
            "exchange_probe_failed",
        )
    shutil.copytree(web, backup / "frontend")
    require(hashes(backup / "frontend") == original, "frontend_backup_mismatch")
    shutil.copytree(staged, previous)
    for path in [previous, *previous.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    require(hashes(previous) == candidate["frontend"], "prepared_frontend_mismatch")
    require(hashes(web) == original, "live_frontend_changed")
    exchange(web, previous)
    try:
        require(
            hashes(web) == candidate["frontend"] and hashes(previous) == original,
            "installed_frontend_mismatch",
        )
    except Exception:
        exchange(web, previous)
        raise
    result = {
        "result": "FRONTEND_INSTALLED",
        "source_commit": candidate["source_commit"],
        "frontend": candidate["frontend"],
        "previous_frontend": str(previous),
        "backup": str(backup),
        "atomic_exchange": True,
    }
    save(STAGE / "frontend-result.json", result)
    save(backup / "frontend-result.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
