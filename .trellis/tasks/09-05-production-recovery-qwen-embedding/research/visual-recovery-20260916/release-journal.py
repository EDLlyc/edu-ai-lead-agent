#!/usr/bin/env python3
"""Read-only seal of today's acknowledged manual override and private draft history."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ACCOUNT = "ae3a5056a1c78eddf728060ecc5287b6a93e48d99e496bc9a22292a2b4eb8fd7"
EDITION = "41b26b7f-e792-56ff-bdfa-643171114056"
RUN = "5e2bbc6e-6bec-4234-b516-7b2c58e198c6"
ARTICLE = "5107bfe9-ae30-4a2d-9fd0-c57a369fa6a8"
ARTICLE_FP = "9104e8fed92d1e852a74d45a158d2ce14fb28ae7daa835dfed556f8f184a37ea"
CONTENT_FP = "6c84df64147d2b6d0fa1dfb2813c2592b27a5d412d6509d14c03b47b9a49d84d"
RECEIPT_FP = "2446ef5e01bdcc59b5624dcfbe9a554d83944bdf71824f105b6b571b405e9882"
PREFIX = "single-" + EDITION.replace("-", "")
AUTH_NAME = "catalog-override-" + EDITION.replace("-", "") + ".json"
CLAIM_NAME = ARTICLE_FP + "-claim.json"
JOURNAL_UID = 999
ROOT = (
    Path(
        "/var/lib/docker/volumes/edu-ai-lead-agent_wechat_mp_draft_artifacts/_data/manual-v1"
    )
    / ACCOUNT
)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "journal_duplicate_key")
        result[key] = value
    return result


def read_file(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and before.st_uid == JOURNAL_UID
            and stat.S_IMODE(before.st_mode) == 0o600
            and 0 < before.st_size <= 4 * 1024 * 1024,
            "journal_file_unsafe",
        )
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            body = stream.read(4 * 1024 * 1024 + 1)
        after = os.fstat(descriptor)
        current = path.lstat()
        key = lambda item: (
            item.st_dev,
            item.st_ino,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
        )
        require(
            key(before) == key(after) == key(current) and len(body) == before.st_size,
            "journal_file_changed",
        )
        return body
    finally:
        os.close(descriptor)


def read_journal(root: Path = ROOT) -> dict:
    require(
        root.is_absolute()
        and not any(path.is_symlink() for path in (root, *root.parents)),
        "journal_root_unsafe",
    )
    info = root.stat()
    require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == JOURNAL_UID
        and stat.S_IMODE(info.st_mode) == 0o700,
        "journal_root_unsafe",
    )
    names = sorted(os.listdir(root))
    require(
        1 <= len(names) <= 10000
        and all(
            name == "lock" or re.fullmatch(r"[a-z0-9_-]{1,180}\.json", name) is not None
            for name in names
        ),
        "journal_names",
    )
    hashes, payloads = {}, {}
    for name in names:
        if name == "lock":
            continue
        body = read_file(root / name)
        envelope = json.loads(body, object_pairs_hook=unique_object)
        require(
            isinstance(envelope, dict)
            and set(envelope) == {"payload", "sha256"}
            and isinstance(envelope["payload"], dict)
            and digest(canonical(envelope["payload"])) == envelope["sha256"]
            and canonical(envelope) == body,
            "journal_envelope",
        )
        hashes[name], payloads[name] = digest(body), envelope["payload"]
    require(names == sorted(os.listdir(root)), "journal_changed_during_read")
    auth = payloads.get(AUTH_NAME)
    require(
        isinstance(auth, dict)
        and set(auth) == {"binding", "authorized_at", "expires_at"},
        "today_override_missing",
    )
    binding = auth["binding"]
    expected = {
        "version": "manual-frozen-catalog-draft-v1",
        "edition_id": EDITION,
        "run_id": RUN,
        "article_id": ARTICLE,
        "account": ACCOUNT,
        "article_fingerprint": ARTICLE_FP,
        "content_fingerprint": CONTENT_FP,
        "media_origin": "existing_frozen_approved_catalog_and_packaged_banners",
        "generated": False,
        "draft_only": True,
        "max_attempts": 1,
    }
    require(
        isinstance(binding, dict)
        and all(
            type(binding.get(k)) is type(v) and binding[k] == v
            for k, v in expected.items()
        ),
        "today_override_binding",
    )
    media = binding.get("media")
    require(isinstance(media, list) and len(media) == 8, "today_override_media")
    begin, end = (
        datetime.fromisoformat(auth[key]) for key in ("authorized_at", "expires_at")
    )
    require(
        begin.utcoffset() is not None
        and end.utcoffset() is not None
        and begin.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        == "2026-09-16"
        and end.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat() == "2026-09-16"
        and timedelta(0) < end - begin <= timedelta(hours=2),
        "today_override_deadline",
    )
    operation_binding = digest(
        canonical(
            {
                "edition": EDITION,
                "article": ARTICLE_FP,
                "content": CONTENT_FP,
                "account": ACCOUNT,
                "policy": "single-write-journal-v1",
                "max_attempts": 1,
            }
        )
    )
    require(
        payloads.get(CLAIM_NAME)
        == {
            "account": ACCOUNT,
            "binding": {
                "version": "single-edition-claim-v1",
                "raw_article": ARTICLE_FP,
                "edition_id": EDITION,
                "fingerprint": operation_binding,
            },
        },
        "today_claim_changed",
    )
    step_names = [*(f"inline-{i}" for i in range(7)), "thumb", "add"]
    exact_steps = {
        f"{PREFIX}-{step}-1-{suffix}.json"
        for step in step_names
        for suffix in ("intent", "ack")
    }
    require(
        {name for name in hashes if name.startswith(PREFIX + "-")} == exact_steps,
        "today_step_names",
    )
    for number, step in enumerate(step_names):
        intent_name, ack_name = (
            f"{PREFIX}-{step}-1-{suffix}.json" for suffix in ("intent", "ack")
        )
        intent, ack = payloads[intent_name], payloads[ack_name]
        require(
            set(intent) == {"binding", "step", "attempt", "request"}
            and intent["binding"] == operation_binding
            and intent["step"] == step
            and type(intent["attempt"]) is int
            and intent["attempt"] == 1
            and isinstance(intent["request"], dict),
            "today_intent_changed",
        )
        require(
            set(ack) == {"intent_sha256", "value"}
            and ack["intent_sha256"] == digest(canonical(intent))
            and isinstance(ack["value"], str)
            and bool(ack["value"]),
            "today_ack_changed",
        )
        if step == "add":
            require(
                digest(ack["value"].encode()) == RECEIPT_FP
                and intent["request"].get("content_source_url") is None,
                "today_receipt_changed",
            )
        else:
            require(
                intent["request"].get("sha256") == media[number].get("sha256"),
                "today_media_changed",
            )
    target_names = [AUTH_NAME, CLAIM_NAME, *sorted(exact_steps)]
    result = {
        "version": "wechat-draft-history-seal-v1",
        "today_draft_already_created": True,
        "edition_id": EDITION,
        "article_fingerprint": ARTICLE_FP,
        "content_fingerprint": CONTENT_FP,
        "draft_receipt_fingerprint": RECEIPT_FP,
        "file_count": len(hashes),
        "file_sha256": hashes,
        "files_sha256": digest(canonical(hashes)),
        "target_file_sha256": {name: hashes[name] for name in target_names},
        "acknowledged_writes": 9,
        "readback_verified": False,
    }
    return validate_snapshot(result)


def validate_snapshot(value: object) -> dict:
    keys = {
        "version",
        "today_draft_already_created",
        "edition_id",
        "article_fingerprint",
        "content_fingerprint",
        "draft_receipt_fingerprint",
        "file_count",
        "file_sha256",
        "files_sha256",
        "target_file_sha256",
        "acknowledged_writes",
        "readback_verified",
    }
    require(isinstance(value, dict) and set(value) == keys, "journal_snapshot_shape")
    require(
        value["version"] == "wechat-draft-history-seal-v1"
        and value["today_draft_already_created"] is True
        and value["edition_id"] == EDITION
        and value["article_fingerprint"] == ARTICLE_FP
        and value["content_fingerprint"] == CONTENT_FP
        and value["draft_receipt_fingerprint"] == RECEIPT_FP
        and type(value["acknowledged_writes"]) is int
        and value["acknowledged_writes"] == 9
        and value["readback_verified"] is False,
        "journal_snapshot_identity",
    )
    hashes = value["file_sha256"]
    require(
        isinstance(hashes, dict)
        and type(value["file_count"]) is int
        and value["file_count"] == len(hashes)
        and 20 <= len(hashes) <= 10000
        and all(
            isinstance(k, str)
            and re.fullmatch(r"[a-z0-9_-]{1,180}\.json", k) is not None
            and isinstance(v, str)
            and re.fullmatch(r"[0-9a-f]{64}", v) is not None
            for k, v in hashes.items()
        )
        and digest(canonical(hashes)) == value["files_sha256"],
        "journal_snapshot_hashes",
    )
    names = {
        AUTH_NAME,
        CLAIM_NAME,
        *(
            f"{PREFIX}-{step}-1-{suffix}.json"
            for step in [*(f"inline-{i}" for i in range(7)), "thumb", "add"]
            for suffix in ("intent", "ack")
        ),
    }
    require(
        isinstance(value["target_file_sha256"], dict)
        and set(value["target_file_sha256"]) == names
        and names <= hashes.keys()
        and value["target_file_sha256"] == {name: hashes[name] for name in names},
        "journal_snapshot_target",
    )
    return value


if __name__ == "__main__":
    try:
        print(canonical(read_journal()).decode())
    except Exception:  # noqa: BLE001 -- never emit private payload/URL/media ID
        raise SystemExit("journal_snapshot_failed") from None
