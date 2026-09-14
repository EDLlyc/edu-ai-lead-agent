"""Private fixed-namespace receipts: no caller-selected operation replay identity."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.application.ports.wechat_official_account_manual_draft import ManualDraftError, require


def canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def fingerprint(payload: dict[str, Any]) -> str:
    return sha256(canonical(payload)).hexdigest()


def _file_ok(fd: int) -> None:
    info = os.fstat(fd)
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and info.st_uid == os.getuid()
        and not info.st_mode & 0o077,
        "manual_journal_unsafe_file",
    )


class LocalManualDraftJournal:
    """Hold one account lock; all descriptor-relative receipts are create-only/fsynced."""

    def __init__(self, artifact_root: Path, account: str) -> None:
        require(re.fullmatch(r"[0-9a-f]{64}", account) is not None, "manual_account_invalid")
        base = artifact_root.absolute()
        require(base != Path("/"), "manual_journal_unsafe_root")
        # Do not follow symlinks in configured root ancestry, including intermediate components.
        current = Path(base.anchor)
        for part in base.parts[1:]:
            current /= part
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
            require(current.is_dir() and not current.is_symlink(), "manual_journal_unsafe_root")
        root_fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in ("manual-v1", account):
                try:
                    os.mkdir(part, mode=0o700, dir_fd=root_fd)
                    os.fsync(root_fd)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
                os.close(root_fd)
                root_fd = child
                info = os.fstat(root_fd)
                require(
                    info.st_uid == os.getuid() and not info.st_mode & 0o077,
                    "manual_journal_unsafe_root",
                )
            self._directory = root_fd
            self._lock = os.open(
                "lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=root_fd,
            )
            _file_ok(self._lock)
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ManualDraftError("manual_journal_locked") from None
        except BaseException:
            if hasattr(self, "_lock"):
                os.close(self._lock)
            os.close(root_fd)
            raise

    def close(self) -> None:
        os.close(self._lock)
        os.close(self._directory)

    def manual_history(self, account: str) -> tuple[tuple[str, str, bool], ...]:
        """Only canonical account/article/receipt hashes cross into the history bridge."""
        names = os.listdir(self._directory)
        require(len(names) <= 10000, "manual_history_scan_overflow")
        for name in names:
            if re.fullmatch(r"[0-9a-f]{64}-add-(intent|ack)\.json", name):
                require(name[:64] + "-claim.json" in names, "manual_history_orphan_receipt")
        rows: list[tuple[str, str, bool]] = []
        for name in sorted(names):
            if re.fullmatch(r"[0-9a-f]{64}-claim\.json", name) is None:
                continue
            article = name[:64]
            claim = self.read(name)
            require(claim is not None and claim.get("account") == account, "manual_history_account")
            assert claim is not None
            binding = claim.get("binding")
            require(
                isinstance(binding, dict) and binding.get("raw_article") == article,
                "manual_history_article",
            )
            assert isinstance(binding, dict)
            if binding.get("version") == "single-edition-claim-v1":
                # SQL already owns this prospective route; do not import it as a manual owner.
                continue
            require(
                binding.get("version")
                in {"manual-draft-binding-v1", "manual-local-editorial-preview-binding-v1"},
                "manual_history_version",
            )
            intent = self.read(article + "-add-intent.json")
            ack = self.read(article + "-add-ack.json")
            if intent is not None:
                require(
                    intent.get("binding") == fingerprint(binding) and intent.get("step") == "add",
                    "manual_history_intent",
                )
            if ack is not None:
                require(
                    intent is not None and ack.get("intent_sha256") == fingerprint(intent),
                    "manual_history_ack",
                )
            # Even a claim-only/unknown operation remains reserved, not "never delivered".
            rows.append(
                (
                    article,
                    fingerprint({"claim": claim, "intent": intent, "ack": ack}),
                    ack is not None,
                )
            )
        return tuple(rows)

    def _name(self, name: str) -> str:
        require(
            re.fullmatch(r"[a-z0-9_-]{1,180}\.json", name) is not None,
            "manual_journal_invalid_name",
        )
        return name

    def read(self, name: str) -> dict[str, Any] | None:
        try:
            fd = os.open(
                self._name(name),
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=self._directory,
            )
        except FileNotFoundError:
            return None
        try:
            _file_ok(fd)
            before = os.fstat(fd)
            require(before.st_size <= 4 * 1024 * 1024, "manual_journal_oversized")
            with os.fdopen(os.dup(fd), "rb") as stream:
                raw = stream.read(4 * 1024 * 1024 + 1)
            after = os.fstat(fd)
            require(
                (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                "manual_journal_changed",
            )
            envelope = json.loads(raw)
            require(
                isinstance(envelope, dict) and set(envelope) == {"payload", "sha256"},
                "manual_journal_corrupt",
            )
            payload = envelope["payload"]
            require(
                isinstance(payload, dict) and fingerprint(payload) == envelope["sha256"],
                "manual_journal_corrupt",
            )
            require(canonical(envelope) == raw, "manual_journal_corrupt")
            return dict(payload)
        finally:
            os.close(fd)

    def write(self, name: str, payload: dict[str, Any]) -> None:
        raw = canonical({"payload": payload, "sha256": fingerprint(payload)})
        fd = os.open(
            self._name(name),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self._directory,
        )
        try:
            with os.fdopen(os.dup(fd), "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(self._directory)
        finally:
            os.close(fd)
