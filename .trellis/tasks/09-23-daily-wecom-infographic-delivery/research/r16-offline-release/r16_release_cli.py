#!/usr/bin/python3 -I
"""Explicit, single-attempt R16 default-off production release entry point.

This launcher authenticates its source siblings and an independently supplied
manifest hash before importing release code. ``preflight`` does not stop
services. ``apply --execute`` is irreversible after its private intent file;
it never restores the old database or replays an uncertain attempt.
An existing attempt directory, including a crash leaving migration-intent
without release-receipt, is forward-reconcile-only and never retryable.
"""

from __future__ import annotations

import sys

# The launcher lives beside untrusted-until-hashed Python files. Without -I,
# Python can import a sibling named like a standard-library module *before*
# authenticate_bundle() has a chance to reject it.
if __name__ == "__main__" and not sys.flags.isolated:
    sys.stdout.write('{"phase":"blocked","code":"isolated_python_required"}\n')
    raise SystemExit(2)

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, cast

SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_MANIFEST_BYTES = 64 * 1024
ALLOWED_BUNDLE_FILES = {
    "candidate.json",
    "backend-image.oci.tar.gz",
    "r16_forward_operator.py",
    "r16_real_host.py",
    "r16_release_cli.py",
    "r16_enablement.py",
    "r16_enable_host.py",
}
HOST_FILE_DIRS = {"deploy", "deploy/release", "scripts"}
HOST_FILE_FILES = {
    "compose.yaml",
    "deploy/release/migration-compatibility.json",
    "scripts/doctor.sh",
}


