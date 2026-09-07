#!/usr/bin/env python3
"""September 7 source-preflight incident release; never a generic deployer.

The older incident validator is a checksum-pinned *pure library*. Its .12 configuration,
baseline, dated authority, and operator functions are deliberately never invoked.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, BinaryIO, cast

sys.dont_write_bytecode = True
BASE = "5c560da71bcbb61b765d3fe82c742cf2d5e676e1"
OLD_IMAGE = (
    "edu-ai-lead-agent-backend@"
    "sha256:35e4405a5dfa06e70a45c360d8838021e00c05938ac7f7e818378c6454d48454"
)
HEAD = "20260901_0042"
REF = "refs/heads/release/weekly-source-preflight-20260907"
REMOTE_REF = "refs/remotes/origin/release/weekly-source-preflight-20260907"
SOURCE_URL = (
    "https://codeup.aliyun.com/601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git"
)
LIB_COMMIT = "f406f6bbdb439b9c699481013172944f9ba58852"
TASK = ".trellis/tasks/09-05-production-recovery-qwen-embedding"
SELF_PATH = TASK + "/research/weekly-release/weekly_release.py"
LIB_PATH = TASK + "/research/substantive-release/validate-substantive-release.py"
LIB_SHA = "3204ae61775e9d761abcbc0b1ec3b8644431096e60ac746b5d7e8e51e5cc1334"
SOURCE_ROOTS = (
    "backend",
    "deploy",
    "infra",
    "scripts",
    "compose.yaml",
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "Makefile",
    "README.md",
    "environment.yml",
)
RUNTIME = frozenset(
    {
        "backend/app/application/services/official_account_weekly_production.py",
        "backend/app/infrastructure/db/official_account_weekly_production.py",
        "compose.yaml",
    }
)
AUDIT = frozenset(
    {
        "backend/tests/unit/test_official_account_weekly_production.py",
        "backend/tests/unit/test_official_account_weekly_material_preflight.py",
        "backend/tests/integration/test_official_account_weekly_production_preflight.py",
        "backend/tests/unit/test_weekly_draft_inbox_contract.py",
        ".trellis/spec/backend/weekly-production-source-preflight.md",
        ".trellis/spec/backend/index.md",
    }
)
APP = Path("/opt/edu-ai-lead-agent")
BACKUPS = Path("/opt/edu-ai-release-backups")
PROFILES = (
    "governance",
    "content",
    "wecom",
    "official-account-weekly-dag",
    "official-account-local",
    "wechat-official-account-draft",
)
PROTECTED = (".env", ".release.env", ".release-commit", "RELEASE_COMMIT")
SAFE_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LC_ALL": "C",
}
MEMBERS = frozenset(
    {
        "base-compose.yaml",
        "weekly_release.py",
        "pure_validator.py",
        "release.json",
        "source.tar.gz",
        "source-manifest.tsv",
        "base-source.json",
        "image-source.sha256",
        "backend-image.oci.tar.gz",
        "checksums.json",
    }
)


class ReleaseError(RuntimeError):
    """Only stable locally-authored issue codes cross the CLI boundary."""


def require(condition: object, code: str) -> None:
    if not condition:
        raise ReleaseError(code)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def log(phase: str, **facts: object) -> None:
    print(canonical({"phase": phase, **facts}).decode(), flush=True)


def run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    input_bytes: bytes | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 180,
    stdout: BinaryIO | None = None,
) -> bytes:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=env or SAFE_ENV,
            input=input_bytes,
            stdin=subprocess.DEVNULL if input_bytes is None else None,
            stdout=stdout or subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseError("command_unavailable_or_timeout") from exc
    if result.returncode:
        log(
            "command_failed",
            returncode=result.returncode,
            stderr_bytes=len(result.stderr),
            stderr_sha256=digest(result.stderr),
        )
        raise ReleaseError("command_failed")
    return result.stdout or b""


def no_clobber(path: Path, value: bytes) -> None:
    require(
        path.is_absolute() and path.parent.resolve() == path.parent,
        "output_path_invalid",
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def load_lib(path: Path) -> ModuleType:
    require(path.is_file() and not path.is_symlink(), "validator_missing")
    require(digest(path.read_bytes()) == LIB_SHA, "validator_checksum_drift")
    spec = importlib.util.spec_from_file_location("weekly_pure_validator", path)
    require(spec and spec.loader, "validator_import_unavailable")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path, lib: ModuleType) -> Any:
    raw, _ = lib.stable_read_regular(path, max_bytes=16 * 1024 * 1024)
    return lib.strict_json(raw, "release evidence")


def window(cutoff: str, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    require(re.fullmatch(r"2026-09-07T\d{2}:\d{2}:\d{2}Z", cutoff), "cutoff_invalid")
    boundary = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    require(
        boundary <= datetime(2026, 9, 7, 3, 0, tzinfo=UTC),
        "cutoff_after_writer_schedule",
    )
    require(
        datetime(2026, 9, 7, 1, 0, tzinfo=UTC) <= now < boundary - timedelta(minutes=15),
        "release_window_closed",
    )


def git(repo: Path, *args: str) -> bytes:
    # Authentication stays in the existing SSH agent/config; no ambient Git overrides.
    env = {
        **SAFE_ENV,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/false",
        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10",
    }
    for key in ("HOME", "SSH_AUTH_SOCK"):
        if key in os.environ:
            env[key] = os.environ[key]
    return run(["git", "-C", str(repo), *args], env=env)


def committed_source(repo: Path, commit: str) -> dict[str, tuple[int, bytes]]:
    raw = git(repo, "ls-tree", "-rz", commit, "--", *SOURCE_ROOTS)
    rows: dict[str, tuple[int, bytes]] = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        metadata, name_bytes = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.split()
        name = name_bytes.decode("ascii")
        require(
            re.fullmatch(r"[A-Za-z0-9._/-]+", name) and ".." not in name.split("/"),
            "source_path_invalid",
        )
        require(mode in {b"100644", b"100755"} and kind == b"blob", "source_type_invalid")
        rows[name] = (
            0o755 if mode == b"100755" else 0o644,
            git(repo, "cat-file", "blob", object_id.decode()),
        )
    require(
        rows
        and all(any(n == root or n.startswith(root + "/") for n in rows) for root in SOURCE_ROOTS),
        "source_root_missing",
    )
    return rows


def allowed_diff(repo: Path, commit: str) -> None:
    git(repo, "merge-base", "--is-ancestor", BASE, commit)
    changed = git(repo, "diff", "--name-status", "--no-renames", BASE, commit).decode().splitlines()
    runtime: set[str] = set()
    seen: set[str] = set()
    for entry in changed:
        status_code, name = entry.split("\t")
        require(name not in seen, "unreviewed_diff")
        seen.add(name)
        if name in RUNTIME:
            require(status_code == "M", "runtime_type_drift")
            runtime.add(name)
        else:
            require(
                status_code in {"A", "M"} and (name in AUDIT or name.startswith(TASK + "/")),
                "unreviewed_diff",
            )
    require(runtime == RUNTIME, "runtime_diff_incomplete")


def validate_compose_change(previous: bytes, candidate: bytes) -> None:
    old = b"      WECHAT_MP_DRAFT_WEEKLY_INBOX_ROOT: /app/input/weekly-inbox\n"
    new = (
        b"      WECHAT_MP_DRAFT_WEEKLY_INBOX_ROOT: "
        b"/app/input/official-account-weekly-editions/weekly-inbox\n"
    )
    require(
        previous.count(old) == 1 and candidate == previous.replace(old, new),
        "compose_change_outside_inbox_path",
    )


def write_source(stage: Path, rows: dict[str, tuple[int, bytes]]) -> None:
    manifest: dict[str, tuple[str, int, str]] = {}
    for name, (mode, value) in rows.items():
        manifest[name] = ("f", mode, digest(value))
        for parent in Path(name).parents:
            if str(parent) != ".":
                manifest[str(parent)] = ("d", 0o755, "-")
    with (
        (stage / "source.tar.gz").open("xb") as target,
        gzip.GzipFile(fileobj=target, mode="wb", mtime=0, filename="") as compressed,
        tarfile.open(fileobj=compressed, mode="w|") as archive,
    ):
        for name in sorted(manifest):
            kind, mode, _ = manifest[name]
            info = tarfile.TarInfo(name)
            info.mode = mode
            info.type = tarfile.DIRTYPE if kind == "d" else tarfile.REGTYPE
            value = b"" if kind == "d" else rows[name][1]
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value) if kind == "f" else None)
    no_clobber(
        stage / "source-manifest.tsv",
        "".join(
            f"{kind}\t{mode:04o}\t{checksum}\t{name}\n"
            for name, (kind, mode, checksum) in sorted(manifest.items())
        ).encode(),
    )


IMAGE_PROBE = """import hashlib,pathlib,re
root=pathlib.Path('/app')
names=['alembic.ini','pyproject.toml']
for dirname in ('app','alembic'):
    folder=root/dirname
    assert folder.is_dir() and not folder.is_symlink()
    for path in folder.rglob('*'):
        assert not path.is_symlink()
        if path.is_file() and path.suffix in ('.py','.html'):
            names.append(path.relative_to(root).as_posix())
