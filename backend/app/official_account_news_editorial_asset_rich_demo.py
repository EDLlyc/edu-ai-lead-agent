# ruff: noqa: RUF001 -- Chinese editorial copy is intentional.
"""Provider-free five-image editorial repackage with approved local IP assets.

The command validates the frozen v1 news/IP bundle, builds an additive v4 Article
Package from the frozen v3 article, and resolves two pinned publication derivatives
through the local approved-catalog adapter. It never constructs a network, model,
image-generation, WeChat, WeCom, or publish client.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, UnidentifiedImageError

from app import official_account_news_editorial_polished_demo as polished_v3
from app.application.ports.official_account_local import OfficialAccountSourceMedia
from app.domain.official_account_local import (
    ArticleBulletListBlock,
    ArticleImageBlock,
    ArticleMediaSlot,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleQuoteBlock,
    ArticleVersionBundle,
    article_body_character_count,
    article_package_fingerprint,
    body_media_placeholder,
    fingerprint,
)
from app.infrastructure.official_account_catalog import (
    OFFICIAL_ACCOUNT_CATALOG_EXPECTED_ASSET_COUNT,
    OFFICIAL_ACCOUNT_CATALOG_PUBLICATION_MEDIA_TYPE,
    LocalOfficialAccountCatalogMediaProvider,
    official_account_catalog_fingerprint,
)
from app.official_account_news_editorial_demo import (
    EditorialSourceBundle,
)
from app.official_account_news_editorial_demo import (
    load_source_bundle as load_source_bundle,
)

NEWS_URL = polished_v3.NEWS_URL
PLAN_URL = polished_v3.PLAN_URL
REFERENCE_URL = polished_v3.REFERENCE_URL
SOURCE_REPORT_VERSION = polished_v3.SOURCE_REPORT_VERSION
SOURCE_EVIDENCE_VERSION = polished_v3.SOURCE_EVIDENCE_VERSION
INHERITED_BODY_IMAGE_NAMES = polished_v3.BODY_IMAGE_NAMES
BODY_IMAGE_NAMES = tuple(f"body-{ordinal:02d}.jpg" for ordinal in range(5))
BODY_TARGET_MIN = polished_v3.BODY_TARGET_MIN
BODY_TARGET_MAX = polished_v3.BODY_TARGET_MAX

REPORT_VERSION = "official-account-news-editorial-asset-rich-demo-v4"
ARTICLE_SCHEMA_VERSION = "official-account-news-editorial-schema-v4-approved-catalog-five-image"
RENDERER_VERSION = "wechat-news-editorial-renderer-v4-approved-catalog-five-image"
STYLE_VERSION = "wechat-news-editorial-style-v4-navy-cobalt-orange-cutaways"
TEMPLATE_VERSION = "wechat-news-editorial-template-v4-five-image-mobile"
REFERENCE_STUDY_VERSION = "wechat-public-reference-patterns-v3-approved-ip-cutaways"
LOCAL_ADAPTER_VERSION = "official-account-news-editorial-local-adapter-v4-approved-catalog"
DEFAULT_SOURCE_DIR = Path("output/official-account-news-ip-20260824-v1")
DEFAULT_CATALOG_MANIFEST = Path("private/brand-materials/visual-assets.manifest.json")
DEFAULT_OUTPUT_DIR = Path("output/official-account-news-ip-editorial-20260825-v4")

PARENT_QUESTION_PUBLIC_REF = "1bb84f2abb140b8f"
AI_BOUNDARY_PUBLIC_REF = "bab27fe77a8edff4"
APPROVED_PUBLIC_REFS = (PARENT_QUESTION_PUBLIC_REF, AI_BOUNDARY_PUBLIC_REF)
HISTORICAL_PUBLIC_REFS = frozenset(("33586a916bbbfbf1", "5c2a29bbec16ca4f", "09c8fd9470cb5502"))
_EXPECTED_CATALOG_VERSION = "brand-visual-catalog-v1"


@dataclass(frozen=True, slots=True)
class _CatalogAssetContract:
    label: str
    tags: tuple[str, ...]
    width: int
    height: int
    section_index: int
    slot_key: str
    alt: str
    field: str


_EXPECTED_CATALOG_ASSETS = {
    PARENT_QUESTION_PUBLIC_REF: _CatalogAssetContract(
        label="小赛和赛先生思考",
        tags=(
            "discuss",
            "editorial",
            "education",
            "reading",
            "science",
            "think",
            "thinking",
        ),
        width=614,
        height=614,
        section_index=1,
        slot_key="body-3",
        alt="小赛和赛先生一起提问、思考和交流，呼应家长三问",
        field="warm",
    ),
    AI_BOUNDARY_PUBLIC_REF: _CatalogAssetContract(
        label="小赛探测",
        tags=(
            "ai",
            "discover",
            "experiment",
            "explore",
            "observe",
            "robotics",
            "robotics_lab",
            "science",
        ),
        width=1_536,
        height=1_536,
        section_index=3,
        slot_key="body-4",
        alt="小赛使用科学工具观察和探测，呼应AI协助与孩子判断的边界",
        field="blue",
    ),
}
_V3_MODULE_MARKERS = polished_v3._MODULE_MARKERS
_ZERO_CALLS = {
    "source_fetch_calls_in_repackage": 0,
    "article_provider_calls_in_repackage": 0,
    "embedding_provider_calls_in_repackage": 0,
    "image_provider_calls_in_repackage": 0,
    "comfly_calls_in_repackage": 0,
    "toapis_calls_in_repackage": 0,
    "wechat_calls": 0,
    "wecom_calls": 0,
    "publish_calls": 0,
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


@dataclass(frozen=True, slots=True)
class ApprovedCatalogPublication:
    """Safe publication-bound projection; deliberately excludes private catalog identity."""

    public_ref: str
    catalog_version: str
    source_master_sha256: str
    publication_sha256: str
    media_type: str
    byte_size: int
    width: int
    height: int
    reader_label: str
    semantic_tags: tuple[str, ...]
    semantic_alt: str
    caption: str
    section_index: int
    slot_key: str
    body: bytes


@dataclass(frozen=True, slots=True)
class ApprovedCatalogSelection:
    publications: tuple[ApprovedCatalogPublication, ApprovedCatalogPublication]
    catalog_version: str
    complete_catalog_fingerprint: str


def _versions() -> ArticleVersionBundle:
    return ArticleVersionBundle(
        generator_prompt_version="official-account-news-editorial-assembler-v4-approved-catalog",
        article_schema_version=ARTICLE_SCHEMA_VERSION,
        auditor_prompt_version="official-account-news-editorial-audit-v4",
        audit_schema_version="official-account-news-editorial-audit-schema-v4",
        rule_version="official-account-news-editorial-rules-v4-evidence-bound-five-image",
        renderer_version=RENDERER_VERSION,
        style_version=STYLE_VERSION,
        template_version=TEMPLATE_VERSION,
        local_adapter_version=LOCAL_ADAPTER_VERSION,
    )


def _safe_digest(value: str | None, *, field: str) -> str:
    if (
        value is None
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"approved catalog {field} is invalid")
    return value


def _safe_public_ref(value: str | None) -> str:
    if (
        value is None
        or len(value) != 16
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("approved catalog public reference is invalid")
    return value


def _candidate_public_identity(candidate: OfficialAccountSourceMedia) -> tuple[object, ...]:
    return (
        candidate.catalog_asset_ref,
        candidate.catalog_version,
        candidate.source_master_sha256,
        candidate.sha256,
        candidate.byte_size,
        candidate.media_type,
        candidate.semantic_label,
        candidate.semantic_tags,
        candidate.alt_text,
        candidate.caption_text,
    )


def _inspect_publication(
    body: bytes,
    *,
    expected_width: int,
    expected_height: int,
) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(body)) as opened:
            opened.load()
            if (
                opened.format != "JPEG"
                or opened.size != (expected_width, expected_height)
                or opened.getexif()
                or "icc_profile" in opened.info
            ):
                raise ValueError("approved catalog publication profile changed")
            return opened.size
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError("approved catalog publication bytes cannot be decoded") from error


async def load_approved_catalog_publications(
    manifest_path: Path,
    *,
    provider: _CatalogProvider | None = None,
) -> ApprovedCatalogSelection:
    """Resolve exactly two pinned local derivatives through a complete catalog fence."""

    catalog_provider: _CatalogProvider = provider or LocalOfficialAccountCatalogMediaProvider(
        manifest_path
    )
    candidates = await catalog_provider.load_candidates()
    if len(candidates) != OFFICIAL_ACCOUNT_CATALOG_EXPECTED_ASSET_COUNT:
        raise ValueError("approved catalog does not contain the complete 41-item set")

    public_refs = tuple(_safe_public_ref(candidate.catalog_asset_ref) for candidate in candidates)
    source_checksums = tuple(
        _safe_digest(candidate.source_master_sha256, field="source-master checksum")
        for candidate in candidates
    )
    publication_checksums = tuple(
        _safe_digest(candidate.sha256, field="publication checksum") for candidate in candidates
    )
    if (
        len(set(public_refs)) != len(candidates)
        or len(set(source_checksums)) != len(candidates)
        or len(set(publication_checksums)) != len(candidates)
    ):
        raise ValueError("approved catalog identities must be complete and unique")
    if set(APPROVED_PUBLIC_REFS) & HISTORICAL_PUBLIC_REFS:
        raise ValueError("approved catalog selection reuses a historical reference")

    by_ref = dict(zip(public_refs, candidates, strict=True))
    if not all(public_ref in by_ref for public_ref in APPROVED_PUBLIC_REFS):
        raise ValueError("approved catalog pinned publication is unavailable")

    publications: list[ApprovedCatalogPublication] = []
    for public_ref in APPROVED_PUBLIC_REFS:
        expected = _EXPECTED_CATALOG_ASSETS[public_ref]
        candidate = by_ref[public_ref]
        if (
            candidate.catalog_version != _EXPECTED_CATALOG_VERSION
            or candidate.media_type != OFFICIAL_ACCOUNT_CATALOG_PUBLICATION_MEDIA_TYPE
            or candidate.semantic_label != expected.label
            or candidate.semantic_tags != expected.tags
        ):
            raise ValueError("approved catalog pinned metadata changed")
        refreshed = await catalog_provider.revalidate_candidate(candidate)
        if _candidate_public_identity(refreshed) != _candidate_public_identity(candidate):
            raise ValueError("approved catalog candidate changed during revalidation")
        catalog_version = str(refreshed.catalog_version)
        source_master_sha256 = _safe_digest(
            refreshed.source_master_sha256, field="source-master checksum"
        )
        publication_sha256 = _safe_digest(refreshed.sha256, field="publication checksum")
        body = await catalog_provider.read_publication_bytes(
            catalog_asset_ref=public_ref,
            catalog_version=catalog_version,
            source_master_sha256=source_master_sha256,
            publication_sha256=publication_sha256,
        )
        if len(body) != refreshed.byte_size or sha256(body).hexdigest() != publication_sha256:
            raise ValueError("approved catalog publication bytes changed")
        width, height = _inspect_publication(
            body,
            expected_width=expected.width,
            expected_height=expected.height,
        )
        publications.append(
            ApprovedCatalogPublication(
                public_ref=public_ref,
                catalog_version=catalog_version,
                source_master_sha256=source_master_sha256,
                publication_sha256=publication_sha256,
                media_type=refreshed.media_type,
                byte_size=len(body),
                width=width,
                height=height,
                reader_label=refreshed.semantic_label,
                semantic_tags=refreshed.semantic_tags,
                semantic_alt=expected.alt,
                caption=refreshed.caption_text,
                section_index=expected.section_index,
                slot_key=expected.slot_key,
                body=body,
            )
        )

    if not await catalog_provider.catalog_is_current(candidates):
        raise ValueError("approved catalog changed after publication reads")
    if len({item.publication_sha256 for item in publications}) != len(publications):
        raise ValueError("approved catalog selected duplicate publication bytes")
    return ApprovedCatalogSelection(
        publications=(publications[0], publications[1]),
        catalog_version=_EXPECTED_CATALOG_VERSION,
        complete_catalog_fingerprint=official_account_catalog_fingerprint(candidates),
    )


def _as_polished_projection(article: ArticlePackage) -> ArticlePackage:
    questions = article.sections[1]
    boundary = article.sections[3]
    projected_sections = (
        article.sections[0],
        questions.model_copy(update={"blocks": (*questions.blocks[:3], questions.blocks[4])}),
        article.sections[2],
        boundary.model_copy(
            update={"blocks": (boundary.blocks[0], boundary.blocks[1], boundary.blocks[3])}
        ),
        article.sections[4],
        article.sections[5],
    )
    provisional = article.model_copy(
        update={
            "sections": projected_sections,
            "media_slots": (
                ArticleMediaSlot(slot_key="body-0", role="body", ordinal=0),
                ArticleMediaSlot(slot_key="body-1", role="body", ordinal=1),
                ArticleMediaSlot(slot_key="body-2", role="body", ordinal=2),
                ArticleMediaSlot(slot_key="cover-0", role="cover", ordinal=0),
            ),
            "versions": polished_v3._versions(),
            "content_fingerprint": "0" * 64,
        }
    )
    return provisional.model_copy(
        update={"content_fingerprint": article_package_fingerprint(provisional)}
    )


def _module_shapes(article: ArticlePackage) -> tuple[tuple[type[object], ...], ...]:
    return tuple(tuple(type(block) for block in section.blocks) for section in article.sections)


def _validate_asset_rich_article(article: ArticlePackage) -> None:
    if article.versions != _versions():
        raise ValueError("asset-rich editorial Article Package version changed")
    if len(article.sections) != 6:
        raise ValueError("asset-rich editorial Article Package must contain exactly six units")
    if not BODY_TARGET_MIN <= article_body_character_count(article) <= BODY_TARGET_MAX:
        raise ValueError("asset-rich editorial article is outside the approved target length")
    if article.content_fingerprint != article_package_fingerprint(article):
        raise ValueError("asset-rich editorial Article Package fingerprint changed")
    expected_shapes = (
        (ArticleParagraphBlock, ArticleBulletListBlock, ArticleQuoteBlock, ArticleImageBlock),
        (
            ArticleParagraphBlock,
            ArticleParagraphBlock,
            ArticleParagraphBlock,
            ArticleImageBlock,
            ArticleQuoteBlock,
        ),
        (ArticleParagraphBlock, ArticleParagraphBlock, ArticleBulletListBlock, ArticleImageBlock),
        (ArticleParagraphBlock, ArticleBulletListBlock, ArticleImageBlock, ArticleQuoteBlock),
        (ArticleParagraphBlock, ArticleBulletListBlock, ArticleParagraphBlock, ArticleImageBlock),
        (ArticleParagraphBlock, ArticleParagraphBlock, ArticleQuoteBlock),
    )
    if _module_shapes(article) != expected_shapes:
        raise ValueError("asset-rich editorial module shape changed")
    placements = tuple(
        (section_index, block.slot_key)
        for section_index, section in enumerate(article.sections)
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    )
    if placements != (
        (0, "body-0"),
        (1, "body-3"),
        (2, "body-1"),
        (3, "body-4"),
        (4, "body-2"),
    ):
        raise ValueError("asset-rich editorial image placements changed")
    slots = tuple((slot.slot_key, slot.role, slot.ordinal) for slot in article.media_slots)
    if slots != (
        ("body-0", "body", 0),
        ("body-1", "body", 1),
        ("body-2", "body", 2),
        ("body-3", "body", 3),
        ("body-4", "body", 4),
        ("cover-0", "cover", 0),
    ):
        raise ValueError("asset-rich editorial media slots changed")
    images = tuple(
        block
        for section in article.sections
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    )
    if any(block.claim_refs for block in images):
        raise ValueError("asset-rich editorial images cannot assert factual claims")
    if (
        images[1].alt_text != _EXPECTED_CATALOG_ASSETS[PARENT_QUESTION_PUBLIC_REF].alt
        or images[3].alt_text != _EXPECTED_CATALOG_ASSETS[AI_BOUNDARY_PUBLIC_REF].alt
    ):
        raise ValueError("asset-rich editorial catalog alt text changed")
    polished_v3._validate_polished_article(_as_polished_projection(article))


def build_asset_rich_article(bundle: EditorialSourceBundle) -> ArticlePackage:
    """Add two block-bound approved-catalog image slots to the validated v3 article."""

    baseline = polished_v3.build_polished_article(bundle)
    question_image = ArticleImageBlock(
        kind="image",
        slot_key="body-3",
        alt_text=_EXPECTED_CATALOG_ASSETS[PARENT_QUESTION_PUBLIC_REF].alt,
    )
    boundary_image = ArticleImageBlock(
        kind="image",
        slot_key="body-4",
        alt_text=_EXPECTED_CATALOG_ASSETS[AI_BOUNDARY_PUBLIC_REF].alt,
    )
    questions = baseline.sections[1]
    boundary = baseline.sections[3]
    sections = (
        baseline.sections[0],
        questions.model_copy(
            update={"blocks": (*questions.blocks[:3], question_image, questions.blocks[3])}
        ),
        baseline.sections[2],
        boundary.model_copy(
            update={
                "blocks": (
                    boundary.blocks[0],
                    boundary.blocks[1],
                    boundary_image,
                    boundary.blocks[2],
                )
            }
        ),
        baseline.sections[4],
        baseline.sections[5],
    )
    provisional = baseline.model_copy(
        update={
            "sections": sections,
            "media_slots": (
                ArticleMediaSlot(slot_key="body-0", role="body", ordinal=0),
                ArticleMediaSlot(slot_key="body-1", role="body", ordinal=1),
                ArticleMediaSlot(slot_key="body-2", role="body", ordinal=2),
                ArticleMediaSlot(slot_key="body-3", role="body", ordinal=3),
                ArticleMediaSlot(slot_key="body-4", role="body", ordinal=4),
                ArticleMediaSlot(slot_key="cover-0", role="cover", ordinal=0),
            ),
            "versions": _versions(),
            "content_fingerprint": "0" * 64,
        }
    )
    article = provisional.model_copy(
        update={"content_fingerprint": article_package_fingerprint(provisional)}
    )
    _validate_asset_rich_article(article)
    return article


_CUTAWAY_STYLE = {
    "warm": (
        "margin:23px 0 21px;padding:13px;background:#f5d34e;"
        "border:1px solid #071b33;box-shadow:7px 7px 0 #f2663a;"
    ),
    "blue": (
        "margin:20px 0 0;padding:13px;background:#dce6ff;"
        "border:1px solid #071b33;box-shadow:7px 7px 0 #1e5bff;"
    ),
    "image_warm": (
        "display:block;width:100%;height:auto;aspect-ratio:1/1;object-fit:contain;"
        "background:#fff7cf;border:0;"
    ),
    "image_blue": (
        "display:block;width:100%;height:auto;aspect-ratio:1/1;object-fit:contain;"
        "background:#eef3ff;border:0;"
    ),
    "label": (
        "margin:11px 3px 4px;color:#071b33;font-size:10px;line-height:1.5;"
        "font-weight:900;letter-spacing:1.5px;"
    ),
    "caption": "margin:0 3px 2px;color:#33445b;font-size:11px;line-height:1.65;",
}


def _catalog_cutaway_html(block: ArticleImageBlock, *, field: str) -> str:
    ordinal = int(block.slot_key.removeprefix("body-"))
    if ordinal not in (3, 4) or field not in {"warm", "blue"}:
        raise ValueError("asset-rich editorial cutaway binding changed")
    return (
        f'<section data-module="catalog-cutaway" data-cutaway-field="{field}" '
        f'style="{_CUTAWAY_STYLE[field]}">'
        f'<img src="{body_media_placeholder(ordinal)}" alt="{escape(block.alt_text, quote=True)}" '
        f'style="{_CUTAWAY_STYLE[f"image_{field}"]}">'
        f'<p style="{_CUTAWAY_STYLE["label"]}">IP 观察札记 · 小赛科学探索</p>'
        f'<p style="{_CUTAWAY_STYLE["caption"]}">{escape(block.alt_text)}</p>'
        "</section>"
    )


def render_asset_rich_html(article: ArticlePackage) -> str:
    _validate_asset_rich_article(article)
    html = polished_v3.render_polished_html(_as_polished_projection(article))
    question_image = article.sections[1].blocks[3]
    boundary_image = article.sections[3].blocks[2]
    if not isinstance(question_image, ArticleImageBlock) or not isinstance(
        boundary_image, ArticleImageBlock
    ):
        raise ValueError("asset-rich editorial cutaway shape changed")

    question_anchor = f'<p style="{polished_v3._STYLE["boundary_note"]}">'
    boundary_anchor = f'<p style="{polished_v3._STYLE["boundary_rule"]}">'
    if html.count(question_anchor) != 1 or html.count(boundary_anchor) != 1:
        raise ValueError("asset-rich editorial render anchor changed")
    html = html.replace(
        question_anchor,
        _catalog_cutaway_html(question_image, field="warm") + question_anchor,
        1,
    )
    html = html.replace(
        boundary_anchor,
        _catalog_cutaway_html(boundary_image, field="blue") + boundary_anchor,
        1,
    )
    if html.count("<h1 ") != 1 or html.count('data-module="catalog-cutaway"') != 2:
        raise ValueError("asset-rich editorial module markers changed")
    if any(html.count(f'data-module="{marker}"') != 1 for marker in _V3_MODULE_MARKERS):
        raise ValueError("asset-rich editorial inherited module markers changed")
    for ordinal in range(5):
        if html.count(body_media_placeholder(ordinal)) != 1:
            raise ValueError("asset-rich editorial render placeholder set is invalid")
    return html


def _catalog_projection(publication: ApprovedCatalogPublication) -> dict[str, object]:
    return {
        "provenance_kind": "approved_local_catalog_publication_derivative",
        "catalog_public_ref": publication.public_ref,
        "catalog_version": publication.catalog_version,
        "source_master_sha256": publication.source_master_sha256,
        "publication_sha256": publication.publication_sha256,
        "media_type": publication.media_type,
        "byte_size": publication.byte_size,
        "width": publication.width,
        "height": publication.height,
        "semantic_tags": list(publication.semantic_tags),
        "reader_label": publication.reader_label,
        "semantic_alt": publication.semantic_alt,
        "caption": publication.caption,
        "section_index": publication.section_index,
        "slot_key": publication.slot_key,
        "current_repackage_provider_calls": 0,
    }


def _resolve_html(canonical_html: str) -> str:
    resolved = canonical_html
    for ordinal, image_name in enumerate(BODY_IMAGE_NAMES):
        placeholder = body_media_placeholder(ordinal)
        if resolved.count(placeholder) != 1:
            raise ValueError("asset-rich editorial render placeholder set is invalid")
        resolved = resolved.replace(placeholder, f"assets/{image_name}")
    if "__OFFICIAL_ACCOUNT_BODY_MEDIA_" in resolved:
        raise ValueError("asset-rich editorial render retains a media placeholder")
    return resolved


def _load_catalog_sync(manifest_path: Path) -> ApprovedCatalogSelection:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(load_approved_catalog_publications(manifest_path))
    raise RuntimeError("asset-rich exporter must run outside an active event loop")


def export_asset_rich_bundle(
    source_dir: Path,
    catalog_manifest: Path,
    output_dir: Path,
) -> Path:
    """Export a fresh, atomic, local-only v4 bundle without provider work."""

    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("refusing to replace an existing asset-rich editorial directory")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    bundle = load_source_bundle(source_dir)
    article = build_asset_rich_article(bundle)
    selection = _load_catalog_sync(catalog_manifest)
    publication_bodies = tuple(item.body for item in selection.publications)
    publication_checksums = tuple(item.publication_sha256 for item in selection.publications)
    all_bodies = (*bundle.image_bodies, *publication_bodies)
    all_checksums = (*bundle.image_checksums, *publication_checksums)
    if len(all_bodies) != 5 or len(set(all_checksums)) != 5:
        raise ValueError("asset-rich editorial requires five distinct image identities")
    if any(
        sha256(body).hexdigest() != checksum
        for body, checksum in zip(all_bodies, all_checksums, strict=True)
    ):
        raise ValueError("asset-rich editorial image bytes changed before export")

    canonical_html = render_asset_rich_html(article)
    resolved_html = _resolve_html(canonical_html)
    render_fingerprint = fingerprint(
        REPORT_VERSION,
        RENDERER_VERSION,
        STYLE_VERSION,
        TEMPLATE_VERSION,
        canonical_html,
        all_checksums,
        tuple(
            (
                item.public_ref,
                item.catalog_version,
                item.source_master_sha256,
                item.publication_sha256,
                item.section_index,
                item.slot_key,
            )
            for item in selection.publications
        ),
    )

    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        (temporary / "assets").mkdir()
        for name, body, checksum in zip(BODY_IMAGE_NAMES, all_bodies, all_checksums, strict=True):
            if sha256(body).hexdigest() != checksum:
                raise ValueError("asset-rich editorial image changed during export")
            (temporary / "assets" / name).write_bytes(body)
        (temporary / "article-body.html").write_text(resolved_html, encoding="utf-8")
        (temporary / "preview.html").write_text(
            polished_v3._preview_document(resolved_html), encoding="utf-8"
        )
        (temporary / "article.md").write_text(
            polished_v3._article_markdown(article), encoding="utf-8"
        )
        polished_v3._write_json(
            temporary / "article-package.json",
            {"version": ARTICLE_SCHEMA_VERSION, "article": article.model_dump(mode="json")},
        )
        polished_v3._write_json(
            temporary / "evidence.json",
            {
                "version": "official-account-news-editorial-evidence-v4",
                "source_snapshot_version": SOURCE_EVIDENCE_VERSION,
                "fact_brand_boundary": (
                    "external facts use evidence; catalog visuals prove no facts"
                ),
                "sources": list(bundle.evidence_sources),
                "claims": [claim.model_dump(mode="json") for claim in article.claims],
            },
        )
        generated_section_indexes = (0, 2, 4)
        visual_rows: list[dict[str, Any]] = []
        for ordinal, (source_row, checksum, section_index) in enumerate(
            zip(bundle.visual_rows, bundle.image_checksums, generated_section_indexes, strict=True)
        ):
            image = next(
                block
                for block in article.sections[section_index].blocks
                if isinstance(block, ArticleImageBlock)
            )
            visual_rows.append(
                {
                    "ordinal": ordinal,
                    "slot_key": f"body-{ordinal}",
                    "section_index": section_index,
                    "section_heading": article.sections[section_index].heading,
                    "semantic_alt": image.alt_text,
                    "output_sha256": checksum,
                    "source_output_sha256": source_row["output"]["sha256"],
                    "provenance_kind": "inherited_paid_generated_scene",
                    "reused_byte_exact": True,
                    "inherited_ip_visibility_assessment": source_row["ip_visibility_assessment"],
                    "inherited_reference_public_ref": source_row["reference_public_ref"],
                    "current_repackage_provider_calls": 0,
                }
            )
        for ordinal, publication in enumerate(selection.publications, start=3):
            visual_rows.append({"ordinal": ordinal, **_catalog_projection(publication)})
        polished_v3._write_json(
            temporary / "visual-map.json",
            {
                "version": "official-account-news-editorial-visual-map-v4-five-image",
                "quality_status": "passed_inherited_and_approved_local_validation",
                "complete_catalog_fingerprint": selection.complete_catalog_fingerprint,
                "visuals": visual_rows,
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
                    "five block-bound visuals distributed through the article",
                    "three 3:2 generated scenes retain narrative continuity",
                    "two square approved-IP cutaways use contained editorial fields",
                    "each visual has one Article Package slot and one semantic alt",
                ],
                "module_markers": [*_V3_MODULE_MARKERS, "catalog-cutaway", "catalog-cutaway"],
            },
        )
        polished_v3._write_json(
            temporary / "run.json",
            {
                "version": REPORT_VERSION,
                "status": "ready",
                "simulation": True,
                "local_only": True,
                "copy_ready": False,
                "published": False,
                "manual_review_status": "pending",
                "article_body_character_count": article_body_character_count(article),
                "article_section_count": len(article.sections),
                "body_image_count": len(all_bodies),
                "content_fingerprint": article.content_fingerprint,
                "render_fingerprint": render_fingerprint,
                "renderer_version": RENDERER_VERSION,
                "style_version": STYLE_VERSION,
                "template_version": TEMPLATE_VERSION,
                "local_adapter_version": LOCAL_ADAPTER_VERSION,
                "catalog_version": selection.catalog_version,
                "complete_catalog_fingerprint": selection.complete_catalog_fingerprint,
                "source_bundle_version": SOURCE_REPORT_VERSION,
                "source_bundle_content_fingerprint": bundle.source_content_fingerprint,
                "source_bundle_render_fingerprint": bundle.source_render_fingerprint,
                "source_bundle_run_id": bundle.source_run_id,
                "source_bundle_manifest_sha256": bundle.source_manifest_sha256,
                "inherited_historical_paid_image_calls": 3,
                **_ZERO_CALLS,
            },
        )
        (temporary / "README.md").write_text(
            "# 教育部新闻 × 小赛 IP｜五图科学杂志版 v4\n\n"
            "本目录保留三张既有小赛 IP 新闻场景图，并从已批准的本地品牌视觉目录读取两张"
            "发布衍生图，分别绑定家长三问和 AI/孩子责任边界。两张方图采用完整展示，不做 3:2 "
            "裁切。\n\n"
            "- 图片：五张 JPEG 各使用一次；前三张继承图字节不变，后两张由本地 catalog adapter "
            "重验并读取\n"
            "- 事实：仅绑定两条教育部证据；品牌图不作为外部事实证据\n"
            "- 本次重排：新闻、文章模型、Embedding、生图、微信、企微、发布调用均为 0\n"
            "- 状态：ready / local-only / manual review pending / copy-ready false / "
            "unpublished\n\n"
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
                "copy_ready": False,
                "published": False,
                "manual_review_status": "pending",
                "current_repackage_external_calls": 0,
                "inherited_historical_paid_image_calls": 3,
                "catalog_version": selection.catalog_version,
                "complete_catalog_fingerprint": selection.complete_catalog_fingerprint,
                "source_bundle_version": SOURCE_REPORT_VERSION,
                "source_bundle_run_id": bundle.source_run_id,
                "source_bundle_manifest_sha256": bundle.source_manifest_sha256,
                **_ZERO_CALLS,
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
        if output_dir.exists() or output_dir.is_symlink():
            raise FileExistsError("refusing to replace an existing asset-rich editorial directory")
        temporary.rename(output_dir)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--catalog-manifest", type=Path, default=DEFAULT_CATALOG_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    output = export_asset_rich_bundle(args.source_dir, args.catalog_manifest, args.output_dir)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
