"""Explicit opt-in live acquisition for three distinct local weekly articles.

This module fetches only code-registered source pages and their same-host editorial images.  It
never constructs model, image-generation, WeChat, WeCom, upload, draft, publish, or send clients.
The default weekly fixture remains fully offline.
"""

# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional article copy.

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from hashlib import sha256
from pathlib import Path
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from app.application.ports.official_account_local import OfficialAccountMediaResult
from app.application.services.official_account_editor_handoff_v2 import (
    EditorHandoffV2Artifact,
    bind_editor_handoff_v2_mobile_validation,
    build_editor_handoff_v2_artifact,
    write_editor_handoff_v2_artifact,
)
from app.application.services.official_account_weekly_edition import (
    WEEKLY_LIVE_ACQUISITION_AUDIT_VERSION,
    WeeklyEditionArtifact,
    bind_weekly_child,
    build_weekly_edition_artifact,
    finalized_v2_child_from_artifact,
    write_weekly_edition_artifact,
)
from app.core.config import Settings, get_settings
from app.domain.editorial_relevance import (
    ScienceTechContentSignal,
    ScienceTechEditorialCohort,
)
from app.domain.entities import (
    DiscoveredItem,
    ExtractedDocument,
    FetchedResponse,
    SourceImageReference,
    SourceProfile,
    ValidatedSourceImage,
)
from app.domain.enums import SourceTier
from app.domain.official_account_editor_handoff_v2 import (
    EditorHandoffMobileValidation,
    EditorHandoffRelease,
    fingerprint_v2,
)
from app.domain.official_account_local import (
    ArticleBlock,
    ArticleBulletListBlock,
    ArticleImageBlock,
    ArticleNewsContextMediaItem,
    ArticleNewsContextMediaSnapshot,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleQuoteBlock,
    ArticleSection,
    ArticleSourceProjection,
    GeneratedArticleClaim,
    article_package_fingerprint,
)
from app.domain.official_account_weekly_edition import (
    WEEKLY_EDITION_ROLE_ORDER,
    WeeklyArticleRole,
    WeeklyEditionSchedule,
    WeeklyEditionSelection,
    WeeklyGovernedCandidate,
    select_weekly_articles,
)
from app.domain.topic_selection import TopicCandidate, TopicScoringConfig, score_topic_candidate
from app.infrastructure.ingestion.connectors import HtmlConnector
from app.infrastructure.ingestion.fetcher import SafeHttpFetcher
from app.infrastructure.ingestion.source_image_fetcher import SafeSourceImageFetcher
from app.official_account_editor_handoff_v2_demo import _load_browser_report
from app.official_account_weekly_edition_demo import (
    _bind_fixture_media_selection,
    _build_portable_base_artifact,
    _compose_role_cover,
    _fixture_body_visual_lineages,
    _fixture_role_visuals,
    _FixtureRoleVisual,
)

LIVE_INPUT_VERSION = "official-account-weekly-live-input-v1"
LIVE_THEME_CLUSTER_INPUT_VERSION = "official-account-weekly-live-input-v2"
LIVE_SOURCE_REGISTRY_VERSION = "official-account-weekly-live-source-registry-v2"
LIVE_THEME_CLUSTER_AUDIT_VERSION = "official-account-weekly-live-acquisition-audit-v3"
_LIVE_NAMESPACE = UUID("25588aaf-06e5-4873-b0a3-1da1d0f519cb")
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TERMS_REVIEWED_AT = datetime(2026, 8, 31, tzinfo=UTC)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class LiveSourceDefinition:
    key: str
    publisher: str
    organization_type: str
    allowed_hosts: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    content_selectors: tuple[str, ...]
    robots_status: str = "manual_review"

    @property
    def fingerprint(self) -> str:
        return fingerprint_v2(
            LIVE_SOURCE_REGISTRY_VERSION,
            self.key,
            self.publisher,
            self.organization_type,
            self.allowed_hosts,
            self.allowed_path_prefixes,
            self.content_selectors,
            self.robots_status,
            _TERMS_REVIEWED_AT.isoformat(),
        )


_LIVE_SOURCES = {
    "beijing-government-service": LiveSourceDefinition(
        key="beijing-government-service",
        publisher="北京市人民政府门户网站",
        organization_type="government",
        allowed_hosts=("www.beijing.gov.cn",),
        allowed_path_prefixes=("/fuwu/",),
        content_selectors=(".TRS_UEDITOR", ".view", "#mainText", "article", "main"),
    ),
    "xinhua-main": LiveSourceDefinition(
        key="xinhua-main",
        publisher="新华网",
        organization_type="authoritative_media",
        allowed_hosts=("www.news.cn",),
        allowed_path_prefixes=("/20260829/",),
        content_selectors=("#detail", ".main-aticle", ".article", "article", "main"),
    ),
    "xinhua-jiangsu": LiveSourceDefinition(
        key="xinhua-jiangsu",
        publisher="新华网江苏频道",
        organization_type="authoritative_media",
        allowed_hosts=("js.news.cn",),
        allowed_path_prefixes=("/20260825/",),
        content_selectors=("#detail", ".main-aticle", ".article", "article", "main"),
    ),
    "xinhua-tech": LiveSourceDefinition(
        key="xinhua-tech",
        publisher="新华网科技频道",
        organization_type="authoritative_media",
        allowed_hosts=("www.news.cn",),
        allowed_path_prefixes=("/tech/20260804/956dc0450c2f4e8cbf27c7f132a5ee23/",),
        content_selectors=("#detail", ".main-aticle", ".article", "article", "main"),
    ),
    "guangzhou-education-bureau": LiveSourceDefinition(
        key="guangzhou-education-bureau",
        publisher="广州市教育局",
        organization_type="government",
        allowed_hosts=("jyj.gz.gov.cn",),
        allowed_path_prefixes=(
            "/gkmlpt/content/10/10949/",
            "/img/1/1675/",
        ),
        content_selectors=(".content", ".article-content", "section", "article", "main"),
    ),
    "xinhua-education": LiveSourceDefinition(
        key="xinhua-education",
        publisher="新华网教育频道",
        organization_type="authoritative_media",
        allowed_hosts=("www.news.cn",),
        allowed_path_prefixes=("/edu/20260812/253c539cb4f04b2da99dbe9d536d5fc5/",),
        content_selectors=("#detail", ".main-aticle", ".article", "article", "main"),
    ),
}

LiveSourceRelation = Literal["primary", "supporting"]
LiveArticleAngle = Literal["official_policy", "industry_method", "application_practice"]


@dataclass(frozen=True, slots=True)
class LiveArticleInput:
    role: WeeklyArticleRole
    source_key: str
    url: str
    expected_title: str
    expected_published_date: date
    preferred_image_urls: tuple[str, ...]
    relation: LiveSourceRelation = "primary"


@dataclass(frozen=True, slots=True)
class LiveArticleClusterInput:
    role: WeeklyArticleRole
    angle: LiveArticleAngle
    editorial_title: str
    sources: tuple[LiveArticleInput, ...]


@dataclass(frozen=True, slots=True)
class LiveWeeklyInput:
    selection_cutoff: datetime
    articles: tuple[LiveArticleInput, LiveArticleInput, LiveArticleInput]
    version: str = LIVE_INPUT_VERSION
    theme: str | None = None
    clusters: (
        tuple[
            LiveArticleClusterInput,
            LiveArticleClusterInput,
            LiveArticleClusterInput,
        ]
        | None
    ) = None


@dataclass(frozen=True, slots=True)
class AcquiredNewsImage:
    reference: SourceImageReference
    image: ValidatedSourceImage
    source_article_image_id: UUID
    credit: str


@dataclass(frozen=True, slots=True)
class AcquiredNewsArticle:
    input: LiveArticleInput
    source: LiveSourceDefinition
    document: ExtractedDocument
    page_sha256: str
    page_byte_size: int
    page_media_type: str
    page_fetched_at: datetime
    requested_url: str
    final_url: str
    evidence_id: UUID
    evidence_quote: str
    event_id: UUID
    event_version_id: UUID
    images: tuple[AcquiredNewsImage, ...]


@dataclass(frozen=True, slots=True)
class AcquiredArticleCluster:
    input: LiveArticleClusterInput
    sources: tuple[AcquiredNewsArticle, ...]

    @property
    def primary(self) -> AcquiredNewsArticle:
        return self.sources[0]


class PageFetcher(Protocol):
    async def fetch(
        self,
        url: str,
        profile: SourceProfile,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchedResponse: ...


class NewsImageFetcher(Protocol):
    async def fetch(
        self,
        reference: SourceImageReference,
        profile: SourceProfile,
    ) -> ValidatedSourceImage: ...


def load_live_weekly_input(path: Path) -> LiveWeeklyInput:
    payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates)
    if not isinstance(payload, dict):
        raise ValueError("weekly live input must be an object")
    version = payload.get("version")
    if version == LIVE_INPUT_VERSION:
        return _load_live_weekly_input_v1(payload)
    if version == LIVE_THEME_CLUSTER_INPUT_VERSION:
        return _load_live_weekly_input_v2(payload)
    raise ValueError("weekly live input version is unsupported")


def _selection_cutoff(value: object) -> datetime:
    try:
        selection_cutoff = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("weekly live selection cutoff is invalid") from exc
    if selection_cutoff.tzinfo is None:
        raise ValueError("weekly live selection cutoff must be timezone-aware")
    return selection_cutoff.astimezone(_SHANGHAI)


