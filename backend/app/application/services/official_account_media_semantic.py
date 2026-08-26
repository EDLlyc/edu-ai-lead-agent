from __future__ import annotations

from collections.abc import Callable
from typing import Literal, cast

from app.application.ports.official_account_local import (
    OfficialAccountCatalogMediaProvider,
    OfficialAccountMediaSelectionResult,
    OfficialAccountSourceMedia,
)
from app.application.ports.visual_retrieval import VisualEmbeddingModel, VisualIndexRepository
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
    OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
    OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
    ArticleMediaEmbeddingIdentity,
    ArticleMediaSelectionItem,
    ArticleMediaSelectionSnapshot,
    GeneratedArticleSection,
    SemanticMediaAssignment,
    SemanticMediaCandidate,
    assign_deterministic_body_media_v3,
    assign_deterministic_body_media_v4,
    assign_multimodal_body_media,
    serialize_official_account_visual_query,
)
from app.domain.visual_retrieval import (
    VisualEmbeddingError,
    VisualEmbeddingIdentity,
    VisualEmbeddingRequest,
    VisualIndexUnavailableError,
    VisualRetrievalUnavailableReason,
)
from app.infrastructure.official_account_catalog import official_account_catalog_fingerprint

_FallbackReason = Literal[
    "disabled",
    "single_candidate",
    "index_incomplete",
    "provider_unavailable",
    "invalid_provider_output",
    "identity_mismatch",
    "catalog_changed",
    "input_normalization_failed",
]


def _closed_reason(value: VisualRetrievalUnavailableReason) -> _FallbackReason:
    mapping: dict[VisualRetrievalUnavailableReason, _FallbackReason] = {
        VisualRetrievalUnavailableReason.DISABLED: "disabled",
        VisualRetrievalUnavailableReason.INPUT_NORMALIZATION_FAILED: ("input_normalization_failed"),
        VisualRetrievalUnavailableReason.PROVIDER_UNAVAILABLE: "provider_unavailable",
        VisualRetrievalUnavailableReason.INVALID_PROVIDER_OUTPUT: "invalid_provider_output",
        VisualRetrievalUnavailableReason.IDENTITY_MISMATCH: "identity_mismatch",
        VisualRetrievalUnavailableReason.INDEX_INCOMPLETE: "index_incomplete",
        VisualRetrievalUnavailableReason.CATALOG_CHANGED: "catalog_changed",
    }
    return mapping[value]


def _semantic_candidate(source: OfficialAccountSourceMedia) -> SemanticMediaCandidate:
    if (
        len(source.candidate_id) != 16
        or any(character not in "0123456789abcdef" for character in source.candidate_id)
        or not source.semantic_tags
        or not source.alt_text
        or not source.caption_text
    ):
        raise ValueError("official-account v7 candidate projection is incomplete")
    return SemanticMediaCandidate(
        candidate_id=source.candidate_id,
        sha256=source.sha256,
        semantic_label=source.semantic_label,
        semantic_tags=source.semantic_tags,
        alt_text=source.alt_text,
        caption_text=source.caption_text,
        publication_priority=source.publication_priority,
    )


