from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


VisitorStageState = Literal[
    "pending",
    "running",
    "passed",
    "advisory",
    "review_required",
    "failed",
    "result_unknown",
    "not_configured",
]


class VisitorDisplaySource(_StrictModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2_048)
    tier_label: str = Field(min_length=1, max_length=40)

    @field_validator("url")
    @classmethod
    def validate_stored_https_url(cls, value: str) -> str:
        return stored_https_url(value)


def stored_https_url(value: str) -> str:
    from urllib.parse import urlsplit

    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("visitor source URL must be a stored HTTPS URL")
    return value


class VisitorDisplayExcerpt(_StrictModel):
    heading: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=800)


class VisitorDisplayEvidence(_StrictModel):
    external_fact_count: int = Field(ge=0, le=40)
    bound_external_fact_count: int = Field(ge=0, le=40)
    validation: VisitorStageState
    audit: VisitorStageState
    review: VisitorStageState

    @model_validator(mode="after")
    def validate_binding_count(self) -> VisitorDisplayEvidence:
        if self.bound_external_fact_count > self.external_fact_count:
            raise ValueError("bound external fact count cannot exceed total")
        return self


class VisitorDisplayVisual(_StrictModel):
    url: str = Field(pattern=r"^/api/v1/visitor-display/assets/vd1_[A-Za-z0-9_-]{43}$")
    alt: str = Field(min_length=1, max_length=200)
    role: Literal["cover", "body", "context"]
    provenance_label: str = Field(min_length=1, max_length=80)
    rights_label: str | None = Field(default=None, min_length=1, max_length=120)


class VisitorDisplayTimelineItem(_StrictModel):
    key: Literal[
        "source",
        "selection",
        "evidence",
        "writing",
        "review",
        "visuals",
        "draft",
    ]
    label: str = Field(min_length=1, max_length=40)
    state: VisitorStageState
    detail: str = Field(min_length=1, max_length=200)
    occurred_at: datetime | None = None


class VisitorDisplayArticle(_StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    display_title: str = Field(min_length=1, max_length=120)
    digest: str | None = Field(default=None, min_length=1, max_length=240)
    author: str | None = Field(default=None, min_length=1, max_length=80)
    topic_title: str | None = Field(default=None, min_length=1, max_length=300)
    created_at: datetime
    updated_at: datetime
    run_state: Literal[
        "queued",
        "running",
        "review_required",
        "ready",
        "failed",
        "result_unknown",
    ]
    current_stage: Literal[
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
    ]
    attempt_count: int = Field(ge=0, le=100)
    delivery_state: Literal[
        "not_confirmed",
        "local_handoff",
        "in_progress",
        "created",
        "failed",
        "result_unknown",
    ]
    draft_created: bool
    published: Literal[False] = False
    sources: list[VisitorDisplaySource] = Field(default_factory=list, max_length=8)
    excerpts: list[VisitorDisplayExcerpt] = Field(default_factory=list, max_length=3)
    evidence: VisitorDisplayEvidence
    visuals: list[VisitorDisplayVisual] = Field(default_factory=list, max_length=8)
    timeline: Annotated[list[VisitorDisplayTimelineItem], Field(min_length=7, max_length=7)]

    @model_validator(mode="after")
    def validate_public_truth(self) -> VisitorDisplayArticle:
        if self.draft_created != (self.delivery_state == "created"):
            raise ValueError("draft_created must exactly match created delivery state")
        expected_timeline = [
            "source",
            "selection",
            "evidence",
            "writing",
            "review",
            "visuals",
            "draft",
        ]
        if [item.key for item in self.timeline] != expected_timeline:
            raise ValueError("visitor timeline must use the canonical ordered stages")
        return self


VisitorNewsReason = Literal[
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
    "other_rule",
    "below_threshold",
    "same_day_already_selected",
    "not_eligible",
    "ranked_out",
]
VisitorNewsDimension = Literal[
    "source_trust",
    "source_diversity",
    "freshness",
    "communication_potential",
    "ai_relevance",
    "parent_relevance",
    "science_education_relevance",
    "product_matrix_fit",
    "editorial_priority",
    "theme_repetition",
    "controversy_risk",
    "marketing_risk",
]
VisitorNewsUnfilledReason = Literal[
    "no_candidates",
    "all_vetoed",
    "below_threshold",
    "same_day_already_selected",
    "insufficient_eligible_candidates",
]
VisitorHumanDecision = Literal["agree", "include", "exclude"]
NEWS_KEY_PATTERN = r"^vn1_[0-9a-f]{24}$"


class VisitorDisplayScoreDimension(_StrictModel):
    key: VisitorNewsDimension
    kind: Literal["positive", "penalty"]
    value: float = Field(ge=0, le=1)
    weight: float = Field(ge=0, le=1)


# Progress of a production "人工加推" (operator human pick) through the normal pipeline.
VisitorHumanPickStage = Literal[
    "queued",
    "writing",
    "imaging",
    # Copy and picture are ready; held until the operator pushes (since 2026-10-01).
    "awaiting_review",
    "sending",
    "delivered",
    "partial",
    "unknown",
    "failed",
    "expired",
]
VisitorHumanPickRejection = Literal[
    "human_pick_already_selected",
    "human_pick_already_delivered",
    "human_pick_slot_busy",
    "human_pick_no_lineage",
    "human_pick_too_late",
    "content_slot_disabled",
    # Review, edit and push of a held pick.
    "human_pick_not_ready",
    "human_pick_already_pushed",
    "human_pick_rejected",
    "human_pick_expired",
    "human_pick_copy_invalid",
]


class VisitorDisplayHumanPick(_StrictModel):
    stage: VisitorHumanPickStage
    picked_at: datetime
    failure_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]{1,80}$")
    long_image: Literal["making", "sent", "failed"] | None = None


