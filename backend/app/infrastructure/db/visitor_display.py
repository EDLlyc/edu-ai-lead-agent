"""Bounded read model for the public visitor display."""

from __future__ import annotations

import asyncio
import logging
import time
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import (
    DateTime,
    String,
    Uuid,
    and_,
    case,
    column,
    func,
    or_,
    select,
    table,
    tuple_,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db.models import (
    ContentSlotRunModel,
    ContentSlotScoreModel,
    ContentSlotSelectionModel,
    CopyGenerationRunModel,
    EventClusterVersionModel,
    EvidenceCandidateModel,
    MaterialPackageModel,
    NewsInfographicJobModel,
    NormalizedArticleModel,
    OfficialAccountArticleRunModel,
    OfficialAccountArticleVersionModel,
    OfficialAccountGeneratedVisualEvalModel,
    OfficialAccountGeneratedVisualModel,
    OfficialAccountLocalDraftModel,
    OfficialAccountLocalMediaModel,
    OfficialAccountManualReviewModel,
    SourceModel,
    WeChatOfficialAccountDraftItemModel,
    WeComDeliveryJobModel,
    WeComInfographicSupplementModel,
)
from app.infrastructure.db.visitor_improvement import VisitorIssueSignal, load_issue_signals
from app.infrastructure.db.visitor_moments import VisitorMomentRow, load_moments
from app.infrastructure.db.visitor_report import VisitorReportDay, load_report_days

VISIBLE_RUN_LIMIT = 12
SLOT_BATCH_TRIGGERS = ("scheduled", "manual")
# Operator "人工加推" runs (production trigger `human`): one item each, shown as progress only.
HUMAN_PICK_TRIGGER = "human"
HUMAN_PICK_LOOKBACK = timedelta(days=3)
HUMAN_PICK_LIMIT = 24
VISIBLE_MEDIA_LIMIT = VISIBLE_RUN_LIMIT * 8
# Recent morning/noon/evening scoring batches, newest first, including rejected candidates.
NEWS_POOL_BATCH_LIMIT = 6
NEWS_POOL_CANDIDATE_LIMIT = 40
# Central-government policy documents on science/technology/education are shown past the rank
# cut-off, so an operator can still find and 人工加推 one that scored below the threshold.
NEWS_POOL_POLICY_EXTRA_LIMIT = 8
# Literal alternations only (no classes or lookarounds): production's server encoding may
# match bytes, which keeps whole-character literals correct. Mirrors the headline rule in
# `domain.national_tech_policy_signal`, restated here because the exhibit adapter runs from a
# pinned release source that predates that module.
_POLICY_ISSUER_REGEX = "中共中央|党中央|国务院|中央办公厅|国办印发|国办发布|国办关于|国办近日"
_POLICY_DOCUMENT_REGEX = (
    "意见|方案|规划|纲要|行动计划|行动方案|办法|条例|决定|若干措施|若干政策|通知"
)
_POLICY_SUBJECT_REGEX = (
    "新质生产力|科技|科学|创新|人工智能|数字经济|数字中国|数据要素|未来产业|战略性新兴产业|"
    "集成电路|量子|航天|制造强国|教育|人才"
)
_POLICY_EXCLUDED_REGEX = (
    "会议|座谈|会见|会晤|会谈|讲话|考察|调研|致信|贺信|通电话|经贸|磋商|关税|任免|任命|免去"
)
_NEWS_POOL_RUN_SCAN_LIMIT = NEWS_POOL_BATCH_LIMIT * 4
_NEWS_SNIPPET_CHARACTERS = 160
# Production text must not be cut in SQL: its server encoding truncates by bytes and splits
# CJK characters, which the UTF-8 client then rejects. Read whole values (bounded rows) and
# reuse the result briefly, since scoring batches change a few times a day.
_NEWS_POOL_TTL_SECONDS = 60.0

# This production-only read contract is deliberately outside Base.metadata. Older
# schemas need no migration or scheduler model just to serve the visitor display.
_SINGLE_EDITIONS = table(
    "official_account_single_editions",
    column("article_run_id", Uuid),
    column("article_fingerprint", String),
    column("content_fingerprint", String),
    column("prepared_artifact", JSONB),
    column("status", String),
    column("receipt_fingerprint", String),
    column("updated_at", DateTime(timezone=True)),
    schema="public",
)


@dataclass(frozen=True, slots=True)
class VisitorDisplaySingleEdition:
    article_run_id: UUID
    article_fingerprint: str
    content_fingerprint: str | None
    prepared_artifact: object
    status: str
    receipt_fingerprint: str | None
    updated_at: datetime
    match_count: int


@dataclass(frozen=True, slots=True)
class VisitorDisplayRunBundle:
    run: OfficialAccountArticleRunModel
    article: OfficialAccountArticleVersionModel | None
    media: tuple[OfficialAccountLocalMediaModel, ...]
    draft: OfficialAccountLocalDraftModel | None
    review: OfficialAccountManualReviewModel | None
    visual_evals: tuple[OfficialAccountGeneratedVisualEvalModel, ...]
    wechat_items: tuple[WeChatOfficialAccountDraftItemModel, ...]
    wechat_match_count: int
    single_editions: tuple[VisitorDisplaySingleEdition, ...] = ()


@dataclass(frozen=True, slots=True)
class VisitorNewsPoolCandidate:
    event_id: UUID
    title: str
    source_name: str | None
    source_url: str | None
    trust_tier: str | None
    published_at: datetime | None
    snippet: str | None
    total: float
    threshold: float
    passes_threshold: bool
    eligible: bool
    veto_codes: tuple[str, ...]
    same_day_excluded: bool
    same_day_exclusion_reason: str | None
    rank: int
    selected_ordinal: int | None
    normalized_features: dict[str, Any]
    weights: dict[str, Any]
    penalty_weights: dict[str, Any]


@dataclass(frozen=True, slots=True)
class VisitorNewsPoolBatch:
    business_date: date
    content_slot: str
    target_at: datetime
    total_scores: int
    eligible_scores: int
    selected_count: int
    unfilled_reason_codes: tuple[str, ...]
    candidates: tuple[VisitorNewsPoolCandidate, ...]
    # Source of a human pick; kept server-side only (never projected to the exhibit).
    run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class VisitorHumanPickRow:
    """Read-only progress of one production human pick through the normal pipeline."""

    event_id: UUID
    picked_at: datetime
    expires_at: datetime
    copy_status: str | None = None
    copy_error: str | None = None
    package_status: str | None = None
    # "pending" until the operator pushes (approves) a held pick.
    package_review_status: str | None = None
    delivery_status: str | None = None
    delivery_error: str | None = None
    infographic_status: str | None = None
    supplement_status: str | None = None


_LOGGER = logging.getLogger(__name__)
T = TypeVar("T")
_REPORT_TTL_SECONDS = 120.0
# A new post should reach the screens soon after it is sent; this read is small.
_MOMENT_TTL_SECONDS = 15.0
# How long an expired result may still be served while a refresh runs behind it.
_STALE_SERVE_SECONDS = 600.0
_REFRESH_TIMEOUT_SECONDS = 30.0


@dataclass(slots=True)
class _CacheEntry:
    loaded_at: float
    day: date | None
    value: Any


_CACHE: weakref.WeakKeyDictionary[async_sessionmaker[AsyncSession], dict[str, _CacheEntry]] = (
    weakref.WeakKeyDictionary()
)
_REFRESHING: weakref.WeakKeyDictionary[
    async_sessionmaker[AsyncSession], dict[str, asyncio.Task[None]]
] = weakref.WeakKeyDictionary()


class PostgresVisitorDisplayRepository:
    """Loads one bounded, consistent-enough read projection without mutation."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_latest(self) -> tuple[VisitorDisplayRunBundle, ...]:
        async with self._session_factory() as session:
            runs = await _latest_live_runs(session)
            if not runs:
                return ()
            run_ids = tuple(run.id for run in runs)
            article_ids = tuple(
                run.active_article_version_id
                for run in runs
                if run.active_article_version_id is not None
            )
            articles = (
                tuple(
                    await session.scalars(
                        select(OfficialAccountArticleVersionModel).where(
                            OfficialAccountArticleVersionModel.id.in_(article_ids)
                        )
                    )
                )
                if article_ids
                else ()
            )
            article_by_id = {row.id: row for row in articles}
            single_editions = await load_single_edition_deliveries(
                session,
                tuple(
                    (run.id, row.content_fingerprint)
                    for run in runs
                    if run.active_article_version_id is not None
                    and (row := article_by_id.get(run.active_article_version_id)) is not None
                    and row.run_id == run.id
                ),
            )
            media = await _ready_media_for_runs(session, runs)
            drafts = tuple(
                await session.scalars(
                    select(OfficialAccountLocalDraftModel)
                    .where(OfficialAccountLocalDraftModel.run_id.in_(run_ids))
                    .limit(VISIBLE_RUN_LIMIT)
                )
            )
            reviews = tuple(
                await session.scalars(
                    select(OfficialAccountManualReviewModel)
                    .where(OfficialAccountManualReviewModel.run_id.in_(run_ids))
                    .limit(VISIBLE_RUN_LIMIT)
                )
            )
            active_render_ids = tuple(
                run.active_render_version_id
                for run in runs
                if run.active_render_version_id is not None
            )
            visual_evals = (
                tuple(
                    await session.scalars(
                        select(OfficialAccountGeneratedVisualEvalModel)
                        .join(
                            OfficialAccountGeneratedVisualModel,
                            and_(
                                OfficialAccountGeneratedVisualEvalModel.generated_visual_id
                                == OfficialAccountGeneratedVisualModel.id,
                                OfficialAccountGeneratedVisualEvalModel.run_id
                                == OfficialAccountGeneratedVisualModel.run_id,
                                OfficialAccountGeneratedVisualEvalModel.publication_sha256
                                == OfficialAccountGeneratedVisualModel.sha256,
                            ),
                        )
                        .where(
                            OfficialAccountGeneratedVisualModel.run_id.in_(run_ids),
                            OfficialAccountGeneratedVisualModel.render_version_id.in_(
                                active_render_ids
                            ),
                        )
                        .order_by(
                            OfficialAccountGeneratedVisualEvalModel.run_id,
                            OfficialAccountGeneratedVisualEvalModel.completed_at,
                        )
                        .limit(VISIBLE_RUN_LIMIT * 5)
                    )
                )
                if active_render_ids
                else ()
            )
            article_fingerprints = tuple(row.content_fingerprint for row in articles)
            if article_fingerprints:
                count_rows = (
                    await session.execute(
                        select(
                            WeChatOfficialAccountDraftItemModel.article_fingerprint,
                            func.count(),
                        )
                        .where(
                            WeChatOfficialAccountDraftItemModel.article_fingerprint.in_(
                                article_fingerprints
                            )
                        )
                        .group_by(WeChatOfficialAccountDraftItemModel.article_fingerprint)
                    )
                ).all()
                wechat_match_counts = {fingerprint: int(count) for fingerprint, count in count_rows}
                unique_fingerprints = tuple(
                    fingerprint for fingerprint, count in wechat_match_counts.items() if count == 1
                )
                wechat_items = (
                    tuple(
                        await session.scalars(
                            select(WeChatOfficialAccountDraftItemModel)
                            .where(
                                WeChatOfficialAccountDraftItemModel.article_fingerprint.in_(
                                    unique_fingerprints
                                )
                            )
                            .limit(VISIBLE_RUN_LIMIT)
                        )
                    )
                    if unique_fingerprints
                    else ()
                )
            else:
                wechat_match_counts = {}
                wechat_items = ()

        bundles: list[VisitorDisplayRunBundle] = []
        for run in runs:
            article = (
                article_by_id.get(run.active_article_version_id)
                if run.active_article_version_id is not None
                else None
            )
            bundles.append(
                VisitorDisplayRunBundle(
                    run=run,
                    article=article,
                    media=tuple(
                        row
                        for row in media
                        if row.run_id == run.id
                        and row.render_version_id == run.active_render_version_id
                    ),
                    draft=next((row for row in drafts if row.run_id == run.id), None),
                    review=next((row for row in reviews if row.run_id == run.id), None),
                    visual_evals=tuple(row for row in visual_evals if row.run_id == run.id),
                    wechat_items=tuple(
                        row
                        for row in wechat_items
                        if article is not None
                        and row.article_fingerprint == article.content_fingerprint
                    ),
                    wechat_match_count=(
                        wechat_match_counts.get(article.content_fingerprint, 0)
                        if article is not None
                        else 0
                    ),
                    single_editions=tuple(
                        row for row in single_editions if row.article_run_id == run.id
                    ),
                )
            )
        return tuple(bundles)

    async def _cached(
        self,
        name: str,
        ttl: float,
        load: Callable[[AsyncSession], Awaitable[T]],
        *,
        day: date | None = None,
    ) -> T:
        entry = _CACHE.setdefault(self._session_factory, {}).get(name)
        if entry is not None and entry.day == day:
            age = time.monotonic() - entry.loaded_at
            if age < ttl:
                return entry.value  # type: ignore[no-any-return]
            if age < _STALE_SERVE_SECONDS:
                # A refresh reads production through the tunnel and can take several seconds,
                # while every screen polls with a short timeout. Answer with the last result
                # and refresh behind it, so one slow read never shows as a lost connection.
                self._refresh_in_background(name, load, day)
                return entry.value  # type: ignore[no-any-return]
        return await self._load_into_cache(name, load, day)

    async def _load_into_cache(
        self,
        name: str,
        load: Callable[[AsyncSession], Awaitable[T]],
        day: date | None,
    ) -> T:
        async with self._session_factory() as session:
            value = await load(session)
        _CACHE.setdefault(self._session_factory, {})[name] = _CacheEntry(
            time.monotonic(), day, value
        )
        return value

    def _refresh_in_background(
        self,
        name: str,
        load: Callable[[AsyncSession], Awaitable[T]],
        day: date | None,
    ) -> None:
        running = _REFRESHING.setdefault(self._session_factory, {})
        if name in running:
            return

        async def refresh() -> None:
            try:
                await asyncio.wait_for(
                    self._load_into_cache(name, load, day), _REFRESH_TIMEOUT_SECONDS
                )
            except Exception as error:
                # Only the kind of read and the exception class: never SQL or settings.
                _LOGGER.warning("visitor cache refresh failed: %s %s", name, type(error).__name__)
            finally:
                running.pop(name, None)

        running[name] = asyncio.get_running_loop().create_task(refresh())

    async def load_news_pool(self) -> tuple[VisitorNewsPoolBatch, ...]:
        return await self._cached("news_pool", _NEWS_POOL_TTL_SECONDS, load_news_pool)

    async def load_human_picks(self, *, now: datetime) -> tuple[VisitorHumanPickRow, ...]:
        # Uncached: an operator watches this right after pressing the button.
        async with self._session_factory() as session:
            return await load_human_picks(session, now=now)

    async def load_human_pick_review(
        self, *, event_id: UUID, now: datetime
    ) -> VisitorHumanPickReviewRow | None:
        # Uncached: the operator edits and pushes against the current copy.
        async with self._session_factory() as session:
            return await load_human_pick_review(session, event_id=event_id, now=now)

    async def load_moments(self) -> tuple[VisitorMomentRow, ...]:
        # Short cache: the snapshot and each image request resolve against the same posts.
        return await self._cached("moments", _MOMENT_TTL_SECONDS, load_moments)

    async def load_issue_signals(self, *, today: date) -> tuple[VisitorIssueSignal, ...]:
        return await self._cached(
            "issue_signals",
            _REPORT_TTL_SECONDS,
            lambda session: load_issue_signals(session, today=today),
            day=today,
        )

    async def load_report(self, *, today: date) -> tuple[VisitorReportDay, ...]:
        return await self._cached(
            "report",
            _REPORT_TTL_SECONDS,
            lambda session: load_report_days(session, today=today),
            day=today,
        )


async def load_news_pool(session: AsyncSession) -> tuple[VisitorNewsPoolBatch, ...]:
    """Read the newest completed batch per business date and slot with every scored candidate.

    Rejected candidates are part of the persisted scoring record; nothing here selects,
    re-scores or writes. Candidate rows are bounded per batch by their stored rank.
    """
    scanned = tuple(
        await session.scalars(
            select(ContentSlotRunModel)
            .where(
                ContentSlotRunModel.status == "succeeded",
                # Extra human-pick runs never stand in for a slot's regular scoring batch.
                ContentSlotRunModel.trigger.in_(SLOT_BATCH_TRIGGERS),
            )
            .order_by(
                ContentSlotRunModel.target_at.desc(),
                ContentSlotRunModel.completed_at.desc(),
                ContentSlotRunModel.id.desc(),
            )
            .limit(_NEWS_POOL_RUN_SCAN_LIMIT)
        )
    )
    runs: list[ContentSlotRunModel] = []
    seen: set[tuple[date, str]] = set()
    for run in scanned:
        identity = (run.business_date, run.content_slot)
        if identity in seen:
            continue
        seen.add(identity)
        runs.append(run)
        if len(runs) == NEWS_POOL_BATCH_LIMIT:
            break
    if not runs:
        return ()
    run_ids = tuple(run.id for run in runs)
    title = EventClusterVersionModel.representative_title
    # Past the rank cut-off, keep only central policy documents, at most N per batch.
    policy_extras = (
        select(
            ContentSlotScoreModel.run_id.label("run_id"),
            ContentSlotScoreModel.event_id.label("event_id"),
            func.row_number()
            .over(
                partition_by=ContentSlotScoreModel.run_id,
                order_by=ContentSlotScoreModel.rank,
            )
            .label("extra_rank"),
        )
        .join(
            EventClusterVersionModel,
            EventClusterVersionModel.id == ContentSlotScoreModel.event_version_id,
        )
        .where(
            ContentSlotScoreModel.run_id.in_(run_ids),
            ContentSlotScoreModel.rank > NEWS_POOL_CANDIDATE_LIMIT,
            title.op("~")(_POLICY_ISSUER_REGEX),
            title.op("~")(_POLICY_DOCUMENT_REGEX),
            title.op("~")(_POLICY_SUBJECT_REGEX),
            ~title.op("~")(_POLICY_EXCLUDED_REGEX),
        )
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                ContentSlotScoreModel.run_id,
                ContentSlotScoreModel.event_id,
                ContentSlotScoreModel.total,
                ContentSlotScoreModel.threshold,
                ContentSlotScoreModel.passes_threshold,
                ContentSlotScoreModel.eligible,
                ContentSlotScoreModel.veto_codes,
                ContentSlotScoreModel.same_day_excluded,
                ContentSlotScoreModel.same_day_exclusion_reason,
                ContentSlotScoreModel.rank,
                ContentSlotScoreModel.selected_ordinal,
                ContentSlotScoreModel.normalized_features,
                ContentSlotScoreModel.weights,
                ContentSlotScoreModel.penalty_weights,
                EventClusterVersionModel.representative_title,
                EvidenceCandidateModel.canonical_url,
                EvidenceCandidateModel.trust_tier,
                EvidenceCandidateModel.published_at,
                EvidenceCandidateModel.clean_text,
                SourceModel.display_name,
            )
            .join(
                EventClusterVersionModel,
                EventClusterVersionModel.id == ContentSlotScoreModel.event_version_id,
            )
            .outerjoin(
                NormalizedArticleModel,
                NormalizedArticleModel.id == EventClusterVersionModel.representative_article_id,
            )
            .outerjoin(
                EvidenceCandidateModel,
                EvidenceCandidateModel.id == NormalizedArticleModel.candidate_id,
            )
            .outerjoin(SourceModel, SourceModel.id == EvidenceCandidateModel.source_id)
            .where(
                ContentSlotScoreModel.run_id.in_(run_ids),
                or_(
                    ContentSlotScoreModel.rank <= NEWS_POOL_CANDIDATE_LIMIT,
                    tuple_(ContentSlotScoreModel.run_id, ContentSlotScoreModel.event_id).in_(
                        select(policy_extras.c.run_id, policy_extras.c.event_id).where(
                            policy_extras.c.extra_rank <= NEWS_POOL_POLICY_EXTRA_LIMIT
                        )
                    ),
                ),
            )
            .order_by(ContentSlotScoreModel.run_id, ContentSlotScoreModel.rank)
            .limit(
                NEWS_POOL_BATCH_LIMIT * (NEWS_POOL_CANDIDATE_LIMIT + NEWS_POOL_POLICY_EXTRA_LIMIT)
            )
        )
    ).mappings()
    candidates: dict[UUID, list[VisitorNewsPoolCandidate]] = {run.id: [] for run in runs}
    for row in rows:
        candidates[row["run_id"]].append(
            VisitorNewsPoolCandidate(
                event_id=row["event_id"],
                title=row["representative_title"],
                source_name=row["display_name"],
                source_url=row["canonical_url"],
                trust_tier=row["trust_tier"],
                published_at=row["published_at"],
                snippet=_snippet(row["clean_text"]),
                total=float(row["total"]),
                threshold=float(row["threshold"]),
                passes_threshold=bool(row["passes_threshold"]),
                eligible=bool(row["eligible"]),
                veto_codes=tuple(_strings(row["veto_codes"])),
                same_day_excluded=bool(row["same_day_excluded"]),
                same_day_exclusion_reason=row["same_day_exclusion_reason"],
                rank=int(row["rank"]),
                selected_ordinal=row["selected_ordinal"],
                normalized_features=_mapping(row["normalized_features"]),
                weights=_mapping(row["weights"]),
                penalty_weights=_mapping(row["penalty_weights"]),
            )
        )
    return tuple(
        VisitorNewsPoolBatch(
            business_date=run.business_date,
            content_slot=run.content_slot,
            target_at=run.target_at,
            total_scores=run.total_scores,
            eligible_scores=run.eligible_scores,
            selected_count=run.selected_count,
            unfilled_reason_codes=tuple(_strings(run.unfilled_reason_codes)),
            candidates=tuple(candidates[run.id]),
            run_id=run.id,
        )
        for run in runs
    )


async def load_human_picks(
    session: AsyncSession, *, now: datetime
) -> tuple[VisitorHumanPickRow, ...]:
    """Recent human picks and the newest downstream row of each stage; nothing is written."""
    picks = (
        await session.execute(
            select(
                ContentSlotSelectionModel.id,
                ContentSlotSelectionModel.selected_event_id,
                ContentSlotRunModel.target_at,
                ContentSlotRunModel.expires_at,
            )
            .join(ContentSlotRunModel, ContentSlotRunModel.id == ContentSlotSelectionModel.run_id)
            .where(
                ContentSlotRunModel.trigger == HUMAN_PICK_TRIGGER,
                ContentSlotRunModel.created_at >= now - HUMAN_PICK_LOOKBACK,
            )
            .order_by(ContentSlotRunModel.created_at.desc())
            .limit(HUMAN_PICK_LIMIT)
        )
    ).all()
    if not picks:
        return ()
    selection_ids = [row[0] for row in picks]
    copies = {
        row[0]: row
        for row in (
            await session.execute(
                select(
                    CopyGenerationRunModel.content_slot_selection_id,
                    CopyGenerationRunModel.id,
                    CopyGenerationRunModel.status,
                    CopyGenerationRunModel.error_code,
                ).where(CopyGenerationRunModel.content_slot_selection_id.in_(selection_ids))
            )
        ).all()
    }
    packages = _newest_by_owner(
        (
            await session.execute(
                select(
                    MaterialPackageModel.run_id,
                    MaterialPackageModel.id,
                    MaterialPackageModel.status,
                    MaterialPackageModel.review_status,
                )
                .where(MaterialPackageModel.run_id.in_([row[1] for row in copies.values()]))
                .order_by(MaterialPackageModel.created_at, MaterialPackageModel.id)
            )
        ).all()
    )
    deliveries = _newest_by_owner(
        (
            await session.execute(
                select(
                    WeComDeliveryJobModel.material_package_id,
                    WeComDeliveryJobModel.status,
                    WeComDeliveryJobModel.last_error_code,
                )
                .where(
                    WeComDeliveryJobModel.material_package_id.in_(
                        [row[1] for row in packages.values()]
                    ),
                    WeComDeliveryJobModel.mode == "formal",
                )
                .order_by(WeComDeliveryJobModel.created_at, WeComDeliveryJobModel.id)
            )
        ).all()
    )
    infographics = _newest_by_owner(
        (
            await session.execute(
                select(
                    NewsInfographicJobModel.content_slot_selection_id,
                    NewsInfographicJobModel.id,
                    NewsInfographicJobModel.status,
                )
                .where(NewsInfographicJobModel.content_slot_selection_id.in_(selection_ids))
                .order_by(NewsInfographicJobModel.created_at, NewsInfographicJobModel.id)
            )
        ).all()
    )
    supplements = _newest_by_owner(
        (
            await session.execute(
                select(
                    WeComInfographicSupplementModel.infographic_job_id,
                    WeComInfographicSupplementModel.status,
                )
                .where(
                    WeComInfographicSupplementModel.infographic_job_id.in_(
                        [row[1] for row in infographics.values()]
                    )
                )
                .order_by(WeComInfographicSupplementModel.created_at)
            )
        ).all()
    )
    rows: list[VisitorHumanPickRow] = []
    for selection_id, event_id, picked_at, expires_at in picks:
        copy = copies.get(selection_id)
        package = packages.get(copy[1]) if copy is not None else None
        delivery = deliveries.get(package[1]) if package is not None else None
        infographic = infographics.get(selection_id)
        supplement = supplements.get(infographic[1]) if infographic is not None else None
        rows.append(
            VisitorHumanPickRow(
                event_id=event_id,
                picked_at=picked_at,
                expires_at=expires_at,
                copy_status=copy[2] if copy is not None else None,
                copy_error=copy[3] if copy is not None else None,
                package_status=package[2] if package is not None else None,
                package_review_status=package[3] if package is not None else None,
                delivery_status=delivery[1] if delivery is not None else None,
                delivery_error=delivery[2] if delivery is not None else None,
                infographic_status=infographic[2] if infographic is not None else None,
                supplement_status=supplement[1] if supplement is not None else None,
            )
        )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class VisitorHumanPickReviewRow:
    """What the operator reviews for one held pick (PIN-gated; never in the snapshot)."""

    run_id: UUID
    picked_at: datetime
    expires_at: datetime
    copywriting: str | None
    issues: tuple[dict[str, Any], ...]
    package_review_status: str | None
    pushed: bool


async def load_human_pick_review(
    session: AsyncSession, *, event_id: UUID, now: datetime
) -> VisitorHumanPickReviewRow | None:
    """The newest recent human pick of ``event_id`` with its current copy; read-only."""
    pick = (
        await session.execute(
            select(
                ContentSlotRunModel.id,
                ContentSlotRunModel.target_at,
                ContentSlotRunModel.expires_at,
                ContentSlotSelectionModel.id,
            )
            .join(
                ContentSlotSelectionModel,
                ContentSlotSelectionModel.run_id == ContentSlotRunModel.id,
            )
            .where(
                ContentSlotRunModel.trigger == HUMAN_PICK_TRIGGER,
                ContentSlotRunModel.created_at >= now - HUMAN_PICK_LOOKBACK,
                ContentSlotSelectionModel.selected_event_id == event_id,
            )
            .order_by(ContentSlotRunModel.created_at.desc())
            .limit(1)
        )
    ).first()
    if pick is None:
        return None
    run_id, picked_at, expires_at, selection_id = pick
    package = await session.scalar(
        select(MaterialPackageModel)
        .join(CopyGenerationRunModel, CopyGenerationRunModel.id == MaterialPackageModel.run_id)
        .where(CopyGenerationRunModel.content_slot_selection_id == selection_id)
        .order_by(MaterialPackageModel.created_at.desc())
        .limit(1)
    )
    if package is None:
        return VisitorHumanPickReviewRow(run_id, picked_at, expires_at, None, (), None, False)
    pushed = (
        await session.scalar(
            select(WeComDeliveryJobModel.id)
            .where(
                WeComDeliveryJobModel.material_package_id == package.id,
                WeComDeliveryJobModel.mode == "formal",
            )
            .limit(1)
        )
    ) is not None
    copywriting = package.copy_snapshot.get("copywriting")
    raw_issues = package.validation_snapshot.get("issues")
    issues = tuple(
        issue
        for issue in (raw_issues if isinstance(raw_issues, list) else ())
        if isinstance(issue, dict)
    )
    return VisitorHumanPickReviewRow(
        run_id=run_id,
        picked_at=picked_at,
        expires_at=expires_at,
        copywriting=copywriting if isinstance(copywriting, str) else None,
        issues=issues,
        package_review_status=package.review_status,
        pushed=pushed,
    )


def _newest_by_owner(rows: Any) -> dict[Any, Any]:
    """Rows are ordered oldest first; the last row per owner (first column) wins."""
    return {row[0]: row for row in rows}


def _snippet(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return (
        " ".join(value[: _NEWS_SNIPPET_CHARACTERS * 2].split())[:_NEWS_SNIPPET_CHARACTERS] or None
    )


def _strings(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


async def load_single_edition_deliveries(
    session: AsyncSession,
    identities: tuple[tuple[UUID, str], ...],
) -> tuple[VisitorDisplaySingleEdition, ...]:
    """Read exact owners, counting *before* bounding rows; never pick a winner.

    The existence probe is a SELECT so an absent optional table does not abort
    the transaction. Permission, column and all other SQL errors still propagate.
    """
    if len(identities) > VISIBLE_RUN_LIMIT or len({run_id for run_id, _ in identities}) != len(
        identities
    ):
        raise ValueError("visitor display single-edition scope is invalid")
    if not identities:
        return ()
    if (
        await session.scalar(select(func.to_regclass("public.official_account_single_editions")))
        is None
    ):
        return ()
    partition = (_SINGLE_EDITIONS.c.article_run_id, _SINGLE_EDITIONS.c.article_fingerprint)
    ranked = (
        select(
            *_SINGLE_EDITIONS.c,
            func.count().over(partition_by=partition).label("match_count"),
            func.row_number().over(partition_by=partition).label("visitor_rank"),
        )
        .where(tuple_(*partition).in_(identities))
        .subquery()
    )
    rows = (
        await session.execute(
            select(*(ranked.c[name] for name in _SINGLE_EDITIONS.c.keys()), ranked.c.match_count)
            .where(ranked.c.visitor_rank == 1)
            .limit(VISIBLE_RUN_LIMIT)
        )
    ).mappings()
    return tuple(VisitorDisplaySingleEdition(**row) for row in rows)


async def load_visible_ready_media(
    session: AsyncSession,
) -> tuple[OfficialAccountLocalMediaModel, ...]:
    runs = await _latest_live_runs(session)
    if not runs:
        return ()
    return await _ready_media_for_runs(session, runs)


async def _ready_media_for_runs(
    session: AsyncSession,
    runs: tuple[OfficialAccountArticleRunModel, ...],
) -> tuple[OfficialAccountLocalMediaModel, ...]:
    """Return at most eight safe, active-render media rows for each visible run."""

    run_ids = tuple(run.id for run in runs)
    active_render_ids = tuple(
        run.active_render_version_id for run in runs if run.active_render_version_id is not None
    )
    if not active_render_ids:
        return ()
    role_order = case(
        (OfficialAccountLocalMediaModel.role == "cover", 0),
        (OfficialAccountLocalMediaModel.role == "body", 1),
        else_=2,
    )
    ranked = (
        select(
            OfficialAccountLocalMediaModel.id.label("media_id"),
            func.row_number()
            .over(
                partition_by=OfficialAccountLocalMediaModel.run_id,
                order_by=(
                    role_order,
                    OfficialAccountLocalMediaModel.ordinal,
                    OfficialAccountLocalMediaModel.id,
                ),
            )
            .label("visitor_rank"),
        )
        .where(
            OfficialAccountLocalMediaModel.run_id.in_(run_ids),
            OfficialAccountLocalMediaModel.render_version_id.in_(active_render_ids),
            OfficialAccountLocalMediaModel.status == "ready",
            OfficialAccountLocalMediaModel.media_type.in_(
                ("image/jpeg", "image/png", "image/webp")
            ),
        )
        .subquery()
    )
    return tuple(
        await session.scalars(
            select(OfficialAccountLocalMediaModel)
            .join(ranked, ranked.c.media_id == OfficialAccountLocalMediaModel.id)
            .where(ranked.c.visitor_rank <= 8)
            .order_by(
                OfficialAccountLocalMediaModel.run_id,
                role_order,
                OfficialAccountLocalMediaModel.ordinal,
            )
            .limit(VISIBLE_MEDIA_LIMIT)
        )
    )


async def _latest_live_runs(
    session: AsyncSession,
) -> tuple[OfficialAccountArticleRunModel, ...]:
    return tuple(
        await session.scalars(
            select(OfficialAccountArticleRunModel)
            .where(OfficialAccountArticleRunModel.generation_mode == "live")
            .order_by(
                OfficialAccountArticleRunModel.updated_at.desc(),
                OfficialAccountArticleRunModel.created_at.desc(),
                OfficialAccountArticleRunModel.id.desc(),
            )
            .limit(VISIBLE_RUN_LIMIT)
        )
    )


__all__ = [
    "PostgresVisitorDisplayRepository",
    "VisitorDisplayRunBundle",
    "VisitorDisplaySingleEdition",
    "VisitorHumanPickRow",
    "VisitorNewsPoolBatch",
    "VisitorNewsPoolCandidate",
    "load_human_picks",
    "load_news_pool",
    "load_single_edition_deliveries",
    "load_visible_ready_media",
]
