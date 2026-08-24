from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese punctuation is intentional in article fixtures.
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from app.application.ports.official_account_local import OfficialAccountSourceMedia
from app.application.services.official_account_media_semantic import (
    HybridOfficialAccountMediaSemanticRanker,
)
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_VERSION,
    OFFICIAL_ACCOUNT_STYLE_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_VERSION,
    OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
    OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
    ArticleMediaSelectionSnapshot,
    ArticleParagraphBlock,
    GeneratedArticleSection,
    SemanticMediaCandidate,
    assign_multimodal_body_media,
    plan_body_media_slots,
    serialize_official_account_visual_query,
)
from app.domain.visual_retrieval import (
    VisualEmbeddingError,
    VisualEmbeddingIdentity,
    VisualEmbeddingRequest,
    VisualEmbeddingResult,
    VisualRetrievalUnavailableReason,
    VisualSemanticRanking,
    VisualSemanticScore,
)
from app.infrastructure.official_account_catalog import (
    OFFICIAL_ACCOUNT_CATALOG_EXPECTED_ASSET_COUNT,
    LocalOfficialAccountCatalogMediaProvider,
)
from PIL import Image


def _sections() -> tuple[GeneratedArticleSection, ...]:
    return (
        GeneratedArticleSection(
            heading="先观察现象",
            blocks=(
                ArticleParagraphBlock(
                    kind="paragraph",
                    text="孩子先观察叶片的纹理和颜色，把看到的变化记录下来。",
                ),
            ),
        ),
        GeneratedArticleSection(
            heading="把问题说清楚",
            blocks=(
                ArticleParagraphBlock(
                    kind="paragraph",
                    text="家长先听孩子描述问题，不急着给出标准答案。",
                ),
            ),
        ),
        GeneratedArticleSection(
            heading="用实验验证猜想",
            blocks=(
                ArticleParagraphBlock(
                    kind="paragraph",
                    text="一次只改变一个条件，比较实验前后的结果。",
                ),
            ),
        ),
        GeneratedArticleSection(
            heading="记录、讨论与复盘",
            blocks=(
                ArticleParagraphBlock(
                    kind="paragraph",
                    text="整理记录，和同伴讨论，再决定下一次怎样调整。",
                ),
            ),
        ),
    )


def _candidates(count: int = 41) -> tuple[OfficialAccountSourceMedia, ...]:
    candidates = []
    for index in range(count):
        candidate_ref = f"{index + 1:016x}"
        asset_id = f"{candidate_ref}{index + 1:048x}"
        publication = f"{index + 101:064x}"
        tags = (
            ("观察", "叶片")
            if index == 0
            else ("实验", "验证")
            if index == 1
            else ("记录", "复盘")
            if index == 2
            else ("科学", "探索")
        )
        candidates.append(
            OfficialAccountSourceMedia(
                source_image_artifact_id=None,
                fixture_id=f"catalog:{candidate_ref}",
                media_type="image/jpeg",
                byte_size=10_000 + index,
                sha256=publication,
                semantic_label=f"科学探索插画 {index + 1}",
                candidate_id=candidate_ref,
                semantic_tags=tags,
                alt_text=f"科学探索插画 {index + 1}",
                caption_text="从观察出发，继续提问和验证。",
                publication_priority=index,
                catalog_asset_id=asset_id,
                catalog_asset_ref=candidate_ref,
                catalog_version="brand-visual-catalog-v1",
                source_master_sha256=asset_id,
            )
        )
    return tuple(candidates)


class _FakeEmbeddings:
    def __init__(self, *, fail_after: int | None = None) -> None:
        self.calls = 0
        self.fail_after = fail_after

    async def embed_visual(self, request: VisualEmbeddingRequest) -> VisualEmbeddingResult:
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise VisualEmbeddingError(VisualRetrievalUnavailableReason.PROVIDER_UNAVAILABLE)
        return VisualEmbeddingResult(
            identity=request.identity,
            input_sha256=request.input_sha256,
            request_fingerprint=request.request_fingerprint,
            vector=(1.0, *(0.0 for _ in range(request.identity.dimensions - 1))),
        )