class VisitorDisplayHumanReview(_StrictModel):
    decision: VisitorHumanDecision
    note: str | None = Field(default=None, min_length=1, max_length=280)
    reviewed_at: datetime


class VisitorDisplayNewsCandidate(_StrictModel):
    key: str = Field(pattern=NEWS_KEY_PATTERN)
    title: str = Field(min_length=1, max_length=200)
    source_name: str | None = Field(default=None, min_length=1, max_length=120)
    source_url: str | None = Field(default=None, min_length=1, max_length=2_048)
    tier_label: str | None = Field(default=None, min_length=1, max_length=40)
    published_at: datetime | None = None
    snippet: str | None = Field(default=None, min_length=1, max_length=200)
    verdict: Literal["selected", "rejected"]
    selected_ordinal: int | None = Field(default=None, ge=1, le=3)
    rank: int = Field(ge=1, le=10_000)
    score: float = Field(ge=-10, le=10)
    threshold: float = Field(ge=0, le=10)
    reasons: list[VisitorNewsReason] = Field(default_factory=list, max_length=16)
    dimensions: list[VisitorDisplayScoreDimension] = Field(default_factory=list, max_length=16)
    human_review: VisitorDisplayHumanReview | None = None
    human_pick: VisitorDisplayHumanPick | None = None

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return stored_https_url(value)

    @model_validator(mode="after")
    def validate_verdict(self) -> VisitorDisplayNewsCandidate:
        if (self.verdict == "selected") != (self.selected_ordinal is not None):
            raise ValueError("selected verdict must exactly match a selection ordinal")
        if self.verdict == "rejected" and not self.reasons:
            raise ValueError("a rejected candidate needs at least one reason")
        return self


class VisitorDisplayNewsBatch(_StrictModel):
    business_date: date
    slot: Literal["morning", "noon", "evening"]
    target_at: datetime
    total_count: int = Field(ge=0, le=10_000)
    eligible_count: int = Field(ge=0, le=10_000)
    selected_count: int = Field(ge=0, le=3)
    unfilled_reasons: list[VisitorNewsUnfilledReason] = Field(default_factory=list, max_length=5)
    # 40 by rank plus up to 8 central policy documents ranked below the cut-off.
    candidates: list[VisitorDisplayNewsCandidate] = Field(default_factory=list, max_length=48)


class VisitorDisplayNewsPool(_StrictModel):
    review_enabled: bool = False
    human_pick_enabled: bool = False
    # Production holds picks for review, edit and push (it answers the review routes).
    human_pick_review_enabled: bool = False
    batches: list[VisitorDisplayNewsBatch] = Field(default_factory=list, max_length=6)


_COUNT = Field(default=0, ge=0, le=10_000_000)