class HybridOfficialAccountMediaSemanticRanker:
    def __init__(
        self,
        *,
        repository: VisualIndexRepository,
        embeddings_factory: Callable[[], VisualEmbeddingModel],
        catalog_provider: OfficialAccountCatalogMediaProvider,
        identity: VisualEmbeddingIdentity | None = None,
    ) -> None:
        self._repository = repository
        self._embeddings_factory = embeddings_factory
        self._catalog_provider = catalog_provider
        self._identity = identity or VisualEmbeddingIdentity()

    async def select(
        self,
        *,
        topic_title: str,
        sections: tuple[GeneratedArticleSection, ...],
        candidates: tuple[OfficialAccountSourceMedia, ...],
        enabled: bool,
        media_plan_version: str = OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
    ) -> OfficialAccountMediaSelectionResult:
        if media_plan_version not in {
            OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
            OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
        }:
            raise ValueError("official-account multimodal media-plan version is unsupported")
        semantic_candidates = tuple(_semantic_candidate(item) for item in candidates)
        if len(semantic_candidates) == 1:
            return self._fallback(
                sections=sections,
                candidates=candidates,
                semantic_candidates=semantic_candidates,
                status="single_candidate",
                reason="single_candidate",
                media_plan_version=media_plan_version,
            )
        if not enabled:
            return self._fallback(
                sections=sections,
                candidates=candidates,
                semantic_candidates=semantic_candidates,
                status="semantic_unavailable",
                reason="disabled",
                media_plan_version=media_plan_version,
            )
        catalog_version, catalog_assets = _catalog_identity(candidates)
        try:
            from app.domain.official_account_local import plan_body_media_slots

            placements = plan_body_media_slots(
                section_count=len(sections),
                candidate_count=len(candidates),
                media_plan_version=media_plan_version,
            )
            queries = tuple(
                serialize_official_account_visual_query(
                    topic_title=topic_title,
                    section=sections[section_index],
                )
                for section_index in placements
            )
        except ValueError:
            return self._fallback(
                sections=sections,
                candidates=candidates,
                semantic_candidates=semantic_candidates,
                status="semantic_unavailable",
                reason="input_normalization_failed",
                media_plan_version=media_plan_version,
            )
        try:
            complete = await self._repository.prove_complete_catalog(
                catalog_version=catalog_version,
                catalog_assets=catalog_assets,
                identity=self._identity,
            )
        except Exception:
            complete = False
        if not complete:
            return self._fallback(
                sections=sections,
                candidates=candidates,
                semantic_candidates=semantic_candidates,
                status="semantic_unavailable",
                reason="index_incomplete",
                media_plan_version=media_plan_version,
            )
        embeddings = self._embeddings_factory()
        similarity_rows: list[dict[str, float]] = []
        query_fingerprints: list[str] = []
        asset_ref_by_id = {
            item.catalog_asset_id: item.candidate_id
            for item in candidates
            if item.catalog_asset_id is not None
        }
        try:
            for query in queries:
                request = VisualEmbeddingRequest.for_text(query, identity=self._identity)
                result = await embeddings.embed_visual(request)
                if (
                    result.identity != self._identity
                    or result.input_sha256 != request.input_sha256
                    or result.request_fingerprint != request.request_fingerprint
                ):
                    raise VisualIndexUnavailableError(
                        VisualRetrievalUnavailableReason.IDENTITY_MISMATCH
                    )
                ranking = await self._repository.search_complete_catalog(
                    catalog_version=catalog_version,
                    catalog_assets=catalog_assets,
                    identity=self._identity,
                    query=result,
                )
                expected_ids = {asset_id for asset_id, _checksum in catalog_assets}
                if (
                    not ranking.complete
                    or ranking.identity != self._identity
                    or ranking.catalog_version != catalog_version
                    or set(ranking.score_map) != expected_ids
                ):
                    raise VisualIndexUnavailableError(
                        VisualRetrievalUnavailableReason.INDEX_INCOMPLETE
                    )
                similarity_rows.append(
                    {
                        asset_ref_by_id[asset_id]: similarity
                        for asset_id, similarity in ranking.score_map.items()
                    }
                )
                query_fingerprints.append(request.request_fingerprint)
                if not await self._catalog_provider.catalog_is_current(candidates):
                    raise VisualIndexUnavailableError(
                        VisualRetrievalUnavailableReason.CATALOG_CHANGED
                    )
            assignments = assign_multimodal_body_media(
                sections=sections,
                candidates=semantic_candidates,
                similarity_matrix=tuple(similarity_rows),
                media_plan_version=media_plan_version,
            )
        except VisualIndexUnavailableError as error:
            if error.reason == VisualRetrievalUnavailableReason.CATALOG_CHANGED:
                try:
                    refreshed = await self._catalog_provider.load_candidates()
                    refreshed_semantic = tuple(_semantic_candidate(item) for item in refreshed)
                    _catalog_identity(refreshed)
                except (TypeError, ValueError):
                    raise ValueError(
                        "official-account catalog changed without a safe replacement set"
                    ) from error
                return self._fallback(
                    sections=sections,
                    candidates=refreshed,
                    semantic_candidates=refreshed_semantic,
                    status="semantic_unavailable",
                    reason="catalog_changed",
                    media_plan_version=media_plan_version,
                )
            return self._fallback(
                sections=sections,
                candidates=candidates,
                semantic_candidates=semantic_candidates,
                status="semantic_unavailable",
                reason=_closed_reason(error.reason),
                media_plan_version=media_plan_version,
            )
        except VisualEmbeddingError as error:
            return self._fallback(
                sections=sections,
                candidates=candidates,
                semantic_candidates=semantic_candidates,
                status="semantic_unavailable",
                reason=_closed_reason(error.reason),
                media_plan_version=media_plan_version,
            )
        except ValueError:
            return self._fallback(
                sections=sections,
                candidates=candidates,
                semantic_candidates=semantic_candidates,
                status="semantic_unavailable",
                reason="invalid_provider_output",
                media_plan_version=media_plan_version,
            )
        except Exception:
            return self._fallback(
                sections=sections,
                candidates=candidates,
                semantic_candidates=semantic_candidates,
                status="semantic_unavailable",
                reason="provider_unavailable",
                media_plan_version=media_plan_version,
            )
        snapshot = self._snapshot(
            candidates=candidates,
            assignments=assignments,
            status="semantic_ready",
            reason=None,
            query_fingerprints=tuple(query_fingerprints),
            media_plan_version=media_plan_version,
        )
        return OfficialAccountMediaSelectionResult(
            assignments=assignments,
            snapshot=snapshot,
            candidates=candidates,
        )

    def _fallback(
        self,
        *,
        sections: tuple[GeneratedArticleSection, ...],
        candidates: tuple[OfficialAccountSourceMedia, ...],
        semantic_candidates: tuple[SemanticMediaCandidate, ...],
        status: Literal["semantic_unavailable", "single_candidate"],
        reason: _FallbackReason,
        media_plan_version: str,
    ) -> OfficialAccountMediaSelectionResult:
        assignments = (
            assign_deterministic_body_media_v4(
                sections=sections,
                candidates=semantic_candidates,
            )
            if media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION
            else assign_deterministic_body_media_v3(
                sections=sections,
                candidates=semantic_candidates,
            )
        )
        snapshot = self._snapshot(
            candidates=candidates,
            assignments=assignments,
            status=status,
            reason=reason,
            query_fingerprints=(),
            media_plan_version=media_plan_version,
        )
        return OfficialAccountMediaSelectionResult(
            assignments=assignments,
            snapshot=snapshot,
            candidates=candidates,
        )

    def _snapshot(
        self,
        *,
        candidates: tuple[OfficialAccountSourceMedia, ...],
        assignments: tuple[SemanticMediaAssignment, ...],
        status: Literal["semantic_ready", "semantic_unavailable", "single_candidate"],
        reason: (_FallbackReason | None),
        query_fingerprints: tuple[str, ...],
        media_plan_version: str,
    ) -> ArticleMediaSelectionSnapshot:
        by_ref = {item.candidate_id: item for item in candidates}
        return ArticleMediaSelectionSnapshot(
            media_plan_version=cast(
                Literal[
                    "official-account-media-plan-v3-multimodal-hybrid",
                    "official-account-media-plan-v4-five-blocks",
                ],
                media_plan_version,
            ),
            visual_query_version=OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
            visual_selector_version=OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
            status=status,
            closed_reason=reason,
            catalog_version=_safe_catalog_version(candidates),
            catalog_fingerprint=official_account_catalog_fingerprint(candidates),
            embedding_identity=(
                ArticleMediaEmbeddingIdentity(
                    provider="alibaba-model-studio",
                    model="qwen3-vl-embedding",
                    dimensions=2048,
                    input_policy_version="brand-visual-embedding-input-v2",
                )
                if status == "semantic_ready"
                else None
            ),
            query_fingerprints=query_fingerprints,
            assignments=tuple(
                ArticleMediaSelectionItem(
                    ordinal=item.ordinal,
                    section_index=item.section_index,
                    candidate_ref=item.candidate_id,
                    source_checksum=(
                        by_ref[item.candidate_id].source_master_sha256
                        or by_ref[item.candidate_id].sha256
                    ),
                    publication_checksum=by_ref[item.candidate_id].sha256,
                    selection_method=item.selection_method,
                    reason_code=item.reason_code,
                    similarity_band=item.similarity_band,
                )
                for item in assignments
            ),
        )


