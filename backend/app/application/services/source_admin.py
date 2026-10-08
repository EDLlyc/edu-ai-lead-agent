# ruff: noqa: RUF001
"""Manage news sources from the 运营后台: preview, add, edit, switch on/off, archive.

A preview fetches with the same `SafeHttpFetcher` rules as acquisition (https, public DNS only,
bounded redirects and size) and stores nothing. Adding or editing re-checks robots.txt. A new
operator source starts disabled. Code-defined sources can only be switched on or off; that choice
is kept by `seed_sources` across deploys. Every change writes an audit row in the same
transaction.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.admin_auth import AdminPrincipal
from app.core.config import Settings
from app.core.errors import (
    AppError,
    ConflictError,
    NotFoundError,
    PermanentFetchError,
)
from app.domain.editorial_relevance import (
    ScienceTechEditorialCohort,
    evaluate_science_tech_editorial_relevance,
)
from app.domain.entities import DiscoveredItem, FetchedResponse, SourceProfile
from app.domain.enums import SourceTier
from app.domain.freshness import evaluate_publication_freshness
from app.domain.source_admin import (
    GENERIC_CONNECTOR_VERSION,
    GENERIC_PARSER_VERSION,
    OPERATOR_RELEVANCE_RULE_VERSION,
    OperatorSourceDraft,
)
from app.infrastructure.db.admin_auth import add_audit_event
from app.infrastructure.db.models import SourceModel, SourceVersionModel
from app.infrastructure.db.source_admin import (
    add_operator_source,
    ensure_operator_version,
    load_source_for_update,
)
from app.infrastructure.ingestion.connectors import build_generic_connector

PREVIEW_LINK_LIMIT = 10
PREVIEW_SAMPLE_LIMIT = 3
PREVIEW_REQUEST_GAP_SECONDS = 1.0

RobotsVerdict = Literal["allowed", "no_robots_file", "disallowed"]


class SourceFetcher(Protocol):
    async def fetch(self, url: str, profile: SourceProfile) -> FetchedResponse: ...


# Operator-facing reasons for fetch failures (codes from SafeHttpFetcher / the security checks).
_FETCH_PROBLEMS = {
    "host_not_allowed": "网址跳转到了别的域名，请直接填跳转后的地址",
    "path_not_allowed": "网址跳转到了不允许的位置",
    "https_required": "网站跳转到了不安全的 http 地址",
    "non_public_address": "这个域名指向内网地址，不能抓取",
    "dns_resolution_failed": "域名解析不到，请检查网址",
    "redirect_limit": "网站跳转次数太多",
    "response_too_large": "页面太大，超过抓取上限",
    "unsupported_content": "这个地址不是网页或 RSS",
    "total_timeout": "网站响应太慢，超时了",
    "network_failure": "连不上这个网站",
    "parse_failure": "页面里没找到能识别的文章",
}


def fetch_problem(error: AppError) -> str:
    if error.code.startswith("http_"):
        return f"网站返回错误 {error.code.removeprefix('http_')}"
    return _FETCH_PROBLEMS.get(error.code, f"抓取失败（{error.code}）")


def _profile(draft: OperatorSourceDraft, *, robots_status: str = "allowed") -> SourceProfile:
    return SourceProfile(
        source_id=uuid4(),
        source_version_id=uuid4(),
        slug="ops-preview",
        display_name=draft.display_name,
        organization_type=draft.organization_type,
        tier=SourceTier(draft.tier),
        connector_key=draft.config.connector_key,
        entry_url=draft.entry_url,
        allowed_hosts=(draft.host,),
        allowed_path_prefixes=("/",),
        connector_version=GENERIC_CONNECTOR_VERSION,
        parser_version=GENERIC_PARSER_VERSION,
        relevance_rule_version=OPERATOR_RELEVANCE_RULE_VERSION,
        robots_status=robots_status,
        connector_config=draft.config.to_json(),
    )


async def check_robots(
    fetcher: SourceFetcher, draft: OperatorSourceDraft, *, user_agent: str
) -> RobotsVerdict:
    """robots.txt for the entry URL; a missing file (4xx) allows, a server error refuses."""

    parts = urlsplit(draft.entry_url)
    robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
    try:
        response = await fetcher.fetch(robots_url, _profile(draft))
    except PermanentFetchError as error:
        if error.code.startswith("http_4"):
            return "no_robots_file"
        raise
    parser = RobotFileParser()
    parser.parse(response.body.decode("utf-8", errors="replace").splitlines())
    return "allowed" if parser.can_fetch(user_agent, draft.entry_url) else "disallowed"


class RobotsDisallowedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "source_robots_disallowed", "这个网站的 robots.txt 不允许抓取这个地址", 422
        )


async def _required_robots(
    fetcher: SourceFetcher, draft: OperatorSourceDraft, *, user_agent: str
) -> str:
    try:
        verdict = await check_robots(fetcher, draft, user_agent=user_agent)
    except AppError as error:
        raise AppError(
            "source_robots_unreadable", f"读不到 robots.txt：{fetch_problem(error)}", 422
        ) from error
    if verdict == "disallowed":
        raise RobotsDisallowedError()
    return "allowed"


@dataclass(frozen=True, slots=True)
class PreviewSample:
    title: str | None
    url: str
    published_at: datetime | None
    characters: int
    excerpt: str
    freshness: Literal["fresh", "stale", "unknown"]
    relevant: bool
    topic: Literal["education", "frontier", "other"] | None
    problem: str | None


@dataclass(frozen=True, slots=True)
class SourcePreview:
    robots: RobotsVerdict | None
    problem: str | None
    links: tuple[DiscoveredItem, ...]
    samples: tuple[PreviewSample, ...]

    @property
    def ok(self) -> bool:
        return self.problem is None and any(sample.problem is None for sample in self.samples)


PreviewTopic = Literal["education", "frontier", "other"]
_TOPICS: dict[ScienceTechEditorialCohort, PreviewTopic] = {
    ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY: "education",
    ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY: "frontier",
}


async def preview_source(
    fetcher: SourceFetcher,
    draft: OperatorSourceDraft,
    *,
    settings: Settings,
    now: datetime,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> SourcePreview:
    try:
        robots = await check_robots(fetcher, draft, user_agent=settings.acquisition_user_agent)
    except AppError as error:
        return SourcePreview(None, f"读不到 robots.txt：{fetch_problem(error)}", (), ())
    if robots == "disallowed":
        return SourcePreview(robots, "这个网站的 robots.txt 不允许抓取这个地址", (), ())

    profile = _profile(draft)
    connector = build_generic_connector(draft.config)
    try:
        await sleep(PREVIEW_REQUEST_GAP_SECONDS)
        listing = await fetcher.fetch(draft.entry_url, profile)
        links = tuple(connector.discover(listing, profile, limit=PREVIEW_LINK_LIMIT))
    except AppError as error:
        return SourcePreview(robots, fetch_problem(error), (), ())

    samples: list[PreviewSample] = []
    for item in links[:PREVIEW_SAMPLE_LIMIT]:
        try:
            await sleep(PREVIEW_REQUEST_GAP_SECONDS)
            document = connector.extract(await fetcher.fetch(item.url, profile), item, profile)
        except AppError as error:
            samples.append(
                PreviewSample(
                    item.title,
                    item.url,
                    item.published_at,
                    0,
                    "",
                    "unknown",
                    False,
                    None,
                    fetch_problem(error),
                )
            )
            continue
        freshness = evaluate_publication_freshness(
            document.published_at,
            evaluated_at=now,
            max_age_days=settings.acquisition_freshness_window_days,
        )
        relevance = evaluate_science_tech_editorial_relevance(
            document.title, document.clean_text, rule_version=OPERATOR_RELEVANCE_RULE_VERSION
        )
        samples.append(
            PreviewSample(
                title=document.title,
                url=document.canonical_url,
                published_at=document.published_at,
                characters=len(document.clean_text),
                excerpt=" ".join(document.clean_text.split())[:120],
                freshness=freshness.status,
                relevant=relevance.is_candidate,
                topic=_TOPICS.get(relevance.cohort, "other"),
                problem=None,
            )
        )
    return SourcePreview(robots, None, links, tuple(samples))


async def create_operator_source(
    session: AsyncSession,
    fetcher: SourceFetcher,
    draft: OperatorSourceDraft,
    *,
    principal: AdminPrincipal,
    settings: Settings,
    now: datetime,
) -> tuple[SourceModel, SourceVersionModel]:
    robots_status = await _required_robots(
        fetcher, draft, user_agent=settings.acquisition_user_agent
    )
    source, version = await add_operator_source(
        session,
        draft=draft,
        robots_status=robots_status,
        owner=f"admin:{principal.username}",
        now=now,
    )
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="source.created",
        target_type="source",
        target_id=str(source.id),
        detail={
            "display_name": source.display_name,
            "entry_url": version.entry_url,
            "kind": draft.config.kind,
            "tier": version.trust_tier,
            "version": version.version,
        },
    )
    await session.commit()
    return source, version


async def _require_source(
    session: AsyncSession, source_id: UUID
) -> tuple[SourceModel, SourceVersionModel | None]:
    found = await load_source_for_update(session, source_id)
    if found is None:
        raise NotFoundError("source")
    return found


async def update_operator_source(
    session: AsyncSession,
    fetcher: SourceFetcher,
    source_id: UUID,
    draft: OperatorSourceDraft,
    *,
    principal: AdminPrincipal,
    settings: Settings,
    now: datetime,
) -> tuple[SourceModel, SourceVersionModel]:
    source, current = await _require_source(session, source_id)
    if source.managed_by != "operator":
        await session.rollback()
        raise ConflictError("内置新闻源只能开关，不能修改")
    if source.archived_at is not None:
        await session.rollback()
        raise ConflictError("这个新闻源已归档")
    robots_status = await _required_robots(
        fetcher, draft, user_agent=settings.acquisition_user_agent
    )
    changed: list[str] = []
    if source.display_name != draft.display_name:
        changed.append("display_name")
        source.display_name = draft.display_name
    if source.organization_type != draft.organization_type:
        changed.append("organization_type")
        source.organization_type = draft.organization_type
    version, _created = await ensure_operator_version(
        session, source=source, draft=draft, robots_status=robots_status, now=now
    )
    if current is None or version.id != current.id:
        changed_before_version = len(changed)
        if current is not None:
            if current.entry_url != version.entry_url:
                changed.append("entry_url")
            if current.trust_tier != version.trust_tier:
                changed.append("tier")
            if current.connector_config != version.connector_config:
                changed.append("connector_config")
        if len(changed) == changed_before_version:
            changed.append("fetch_settings")
        source.active_version_id = version.id
    if not changed:
        await session.rollback()
        return source, version
    source.updated_at = now
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="source.updated",
        target_type="source",
        target_id=str(source.id),
        detail={
            "display_name": source.display_name,
            "changed": changed,
            "version": version.version,
        },
    )
    await session.commit()
    return source, version


async def set_source_enabled(
    session: AsyncSession,
    source_id: UUID,
    *,
    enabled: bool,
    principal: AdminPrincipal,
    now: datetime,
) -> SourceModel:
    source, version = await _require_source(session, source_id)
    if source.archived_at is not None:
        await session.rollback()
        raise ConflictError("这个新闻源已归档")
    if version is None:
        await session.rollback()
        raise ConflictError("这个新闻源还没接入完成，不能打开")
    if source.enabled == enabled:
        source.enabled_set_by = "operator"
        await session.commit()
        return source
    source.enabled = enabled
    source.enabled_set_by = "operator"
    source.updated_at = now
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="source.enabled" if enabled else "source.disabled",
        target_type="source",
        target_id=str(source.id),
        detail={"display_name": source.display_name, "managed_by": source.managed_by},
    )
    await session.commit()
    return source


async def archive_operator_source(
    session: AsyncSession,
    source_id: UUID,
    *,
    principal: AdminPrincipal,
    now: datetime,
) -> SourceModel:
    source, _version = await _require_source(session, source_id)
    if source.managed_by != "operator":
        await session.rollback()
        raise ConflictError("内置新闻源不能删除，只能关闭")
    if source.archived_at is not None:
        await session.rollback()
        return source
    source.enabled = False
    source.enabled_set_by = "operator"
    source.archived_at = now
    source.updated_at = now
    await add_audit_event(
        session,
        now=now,
        user_id=principal.user_id,
        username=principal.username,
        action="source.archived",
        target_type="source",
        target_id=str(source.id),
        detail={"display_name": source.display_name},
    )
    await session.commit()
    return source


__all__ = [
    "PreviewSample",
    "RobotsDisallowedError",
    "SourceFetcher",
    "SourcePreview",
    "archive_operator_source",
    "check_robots",
    "create_operator_source",
    "fetch_problem",
    "preview_source",
    "set_source_enabled",
    "update_operator_source",
]