class VisitorDisplayReportDay(_StrictModel):
    day: date
    fetched_new: int = _COUNT
    filtered: int = _COUNT
    duplicates: int = _COUNT
    scoring_batches: int = _COUNT
    evaluated: int = _COUNT
    eligible: int = _COUNT
    selected: int = _COUNT
    copies_accepted: int = _COUNT
    copies_review_required: int = _COUNT
    copies_failed: int = _COUNT
    copies_no_topic: int = _COUNT
    wecom_delivered: int = _COUNT
    wecom_partial: int = _COUNT
    wecom_failed: int = _COUNT
    wecom_unknown: int = _COUNT
    articles_ready: int = _COUNT
    articles_failed: int = _COUNT
    articles_other: int = _COUNT
    drafts_created: int = _COUNT
    human_reviews: int = _COUNT
    human_disagreements: int = _COUNT


class VisitorDisplayReport(_StrictModel):
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    generated_at: datetime
    days: list[VisitorDisplayReportDay] = Field(min_length=1, max_length=7)

    @model_validator(mode="after")
    def validate_consecutive_days(self) -> VisitorDisplayReport:
        ordinals = [item.day.toordinal() for item in self.days]
        if ordinals != list(range(ordinals[0], ordinals[0] + len(ordinals))):
            raise ValueError("report days must be consecutive and ascending")
        return self


# 「复盘提升」: problems found by humans and the daily/weekly reports, and what was optimized.
VisitorImprovementSource = Literal["daily", "weekly", "human"]
_IMPROVEMENT_KEY = r"^[a-z0-9_:.-]{1,80}$"


class VisitorImprovementIssue(_StrictModel):
    key: str = Field(pattern=_IMPROVEMENT_KEY)
    source: VisitorImprovementSource
    title: str = Field(min_length=1, max_length=60)
    cause: str = Field(min_length=1, max_length=140)
    this_week: int = Field(ge=0, le=100_000)
    last_week: int = Field(ge=0, le=100_000)
    today: int = Field(ge=0, le=100_000)
    status: Literal["fixed", "watching", "open"]
    fix_key: str | None = Field(default=None, pattern=_IMPROVEMENT_KEY)
    suggestion: str | None = Field(default=None, min_length=1, max_length=140)


class VisitorImprovementFix(_StrictModel):
    key: str = Field(pattern=_IMPROVEMENT_KEY)
    shipped_at: datetime
    source: VisitorImprovementSource
    problem: str = Field(min_length=1, max_length=80)
    change: str = Field(min_length=1, max_length=140)
    version: str | None = Field(default=None, min_length=1, max_length=60)
    # Occurrences of the measured problem on days up to / after the release day (None: the
    # problem has no live signal, e.g. it came from a person or a one-off report check).
    before: int | None = Field(default=None, ge=0, le=100_000)
    after: int | None = Field(default=None, ge=0, le=100_000)
    days_live: int = Field(ge=0, le=10_000)


class VisitorImprovementHuman(_StrictModel):
    reviews: int = Field(default=0, ge=0, le=100_000)
    include_overrides: int = Field(default=0, ge=0, le=100_000)
    exclude_overrides: int = Field(default=0, ge=0, le=100_000)
    picks: int = Field(default=0, ge=0, le=100_000)


class VisitorDisplayImprovement(_StrictModel):
    generated_at: datetime
    window_days: Literal[7] = 7
    issues: list[VisitorImprovementIssue] = Field(default_factory=list, max_length=16)
    fixes: list[VisitorImprovementFix] = Field(default_factory=list, max_length=16)
    human: VisitorImprovementHuman = Field(default_factory=VisitorImprovementHuman)
    next_steps: list[str] = Field(default_factory=list, max_length=3)


# 「朋友圈」: one real WeCom group post traced back through its production steps.
MOMENT_KEY_PATTERN = r"^vmk_[0-9a-f]{24}$"
MOMENT_ASSET_PATTERN = r"^vm1_[A-Za-z0-9_-]{43}$"


class VisitorMomentImageRef(_StrictModel):
    ref: str = Field(pattern=MOMENT_ASSET_PATTERN)
    width: int | None = Field(default=None, ge=1, le=10_000)
    height: int | None = Field(default=None, ge=1, le=10_000)


