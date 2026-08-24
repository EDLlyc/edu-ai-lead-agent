"""Shared, fail-closed byte resolution for local official-account media.

The HTTP media route and the explicit local export command deliberately share this
resolver.  It keeps private storage details inside infrastructure while checking
the durable media row against the immutable fixture, approved-catalog, or source
image lineage before a byte leaves that boundary.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import (
    ImageArtifactModel,
    OfficialAccountGeneratedVisualModel,
    OfficialAccountLocalMediaModel,
)
from app.infrastructure.official_account_catalog import LocalOfficialAccountCatalogMediaProvider
from app.infrastructure.official_account_local import (
    FIXTURE_BODY_IMAGE_BYTE_SIZES,
    FIXTURE_BODY_IMAGE_SHA256S,
    FIXTURE_BODY_PUBLICATION_BYTE_SIZES,
    FIXTURE_BODY_PUBLICATION_MEDIA_TYPE,
    FIXTURE_BODY_PUBLICATION_SHA256S,
    FIXTURE_COVER_BYTE_SIZE,
    FIXTURE_COVER_MEDIA_TYPE,
    FIXTURE_COVER_PUBLICATION_BYTE_SIZE,
    FIXTURE_COVER_PUBLICATION_MEDIA_TYPE,
    FIXTURE_COVER_PUBLICATION_SHA256,
    FIXTURE_COVER_SHA256,
    FIXTURE_IMAGE_BYTE_SIZE,
    FIXTURE_IMAGE_MEDIA_TYPE,
    FIXTURE_IMAGE_SHA256,
    fixture_media_path,
)
from app.infrastructure.storage.minio_image_store import ImageObjectDescriptor, MinioImageStore


class OfficialAccountMediaIntegrityError(ValueError):
    """A persisted local-media row can no longer be verified safely."""


@dataclass(frozen=True, slots=True)
class OfficialAccountPersistedMedia:
    """The small durable-media projection needed outside a database transaction."""

    local_media_id: str
    source_image_artifact_id: UUID | None
    fixture_id: str | None
    role: str
    ordinal: int
    media_type: str
    byte_size: int
    sha256: str
    descriptor: dict[str, Any]
    generated_visual_id: UUID | None = None
    run_id: UUID | None = None
    render_version_id: UUID | None = None


def persisted_media_snapshot(
    media: OfficialAccountLocalMediaModel,
) -> OfficialAccountPersistedMedia:
    descriptor = getattr(media, "descriptor", {})
    if not isinstance(descriptor, dict):
        raise OfficialAccountMediaIntegrityError("local media descriptor is invalid")
    return OfficialAccountPersistedMedia(
        local_media_id=media.local_media_id,
        source_image_artifact_id=media.source_image_artifact_id,
        fixture_id=media.fixture_id,
        role=media.role,
        ordinal=media.ordinal,
        media_type=media.media_type,
        byte_size=media.byte_size,
        sha256=media.sha256,
        descriptor=dict(descriptor),
        generated_visual_id=getattr(media, "generated_visual_id", None),
        run_id=getattr(media, "run_id", None),
        render_version_id=getattr(media, "render_version_id", None),
    )


class OfficialAccountLocalMediaResolver:
    """Resolve persisted media without exposing storage bucket, key, or path."""

    def __init__(
        self,
        *,
        image_asset_manifest: str | None,
        image_store: MinioImageStore | None,
    ) -> None:
        self._image_asset_manifest = image_asset_manifest
        self._image_store = image_store

    async def read_verified_bytes(
        self,
        *,
        session: AsyncSession,
        media: OfficialAccountLocalMediaModel | OfficialAccountPersistedMedia,
    ) -> bytes:
        snapshot = (
            media
            if isinstance(media, OfficialAccountPersistedMedia)
            else persisted_media_snapshot(media)
        )
        if snapshot.descriptor.get("source_kind") == "approved_catalog":
            await _release_read_transaction(session)
            return await self._read_catalog_bytes(snapshot)
        if snapshot.descriptor.get("source_kind") == "generated_visual":
            return await self._read_generated_visual_bytes(session=session, media=snapshot)
        if snapshot.fixture_id is not None:
            await _release_read_transaction(session)
            return await self._read_fixture_bytes(snapshot)
        return await self._read_source_image_bytes(session=session, media=snapshot)

    async def _read_catalog_bytes(self, media: OfficialAccountPersistedMedia) -> bytes:
        descriptor = media.descriptor
        catalog_ref = descriptor.get("catalog_asset_ref")
        catalog_version = descriptor.get("catalog_version")
        source_master_sha256 = descriptor.get("source_master_sha256")
        if (
            not isinstance(catalog_ref, str)
            or len(catalog_ref) != 16
            or not isinstance(catalog_version, str)
            or not catalog_version
            or not isinstance(source_master_sha256, str)
            or len(source_master_sha256) != 64
            or media.fixture_id != f"catalog:{catalog_ref}"
            or media.source_image_artifact_id is not None
            or media.role != "body"
            or media.media_type != "image/jpeg"
            or not self._image_asset_manifest
        ):
            raise OfficialAccountMediaIntegrityError("catalog media lineage is invalid")
        try:
            provider = LocalOfficialAccountCatalogMediaProvider(self._image_asset_manifest)
            body = await provider.read_publication_bytes(
                catalog_asset_ref=catalog_ref,
                catalog_version=catalog_version,
                source_master_sha256=source_master_sha256,
                publication_sha256=media.sha256,
            )
        except ValueError as error:
            raise OfficialAccountMediaIntegrityError(
                "catalog media integrity check failed"
            ) from error
        _assert_bytes_match(media, body, "catalog media integrity check failed")
        return body

    async def _read_fixture_bytes(self, media: OfficialAccountPersistedMedia) -> bytes:
        try:
            path = fixture_media_path(role=media.role, checksum=media.sha256)
            body = await asyncio.to_thread(path.read_bytes)
        except (OSError, ValueError) as error:
            raise OfficialAccountMediaIntegrityError(
                "fixture media integrity check failed"
            ) from error
        expected_media_type, expected_byte_size = _fixture_metadata(media.sha256)
        if (
            media.fixture_id != "official-account-article-v1"
            or media.role not in {"body", "cover"}
            or media.media_type != expected_media_type
            or media.byte_size != expected_byte_size
            or media.sha256
            not in {
                FIXTURE_IMAGE_SHA256,
                FIXTURE_COVER_SHA256,
                FIXTURE_COVER_PUBLICATION_SHA256,
                *FIXTURE_BODY_IMAGE_SHA256S,
                *FIXTURE_BODY_PUBLICATION_SHA256S,
            }
        ):
            raise OfficialAccountMediaIntegrityError("fixture media integrity check failed")
        _assert_bytes_match(media, body, "fixture media integrity check failed")
        return body

    async def _read_generated_visual_bytes(
        self,
        *,
        session: AsyncSession,
        media: OfficialAccountPersistedMedia,
    ) -> bytes:
        if (
            media.generated_visual_id is None
            or media.run_id is None
            or media.render_version_id is None
            or media.source_image_artifact_id is not None
            or media.fixture_id is not None
            or media.role != "body"
            or self._image_store is None
        ):
            raise OfficialAccountMediaIntegrityError("generated visual media lineage is invalid")
        visual = await session.get(OfficialAccountGeneratedVisualModel, media.generated_visual_id)
        if (
            visual is None
            or visual.run_id != media.run_id
            or visual.render_version_id != media.render_version_id
            or visual.status != "ready"
            or visual.ordinal != media.ordinal
            or visual.media_type != media.media_type
            or visual.byte_size != media.byte_size
            or visual.sha256 != media.sha256
        ):
            raise OfficialAccountMediaIntegrityError("generated visual metadata does not match")
        await _release_read_transaction(session)
        try:
            body = await self._image_store.get_content_addressed_bytes(
                media_type=media.media_type,
                byte_size=media.byte_size,
                sha256=media.sha256,
            )
        except Exception as error:
            raise OfficialAccountMediaIntegrityError(
                "generated visual source image is unavailable"
            ) from error
        _assert_bytes_match(media, body, "generated visual metadata does not match")
        return body

    async def _read_source_image_bytes(
        self,
        *,
        session: AsyncSession,
        media: OfficialAccountPersistedMedia,
    ) -> bytes:
        if media.source_image_artifact_id is None:
            raise OfficialAccountMediaIntegrityError("local media source lineage is incomplete")
        image = await session.get(ImageArtifactModel, media.source_image_artifact_id)
        if image is None or any(
            value is None
            for value in (
                image.bucket,
                image.object_key,
                image.media_type,
                image.byte_size,
                image.sha256,
            )
        ):
            raise OfficialAccountMediaIntegrityError("local media source image is unavailable")
        image_descriptor = ImageObjectDescriptor(
            bucket=cast(str, image.bucket),
            object_key=cast(str, image.object_key),
            media_type=cast(str, image.media_type),
            byte_size=cast(int, image.byte_size),
            sha256=cast(str, image.sha256),
        )
        if (
            image.media_type != media.media_type
            or image.byte_size != media.byte_size
            or image.sha256 != media.sha256
            or self._image_store is None
        ):
            raise OfficialAccountMediaIntegrityError("local media source metadata does not match")
        await _release_read_transaction(session)
        try:
            body = await self._image_store.get_bytes(image_descriptor)
        except Exception as error:
            raise OfficialAccountMediaIntegrityError(
                "local media source image is unavailable"
            ) from error
        _assert_bytes_match(media, body, "local media source metadata does not match")
        return body


def _fixture_metadata(checksum: str) -> tuple[str, int]:
    if checksum == FIXTURE_COVER_PUBLICATION_SHA256:
        return FIXTURE_COVER_PUBLICATION_MEDIA_TYPE, FIXTURE_COVER_PUBLICATION_BYTE_SIZE
    if checksum == FIXTURE_COVER_SHA256:
        return FIXTURE_COVER_MEDIA_TYPE, FIXTURE_COVER_BYTE_SIZE
    if checksum in FIXTURE_BODY_PUBLICATION_SHA256S:
        ordinal = FIXTURE_BODY_PUBLICATION_SHA256S.index(checksum)
        return FIXTURE_BODY_PUBLICATION_MEDIA_TYPE, FIXTURE_BODY_PUBLICATION_BYTE_SIZES[ordinal]
    if checksum in FIXTURE_BODY_IMAGE_SHA256S:
        ordinal = FIXTURE_BODY_IMAGE_SHA256S.index(checksum)
        return FIXTURE_IMAGE_MEDIA_TYPE, FIXTURE_BODY_IMAGE_BYTE_SIZES[ordinal]
    return FIXTURE_IMAGE_MEDIA_TYPE, FIXTURE_IMAGE_BYTE_SIZE


def _assert_bytes_match(
    media: OfficialAccountPersistedMedia,
    body: bytes,
    message: str,
) -> None:
    if len(body) != media.byte_size or sha256(body).hexdigest() != media.sha256:
        raise OfficialAccountMediaIntegrityError(message)


async def _release_read_transaction(session: AsyncSession) -> None:
    """Finish the read before local storage/catalog I/O begins.

    Unit tests use small session doubles without ``rollback``; real SQLAlchemy
    sessions expose it and this keeps object reads outside a database transaction.
    """

    rollback = getattr(session, "rollback", None)
    if rollback is not None:
        await rollback()
