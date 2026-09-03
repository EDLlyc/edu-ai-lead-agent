"""Private, exclusive evidence I/O constrained to the ignored output tree."""

from __future__ import annotations

import fcntl
import os
import stat
import subprocess
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .models import canonical_json_bytes
from .parsing import ModelPanelParseError, strict_json_object
from .privacy import PrivacyProfile, require_privacy_safe

MAX_EVIDENCE_FILE_BYTES = 128 * 1024 * 1024
MAX_JOURNAL_BYTES = 32 * 1024 * 1024
ModelT = TypeVar("ModelT", bound=BaseModel)


class ModelPanelIOError(ValueError):
    """An evidence path, permission, or immutable-write contract was violated."""


class SecureEvidenceStore:
    """Own private artifacts without following links or replacing existing evidence."""

    def __init__(
        self,
        *,
        repository_root: Path,
        output_root: Path | None = None,
        tracked_path_predicate: Callable[[Path], bool] | None = None,
        ignored_path_predicate: Callable[[Path], bool] | None = None,
    ) -> None:
        self.repository_root = repository_root.resolve(strict=True)
        default_output = self.repository_root / "output" / "evals"
        self.output_root = self._lexical_absolute(output_root or default_output)
        if self.output_root != default_output:
            raise ModelPanelIOError("model-panel evidence root must be repository output/evals")
        self._is_tracked = tracked_path_predicate or self._git_tracked
        self._is_ignored = ignored_path_predicate or self._git_ignored

    def create_run_directory(self, path: Path) -> Path:
        target = self.require_output_path(path)
        if target == self.output_root:
            raise ModelPanelIOError("run directory must be below the evidence output root")
        if self._is_tracked(target):
            raise ModelPanelIOError("tracked paths cannot contain private model-panel evidence")
        if not self._is_ignored(target):
            raise ModelPanelIOError("model-panel evidence destination must be gitignored")
        self._reject_symlink_ancestors(target)
        self._create_private_tree(target)
        self._require_private_directory(target)
        return target

    def create_private_directory(self, path: Path) -> Path:
        target = self.require_output_path(path)
        parent = target.parent
        self._require_private_directory(parent)
        if self._is_tracked(target):
            raise ModelPanelIOError("tracked paths cannot contain private model-panel evidence")
        try:
            target.mkdir(mode=0o700, exist_ok=False)
            os.chmod(target, 0o700)
        except OSError as exc:
            raise ModelPanelIOError("private evidence directory must be new") from exc
        self._require_private_directory(target)
        return target

    def write_json_exclusive(
        self,
        path: Path,
        value: object,
        *,
        privacy_profile: PrivacyProfile,
    ) -> None:
        require_privacy_safe(value, profile=privacy_profile)
        self.write_bytes_exclusive(
            path,
            canonical_json_bytes(value),
        )

    def write_text_exclusive(
        self,
        path: Path,
        value: str,
        *,
        privacy_profile: PrivacyProfile,
    ) -> None:
        require_privacy_safe(value, profile=privacy_profile)
        self.write_bytes_exclusive(path, value.encode("utf-8"))

    def write_bytes_exclusive(self, path: Path, payload: bytes) -> None:
        target = self.require_output_path(path)
        if not payload or len(payload) > MAX_EVIDENCE_FILE_BYTES:
            raise ModelPanelIOError("evidence artifact has an invalid byte length")
        if self._is_tracked(target):
            raise ModelPanelIOError("tracked destinations cannot be overwritten by evidence")
        parent_descriptor = self._open_private_parent(target)
        descriptor: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(target.name, flags, 0o600, dir_fd=parent_descriptor)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                os.fchmod(stream.fileno(), 0o600)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(parent_descriptor)
        except OSError as exc:
            raise ModelPanelIOError(
                "evidence artifacts are immutable and cannot be overwritten"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent_descriptor)

    def read_bytes(self, path: Path, *, maximum: int = MAX_EVIDENCE_FILE_BYTES) -> bytes:
        target = self.require_output_path(path)
        parent_descriptor = self._open_private_parent(target)
        descriptor: int | None = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(target.name, flags, dir_fd=parent_descriptor)
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = None
                metadata = os.fstat(stream.fileno())
                self._require_private_file(metadata, label="evidence artifact")
                payload = stream.read(maximum + 1)
        except OSError as exc:
            raise ModelPanelIOError("evidence artifact could not be read") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent_descriptor)
        if not payload or len(payload) > maximum:
            raise ModelPanelIOError("evidence artifact has an invalid byte length")
        return payload

    def load_json_model(self, path: Path, model: type[ModelT]) -> ModelT:
        try:
            raw = strict_json_object(self.read_bytes(path))
            return model.model_validate_json(canonical_json_bytes(raw))
        except (ModelPanelParseError, ValidationError) as exc:
            raise ModelPanelIOError("evidence artifact failed strict schema validation") from exc

    def append_line_locked(
        self,
        path: Path,
        build_line: Callable[[bytes], bytes],
    ) -> bytes:
        """Build and append one line while holding an exclusive file lock."""

        target = self.require_output_path(path)
        if self._is_tracked(target):
            raise ModelPanelIOError("tracked destinations cannot contain an evidence journal")
        parent_descriptor = self._open_private_parent(target)
        descriptor: int | None = None
        try:
            flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(target.name, flags, 0o600, dir_fd=parent_descriptor)
            with os.fdopen(descriptor, "r+b") as stream:
                descriptor = None
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                metadata = os.fstat(stream.fileno())
                self._require_private_file(metadata, label="evidence journal")
                if metadata.st_size > MAX_JOURNAL_BYTES:
                    raise ModelPanelIOError("evidence journal exceeds its byte limit")
                stream.seek(0)
                current = stream.read(MAX_JOURNAL_BYTES + 1)
                line = build_line(current)
                if (
                    not line
                    or line.count(b"\n") > 1
                    or (b"\n" in line and not line.endswith(b"\n"))
                    or len(line) > MAX_JOURNAL_BYTES
                ):
                    raise ModelPanelIOError("journal builder returned an invalid line")
                if not line.endswith(b"\n"):
                    line += b"\n"
                if len(current) + len(line) > MAX_JOURNAL_BYTES:
                    raise ModelPanelIOError("evidence journal exceeds its byte limit")
                stream.seek(0, os.SEEK_END)
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            os.fsync(parent_descriptor)
            return line
        except OSError as exc:
            raise ModelPanelIOError("evidence journal could not be durably appended") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent_descriptor)

    def file_sha256(self, path: Path) -> tuple[str, int]:
        payload = self.read_bytes(path)
        return sha256(payload).hexdigest(), len(payload)

    def require_output_path(self, path: Path) -> Path:
        target = self._lexical_absolute(path)
        if target == self.output_root or self.output_root not in target.parents:
            raise ModelPanelIOError("model-panel artifacts must stay below output/evals")
        self._reject_symlink_ancestors(target)
        resolved = target.resolve(strict=False)
        if resolved == self.output_root or self.output_root not in resolved.parents:
            raise ModelPanelIOError("model-panel artifact path escapes the output root")
        return target

    def _open_private_parent(self, target: Path) -> int:
        self._require_private_directory(target.parent)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            return os.open(target.parent, flags)
        except OSError as exc:
            raise ModelPanelIOError("private evidence parent is unavailable") from exc

    def _require_private_directory(self, path: Path) -> None:
        try:
            metadata = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise ModelPanelIOError("private evidence directory is unavailable") from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.geteuid()
        ):
            raise ModelPanelIOError("evidence directories must have mode 0700")

    def _require_private_file(self, metadata: os.stat_result, *, label: str) -> None:
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
        ):
            raise ModelPanelIOError(f"{label} must be an owned, unlinked 0600 regular file")

    def _create_private_tree(self, target: Path) -> None:
        """Create missing evidence descendants privately; the final directory is exclusive."""

        if not self.output_root.exists():
            try:
                self.output_root.mkdir(mode=0o700, parents=True, exist_ok=False)
                os.chmod(self.output_root, 0o700)
            except OSError as exc:
                raise ModelPanelIOError("model-panel evidence root could not be created") from exc
        current = self.output_root
        relative = target.relative_to(self.output_root)
        for index, component in enumerate(relative.parts):
            current = current / component
            is_target = index == len(relative.parts) - 1
            try:
                current.mkdir(mode=0o700, exist_ok=False)
                os.chmod(current, 0o700)
            except FileExistsError as exc:
                if is_target:
                    raise ModelPanelIOError("model-panel run directory must be new") from exc
                self._require_private_directory(current)
            except OSError as exc:
                raise ModelPanelIOError("model-panel run directory must be new") from exc

    def _reject_symlink_ancestors(self, target: Path) -> None:
        current = self.repository_root
        try:
            relative = target.relative_to(self.repository_root)
        except ValueError as exc:
            raise ModelPanelIOError("evidence path is outside the repository") from exc
        for component in relative.parts:
            current = current / component
            if current.is_symlink():
                raise ModelPanelIOError("evidence paths cannot contain symbolic links")

    def _lexical_absolute(self, path: Path) -> Path:
        candidate = path if path.is_absolute() else self.repository_root / path
        return Path(os.path.abspath(candidate))

    def _git_tracked(self, path: Path) -> bool:
        relative = path.relative_to(self.repository_root)
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.repository_root),
                "ls-files",
                "--error-unmatch",
                "--",
                str(relative),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0

    def _git_ignored(self, path: Path) -> bool:
        relative = path.relative_to(self.repository_root)
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.repository_root),
                "check-ignore",
                "--no-index",
                "--",
                str(relative),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