def _load_live_weekly_input_v1(payload: dict[str, object]) -> LiveWeeklyInput:
    if not isinstance(payload, dict) or set(payload) != {
        "version",
        "selection_cutoff",
        "articles",
    }:
        raise ValueError("weekly live input fields changed")
    if payload["version"] != LIVE_INPUT_VERSION:
        raise ValueError("weekly live input version is unsupported")
    selection_cutoff = _selection_cutoff(payload["selection_cutoff"])
    rows = payload["articles"]
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("weekly live input requires exactly three articles")
    articles: list[LiveArticleInput] = []
    expected_fields = {
        "role",
        "source_key",
        "url",
        "expected_title",
        "expected_published_date",
        "preferred_image_urls",
    }
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected_fields:
            raise ValueError("weekly live article input fields changed")
        image_urls = row["preferred_image_urls"]
        if (
            not isinstance(image_urls, list)
            or not 1 <= len(image_urls) <= 2
            or not all(isinstance(value, str) for value in image_urls)
            or len(set(image_urls)) != len(image_urls)
        ):
            raise ValueError("weekly live preferred images must contain one or two unique URLs")
        try:
            expected_date = date.fromisoformat(str(row["expected_published_date"]))
        except ValueError as exc:
            raise ValueError("weekly live expected publication date is invalid") from exc
        articles.append(
            LiveArticleInput(
                role=WeeklyArticleRole(str(row["role"])),
                source_key=str(row["source_key"]),
                url=str(row["url"]),
                expected_title=str(row["expected_title"]),
                expected_published_date=expected_date,
                preferred_image_urls=tuple(image_urls),
            )
        )
    if tuple(item.role.value for item in articles) != WEEKLY_EDITION_ROLE_ORDER:
        raise ValueError("weekly live articles must use canonical role order")
    if (
        len({item.url for item in articles}) != 3
        or len({item.expected_title for item in articles}) != 3
        or len({item.expected_published_date for item in articles}) != 3
    ):
        raise ValueError("weekly live source URLs, titles, and event dates must be distinct")
    sources: list[LiveSourceDefinition] = []
    for item in articles:
        source = _LIVE_SOURCES.get(item.source_key)
        if source is None:
            raise ValueError("weekly live source key is not registered")
        sources.append(source)
        _validate_registered_url(item.url, source)
        for image_url in item.preferred_image_urls:
            _validate_registered_url(image_url, source)
        if (
            item.role is WeeklyArticleRole.OFFICIAL_ANCHOR
            and source.organization_type != "government"
        ):
            raise ValueError("weekly live official role requires registered government authority")
    if len({item.key for item in sources}) != 3 or len({item.publisher for item in sources}) != 3:
        raise ValueError("weekly live source registrations and publishers must be distinct")
    return LiveWeeklyInput(
        selection_cutoff=selection_cutoff,
        articles=(articles[0], articles[1], articles[2]),
    )


def _load_live_weekly_input_v2(payload: dict[str, object]) -> LiveWeeklyInput:
    if set(payload) != {"version", "selection_cutoff", "theme", "articles"}:
        raise ValueError("weekly live theme-cluster input fields changed")
    selection_cutoff = _selection_cutoff(payload["selection_cutoff"])
    theme = str(payload["theme"]).strip()
    if not 4 <= len(theme) <= 120:
        raise ValueError("weekly live theme must contain 4 to 120 characters")
    rows = payload["articles"]
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("weekly live theme input requires exactly three article clusters")
    expected_angles: tuple[LiveArticleAngle, ...] = (
        "official_policy",
        "industry_method",
        "application_practice",
    )
    clusters: list[LiveArticleClusterInput] = []
    flat_sources: list[LiveArticleInput] = []
    for row_ordinal, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {
            "role",
            "angle",
            "editorial_title",
            "sources",
        }:
            raise ValueError("weekly live article-cluster fields changed")
        role = WeeklyArticleRole(str(row["role"]))
        if role.value != WEEKLY_EDITION_ROLE_ORDER[row_ordinal]:
            raise ValueError("weekly live article clusters must use canonical role order")
        angle = str(row["angle"])
        if angle != expected_angles[row_ordinal]:
            raise ValueError("weekly live article-cluster angles changed")
        editorial_title = str(row["editorial_title"]).strip()
        if not 6 <= len(editorial_title) <= 120:
            raise ValueError("weekly live editorial title length changed")
        source_rows = row["sources"]
        # ArticleNewsContextMediaSnapshot is deliberately bounded to two items.  V2 therefore
        # accepts one primary plus one supporting source, one adopted original image each.
        if not isinstance(source_rows, list) or len(source_rows) != 2:
            raise ValueError(
                "weekly live article cluster requires one primary and one supporting source"
            )
        sources: list[LiveArticleInput] = []
        for source_ordinal, source_row in enumerate(source_rows):
            if not isinstance(source_row, dict) or set(source_row) != {
                "relation",
                "source_key",
                "url",
                "expected_title",
                "expected_published_date",
                "preferred_image_urls",
            }:
                raise ValueError("weekly live cluster source fields changed")
            relation = str(source_row["relation"])
            expected_relation = "primary" if source_ordinal == 0 else "supporting"
            if relation != expected_relation:
                raise ValueError("weekly live cluster requires primary then supporting relation")
            image_urls = source_row["preferred_image_urls"]
            if (
                not isinstance(image_urls, list)
                or len(image_urls) != 1
                or not isinstance(image_urls[0], str)
            ):
                raise ValueError("weekly live cluster sources require one preferred image each")
            try:
                expected_date = date.fromisoformat(str(source_row["expected_published_date"]))
            except ValueError as exc:
                raise ValueError("weekly live expected publication date is invalid") from exc
            source_input = LiveArticleInput(
                role=role,
                relation=cast(LiveSourceRelation, relation),
                source_key=str(source_row["source_key"]),
                url=str(source_row["url"]),
                expected_title=str(source_row["expected_title"]),
                expected_published_date=expected_date,
                preferred_image_urls=(image_urls[0],),
            )
            definition = _LIVE_SOURCES.get(source_input.source_key)
            if definition is None:
                raise ValueError("weekly live source key is not registered")
            _validate_registered_url(source_input.url, definition)
            _validate_registered_url(image_urls[0], definition)
            if (
                role is WeeklyArticleRole.OFFICIAL_ANCHOR
                and relation == "primary"
                and definition.organization_type != "government"
            ):
                raise ValueError(
                    "weekly live official primary requires registered government authority"
                )
            sources.append(source_input)
            flat_sources.append(source_input)
        clusters.append(
            LiveArticleClusterInput(
                role=role,
                angle=angle,
                editorial_title=editorial_title,
                sources=tuple(sources),
            )
        )
    identity_groups = (
        [item.url for item in flat_sources],
        [item.expected_title for item in flat_sources],
        [image for item in flat_sources for image in item.preferred_image_urls],
    )
    if any(len(values) != len(set(values)) for values in identity_groups):
        raise ValueError(
            "weekly live cluster URLs, titles, and image URLs must be globally distinct"
        )
    typed_clusters = (clusters[0], clusters[1], clusters[2])
    primaries = tuple(cluster.sources[0] for cluster in typed_clusters)
    return LiveWeeklyInput(
        selection_cutoff=selection_cutoff,
        articles=(primaries[0], primaries[1], primaries[2]),
        version=LIVE_THEME_CLUSTER_INPUT_VERSION,
        theme=theme,
        clusters=typed_clusters,
    )


async def acquire_live_weekly_news(
    live_input: LiveWeeklyInput,
    *,
    page_fetcher: PageFetcher,
    image_fetcher: NewsImageFetcher,
) -> tuple[AcquiredNewsArticle, AcquiredNewsArticle, AcquiredNewsArticle]:
    if live_input.version != LIVE_INPUT_VERSION:
        raise ValueError("single-source acquisition only accepts weekly live input v1")
    acquired: list[AcquiredNewsArticle] = []
    for item in live_input.articles:
        acquired.append(
            await _acquire_live_source(
                item,
                page_fetcher=page_fetcher,
                image_fetcher=image_fetcher,
            )
        )
    _validate_acquired_distinctness(acquired)
    return acquired[0], acquired[1], acquired[2]


async def acquire_live_weekly_theme_clusters(
    live_input: LiveWeeklyInput,
    *,
    page_fetcher: PageFetcher,
    image_fetcher: NewsImageFetcher,
) -> tuple[AcquiredArticleCluster, AcquiredArticleCluster, AcquiredArticleCluster]:
    if live_input.version != LIVE_THEME_CLUSTER_INPUT_VERSION or live_input.clusters is None:
        raise ValueError("theme-cluster acquisition requires weekly live input v2")
    acquired_clusters: list[AcquiredArticleCluster] = []
    all_sources: list[AcquiredNewsArticle] = []
    for cluster in live_input.clusters:
        acquired_sources = tuple(
            [
                await _acquire_live_source(
                    source,
                    page_fetcher=page_fetcher,
                    image_fetcher=image_fetcher,
                )
                for source in cluster.sources
            ]
        )
        acquired_clusters.append(AcquiredArticleCluster(input=cluster, sources=acquired_sources))
        all_sources.extend(acquired_sources)
    _validate_acquired_cluster_distinctness(acquired_clusters, all_sources)
    return acquired_clusters[0], acquired_clusters[1], acquired_clusters[2]


