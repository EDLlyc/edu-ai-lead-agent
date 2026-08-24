from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import urlsplit

from minio import Minio
from minio.error import S3Error

from app.core.config import Settings
from app.core.errors import ConflictError
from app.domain.image_generation import image_checksum, image_content_key


@dataclass(frozen=True, slots=True)
class ImageObjectDescriptor:
    bucket: str
    object_key: str
    media_type: str
    byte_size: int
    sha256: str


class MinioImageStore:
    """Private, immutable generated-image storage; object keys never cross the API boundary."""

    def __init__(self, settings: Settings, client: Minio | None = None) -> None:
        endpoint = urlsplit(settings.minio_endpoint)
        if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
            raise ValueError("MINIO_ENDPOINT must be an HTTP(S) endpoint")
        self._bucket = settings.minio_bucket
        self._max_bytes = settings.image_max_download_bytes
        self._client = client or Minio(
            endpoint.netloc,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
        )

    async def put_immutable(
        self, body: bytes, *, media_type: str = "image/png"
    ) -> ImageObjectDescriptor:
        if not body or len(body) > self._max_bytes:
            raise ValueError("generated image exceeds configured storage limit")
        if media_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError("unsupported generated image media type")
        digest = image_checksum(body)
        descriptor = ImageObjectDescriptor(
            bucket=self._bucket,
            object_key=image_content_key(digest, media_type),
            media_type=media_type,
            byte_size=len(body),
            sha256=digest,
        )
        await asyncio.to_thread(self._put_or_verify, descriptor, body)
        return descriptor

    async def get_bytes(self, descriptor: ImageObjectDescriptor) -> bytes:
        return await asyncio.to_thread(self._get_verified, descriptor)

    async def get_content_addressed_bytes(
        self,
        *,
        media_type: str,
        byte_size: int,
        sha256: str,
    ) -> bytes:
        """Read a generated object from public-safe content metadata only.

        Callers never receive or persist a bucket/object-key projection; this infrastructure
        boundary derives the private location from the immutable checksum.
        """

        return await self.get_bytes(
            ImageObjectDescriptor(
                bucket=self._bucket,
                object_key=image_content_key(sha256, media_type),
                media_type=media_type,
                byte_size=byte_size,
                sha256=sha256,
            )
        )

    def _put_or_verify(self, descriptor: ImageObjectDescriptor, body: bytes) -> None:
        try:
            stat = self._client.stat_object(descriptor.bucket, descriptor.object_key)
        except S3Error as error:
            if error.code not in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                raise
            if error.code == "NoSuchBucket":
                self._client.make_bucket(descriptor.bucket)
        else:
            metadata = stat.metadata or {}
            stored_hash = metadata.get("x-amz-meta-sha256") or metadata.get("sha256")
            if stat.size != descriptor.byte_size or stored_hash != descriptor.sha256:
                raise ConflictError("immutable image object metadata does not match content")
            return
        self._client.put_object(
            descriptor.bucket,
            descriptor.object_key,
            BytesIO(body),
            descriptor.byte_size,
            content_type=descriptor.media_type,
            metadata={"sha256": descriptor.sha256, "private": "true"},
        )

    def _get_verified(self, descriptor: ImageObjectDescriptor) -> bytes:
        if descriptor.bucket != self._bucket:
            raise ConflictError("image object bucket is outside the private store")
        if descriptor.object_key != image_content_key(descriptor.sha256, descriptor.media_type):
            raise ConflictError("image object key is not content addressed")
        response = self._client.get_object(descriptor.bucket, descriptor.object_key)
        try:
            chunks: list[bytes] = []
            byte_count = 0
            for chunk in response.stream(64 * 1024):
                byte_count += len(chunk)
                if byte_count > self._max_bytes:
                    raise ConflictError("stored image exceeds configured limit")
                chunks.append(chunk)
            body = b"".join(chunks)
        finally:
            response.close()
            response.release_conn()
        if len(body) != descriptor.byte_size or image_checksum(body) != descriptor.sha256:
            raise ConflictError("stored image checksum does not match metadata")
        return body