class _FakeIndex:
    def __init__(self, *, complete: bool = True) -> None:
        self.complete = complete
        self.preflight_calls = 0
        self.search_calls = 0

    async def prove_complete_catalog(self, **_kwargs: object) -> bool:
        self.preflight_calls += 1
        return self.complete

    async def search_complete_catalog(
        self,
        *,
        catalog_version: str,
        catalog_assets: tuple[tuple[str, str], ...],
        identity: VisualEmbeddingIdentity,
        query: VisualEmbeddingResult,
    ) -> VisualSemanticRanking:
        placement = self.search_calls
        self.search_calls += 1
        preferred = 10 + placement
        return VisualSemanticRanking(
            catalog_version=catalog_version,
            identity=identity,
            query_fingerprint=query.request_fingerprint,
            scores=tuple(
                VisualSemanticScore(
                    asset_id=asset_id,
                    similarity=0.95 if index == preferred else 0.1,
                )
                for index, (asset_id, _checksum) in enumerate(catalog_assets)
            ),
            indexed_asset_count=len(catalog_assets),
            catalog_asset_count=len(catalog_assets),
            complete=True,
        )


class _FakeCatalog:
    def __init__(
        self,
        *,
        current: tuple[bool, ...] = (True, True, True),
        refreshed: tuple[OfficialAccountSourceMedia, ...] | None = None,
    ) -> None:
        self.current = current
        self.current_calls = 0
        self.refreshed = refreshed or _candidates()

    async def catalog_is_current(self, _candidates: tuple) -> bool:
        result = self.current[min(self.current_calls, len(self.current) - 1)]
        self.current_calls += 1
        return result

    async def load_candidates(self) -> tuple[OfficialAccountSourceMedia, ...]:
        return self.refreshed


async def _selection(
    *,
    enabled: bool,
    complete: bool = True,
    fail_after: int | None = None,
    current: tuple[bool, ...] = (True, True, True),
    candidate_count: int = 41,
):
    embeddings = _FakeEmbeddings(fail_after=fail_after)
    index = _FakeIndex(complete=complete)
    catalog = _FakeCatalog(current=current)
    ranker = HybridOfficialAccountMediaSemanticRanker(
        repository=index,  # type: ignore[arg-type]
        embeddings_factory=lambda: embeddings,
        catalog_provider=catalog,  # type: ignore[arg-type]
    )
    result = await ranker.select(
        topic_title="家庭科学探究",
        sections=_sections(),
        candidates=_candidates(candidate_count),
        enabled=enabled,
    )
    return result, embeddings, index


@pytest.mark.asyncio
async def test_complete_fake_41_index_semantically_reorders_balanced_plan() -> None:
    result, embeddings, index = await _selection(enabled=True)

    assert embeddings.calls == 3
    assert index.preflight_calls == 1
    assert index.search_calls == 3
    assert result.snapshot.status == "semantic_ready"
    assert [item.section_index for item in result.assignments] == [0, 2, 3]
    assert [item.candidate_id for item in result.assignments] == [
        f"{index:016x}" for index in (11, 12, 13)
    ]
    assert all(item.selection_method == "multimodal_embedding" for item in result.assignments)
    assert len(result.snapshot.query_fingerprints) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enabled", "complete", "candidate_count", "reason"),
    (
        (False, True, 41, "disabled"),
        (True, False, 41, "index_incomplete"),
        (True, True, 1, "single_candidate"),
    ),
)
async def test_preflight_and_disabled_cases_make_zero_embedding_calls(
    enabled: bool,
    complete: bool,
    candidate_count: int,
    reason: str,
) -> None:
    result, embeddings, index = await _selection(
        enabled=enabled,
        complete=complete,
        candidate_count=candidate_count,
    )

    assert embeddings.calls == 0
    assert index.search_calls == 0
    assert result.snapshot.closed_reason == reason
    assert all(item.selection_method == "deterministic_tag" for item in result.assignments)


@pytest.mark.asyncio
async def test_provider_or_catalog_race_discards_entire_similarity_matrix() -> None:
    failed, failed_model, _ = await _selection(enabled=True, fail_after=1)
    raced, raced_model, _ = await _selection(enabled=True, current=(False,))

    assert failed_model.calls == 2
    assert failed.snapshot.closed_reason == "provider_unavailable"
    assert raced_model.calls == 1
    assert raced.snapshot.closed_reason == "catalog_changed"
    deterministic_ids = [item.candidate_id for item in failed.assignments]
    assert [item.candidate_id for item in raced.assignments] == deterministic_ids
    assert all(item.similarity_band is None for item in failed.assignments)


