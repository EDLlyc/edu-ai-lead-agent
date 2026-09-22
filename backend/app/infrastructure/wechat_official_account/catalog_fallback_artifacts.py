"""Single-edition fallback owner; no paid provider, social client or run mutation."""

from __future__ import annotations

from datetime import datetime

from app.application.ports.official_account_local import OfficialAccountCatalogMediaProvider
from app.application.ports.official_account_single_edition import SingleEdition
from app.application.services.official_account_catalog_fallback import (
    build_catalog_fallback_projection,
)
from app.application.services.wechat_official_account_draft import WeChatDraftLocalSource
from app.domain.official_account_weekly_dag import WeeklyDagArtifact
from app.domain.official_account_weekly_edition import WeeklyArticleRole
from app.infrastructure.db.models import SourceArticleImageModel
from app.infrastructure.db.official_account_catalog_fallback import load_catalog_fallback_source
from app.infrastructure.official_account_media import OfficialAccountPersistedMedia
from app.infrastructure.wechat_official_account.prepared_artifacts import (
    PREPARED_DRAFT_CHILD_REF_VERSION,
    PreparedWeeklyDraftArtifactOwner,
    _directory_size,
    _json_bytes,
    _write_directory,
)


class PreparedSingleDraftArtifactOwner(PreparedWeeklyDraftArtifactOwner):
    async def build_fallback_child(
        self,
        *,
        edition: SingleEdition,
        now: datetime,
        catalog: OfficialAccountCatalogMediaProvider,
    ) -> WeeklyDagArtifact:
        source = await load_catalog_fallback_source(self._session_factory, edition, now=now)
        package = source.article.article
        selection = package.media_selection
        assert selection is not None and edition.article_run_id is not None and edition.role
        candidates = await catalog.load_candidates()
        by_ref = {item.catalog_asset_ref: item for item in candidates}
        if len(by_ref) != len(candidates):
            raise ValueError("single_catalog_fallback_catalog_ambiguous")
        bodies: list[bytes] = []
        for assignment in selection.assignments:
            candidate = by_ref.get(assignment.candidate_ref)
            if (
                candidate is None
                or (
                    candidate.catalog_version,
                    candidate.source_master_sha256,
                    candidate.sha256,
                )
                != (
                    selection.catalog_version,
                    assignment.source_checksum,
                    assignment.publication_checksum,
                )
                or set(await catalog.reference_characters(candidate)) != {"xiao-sai"}
            ):
                raise ValueError("single_catalog_fallback_catalog_changed")
            bodies.append(
                await catalog.read_publication_bytes(
                    catalog_asset_ref=assignment.candidate_ref,
                    catalog_version=selection.catalog_version,
                    source_master_sha256=assignment.source_checksum,
                    publication_sha256=assignment.publication_checksum,
                )
            )
        contexts: dict[int, bytes] = {}
        for item in package.news_context_media.items if package.news_context_media else ():
            async with self._session_factory() as session:
                row = await session.get(SourceArticleImageModel, item.source_article_image_id)
                if row is None or row.byte_size is None:
                    raise ValueError("single_catalog_fallback_context_missing")
                contexts[item.ordinal] = await self._resolver.read_verified_bytes(
                    session=session,
                    media=OfficialAccountPersistedMedia(
                        local_media_id="fallback-context",
                        source_image_artifact_id=None,
                        fixture_id=None,
                        role="context",
                        ordinal=item.ordinal,
                        media_type=item.media_type,
                        byte_size=row.byte_size,
                        sha256=item.sha256,
                        descriptor={"source_kind": "source_news"},
                        source_article_image_id=item.source_article_image_id,
                        run_id=edition.article_run_id,
                        render_version_id=source.render.id,
                    ),
                )
        (
            header,
            header_bytes,
            footer,
            footer_bytes,
        ) = await self._resolver.read_official_account_marketing_framing(package)
        projection = build_catalog_fallback_projection(
            run_id=edition.article_run_id,
            article_version_id=source.article.id,
            render_version_id=source.render.id,
            article=package,
            role=edition.role,
            failure_evidence=source.evidence,
            bodies=tuple(bodies),
            contexts=contexts,
            header=header,
            header_bytes=header_bytes,
            footer=footer,
            footer_bytes=footer_bytes,
        )
        target = self._child_path(projection.child_fingerprint)
        _write_directory(
            target,
            files={**projection.files, "prepared-manifest.json": _json_bytes(projection.manifest)},
        )
        self._preparer.prepare(
            WeChatDraftLocalSource(directory=target, role=WeeklyArticleRole(edition.role).value)
        )
        return WeeklyDagArtifact(
            opaque_ref=f"{PREPARED_DRAFT_CHILD_REF_VERSION}:{projection.child_fingerprint}",
            fingerprint=projection.child_fingerprint,
            media_type="application/vnd.wechat.approved-catalog-fallback-child+directory",
            byte_size=_directory_size(target),
        )
