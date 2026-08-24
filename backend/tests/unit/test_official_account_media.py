from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.infrastructure.official_account_local import (
    fixture_body_publication_path,
    fixture_cover_path,
)
from app.infrastructure.official_account_media import (
    OfficialAccountLocalMediaResolver,
    OfficialAccountMediaIntegrityError,
)


class _Session:
    def __init__(self, image: object | None = None) -> None:
        self.image = image
        self.rollback_count = 0

    async def get(self, _model: object, _identifier: object) -> object | None:
        return self.image

    async def rollback(self) -> None:
        self.rollback_count += 1


@pytest.mark.asyncio
async def test_catalog_media_resolution_revalidates_persisted_publication_checksum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = fixture_body_publication_path(0).read_bytes()
    checksum = sha256(body).hexdigest()
    catalog_ref = "a" * 16

    class CatalogProvider:
        def __init__(self, manifest: str) -> None:
            assert manifest == "approved-manifest.json"

        async def read_publication_bytes(self, **kwargs: object) -> bytes:
            assert kwargs["catalog_asset_ref"] == catalog_ref
            return body

    monkeypatch.setattr(
        "app.infrastructure.official_account_media.LocalOfficialAccountCatalogMediaProvider",
        CatalogProvider,
    )
    media = SimpleNamespace(
        local_media_id="local-media-catalog",
        descriptor={
            "source_kind": "approved_catalog",
            "catalog_asset_ref": catalog_ref,
            "catalog_version": "catalog-v1",
            "source_master_sha256": "b" * 64,
        },
        fixture_id=f"catalog:{catalog_ref}",
        source_image_artifact_id=None,
        role="body",
        ordinal=0,
        media_type="image/jpeg",
        byte_size=len(body),
        sha256=checksum,
    )
    session = _Session()
    resolver = OfficialAccountLocalMediaResolver(
        image_asset_manifest="approved-manifest.json",
        image_store=None,
    )

    assert await resolver.read_verified_bytes(session=session, media=media) == body
    assert session.rollback_count == 1

    invalid = SimpleNamespace(**{**media.__dict__, "sha256": "0" * 64})
    with pytest.raises(OfficialAccountMediaIntegrityError, match="catalog media integrity"):
        await resolver.read_verified_bytes(session=_Session(), media=invalid)


@pytest.mark.asyncio
async def test_source_image_media_resolution_fails_closed_before_any_export_write() -> None:
    expected = fixture_cover_path().read_bytes()
    source_id = uuid4()
    image = SimpleNamespace(
        bucket="private-images",
        object_key="images/sha256/example",
        media_type="image/png",
        byte_size=len(expected),
        sha256=sha256(expected).hexdigest(),
    )
    media = SimpleNamespace(
        local_media_id="local-media-source-cover",
        descriptor={"source_kind": "image_artifact"},
        fixture_id=None,
        source_image_artifact_id=source_id,
        role="cover",
        ordinal=0,
        media_type="image/png",
        byte_size=len(expected),
        sha256=sha256(expected).hexdigest(),
    )

    class Store:
        async def get_bytes(self, _descriptor: object) -> bytes:
            return expected[:-1]

    session = _Session(image)
    resolver = OfficialAccountLocalMediaResolver(
        image_asset_manifest=None,
        image_store=Store(),  # type: ignore[arg-type]
    )

    with pytest.raises(OfficialAccountMediaIntegrityError, match="source metadata"):
        await resolver.read_verified_bytes(session=session, media=media)
    assert session.rollback_count == 1


@pytest.mark.asyncio
async def test_generated_body_visual_resolves_from_content_addressed_store() -> None:
    body = b"generated-local-body-visual"
    checksum = sha256(body).hexdigest()
    visual_id = uuid4()
    run_id = uuid4()
    render_version_id = uuid4()
    visual = SimpleNamespace(
        run_id=run_id,
        render_version_id=render_version_id,
        status="ready",
        ordinal=1,
        media_type="image/png",
        byte_size=len(body),
        sha256=checksum,
    )
    media = SimpleNamespace(
        local_media_id="local-media-generated-body",
        descriptor={"source_kind": "generated_visual"},
        fixture_id=None,
        source_image_artifact_id=None,
        generated_visual_id=visual_id,
        run_id=run_id,
        render_version_id=render_version_id,
        role="body",
        ordinal=1,
        media_type="image/png",
        byte_size=len(body),
        sha256=checksum,
    )

    class Store:
        async def get_content_addressed_bytes(self, **kwargs: object) -> bytes:
            assert kwargs == {
                "media_type": "image/png",
                "byte_size": len(body),
                "sha256": checksum,
            }
            return body

    session = _Session(visual)
    resolver = OfficialAccountLocalMediaResolver(
        image_asset_manifest=None,
        image_store=Store(),  # type: ignore[arg-type]
    )

    assert await resolver.read_verified_bytes(session=session, media=media) == body
    assert session.rollback_count == 1

    wrong_run = SimpleNamespace(**{**visual.__dict__, "run_id": uuid4()})
    with pytest.raises(OfficialAccountMediaIntegrityError, match="metadata does not match"):
        await resolver.read_verified_bytes(session=_Session(wrong_run), media=media)