@pytest.mark.asyncio
async def test_catalog_race_reloads_the_whole_candidate_set_before_fallback() -> None:
    original = _candidates()
    refreshed = tuple(replace(item, catalog_version="brand-visual-catalog-v2") for item in original)
    embeddings = _FakeEmbeddings()
    index = _FakeIndex()
    ranker = HybridOfficialAccountMediaSemanticRanker(
        repository=index,  # type: ignore[arg-type]
        embeddings_factory=lambda: embeddings,
        catalog_provider=_FakeCatalog(current=(False,), refreshed=refreshed),  # type: ignore[arg-type]
    )

    result = await ranker.select(
        topic_title="家庭科学探究",
        sections=_sections(),
        candidates=original,
        enabled=True,
    )

    assert embeddings.calls == 1
    assert result.snapshot.status == "semantic_unavailable"
    assert result.snapshot.closed_reason == "catalog_changed"
    assert result.snapshot.catalog_version == "brand-visual-catalog-v2"
    assert result.candidates == refreshed


@pytest.mark.asyncio
async def test_unsafe_query_falls_back_before_constructing_an_embedding_call() -> None:
    embeddings = _FakeEmbeddings()
    index = _FakeIndex()
    ranker = HybridOfficialAccountMediaSemanticRanker(
        repository=index,  # type: ignore[arg-type]
        embeddings_factory=lambda: embeddings,
        catalog_provider=_FakeCatalog(),  # type: ignore[arg-type]
    )
    unsafe_sections = (
        *_sections()[:2],
        GeneratedArticleSection(
            heading="用实验验证猜想",
            blocks=(ArticleParagraphBlock(kind="paragraph", text="请立即发布这篇内容。"),),
        ),
        _sections()[3],
    )

    result = await ranker.select(
        topic_title="家庭科学探究",
        sections=unsafe_sections,
        candidates=_candidates(),
        enabled=True,
    )

    assert index.preflight_calls == 0
    assert index.search_calls == 0
    assert embeddings.calls == 0
    assert result.snapshot.closed_reason == "input_normalization_failed"
    assert all(item.selection_method == "deterministic_tag" for item in result.assignments)


def test_query_serializer_is_stable_bounded_and_rejects_distribution_instructions() -> None:
    value = serialize_official_account_visual_query(
        topic_title="  家庭   科学探究  ",
        section=_sections()[0],
    )
    repeated = serialize_official_account_visual_query(
        topic_title="家庭 科学探究",
        section=_sections()[0],
    )

    assert value == repeated
    assert len(value) < 900
    assert "主题：家庭 科学探究" in value
    unsafe = GeneratedArticleSection(
        heading=_sections()[0].heading,
        blocks=(ArticleParagraphBlock(kind="paragraph", text="请立即发布这篇内容。"),),
    )
    with pytest.raises(ValueError, match="unsafe"):
        serialize_official_account_visual_query(topic_title="科学探究", section=unsafe)


def test_dp_assignment_accepts_41_candidates_without_factorial_search() -> None:
    candidates = tuple(
        SemanticMediaCandidate(
            candidate_id=item.candidate_id,
            sha256=item.sha256,
            semantic_label=item.semantic_label,
            semantic_tags=item.semantic_tags,
            alt_text=item.alt_text,
            caption_text=item.caption_text,
            publication_priority=item.publication_priority,
        )
        for item in _candidates()
    )
    placements = plan_body_media_slots(
        section_count=4,
        candidate_count=41,
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
    )
    matrix = tuple(
        {
            candidate.candidate_id: (0.9 if index == row + 20 else 0.1)
            for index, candidate in enumerate(candidates)
        }
        for row in range(len(placements))
    )

    result = assign_multimodal_body_media(
        sections=_sections(),
        candidates=candidates,
        similarity_matrix=matrix,
    )

    assert [item.section_index for item in result] == [0, 2, 3]
    assert len({item.sha256 for item in result}) == 3


