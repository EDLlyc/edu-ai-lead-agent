#!/usr/bin/env python3
"""Offline-load and network-none read-only runtime check for an R16 OCI image."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from r16_oci import REPOSITORY, check_oci, strict_json

FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
PROBE = r"""
import hashlib,importlib,json,pathlib,subprocess
from alembic.config import Config
from alembic.script import ScriptDirectory
from PIL import ImageFont
root=pathlib.Path('/app'); files={}
for base in (root/'app',root/'alembic'):
 for p in sorted(base.rglob('*')):
  if '__pycache__' in p.parts or p.suffix=='.pyc': continue
  if p.is_symlink(): raise RuntimeError('runtime_symlink')
  if p.is_file(): files[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
for p in (root/'alembic.ini',root/'pyproject.toml'):
 files[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
font=pathlib.Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
if font.is_symlink() or not font.is_file(): raise RuntimeError('font_path')
loaded=ImageFont.truetype(str(font),32)
if loaded.getmask('赛先生科学探究').getbbox() is None: raise RuntimeError('font_glyphs')
modules=('app.api_main','app.scheduler_main','app.worker_main',
 'app.governance_scheduler_main','app.governance_worker_main',
 'app.content_scheduler_main','app.content_worker_main',
 'app.official_account_weekly_dag_main','app.official_account_weekly_scheduler_main',
 'app.official_account_worker_main','app.wechat_official_account_draft_main',
 'app.wecom_dispatcher_main','app.wecom_news_infographic_main')
for name in modules: importlib.import_module(name)
from app.api_main import app
assert app.openapi()['openapi']
font_version=subprocess.run(['dpkg-query','-W','-f=${Version}','fonts-noto-cjk'],
 capture_output=True,text=True,check=True).stdout
pip=subprocess.run(['python','-m','pip','check'],capture_output=True,check=False).returncode
print(json.dumps({'files':files,'font_version':font_version,
 'font_sha256':hashlib.sha256(font.read_bytes()).hexdigest(),
 'font_loaded':True,'head':ScriptDirectory.from_config(Config('/app/alembic.ini')).get_heads(),
 'pip_check':pip},sort_keys=True))
"""


class SmokeError(RuntimeError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise SmokeError(code)


def run(args: list[str], *, cwd: Path | None = None, timeout: int = 120) -> bytes:
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    require(result.returncode == 0, "subprocess_failed:" + args[0])
    return result.stdout


def source_tree(repo: Path, revision: str) -> dict[str, str]:
    archive = run(
        [
            "git",
            "-C",
            str(repo),
            "archive",
            "--format=tar",
            revision,
            "backend/app",
            "backend/alembic",
            "backend/alembic.ini",
            "backend/pyproject.toml",
        ]
    )
    expected: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as content:
        for item in content:
            if item.isdir():
                continue
            require(
                item.isfile() and item.name.startswith("backend/"), "source_file_type"
            )
            stream = content.extractfile(item)
            require(stream is not None, "source_stream")
            assert stream is not None
            expected[item.name.removeprefix("backend/")] = hashlib.sha256(
                stream.read()
            ).hexdigest()
    return expected


def font_contract(repo: Path, revision: str) -> tuple[str, str]:
    body = run(["git", "-C", str(repo), "show", f"{revision}:backend/Dockerfile"])
    version = re.search(rb"(?m)^ARG FONTS_NOTO_CJK_VERSION=([^\s]+)\s*$", body)
    sha = re.search(
        rb"([0-9a-f]{64}) /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        body,
    )
    require(version is not None and sha is not None, "font_source_contract")
    assert version is not None and sha is not None
    return version.group(1).decode(), sha.group(1).decode()


def smoke(
    repo: Path,
    revision: str,
    archive: Path,
    *,
    config_id: str,
    expected_image: str,
) -> dict[str, Any]:
    require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "revision")
    require(
        run(["git", "-C", str(repo), "rev-parse", "HEAD"]).decode().strip() == revision,
        "head_drift",
    )
    require(
        run(["git", "-C", str(repo), "status", "--porcelain"]) == b"",
        "dirty_worktree",
    )
    tag = f"{REPOSITORY}:infographic-r16-{revision[:12]}"
    graph = check_oci(archive, tag=tag, revision=revision, config_id=config_id)
    require(graph["image"] == expected_image, "image_digest")
    run(["docker", "load", "-i", str(archive)], timeout=300)
    inspected = strict_json(run(["docker", "image", "inspect", tag]))
    require(
        isinstance(inspected, list)
        and len(inspected) == 1
        # Docker 29's containerd-backed store reports the OCI manifest digest
        # as the image ID for this archive, not its config-blob digest.
        and inspected[0]["Id"] == expected_image
        and tag in inspected[0].get("RepoTags", []),
        "loaded_image_identity",
    )
    probe: Any = strict_json(
        run(
            [
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--entrypoint",
                "python",
                tag,
                "-B",
                "-c",
                PROBE,
            ],
            timeout=180,
        )
    )
    font_version, font_sha = font_contract(repo, revision)
    require(
        probe.get("files") == source_tree(repo, revision),
        "runtime_source_tree",
    )
    require(
        probe.get("font_version") == font_version
        and probe.get("font_sha256") == font_sha
        and probe.get("font_loaded") is True,
        "font_runtime_identity",
    )
    require(probe.get("head") == ["20260926_0050"], "migration_head")
    require(probe.get("pip_check") == 0, "pip_check")
    for profiles in (("content", "wecom"), ("content", "wecom", "infographic")):
        command = ["docker", "compose"]
        for profile in profiles:
            command += ["--profile", profile]
        command += ["config", "--quiet"]
        run(command, cwd=repo, timeout=60)
    return {
        "status": "local_smoke_passed",
        "revision": revision,
        "image": expected_image,
        "config_id": config_id,
        "archive_sha256": graph["archive_sha256"],
        "font_version": font_version,
        "font_sha256": font_sha,
        "migration_head": "20260926_0050",
        "source_files": len(probe["files"]),
        "network": "none",
        "production_activation": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--config-id", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    try:
        result = smoke(
            args.repo,
            args.revision,
            args.archive,
            config_id=args.config_id,
            expected_image=args.image,
        )
    except (
        SmokeError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        tarfile.TarError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(json.dumps({"status": "blocked", "code": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