def _catalog_identity(
    candidates: tuple[OfficialAccountSourceMedia, ...],
) -> tuple[str, tuple[tuple[str, str], ...]]:
    if not 2 <= len(candidates) <= 41:
        raise ValueError("official-account semantic catalog candidate count is invalid")
    version = _safe_catalog_version(candidates)
    if any(
        item.catalog_asset_id is None
        or len(item.catalog_asset_id) != 64
        or any(character not in "0123456789abcdef" for character in item.catalog_asset_id)
        or item.catalog_asset_ref != item.candidate_id
        or not item.catalog_asset_id.startswith(item.candidate_id)
        or item.source_master_sha256 != item.catalog_asset_id
        or item.fixture_id != f"catalog:{item.candidate_id}"
        or item.source_image_artifact_id is not None
        or item.media_type != "image/jpeg"
        or not 1 <= item.byte_size <= 10 * 1024 * 1024
        for item in candidates
    ):
        raise ValueError("official-account semantic candidate lineage is invalid")
    if (
        len({item.catalog_asset_id for item in candidates}) != len(candidates)
        or len({item.candidate_id for item in candidates}) != len(candidates)
        or len({item.source_master_sha256 for item in candidates}) != len(candidates)
        or len({item.sha256 for item in candidates}) != len(candidates)
    ):
        raise ValueError("official-account semantic candidate identity is not unique")
    assets = tuple(
        sorted(
            (item.catalog_asset_id, item.source_master_sha256)
            for item in candidates
            if item.catalog_asset_id is not None and item.source_master_sha256 is not None
        )
    )
    if len(assets) != len(candidates):
        raise ValueError("official-account semantic candidates lack catalog identity")
    return version, assets


def _safe_catalog_version(candidates: tuple[OfficialAccountSourceMedia, ...]) -> str:
    versions = {item.catalog_version for item in candidates if item.catalog_version is not None}
    if len(versions) != 1:
        raise ValueError("official-account candidates do not share one catalog version")
    return next(iter(versions))