async def _acquire_live_source(
    item: LiveArticleInput,
    *,
    page_fetcher: PageFetcher,
    image_fetcher: NewsImageFetcher,
) -> AcquiredNewsArticle:
    source = _LIVE_SOURCES[item.source_key]
    profile = _source_profile(source, item.url)
    response = await page_fetcher.fetch(item.url, profile)
    page_body = response.body
    if response.media_type != "text/html" or not page_body:
        raise ValueError("weekly live source page must be non-empty HTML")
    if response.final_url != item.url:
        raise ValueError("weekly live source page redirected away from the approved URL")
    _verify_date_literal(page_body, item.expected_published_date)
    discovered = DiscoveredItem(
        source_item_id=urlsplit(item.url).path.rstrip("/").rsplit("/", 1)[-1],
        url=item.url,
        title=item.expected_title,
        published_at=datetime.combine(
            item.expected_published_date,
            time(hour=12),
            tzinfo=_SHANGHAI,
        ),
    )
    connector = HtmlConnector(
        _exact_url_filter(item.url),
        source.content_selectors,
        prefer_detail_published_at=True,
    )
    document = connector.extract(response, discovered, profile)
    if _normalized(document.title) != _normalized(item.expected_title):
        raise ValueError("weekly live extracted title does not match the approved input")
    if document.canonical_url != item.url:
        raise ValueError("weekly live canonical source URL changed")
    if document.published_at is None or (
        document.published_at.astimezone(_SHANGHAI).date() != item.expected_published_date
    ):
        raise ValueError("weekly live extracted publication date changed")
    if len(_normalized(document.clean_text)) < 300:
        raise ValueError("weekly live extracted source text is too short")
    references = {reference.image_url: reference for reference in document.source_images}
    selected_references: list[SourceImageReference] = []
    for image_url in item.preferred_image_urls:
        reference = references.get(image_url)
        if reference is None:
            raise ValueError("weekly live preferred image was not discovered in the source page")
        selected_references.append(reference)
    event_id = uuid5(NAMESPACE_URL, f"official-account-weekly-event:{document.canonical_url}")
    event_version_id = uuid5(event_id, response.sha256)
    images: list[AcquiredNewsImage] = []
    for reference in selected_references:
        image = await image_fetcher.fetch(reference, profile)
        if image.response.final_url != reference.image_url:
            raise ValueError("weekly live source image redirected away from its approved URL")
        images.append(
            AcquiredNewsImage(
                reference=reference,
                image=image,
                source_article_image_id=uuid5(event_version_id, reference.image_url),
                credit=(
                    reference.credit
                    or f"{source.publisher}｜来源页原图；原图标记保留；转载授权未核验"
                ),
            )
        )
    evidence_quote = _bounded_evidence_quote(
        document.clean_text,
        excluded_lines=(document.title,),
    )
    return AcquiredNewsArticle(
        input=item,
        source=source,
        document=document,
        page_sha256=response.sha256,
        page_byte_size=len(page_body),
        page_media_type=response.media_type,
        page_fetched_at=response.fetched_at,
        requested_url=item.url,
        final_url=response.final_url,
        evidence_id=uuid5(event_version_id, "evidence:source-page:0"),
        evidence_quote=evidence_quote,
        event_id=event_id,
        event_version_id=event_version_id,
        images=tuple(images),
    )


async def build_live_weekly_edition_artifact(
    live_input: LiveWeeklyInput,
    *,
    page_fetcher: PageFetcher,
    image_fetcher: NewsImageFetcher,
    mobile_validation_factory: Callable[[EditorHandoffV2Artifact], EditorHandoffMobileValidation],
) -> WeeklyEditionArtifact:
    if live_input.version == LIVE_THEME_CLUSTER_INPUT_VERSION:
        return await _build_live_theme_cluster_artifact(
            live_input,
            page_fetcher=page_fetcher,
            image_fetcher=image_fetcher,
            mobile_validation_factory=mobile_validation_factory,
        )
    acquired = await acquire_live_weekly_news(
        live_input,
        page_fetcher=page_fetcher,
        image_fetcher=image_fetcher,
    )
    selection = _live_selection(live_input, acquired)
    staged = await _build_live_children(acquired)
    reports = {
        role: mobile_validation_factory(artifact)
        for role, artifact in zip(WeeklyArticleRole, staged, strict=True)
    }
    finalized = await _build_live_children(acquired, browser_validations=reports)
    children = tuple(
        finalized_v2_child_from_artifact(artifact, role=role)
        for role, artifact in zip(WeeklyArticleRole, finalized, strict=True)
    )
    bindings = tuple(
        bind_weekly_child(selected=selected, child=child)
        for selected, child in zip(selection.selected, children, strict=True)
    )
    return build_weekly_edition_artifact(
        selection=selection,
        schedule=WeeklyEditionSchedule(),
        children=(children[0], children[1], children[2]),
        bindings=(bindings[0], bindings[1], bindings[2]),
        live_acquisition_audit=_live_acquisition_audit(live_input, acquired),
    )


async def _build_live_theme_cluster_artifact(
    live_input: LiveWeeklyInput,
    *,
    page_fetcher: PageFetcher,
    image_fetcher: NewsImageFetcher,
    mobile_validation_factory: Callable[[EditorHandoffV2Artifact], EditorHandoffMobileValidation],
) -> WeeklyEditionArtifact:
    acquired_clusters = await acquire_live_weekly_theme_clusters(
        live_input,
        page_fetcher=page_fetcher,
        image_fetcher=image_fetcher,
    )
    primaries = tuple(cluster.primary for cluster in acquired_clusters)
    selection = _live_selection(
        live_input,
        (primaries[0], primaries[1], primaries[2]),
    )
    staged = await _build_live_theme_cluster_children(live_input, acquired_clusters)
    reports = {
        role: mobile_validation_factory(artifact)
        for role, artifact in zip(WeeklyArticleRole, staged, strict=True)
    }
    finalized = await _build_live_theme_cluster_children(
        live_input,
        acquired_clusters,
        browser_validations=reports,
    )
    children = tuple(
        finalized_v2_child_from_artifact(artifact, role=role)
        for role, artifact in zip(WeeklyArticleRole, finalized, strict=True)
    )
    bindings = tuple(
        bind_weekly_child(selected=selected, child=child)
        for selected, child in zip(selection.selected, children, strict=True)
    )
    return build_weekly_edition_artifact(
        selection=selection,
        schedule=WeeklyEditionSchedule(),
        children=(children[0], children[1], children[2]),
        bindings=(bindings[0], bindings[1], bindings[2]),
        live_acquisition_audit=_live_theme_cluster_audit(live_input, acquired_clusters),
    )


async def _build_live_children(
    acquired: tuple[AcquiredNewsArticle, AcquiredNewsArticle, AcquiredNewsArticle],
    *,
    browser_validations: dict[WeeklyArticleRole, EditorHandoffMobileValidation] | None = None,
) -> tuple[EditorHandoffV2Artifact, EditorHandoffV2Artifact, EditorHandoffV2Artifact]:
    base = await _build_portable_base_artifact()
    base_article = ArticlePackage.model_validate_json(base.files["article.json"])
    artifacts: list[EditorHandoffV2Artifact] = []
    for record in acquired:
        role = record.input.role
        visuals = tuple(
            replace(
                visual,
                scene_brief=(
                    f"小赛和赛先生围绕《{record.document.title[:48]}》对应正文块进行来源核对、"
                    f"场景观察与家庭科创讨论（场景 {visual.ordinal + 1}）。"
                ),
            )
            for visual in _fixture_role_visuals(role)
        )
        typed_visuals = (visuals[0], visuals[1], visuals[2])
        claims = _live_claims(record)
        article = base_article.model_copy(
            update={
                "title": record.document.title[:120],
                "digest": _live_digest(record),
                "lead": _live_lead(record),
                "sections": _live_sections(
                    article=base_article,
                    record=record,
                    scene_briefs=(
                        typed_visuals[0].scene_brief,
                        typed_visuals[1].scene_brief,
                        typed_visuals[2].scene_brief,
                    ),
                ),
                "conclusion": _live_conclusion(record),
                "claims": claims,
                "sources": (
                    ArticleSourceProjection(
                        evidence_id=record.evidence_id,
                        source_name=f"{record.source.publisher}｜{record.document.title}"[:200],
                        source_url=record.document.canonical_url,
                        source_tier=(
                            "official"
                            if record.source.organization_type == "government"
                            else "authoritative_media"
                        ),
                    ),
                ),
                "topic_title": record.document.title[:300],
                "news_context_media": _live_context_snapshot(record),
            }
        )
        article = _bind_fixture_media_selection(article=article, visuals=typed_visuals)
        article = article.model_copy(
            update={"content_fingerprint": article_package_fingerprint(article)}
        )
        run_id = uuid5(_LIVE_NAMESPACE, f"run:{record.event_version_id}")
        media = _live_media_rows(base=base, record=record, visuals=typed_visuals)
        body_visuals = _fixture_body_visual_lineages(
            base=base,
            article=article,
            role=role,
            visuals=typed_visuals,
        )
        release = EditorHandoffRelease(
            policy="quality_auto",
            kind="machine",
            input_fingerprint=fingerprint_v2(
                "weekly-live-release-v1",
                role.value,
                article.content_fingerprint,
                record.page_sha256,
            ),
            gate_codes=base.release.gate_codes,
        )
        artifact = build_editor_handoff_v2_artifact(
            run_id=run_id,
            run_request_fingerprint=fingerprint_v2(
                "weekly-live-run-v1",
                role.value,
                str(record.event_id),
                str(record.event_version_id),
                record.page_sha256,
            ),
            article=article,
            release=release,
            review=None,
            draft_resolved_fingerprint=fingerprint_v2(
                "weekly-live-draft-v1",
                role.value,
                article.content_fingerprint,
            ),
            media=media,
            body_visuals=body_visuals,
            eligibility_checks=(),
        )
        if browser_validations is not None:
            artifact = bind_editor_handoff_v2_mobile_validation(
                artifact,
                browser_validations[role],
            )
        artifacts.append(artifact)
    return artifacts[0], artifacts[1], artifacts[2]


