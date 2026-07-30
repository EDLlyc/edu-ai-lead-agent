from __future__ import annotations

import asyncio
from io import BytesIO
from urllib.parse import urlsplit

from minio import Minio
from minio.error import S3Error

from app.core.config import Settings
from app.core.errors import ConflictError
from app.domain.brand_knowledge import BrandOriginalDescriptor, ValidatedBrandUpload
from app.domain.value_objects import sha256_bytes


class MinioBrandOriginalStore:
    def __init__(self, settings: Settings, client: Minio | None = None) -> None:
        endpoint = urlsplit(settings.minio_endpoint)
        if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
            raise ValueError("MINIO_ENDPOINT must be an HTTP(S) endpoint")
        self._bucket = settings.minio_bucket
        self._max_bytes = settings.brand_upload_max_bytes
        self._client = client or Minio(
            endpoint.netloc,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
        )

    async def put_immutable(self, upload: ValidatedBrandUpload) -> BrandOriginalDescriptor:
        if len(upload.body) > self._max_bytes:
            raise ValueError("brand original exceeded the configured upload limit")
        object_key = f"brand-originals/sha256/{upload.sha256[:2]}/{upload.sha256}"
        descriptor = BrandOriginalDescriptor(
            bucket=self._bucket,
            object_key=object_key,
            media_type=upload.media_type,
            byte_size=len(upload.body),
            sha256=upload.sha256,
        )
        await asyncio.to_thread(self._put_or_verify, descriptor, upload.body)
        return descriptor

    async def get_immutable(self, *, bucket: str, object_key: str, sha256: str) -> bytes:
        return await asyncio.to_thread(self._get_verified, bucket, object_key, sha256)

    def _put_or_verify(self, descriptor: BrandOriginalDescriptor, body: bytes) -> None:
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
                raise ConflictError("immutable brand object metadata does not match content")
            return
        self._client.put_object(
            descriptor.bucket,
            descriptor.object_key,
            BytesIO(body),
            descriptor.byte_size,
            content_type=descriptor.media_type,
            metadata={"sha256": descriptor.sha256, "private": "true"},
        )

    def _get_verified(self, bucket: str, object_key: str, expected_sha256: str) -> bytes:
        response = self._client.get_object(bucket, object_key)
        try:
            chunks: list[bytes] = []
            byte_count = 0
            for chunk in response.stream(64 * 1024):
                byte_count += len(chunk)
                if byte_count > self._max_bytes:
                    raise ConflictError("stored brand original exceeds its configured limit")
                chunks.append(chunk)
            body = b"".join(chunks)
        finally:
            response.close()
            response.release_conn()
        if sha256_bytes(body) != expected_sha256:
            raise ConflictError("stored brand original checksum does not match metadata")
        return body
