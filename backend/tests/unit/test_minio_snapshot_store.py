from types import SimpleNamespace

import pytest
from app.core.errors import ConflictError
from app.domain.entities import SnapshotDescriptor
from app.infrastructure.storage.minio_snapshot_store import MinioSnapshotStore


class ExistingObjectWithoutHashClient:
    def stat_object(self, _bucket: str, _object_key: str) -> SimpleNamespace:
        return SimpleNamespace(size=4, metadata={})


def test_existing_object_without_sha256_metadata_is_not_trusted_by_size() -> None:
    store = object.__new__(MinioSnapshotStore)
    store._client = ExistingObjectWithoutHashClient()  # type: ignore[attr-defined]
    descriptor = SnapshotDescriptor(
        bucket="snapshots",
        object_key="source-snapshots/sha256/00/digest",
        media_type="text/plain",
        byte_size=4,
        sha256="digest",
    )

    with pytest.raises(ConflictError, match="metadata"):
        store._put_or_verify(descriptor, b"same")
