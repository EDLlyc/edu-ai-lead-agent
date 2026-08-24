from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
from urllib.parse import urlsplit

from minio import Minio
from minio.error import S3Error

from app.application.ports.ip_assets import IpAssetObjectDescriptor
from app.core.config import Settings
from app.core.errors import ConflictError
from app.domain.ip_assets import IP_ASSET_MAX_BYTES, ValidatedIpAssetUpload


class MinioIpAssetStore:
    """Private content-addressed storage for immutable shared-library originals."""

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

    async def put_immutable(self, upload: ValidatedIpAssetUpload) -> IpAssetObjectDescriptor:
        if not upload.body or len(upload.body) > IP_ASSET_MAX_BYTES:
            raise ValueError("IP asset original exceeded the configured limit")
        key = f"ip-assets/originals/sha256/{upload.sha256[:2]}/{upload.sha256}.{upload.extension}"
        descriptor = IpAssetObjectDescriptor(
            bucket=self._bucket,
            object_key=key,
            media_type=upload.media_type,
            byte_size=upload.byte_size,
            sha256=upload.sha256,
        )
        await asyncio.to_thread(self._put_or_verify, descriptor, upload.body)
        return descriptor

    async def get_verified(self, descriptor: IpAssetObjectDescriptor) -> bytes:
        return await asyncio.to_thread(self._get_verified, descriptor)

    def _put_or_verify(self, descriptor: IpAssetObjectDescriptor, body: bytes) -> None:
        try:
            stat = self._client.stat_object(descriptor.bucket, descriptor.object_key)
        except S3Error as error:
            if error.code not in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                raise
            if error.code == "NoSuchBucket":
                self._client.make_bucket(descriptor.bucket)
        else:
            metadata = stat.metadata or {}
            digest = metadata.get("x-amz-meta-sha256") or metadata.get("sha256")
            if stat.size != descriptor.byte_size or digest != descriptor.sha256:
                raise ConflictError("immutable IP asset metadata does not match content")
            # Object metadata is not proof of content. Verify the existing immutable bytes before
            # allowing a database row to reference them.
            self._get_verified(descriptor)
            return
        self._client.put_object(
            descriptor.bucket,
            descriptor.object_key,
            BytesIO(body),
            descriptor.byte_size,
            content_type=descriptor.media_type,
            metadata={"sha256": descriptor.sha256, "private": "true"},
        )
        self._get_verified(descriptor)

    def _get_verified(self, descriptor: IpAssetObjectDescriptor) -> bytes:
        if descriptor.bucket != self._bucket:
            raise ConflictError("IP asset object is outside the private store")
        extension = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
        }.get(descriptor.media_type)
        expected_key = (
            f"ip-assets/originals/sha256/{descriptor.sha256[:2]}/{descriptor.sha256}.{extension}"
            if extension is not None
            else ""
        )
        if descriptor.object_key != expected_key:
            raise ConflictError("IP asset object key is not content addressed")
        response = self._client.get_object(descriptor.bucket, descriptor.object_key)
        try:
            chunks: list[bytes] = []
            size = 0
            for chunk in response.stream(64 * 1024):
                size += len(chunk)
                if size > IP_ASSET_MAX_BYTES:
                    raise ConflictError("stored IP asset exceeds the configured limit")
                chunks.append(chunk)
            body = b"".join(chunks)
        finally:
            response.close()
            response.release_conn()
        if (
            len(body) != descriptor.byte_size
            or hashlib.sha256(body).hexdigest() != descriptor.sha256
        ):
            raise ConflictError("stored IP asset checksum does not match metadata")
        return body