async def _build_live_theme_cluster_children(
    live_input: LiveWeeklyInput,
    acquired: tuple[AcquiredArticleCluster, AcquiredArticleCluster, AcquiredArticleCluster],
    *,
    browser_validations: dict[WeeklyArticleRole, EditorHandoffMobileValidation] | None = None,
) -> tuple[EditorHandoffV2Artifact, EditorHandoffV2Artifact, EditorHandoffV2Artifact]:
    if live_input.theme is None:
        raise ValueError("weekly live theme-cluster build requires an explicit theme")
    base = await _build_portable_base_artifact()
    base_article = ArticlePackage.model_validate_json(base.files["article.json"])
    artifacts: list[EditorHandoffV2Artifact] = []
    for cluster in acquired:
        role = cluster.input.role
        angle_label = _theme_cluster_angle_label(cluster.input.angle)
        visuals = tuple(
            replace(
                visual,
                scene_brief=(
                    f"小赛和赛先生围绕周主题《{live_input.theme[:42]}》和{angle_label}角度，"
                    f"对《{cluster.input.editorial_title[:42]}》正文块进行来源核对与实践讨论"
                    f"（场景 {visual.ordinal + 1}）。"
                ),
            )
            for visual in _fixture_role_visuals(role)
        )
        typed_visuals = (visuals[0], visuals[1], visuals[2])
        article = base_article.model_copy(
            update={
                "title": cluster.input.editorial_title,
                "digest": _theme_cluster_digest(live_input.theme, cluster),
                "lead": _theme_cluster_lead(live_input.theme, cluster),
                "sections": _live_theme_cluster_sections(
                    article=base_article,
                    theme=live_input.theme,
                    cluster=cluster,
                    scene_briefs=(
                        typed_visuals[0].scene_brief,
                        typed_visuals[1].scene_brief,
                        typed_visuals[2].scene_brief,
                    ),
                ),
                "conclusion": _theme_cluster_conclusion(live_input.theme, cluster),
                "claims": _live_theme_cluster_claims(cluster),
                "sources": tuple(
                    ArticleSourceProjection(
                        evidence_id=source.evidence_id,
                        source_name=(
                            f"{'主来源' if source.input.relation == 'primary' else '补充来源'}｜"
                            f"{source.source.publisher}｜{source.document.title}"
                        )[:200],
                        source_url=source.document.canonical_url,
                        source_tier=(
                            "official"
                            if source.source.organization_type == "government"
                            else "authoritative_media"
                        ),
                    )
                    for source in cluster.sources
                ),
                "topic_title": f"{live_input.theme}｜{cluster.input.editorial_title}"[:300],
                "news_context_media": _live_theme_context_snapshot(cluster),
            }
        )
        article = _bind_fixture_media_selection(article=article, visuals=typed_visuals)
        article = article.model_copy(
            update={"content_fingerprint": article_package_fingerprint(article)}
        )
        cluster_fingerprint = fingerprint_v2(
            LIVE_THEME_CLUSTER_INPUT_VERSION,
            live_input.theme,
            role.value,
            cluster.input.angle,
            tuple(str(source.event_version_id) for source in cluster.sources),
        )
        run_id = uuid5(_LIVE_NAMESPACE, f"theme-cluster-run:{cluster_fingerprint}")
        media = _live_theme_media_rows(base=base, cluster=cluster, visuals=typed_visuals)
        body_visuals = _fixture_body_visual_lineages(
            base=base,
            article=article,
            role=role,
            visuals=typed_visuals,
        )
        release = EditorHandoffRelease(
            policy="quality_auto",
            kind="machine",
            input_fingerprint=fingerprint_v2(
                "weekly-live-theme-cluster-release-v1",
                role.value,
                article.content_fingerprint,
                cluster_fingerprint,
            ),
            gate_codes=base.release.gate_codes,
        )
        artifact = build_editor_handoff_v2_artifact(
            run_id=run_id,
            run_request_fingerprint=fingerprint_v2(
                "weekly-live-theme-cluster-run-v1",
                role.value,
                cluster_fingerprint,
            ),
            article=article,
            release=release,
            review=None,
            draft_resolved_fingerprint=fingerprint_v2(
                "weekly-live-theme-cluster-draft-v1",
                role.value,
                article.content_fingerprint,
            ),
            media=media,
            body_visuals=body_visuals,
            eligibility_checks=(),
        )
        if browser_validations is not None:
            artifact = bind_editor_handoff_v2_mobile_validation(
                artifact,
                browser_validations[role],
            )
        artifacts.append(artifact)
    return artifacts[0], artifacts[1], artifacts[2]


def _live_theme_cluster_sections(
    *,
    article: ArticlePackage,
    theme: str,
    cluster: AcquiredArticleCluster,
    scene_briefs: tuple[str, str, str],
) -> tuple[ArticleSection, ...]:
    headings = {
        "official_policy": ("政策信号", "落地条件", "家庭如何理解", "继续核对"),
        "industry_method": ("产业与教学的交点", "方法比工具更重要", "能力边界", "观察指标"),
        "application_practice": (
            "真实实践发生了什么",
            "拆解学习动作",
            "保留学生判断",
            "复盘与迁移",
        ),
    }[cluster.input.angle]
    replacements = iter(_theme_cluster_section_text(theme, cluster))
    image_ordinal = 0
    sections: list[ArticleSection] = []
    for section_index, base_section in enumerate(article.sections):
        blocks: list[ArticleBlock] = []
        for block in base_section.blocks:
            if isinstance(block, ArticleImageBlock):
                blocks.append(block.model_copy(update={"alt_text": scene_briefs[image_ordinal]}))
                image_ordinal += 1
                continue
            text_value, claim_refs = next(replacements)
            if isinstance(block, ArticleParagraphBlock | ArticleQuoteBlock):
                blocks.append(
                    block.model_copy(update={"text": text_value, "claim_refs": claim_refs})
                )
            elif isinstance(block, ArticleBulletListBlock):
                blocks.append(
                    block.model_copy(
                        update={
                            "items": tuple(
                                f"{text_value}（核对项 {ordinal}）"
                                for ordinal in range(1, min(4, len(block.items)) + 1)
                            ),
                            "claim_refs": claim_refs,
                        }
                    )
                )
            else:  # pragma: no cover
                raise TypeError("unsupported weekly live theme article block")
        sections.append(
            base_section.model_copy(
                update={"heading": headings[section_index], "blocks": tuple(blocks)}
            )
        )
    if next(replacements, None) is not None or image_ordinal != 3:
        raise ValueError("weekly live theme article structural shell changed")
    return tuple(sections)