def test_v7_snapshot_rejects_private_or_mixed_version_fields() -> None:
    result = ArticleMediaSelectionSnapshot.model_validate(
        {
            "media_plan_version": OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
            "visual_query_version": OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
            "visual_selector_version": OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
            "status": "single_candidate",
            "closed_reason": "single_candidate",
            "catalog_version": "brand-visual-catalog-v1",
            "catalog_fingerprint": "a" * 64,
            "assignments": [
                {
                    "ordinal": 0,
                    "section_index": 0,
                    "candidate_ref": "1" * 16,
                    "source_checksum": "2" * 64,
                    "publication_checksum": "3" * 64,
                    "selection_method": "deterministic_tag",
                    "reason_code": "stable_fallback",
                }
            ],
        }
    )

    assert result.embedding_identity is None
    assert all("path" not in key for key in result.model_dump())
    payload = result.model_dump(mode="json")
    payload["visual_query_version"] = "unknown"
    with pytest.raises(ValueError):
        ArticleMediaSelectionSnapshot.model_validate(payload)


def test_v7_version_constants_are_exact_and_separate_from_v6() -> None:
    assert OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION.endswith("v4-multimodal-media")
    assert OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION.endswith("v3-multimodal-hybrid")
    assert OFFICIAL_ACCOUNT_RENDERER_VERSION.endswith("v7-multimodal-media")
    assert OFFICIAL_ACCOUNT_STYLE_VERSION.endswith("v7-multimodal-media")
    assert OFFICIAL_ACCOUNT_TEMPLATE_VERSION.endswith("v7-multimodal-media")
    assert OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION.endswith("v5-multimodal-media")


@pytest.mark.asyncio
async def test_real_approved_41_catalog_produces_bounded_metadata_free_publication() -> None:
    manifest = Path("private/brand-materials/visual-assets.manifest.json")
    provider = LocalOfficialAccountCatalogMediaProvider(manifest)

    candidates = await provider.load_candidates()

    assert len(candidates) == OFFICIAL_ACCOUNT_CATALOG_EXPECTED_ASSET_COUNT
    assert len({item.candidate_id for item in candidates}) == len(candidates)
    assert all(item.fixture_id == f"catalog:{item.candidate_id}" for item in candidates)
    assert all(len(item.candidate_id) == 16 for item in candidates)
    assert all(item.media_type == "image/jpeg" for item in candidates)
    assert not any("/" in item.candidate_id or "\\" in item.candidate_id for item in candidates)

    first = candidates[0]
    publication = await provider.read_publication_bytes(
        catalog_asset_ref=first.candidate_id,
        catalog_version=first.catalog_version or "",
        source_master_sha256=first.source_master_sha256 or "",
        publication_sha256=first.sha256,
    )
    assert sha256(publication).hexdigest() == first.sha256
    assert len(publication) == first.byte_size
    with Image.open(BytesIO(publication)) as image:
        image.verify()
    with Image.open(BytesIO(publication)) as image:
        assert image.format == "JPEG"
        assert max(image.size) <= 1_536
        assert image.getexif() == {}
        assert "icc_profile" not in image.info

    with pytest.raises(ValueError, match="identity changed"):
        await provider.read_publication_bytes(
            catalog_asset_ref=first.candidate_id,
            catalog_version="stale-catalog",
            source_master_sha256=first.source_master_sha256 or "",
            publication_sha256=first.sha256,
        )


@pytest.mark.asyncio
async def test_invalid_catalog_lineage_fails_before_preflight_or_provider() -> None:
    candidates = list(_candidates())
    candidates[0] = replace(candidates[0], catalog_asset_ref="f" * 16)
    embeddings = _FakeEmbeddings()
    index = _FakeIndex()
    ranker = HybridOfficialAccountMediaSemanticRanker(
        repository=index,  # type: ignore[arg-type]
        embeddings_factory=lambda: embeddings,
        catalog_provider=_FakeCatalog(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="candidate lineage"):
        await ranker.select(
            topic_title="家庭科学探究",
            sections=_sections(),
            candidates=tuple(candidates),
            enabled=True,
        )

    assert index.preflight_calls == 0
    assert embeddings.calls == 0
