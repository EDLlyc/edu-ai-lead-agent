"""Read-only, incident-pinned capture; no generation, queue, or social capability."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from dataclasses import asdict, replace
from io import BytesIO
from pathlib import Path
from uuid import UUID

from app.application.ports.official_account_local import OfficialAccountSourceMedia
from app.core.config import Settings
from app.infrastructure.db.models import (
    ImageArtifactModel,
    MaterialPackageModel,
    OfficialAccountArticleRunModel,
    OfficialAccountArticleVersionModel,
    OfficialAccountLocalMediaModel,
    OfficialAccountRenderVersionModel,
    SourceArticleImageModel,
)
from app.infrastructure.db.official_account_local import (
    material_package_source_snapshot,
)
from app.infrastructure.official_account_catalog import (
    LocalOfficialAccountCatalogMediaProvider,
)
from app.infrastructure.official_account_media import (
    OfficialAccountLocalMediaResolver,
    persisted_media_snapshot,
)
from app.infrastructure.storage.minio_image_store import MinioImageStore
from app.infrastructure.storage.minio_snapshot_store import MinioSnapshotStore
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

RUN = UUID("1c8a0cc8-b960-4b33-82ff-e7204def40f6")
PACKAGE = UUID("198969a7-056d-482b-81f4-8219cbd2106b")
CONTEXT_SHA = "815f1c8f352aa0da0a33c7e7df87c8c7437580b2072864c49644ea0b7f32ed8a"
REFERENCE_REFS = ("0121c4aed51e0312", "5c2a29bbec16ca4f", "bab27fe77a8edff4")
SUFFIX = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def encoded(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")


async def capture(destination: Path) -> None:
    if destination.parent != Path("/tmp") or not destination.name.startswith(
        "edu-ai-visual-source-20260907-"
    ):
        raise ValueError("capture_destination_invalid")
    if destination.exists() or destination.is_symlink():
        raise ValueError("capture_destination_exists")
    settings = Settings()
    engine = create_async_engine(
        settings.database_url.get_secret_value(),
        connect_args={"server_settings": {"default_transaction_read_only": "on"}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    catalog = LocalOfficialAccountCatalogMediaProvider(settings.image_asset_manifest)
    resolver = OfficialAccountLocalMediaResolver(
        image_asset_manifest=settings.image_asset_manifest,
        image_store=MinioImageStore(settings),
        snapshot_store=MinioSnapshotStore(settings),
    )
    files: dict[str, bytes] = {}
    try:
        candidates = await catalog.load_candidates()
        by_ref = {item.catalog_asset_ref: item for item in candidates}
        async with factory() as session:
            run = await session.get(OfficialAccountArticleRunModel, RUN)
            if (
                run is None
                or run.status != "ready"
                or run.material_package_id != PACKAGE
            ):
                raise ValueError("capture_run_identity_invalid")
            article = await session.get(
                OfficialAccountArticleVersionModel, run.active_article_version_id
            )
            render = await session.get(
                OfficialAccountRenderVersionModel, run.active_render_version_id
            )
            package = await session.get(MaterialPackageModel, PACKAGE)
            if article is None or render is None or package is None:
                raise ValueError("capture_lineage_missing")
            image = await session.get(ImageArtifactModel, package.image_artifact_id)
            if image is None or render.article_version_id != article.id:
                raise ValueError("capture_lineage_invalid")
            source = material_package_source_snapshot(package, image)
            if source.source_fingerprint != run.source_fingerprint:
                raise ValueError("capture_source_drift")
            if article.audit_snapshot.get("status") != "accepted":
                raise ValueError("capture_text_audit_not_accepted")
            rows = tuple(
                (
                    await session.scalars(
                        select(OfficialAccountLocalMediaModel)
                        .where(
                            OfficialAccountLocalMediaModel.run_id == RUN,
                            OfficialAccountLocalMediaModel.role.in_(
                                ("body", "context")
                            ),
                        )
                        .order_by(
                            OfficialAccountLocalMediaModel.role,
                            OfficialAccountLocalMediaModel.ordinal,
                        )
                    )
                ).all()
            )
            bodies = [row for row in rows if row.role == "body"]
            contexts = [row for row in rows if row.role == "context"]
            if (
                len(bodies) != 5
                or len(contexts) != 1
                or contexts[0].sha256 != CONTEXT_SHA
            ):
                raise ValueError("capture_media_cohort_invalid")
            files["article.json"] = encoded(article.article_payload)
            files["source.json"] = encoded(source.model_dump(mode="json"))
            snapshot: dict[str, object] = {
                "article_version_id": str(article.id),
                "render_version_id": str(render.id),
                "render_fingerprint": render.render_fingerprint,
                "article_created_at": article.created_at.isoformat(),
                "validation_issues": article.validation_snapshot.get("issues", []),
                "audit": {
                    "accepted": article.audit_snapshot["accepted"],
                    "issue_codes": article.audit_snapshot.get("issue_codes", []),
                    "claim_ids": article.audit_snapshot.get("claim_ids", []),
                },
            }
            body_metadata = []
            # Media resolution rolls back read transactions; keep already-captured rows detached.
            session.expunge_all()
            for row in bodies:
                candidate = by_ref[row.descriptor["catalog_asset_ref"]]
                body = await resolver.read_verified_bytes(
                    session=session, media=persisted_media_snapshot(row)
                )
                with Image.open(BytesIO(body)) as decoded:
                    width, height = decoded.size
                candidate = replace(
                    candidate,
                    ordinal=row.ordinal,
                    width=width,
                    height=height,
                    assigned_section_index=row.descriptor["assigned_section_index"],
                    selection_reason_code=row.descriptor["selection_reason_code"],
                )
                if (
                    candidate.sha256 != row.sha256
                    or hashlib.sha256(body).hexdigest() != row.sha256
                ):
                    raise ValueError("capture_body_hash_drift")
                body_metadata.append(asdict(candidate))
                files[f"catalog/{row.ordinal}.{SUFFIX[row.media_type]}"] = body
            snapshot["catalog_media"] = body_metadata
            context = contexts[0]
            original = await session.get(
                SourceArticleImageModel, context.source_article_image_id
            )
            if (
                original is None
                or original.status != "ready"
                or original.sha256 != CONTEXT_SHA
            ):
                raise ValueError("capture_original_unavailable")
            context_candidate = OfficialAccountSourceMedia(
                source_image_artifact_id=None,
                fixture_id=None,
                source_article_image_id=original.id,
                media_type=context.media_type,
                byte_size=context.byte_size,
                sha256=context.sha256,
                ordinal=0,
                semantic_label="新闻原图",
                selection_reason="evidence_snapshot_lineage_v1",
                candidate_id=str(original.id),
                alt_text=original.alt_text or original.caption or "新闻原图",
                caption_text=original.caption or "",
                credit=original.credit,
                source_page_url=original.source_page_url,
                image_url=original.final_image_url,
                rights_status=original.rights_status,
                context_only_not_evidence=True,
                width=original.width,
                height=original.height,
                assigned_section_index=context.descriptor["assigned_section_index"],
            )
            context_bytes = await resolver.read_verified_bytes(
                session=session, media=persisted_media_snapshot(context)
            )
            if hashlib.sha256(context_bytes).hexdigest() != CONTEXT_SHA:
                raise ValueError("capture_original_hash_drift")
            snapshot["context_media"] = asdict(context_candidate)
            files[f"context/0.{SUFFIX[context.media_type]}"] = context_bytes
            references = []
            for ordinal, ref in enumerate(REFERENCE_REFS):
                candidate = by_ref[ref]
                body = await catalog.read_publication_bytes(
                    catalog_asset_ref=ref,
                    catalog_version=candidate.catalog_version,
                    source_master_sha256=candidate.source_master_sha256,
                    publication_sha256=candidate.sha256,
                )
                with Image.open(BytesIO(body)) as decoded:
                    width, height = decoded.size
                if min(width, height) < 512:
                    raise ValueError("capture_reference_too_small")
                references.append(
                    asdict(
                        replace(candidate, ordinal=ordinal, width=width, height=height)
                    )
                )
                files[f"references/{ordinal}.{SUFFIX[candidate.media_type]}"] = body
            snapshot["references"] = references
            files["snapshot.json"] = encoded(snapshot)
            await session.rollback()
        manifest = {
            "schema_version": "official-account-visual-preview-input-v1",
            "source_run_id": str(RUN),
            "status": "ready",
            "files": [
                {
                    "path": path,
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "byte_size": len(body),
                }
                for path, body in sorted(files.items())
            ],
        }
        files["manifest.json"] = encoded(manifest)
        os.mkdir(destination, 0o700)
        for name, body in sorted(files.items()):
            target = destination / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
        print(
            json.dumps(
                {
                    "status": "captured",
                    "run_id": str(RUN),
                    "file_count": len(files),
                    "reference_count": len(REFERENCE_REFS),
                    "source_manifest_sha256": hashlib.sha256(
                        files["manifest.json"]
                    ).hexdigest(),
                    "database_writes": 0,
                    "provider_calls": 0,
                }
            )
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(capture(Path(sys.argv[1])))
    except Exception as error:  # noqa: BLE001 -- redact all operational failures at the CLI boundary.
        frames = []
        trace = error.__traceback__
        while trace is not None:
            frames.append(
                {
                    "file": Path(trace.tb_frame.f_code.co_filename).name,
                    "line": trace.tb_lineno,
                }
            )
            trace = trace.tb_next
        print(
            json.dumps(
                {
                    "status": "capture_failed",
                    "error_type": type(error).__name__,
                    "frames": frames,
                }
            )
        )
        raise SystemExit(2) from None