def _theme_cluster_section_text(
    theme: str,
    cluster: AcquiredArticleCluster,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    primary, supporting = cluster.sources
    primary_excerpts = _source_excerpts(primary.evidence_quote)
    supporting_excerpts = _source_excerpts(
        supporting.evidence_quote,
        prioritized_terms=("设计跨学科课程", "教学智能体")
        if supporting.source.key == "xinhua-tech"
        else (),
    )
    primary_fact = "live-source-fact-0"
    supporting_fact = "live-source-fact-1"
    source_note = (
        f"主来源是{primary.source.publisher}《{primary.document.title}》，补充来源是"
        f"{supporting.source.publisher}《{supporting.document.title}》。两条事实分别保留自己的链接、"
        "证据编号和原图，不互相代替。"
    )
    source_method = (
        f"围绕“{theme}”，小赛先标明谁发布、何时发布、原文说了什么，再比较两条来源共同指向的"
        "变化。相同结论也必须分别找到证据，不能用编辑主题代替外部事实。"
    )
    comparison_method = (
        "把两条来源并排阅读时，只把各自明示的事实放进对照表；共同趋势属于编辑观察，"
        "需要与原文陈述分开表达。"
    )
    supporting_context = comparison_method
    if supporting.source.key == "xinhua-education":
        supporting_context = (
            "这条成果征集通知只用于说明案例后续如何征集、评估与复用；它不能证明主来源中的培训"
            "已经形成成功、可复制的应用成果。"
        )
    followup_source_note = (
        "后续更新仍按主来源与补充来源分别记录，新增判断必须回到产生它的原文和证据编号。"
    )
    transfer_method = (
        "最后把政策信号、课堂方法与实践动作分层记录：已发生的回查来源，可尝试的写成假设，"
        "仍未知的留给下一次观察。"
    )
    action = (
        "把新闻转成学习问题时，可以让孩子先观察一个现象、提出一种解释、设计一次可重复的小实验，"
        "最后写下结果和仍未确认的部分。"
    )
    boundary = (
        "来源页原图只帮助理解现场，既不是事实证据，也不代表取得转载授权；已有标记和署名保持不变。"
    )
    rows = (
        (
            f"{primary.source.publisher}于{primary.input.expected_published_date.isoformat()}发布的主来源写道："
            f"{primary_excerpts[0]}",
            (primary_fact,),
        ),
        (f"主来源还写到：{primary_excerpts[1]}", (primary_fact,)),
        (source_note, ("source-boundary",)),
        (source_method, ("analysis-method",)),
        ("先分别核对两条新闻，再讨论它们如何组成同一主题。", ("source-boundary",)),
        (
            f"{supporting.source.publisher}的补充来源提供另一组可核对信息："
            f"{supporting_excerpts[0]}",
            (supporting_fact,),
        ),
        (f"补充来源还写到：{supporting_excerpts[1]}", (supporting_fact,)),
        (supporting_context, ("analysis-method",)),
        (boundary, ("source-boundary",)),
        (f"回到主来源继续核对：{primary_excerpts[2]}", (primary_fact,)),
        (action, ("family-action",)),
        (f"补充来源的另一条信息是：{supporting_excerpts[2]}", (supporting_fact,)),
        (transfer_method, ("analysis-method",)),
        ("工具可以辅助整理，但观察、选择和解释仍由学习者完成。", ("family-action",)),
        (f"主来源的后续观察点：{primary_excerpts[3]}", (primary_fact,)),
        (f"补充来源的后续观察点：{supporting_excerpts[3]}", (supporting_fact,)),
        (followup_source_note, ("source-boundary",)),
        ("新闻会更新；保留来源、日期和差异，才能在新证据出现时修正判断。", ("analysis-method",)),
    )
    return rows


def _live_theme_cluster_claims(
    cluster: AcquiredArticleCluster,
) -> tuple[GeneratedArticleClaim, ...]:
    source_claims = tuple(
        GeneratedArticleClaim(
            id=f"live-source-fact-{ordinal}",
            text=_complete_prefix(source.evidence_quote, maximum=600),
            kind="external_fact",
            evidence_ids=(source.evidence_id,),
        )
        for ordinal, source in enumerate(cluster.sources)
    )
    return (
        *source_claims,
        GeneratedArticleClaim(
            id="source-boundary",
            text="每条事实和新闻原图保持来源隔离，新闻原图仅作上下文。",
            kind="opinion",
        ),
        GeneratedArticleClaim(
            id="analysis-method",
            text="多来源共同支撑主题，但每条事实仍须回到自己的原文核对。",
            kind="opinion",
        ),
        GeneratedArticleClaim(
            id="family-action",
            text="家庭可以把主题转成可观察、可验证、可复盘的小问题。",
            kind="opinion",
        ),
    )


def _live_theme_context_snapshot(
    cluster: AcquiredArticleCluster,
) -> ArticleNewsContextMediaSnapshot:
    items: list[ArticleNewsContextMediaItem] = []
    for ordinal, source in enumerate(cluster.sources):
        image = source.images[0]
        relation = "主来源" if source.input.relation == "primary" else "补充来源"
        items.append(
            ArticleNewsContextMediaItem(
                ordinal=ordinal,
                section_index=ordinal,
                source_article_image_id=image.source_article_image_id,
                sha256=image.image.response.sha256,
                media_type=cast(
                    Literal["image/jpeg", "image/png", "image/webp"],
                    image.image.response.media_type,
                ),
                width=image.image.width,
                height=image.image.height,
                alt_text=f"{relation}《{source.document.title}》新闻原图"[:200],
                caption=(
                    image.reference.caption
                    or (
                        f"{relation}《{source.document.title}》来源页原图；"
                        "仅作上下文，不构成事实证据。"
                    )
                )[:300],
                credit=image.credit[:200],
                source_page_url=source.document.canonical_url,
                rights_status="publish_permission_unverified",
                context_only_not_evidence=True,
            )
        )
    return ArticleNewsContextMediaSnapshot(
        selection_version="official-account-news-context-selection-v1",
        status="ready",
        items=tuple(items),
    )


def _theme_cluster_digest(theme: str, cluster: AcquiredArticleCluster) -> str:
    primary, supporting = cluster.sources
    return (
        f"本周主题“{theme}”的{_theme_cluster_angle_label(cluster.input.angle)}角度，"
        f"使用{primary.source.publisher}主来源和"
        f"{supporting.source.publisher}补充来源交叉观察；事实、证据与原图逐来源绑定。"
    )[:240]


def _theme_cluster_lead(theme: str, cluster: AcquiredArticleCluster) -> str:
    return (
        f"一个主题不等于一条新闻。本篇从“{theme}”的"
        f"{_theme_cluster_angle_label(cluster.input.angle)}角度出发，分别核对"
        f"《{cluster.sources[0].document.title}》与《{cluster.sources[1].document.title}》。"
        "两条新闻各自保留证据和原图边界，再共同回答同一个教育问题。"
    )


def _theme_cluster_conclusion(theme: str, cluster: AcquiredArticleCluster) -> str:
    return (
        f"围绕“{theme}”，这篇文章没有把两条新闻揉成一个未经区分的结论。"
        f"{cluster.sources[0].source.publisher}与{cluster.sources[1].source.publisher}的事实仍可逐条"
        "回查；行动建议则需要在真实学习场景中继续验证和复盘。"
    )


def _theme_cluster_angle_label(angle: LiveArticleAngle) -> str:
    return {
        "official_policy": "官方政策",
        "industry_method": "行业方法",
        "application_practice": "应用实践",
    }[angle]


def _live_theme_media_rows(
    *,
    base: EditorHandoffV2Artifact,
    cluster: AcquiredArticleCluster,
    visuals: tuple[_FixtureRoleVisual, _FixtureRoleVisual, _FixtureRoleVisual],
) -> tuple[tuple[OfficialAccountMediaResult, bytes], ...]:
    primary = cluster.primary
    rows = list(_live_media_rows(base=base, record=primary, visuals=visuals))
    # Drop the single-source context and cover; keep the three role-specific IP body visuals.
    rows = [row for row in rows if row[0].role == "body"]
    for ordinal, source in enumerate(cluster.sources):
        item = source.images[0]
        body = item.image.response.body
        relation = "主来源" if source.input.relation == "primary" else "补充来源"
        rows.append(
            (
                OfficialAccountMediaResult(
                    local_media_id=f"weekly-live-{cluster.input.role.value}-context-{ordinal}",
                    role="context",
                    ordinal=ordinal,
                    media_url=f"/local/weekly-live-{cluster.input.role.value}-context-{ordinal}",
                    media_type=cast(str, item.image.response.media_type),
                    byte_size=len(body),
                    sha256=item.image.response.sha256,
                    semantic_label=f"{relation}《{source.document.title}》新闻原图"[:200],
                    assigned_section_index=ordinal,
                    alt_text=f"{relation}《{source.document.title}》新闻原图"[:200],
                    provenance_kind="live_same_source_news_image",
                    source_page_url=source.document.canonical_url,
                    caption=(
                        item.reference.caption
                        or (
                            f"{relation}《{source.document.title}》来源页原图；"
                            "仅作上下文，不构成事实证据。"
                        )
                    )[:300],
                    credit=item.credit[:200],
                    rights_status="publish_permission_unverified",
                    context_only_not_evidence=True,
                ),
                body,
            )
        )
    cover = _compose_role_cover(cluster.input.role)
    rows.append(
        (
            OfficialAccountMediaResult(
                local_media_id=f"weekly-live-{cluster.input.role.value}-cover-0",
                role="cover",
                ordinal=0,
                media_url=f"/local/weekly-live-{cluster.input.role.value}-cover-0",
                media_type="image/jpeg",
                byte_size=len(cover),
                sha256=sha256(cover).hexdigest(),
                semantic_label=f"{cluster.input.editorial_title}小赛 AI 宽封面"[:200],
                provenance_kind="deterministic_local_ip_composition",
            ),
            cover,
        )
    )
    return tuple(rows)


def _live_sections(
    *,
    article: ArticlePackage,
    record: AcquiredNewsArticle,
    scene_briefs: tuple[str, str, str],
) -> tuple[ArticleSection, ...]:
    role_labels = {
        WeeklyArticleRole.OFFICIAL_ANCHOR: (
            "先核对官方原文",
            "拆开事实与解释",
            "转成家庭问题",
            "保留复盘记录",
        ),
        WeeklyArticleRole.INDUSTRY_TREND: (
            "这条产业新闻说了什么",
            "从产品热度回到真实能力",
            "观察场景与边界",
            "继续追踪哪些信号",
        ),
        WeeklyArticleRole.APPLICATION_CASE: (
            "这个落地案例发生了什么",
            "把体验拆成学习动作",
            "让孩子保留判断权",
            "把一次体验变成方法",
        ),
    }[record.input.role]
    excerpts = _source_excerpts(record.evidence_quote)
    section_text = _role_section_text(record, excerpts)
    image_ordinal = 0
    sections: list[ArticleSection] = []
    for section_index, base_section in enumerate(article.sections):
        replacement = iter(section_text[section_index])
        blocks: list[ArticleBlock] = []
        for block in base_section.blocks:
            if isinstance(block, ArticleImageBlock):
                blocks.append(block.model_copy(update={"alt_text": scene_briefs[image_ordinal]}))
                image_ordinal += 1
            elif isinstance(block, ArticleParagraphBlock):
                text_value, claim_refs = next(replacement)
                blocks.append(
                    block.model_copy(update={"text": text_value, "claim_refs": claim_refs})
                )
            elif isinstance(block, ArticleQuoteBlock):
                text_value, claim_refs = next(replacement)
                blocks.append(
                    block.model_copy(update={"text": text_value, "claim_refs": claim_refs})
                )
            elif isinstance(block, ArticleBulletListBlock):
                text_value, claim_refs = next(replacement)
                blocks.append(
                    block.model_copy(
                        update={
                            "items": tuple(
                                f"{text_value}（核对项 {ordinal}）"
                                for ordinal in range(1, min(4, len(block.items)) + 1)
                            ),
                            "claim_refs": claim_refs,
                        }
                    )
                )
            else:  # pragma: no cover - ArticleBlock is exhaustively discriminated.
                raise TypeError("unsupported weekly live article block")
        if next(replacement, None) is not None:
            raise ValueError("weekly live section copy has unused text")
        sections.append(
            base_section.model_copy(
                update={"heading": role_labels[section_index], "blocks": tuple(blocks)}
            )
        )
    if image_ordinal != 3:
        raise ValueError("weekly live article visual anchors changed")
    return tuple(sections)


def _role_section_text(
    record: AcquiredNewsArticle,
    excerpts: tuple[str, str, str, str],
) -> tuple[tuple[tuple[str, tuple[str, ...]], ...], ...]:
    title = record.document.title
    publisher = record.source.publisher
    published = record.input.expected_published_date.isoformat()
    opening = f"{publisher}于{published}发布《{title}》。原文中的一段可核对信息是：{excerpts[0]}"
    source_boundary = (
        f"这篇文章只把来源页中能够直接核对的文字当作外部事实。新闻图片帮助理解现场，但不替代"
        f"{publisher}的原文，也不自动取得转载授权。"
    )
    analysis = (
        "小赛的阅读方法是先写下发布者、日期和原始链接，再区分事实、判断与行动建议。这样做能让"
        "读者看见每一步解释增加了什么，而不是把编辑观点混进新闻原句。"
    )
    home = (
        "面向家庭时，不急着把新闻变成新的任务清单。可以先问孩子：你看见了什么变化，哪一句话"
        "能够支持判断，还有什么信息需要继续查证。"
    )
    follow = (
        "值得继续追踪的不是一次活动是否热闹，而是同类实践能否重复、参与者是否真正拥有选择权，"
        "以及结果能否用公开资料和后续记录复核。"
    )
    return (
        (
            (opening, ("live-fact",)),
            (f"原文还写到：{excerpts[1]}", ("live-fact",)),
            (source_boundary, ("source-boundary",)),
            (analysis, ("analysis-method",)),
            ("先确认新闻原文，再讨论它对科创教育意味着什么。", ("source-boundary",)),
        ),
        (
            (f"继续阅读可看到：{excerpts[2]}", ("live-fact",)),
            (analysis, ("analysis-method",)),
            (source_boundary, ("source-boundary",)),
            ("事实可以引用，判断需要说明推导，建议还要经过真实场景验证。", ("analysis-method",)),
        ),
        (
            (f"来源页中的另一个信息片段是：{excerpts[3]}", ("live-fact",)),
            (home, ("family-action",)),
            (analysis, ("analysis-method",)),
            (follow, ("family-action",)),
            ("让工具协助整理，让孩子保留观察、选择和解释。", ("family-action",)),
        ),
        (
            (home, ("family-action",)),
            (follow, ("family-action",)),
            (source_boundary, ("source-boundary",)),
            (
                "新闻会更新，可靠的方法是保留来源、记录变化，并允许根据新证据修正判断。",
                ("analysis-method",),
            ),
        ),
    )


def _live_claims(record: AcquiredNewsArticle) -> tuple[GeneratedArticleClaim, ...]:
    return (
        GeneratedArticleClaim(
            id="live-fact",
            text=_complete_prefix(record.evidence_quote, maximum=600),
            kind="external_fact",
            evidence_ids=(record.evidence_id,),
        ),
        GeneratedArticleClaim(
            id="source-boundary",
            text="新闻原图仅作上下文，事实仍须回到来源页原文核对。",
            kind="opinion",
        ),
        GeneratedArticleClaim(
            id="analysis-method",
            text="区分事实、判断与行动建议，能够减少传播中的无依据扩写。",
            kind="opinion",
        ),
        GeneratedArticleClaim(
            id="family-action",
            text="家庭可以把新闻转成一个可观察、可验证、可复盘的小问题。",
            kind="opinion",
        ),
    )


def _live_context_snapshot(record: AcquiredNewsArticle) -> ArticleNewsContextMediaSnapshot:
    items = tuple(
        ArticleNewsContextMediaItem(
            ordinal=ordinal,
            section_index=ordinal,
            source_article_image_id=item.source_article_image_id,
            sha256=item.image.response.sha256,
            media_type=cast(
                Literal["image/jpeg", "image/png", "image/webp"],
                item.image.response.media_type,
            ),
            width=item.image.width,
            height=item.image.height,
            alt_text=f"{record.document.title}来源页新闻原图 {ordinal + 1}"[:200],
            caption=(
                item.reference.caption
                or f"{record.document.title}来源页原图；仅作新闻上下文，不构成事实证据。"
            )[:300],
            credit=item.credit[:200],
            source_page_url=record.document.canonical_url,
            rights_status="publish_permission_unverified",
            context_only_not_evidence=True,
        )
        for ordinal, item in enumerate(record.images)
    )
    return ArticleNewsContextMediaSnapshot(
        selection_version="official-account-news-context-selection-v1",
        status="partial" if len(items) == 1 else "ready",
        items=items,
    )


def _live_media_rows(
    *,
    base: EditorHandoffV2Artifact,
    record: AcquiredNewsArticle,
    visuals: tuple[_FixtureRoleVisual, _FixtureRoleVisual, _FixtureRoleVisual],
) -> tuple[tuple[OfficialAccountMediaResult, bytes], ...]:
    rows: list[tuple[OfficialAccountMediaResult, bytes]] = []
    for visual, lineage in zip(visuals, base.body_visuals, strict=True):
        visual_body = visual.body
        visual_sha = visual.body_sha256
        scene_brief = visual.scene_brief
        ordinal = visual.ordinal
        rows.append(
            (
                OfficialAccountMediaResult(
                    local_media_id=f"weekly-live-{record.input.role.value}-body-{ordinal}",
                    role="body",
                    ordinal=ordinal,
                    media_url=f"/local/weekly-live-{record.input.role.value}-body-{ordinal}",
                    media_type="image/jpeg",
                    byte_size=len(visual_body),
                    sha256=visual_sha,
                    semantic_label=scene_brief,
                    assigned_section_index=lineage.section_index,
                    selection_reason_code="approved_local_ip_exact_block_live_projection",
                    selection_method="deterministic_tag",
                    alt_text=scene_brief,
                    provenance_kind="deterministic_local_ip_composition",
                    caption="按当前新闻正文块绑定的小赛与赛先生本地场景图；未调用生图服务。",
                ),
                visual_body,
            )
        )
    for ordinal, item in enumerate(record.images):
        body = item.image.response.body
        rows.append(
            (
                OfficialAccountMediaResult(
                    local_media_id=f"weekly-live-{record.input.role.value}-context-{ordinal}",
                    role="context",
                    ordinal=ordinal,
                    media_url=f"/local/weekly-live-{record.input.role.value}-context-{ordinal}",
                    media_type=cast(str, item.image.response.media_type),
                    byte_size=len(body),
                    sha256=item.image.response.sha256,
                    semantic_label=f"{record.document.title}来源页新闻原图",
                    assigned_section_index=ordinal,
                    alt_text=f"{record.document.title}来源页新闻原图 {ordinal + 1}"[:200],
                    provenance_kind="live_same_source_news_image",
                    source_page_url=record.document.canonical_url,
                    caption=(
                        item.reference.caption
                        or f"{record.document.title}来源页原图；仅作新闻上下文，不构成事实证据。"
                    )[:300],
                    credit=item.credit[:200],
                    rights_status="publish_permission_unverified",
                    context_only_not_evidence=True,
                ),
                body,
            )
        )
    cover = _compose_role_cover(record.input.role)
    rows.append(
        (
            OfficialAccountMediaResult(
                local_media_id=f"weekly-live-{record.input.role.value}-cover-0",
                role="cover",
                ordinal=0,
                media_url=f"/local/weekly-live-{record.input.role.value}-cover-0",
                media_type="image/jpeg",
                byte_size=len(cover),
                sha256=sha256(cover).hexdigest(),
                semantic_label=f"{record.document.title}小赛 AI 宽封面"[:200],
                provenance_kind="deterministic_local_ip_composition",
            ),
            cover,
        )
    )
    return tuple(rows)


def _live_selection(
    live_input: LiveWeeklyInput,
    acquired: tuple[AcquiredNewsArticle, AcquiredNewsArticle, AcquiredNewsArticle],
) -> WeeklyEditionSelection:
    candidates: list[WeeklyGovernedCandidate] = []
    for record in acquired:
        role = record.input.role
        candidate = TopicCandidate(
            event_id=record.event_id,
            event_version_id=record.event_version_id,
            event_time=cast(datetime, record.document.published_at),
            source_trust=0.95,
            source_diversity=4,
            ai_relevance=0.92,
            parent_relevance=0.9,
            communication_potential=0.9,
            editorial_priority=0.9,
            science_tech_editorial_cohort=(
                ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY
                if role is WeeklyArticleRole.INDUSTRY_TREND
                else ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY
            ),
            science_tech_education_relevance=0.92,
            frontier_significance=0.95 if role is WeeklyArticleRole.INDUSTRY_TREND else 0.82,
            science_tech_editorial_reason_codes=("explicit_science_technology_education",),
            science_tech_content_signals=(
                (ScienceTechContentSignal.COMPLETED_PROGRESS,)
                if role is WeeklyArticleRole.INDUSTRY_TREND
                else ()
            ),
            product_matrix_fit_v2=0.92,
            product_matrix_v2_direction_ids=(
                ("ai_theme_robotics_agent_safety_math_3d_hackathon",)
                if role is WeeklyArticleRole.INDUSTRY_TREND
                else ("science_exploration_courses_and_camps",)
                if role is WeeklyArticleRole.APPLICATION_CASE
                else ()
            ),
            priority_title=record.document.title,
            priority_summary=_complete_prefix(record.evidence_quote, maximum=500),
        )
        score = score_topic_candidate(
            candidate,
            as_of=live_input.selection_cutoff,
            config=TopicScoringConfig(),
        )
        candidates.append(
            WeeklyGovernedCandidate(
                candidate=candidate,
                score=score,
                organization_type=record.source.organization_type,
                source_metadata_fingerprint=record.source.fingerprint,
            )
        )
    schedule = WeeklyEditionSchedule()
    week_start = live_input.selection_cutoff.date()
    week_start = week_start.fromordinal(week_start.toordinal() - week_start.weekday())
    selection = select_weekly_articles(
        tuple(candidates),
        week_start=week_start,
        cutoff=live_input.selection_cutoff,
        schedule=schedule,
    )
    if tuple(item.event_id for item in selection.selected) != tuple(
        item.event_id for item in acquired
    ):
        raise ValueError("weekly live governed role assignment changed")
    return selection


def _live_acquisition_audit(
    live_input: LiveWeeklyInput,
    acquired: tuple[AcquiredNewsArticle, AcquiredNewsArticle, AcquiredNewsArticle],
) -> dict[str, object]:
    image_calls = sum(len(item.images) for item in acquired)
    return {
        "version": WEEKLY_LIVE_ACQUISITION_AUDIT_VERSION,
        "mode": "explicit_live_local_only",
        "selection_cutoff": live_input.selection_cutoff.isoformat(),
        "fetched_at": max(item.page_fetched_at for item in acquired).isoformat(),
        "article_count": 3,
        "articles": [
            {
                "role": item.input.role.value,
                "source_key": item.source.key,
                "source_registry_version": LIVE_SOURCE_REGISTRY_VERSION,
                "source_metadata_fingerprint": item.source.fingerprint,
                "publisher": item.source.publisher,
                "organization_type": item.source.organization_type,
                "requested_url": item.requested_url,
                "final_url": item.final_url,
                "canonical_url": item.document.canonical_url,
                "title": item.document.title,
                "published_at": cast(datetime, item.document.published_at).isoformat(),
                "published_date": item.input.expected_published_date.isoformat(),
                "page_media_type": item.page_media_type,
                "page_byte_size": item.page_byte_size,
                "page_sha256": item.page_sha256,
                "page_fetched_at": item.page_fetched_at.isoformat(),
                "clean_text_byte_size": len(item.document.clean_text.encode("utf-8")),
                "clean_text_sha256": sha256(item.document.clean_text.encode("utf-8")).hexdigest(),
                "evidence_id": str(item.evidence_id),
                "evidence_quote_sha256": sha256(item.evidence_quote.encode("utf-8")).hexdigest(),
                "event_id": str(item.event_id),
                "event_version_id": str(item.event_version_id),
                "images": [
                    {
                        "image_url": image.reference.image_url,
                        "source_page_url": image.reference.source_page_url,
                        "response_media_type": image.image.response.media_type,
                        "byte_size": len(image.image.response.body),
                        "sha256": image.image.response.sha256,
                        "width": image.image.width,
                        "height": image.image.height,
                        "fetched_at": image.image.response.fetched_at.isoformat(),
                        "caption": image.reference.caption,
                        "credit": image.credit,
                        "rights_status": "publish_permission_unverified",
                        "context_only_not_evidence": True,
                    }
                    for image in item.images
                ],
            }
            for item in acquired
        ],
        "external_calls": {
            "news": 3 + image_calls,
            "source_pages": 3,
            "news_images": image_calls,
            "model": 0,
            "embedding": 0,
            "image_generation": 0,
            "wechat": 0,
            "wecom": 0,
        },
        "boundaries": {
            "development_only": True,
            "local_only": True,
            "published": False,
            "news_images_context_only_not_evidence": True,
            "publish_permission_verified": False,
            "wechat_or_wecom_clients_constructed": False,
        },
    }


def _live_theme_cluster_audit(
    live_input: LiveWeeklyInput,
    acquired: tuple[AcquiredArticleCluster, AcquiredArticleCluster, AcquiredArticleCluster],
) -> dict[str, object]:
    if live_input.theme is None:
        raise ValueError("weekly live theme audit requires a theme")
    all_sources = [source for cluster in acquired for source in cluster.sources]
    image_calls = sum(len(source.images) for source in all_sources)
    return {
        "version": LIVE_THEME_CLUSTER_AUDIT_VERSION,
        "mode": "explicit_live_theme_clusters_local_only",
        "selection_cutoff": live_input.selection_cutoff.isoformat(),
        "fetched_at": max(source.page_fetched_at for source in all_sources).isoformat(),
        "theme": live_input.theme,
        "article_count": 3,
        "source_count": len(all_sources),
        "articles": [
            {
                "role": cluster.input.role.value,
                "angle": cluster.input.angle,
                "editorial_title": cluster.input.editorial_title,
                "event_id": str(cluster.primary.event_id),
                "event_version_id": str(cluster.primary.event_version_id),
                "organization_type": cluster.primary.source.organization_type,
                "source_metadata_fingerprint": cluster.primary.source.fingerprint,
                "sources": [_theme_cluster_source_audit(source) for source in cluster.sources],
            }
            for cluster in acquired
        ],
        "external_calls": {
            "news": len(all_sources) + image_calls,
            "source_pages": len(all_sources),
            "news_images": image_calls,
            "model": 0,
            "embedding": 0,
            "image_generation": 0,
            "wechat": 0,
            "wecom": 0,
        },
        "boundaries": {
            "development_only": True,
            "local_only": True,
            "published": False,
            "news_images_context_only_not_evidence": True,
            "publish_permission_verified": False,
            "source_marks_preserved": True,
            "wechat_or_wecom_clients_constructed": False,
        },
    }


def _theme_cluster_source_audit(item: AcquiredNewsArticle) -> dict[str, object]:
    return {
        "relation": item.input.relation,
        "owner_role": item.input.role.value,
        "source_key": item.source.key,
        "source_registry_version": LIVE_SOURCE_REGISTRY_VERSION,
        "source_metadata_fingerprint": item.source.fingerprint,
        "publisher": item.source.publisher,
        "organization_type": item.source.organization_type,
        "requested_url": item.requested_url,
        "final_url": item.final_url,
        "canonical_url": item.document.canonical_url,
        "title": item.document.title,
        "published_at": cast(datetime, item.document.published_at).isoformat(),
        "published_date": item.input.expected_published_date.isoformat(),
        "page_media_type": item.page_media_type,
        "page_byte_size": item.page_byte_size,
        "page_sha256": item.page_sha256,
        "page_fetched_at": item.page_fetched_at.isoformat(),
        "clean_text_byte_size": len(item.document.clean_text.encode("utf-8")),
        "clean_text_sha256": sha256(item.document.clean_text.encode("utf-8")).hexdigest(),
        "evidence_id": str(item.evidence_id),
        "evidence_quote_sha256": sha256(item.evidence_quote.encode("utf-8")).hexdigest(),
        "event_id": str(item.event_id),
        "event_version_id": str(item.event_version_id),
        "images": [
            {
                "image_url": image.reference.image_url,
                "source_page_url": image.reference.source_page_url,
                "response_media_type": image.image.response.media_type,
                "byte_size": len(image.image.response.body),
                "sha256": image.image.response.sha256,
                "width": image.image.width,
                "height": image.image.height,
                "fetched_at": image.image.response.fetched_at.isoformat(),
                "caption": image.reference.caption,
                "credit": image.credit,
                "rights_status": "publish_permission_unverified",
                "context_only_not_evidence": True,
                "source_marks_preserved": True,
            }
            for image in item.images
        ],
    }


def _source_profile(source: LiveSourceDefinition, entry_url: str) -> SourceProfile:
    source_id = uuid5(NAMESPACE_URL, f"weekly-live-source:{source.key}")
    return SourceProfile(
        source_id=source_id,
        source_version_id=uuid5(source_id, source.fingerprint),
        slug=source.key,
        display_name=source.publisher,
        organization_type=source.organization_type,
        tier=SourceTier.A,
        connector_key="weekly_live_exact_html_v1",
        entry_url=entry_url,
        allowed_hosts=source.allowed_hosts,
        allowed_path_prefixes=source.allowed_path_prefixes,
        connector_version="1.0.0",
        parser_version="1.0.0",
        robots_status=source.robots_status,
        terms_reviewed_at=_TERMS_REVIEWED_AT,
    )


def _validate_registered_url(value: str, source: LiveSourceDefinition) -> None:
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or parts.hostname not in source.allowed_hosts
        or parts.query
        or parts.fragment
        or parts.username is not None
        or parts.password is not None
        or not any(parts.path.startswith(prefix) for prefix in source.allowed_path_prefixes)
    ):
        raise ValueError("weekly live URL is outside the registered source boundary")


