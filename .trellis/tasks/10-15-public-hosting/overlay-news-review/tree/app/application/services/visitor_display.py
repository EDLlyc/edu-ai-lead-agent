"""Public-safe, read-only projection for the large-screen visitor exhibit."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import math
import re
from collections.abc import Iterable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.application.services.visitor_improvement import project_improvement
from app.application.services.visitor_moments import project_moments
from app.core.errors import ConflictError, NotFoundError
from app.domain.official_account_local import (
    ArticleBulletListBlock,
    ArticleImageBlock,
    ArticlePackage,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleVersionModel,
    OfficialAccountLocalMediaModel,
)
from app.infrastructure.db.visitor_display import (
    PostgresVisitorDisplayRepository,
    VisitorDisplayRunBundle,
    VisitorDisplaySingleEdition,
    VisitorHumanPickRow,
    VisitorNewsPoolBatch,
    VisitorNewsPoolCandidate,
)
from app.infrastructure.db.visitor_improvement import improvement_window
from app.infrastructure.db.visitor_report import REPORT_TIMEZONE
from app.infrastructure.visitor_review_store import NewsReviewStore, StoredNewsReview
from app.schemas.visitor_display import (
    VisitorDisplayArticle,
    VisitorDisplayEvidence,
    VisitorDisplayExcerpt,
    VisitorDisplayHumanPick,
    VisitorDisplayHumanReview,
    VisitorDisplayImprovement,
    VisitorDisplayMoment,
    VisitorDisplayNewsBatch,
    VisitorDisplayNewsCandidate,
    VisitorDisplayNewsPool,
    VisitorDisplayReport,
    VisitorDisplayReportDay,
    VisitorDisplayScoreDimension,
    VisitorDisplaySnapshot,
    VisitorDisplaySource,
    VisitorDisplayTimelineItem,
    VisitorDisplayVisual,
    VisitorStageState,
)

_MEDIA_REF_PREFIX = "vd1_"
_MEDIA_REF_DOMAIN = b"edu-ai-visitor-display-media-v1\0"
_ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_PREPARED_CHILD_TYPES = frozenset(
    {
        "application/vnd.wechat.prepared-draft-child+directory",
        "application/vnd.wechat.approved-catalog-fallback-child+directory",
    }
)
_LOGGER = logging.getLogger(__name__)
_NEWS_KEY_PREFIX = "vn1_"
_NEWS_KEY_DOMAIN = b"edu-ai-visitor-news-v1\0"
_VETO_REASONS = frozenset(
    {
        "unresolved_governance",
        "ineligible_evidence",
        "tier_c_only",
        "unverified",
        "unsuitable_negative_incident",
        "privacy_legal_safety_uncertain",
        "prohibited_marketing_risk",
        "repeated_within_window",
        "stale_event",
        "outside_science_ai_education_scope",
    }
)
_UNFILLED_REASONS = frozenset(
    {
        "no_candidates",
        "all_vetoed",
        "below_threshold",
        "same_day_already_selected",
        "insufficient_eligible_candidates",
    }
)
_POSITIVE_DIMENSIONS = (
    "science_education_relevance",
    "editorial_priority",
    "product_matrix_fit",
    "ai_relevance",
    "parent_relevance",
    "source_trust",
    "freshness",
    "communication_potential",
    "source_diversity",
)
_PENALTY_DIMENSIONS = ("theme_repetition", "controversy_risk", "marketing_risk")
_SLOTS = frozenset({"morning", "noon", "evening"})
_RUN_STATES = frozenset(
    {"queued", "running", "review_required", "ready", "failed", "result_unknown"}
)
_RUN_STAGES = frozenset(
    {
        "queued",
        "generating",
        "validating",
        "auditing",
        "rendering",
        "generating_body_visuals",
        "staging_body_media",
        "staging_cover",
        "creating_local_draft",
        "ready",
        "review_required",
        "failed",
        "result_unknown",
    }
)


class VisitorDisplayService:
    def __init__(
        self,
        *,
        repository: PostgresVisitorDisplayRepository,
        asset_secret: str,
        reviews: NewsReviewStore | None = None,
        human_picks_enabled: bool = False,
    ) -> None:
        if len(asset_secret.strip().encode("utf-8")) < 32:
            raise ValueError("visitor display asset secret is too short")
        self._repository = repository
        self._asset_secret = asset_secret.strip()
        self._reviews = reviews
        self._human_picks_enabled = human_picks_enabled

    async def snapshot(self, *, now: datetime | None = None) -> VisitorDisplaySnapshot:
        observed_at = now or datetime.now(UTC)
        bundles = await self._repository.load_latest()
        articles = [self._project_article(bundle) for bundle in bundles]
        return VisitorDisplaySnapshot(
            observed_at=observed_at,
            state="live" if articles else "empty",
            articles=articles,
            news_pool=await self._news_pool_or_none(),
            report=await self._report_or_none(observed_at),
            improvement=await self._improvement_or_none(observed_at),
            moments=await self._moments_or_none(),
        )

    async def news_pool(self) -> VisitorDisplayNewsPool:
        batches = project_news_pool(await self._repository.load_news_pool())
        picks = await self._human_picks()
        latest = (
            {}
            if self._reviews is None
            else await self._reviews.latest(
                candidate.key for batch in batches for candidate in batch.candidates
            )
        )
        return VisitorDisplayNewsPool(
            review_enabled=self._reviews is not None,
            human_pick_enabled=self._human_picks_enabled,
            batches=[
                batch.model_copy(
                    update={
                        "candidates": [
                            candidate.model_copy(
                                update={
                                    "human_review": _human_review(latest.get(candidate.key)),
                                    "human_pick": picks.get(candidate.key),
                                }
                            )
                            for candidate in batch.candidates
                        ]
                    }
                )
                for batch in batches
            ],
        )

    async def find_news_source(self, key: str) -> tuple[UUID, UUID] | None:
        """Resolve a human-pick target to its persisted (AI run, event), never client input."""
        for batch in await self._repository.load_news_pool():
            for candidate in batch.candidates:
                if batch.run_id is not None and hmac.compare_digest(
                    news_key(candidate.event_id), key
                ):
                    return batch.run_id, candidate.event_id
        return None

    async def _human_picks(self) -> dict[str, VisitorDisplayHumanPick]:
        # Only the operator adapter with a production API tunnel shows human-pick progress.
        # The chips are secondary; a failed read hides them instead of the pool.
        if not self._human_picks_enabled:
            return {}
        now = datetime.now(UTC)
        try:
            rows = await self._repository.load_human_picks(now=now)
        except SQLAlchemyError as error:
            _log_unavailable("human picks", error)
            return {}
        picks: dict[str, VisitorDisplayHumanPick] = {}
        for row in rows:  # newest first
            picks.setdefault(news_key(row.event_id), project_human_pick(row, now=now))
        return picks

    async def find_news_candidate(
        self, key: str
    ) -> tuple[VisitorDisplayNewsBatch, VisitorDisplayNewsCandidate] | None:
        """Resolve a review target against the current persisted pool, never client input."""
        for batch in project_news_pool(await self._repository.load_news_pool()):
            for candidate in batch.candidates:
                if hmac.compare_digest(candidate.key, key):
                    return batch, candidate
        return None

    async def _news_pool_or_none(self) -> VisitorDisplayNewsPool | None:
        # Article truth is the primary exhibit; an unreadable scoring history must not
        # take it down. The pool is simply absent rather than invented.
        try:
            return await self.news_pool()
        except SQLAlchemyError as error:
            _log_unavailable("news pool", error)
            return None

    async def report(self, *, now: datetime | None = None) -> VisitorDisplayReport:
        generated_at = now or datetime.now(UTC)
        today = generated_at.astimezone(ZoneInfo(REPORT_TIMEZONE)).date()
        days = await self._repository.load_report(today=today)
        if self._reviews is not None:
            counts = await self._reviews.daily_counts(
                tuple(item.day for item in days), timezone=REPORT_TIMEZONE
            )
            days = tuple(
                replace(
                    item,
                    human_reviews=counts.get(item.day, (0, 0))[0],
                    human_disagreements=counts.get(item.day, (0, 0))[1],
                )
                for item in days
            )
        return VisitorDisplayReport(
            generated_at=generated_at,
            days=[VisitorDisplayReportDay(**asdict(item)) for item in days],
        )

    async def _report_or_none(self, now: datetime) -> VisitorDisplayReport | None:
        # Like the pool, statistics never take down article truth.
        try:
            return await self.report(now=now)
        except SQLAlchemyError as error:
            _log_unavailable("report", error)
            return None

    async def improvement(self, *, now: datetime | None = None) -> VisitorDisplayImprovement:
        generated_at = now or datetime.now(UTC)
        today = generated_at.astimezone(ZoneInfo(REPORT_TIMEZONE)).date()
        signals = await self._repository.load_issue_signals(today=today)
        human_days = (
            {}
            if self._reviews is None
            else await self._reviews.daily_decisions(
                improvement_window(today), timezone=REPORT_TIMEZONE
            )
        )
        return project_improvement(signals, human_days, now=generated_at)

    async def moments(self) -> list[VisitorDisplayMoment]:
        return project_moments(await self._repository.load_moments(), secret=self._asset_secret)

    async def _moments_or_none(self) -> list[VisitorDisplayMoment] | None:
        try:
            return await self.moments()
        except SQLAlchemyError as error:
            _log_unavailable("moments", error)
            return None

    async def _improvement_or_none(self, now: datetime) -> VisitorDisplayImprovement | None:
        try:
            return await self.improvement(now=now)
        except SQLAlchemyError as error:
            _log_unavailable("improvement", error)
            return None

    def _project_article(self, bundle: VisitorDisplayRunBundle) -> VisitorDisplayArticle:
        run = bundle.run
        validate_runtime_state(run.status, run.current_stage)
        article, article_row = _validated_article(bundle)
        sources = _sources(article)
        excerpts = _excerpts(article)
        delivery_state, draft_created, delivery_time = _delivery(bundle, article)
        evidence = _evidence(bundle, article)
        visuals = [
            _visual(row, asset_secret=self._asset_secret)
            for row in bundle.media[:8]
            if row.media_type in _ALLOWED_MEDIA_TYPES
        ]
        title = article.title if article is not None else None
        return VisitorDisplayArticle(
            title=title,
            display_title=title or "内容正在生成",
            digest=article.digest if article is not None else None,
            author=article.author if article is not None else None,
            topic_title=article.topic_title if article is not None else None,
            created_at=run.created_at,
            updated_at=run.updated_at,
            run_state=cast(Any, run.status),
            current_stage=cast(Any, run.current_stage),
            attempt_count=min(max(run.attempt_count, 0), 100),
            delivery_state=delivery_state,
            draft_created=draft_created,
            sources=sources,
            excerpts=excerpts,
            evidence=evidence,
            visuals=visuals,
            timeline=_timeline(
                bundle,
                article_present=article is not None,
                article_created_at=article_row.created_at if article_row is not None else None,
                evidence=evidence,
                visual_count=len(visuals),
                delivery_state=delivery_state,
                delivery_time=delivery_time,
            ),
        )


def _log_unavailable(what: str, error: SQLAlchemyError) -> None:
    # Type, SQLSTATE and the server's first message line only: never the statement,
    # parameters or connection details.
    original = getattr(error, "orig", None)
    _LOGGER.warning(
        "visitor %s unavailable: %s sqlstate=%s %s",
        what,
        type(error).__name__,
        getattr(original, "sqlstate", None),
        str(original).splitlines()[0][:200] if original is not None else "",
    )


def news_key(event_id: UUID) -> str:
    """Stable, non-reversible public reference for one news event across restarts."""
    return _NEWS_KEY_PREFIX + hashlib.sha256(_NEWS_KEY_DOMAIN + event_id.bytes).hexdigest()[:24]


def project_news_pool(
    batches: Iterable[VisitorNewsPoolBatch],
) -> list[VisitorDisplayNewsBatch]:
    result: list[VisitorDisplayNewsBatch] = []
    for batch in batches:
        if batch.content_slot not in _SLOTS:
            continue
        candidates = [
            projected for row in batch.candidates if (projected := _news_candidate(row)) is not None
        ]
        result.append(
            VisitorDisplayNewsBatch(
                business_date=batch.business_date,
                slot=cast(Literal["morning", "noon", "evening"], batch.content_slot),
                target_at=batch.target_at,
                total_count=min(max(batch.total_scores, 0), 10_000),
                eligible_count=min(max(batch.eligible_scores, 0), 10_000),
                selected_count=sum(item.verdict == "selected" for item in candidates),
                unfilled_reasons=cast(
                    Any,
                    [
                        code
                        for code in dict.fromkeys(batch.unfilled_reason_codes)
                        if code in _UNFILLED_REASONS
                    ],
                ),
                candidates=candidates,
            )
        )
    return result


def _news_candidate(row: VisitorNewsPoolCandidate) -> VisitorDisplayNewsCandidate | None:
    title = " ".join(row.title.split())[:200]
    if not title:
        return None
    selected = row.selected_ordinal is not None and 1 <= row.selected_ordinal <= 3
    snippet = " ".join((row.snippet or "").split())[:200] or None
    source_url = row.source_url if row.source_url and _is_https(row.source_url) else None
    source_name = (row.source_name or "").strip()[:120] or None
    try:
        return VisitorDisplayNewsCandidate(
            key=news_key(row.event_id),
            title=title,
            source_name=source_name,
            source_url=source_url,
            tier_label={"A": "权威来源", "B": "可信来源", "C": "一般来源"}.get(
                row.trust_tier or ""
            ),
            published_at=row.published_at,
            snippet=snippet,
            verdict="selected" if selected else "rejected",
            selected_ordinal=row.selected_ordinal if selected else None,
            rank=row.rank,
            score=round(row.total, 4),
            threshold=round(row.threshold, 4),
            reasons=cast(Any, [] if selected else _rejection_reasons(row)),
            dimensions=_dimensions(row),
        )
    except ValidationError:
        return None


def _rejection_reasons(row: VisitorNewsPoolCandidate) -> list[str]:
    reasons = [code if code in _VETO_REASONS else "other_rule" for code in row.veto_codes]
    if not row.passes_threshold:
        reasons.append("below_threshold")
    if row.same_day_excluded:
        reasons.append("same_day_already_selected")
    if not row.eligible and not row.veto_codes:
        reasons.append("not_eligible")
    if not reasons:
        # Passed every rule but the slot was already filled by higher-ranked news.
        reasons.append("ranked_out")
    return list(dict.fromkeys(reasons))


def _dimensions(row: VisitorNewsPoolCandidate) -> list[VisitorDisplayScoreDimension]:
    result: list[VisitorDisplayScoreDimension] = []
    for kind, keys, weights in (
        ("positive", _POSITIVE_DIMENSIONS, row.weights),
        ("penalty", _PENALTY_DIMENSIONS, row.penalty_weights),
    ):
        for key in keys:
            weight = _unit(weights.get(key))
            value = _unit(row.normalized_features.get(key))
            if weight is None or value is None or weight <= 0:
                continue
            result.append(
                VisitorDisplayScoreDimension(
                    key=cast(Any, key),
                    kind=cast(Literal["positive", "penalty"], kind),
                    value=round(value, 4),
                    weight=round(weight, 4),
                )
            )
    return result


def _unit(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return min(max(number, 0.0), 1.0)


def _is_https(value: str) -> bool:
    from urllib.parse import urlsplit

    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and len(value) <= 2_048
    )


_DELIVERY_STAGES: dict[str, Any] = {
    "delivered": "delivered",
    "partial": "partial",
    "delivery_unknown": "unknown",
    "failed": "failed",
    "cancelled": "expired",
    "delivery_window_expired": "expired",
}
_READY_PACKAGE_STATUSES = frozenset({"ready", "awaiting_manual_use", "completed"})
_IN_PROGRESS_STAGES = frozenset({"queued", "writing", "imaging", "sending"})


def project_human_pick(row: VisitorHumanPickRow, *, now: datetime) -> VisitorDisplayHumanPick:
    """Collapse the newest row of each production stage into one exhibit stage."""
    failure: str | None = None
    if row.delivery_status is not None:
        stage = _DELIVERY_STAGES.get(row.delivery_status, "sending")
        failure = row.delivery_error if stage in {"failed", "partial", "unknown"} else None
    elif row.package_status in {"failed", "rejected"}:
        stage, failure = "failed", f"package_{row.package_status}"
    elif row.package_status in _READY_PACKAGE_STATUSES:
        stage = "sending"
    elif row.package_status is not None or row.copy_status == "accepted":
        stage = "imaging"
    elif row.copy_status in {"review_required", "failed", "no_topic"}:
        stage, failure = "failed", row.copy_error or f"copy_{row.copy_status}"
    elif row.copy_status is not None:
        stage = "writing"
    else:
        stage = "queued"
    if stage in _IN_PROGRESS_STAGES and now >= row.expires_at:
        stage = "expired"
    long_image: Any = None
    if row.supplement_status == "delivered":
        long_image = "sent"
    elif row.supplement_status in {"failed", "result_unknown", "expired"} or (
        row.infographic_status in {"failed", "result_unknown", "expired"}
    ):
        long_image = "failed"
    elif row.infographic_status is not None and row.infographic_status != "skipped":
        long_image = "making"
    return VisitorDisplayHumanPick(
        stage=stage,
        picked_at=row.picked_at,
        failure_code=_safe_code(failure),
        long_image=long_image,
    )


def _safe_code(value: str | None) -> str | None:
    if value is None:
        return None
    code = value.strip().lower()[:80]
    return code if re.fullmatch(r"[a-z0-9_]{1,80}", code) else "unknown_error"


def _human_review(stored: StoredNewsReview | None) -> VisitorDisplayHumanReview | None:
    if stored is None:
        return None
    return VisitorDisplayHumanReview(
        decision=cast(Any, stored.decision),
        note=stored.note,
        reviewed_at=stored.reviewed_at,
    )


def media_asset_ref(*, secret: str, media: OfficialAccountLocalMediaModel) -> str:
    message = _MEDIA_REF_DOMAIN + "\0".join(
        (
            str(media.run_id),
            str(media.id),
            media.role,
            str(media.ordinal),
            media.sha256,
        )
    ).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return _MEDIA_REF_PREFIX + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def resolve_media_asset(
    *,
    secret: str,
    asset_ref: str,
    media: Iterable[OfficialAccountLocalMediaModel],
) -> OfficialAccountLocalMediaModel:
    if not asset_ref.startswith(_MEDIA_REF_PREFIX) or len(asset_ref) != 47:
        raise NotFoundError("visitor display asset")
    matches = tuple(
        row
        for row in media
        if row.media_type in _ALLOWED_MEDIA_TYPES
        and hmac.compare_digest(media_asset_ref(secret=secret, media=row), asset_ref)
    )
    if not matches:
        raise NotFoundError("visitor display asset")
    if len(matches) != 1:
        raise ConflictError("visitor display asset reference is ambiguous")
    return matches[0]


def _validated_article(
    bundle: VisitorDisplayRunBundle,
) -> tuple[ArticlePackage | None, OfficialAccountArticleVersionModel | None]:
    row = bundle.article
    if row is None or row.id != bundle.run.active_article_version_id or row.run_id != bundle.run.id:
        return None, None
    try:
        article = ArticlePackage.model_validate(row.article_payload)
    except ValidationError:
        return None, None
    if article.content_fingerprint != row.content_fingerprint:
        return None, None
    return article, row


def _sources(article: ArticlePackage | None) -> list[VisitorDisplaySource]:
    if article is None:
        return []
    seen: set[str] = set()
    result: list[VisitorDisplaySource] = []
    for source in article.sources:
        if source.source_url in seen:
            continue
        seen.add(source.source_url)
        tier = "权威来源" if source.source_tier == "A" else "可信来源"
        result.append(
            VisitorDisplaySource(
                name=source.source_name[:120],
                url=source.source_url,
                tier_label=tier,
            )
        )
        if len(result) == 8:
            break
    return result


def _excerpts(article: ArticlePackage | None) -> list[VisitorDisplayExcerpt]:
    if article is None:
        return []
    result: list[VisitorDisplayExcerpt] = []
    for section in article.sections:
        pieces: list[str] = []
        for block in section.blocks:
            if isinstance(block, ArticleImageBlock):
                continue
            if isinstance(block, ArticleBulletListBlock):
                pieces.extend(block.items)
            else:
                pieces.append(block.text)
        body = " ".join(piece.strip() for piece in pieces if piece.strip())[:800].strip()
        if body:
            result.append(VisitorDisplayExcerpt(heading=section.heading, body=body))
        if len(result) == 3:
            break
    return result


def _evidence(
    bundle: VisitorDisplayRunBundle,
    article: ArticlePackage | None,
) -> VisitorDisplayEvidence:
    if article is None:
        state = _missing_artifact_state(bundle.run.status)
        return VisitorDisplayEvidence(
            external_fact_count=0,
            bound_external_fact_count=0,
            validation=state,
            audit=state,
            review="pending" if state in {"pending", "running"} else state,
        )
    external = tuple(claim for claim in article.claims if claim.kind == "external_fact")
    validation: VisitorStageState = (
        "passed" if article.quality.inherited_copy_validation_passed else "failed"
    )
    audit: VisitorStageState = (
        "passed" if article.quality.inherited_copy_audit_accepted else "failed"
    )
    if bundle.review is None:
        review: VisitorStageState = (
            "review_required" if bundle.run.status == "review_required" else "not_configured"
        )
    else:
        review = "passed" if bundle.review.decision == "approved" else "failed"
    return VisitorDisplayEvidence(
        external_fact_count=len(external),
        bound_external_fact_count=sum(bool(claim.evidence_ids) for claim in external),
        validation=validation,
        audit=audit,
        review=review,
    )


DeliveryState = Literal[
    "not_confirmed",
    "local_handoff",
    "in_progress",
    "created",
    "failed",
    "result_unknown",
]


def _delivery(
    bundle: VisitorDisplayRunBundle,
    article: ArticlePackage | None,
) -> tuple[DeliveryState, bool, datetime | None]:
    # No channel can attribute delivery to missing, replaced or corrupt active
    # content. The application projection is the sole Article decoder.
    if article is None:
        return "not_confirmed", False, None
    items = bundle.wechat_items
    editions = bundle.single_editions
    if editions:
        if len(editions) != 1 or editions[0].match_count != 1 or bundle.wechat_match_count != 0:
            return "not_confirmed", False, None
        edition = editions[0]
        if (
            edition.article_run_id != bundle.run.id
            or edition.article_fingerprint != article.content_fingerprint
        ):
            return "not_confirmed", False, None
        return _single_delivery(edition)
    if bundle.wechat_match_count > 1:
        return "not_confirmed", False, None
    if bundle.wechat_match_count == 1:
        if len(items) != 1:
            return "not_confirmed", False, None
        item = items[0]
        if item.article_fingerprint != article.content_fingerprint:
            return "not_confirmed", False, None
        if item.status == "succeeded":
            return "created", True, item.completed_at
        if item.status in {"pending", "running", "retryable_failed"}:
            return "in_progress", False, item.updated_at
        if item.status == "terminal_failed":
            return "failed", False, item.completed_at
        if item.status == "outcome_unknown":
            return "result_unknown", False, item.completed_at
        return "not_confirmed", False, None
    if bundle.draft is not None and bundle.draft.simulation and bundle.draft.state == "ready":
        return "local_handoff", False, bundle.draft.created_at
    return "not_confirmed", False, None


def _single_delivery(
    edition: VisitorDisplaySingleEdition,
) -> tuple[DeliveryState, bool, datetime | None]:
    if edition.status == "delivered":
        if not (
            _valid_prepared_descriptor(edition.prepared_artifact)
            and _is_sha256(edition.content_fingerprint)
            and _is_sha256(edition.receipt_fingerprint)
        ):
            return "result_unknown", False, edition.updated_at
        # This projects the durable writer receipt, not an independent remote
        # readback. updated_at is the owner's timestamp, not a completion clock.
        return "created", True, edition.updated_at
    if edition.status in {"ready", "delivering"}:
        return "in_progress", False, edition.updated_at
    if edition.status == "outcome_unknown":
        return "result_unknown", False, edition.updated_at
    if edition.status in {"failed", "expired"}:
        return "failed", False, edition.updated_at
    return "not_confirmed", False, None


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _valid_prepared_descriptor(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    fingerprint = value.get("fingerprint")
    media_type = value.get("media_type")
    size = value.get("byte_size")
    return (
        _is_sha256(fingerprint)
        and value.get("opaque_ref") == f"wechat-prepared-child-v1:{fingerprint}"
        and isinstance(media_type, str)
        and media_type in _PREPARED_CHILD_TYPES
        and isinstance(size, int)
        and not isinstance(size, bool)
        and size >= 0
    )


def _visual(
    row: OfficialAccountLocalMediaModel,
    *,
    asset_secret: str,
) -> VisitorDisplayVisual:
    descriptor = row.descriptor if isinstance(row.descriptor, dict) else {}
    source_kind = descriptor.get("source_kind")
    if source_kind == "source_news":
        provenance_label = "来源图片 · 授权状态未核验 · 仅作上下文"
        rights_label = "不是事实证据"
    elif source_kind == "generated_visual":
        provenance_label = "主题插画 · 非新闻现场图"
        rights_label = None
    elif source_kind == "approved_catalog":
        provenance_label = "品牌主题插画 · 非新闻现场图"
        rights_label = None
    else:
        provenance_label = "内容配图 · 非新闻现场图"
        rights_label = None
    raw_alt = descriptor.get("alt_text")
    alt = (
        raw_alt.strip()[:200]
        if isinstance(raw_alt, str) and raw_alt.strip()
        else ("公众号文章封面" if row.role == "cover" else "公众号文章配图")
    )
    return VisitorDisplayVisual(
        url=f"/api/v1/visitor-display/assets/{media_asset_ref(secret=asset_secret, media=row)}",
        alt=alt,
        role=cast(Literal["cover", "body", "context"], row.role),
        provenance_label=provenance_label,
        rights_label=rights_label,
    )


def _timeline(
    bundle: VisitorDisplayRunBundle,
    *,
    article_present: bool,
    article_created_at: datetime | None,
    evidence: VisitorDisplayEvidence,
    visual_count: int,
    delivery_state: DeliveryState,
    delivery_time: datetime | None,
) -> list[VisitorDisplayTimelineItem]:
    run = bundle.run
    missing = _missing_artifact_state(run.status)
    writing_state: VisitorStageState = "passed" if article_present else missing
    review_state: VisitorStageState
    if evidence.validation == "failed" or evidence.audit == "failed" or evidence.review == "failed":
        review_state = "failed"
    elif evidence.review == "review_required":
        review_state = "review_required"
    elif evidence.validation == "passed" and evidence.audit == "passed":
        review_state = "passed" if evidence.review == "passed" else "advisory"
    else:
        review_state = missing
    visual_state, visual_detail = _visual_stage(bundle, visual_count=visual_count)
    delivery_state_map: dict[str, VisitorStageState] = {
        "created": "passed",
        "local_handoff": "advisory",
        "in_progress": "running",
        "failed": "failed",
        "result_unknown": "result_unknown",
        "not_confirmed": missing,
    }
    media_time = max((row.created_at for row in bundle.media), default=None)
    review_time = (
        bundle.review.reviewed_at
        if bundle.review is not None
        else (getattr(bundle.article, "audited_at", None) if bundle.article is not None else None)
    )
    return [
        VisitorDisplayTimelineItem(
            key="source",
            label="可信来源",
            state="passed",
            detail="真实生产任务已绑定来源素材",
            occurred_at=run.created_at,
        ),
        VisitorDisplayTimelineItem(
            key="selection",
            label="选题判断",
            state="passed",
            detail="候选内容已进入受控生产链路",
            occurred_at=run.created_at,
        ),
        VisitorDisplayTimelineItem(
            key="evidence",
            label="事实绑定",
            state=evidence.validation if article_present else missing,
            detail=(
                f"{evidence.bound_external_fact_count}/"
                f"{evidence.external_fact_count} 项外部事实已绑定"
                if article_present
                else "等待文章证据结构"
            ),
            occurred_at=article_created_at,
        ),
        VisitorDisplayTimelineItem(
            key="writing",
            label="结构化写作",
            state=writing_state,
            detail="文章结构已持久化" if article_present else "文章正在生成",
            occurred_at=article_created_at,
        ),
        VisitorDisplayTimelineItem(
            key="review",
            label="编辑审查",
            state=review_state,
            detail="规则、模型与人工状态均按真实记录展示",
            occurred_at=review_time,
        ),
        VisitorDisplayTimelineItem(
            key="visuals",
            label="视觉生产",
            state=visual_state,
            detail=visual_detail,
            occurred_at=media_time,
        ),
        VisitorDisplayTimelineItem(
            key="draft",
            label="微信草稿",
            state=delivery_state_map[delivery_state],
            detail={
                "created": "微信草稿已创建 · 未发布",
                "local_handoff": "仅完成本地交付 · 微信状态未确认",
                "in_progress": (
                    "微信草稿等待创建 · 未发布"
                    if len(bundle.single_editions) == 1
                    and bundle.single_editions[0].status == "ready"
                    else "微信草稿任务处理中 · 未发布"
                ),
                "failed": (
                    "微信草稿任务已过期 · 未发布"
                    if len(bundle.single_editions) == 1
                    and bundle.single_editions[0].status == "expired"
                    else "微信草稿创建失败 · 未发布"
                ),
                "result_unknown": "微信草稿结果未知 · 未发布",
                "not_confirmed": "微信草稿状态未确认 · 未发布",
            }[delivery_state],
            occurred_at=delivery_time,
        ),
    ]


def _visual_stage(
    bundle: VisitorDisplayRunBundle, *, visual_count: int
) -> tuple[VisitorStageState, str]:
    decisions = {row.decision for row in bundle.visual_evals}
    if "rejected" in decisions:
        return "failed", "图片模型审查未通过"
    if "manual_review" in decisions:
        return "review_required", "图片模型审查要求人工复核"
    if "unavailable" in decisions:
        suffix = f" · {visual_count} 张图片已通过存储校验" if visual_count else ""
        return "not_configured", f"图片模型审查不可用{suffix}"
    if decisions and decisions == {"accepted"}:
        if visual_count:
            return "passed", f"{visual_count} 张图片已通过存储与模型审查"
        return _missing_artifact_state(bundle.run.status), "模型审查通过 · 等待图片存储校验"
    if visual_count:
        return "advisory", f"{visual_count} 张图片已通过存储校验 · 模型审查未配置"
    if bundle.run.current_stage == "generating_body_visuals":
        return "running", "图片正在生成"
    return _missing_artifact_state(bundle.run.status), "等待可展示图片"


def _missing_artifact_state(run_status: str) -> VisitorStageState:
    if run_status == "failed":
        return "failed"
    if run_status == "result_unknown":
        return "result_unknown"
    if run_status == "review_required":
        return "review_required"
    if run_status == "queued":
        return "pending"
    if run_status == "ready":
        return "result_unknown"
    return "running"


def validate_runtime_state(run_state: str, current_stage: str) -> None:
    """Small explicit guard used before public enum casts."""

    if run_state not in _RUN_STATES or current_stage not in _RUN_STAGES:
        raise ConflictError("visitor display run state is unsupported")


__all__ = [
    "VisitorDisplayService",
    "media_asset_ref",
    "news_key",
    "project_news_pool",
    "resolve_media_asset",
    "validate_runtime_state",
]