assert len(names)==len(set(names))
for name in sorted(names):
    assert re.fullmatch('[A-Za-z0-9._/-]+',name) and '..' not in name.split('/')
    path=root/name
    assert path.is_file() and not path.is_symlink()
    print(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+name)
"""


def docker(*args: str, timeout: int = 180) -> bytes:
    return run(["docker", *args], timeout=timeout)


def inspect_image(reference: str) -> dict[str, Any]:
    value = json.loads(docker("image", "inspect", reference))
    require(isinstance(value, list) and len(value) == 1, "image_ambiguous")
    return cast(dict[str, Any], value[0])


def probe_image(stage: Path, metadata: dict[str, Any], lib: ModuleType) -> str:
    reference = metadata["candidate_reference"]
    actual = inspect_image(metadata["transport_tag"])
    require(
        actual["Id"] in {reference.split("@")[1], metadata["candidate_config_digest"]},
        "loaded_image_identity_drift",
    )
    require(
        reference in actual.get("RepoDigests", [])
        and inspect_image(reference)["Id"] == actual["Id"],
        "loaded_digest_drift",
    )
    config = actual["Config"]
    require(
        config["User"] == "app"
        and config["Labels"]["org.opencontainers.image.revision"] == metadata["release_commit"]
        and config["Labels"]["org.opencontainers.image.source"] == SOURCE_URL,
        "image_labels_drift",
    )
    require(
        config["Labels"].get("org.opencontainers.image.created") == metadata["created"],
        "image_created_drift",
    )
    prefix = [
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        "512m",
        "--cpus",
        "1",
    ]
    source = docker(*prefix, "--entrypoint", "python", reference, "-B", "-c", IMAGE_PROBE)
    require(source == (stage / "image-source.sha256").read_bytes(), "image_source_drift")
    modules = ["app.api_main"] + [
        command[2] for name, command in lib.SERVICE_COMMANDS.items() if name != "acquisition-api"
    ]
    require(len(modules) == 12 and len(set(modules)) == 12, "entrypoint_count_drift")
    docker(
        *prefix,
        "--entrypoint",
        "python",
        reference,
        "-B",
        "-c",
        "import " + ",".join(modules),
    )
    docker(*prefix, "--entrypoint", "python", reference, "-m", "pip", "check")
    require(
        docker(*prefix, "--entrypoint", "alembic", reference, "-c", "alembic.ini", "heads").strip()
        == (HEAD + " (head)").encode(),
        "image_alembic_drift",
    )
    return str(actual["Id"])


def build(args: argparse.Namespace) -> None:
    repo = args.repo.resolve(strict=True)
    common = Path(git(repo, "rev-parse", "--git-common-dir").decode().strip())
    if not common.is_absolute():
        common = repo / common
    common = common.resolve(strict=True)
    descriptor = os.open(
        common / "weekly-release-build.lock",
        os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(descriptor, "w"):
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        build_locked(args)


def build_locked(args: argparse.Namespace) -> None:
    window(args.cutoff)
    repo = args.repo.resolve(strict=True)
    commit = args.commit
    require(re.fullmatch(r"[0-9a-f]{40}", commit) and commit != BASE, "commit_invalid")
    remote = git(repo, "remote", "get-url", "origin").decode().strip()
    alias = "git@codeup-edu-ai:601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git"
    require(
        remote
        in {
            SOURCE_URL,
            SOURCE_URL.replace("https://codeup.aliyun.com/", "git@codeup.aliyun.com:"),
            alias,
        },
        "origin_authority_invalid",
    )
    if remote == alias:
        config = run(["ssh", "-G", "codeup-edu-ai"]).decode().splitlines()
        require(
            {"hostname codeup.aliyun.com", "user git", "port 22"}.issubset(config),
            "ssh_alias_drift",
        )
    git(repo, "fetch", "--no-tags", "origin", f"{REF}:{REMOTE_REF}")
    require(
        git(repo, "rev-parse", REMOTE_REF).decode().strip() == commit,
        "fetched_ref_drift",
    )
    require(
        git(repo, "show", f"{commit}:{SELF_PATH}") == Path(__file__).read_bytes(),
        "builder_not_committed",
    )
    allowed_diff(repo, commit)
    stage = args.output.absolute()
    require(
        stage.parent.resolve() == stage.parent and not stage.exists(),
        "stage_not_absent",
    )
    stage.mkdir(mode=0o700)
    no_clobber(stage / "weekly_release.py", Path(__file__).read_bytes())
    no_clobber(stage / "pure_validator.py", git(repo, "show", f"{LIB_COMMIT}:{LIB_PATH}"))
    lib = load_lib(stage / "pure_validator.py")
    baseline = committed_source(repo, BASE)
    rows = committed_source(repo, commit)
    validate_compose_change(baseline["compose.yaml"][1], rows["compose.yaml"][1])
    no_clobber(stage / "base-compose.yaml", baseline["compose.yaml"][1])
    write_source(stage, rows)
    no_clobber(
        stage / "base-source.json",
        canonical(
            {
                name: {"mode": mode, "sha256": digest(value)}
                for name, (mode, value) in baseline.items()
            }
        ),
    )
    projected = lib.validate_source_archive(stage)
    no_clobber(
        stage / "image-source.sha256",
        "".join(f"{sha}  {name}\n" for name, sha in sorted(projected.items())).encode(),
    )
    context = docker("context", "show").decode().strip()
    require(
        docker("context", "inspect", "--format", "{{.Endpoints.docker.Host}}", context).strip()
        == b"unix:///var/run/docker.sock",
        "nonlocal_docker",
    )
    require(
        docker("version", "--format", "{{.Client.Version}} {{.Server.Version}}").strip()
        == b"29.1.3 29.1.3",
        "legacy_docker_version_drift",
    )
    require(
        docker("info", "--format", "{{.OSType}}/{{.Architecture}}").strip() == b"linux/x86_64",
        "docker_platform_drift",
    )
    require(
        ["driver-type", "io.containerd.snapshotter.v1"]
        in json.loads(docker("info", "--format", "{{json .DriverStatus}}")),
        "snapshotter_drift",
    )
    socket = Path("/run/containerd/containerd.sock")
    require(
        stat.S_ISSOCK(socket.lstat().st_mode) and not lib.has_symlink_component(socket),
        "containerd_socket_invalid",
    )
    ctr = ["ctr", "--address", str(socket)]
    versions = run([*ctr, "version"]).decode()
    require(versions.count("  Version:  2.2.1") == 2, "containerd_version_drift")
    require(
        "moby" in run([*ctr, "namespaces", "list", "-q"]).decode().splitlines(),
        "namespace_missing",
    )
    help_text = run([*ctr, "--namespace", "moby", "images", "export", "--help"]).decode()
    require(
        "--skip-manifest-json" in help_text and "--platform" in help_text,
        "export_capability_missing",
    )
    # This incident explicitly selects the already-reviewed legacy route before construction.
    with tempfile.TemporaryDirectory(prefix="weekly-release-build-") as raw_temp:
        scratch = Path(raw_temp)
        source = scratch / "source"
        source.mkdir(mode=0o700)
        for name, (mode, value) in rows.items():
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_bytes(value)
            path.chmod(mode)
        suffix = scratch.name.rsplit("-", 1)[1].lower()
        tag = f"edu-ai-lead-agent-backend:weekly-{commit[:12]}-{suffix}"
        require(
            tag.encode()
            not in docker("image", "ls", "--format", "{{.Repository}}:{{.Tag}}").splitlines(),
            "transport_tag_exists",
        )
        created = git(repo, "show", "-s", "--format=%cI", commit).decode().strip()
        log("build_started", release_commit=commit, route="legacy-containerd")
        run(
            [
                "docker",
                "build",
                "--pull",
                "--platform",
                "linux/amd64",
                "--build-arg",
                "CODEUP_COMMIT=" + commit,
                "--build-arg",
                "SOURCE_URL=" + SOURCE_URL,
                "--build-arg",
                "BUILD_CREATED=" + created,
                "--tag",
                tag,
                str(source / "backend"),
            ],
            env={**SAFE_ENV, "DOCKER_BUILDKIT": "0"},
            timeout=1800,
        )
        raw_id = inspect_image(tag)["Id"]
        legacy = scratch / "legacy.oci.tar"
        normalized = lib.normalize_containerd_reference(tag)
        run([*ctr, "--namespace", "moby", "images", "inspect", normalized])
        run(
            [
                *ctr,
                "--namespace",
                "moby",
                "images",
                "export",
                "--skip-manifest-json",
                "--platform",
                "linux/amd64",
                str(legacy),
                normalized,
            ],
            timeout=600,
        )
        canonical_tar = scratch / "canonical.oci.tar"
        manifest = lib.canonicalize_legacy_oci_archive(legacy, canonical_tar, tag)
        with (
            canonical_tar.open("rb") as incoming,
            (stage / "backend-image.oci.tar.gz").open("xb") as outgoing,
            gzip.GzipFile(fileobj=outgoing, mode="wb", mtime=0, filename="") as compressed,
        ):
            shutil.copyfileobj(incoming, compressed)
        with tarfile.open(canonical_tar, "r:") as archive:
            stream = archive.extractfile("blobs/sha256/" + manifest[7:])
            require(stream, "manifest_missing")
            assert stream is not None
            config_digest = lib.strict_json(stream.read(), "manifest")["config"]["digest"]
        metadata = {
            "schema": 1,
            "base_commit": BASE,
            "release_commit": commit,
            "ref": REF,
            "cutoff": args.cutoff,
            "created": created,
            "candidate_repository": "edu-ai-lead-agent-backend",
            "candidate_reference": "edu-ai-lead-agent-backend@" + manifest,
            "candidate_config_digest": config_digest,
            "transport_tag": tag,
            "runtime_paths": sorted(RUNTIME),
            "validator_sha256": LIB_SHA,
        }
        lib.validate_image_archive(stage, metadata)
        require(inspect_image(tag)["Id"] == raw_id, "raw_tag_ownership_drift")
        docker("image", "rm", tag)
        require(
            tag.encode()
            not in docker("image", "ls", "--format", "{{.Repository}}:{{.Tag}}").splitlines(),
            "raw_tag_still_present",
        )
        docker(
            "image",
            "load",
            "--input",
            str(stage / "backend-image.oci.tar.gz"),
            timeout=600,
        )
        probe_image(stage, metadata, lib)
    no_clobber(stage / "release.json", canonical(metadata))
    no_clobber(
        stage / "checksums.json",
        canonical(
            {name: lib.digest_file(stage / name) for name in sorted(MEMBERS - {"checksums.json"})}
        ),
    )
    for path in stage.iterdir():
        path.chmod(0o600)
    log(
        "build_complete",
        release_commit=commit,
        candidate_reference=metadata["candidate_reference"],
        stage_sha256=digest((stage / "checksums.json").read_bytes()),
    )


def validate_stage(stage: Path, expected_sha: str) -> tuple[ModuleType, dict[str, Any]]:
    require(
        stage.is_absolute() and stage.resolve() == stage and stage.is_dir(),
        "stage_path_invalid",
    )
    require(
        stat.S_IMODE(stage.stat().st_mode) == 0o700 and stage.stat().st_uid == 0,
        "stage_permissions_invalid",
    )
    require({path.name for path in stage.iterdir()} == MEMBERS, "stage_member_drift")
    for path in stage.iterdir():
        value = path.lstat()
        require(
            stat.S_ISREG(value.st_mode)
            and stat.S_IMODE(value.st_mode) == 0o600
            and value.st_uid == 0
            and value.st_gid == 0,
            "stage_member_identity_drift",
        )
    require(
        re.fullmatch(r"[0-9a-f]{64}", expected_sha)
        and digest((stage / "checksums.json").read_bytes()) == expected_sha,
        "stage_checksum_drift",
    )
    lib = load_lib(stage / "pure_validator.py")
    checksums = read_json(stage / "checksums.json", lib)
    require(
        isinstance(checksums, dict) and set(checksums) == MEMBERS - {"checksums.json"},
        "checksum_members_invalid",
    )
    for name, checksum in checksums.items():
        require(lib.digest_file(stage / name) == checksum, "stage_content_drift")
    require(
        (stage / "weekly_release.py").read_bytes() == Path(__file__).read_bytes(),
        "operator_identity_drift",
    )
    metadata = read_json(stage / "release.json", lib)
    require(
        set(metadata)
        == {
            "schema",
            "base_commit",
            "release_commit",
            "ref",
            "cutoff",
            "created",
            "candidate_repository",
            "candidate_reference",
            "candidate_config_digest",
            "transport_tag",
            "runtime_paths",
            "validator_sha256",
        },
        "metadata_schema_drift",
    )
    require(
        type(metadata["schema"]) is int
        and metadata["schema"] == 1
        and metadata["base_commit"] == BASE
        and metadata["ref"] == REF
        and metadata["runtime_paths"] == sorted(RUNTIME)
        and metadata["validator_sha256"] == LIB_SHA
        and metadata["candidate_repository"] == "edu-ai-lead-agent-backend"
        and re.fullmatch(r"[0-9a-f]{40}", metadata["release_commit"])
        and metadata["release_commit"] != BASE,
        "metadata_identity_drift",
    )
    window(metadata["cutoff"])
    projection = lib.validate_source_archive(stage)
    lib.validate_image_source(stage / "image-source.sha256", projection)
    lib.validate_image_archive(stage, metadata)
    base = read_json(stage / "base-source.json", lib)
    previous_compose = (stage / "base-compose.yaml").read_bytes()
    require(
        digest(previous_compose) == base["compose.yaml"]["sha256"], "base_compose_identity_drift"
    )
    with tarfile.open(stage / "source.tar.gz", "r:gz") as archive:
        stream = archive.extractfile("compose.yaml")
        require(stream is not None, "candidate_compose_missing")
        assert stream is not None
        validate_compose_change(previous_compose, stream.read())
    current = lib.source_manifest(stage / "source-manifest.tsv")
    files = {
        name: {"mode": mode, "sha256": sha}
        for name, (kind, mode, sha) in current.items()
        if kind == "f"
    }
    require(set(base) <= set(files), "candidate_omits_base_source")
    changed = {name for name in files if files[name] != base.get(name)}
    require(RUNTIME <= changed <= RUNTIME | AUDIT, "candidate_source_diff_drift")
    for name in RUNTIME:
        require(files[name]["mode"] == base[name]["mode"], "runtime_mode_changed")
    return lib, metadata


def compose(*args: str, image: str | None = None, timeout: int = 180) -> bytes:
    require(
        not any(arg == "--build" or arg.startswith("--build=") for arg in args),
        "compose_build_forbidden",
    )
    if args and args[0] in {"up", "create"}:
        require("--no-build" in args, "compose_missing_no_build")
    command = [
        "docker",
        "compose",
        "--project-name",
        "edu-ai-lead-agent",
        "--project-directory",
        str(APP),
        "--file",
        str(APP / "compose.yaml"),
        "--env-file",
        str(APP / ".env"),
        "--env-file",
        str(APP / ".release.env"),
    ]
    for profile in PROFILES:
        command.extend(["--profile", profile])
    return run(
        [*command, *args],
        cwd=APP,
        env={**SAFE_ENV, **({"APP_IMAGE": image} if image else {})},
        timeout=timeout,
    )


def sql(query: str) -> bytes:
    # Credentials expand only inside the existing PostgreSQL container, never on the host argv.
    return run(
        [
            "docker",
            "exec",
            "-i",
            "edu-ai-lead-agent-postgres-1",
            "sh",
            "-c",
            'exec psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At',
        ],
        input_bytes=(
            "BEGIN READ ONLY; SET LOCAL statement_timeout='15s';\n" + query + "\nCOMMIT;\n"
        ).encode(),
    )


HISTORY_TABLES = (
    "acquisition_jobs",
    "governance_jobs",
    "topic_selection_jobs",
    "content_slot_jobs",
    "copy_generation_runs",
    "copy_generation_jobs",
    "copy_generation_attempts",
    "material_packages",
    "wecom_delivery_jobs",
    "wecom_delivery_attempts",
    "official_account_weekly_dag_runs",
    "official_account_weekly_dag_nodes",
    "official_account_weekly_dag_attempts",
    "official_account_article_runs",
    "official_account_article_attempts",
    "official_account_article_versions",
    "wechat_mp_draft_jobs",
    "wechat_mp_draft_items",
    "wechat_mp_draft_attempts",
)
ACTIVE_TABLES = (
    "acquisition_jobs",
    "governance_jobs",
    "topic_selection_jobs",
    "content_slot_jobs",
    "brand_ingestion_jobs",
    "brand_visual_index_jobs",
    "copy_generation_jobs",
    "image_artifacts",
    "official_account_article_runs",
    "official_account_weekly_dag_nodes",
    "wechat_mp_draft_jobs",
    "wecom_delivery_jobs",
    "ip_asset_embedding_jobs",
    "ip_asset_generation_jobs",
)


def database_state() -> dict[str, Any]:
    require(
        sql("SELECT version_num FROM alembic_version;").strip() == HEAD.encode(),
        "database_head_drift",
    )
    zero_checks = [
        f"(SELECT count(*) FROM {table} WHERE status = 'running' "
        "OR lease_expires_at > statement_timestamp())"
        for table in ACTIVE_TABLES
    ]
    zero_checks += [
        f"(SELECT count(*) FROM {table} WHERE status IN ('queued','retry_scheduled'))"
        for table in ACTIVE_TABLES
        if table
        not in {
            "copy_generation_jobs",
            "official_account_weekly_dag_nodes",
            "image_artifacts",
            "official_account_article_runs",
            "wechat_mp_draft_jobs",
            "wecom_delivery_jobs",
        }
    ]
    zero_checks += [
        (
            "(SELECT count(*) FROM copy_generation_jobs j "
            "JOIN copy_generation_runs r ON r.id=j.run_id "
            "WHERE j.status IN ('queued','retry_scheduled') AND r.business_date >= '2026-09-07')"
        ),
        "(SELECT count(*) FROM source_fetch_leases WHERE expires_at > statement_timestamp())",
        "(SELECT count(*) FROM material_packages WHERE status = 'queued')",
        "(SELECT count(*) FROM image_artifacts WHERE status = 'queued')",
        "(SELECT count(*) FROM wecom_delivery_jobs "
        "WHERE status IN ('queued','partial','delivery_unknown'))",
        "(SELECT count(*) FROM official_account_article_runs WHERE status='queued')",
        "(SELECT count(*) FROM official_account_weekly_dag_runs "
        "WHERE status IN ('pending','running','partial','retryable_failed'))",
        "(SELECT count(*) FROM wechat_mp_draft_jobs WHERE status IN ('queued','retryable_failed'))",
    ]
    observed = sql("SELECT " + " + ".join(zero_checks) + ";").strip()
    require(observed == b"0", "active_work_not_drained")
    require(
        sql(
            "SELECT status FROM official_account_weekly_dag_runs "
            "WHERE id='0ae1c882-4254-561f-bdac-17d254c0c166';"
        ).strip()
        == b"terminal_failed",
        "original_terminal_run_drift",
    )
    require(
        sql(
            "SELECT count(*) FROM official_account_article_runs WHERE status='ready' AND id IN "
            "('85f62fb9-0e96-4a9e-95c0-48a99043fdd3','24ad4ddc-7c1e-46e3-a787-acff86a1f102');"
        ).strip()
        == b"2",
        "original_articles_drift",
    )
    frozen = sql("""SELECT concat_ws('|',j.id::text,j.run_id::text,j.status,r.business_date::text,
        j.attempt_count::text,to_char(j.available_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))
        FROM copy_generation_jobs j JOIN copy_generation_runs r ON r.id=j.run_id
        WHERE r.business_date < '2026-09-07' AND j.status IN ('queued','retry_scheduled')
        ORDER BY r.business_date,j.id::text,j.run_id::text,j.status,
        j.attempt_count,j.available_at;""")
    require(
        len(frozen.splitlines()) == 7
        and digest(frozen) == "657797a7d4b8d51c8355c07c62343610529fc85753ecb7b489dcd2ef3c5dc74c",
        "frozen_copy_cohort_drift",
    )
    queries = [
        f"SELECT '{table}',count(*),encode(sha256(convert_to(coalesce(string_agg("
        "encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex'),'' "
        "ORDER BY to_jsonb(t)::text),''),'UTF8')),'hex') "
        f"FROM {table} t;"
        for table in HISTORY_TABLES
    ]
    result: dict[str, Any] = {}
    for line in sql("\n".join(queries)).decode().splitlines():
        table, count, checksum = line.split("|")
        require(
            table in HISTORY_TABLES and re.fullmatch(r"[0-9a-f]{64}", checksum),
            "state_projection_invalid",
        )
        result[table] = {"count": int(count), "sha256": checksum}
    require(set(result) == set(HISTORY_TABLES), "state_projection_incomplete")
    return result


def file_identity(path: Path, lib: ModuleType) -> tuple[bytes, dict[str, Any]]:
    raw, value = lib.stable_read_regular(path, max_bytes=32 * 1024 * 1024)
    return raw, {
        "mode": stat.S_IMODE(value.st_mode),
        "uid": value.st_uid,
        "gid": value.st_gid,
        "sha256": digest(raw),
    }


def protected_state(lib: ModuleType, *, candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {}
    for name in PROTECTED:
        raw, identity = file_identity(APP / name, lib)
        require(identity["mode"] == 0o600, "protected_mode_drift")
        require(
            (identity["uid"], identity["gid"]) == ((1000, 1001) if name == ".env" else (0, 0)),
            "protected_owner_drift",
        )
        if name in {".release-commit", "RELEASE_COMMIT"}:
            require(
                raw
                in {
                    (candidate["release_commit"] if candidate else BASE).encode(),
                    (candidate["release_commit"] if candidate else BASE).encode() + b"\n",
                },
                "release_marker_drift",
            )
        if name == ".release.env":
            reference = candidate["candidate_reference"] if candidate else OLD_IMAGE
            require(
                raw == ("APP_IMAGE=" + reference + "\n").encode(),
                "release_environment_drift",
            )
        result[name] = identity
    return result


def current_source(lib: ModuleType) -> dict[str, Any]:
    require(APP.resolve() == APP and APP.is_dir(), "application_root_invalid")
    result = {}
    for root_name in SOURCE_ROOTS:
        root = APP / root_name
        require(root.exists() and not root.is_symlink(), "managed_source_missing")
        paths = [root, *root.rglob("*")] if root.is_dir() else [root]
        for path in paths:
            require(not lib.has_symlink_component(path), "source_symlink")
            value = path.lstat()
            name = path.relative_to(APP).as_posix()
            lib.safe_path(name)
            mode = stat.S_IMODE(value.st_mode)
            require(value.st_uid == 0 and value.st_gid == 0, "source_owner_drift")
            if stat.S_ISDIR(value.st_mode):
                require(mode in {0o700, 0o755}, "source_directory_mode_invalid")
                result[name] = {
                    "kind": "d",
                    "mode": mode,
                    "uid": 0,
                    "gid": 0,
                    "sha256": None,
                }
            else:
                require(mode in {0o600, 0o644, 0o700, 0o755}, "source_file_mode_invalid")
                _, identity = file_identity(path, lib)
                result[name] = {"kind": "f", **identity}
    return dict(sorted(result.items()))


def verify_source_bytes(source: dict[str, Any], expected: dict[str, Any]) -> None:
    files = {name: value for name, value in source.items() if value["kind"] == "f"}
    require(set(files) == set(expected), "source_path_set_drift")
    for name, value in files.items():
        require(
            value["sha256"] == expected[name]["sha256"]
            and bool(value["mode"] & 0o111) == bool(expected[name]["mode"] & 0o111),
            "source_bytes_or_class_drift",
        )


def services(
    lib: ModuleType,
    image: str,
    *,
    wait_seconds: int = 0,
    pinned_image_id: str | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + wait_seconds
    stable_since: float | None = None
    expected_id = pinned_image_id or str(inspect_image(image)["Id"])
    while True:
        try:
            names = set(compose("ps", "--services", "--status", "running").decode().splitlines())
            require(
                names == set(lib.APP_SERVICES) | {"postgres", "minio"},
                "service_topology_drift",
            )
            require(inspect_image(image)["Id"] == expected_id, "readiness_digest_drift")
            result = {}
            for name in sorted(names):
                ids = compose("ps", "-q", name).decode().splitlines()
                require(len(ids) == 1, "service_identity_ambiguous")
                value = json.loads(docker("inspect", ids[0]))[0]
                require(
                    value["State"]["Status"] == "running" and value["RestartCount"] == 0,
                    "service_unstable",
                )
                if name in {"acquisition-api", "postgres", "minio"}:
                    require(
                        value["State"].get("Health", {}).get("Status") == "healthy",
                        "service_not_healthy",
                    )
                if name in lib.APP_SERVICES:
                    require(value["Image"] == expected_id, "service_image_drift")
                if name == "acquisition-api":
                    require(
                        value["NetworkSettings"]["Ports"].get("8000/tcp")
                        == [{"HostIp": "127.0.0.1", "HostPort": "8000"}],
                        "api_port_binding_drift",
                    )
                result[name] = {
                    "image": value["Image"],
                    "restart_count": value["RestartCount"],
                }
                if name in {"postgres", "minio"}:
                    result[name]["container_id"] = ids[0]
            health = json.loads(
                run(
                    [
                        "curl",
                        "--fail",
                        "--silent",
                        "--max-time",
                        "10",
                        "http://127.0.0.1:8000/healthz",
                    ]
                )
            )
            require(
                isinstance(health, dict)
                and set(health) == {"service", "status", "environment", "timezone"}
                and health["service"] == "edu-ai-lead-agent-api"
                and health["status"] == "ok"
                and health["environment"] == "production"
                and health["timezone"] == "Asia/Shanghai",
                "api_health_contract_drift",
            )
            if wait_seconds == 0:
                return result
            stable_since = stable_since or time.monotonic()
            if time.monotonic() - stable_since >= 15:
                return result
        except ReleaseError:
            stable_since = None
            if wait_seconds == 0 or time.monotonic() >= deadline:
                raise
        require(time.monotonic() < deadline, "service_readiness_timeout")
        time.sleep(2)


def snapshot(stage: Path, lib: ModuleType) -> dict[str, Any]:
    protected = protected_state(lib)
    source = current_source(lib)
    verify_source_bytes(source, read_json(stage / "base-source.json", lib))
    result = {
        "protected": protected,
        "source": source,
        "database": database_state(),
        "services": services(lib, OLD_IMAGE),
    }
    require(protected_state(lib) == protected, "protected_capture_race")
    return result


def capture(args: argparse.Namespace) -> None:
    require(os.geteuid() == 0, "root_required")
    lib, metadata = validate_stage(args.stage, args.stage_sha256)
    value = {
        "schema": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "release_commit": metadata["release_commit"],
        "stage_sha256": args.stage_sha256,
        "state": snapshot(args.stage, lib),
    }
    no_clobber(args.output, canonical(value))
    log(
        "baseline_captured",
        baseline_sha256=digest(canonical(value)),
        release_commit=metadata["release_commit"],
    )


def assert_root(path: Path) -> None:
    value = path.lstat()
    require(
        path.is_absolute()
        and path.resolve() == path
        and stat.S_ISDIR(value.st_mode)
        and stat.S_IMODE(value.st_mode) == 0o700
        and value.st_uid == 0
        and value.st_gid == 0,
        "recovery_root_invalid",
    )


def atomic_replace(path: Path, raw: bytes, identity: dict[str, Any], lib: ModuleType) -> None:
    require(
        path.parent.resolve() == path.parent and path.parent.is_dir(),
        "replacement_parent_invalid",
    )
    # Existing targets must remain physical regular files; inode/path races are rejected.
    _, before = file_identity(path, lib)
    require(
        (before["mode"], before["uid"], before["gid"])
        == (identity["mode"], identity["uid"], identity["gid"]),
        "replacement_identity_drift",
    )
    fd, temporary_name = tempfile.mkstemp(prefix=".weekly-release-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            os.fchmod(stream.fileno(), identity["mode"])
            os.fchown(stream.fileno(), identity["uid"], identity["gid"])
            stream.flush()
            os.fsync(stream.fileno())
        require(file_identity(path, lib)[1] == before, "replacement_race")
        os.replace(temporary, path)
        require(
            file_identity(path, lib)[1] == {**identity, "sha256": digest(raw)},
            "replacement_verification_failed",
        )
    finally:
        temporary.unlink(missing_ok=True)


def prepare_source(stage: Path, work: Path, previous: dict[str, Any], lib: ModuleType) -> Path:
    root = work / "candidate"
    root.mkdir(mode=0o700)
    # Validation precedes member materialization; no tar extract path or link semantics are used.
    lib.validate_source_archive(stage)
    with tarfile.open(stage / "source.tar.gz", "r:gz") as archive:
        for member in archive:
            name = lib.safe_path(member.name)
            destination = root / name
            metadata = previous.get(name)
            mode = (
                metadata["mode"]
                if metadata
                else (0o700 if member.isdir() or member.mode == 0o755 else 0o600)
            )
            if member.isdir():
                destination.mkdir(mode=mode)
            else:
                stream = archive.extractfile(member)
                require(stream is not None, "candidate_member_unreadable")
                assert stream is not None
                no_clobber(destination, stream.read())
                destination.chmod(mode)
            os.chown(destination, 0, 0)
    return root


def verify_compose(
    metadata: dict[str, Any], lib: ModuleType, *, candidate_source: bool = False
) -> None:
    # The rendered document contains secrets. Consume only in memory; never log or persist it.
    payload = json.loads(
        compose("config", "--format", "json", image=metadata["candidate_reference"])
    )
    require(
        payload["services"]["wechat-official-account-draft-worker"]["environment"][
            "WECHAT_MP_DRAFT_WEEKLY_INBOX_ROOT"
        ]
        == (
            "/app/input/official-account-weekly-editions/weekly-inbox"
            if candidate_source
            else "/app/input/weekly-inbox"
        ),
        "compose_inbox_contract_drift",
    )
    for name, command in lib.SERVICE_COMMANDS.items():
        service = payload["services"][name]
        require(
            service.get("image") == metadata["candidate_reference"]
            and service.get("command") == list(command)
            and "pull_policy" not in service
            and service.get("build")
            == {"context": str(APP / "backend"), "dockerfile": "Dockerfile"},
            "compose_contract_drift",
        )
        if name == "acquisition-api":
            ports = service.get("ports")
            require(
                isinstance(ports, list)
                and len(ports) == 1
                and ports[0].get("target") == 8000
                and str(ports[0].get("published")) == "8000"
                and ports[0].get("host_ip") == "127.0.0.1",
                "compose_api_port_drift",
            )


def verify_backup(output: bytes, started: datetime, lib: ModuleType) -> str:
    lines = output.decode().splitlines()
    records = [
        re.fullmatch(
            r"backup_completed backup_id=(\d{8}T\d{6}Z) postgres_bytes=(\d+) "
            r"minio_files=(\d+) brand_bytes=(\d+)",
            line,
        )
        for line in lines
    ]
    matches = [match for match in records if match]
    require(len(matches) == 1, "backup_completion_unproven")
    match = matches[0]
    assert match is not None
    backup_id = match.group(1)
    observed = datetime.strptime(backup_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    require(
        started - timedelta(seconds=1) <= observed <= datetime.now(UTC)
        and all(int(match.group(index)) > 0 for index in (2, 3, 4)),
        "backup_not_fresh",
    )
    backup_root = Path("/var/backups/edu-ai")
    evidence_path = backup_root / "releases" / backup_id / "backup-evidence.txt"
    raw, _ = lib.stable_read_regular(
        evidence_path, expected_mode=0o600, expected_uid=0, expected_gid=0
    )
    fields = [line.split("=", 1) for line in raw.decode().splitlines()]
    evidence = dict(fields)
    require(
        len(evidence) == len(fields)
        and set(evidence)
        == {
            "schema_version",
            "backup_id",
            "release_commit",
            "release_image",
            "postgres_file",
            "postgres_sha256",
            "minio_file_count",
            "minio_manifest_sha256",
            "brand_file",
            "brand_sha256",
        },
        "backup_evidence_schema_drift",
    )
    require(
        evidence["schema_version"] == "1"
        and evidence["backup_id"] == backup_id
        and evidence["release_commit"] == BASE
        and evidence["release_image"] == OLD_IMAGE
        and evidence["postgres_file"] == f"edu-ai-{backup_id}.dump"
        and evidence["brand_file"] == f"brand-materials-{backup_id}.tar.gz"
        and evidence["minio_file_count"] == match.group(3),
        "backup_identity_drift",
    )
    for path, checksum in (
        (
            backup_root / "postgres" / evidence["postgres_file"],
            evidence["postgres_sha256"],
        ),
        (
            backup_root / "minio" / backup_id / "SHA256SUMS",
            evidence["minio_manifest_sha256"],
        ),
        (
            backup_root / "brand-materials" / evidence["brand_file"],
            evidence["brand_sha256"],
        ),
    ):
        require(
            path.is_file()
            and not lib.has_symlink_component(path)
            and re.fullmatch(r"[0-9a-f]{64}", checksum)
            and lib.digest_file(path) == checksum,
            "backup_checksum_drift",
        )
    return backup_id


def source_candidate_manifest(stage: Path, lib: ModuleType) -> dict[str, Any]:
    return {
        name: {"mode": mode, "sha256": checksum}
        for name, (kind, mode, checksum) in lib.source_manifest(
            stage / "source-manifest.tsv"
        ).items()
        if kind == "f"
    }


def projected_source_metadata(
    stage: Path, previous: dict[str, Any], lib: ModuleType
) -> dict[str, Any]:
    result = {}
    for name, (kind, mode, checksum) in lib.source_manifest(stage / "source-manifest.tsv").items():
        preserved = previous.get(name)
        actual_mode = (
            preserved["mode"] if preserved else (0o700 if kind == "d" or mode == 0o755 else 0o600)
        )
        result[name] = {
            "kind": kind,
            "mode": actual_mode,
            "uid": 0,
            "gid": 0,
            "sha256": checksum if kind == "f" else None,
        }
    return result


class Activation:
    def __init__(
        self,
        stage: Path,
        baseline: dict[str, Any],
        metadata: dict[str, Any],
        lib: ModuleType,
        work: Path,
    ) -> None:
        self.stage, self.baseline, self.metadata, self.lib, self.work = (
            stage,
            baseline,
            metadata,
            lib,
            work,
        )
        self.state = baseline["state"]
        self.armed = False
        self.moved: list[str] = []
        self.installed: list[str] = []
        self.backup_id: str | None = None

    def assert_frozen(self, *, with_services: bool = False) -> None:
        require(
            protected_state(self.lib) == self.state["protected"],
            "protected_baseline_drift",
        )
        require(current_source(self.lib) == self.state["source"], "source_baseline_drift")
        require(database_state() == self.state["database"], "database_baseline_drift")
        if with_services:
            require(
                services(self.lib, OLD_IMAGE) == self.state["services"],
                "service_baseline_drift",
            )

    def restore(self) -> None:
        # A failure from the *first* stop is mutating. Restore all twelve services, including
        # those that an interrupted partial stop did not reach. Never restore/downgrade a DB.
        compose("stop", "-t", "90", *self.lib.APP_SERVICES, timeout=180)
        require(database_state() == self.state["database"], "rollback_database_drift")
        failed = self.work / "failed-candidate"
        failed.mkdir(mode=0o700)
        for name in reversed(self.moved):
            backup_path = self.work / "source.before" / name
            if not backup_path.exists():
                continue  # an interruption may follow intent but precede the first rename
            require(not backup_path.is_symlink(), "rollback_backup_symlink")
            if (APP / name).exists():
                require(not (APP / name).is_symlink(), "rollback_source_symlink")
                os.rename(APP / name, failed / name)
            require(
                not (APP / name).exists() and not (APP / name).is_symlink(),
                "rollback_destination_exists",
            )
            os.rename(backup_path, APP / name)
        for name in PROTECTED:
            raw = (self.work / "protected.before" / name).read_bytes()
            if file_identity(APP / name, self.lib)[1] != self.state["protected"][name]:
                atomic_replace(APP / name, raw, self.state["protected"][name], self.lib)
        self.assert_frozen()
        compose("up", "-d", "--no-deps", "--no-build", *self.lib.APP_SERVICES, timeout=180)
        services(
            self.lib,
            OLD_IMAGE,
            wait_seconds=150,
            pinned_image_id=self.state["services"]["acquisition-api"]["image"],
        )
        self.assert_frozen(with_services=True)
        no_clobber(
            self.work / "rollback.json",
            canonical({"status": "previous_runtime_verified", "base_commit": BASE}),
        )

    def execute(self, stage_sha: str) -> None:
        self.assert_frozen(with_services=True)
        verify_compose(self.metadata, self.lib)
        # Candidate loading is inactive. Leave verified images in place for audit; never infer
        # cleanup ownership from a matching tag or delete any pre-existing image reference.
        tags = docker("image", "ls", "--format", "{{.Repository}}:{{.Tag}}").splitlines()
        require(
            self.metadata["transport_tag"].encode() not in tags,
            "candidate_already_loaded",
        )
        docker(
            "image",
            "load",
            "--input",
            str(self.stage / "backend-image.oci.tar.gz"),
            timeout=600,
        )
        candidate_id = probe_image(self.stage, self.metadata, self.lib)
        candidate = prepare_source(self.stage, self.work, self.state["source"], self.lib)
        expected_source = projected_source_metadata(self.stage, self.state["source"], self.lib)
        before = self.work / "source.before"
        before.mkdir(mode=0o700)
        protected = self.work / "protected.before"
        protected.mkdir(mode=0o700)
        for name in PROTECTED:
            raw, identity = file_identity(APP / name, self.lib)
            require(identity == self.state["protected"][name], "protected_snapshot_drift")
            no_clobber(protected / name, raw)
        self.assert_frozen(with_services=True)
        window(self.metadata["cutoff"])
        no_clobber(self.work / "quiesce-intent.json", canonical({"candidate_id": candidate_id}))
        self.armed = True
        compose("stop", "-t", "90", *self.lib.APP_SERVICES, timeout=180)
        self.assert_frozen()
        started = datetime.now(UTC)
        output = run(["bash", str(APP / "scripts/edu-ai-backup.sh")], timeout=600)
        self.backup_id = verify_backup(output, started, self.lib)
        self.assert_frozen()
        validate_stage(self.stage, stage_sha)
        window(self.metadata["cutoff"])
        for name in SOURCE_ROOTS:
            require(not (before / name).exists(), "source_backup_collision")
            self.moved.append(name)
            os.rename(APP / name, before / name)
            os.rename(candidate / name, APP / name)
            self.installed.append(name)
        verify_source_bytes(
            current_source(self.lib), source_candidate_manifest(self.stage, self.lib)
        )
        require(
            current_source(self.lib) == expected_source,
            "candidate_source_metadata_drift",
        )
        for name in (".release-commit", "RELEASE_COMMIT"):
            atomic_replace(
                APP / name,
                (self.metadata["release_commit"] + "\n").encode(),
                self.state["protected"][name],
                self.lib,
            )
        atomic_replace(
            APP / ".release.env",
            ("APP_IMAGE=" + self.metadata["candidate_reference"] + "\n").encode(),
            self.state["protected"][".release.env"],
            self.lib,
        )
        activated = protected_state(self.lib, candidate=self.metadata)
        require(
            activated[".env"] == self.state["protected"][".env"],
            "private_environment_changed",
        )
        require(database_state() == self.state["database"], "prestart_database_drift")
        window(self.metadata["cutoff"])
        require(
            current_source(self.lib) == expected_source,
            "prestart_source_metadata_drift",
        )
        verify_compose(self.metadata, self.lib, candidate_source=True)
        compose("up", "-d", "--no-deps", "--no-build", *self.lib.APP_SERVICES, timeout=180)
        service_state = services(
            self.lib,
            self.metadata["candidate_reference"],
            wait_seconds=150,
            pinned_image_id=candidate_id,
        )
        require(
            all(
                service_state[name] == self.state["services"][name]
                for name in ("postgres", "minio")
            ),
            "infrastructure_identity_drift",
        )
        require(
            protected_state(self.lib, candidate=self.metadata) == activated,
            "poststart_environment_drift",
        )
        require(database_state() == self.state["database"], "poststart_database_drift")
        verify_source_bytes(
            current_source(self.lib), source_candidate_manifest(self.stage, self.lib)
        )
        require(
            current_source(self.lib) == expected_source,
            "poststart_source_metadata_drift",
        )
        no_clobber(
            self.work / "success.json",
            canonical(
                {
                    "status": "activated",
                    "release_commit": self.metadata["release_commit"],
                    "candidate_id": candidate_id,
                    "candidate_reference": self.metadata["candidate_reference"],
                    "backup_id": self.backup_id,
                    "services": service_state,
                    "database": self.state["database"],
                    "primary_environment": activated[".env"],
                }
            ),
        )
        log(
            "activation_complete",
            release_commit=self.metadata["release_commit"],
            backup_id=self.backup_id,
            application_services=len(self.lib.APP_SERVICES),
        )


def activate(args: argparse.Namespace) -> None:
    require(os.geteuid() == 0, "root_required")
    require(os.read(0, 1) == b"", "activation_requires_null_stdin")
    lib, metadata = validate_stage(args.stage, args.stage_sha256)
    baseline_raw, _ = lib.stable_read_regular(
        args.baseline, expected_mode=0o600, expected_uid=0, expected_gid=0
    )
    require(
        re.fullmatch(r"[0-9a-f]{64}", args.baseline_sha256)
        and digest(baseline_raw) == args.baseline_sha256,
        "baseline_checksum_drift",
    )
    baseline = lib.strict_json(baseline_raw, "baseline")
    require(
        set(baseline) == {"schema", "captured_at", "release_commit", "stage_sha256", "state"}
        and type(baseline["schema"]) is int
        and baseline["schema"] == 1
        and baseline["release_commit"] == metadata["release_commit"]
        and baseline["stage_sha256"] == args.stage_sha256,
        "baseline_identity_drift",
    )
    captured = datetime.fromisoformat(baseline["captured_at"])
    require(
        captured.tzinfo is not None
        and timedelta(0) <= datetime.now(UTC) - captured <= timedelta(minutes=5),
        "baseline_stale",
    )
    lock_path = Path("/var/lock/edu-ai-deploy.lock")
    fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w"):
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(snapshot(args.stage, lib) == baseline["state"], "locked_baseline_drift")
        assert_root(BACKUPS)
        require(BACKUPS.stat().st_dev == APP.stat().st_dev, "source_recovery_cross_device")
        work = BACKUPS / ("weekly-release-" + metadata["release_commit"])
        work.mkdir(mode=0o700)  # permanent, single-consumption attempt identity
        no_clobber(
            work / "attempt.json",
            canonical(
                {
                    "stage_sha256": args.stage_sha256,
                    "baseline_sha256": args.baseline_sha256,
                    "release_commit": metadata["release_commit"],
                }
            ),
        )
        operation = Activation(args.stage, baseline, metadata, lib, work)
        try:
            operation.execute(args.stage_sha256)
        except BaseException:
            if operation.armed:
                try:
                    operation.restore()
                    log("rollback_complete", previous_commit=BASE)
                except BaseException as recovery_error:
                    try:
                        compose("stop", "-t", "90", *lib.APP_SERVICES, timeout=180)
                    finally:
                        log(
                            "incident_writers_stopped",
                            reason="rollback_verification_failed",
                        )
                    raise ReleaseError("rollback_verification_failed") from recovery_error
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--repo", type=Path, required=True)
    build_parser.add_argument("--commit", required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--cutoff", required=True)
    for name in ("capture", "activate"):
        command = commands.add_parser(name)
        command.add_argument("--stage", type=Path, required=True)
        command.add_argument("--stage-sha256", required=True)
        if name == "capture":
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--baseline", type=Path, required=True)
            command.add_argument("--baseline-sha256", required=True)
    args = parser.parse_args()
    os.umask(0o077)

    def interrupted(_number: int, _frame: object) -> None:
        raise ReleaseError("operator_interrupted")

    for number in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(number, interrupted)
    try:
        {"build": build, "capture": capture, "activate": activate}[args.command](args)
    except ReleaseError as exc:
        log("release_failed", reason=str(exc))
        return 1
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError):
        log("release_failed", reason="invalid_state_or_evidence")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
