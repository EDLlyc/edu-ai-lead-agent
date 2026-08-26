# ruff: noqa: ASYNC240, RUF001 -- bounded operator filesystem work and Chinese copy are intentional.
"""Local v5 editorial bundle with two live semantic-reference generated scenes.

This operator-only command preserves the validated v1 news bundle and the additive v2--v4
outputs. It proves the complete 41-item Qwen3-VL index before constructing an embedding client,
runs two exact-block text queries, and generates exactly two ToApis single-reference scenes.
It has no WeChat, WeCom, draft-upload, or publish dependency.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from PIL import Image, UnidentifiedImageError

from app import official_account_news_editorial_asset_rich_demo as asset_rich_v4
from app import official_account_news_editorial_polished_demo as polished_v3
from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerator,
    ImageReference,
)
from app.application.ports.official_account_local import (
    OfficialAccountSourceMedia,
    StoredOfficialAccountArticle,
    StoredOfficialAccountRender,
)
from app.application.ports.visual_retrieval import VisualEmbeddingModel, VisualIndexRepository
from app.application.services.official_account_visual_generation import (
    build_generated_visual_prompt,
    plan_generated_body_visual,
    prepare_generated_visual_result,
    select_generated_visual_block_anchor,
)
from app.core.config import Settings, get_settings
from app.core.errors import AppError, ImageOutputValidationError, ImageProviderTimeoutError
from app.domain.image_provider_input import IMAGE_REFERENCE_INPUT_V2
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
    ArticleBulletListBlock,
    ArticleImageBlock,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleVersionBundle,
    article_body_character_count,
    article_package_fingerprint,
    body_media_placeholder,
    fingerprint,
)
from app.domain.visual_retrieval import (
    MAX_VISUAL_QUERY_CHARACTERS,
    VisualEmbeddingIdentity,
    VisualEmbeddingRequest,
    VisualSemanticRanking,
)
from app.infrastructure.ai.factory import create_image_generator
from app.infrastructure.ai.visual_embedding import AlibabaVisualEmbeddingAdapter
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.visual_retrieval import PostgresVisualIndexRepository
from app.infrastructure.official_account_catalog import (
    OFFICIAL_ACCOUNT_CATALOG_EXPECTED_ASSET_COUNT,
    LocalOfficialAccountCatalogMediaProvider,
    official_account_catalog_fingerprint,
)
from app.official_account_news_editorial_demo import EditorialSourceBundle

NEWS_URL = asset_rich_v4.NEWS_URL
PLAN_URL = asset_rich_v4.PLAN_URL
REFERENCE_URL = asset_rich_v4.REFERENCE_URL
SOURCE_REPORT_VERSION = asset_rich_v4.SOURCE_REPORT_VERSION
SOURCE_EVIDENCE_VERSION = asset_rich_v4.SOURCE_EVIDENCE_VERSION
BODY_IMAGE_NAMES = asset_rich_v4.BODY_IMAGE_NAMES
BODY_TARGET_MIN = asset_rich_v4.BODY_TARGET_MIN
BODY_TARGET_MAX = asset_rich_v4.BODY_TARGET_MAX

REPORT_VERSION = "official-account-news-editorial-semantic-generated-demo-v5"
ARTICLE_SCHEMA_VERSION = "official-account-news-editorial-schema-v5-semantic-generated-five-scene"
RENDERER_VERSION = "wechat-news-editorial-renderer-v5-semantic-generated-five-scene"
STYLE_VERSION = "wechat-news-editorial-style-v5-navy-cobalt-orange-scenes"
TEMPLATE_VERSION = "wechat-news-editorial-template-v5-five-scene-mobile"
REFERENCE_STUDY_VERSION = "wechat-public-reference-patterns-v4-semantic-five-scene"
LOCAL_ADAPTER_VERSION = "official-account-news-editorial-local-adapter-v5-live-semantic"
SEMANTIC_QUERY_VERSION = "official-account-news-editorial-exact-block-query-v1"
SEMANTIC_SELECTOR_VERSION = "official-account-news-editorial-two-block-selector-v1"
DEFAULT_SOURCE_DIR = asset_rich_v4.DEFAULT_SOURCE_DIR
DEFAULT_CATALOG_MANIFEST = asset_rich_v4.DEFAULT_CATALOG_MANIFEST
DEFAULT_OUTPUT_DIR = Path(
    "output/official-account-news-ip-editorial-semantic-generated-20260825-v5"
)
PAID_IMAGE_CALL_LIMIT = 2
SEMANTIC_QUERY_CALL_LIMIT = 2
_PLACEMENTS = ((3, 1), (4, 3))
_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
_SEMANTIC_SCENE_ALTS = {
    3: "小赛陪家长梳理孩子问题背后的线索，呼应先接住问题再一起查证的正文场景",
    4: "小赛与孩子使用科学工具观察、记录和判断，呼应AI协助但不替代孩子思考的正文场景",
}


class _CatalogProvider(Protocol):
    async def load_candidates(self) -> tuple[OfficialAccountSourceMedia, ...]: ...

    async def revalidate_candidate(
        self, candidate: OfficialAccountSourceMedia
    ) -> OfficialAccountSourceMedia: ...

    async def catalog_is_current(
        self, candidates: tuple[OfficialAccountSourceMedia, ...]
    ) -> bool: ...

    async def read_publication_bytes(
        self,
        *,
        catalog_asset_ref: str,
        catalog_version: str,
        source_master_sha256: str,
        publication_sha256: str,
    ) -> bytes: ...


EmbeddingContextFactory = Callable[[], AbstractAsyncContextManager[VisualEmbeddingModel]]
ImageContextFactory = Callable[[], AbstractAsyncContextManager[ImageGenerator]]
BlockKind = Literal["paragraph", "bullet_list", "quote", "callout"]
TerminalState = Literal["failed", "result_unknown"]
_TERMINAL_STATES: tuple[TerminalState, TerminalState] = ("failed", "result_unknown")


@dataclass(frozen=True, slots=True)
class SemanticReference:
    ordinal: int
    section_index: int
    block_index: int
    block_kind: BlockKind
    block_fingerprint: str
    source_text_fingerprint: str
    query_fingerprint: str
    public_ref: str
    catalog_version: str
    source_master_sha256: str
    publication_sha256: str
    similarity_band: Literal["very_high", "high", "medium", "low"]
    candidate: OfficialAccountSourceMedia
    publication_bytes: bytes


@dataclass(frozen=True, slots=True)
class SemanticSelection:
    references: tuple[SemanticReference, SemanticReference]
    catalog_version: str
    catalog_fingerprint: str
    embedding_identity: VisualEmbeddingIdentity


def _versions() -> ArticleVersionBundle:
    return ArticleVersionBundle(
        generator_prompt_version="official-account-news-editorial-assembler-v5-semantic-generated",
        article_schema_version=ARTICLE_SCHEMA_VERSION,
        auditor_prompt_version="official-account-news-editorial-audit-v5",
        audit_schema_version="official-account-news-editorial-audit-schema-v5",
        rule_version="official-account-news-editorial-rules-v5-evidence-bound-five-scene",
        renderer_version=RENDERER_VERSION,
        style_version=STYLE_VERSION,
        template_version=TEMPLATE_VERSION,
        local_adapter_version=LOCAL_ADAPTER_VERSION,
    )


def _as_v4_projection(article: ArticlePackage) -> ArticlePackage:
    questions = article.sections[1]
    boundary = article.sections[3]
    question_image = questions.blocks[3]
    boundary_image = boundary.blocks[2]
    if not isinstance(question_image, ArticleImageBlock) or not isinstance(
        boundary_image, ArticleImageBlock
    ):
        raise ValueError("semantic-generated image shape changed")
    v4_question_alt = asset_rich_v4._EXPECTED_CATALOG_ASSETS[
        asset_rich_v4.PARENT_QUESTION_PUBLIC_REF
    ].alt
    v4_boundary_alt = asset_rich_v4._EXPECTED_CATALOG_ASSETS[
        asset_rich_v4.AI_BOUNDARY_PUBLIC_REF
    ].alt
    sections = list(article.sections)
    sections[1] = questions.model_copy(
        update={
            "blocks": (
                *questions.blocks[:3],
                question_image.model_copy(update={"alt_text": v4_question_alt}),
                *questions.blocks[4:],
            )
        }
    )
    sections[3] = boundary.model_copy(
        update={
            "blocks": (
                *boundary.blocks[:2],
                boundary_image.model_copy(update={"alt_text": v4_boundary_alt}),
                *boundary.blocks[3:],
            )
        }
    )
    provisional = article.model_copy(
        update={
            "sections": tuple(sections),
            "versions": asset_rich_v4._versions(),
            "content_fingerprint": "0" * 64,
        }
    )
    return provisional.model_copy(
        update={"content_fingerprint": article_package_fingerprint(provisional)}
    )


def _validate_semantic_article(article: ArticlePackage) -> None:
    if article.versions != _versions():
        raise ValueError("semantic-generated Article Package version changed")
    if article.content_fingerprint != article_package_fingerprint(article):
        raise ValueError("semantic-generated Article Package fingerprint changed")
    if not BODY_TARGET_MIN <= article_body_character_count(article) <= BODY_TARGET_MAX:
        raise ValueError("semantic-generated article is outside the approved target length")
    question_image = article.sections[1].blocks[3]
    boundary_image = article.sections[3].blocks[2]
    if (
        not isinstance(question_image, ArticleImageBlock)
        or not isinstance(boundary_image, ArticleImageBlock)
        or question_image.alt_text != _SEMANTIC_SCENE_ALTS[3]
        or boundary_image.alt_text != _SEMANTIC_SCENE_ALTS[4]
    ):
        raise ValueError("semantic-generated scene alt binding changed")
    asset_rich_v4._validate_asset_rich_article(_as_v4_projection(article))


def build_semantic_article(
    bundle: EditorialSourceBundle,
) -> ArticlePackage:
    baseline = asset_rich_v4.build_asset_rich_article(bundle)
    questions = baseline.sections[1]
    boundary = baseline.sections[3]
    question_image = questions.blocks[3]
    boundary_image = boundary.blocks[2]
    if not isinstance(question_image, ArticleImageBlock) or not isinstance(
        boundary_image, ArticleImageBlock
    ):
        raise ValueError("semantic-generated image shape changed")
    sections = list(baseline.sections)
    sections[1] = questions.model_copy(
        update={
            "blocks": (
                *questions.blocks[:3],
                question_image.model_copy(update={"alt_text": _SEMANTIC_SCENE_ALTS[3]}),
                *questions.blocks[4:],
            )
        }
    )
    sections[3] = boundary.model_copy(
        update={
            "blocks": (
                *boundary.blocks[:2],
                boundary_image.model_copy(update={"alt_text": _SEMANTIC_SCENE_ALTS[4]}),
                *boundary.blocks[3:],
            )
        }
    )
    provisional = baseline.model_copy(
        update={
            "sections": tuple(sections),
            "versions": _versions(),
            "content_fingerprint": "0" * 64,
        }
    )
    article = provisional.model_copy(
        update={"content_fingerprint": article_package_fingerprint(provisional)}
    )
    _validate_semantic_article(article)
    return article


def _stored_article(article: ArticlePackage) -> StoredOfficialAccountArticle:
    return StoredOfficialAccountArticle(
        id=uuid5(NAMESPACE_URL, f"{REPORT_VERSION}:{article.content_fingerprint}:article"),
        article=article,
        validation_issues=(),
        audit=None,
        provider_request_id=None,
        prompt_tokens=0,
        completion_tokens=0,
        reasoning_tokens=0,
        latency_ms=0,
        created_at=_EPOCH,
    )


def _stored_render(article: StoredOfficialAccountArticle) -> StoredOfficialAccountRender:
    canonical = render_semantic_generated_html(article.article)
    return StoredOfficialAccountRender(
        id=uuid5(NAMESPACE_URL, f"{REPORT_VERSION}:{article.id}:render"),
        article_version_id=article.id,
        canonical_html=canonical,
        render_fingerprint=fingerprint(REPORT_VERSION, RENDERER_VERSION, canonical),
    )


def _scene_html(block: ArticleImageBlock, *, field: Literal["warm", "blue"]) -> str:
    ordinal = int(block.slot_key.removeprefix("body-"))
    if ordinal not in (3, 4):
        raise ValueError("semantic-generated scene binding changed")
    accent = "#f2663a" if field == "warm" else "#1e5bff"
    paper = "#fff7cf" if field == "warm" else "#eef3ff"
    return (
        '<section data-module="semantic-generated-scene" '
        f'data-scene-field="{field}" style="margin:23px 0 21px;padding:11px;'
        f'background:{paper};border:1px solid #071b33;box-shadow:7px 7px 0 {accent};">'
        f'<img src="{body_media_placeholder(ordinal)}" alt="{escape(block.alt_text, quote=True)}" '
        'style="display:block;width:100%;height:auto;aspect-ratio:3/2;object-fit:cover;'
        'background:#eef3f7;border:0;">'
        '<p style="margin:10px 3px 3px;color:#071b33;font-size:10px;line-height:1.5;'
        'font-weight:900;letter-spacing:1.4px;">语义场景 · 小赛科学探索</p>'
        f'<p style="margin:0 3px 2px;color:#33445b;font-size:11px;line-height:1.65;">'
        f"{escape(block.alt_text)}</p></section>"
    )


def render_semantic_generated_html(article: ArticlePackage) -> str:
    _validate_semantic_article(article)
    projected = _as_v4_projection(article)
    html = asset_rich_v4.render_asset_rich_html(projected)
    question = projected.sections[1].blocks[3]
    boundary = projected.sections[3].blocks[2]
    semantic_question = article.sections[1].blocks[3]
    semantic_boundary = article.sections[3].blocks[2]
    if not all(
        isinstance(block, ArticleImageBlock)
        for block in (question, boundary, semantic_question, semantic_boundary)
    ):
        raise ValueError("semantic-generated image shape changed")
    assert isinstance(question, ArticleImageBlock)
    assert isinstance(boundary, ArticleImageBlock)
    assert isinstance(semantic_question, ArticleImageBlock)
    assert isinstance(semantic_boundary, ArticleImageBlock)
    replacements = (
        (
            asset_rich_v4._catalog_cutaway_html(question, field="warm"),
            _scene_html(semantic_question, field="warm"),
        ),
        (
            asset_rich_v4._catalog_cutaway_html(boundary, field="blue"),
            _scene_html(semantic_boundary, field="blue"),
        ),
    )
    for old, new in replacements:
        if html.count(old) != 1:
            raise ValueError("semantic-generated render anchor changed")
        html = html.replace(old, new, 1)
    if (
        html.count('data-module="semantic-generated-scene"') != 2
        or 'data-module="catalog-cutaway"' in html
        or html.count("<h1 ") != 1
    ):
        raise ValueError("semantic-generated render module set changed")
    for ordinal in range(5):
        if html.count(body_media_placeholder(ordinal)) != 1:
            raise ValueError("semantic-generated render placeholder set is invalid")
    return html


def _catalog_identity(
    candidates: tuple[OfficialAccountSourceMedia, ...],
) -> tuple[str, tuple[tuple[str, str], ...]]:
    if len(candidates) != OFFICIAL_ACCOUNT_CATALOG_EXPECTED_ASSET_COUNT:
        raise ValueError("semantic catalog must contain the complete 41-item set")
    versions = {item.catalog_version for item in candidates}
    if len(versions) != 1 or None in versions:
        raise ValueError("semantic catalog version is incomplete")
    refs = tuple(item.catalog_asset_ref for item in candidates)
    ids = tuple(item.catalog_asset_id for item in candidates)
    source_checksums = tuple(item.source_master_sha256 for item in candidates)
    publication_checksums = tuple(item.sha256 for item in candidates)
    if any(
        asset_id is None
        or public_ref is None
        or source_checksum is None
        or len(asset_id) != 64
        or len(public_ref) != 16
        or asset_id[:16] != public_ref
        or source_checksum != asset_id
        or any(character not in "0123456789abcdef" for character in asset_id)
        or any(character not in "0123456789abcdef" for character in public_ref)
        for asset_id, public_ref, source_checksum in zip(ids, refs, source_checksums, strict=True)
    ):
        raise ValueError("semantic catalog lineage is invalid")
    if any(
        len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum)
        for checksum in publication_checksums
    ):
        raise ValueError("semantic catalog publication identity is invalid")
    if any(
        len(set(values)) != len(values)
        for values in (ids, refs, source_checksums, publication_checksums)
    ):
        raise ValueError("semantic catalog identities are not unique")
    assets = tuple(
        sorted(
            (asset_id, checksum)
            for asset_id, checksum in zip(ids, source_checksums, strict=True)
            if asset_id is not None and checksum is not None
        )
    )
    return str(next(iter(versions))), assets


def _slot_exact_source_text(
    *, article: StoredOfficialAccountArticle, ordinal: int, section_index: int
) -> tuple[str, str]:
    section = article.article.sections[section_index]
    if ordinal == 3 and section_index == 1:
        blocks = section.blocks[:3]
        if len(blocks) != 3 or not all(
            isinstance(block, ArticleParagraphBlock) for block in blocks
        ):
            raise ValueError("parent-question exact source group changed")
        text = " | ".join(
            f"paragraph-{index + 1}={block.text}"
            for index, block in enumerate(blocks)
            if isinstance(block, ArticleParagraphBlock)
        )
        source_kind = "three_parent_question_paragraphs"
    elif ordinal == 4 and section_index == 3:
        block = section.blocks[1]
        if not isinstance(block, ArticleBulletListBlock) or len(block.items) < 2:
            raise ValueError("AI-child boundary exact source list changed")
        text = " | ".join(f"item-{index + 1}={item}" for index, item in enumerate(block.items))
        source_kind = "structured_ai_child_boundary_list"
    else:
        raise ValueError("semantic exact source slot is unsupported")
    normalized = " ".join(text.split())
    if not 1 <= len(normalized) <= 1_200:
        raise ValueError("semantic exact source text is outside bounds")
    return normalized, fingerprint(
        "official-account-news-editorial-slot-source-v1",
        ordinal,
        section_index,
        source_kind,
        normalized,
    )


def _exact_block_query(
    *, article: StoredOfficialAccountArticle, ordinal: int, section_index: int
) -> tuple[str, int, BlockKind, str, str]:
    anchor = select_generated_visual_block_anchor(article=article, section_index=section_index)
    source_text, source_text_fingerprint = _slot_exact_source_text(
        article=article,
        ordinal=ordinal,
        section_index=section_index,
    )
    heading = " ".join(article.article.sections[section_index].heading.split())[:120]
    topic = " ".join(article.article.topic_title.split())[:240]
    query = (
        f"version={SEMANTIC_QUERY_VERSION}; topic={topic}; section={heading}; "
        f"block_kind={anchor.block_kind}; exact_source={source_text}; "
        "visual_intent=小赛或赛先生作为清晰主角，参与观察、比较、提问、记录或验证；"
        "style=科学教育杂志插画；no_text=true"
    )
    if not 1 <= len(query) <= MAX_VISUAL_QUERY_CHARACTERS:
        raise ValueError("semantic exact-block query is outside bounds")
    return (
        query,
        anchor.block_index,
        anchor.block_kind,
        anchor.block_fingerprint,
        source_text_fingerprint,
    )


def _validate_ranking(
    ranking: VisualSemanticRanking,
    *,
    request: VisualEmbeddingRequest,
    catalog_version: str,
    identity: VisualEmbeddingIdentity,
    expected_ids: frozenset[str],
) -> dict[str, float]:
    if (
        not ranking.complete
        or ranking.identity != identity
        or ranking.catalog_version != catalog_version
        or ranking.query_fingerprint != request.request_fingerprint
        or set(ranking.score_map) != expected_ids
        or ranking.indexed_asset_count != len(expected_ids)
        or ranking.catalog_asset_count != len(expected_ids)
    ):
        raise ValueError("semantic ranking failed the complete-result fence")
    return ranking.score_map


def _similarity_band(value: float) -> Literal["very_high", "high", "medium", "low"]:
    if value >= 0.75:
        return "very_high"
    if value >= 0.5:
        return "high"
    if value >= 0.25:
        return "medium"
    return "low"


def _select_distinct_pair(
    candidates: tuple[OfficialAccountSourceMedia, ...],
    score_rows: tuple[dict[str, float], dict[str, float]],
    *,
    forbidden_public_refs: frozenset[str],
) -> tuple[OfficialAccountSourceMedia, OfficialAccountSourceMedia]:
    ordered = tuple(
        sorted(
            (
                candidate
                for candidate in candidates
                if candidate.candidate_id not in forbidden_public_refs
            ),
            key=lambda item: (item.publication_priority, item.sha256, item.candidate_id),
        )
    )
    pairs = (
        (
            -(
                score_rows[0][left.catalog_asset_id or ""]
                + score_rows[1][right.catalog_asset_id or ""]
            ),
            left.publication_priority + right.publication_priority,
            left.candidate_id,
            right.candidate_id,
            left,
            right,
        )
        for left in ordered
        for right in ordered
        if left.candidate_id != right.candidate_id and left.sha256 != right.sha256
    )
    try:
        best = min(pairs, key=lambda item: item[:4])
    except ValueError as error:
        raise ValueError("semantic selector cannot produce two distinct references") from error
    return best[4], best[5]


def _same_candidate_identity(
    left: OfficialAccountSourceMedia, right: OfficialAccountSourceMedia
) -> bool:
    return all(
        getattr(left, field) == getattr(right, field)
        for field in (
            "candidate_id",
            "catalog_asset_id",
            "catalog_asset_ref",
            "catalog_version",
            "source_master_sha256",
            "sha256",
            "byte_size",
            "media_type",
            "semantic_label",
            "semantic_tags",
            "alt_text",
            "caption_text",
        )
    )


async def select_semantic_references(
    *,
    article: ArticlePackage,
    catalog_provider: _CatalogProvider,
    repository: VisualIndexRepository,
    embeddings_context_factory: EmbeddingContextFactory,
    forbidden_public_refs: frozenset[str],
    identity: VisualEmbeddingIdentity | None = None,
) -> SemanticSelection:
    """Run exactly two exact-block queries after a complete-index proof."""

    _validate_semantic_article(article)
    selected_identity = identity or VisualEmbeddingIdentity()
    if selected_identity != VisualEmbeddingIdentity():
        raise ValueError("semantic Qwen3-VL identity is not the active v2 identity")
    candidates = await catalog_provider.load_candidates()
    catalog_version, catalog_assets = _catalog_identity(candidates)
    if len(forbidden_public_refs) != 3 or any(
        len(public_ref) != 16
        or any(character not in "0123456789abcdef" for character in public_ref)
        for public_ref in forbidden_public_refs
    ):
        raise ValueError("semantic historical-reference exclusion set is invalid")
    complete = await repository.prove_complete_catalog(
        catalog_version=catalog_version,
        catalog_assets=catalog_assets,
        identity=selected_identity,
    )
    if not complete:
        raise ValueError("semantic Qwen3-VL index is incomplete")

    stored = _stored_article(article)
    query_contracts = tuple(
        _exact_block_query(article=stored, ordinal=ordinal, section_index=section_index)
        for ordinal, section_index in _PLACEMENTS
    )
    requests = tuple(
        VisualEmbeddingRequest.for_text(contract[0], identity=selected_identity)
        for contract in query_contracts
    )
    expected_ids = frozenset(asset_id for asset_id, _checksum in catalog_assets)
    score_rows: list[dict[str, float]] = []
    async with embeddings_context_factory() as embeddings:
        for request in requests:
            result = await embeddings.embed_visual(request)
            if (
                result.identity != selected_identity
                or result.input_sha256 != request.input_sha256
                or result.request_fingerprint != request.request_fingerprint
            ):
                raise ValueError("semantic embedding result identity changed")
            ranking = await repository.search_complete_catalog(
                catalog_version=catalog_version,
                catalog_assets=catalog_assets,
                identity=selected_identity,
                query=result,
            )
            score_rows.append(
                _validate_ranking(
                    ranking,
                    request=request,
                    catalog_version=catalog_version,
                    identity=selected_identity,
                    expected_ids=expected_ids,
                )
            )
            if not await catalog_provider.catalog_is_current(candidates):
                raise ValueError("semantic catalog changed during query execution")
    if len(score_rows) != SEMANTIC_QUERY_CALL_LIMIT:
        raise ValueError("semantic query call count changed")

    chosen = _select_distinct_pair(
        candidates,
        (score_rows[0], score_rows[1]),
        forbidden_public_refs=forbidden_public_refs,
    )
    references: list[SemanticReference] = []
    for placement_index, ((ordinal, section_index), candidate, request, contract) in enumerate(
        zip(_PLACEMENTS, chosen, requests, query_contracts, strict=True)
    ):
        refreshed = await catalog_provider.revalidate_candidate(candidate)
        if not _same_candidate_identity(refreshed, candidate):
            raise ValueError("semantic reference changed during revalidation")
        if (
            refreshed.catalog_asset_ref is None
            or refreshed.catalog_asset_id is None
            or refreshed.catalog_version is None
            or refreshed.source_master_sha256 is None
        ):
            raise ValueError("semantic reference lineage is incomplete")
        body = await catalog_provider.read_publication_bytes(
            catalog_asset_ref=refreshed.catalog_asset_ref,
            catalog_version=refreshed.catalog_version,
            source_master_sha256=refreshed.source_master_sha256,
            publication_sha256=refreshed.sha256,
        )
        if len(body) != refreshed.byte_size or sha256(body).hexdigest() != refreshed.sha256:
            raise ValueError("semantic reference publication changed")
        similarity = score_rows[placement_index][refreshed.catalog_asset_id]
        assigned = replace(
            refreshed,
            ordinal=ordinal,
            assigned_section_index=section_index,
            selection_method="multimodal_embedding",
            similarity_band=_similarity_band(similarity),
            selection_reason="exact_block_qwen3_vl_reference",
            selection_reason_code="multimodal_similarity",
        )
        references.append(
            SemanticReference(
                ordinal=ordinal,
                section_index=section_index,
                block_index=contract[1],
                block_kind=contract[2],
                block_fingerprint=contract[3],
                source_text_fingerprint=contract[4],
                query_fingerprint=request.request_fingerprint,
                public_ref=refreshed.catalog_asset_ref,
                catalog_version=refreshed.catalog_version,
                source_master_sha256=refreshed.source_master_sha256,
                publication_sha256=refreshed.sha256,
                similarity_band=_similarity_band(similarity),
                candidate=assigned,
                publication_bytes=body,
            )
        )
    if (
        len(references) != 2
        or references[0].public_ref == references[1].public_ref
        or any(reference.public_ref in forbidden_public_refs for reference in references)
        or not await catalog_provider.catalog_is_current(candidates)
    ):
        raise ValueError("semantic whole-plan fence failed")
    return SemanticSelection(
        references=(references[0], references[1]),
        catalog_version=catalog_version,
        catalog_fingerprint=official_account_catalog_fingerprint(candidates),
        embedding_identity=selected_identity,
    )


def _safe_json(path: Path, payload: object, *, exclusive: bool = False) -> None:
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _write_intent(root: Path, *, reference: SemanticReference, plan: Any) -> None:
    _safe_json(
        root / "intents" / f"body-{reference.ordinal}.intent.json",
        {
            "version": REPORT_VERSION,
            "ordinal": reference.ordinal,
            "section_index": reference.section_index,
            "block_index": reference.block_index,
            "block_kind": reference.block_kind,
            "block_fingerprint": reference.block_fingerprint,
            "source_text_fingerprint": reference.source_text_fingerprint,
            "query_fingerprint": reference.query_fingerprint,
            "reference_public_ref": reference.public_ref,
            "similarity_band": reference.similarity_band,
            "state": "generating",
            "provider": "toapis",
            "paid_call_limit": PAID_IMAGE_CALL_LIMIT,
            "request_fingerprint": plan.request_fingerprint,
            "automatic_retry_permitted": False,
        },
        exclusive=True,
    )


def _write_failure(
    root: Path,
    *,
    reference: SemanticReference,
    plan: Any,
    state: Literal["failed", "result_unknown"],
    error_code: str,
) -> None:
    _safe_json(
        root / "intents" / f"body-{reference.ordinal}.result.json",
        {
            "version": REPORT_VERSION,
            "ordinal": reference.ordinal,
            "state": state,
            "safe_error_code": error_code,
            "request_fingerprint": plan.request_fingerprint,
            "automatic_retry_permitted": False,
        },
        exclusive=True,
    )


def _validate_jpeg(body: bytes) -> dict[str, Any]:
    try:
        with Image.open(BytesIO(body)) as image:
            image.load()
            if image.format != "JPEG" or image.size != (1536, 1024):
                raise ImageOutputValidationError("image_output_invalid")
            if image.getexif() or image.info.get("icc_profile"):
                raise ImageOutputValidationError("image_output_invalid")
    except (OSError, UnidentifiedImageError) as error:
        raise ImageOutputValidationError("image_output_invalid") from error
    return {
        "media_type": "image/jpeg",
        "width": 1536,
        "height": 1024,
        "byte_size": len(body),
        "sha256": sha256(body).hexdigest(),
        "metadata_free": True,
    }


def _resolve_html(canonical_html: str) -> str:
    resolved = canonical_html
    for ordinal, image_name in enumerate(BODY_IMAGE_NAMES):
        placeholder = body_media_placeholder(ordinal)
        if resolved.count(placeholder) != 1:
            raise ValueError("semantic render placeholder set is invalid")
        resolved = resolved.replace(placeholder, f"assets/{image_name}")
    if "__OFFICIAL_ACCOUNT_BODY_MEDIA_" in resolved:
        raise ValueError("semantic render retains a media placeholder")
    return resolved


def _selection_projection(selection: SemanticSelection) -> dict[str, object]:
    return {
        "version": SEMANTIC_SELECTOR_VERSION,
        "status": "semantic_ready",
        "catalog_version": selection.catalog_version,
        "catalog_fingerprint": selection.catalog_fingerprint,
        "embedding_identity": {
            "provider": selection.embedding_identity.provider,
            "model": selection.embedding_identity.model,
            "dimensions": selection.embedding_identity.dimensions,
            "input_policy_version": selection.embedding_identity.input_policy_version,
        },
        "query_call_count": SEMANTIC_QUERY_CALL_LIMIT,
        "assignments": [
            {
                "ordinal": reference.ordinal,
                "section_index": reference.section_index,
                "block_index": reference.block_index,
                "block_kind": reference.block_kind,
                "block_fingerprint": reference.block_fingerprint,
                "source_text_fingerprint": reference.source_text_fingerprint,
                "query_fingerprint": reference.query_fingerprint,
                "reference_public_ref": reference.public_ref,
                "catalog_version": reference.catalog_version,
                "publication_sha256": reference.publication_sha256,
                "selection_method": "multimodal_embedding",
                "similarity_band": reference.similarity_band,
            }
            for reference in selection.references
        ],
    }


def _publish_temporary(temporary: Path, output_dir: Path) -> None:
    diagnostics_paths = tuple(
        terminal_diagnostics_path(output_dir, state) for state in _TERMINAL_STATES
    )
    if (
        output_dir.exists()
        or output_dir.is_symlink()
        or any(path.exists() or path.is_symlink() for path in diagnostics_paths)
    ):
        raise FileExistsError("refusing to replace an existing semantic-generated directory")
    temporary.rename(output_dir)


def terminal_diagnostics_path(output_dir: Path, state: TerminalState) -> Path:
    suffix = "result-unknown" if state == "result_unknown" else "failed"
    return output_dir.with_name(f"{output_dir.name}.{suffix}-diagnostics")


def _publish_terminal_diagnostics(
    temporary: Path,
    output_dir: Path,
    state: TerminalState,
) -> Path:
    diagnostics = terminal_diagnostics_path(output_dir, state)
    all_diagnostics = tuple(
        terminal_diagnostics_path(output_dir, terminal_state) for terminal_state in _TERMINAL_STATES
    )
    if (
        output_dir.exists()
        or output_dir.is_symlink()
        or any(path.exists() or path.is_symlink() for path in all_diagnostics)
    ):
        raise FileExistsError("refusing to replace semantic-generated output or diagnostics")
    temporary.rename(diagnostics)
    return diagnostics


def _historical_public_refs(
    bundle: EditorialSourceBundle,
) -> frozenset[str]:
    refs = frozenset(str(row.get("reference_public_ref", "")) for row in bundle.visual_rows)
    if len(refs) != 3 or any(
        len(public_ref) != 16
        or any(character not in "0123456789abcdef" for character in public_ref)
        for public_ref in refs
    ):
        raise ValueError("inherited source reference set is invalid")
    return refs


def _write_failed_run(
    root: Path,
    *,
    run_id: UUID,
    state: Literal["failed", "result_unknown"],
    error_code: str,
    attempted: int,
    succeeded: int,
) -> None:
    _safe_json(
        root / "run.json",
        {
            "version": REPORT_VERSION,
            "run_id": str(run_id),
            "status": state,
            "simulation": True,
            "local_only": True,
            "published": False,
            "safe_error_code": error_code,
            "embedding_provider_calls": SEMANTIC_QUERY_CALL_LIMIT,
            "paid_generation_calls_attempted": attempted,
            "paid_generation_calls_succeeded": succeeded,
            "paid_generation_call_limit": PAID_IMAGE_CALL_LIMIT,
            "automatic_retry_permitted": False,
            "comfly_calls": 0,
            "wechat_calls": 0,
            "wecom_calls": 0,
            "publish_calls": 0,
        },
    )


async def export_semantic_generated_bundle(
    source_dir: Path,
    catalog_manifest: Path,
    output_dir: Path,
    *,
    repository: VisualIndexRepository,
    embeddings_context_factory: EmbeddingContextFactory,
    image_context_factory: ImageContextFactory,
    image_model: str = "gpt-image-2",
    max_download_bytes: int = 20 * 1024 * 1024,
    catalog_provider: _CatalogProvider | None = None,
    embedding_identity: VisualEmbeddingIdentity | None = None,
) -> bool:
    """Export a fresh v5 bundle, or an atomic terminal partial on provider failure."""

    if (
        output_dir.exists()
        or output_dir.is_symlink()
        or any(
            terminal_diagnostics_path(output_dir, state).exists()
            or terminal_diagnostics_path(output_dir, state).is_symlink()
            for state in _TERMINAL_STATES
        )
    ):
        raise FileExistsError("refusing to replace an existing semantic-generated directory")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    bundle = asset_rich_v4.load_source_bundle(source_dir)
    forbidden_public_refs = _historical_public_refs(bundle)
    article_package = build_semantic_article(bundle)
    article = _stored_article(article_package)
    render = _stored_render(article)
    provider = catalog_provider or LocalOfficialAccountCatalogMediaProvider(catalog_manifest)
    selection = await select_semantic_references(
        article=article_package,
        catalog_provider=provider,
        repository=repository,
        embeddings_context_factory=embeddings_context_factory,
        forbidden_public_refs=forbidden_public_refs,
        identity=embedding_identity,
    )
    run_id = uuid5(
        NAMESPACE_URL,
        f"{REPORT_VERSION}:{article_package.content_fingerprint}:"
        f"{selection.catalog_fingerprint}:{image_model}",
    )
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    published = False
    try:
        (temporary / "assets").mkdir()
        (temporary / "intents").mkdir()
        _safe_json(
            temporary / "semantic-selection.json",
            _selection_projection(selection),
            exclusive=True,
        )
        generated_rows: list[dict[str, Any]] = []
        generated_bodies: list[bytes] = []
        async with image_context_factory() as generator:
            for call_index, reference in enumerate(selection.references, start=1):
                plan = plan_generated_body_visual(
                    run_id=run_id,
                    article=article,
                    render=render,
                    ordinal=reference.ordinal,
                    reference=reference.candidate,
                    provider="toapis",
                    model=image_model,
                    reference_bytes=reference.publication_bytes,
                    plan_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
                    prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
                )
                if (
                    plan.block_index != reference.block_index
                    or plan.block_kind != reference.block_kind
                    or plan.block_fingerprint != reference.block_fingerprint
                ):
                    raise ValueError("semantic generation block anchor changed")
                prompt = build_generated_visual_prompt(
                    article=article,
                    section_index=reference.section_index,
                    reference=reference.candidate,
                    prompt_version=plan.prompt_version,
                    block_index=reference.block_index,
                )
                _write_intent(temporary, reference=reference, plan=plan)
                request = ImageGenerationRequest(
                    run_id=run_id,
                    draft_version_id=article.id,
                    prompt=prompt,
                    request_fingerprint=plan.request_fingerprint,
                    references=(
                        ImageReference(
                            role="approved_ip_reference",
                            asset_id=reference.public_ref,
                            filename=f"approved-ip-reference-{reference.ordinal}.jpg",
                            sha256=reference.publication_sha256,
                            image_bytes=reference.publication_bytes,
                            selection_reason="exact_block_qwen3_vl_reference",
                            input_normalization_version=(
                                plan.reference_input_version or IMAGE_REFERENCE_INPUT_V2
                            ),
                            provider_input_sha256=plan.reference_input_checksum,
                        ),
                    ),
                    reference_mode="single_reference",
                )
                try:
                    result = await generator.generate(request)
                    if result.attempts != 1:
                        raise ImageOutputValidationError("image_output_invalid")
                    publication = prepare_generated_visual_result(
                        result=result,
                        plan=plan,
                        max_bytes=max_download_bytes,
                    )
                    output = _validate_jpeg(publication.image_bytes)
                except (ImageProviderTimeoutError, TimeoutError) as error:
                    code = error.code if isinstance(error, AppError) else "image_provider_timeout"
                    _write_failure(
                        temporary,
                        reference=reference,
                        plan=plan,
                        state="result_unknown",
                        error_code=code,
                    )
                    _write_failed_run(
                        temporary,
                        run_id=run_id,
                        state="result_unknown",
                        error_code=code,
                        attempted=call_index,
                        succeeded=len(generated_rows),
                    )
                    _publish_terminal_diagnostics(temporary, output_dir, "result_unknown")
                    published = True
                    return False
                except AppError as error:
                    _write_failure(
                        temporary,
                        reference=reference,
                        plan=plan,
                        state="failed",
                        error_code=error.code,
                    )
                    _write_failed_run(
                        temporary,
                        run_id=run_id,
                        state="failed",
                        error_code=error.code,
                        attempted=call_index,
                        succeeded=len(generated_rows),
                    )
                    _publish_terminal_diagnostics(temporary, output_dir, "failed")
                    published = True
                    return False
                generated_bodies.append(publication.image_bytes)
                row = {
                    "ordinal": reference.ordinal,
                    "section_index": reference.section_index,
                    "block_index": reference.block_index,
                    "block_kind": reference.block_kind,
                    "block_fingerprint": reference.block_fingerprint,
                    "source_text_fingerprint": reference.source_text_fingerprint,
                    "query_fingerprint": reference.query_fingerprint,
                    "semantic_alt": _SEMANTIC_SCENE_ALTS[reference.ordinal],
                    "reference_public_ref": reference.public_ref,
                    "reference_catalog_version": reference.catalog_version,
                    "reference_input_version": plan.reference_input_version,
                    "reference_input_sha256": plan.reference_input_checksum,
                    "similarity_band": reference.similarity_band,
                    "plan_version": plan.plan_version,
                    "prompt_version": plan.prompt_version,
                    "output_profile_version": plan.output_profile_version,
                    "request_fingerprint": plan.request_fingerprint,
                    "output": output,
                    "provider_attempts": 1,
                    "automatic_retry_permitted": False,
                }
                generated_rows.append(row)
                _safe_json(
                    temporary / "intents" / f"body-{reference.ordinal}.result.json",
                    row,
                    exclusive=True,
                )

        if len(generated_rows) != PAID_IMAGE_CALL_LIMIT or len(generated_bodies) != 2:
            raise ValueError("semantic image call set is incomplete")
        all_bodies = (*bundle.image_bodies, *generated_bodies)
        all_checksums = tuple(sha256(body).hexdigest() for body in all_bodies)
        if len(all_bodies) != 5 or len(set(all_checksums)) != 5:
            raise ValueError("semantic-generated scenes must have five distinct outputs")
        for name, body in zip(BODY_IMAGE_NAMES, all_bodies, strict=True):
            with (temporary / "assets" / name).open("xb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())

        canonical_html = render.canonical_html
        resolved_html = _resolve_html(canonical_html)
        render_fingerprint = fingerprint(
            REPORT_VERSION,
            RENDERER_VERSION,
            STYLE_VERSION,
            TEMPLATE_VERSION,
            canonical_html,
            all_checksums,
            tuple(row["request_fingerprint"] for row in generated_rows),
        )
        (temporary / "article-body.html").write_text(resolved_html, encoding="utf-8")
        (temporary / "preview.html").write_text(
            polished_v3._preview_document(resolved_html), encoding="utf-8"
        )
        (temporary / "article.md").write_text(
            polished_v3._article_markdown(article_package), encoding="utf-8"
        )
        polished_v3._write_json(
            temporary / "article-package.json",
            {"version": ARTICLE_SCHEMA_VERSION, "article": article_package.model_dump(mode="json")},
        )
        polished_v3._write_json(
            temporary / "evidence.json",
            {
                "version": "official-account-news-editorial-evidence-v5",
                "source_snapshot_version": SOURCE_EVIDENCE_VERSION,
                "fact_brand_boundary": (
                    "external facts use evidence; semantic IP visuals prove no facts"
                ),
                "sources": list(bundle.evidence_sources),
                "claims": [claim.model_dump(mode="json") for claim in article_package.claims],
            },
        )
        inherited_rows: list[dict[str, Any]] = []
        for ordinal, (source_row, checksum, section_index) in enumerate(
            zip(bundle.visual_rows, bundle.image_checksums, (0, 2, 4), strict=True)
        ):
            inherited_rows.append(
                {
                    "ordinal": ordinal,
                    "section_index": section_index,
                    "output_sha256": checksum,
                    "source_output_sha256": source_row["output"]["sha256"],
                    "provenance_kind": "inherited_paid_generated_scene",
                    "reused_byte_exact": True,
                    "inherited_reference_public_ref": source_row["reference_public_ref"],
                    "current_v5_provider_calls": 0,
                }
            )
        polished_v3._write_json(
            temporary / "visual-map.json",
            {
                "version": "official-account-news-editorial-visual-map-v5-five-scene",
                "quality_status": "pending_local_visual_inspection_for_two_new_scenes",
                "visuals": [*inherited_rows, *generated_rows],
            },
        )
        polished_v3._write_json(
            temporary / "reference-learning.json",
            {
                "version": REFERENCE_STUDY_VERSION,
                "reference_url": REFERENCE_URL,
                "retained_source_content": False,
                "retained_source_html": False,
                "retained_source_images": False,
                "copied_reference_expression": False,
                "applied_original_patterns": [
                    "five exact-block 3:2 scenes distributed through the article",
                    "two approved IP references selected by complete-index multimodal retrieval",
                    "one semantic alt and one single-use slot per visual",
                ],
            },
        )
        polished_v3._write_json(
            temporary / "run.json",
            {
                "version": REPORT_VERSION,
                "run_id": str(run_id),
                "status": "ready",
                "simulation": True,
                "local_only": True,
                "copy_ready": False,
                "published": False,
                "manual_review_status": "pending",
                "visual_quality_status": "pending_local_visual_inspection",
                "article_body_character_count": article_body_character_count(article_package),
                "article_section_count": len(article_package.sections),
                "body_image_count": 5,
                "content_fingerprint": article_package.content_fingerprint,
                "render_fingerprint": render_fingerprint,
                "catalog_version": selection.catalog_version,
                "catalog_fingerprint": selection.catalog_fingerprint,
                "embedding_provider_calls": SEMANTIC_QUERY_CALL_LIMIT,
                "paid_generation_calls_attempted": PAID_IMAGE_CALL_LIMIT,
                "paid_generation_calls_succeeded": PAID_IMAGE_CALL_LIMIT,
                "paid_generation_call_limit": PAID_IMAGE_CALL_LIMIT,
                "inherited_historical_paid_image_calls": 3,
                "image_provider": "toapis",
                "image_model": image_model,
                "automatic_retry_permitted": False,
                "article_provider_calls": 0,
                "source_fetch_calls_in_run": 0,
                "comfly_calls": 0,
                "wechat_calls": 0,
                "wecom_calls": 0,
                "publish_calls": 0,
            },
        )
        (temporary / "README.md").write_text(
            "# 教育部新闻 × 小赛 IP｜语义五场景版 v5\n\n"
            "前三张 3:2 场景逐字节继承已检查的 v1 结果；后两张先用完整 41 项 Qwen3-VL "
            "索引按正文块选取不同的批准 IP 参考，再各调用一次 ToApis，规范为无元数据的 "
            "1536×1024 JPEG。\n\n"
            "- 本地：simulation / local-only / unpublished\n"
            "- 调用：Embedding 2 次、生图 2 次、无自动重试\n"
            "- 社交：微信、企微、发布调用均为 0\n"
            "- 状态：正文人工审核与两张新图本地视觉检查待完成\n\n"
            "打开 `preview.html` 查看 320--430 px 本地预览。\n",
            encoding="utf-8",
        )
        payload = tuple(
            sorted(
                (path for path in temporary.rglob("*") if path.is_file()),
                key=lambda path: path.relative_to(temporary).as_posix(),
            )
        )
        polished_v3._write_json(
            temporary / "manifest.json",
            {
                "version": REPORT_VERSION,
                "status": "ready",
                "simulation": True,
                "local_only": True,
                "published": False,
                "manual_review_status": "pending",
                "embedding_provider_calls": SEMANTIC_QUERY_CALL_LIMIT,
                "image_provider_calls": PAID_IMAGE_CALL_LIMIT,
                "comfly_calls": 0,
                "wechat_calls": 0,
                "wecom_calls": 0,
                "publish_calls": 0,
                "files": [
                    {
                        "path": path.relative_to(temporary).as_posix(),
                        "byte_size": path.stat().st_size,
                        "sha256": sha256(path.read_bytes()).hexdigest(),
                    }
                    for path in payload
                ],
            },
        )
        polished_v3._zip_bundle(temporary, archive_root_name=output_dir.name)
        _publish_temporary(temporary, output_dir)
        published = True
        return True
    finally:
        if not published and temporary.exists():
            shutil.rmtree(temporary)


def _preflight_live_settings(settings: Settings, output_dir: Path) -> Settings:
    if (
        output_dir.exists()
        or output_dir.is_symlink()
        or any(
            terminal_diagnostics_path(output_dir, state).exists()
            or terminal_diagnostics_path(output_dir, state).is_symlink()
            for state in _TERMINAL_STATES
        )
    ):
        raise FileExistsError("refusing to replace an existing semantic-generated directory")
    if settings.visual_embedding_provider_mode != "alibaba":
        raise ValueError("v5 requires the active Alibaba Qwen3-VL embedding provider")
    if settings.visual_embedding_endpoint is None or settings.visual_embedding_api_key is None:
        raise ValueError("v5 requires server-side Qwen3-VL credentials")
    if settings.toapis_api_key is None or not settings.toapis_api_key.get_secret_value().strip():
        raise ValueError("v5 requires a server-side ToApis key")
    if settings.toapis_base_url != "https://toapis.com":
        raise ValueError("v5 requires the pinned ToApis origin")
    return settings.model_copy(update={"image_provider_mode": "toapis", "image_max_attempts": 1})


@asynccontextmanager
async def _live_embeddings_context(settings: Settings) -> AsyncIterator[VisualEmbeddingModel]:
    assert settings.visual_embedding_endpoint is not None
    assert settings.visual_embedding_api_key is not None
    async with httpx.AsyncClient(follow_redirects=False) as client:
        yield AlibabaVisualEmbeddingAdapter(
            client=client,
            endpoint=settings.visual_embedding_endpoint,
            api_key=settings.visual_embedding_api_key,
            timeout_seconds=settings.visual_embedding_timeout_seconds,
            concurrency=1,
        )


@asynccontextmanager
async def _live_image_context(settings: Settings) -> AsyncIterator[ImageGenerator]:
    async with httpx.AsyncClient(follow_redirects=False) as client:
        yield create_image_generator(settings, client=client)


async def run_live_semantic_generated_bundle(
    *,
    source_dir: Path,
    catalog_manifest: Path,
    output_dir: Path,
) -> bool:
    settings = _preflight_live_settings(get_settings(), output_dir)
    engine = create_engine(settings)
    try:
        repository = PostgresVisualIndexRepository(create_session_factory(engine))
        return await export_semantic_generated_bundle(
            source_dir,
            catalog_manifest,
            output_dir,
            repository=repository,
            embeddings_context_factory=lambda: _live_embeddings_context(settings),
            image_context_factory=lambda: _live_image_context(settings),
            image_model=settings.image_model,
            max_download_bytes=settings.image_max_download_bytes,
            embedding_identity=settings.visual_embedding_identity,
        )
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--catalog-manifest", type=Path, default=DEFAULT_CATALOG_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    ready = asyncio.run(
        run_live_semantic_generated_bundle(
            source_dir=args.source_dir,
            catalog_manifest=args.catalog_manifest,
            output_dir=args.output_dir,
        )
    )
    print(args.output_dir)
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