class VisitorDisplayMoment(_StrictModel):
    key: str = Field(pattern=MOMENT_KEY_PATTERN)
    business_date: date
    slot: Literal["morning", "noon", "evening"]
    ordinal: int | None = Field(default=None, ge=1, le=3)
    human_pick: bool = False
    title: str = Field(min_length=1, max_length=200)
    source_host: str | None = Field(default=None, min_length=1, max_length=120)
    source_url: str | None = Field(default=None, min_length=1, max_length=2_048)
    selection_reason: str = Field(min_length=1, max_length=80)
    score: float | None = Field(default=None, ge=-10, le=10)
    threshold: float | None = Field(default=None, ge=0, le=10)
    brand_angles: list[str] = Field(default_factory=list, max_length=3)
    copy_text: str = Field(min_length=1, max_length=2_400)
    copy_started_at: datetime | None = None
    copy_finished_at: datetime | None = None
    repair_count: int = Field(default=0, ge=0, le=10)
    checks: list[str] = Field(default_factory=list, max_length=6)
    image: VisitorMomentImageRef | None = None
    delivery: Literal["delivered", "partial", "unknown"]
    text_sent_at: datetime | None = None
    image_sent_at: datetime | None = None
    long_image: VisitorMomentImageRef | None = None
    long_image_state: Literal["sent", "ready", "making", "failed", "none"] = "none"
    long_image_sent_at: datetime | None = None

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return stored_https_url(value)

    @field_validator("brand_angles", "checks")
    @classmethod
    def validate_labels(cls, value: list[str]) -> list[str]:
        if any(not 1 <= len(item) <= 40 for item in value):
            raise ValueError("labels must be 1-40 characters")
        return value


class VisitorDisplaySnapshot(_StrictModel):
    schema_version: Literal["visitor-display-snapshot-v1"] = "visitor-display-snapshot-v1"
    observed_at: datetime
    refresh_after_seconds: Literal[8] = 8
    state: Literal["live", "empty"]
    articles: list[VisitorDisplayArticle] = Field(default_factory=list, max_length=12)
    news_pool: VisitorDisplayNewsPool | None = None
    report: VisitorDisplayReport | None = None
    improvement: VisitorDisplayImprovement | None = None
    moments: list[VisitorDisplayMoment] | None = Field(default=None, max_length=12)

    @model_validator(mode="after")
    def validate_state_matches_articles(self) -> VisitorDisplaySnapshot:
        if (self.state == "empty") != (len(self.articles) == 0):
            raise ValueError("snapshot state must exactly match article availability")
        return self


class VisitorDisplayNewsReviewRequest(_StrictModel):
    key: str = Field(pattern=NEWS_KEY_PATTERN)
    decision: VisitorHumanDecision
    note: str | None = Field(default=None, min_length=1, max_length=280)


class VisitorDisplayHumanPickRequest(_StrictModel):
    key: str = Field(pattern=NEWS_KEY_PATTERN)
    note: str | None = Field(default=None, min_length=1, max_length=280)


class VisitorHumanPickIssue(_StrictModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    severity: Literal["warning", "error"]
    message: str = Field(min_length=1, max_length=240)


class VisitorHumanPickReview(_StrictModel):
    """A held pick's copy for the operator (PIN-gated): fixed lines and the editable ones."""

    stage: VisitorHumanPickStage
    editable: bool
    push_deadline: datetime
    copywriting: str | None = Field(default=None, max_length=4000)
    heading: str | None = Field(default=None, max_length=40)
    headline: list[str] = Field(default_factory=list, max_length=3)
    hook: str = Field(default="", max_length=500)
    source_line: str | None = Field(default=None, max_length=500)
    link_line: str | None = Field(default=None, max_length=1000)
    hashtags: list[str] = Field(default_factory=list, max_length=6)
    issues: list[VisitorHumanPickIssue] = Field(default_factory=list, max_length=40)
    # Set only by a check or save.
    passed: bool | None = None
    saved: bool | None = None


class VisitorHumanPickCopyRequest(_StrictModel):
    hook: str = Field(max_length=500)
    hashtags: list[str] = Field(default_factory=list, max_length=6)
    dry_run: bool = False


class VisitorDisplayOperatorSessionRequest(_StrictModel):
    pin: str = Field(min_length=4, max_length=32)
