from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from pydantic import BaseModel

from app.domain.ip_asset_metadata_repair import canonical_json

_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_Artifact = TypeVar("_Artifact", bound=BaseModel)


@contextmanager
def reserve_private_artifact(path: Path) -> Iterator[None]:
    """Reserve an exclusive output name before provider or database side effects."""

    if not path.name or path.name in {".", ".."}:
        raise ValueError("IP asset repair artifact path is invalid")
    _prepare_private_directory(path.parent)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock_name = f".{path.name}.lock"
    lock_fd: int | None = None
    try:
        try:
            os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(path)
        lock_fd = os.open(
            lock_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        os.fchmod(lock_fd, 0o600)
        os.fsync(lock_fd)
        os.fsync(directory_fd)
        # A process using an older CLI might have created the destination between the first
        # existence check and our lock. Fail before yielding in that case.
        try:
            os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(path)
        yield
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
            try:
                os.unlink(lock_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            os.fsync(directory_fd)
        os.close(directory_fd)


def write_private_artifact(path: Path, artifact: BaseModel) -> None:
    """Atomically create one canonical private JSON artifact without overwrite."""

    if not path.name or path.name in {".", ".."}:
        raise ValueError("IP asset repair artifact path is invalid")
    _prepare_private_directory(path.parent)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary_name = f".{path.name}.{uuid4().hex}.tmp"
    temporary_fd: int | None = None
    try:
        payload = canonical_json(artifact.model_dump(mode="json")) + b"\n"
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise ValueError("IP asset repair artifact exceeds the size limit")
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        os.fchmod(temporary_fd, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(temporary_fd, view)
            if written < 1:
                raise OSError("IP asset repair artifact write made no progress")
            view = view[written:]
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None
        os.link(
            temporary_name,
            path.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
        os.fsync(directory_fd)
    finally:
        if temporary_fd is not None:
            os.close(temporary_fd)
        try:
            os.unlink(temporary_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def read_private_artifact(path: Path, schema: type[_Artifact]) -> _Artifact:
    _assert_no_symlink(path)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        directory_metadata = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(directory_metadata.st_mode)
            or stat.S_IMODE(directory_metadata.st_mode) != 0o700
        ):
            raise ValueError("IP asset repair artifact directory is not private")
        file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        try:
            metadata = os.fstat(file_fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or not 1 <= metadata.st_size <= _MAX_ARTIFACT_BYTES
            ):
                raise ValueError("IP asset repair artifact is invalid")
            chunks: list[bytes] = []
            remaining = metadata.st_size
            while remaining:
                chunk = os.read(file_fd, min(remaining, 64 * 1024))
                if not chunk:
                    raise ValueError("IP asset repair artifact is truncated")
                chunks.append(chunk)
                remaining -= len(chunk)
        finally:
            os.close(file_fd)
    finally:
        os.close(directory_fd)
    return schema.model_validate_json(b"".join(chunks))


def _prepare_private_directory(path: Path) -> None:
    _assert_no_symlink(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    _assert_no_symlink(path)
    if not path.is_dir():
        raise ValueError("IP asset repair artifact directory is invalid")
    path.chmod(0o700)


def _assert_no_symlink(path: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise ValueError("IP asset repair artifact path cannot contain a symlink")
        if current.parent == current:
            break
        current = current.parent