class LaunchBlocked(RuntimeError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise LaunchBlocked(code)


def require_isolated() -> None:
    require(
        bool(sys.flags.isolated) and sys.flags.safe_path, "isolated_python_required"
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while part := stream.read(1024 * 1024):
            digest.update(part)
    return digest.hexdigest()


def trusted_path(path: Path, *, directory: bool) -> None:
    """Reject symlink or writable parents; a bundle is root-owned private."""
    require(path.is_absolute() and ".." not in path.parts, "absolute_path_required")
    current = Path("/")
    for part in path.parts[1:]:
        current /= part
        info = current.lstat()
        require(info.st_uid == 0 and not current.is_symlink(), "path_owner_or_link")
        require(stat.S_IMODE(info.st_mode) & 0o022 == 0, "path_writable")
        if current == path:
            require(
                (
                    stat.S_ISDIR(info.st_mode)
                    if directory
                    else stat.S_ISREG(info.st_mode)
                )
                and (directory or info.st_nlink == 1),
                "path_type",
            )
        else:
            require(stat.S_ISDIR(info.st_mode), "path_parent_type")


def strict_json(body: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            require(key not in value, "duplicate_manifest_key")
            value[key] = item
        return value

    try:
        value = json.loads(body, object_pairs_hook=unique)
    except (ValueError, UnicodeDecodeError) as exc:
        raise LaunchBlocked("manifest_json") from exc
    require(isinstance(value, dict), "manifest_shape")
    return cast(dict[str, Any], value)


def authenticate_bundle(
    launcher: Path,
    bundle: Path,
    manifest_path: Path,
    manifest_sha256: str,
    launcher_sha256: str,
) -> dict[str, Any]:
    """No application module import before these external hash pins pass."""
    require(SHA.fullmatch(manifest_sha256) is not None, "manifest_hash_shape")
    require(SHA.fullmatch(launcher_sha256) is not None, "launcher_hash_shape")
    require(launcher.parent == bundle, "launcher_not_in_bundle")
    require(manifest_path == bundle / "candidate.json", "manifest_not_in_bundle")
    trusted_path(bundle, directory=True)
    require(stat.S_IMODE(bundle.stat().st_mode) == 0o700, "bundle_not_private")
    for path in (launcher, manifest_path, bundle / "backend-image.oci.tar.gz"):
        trusted_path(path, directory=False)
    require(
        stat.S_IMODE(manifest_path.stat().st_mode) == 0o600,
        "manifest_not_private",
    )
    require(file_sha256(launcher) == launcher_sha256, "launcher_hash_mismatch")
    info = manifest_path.stat()
    require(0 < info.st_size <= MAX_MANIFEST_BYTES, "manifest_size")
    body = manifest_path.read_bytes()
    require(
        hashlib.sha256(body).hexdigest() == manifest_sha256, "manifest_hash_mismatch"
    )
    manifest = strict_json(body)
    for name, key in (
        ("r16_forward_operator.py", "operator_sha256"),
        ("r16_real_host.py", "real_host_sha256"),
        ("r16_release_cli.py", "release_cli_sha256"),
        ("r16_enablement.py", "enable_operator_sha256"),
        ("r16_enable_host.py", "enable_host_sha256"),
    ):
        path = bundle / name
        trusted_path(path, directory=False)
        expected = manifest.get(key)
        require(
            isinstance(expected, str)
            and SHA.fullmatch(expected) is not None
            and file_sha256(path) == expected,
            "source_hash_mismatch",
        )
    require(manifest["release_cli_sha256"] == launcher_sha256, "launcher_not_pinned")
    # No unreviewed Python sibling may shadow a standard-library import.
    require(
        {item.name for item in bundle.iterdir()}
        == ALLOWED_BUNDLE_FILES | {"host-files"},
        "unreviewed_bundle_entry",
    )
    host_files = bundle / "host-files"
    trusted_path(host_files, directory=True)
    require(stat.S_IMODE(host_files.stat().st_mode) == 0o700, "host_files_not_private")
    observed = {
        item.relative_to(host_files).as_posix(): item for item in host_files.rglob("*")
    }
    require(
        set(observed) == HOST_FILE_DIRS | HOST_FILE_FILES,
        "unreviewed_host_file_entry",
    )
    for name, path in observed.items():
        trusted_path(path, directory=name in HOST_FILE_DIRS)
    return manifest


def confirmations(args: argparse.Namespace, manifest: dict[str, Any]) -> None:
    require(args.execute is True, "explicit_execute_required")
    require(
        args.confirm_revision == manifest.get("revision")
        and args.confirm_image == manifest.get("image")
        and args.confirm_recipient_fingerprint
        == manifest.get("trusted_recipient_fingerprint")
        and args.confirm_base_revision == manifest.get("base_revision")
        and args.confirm_schema == manifest.get("schema")
        and args.confirm_default_off == "DEFAULT_OFF_12_SERVICES",
        "typed_confirmation_mismatch",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "apply"))
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--launcher-sha256", required=True)
    parser.add_argument("--attempt-dir", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-revision")
    parser.add_argument("--confirm-image")
    parser.add_argument("--confirm-recipient-fingerprint")
    parser.add_argument("--confirm-base-revision")
    parser.add_argument("--confirm-schema")
    parser.add_argument("--confirm-default-off")
    args = parser.parse_args()
    release_blocked_type: type[Exception] | None = None
    try:
        require_isolated()
        require(os.geteuid() == 0, "root_required")
        require(not args.attempt_dir.exists(), "attempt_exists_reconcile_only")
        launcher = Path(__file__).absolute()
        manifest = authenticate_bundle(
            launcher,
            args.bundle,
            args.manifest,
            args.manifest_sha256,
            args.launcher_sha256,
        )
        if args.action == "apply":
            confirmations(args, manifest)
        else:
            require(not args.execute, "preflight_cannot_execute")
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(args.bundle))
        from r16_forward_operator import (
            APPROVED_RECIPIENT_FINGERPRINT,
            ReleaseBlocked,
            apply_release,
            canonical,
            sha,
            two_local_locks,
            valid_baseline,
            valid_production_manifest,
        )
        from r16_real_host import (
            APP,
            BACKUP_ROOT,
            HostPaths,
            RealHostAdapter,
            SubprocessRunner,
        )

        release_blocked_type = ReleaseBlocked

        valid_production_manifest(manifest)
        require(
            args.attempt_dir.is_absolute() and args.attempt_dir.parent == BACKUP_ROOT,
            "attempt_root",
        )
        host = RealHostAdapter(
            SubprocessRunner(),
            HostPaths(app=APP, backup_root=BACKUP_ROOT),
            args.attempt_dir,
            manifest,
            args.bundle,
            trusted_recipient_fingerprint=manifest["trusted_recipient_fingerprint"],
            trusted_recipient_key_sha256=manifest["trusted_recipient_key_sha256"],
        )
        locks = (
            Path("/var/lock/edu-ai-deploy.lock"),
            Path("/var/lock/edu-ai-backup.lock"),
        )
        if args.action == "preflight":
            with two_local_locks(locks):
                require(not args.attempt_dir.exists(), "attempt_exists_reconcile_only")
                baseline = host.capture()
                valid_baseline(baseline)
                require(
                    baseline["recipient_fingerprint"] == APPROVED_RECIPIENT_FINGERPRINT,
                    "approved_recipient_mismatch",
                )
            result = {
                "phase": "preflight_only",
                "candidate": manifest["image"],
                "revision": manifest["revision"],
                "baseline_sha256": sha(canonical(baseline)),
                "recipient_fingerprint": APPROVED_RECIPIENT_FINGERPRINT,
                "default_off": True,
                "production_mutation": False,
                "clone_and_backup_pending": True,
            }
        else:
            result = apply_release(
                host,
                manifest,
                args.manifest_sha256,
                args.attempt_dir,
                locks,
            )
    except Exception as exc:  # noqa: BLE001 - redact all unexpected host errors
        # Never serialize command output, shell arguments, environment or URLs.
        known = isinstance(exc, LaunchBlocked) or (
            release_blocked_type is not None and isinstance(exc, release_blocked_type)
        )
        code = str(exc) if known else "release_error"
        if re.fullmatch(r"[a-z][a-z0-9_]*", code) is None:
            code = "release_error"
        print(json.dumps({"phase": "blocked", "code": code}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
