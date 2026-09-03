"""Exclusive private-artifact I/O for the live A/B harness."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .models import canonical_json_bytes

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = REPOSITORY_ROOT / "output" / "evals" / "agent-retrieval-ab"
_ModelT = TypeVar("_ModelT", bound=BaseModel)


class ArtifactError(ValueError):
    """A private live-eval artifact violated its path or integrity contract."""


def require_output_path(path: Path) -> Path:
    root = OUTPUT_ROOT.resolve()
    absolute = Path(os.path.abspath(path))
    if absolute == root or root not in absolute.parents:
        raise ArtifactError("live A/B artifacts must stay below the ignored output root")
    relative = absolute.relative_to(root)
    current = root
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise ArtifactError("live A/B artifact paths cannot contain symbolic links")
    resolved = absolute.resolve(strict=False)
    if resolved == root or root not in resolved.parents:
        raise ArtifactError("live A/B artifacts must stay below the ignored output root")
    return resolved


def create_run_directory(path: Path) -> Path:
    resolved = require_output_path(path)
    try:
        resolved.mkdir(mode=0o700, parents=True, exist_ok=False)
        (resolved / "attempts").mkdir(mode=0o700)
    except OSError as exc:
        raise ArtifactError("live A/B output directory must be new") from exc
    _require_owner_only_directory(resolved)
    _require_owner_only_directory(resolved / "attempts")
    return resolved


def write_json_exclusive(path: Path, value: object) -> None:
    _write_exclusive(path, canonical_json_bytes(value) + b"\n")


def write_jsonl_exclusive(path: Path, values: tuple[BaseModel, ...]) -> None:
    body = b"".join(canonical_json_bytes(value) + b"\n" for value in values)
    _write_exclusive(path, body)


def write_text_exclusive(path: Path, value: str) -> None:
    _write_exclusive(path, value.encode("utf-8"))


def write_json_atomic(path: Path, value: object) -> None:
    resolved = require_output_path(path)
    resolved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = resolved.with_name(f".{resolved.name}.tmp-{os.getpid()}")
    try:
        _write_exclusive(temporary, canonical_json_bytes(value) + b"\n")
        os.replace(temporary, resolved)
        os.chmod(resolved, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_json_model(path: Path, model: type[_ModelT]) -> _ModelT:
    resolved = require_output_path(path)
    _require_private_file(resolved)
    try:
        payload = resolved.read_bytes()
    except OSError as exc:
        raise ArtifactError("live A/B artifact could not be read") from exc
    if not payload or len(payload) > 4 * 1024 * 1024:
        raise ArtifactError("live A/B artifact has an invalid size")
    try:
        return model.model_validate_json(payload)
    except ValueError as exc:
        raise ArtifactError("live A/B artifact failed schema validation") from exc


def load_jsonl_models(path: Path, model: type[_ModelT]) -> tuple[_ModelT, ...]:
    resolved = require_output_path(path)
    _require_private_file(resolved)
    try:
        lines = resolved.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ArtifactError("live A/B JSONL could not be read") from exc
    if not lines or any(not line.strip() for line in lines):
        raise ArtifactError("live A/B JSONL is empty or contains blank rows")
    try:
        return tuple(model.model_validate_json(line) for line in lines)
    except ValueError as exc:
        raise ArtifactError("live A/B JSONL failed schema validation") from exc


def load_raw_json(path: Path) -> object:
    resolved = require_output_path(path)
    _require_private_file(resolved)
    try:
        return json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError("live A/B JSON could not be loaded") from exc


def _write_exclusive(path: Path, payload: bytes) -> None:
    resolved = require_output_path(path)
    resolved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require_owner_only_directory(resolved.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags, 0o600)
    except OSError as exc:
        raise ArtifactError("live A/B artifacts are immutable and cannot be overwritten") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            resolved.unlink()
        except OSError:
            pass
        raise


def _require_owner_only_directory(path: Path) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ArtifactError("live A/B artifact directory is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o077:
        raise ArtifactError("live A/B artifact directories must be owner-only")


def _require_private_file(path: Path) -> None:
    _require_owner_only_directory(path.parent)
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ArtifactError("live A/B artifact could not be read") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
        raise ArtifactError("live A/B artifact files must be private regular files")
