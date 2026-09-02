"""Local content-addressed artifact owner for production weekly checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Final, cast

from app.domain.official_account_weekly_dag import WeeklyDagArtifact

WEEKLY_PRODUCTION_ARTIFACT_REF_VERSION: Final = "weekly-production-v1"
_MAX_JSON_BYTES: Final = 2 * 1024 * 1024


class LocalWeeklyProductionArtifactOwner:
    """Own JSON payloads while DAG rows retain only safe content addresses."""

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()
        if self._root == Path(self._root.anchor):
            raise ValueError("weekly production artifact root cannot be a filesystem root")

    def put_json(self, payload: dict[str, object]) -> WeeklyDagArtifact:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if not body or len(body) > _MAX_JSON_BYTES:
            raise ValueError("weekly production checkpoint size is invalid")
        fingerprint = hashlib.sha256(body).hexdigest()
        target = self._path(fingerprint)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_symlink() or target.read_bytes() != body:
                raise ValueError("weekly production checkpoint identity changed")
        else:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{fingerprint}.",
                suffix=".tmp",
                dir=target.parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    temporary.rename(target)
                except OSError:
                    if not target.exists() or target.read_bytes() != body:
                        raise
            finally:
                if temporary.exists():
                    temporary.unlink()
        return WeeklyDagArtifact(
            opaque_ref=f"{WEEKLY_PRODUCTION_ARTIFACT_REF_VERSION}:{fingerprint}",
            fingerprint=fingerprint,
            media_type="application/json",
            byte_size=len(body),
        )

    def get_json(self, artifact: WeeklyDagArtifact) -> dict[str, object]:
        expected_ref = f"{WEEKLY_PRODUCTION_ARTIFACT_REF_VERSION}:{artifact.fingerprint}"
        if (
            artifact.opaque_ref != expected_ref
            or artifact.media_type != "application/json"
            or artifact.byte_size < 1
            or artifact.byte_size > _MAX_JSON_BYTES
        ):
            raise ValueError("weekly production checkpoint metadata is invalid")
        path = self._path(artifact.fingerprint)
        if not path.is_file() or path.is_symlink():
            raise ValueError("weekly production checkpoint is unavailable")
        body = path.read_bytes()
        if (
            len(body) != artifact.byte_size
            or hashlib.sha256(body).hexdigest() != artifact.fingerprint
        ):
            raise ValueError("weekly production checkpoint bytes changed")
        payload = json.loads(body.decode("utf-8"), object_pairs_hook=_reject_duplicates)
        if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
            raise ValueError("weekly production checkpoint must be a JSON object")
        return cast(dict[str, object], payload)

    def get_json_by_fingerprint(self, fingerprint: str) -> dict[str, object]:
        path = self._path(fingerprint)
        if not path.is_file() or path.is_symlink():
            raise ValueError("weekly production input snapshot is unavailable")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != fingerprint:
            raise ValueError("weekly production input snapshot changed")
        return self.get_json(
            WeeklyDagArtifact(
                opaque_ref=f"{WEEKLY_PRODUCTION_ARTIFACT_REF_VERSION}:{fingerprint}",
                fingerprint=fingerprint,
                media_type="application/json",
                byte_size=len(body),
            )
        )

    def _path(self, fingerprint: str) -> Path:
        if len(fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in fingerprint
        ):
            raise ValueError("weekly production checkpoint fingerprint is invalid")
        target = self._root / "checkpoints" / f"{fingerprint}.json"
        if target.parent != self._root / "checkpoints":
            raise ValueError("weekly production checkpoint escaped its root")
        return target


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("weekly production checkpoint has duplicate fields")
        result[key] = value
    return result


__all__ = [
    "WEEKLY_PRODUCTION_ARTIFACT_REF_VERSION",
    "LocalWeeklyProductionArtifactOwner",
]