def _verify_date_literal(body: bytes, expected: date) -> None:
    text_value = _decode_page(body)
    variants = {
        expected.isoformat(),
        expected.strftime("%Y/%m/%d"),
        f"{expected.year}年{expected.month}月{expected.day}日",
        f"{expected.year}年{expected.month:02d}月{expected.day:02d}日",
    }
    if not any(value in text_value for value in variants):
        raise ValueError("weekly live expected publication date is absent from the source page")


def _decode_page(body: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("weekly live source page encoding is unsupported")


def _bounded_evidence_quote(
    clean_text: str,
    *,
    excluded_lines: tuple[str, ...] = (),
) -> str:
    units = _source_units(clean_text, excluded_lines=excluded_lines)
    if sum(len(item) for item in units) < 300:
        raise ValueError("weekly live evidence text is too short")
    selected: list[str] = []
    size = 0
    for unit in units:
        addition = len(unit) + (1 if selected else 0)
        if size + addition > 1_800:
            break
        selected.append(unit)
        size += addition
    if len(selected) < 4:
        raise ValueError("weekly live evidence has insufficient complete source units")
    return "\n\n".join(selected)


def _source_excerpts(
    value: str,
    *,
    prioritized_terms: tuple[str, ...] = (),
) -> tuple[str, str, str, str]:
    units = _source_units(value)
    excerpts: list[str] = []
    cursor = 0
    if len(units) < 4:
        raise ValueError("weekly live source has fewer than four complete excerpt groups")
    for group_index in range(4):
        pending: list[str] = []
        pending_size = 0
        remaining_groups = 3 - group_index
        while cursor < len(units):
            combined = "\n".join(pending)
            if pending and pending_size >= 70 and not _has_unbalanced_quotes(combined):
                break
            if (
                pending
                and len(units) - cursor <= remaining_groups
                and not _has_unbalanced_quotes(combined)
            ):
                break
            unit = units[cursor]
            pending.append(unit)
            pending_size += len(unit)
            cursor += 1
        if not pending:
            raise ValueError("weekly live source has fewer than four complete excerpt groups")
        excerpt = "\n".join(pending)
        if _has_unbalanced_quotes(excerpt):
            raise ValueError("weekly live source excerpt has unbalanced quotation marks")
        excerpts.append(excerpt)
    if prioritized_terms:
        prioritized = next(
            (unit for unit in units if all(term in unit for term in prioritized_terms)),
            None,
        )
        if prioritized is not None:
            current_index = next(
                (index for index, excerpt in enumerate(excerpts) if prioritized in excerpt),
                None,
            )
            if current_index is None:
                excerpts[-1] = prioritized
            elif current_index != len(excerpts) - 1:
                excerpts[current_index], excerpts[-1] = excerpts[-1], prioritized
    return excerpts[0], excerpts[1], excerpts[2], excerpts[3]


def _source_units(
    value: str,
    *,
    excluded_lines: tuple[str, ...] = (),
) -> tuple[str, ...]:
    units: list[str] = []
    pending_source_lines: list[str] = []
    normalized_exclusions = {_normalized(item).strip() for item in excluded_lines}

    def flush_source_lines() -> None:
        if not pending_source_lines:
            return
        source_line_unit = "\n".join(pending_source_lines)
        pending_source_lines.clear()
        if len(source_line_unit) >= 12:
            units.append(source_line_unit)

    for raw_line in value.splitlines():
        line = _normalized(raw_line).strip()
        if not line:
            flush_source_lines()
            continue
        if (
            line in normalized_exclusions
            or _is_photo_caption_noise(line)
            or _is_page_chrome_noise(line)
            or (re.search(r"[。！？!?…]", line) is None and _is_event_roster_noise(line))
        ):
            flush_source_lines()
            continue
        line = line.strip(" ，；：、")
        if re.search(r"[。！？!?…]", line) is None:
            if len(line) >= 6:
                pending_source_lines.append(line)
            continue
        flush_source_lines()
        for raw_part in re.findall(r".*?(?:[。！？!?]+|…{1,2})[”’》]?|.+$", line):
            part = raw_part.strip(" ，；：、")
            while part.startswith(("”", "’", "》")) and _can_absorb_closer("".join(units), part[0]):
                units[-1] += part[0]
                part = part[1:].lstrip()
            if not part:
                continue
            complete_sentence = re.search(r"(?:[。！？!?]+|…{1,2})$", part) is not None
            complete_sentence_with_closer = (
                re.search(r"(?:[。！？!?]+|…{1,2})[”’》]$", part) is not None
            )
            if (
                len(part) < 12
                or not (complete_sentence or complete_sentence_with_closer)
                or _is_photo_caption_noise(part)
                or _is_page_chrome_noise(part)
                or _is_event_roster_noise(part)
            ):
                continue
            units.append(part)
    flush_source_lines()
    if len(units) < 4:
        raise ValueError("weekly live source text lacks complete semantic units")
    return tuple(units)


def _is_photo_caption_noise(value: str) -> bool:
    normalized = value.strip()
    return bool(
        normalized in {"图片", "Image"}
        or normalized.startswith(("制作", "责任编辑", "字体", "来源"))
        or re.search(r"(?:新华社)?记者.{0,100}摄[。.]?$", normalized)
        or re.search(r"新华社发（[^）]+摄）[。.]?$", normalized)
    )


def _is_page_chrome_noise(value: str) -> bool:
    normalized = value.strip()
    return bool(
        re.fullmatch(
            r"(?:发布日期|发布时间)[：:]?\s*\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?\s*浏览次数.*",
            normalized,
        )
        or re.fullmatch(r"浏览次数[：:]?\s*[-\d]*", normalized)
    )


def _is_event_roster_noise(value: str) -> bool:
    """Drop ceremonial attendee lists while retaining attributed substantive statements."""

    normalized = value.strip()
    return bool(
        re.search(r"(?:等)?出席(?:开班|开营|活动|会议|仪式|典礼)", normalized)
        or re.search(
            r"(?:领导和专家|专家和学员|学员代表).{0,40}参加(?:开班|开营|活动|会议|仪式|典礼)",
            normalized,
        )
        or re.fullmatch(r".{0,100}(?:致欢迎辞|作开班致辞)[。.]?", normalized)
    )


def _has_unbalanced_quotes(value: str) -> bool:
    return any(
        value.count(opener) != value.count(closer)
        for opener, closer in (("“", "”"), ("‘", "’"), ("《", "》"))
    )


def _can_absorb_closer(value: str, closer: str) -> bool:
    opener = {"”": "“", "’": "‘", "》": "《"}[closer]
    return value.count(opener) > value.count(closer)


def _complete_prefix(value: str, *, maximum: int) -> str:
    units = _source_units(value)
    selected: list[str] = []
    size = 0
    for unit in units:
        addition = len(unit) + (1 if selected else 0)
        if size + addition > maximum:
            break
        selected.append(unit)
        size += addition
    if not selected:
        raise ValueError("weekly live complete source prefix is unavailable")
    return "\n".join(selected)


def _live_digest(record: AcquiredNewsArticle) -> str:
    return (
        f"{record.source.publisher}于{record.input.expected_published_date.isoformat()}发布的真实新闻。"
        "本文核对原文、保留新闻原图权利提示，并从科创教育视角区分事实、判断与家庭行动。"
    )[:240]


def _live_lead(record: AcquiredNewsArticle) -> str:
    focus = ""
    if record.input.role is WeeklyArticleRole.APPLICATION_CASE:
        focus = "这条应用案例聚焦涉农高校把人工智能技术带入教学与实操培训的现场。"
    return (
        f"{focus}本篇绑定真实来源《{record.document.title}》及其独立页面证据。"
        "新闻原图只用于帮助理解现场，不替代原文、不证明转载授权；小赛和赛先生正文图用于"
        "承接解释与家庭科创讨论。"
    )


def _live_conclusion(record: AcquiredNewsArticle) -> str:
    return (
        f"关于《{record.document.title}》，这次本地成品保留了来源、日期、证据和原图边界。"
        "接下来最重要的不是增加结论，而是持续核对后续公开信息，并把家庭行动做小、做实、做完一次复盘。"
    )


def _validate_acquired_distinctness(values: list[AcquiredNewsArticle]) -> None:
    if len(values) != 3:
        raise ValueError("weekly live acquisition requires exactly three results")
    identity_groups = (
        {item.document.canonical_url for item in values},
        {item.document.title for item in values},
        {item.input.expected_published_date for item in values},
        {item.source.key for item in values},
        {item.source.publisher for item in values},
        {item.page_sha256 for item in values},
        {item.event_id for item in values},
        {item.event_version_id for item in values},
        {item.evidence_id for item in values},
    )
    if any(len(group) != 3 for group in identity_groups):
        raise ValueError("weekly live source/event/evidence identities must be distinct")
    image_hashes = [image.image.response.sha256 for item in values for image in item.images]
    if len(image_hashes) < 3 or len(image_hashes) != len(set(image_hashes)):
        raise ValueError("weekly live news-context image bytes must be distinct")


def _validate_acquired_cluster_distinctness(
    clusters: list[AcquiredArticleCluster],
    values: list[AcquiredNewsArticle],
) -> None:
    if len(clusters) != 3 or len(values) != 6:
        raise ValueError("weekly live theme run requires three two-source clusters")
    if tuple(cluster.input.role.value for cluster in clusters) != WEEKLY_EDITION_ROLE_ORDER:
        raise ValueError("weekly live acquired cluster role order changed")
    if any(
        tuple(source.input.relation for source in cluster.sources) != ("primary", "supporting")
        or any(source.input.role is not cluster.input.role for source in cluster.sources)
        for cluster in clusters
    ):
        raise ValueError("weekly live acquired source escaped its owning cluster")
    identity_groups = (
        [item.document.canonical_url for item in values],
        [item.page_sha256 for item in values],
        [item.event_id for item in values],
        [item.event_version_id for item in values],
        [item.evidence_id for item in values],
    )
    if any(len(group) != len(set(group)) for group in identity_groups):
        raise ValueError(
            "weekly live theme source/event/evidence identities must be globally distinct"
        )
    image_hashes = [image.image.response.sha256 for item in values for image in item.images]
    if len(image_hashes) != 6 or len(image_hashes) != len(set(image_hashes)):
        raise ValueError("weekly live theme context-image hashes must be globally distinct")


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _exact_url_filter(approved_url: str) -> Callable[[str], bool]:
    return lambda candidate: candidate == approved_url


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("weekly live JSON contains a duplicate field")
        result[key] = value
    return result


def _fetchers(settings: Settings) -> tuple[SafeHttpFetcher, SafeSourceImageFetcher]:
    return SafeHttpFetcher(settings), SafeSourceImageFetcher(settings)


def _playwright_mobile_validation(
    artifact: EditorHandoffV2Artifact,
) -> EditorHandoffMobileValidation:
    """Run the repository Playwright acceptance against this exact staged child."""

    with tempfile.TemporaryDirectory(prefix="weekly-live-mobile-") as temporary:
        root = Path(temporary)
        target = write_editor_handoff_v2_artifact(artifact, root / "artifact")
        report = root / "browser-report.json"
        environment = os.environ.copy()
        environment.update(
            {
                "EDITOR_HANDOFF_FIXTURE_DIR": str(target),
                "EDITOR_HANDOFF_BROWSER_REPORT": str(report),
            }
        )
        result = subprocess.run(
            (
                "npm",
                "run",
                "test:e2e",
                "--prefix",
                "frontend",
                "--",
                "--grep",
                "editor handoff fixture",
            ),
            cwd=_REPOSITORY_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            details = (result.stdout + "\n" + result.stderr)[-4_000:]
            raise RuntimeError(f"weekly live Playwright validation failed:\n{details}")
        payload = json.loads(
            report.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicates,
        )
        if not isinstance(payload, dict) or payload.get("fixture_fingerprint") != (
            artifact.artifact_fingerprint
        ):
            raise ValueError("weekly live browser report staged-artifact identity changed")
        return _load_browser_report(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    live_input = load_live_weekly_input(args.live_input)
    page_fetcher, image_fetcher = _fetchers(get_settings())
    artifact = asyncio.run(
        build_live_weekly_edition_artifact(
            live_input,
            page_fetcher=page_fetcher,
            image_fetcher=image_fetcher,
            mobile_validation_factory=_playwright_mobile_validation,
        )
    )
    target = write_weekly_edition_artifact(artifact, args.output_dir)
    print(target)
    print(f"zip_sha256={artifact.zip_sha256}")
    print(f"live_acquisition_audit={target / 'live-acquisition.json'}")
    print("wechat_calls=0")
    print("wecom_calls=0")


if __name__ == "__main__":
    main()
