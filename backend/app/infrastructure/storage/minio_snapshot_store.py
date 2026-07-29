from __future__ import annotations

import asyncio
from io import BytesIO
from urllib.parse import urlsplit

from minio import Minio
from minio.error import S3Error

from app.core.config import Settings
from app.core.errors import ConflictError
from app.domain.entities import SnapshotDescriptor
from app.domain.value_objects import sha256_bytes


class MinioSnapshotStore:
    def __init__(self, settings: Settings, client: Minio | None = None) -> None:
        endpoint = urlsplit(settings.minio_endpoint)
        if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
            raise ValueError("MINIO_ENDPOINT must be an HTTP(S) endpoint")
        self._bucket = settings.minio_bucket
        self._client = client or Minio(
            endpoint.netloc,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
        )

    async def put_immutable(self, body: bytes, media_type: str) -> SnapshotDescriptor:
        digest = sha256_bytes(body)
        object_key = f"source-snapshots/sha256/{digest[:2]}/{digest}"
        descriptor = SnapshotDescriptor(
            bucket=self._bucket,
            object_key=object_key,
            media_type=media_type,
            byte_size=len(body),
            sha256=digest,
        )
        await asyncio.to_thread(self._put_or_verify, descriptor, body)
        return descriptor

    def _put_or_verify(self, descriptor: SnapshotDescriptor, body: bytes) -> None:
        try:
            stat = self._client.stat_object(descriptor.bucket, descriptor.object_key)
        except S3Error as error:
            if error.code not in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                raise
            if error.code == "NoSuchBucket":
                self._client.make_bucket(descriptor.bucket)
        else:
            metadata = stat.metadata or {}
            metadata_hash = metadata.get("x-amz-meta-sha256") or metadata.get("sha256")
            if stat.size != descriptor.byte_size or metadata_hash != descriptor.sha256:
                raise ConflictError("immutable snapshot object metadata does not match content")
            return
        self._client.put_object(
            descriptor.bucket,
            descriptor.object_key,
            BytesIO(body),
            descriptor.byte_size,
            content_type=descriptor.media_type,
            metadata={"sha256": descriptor.sha256},
        )
