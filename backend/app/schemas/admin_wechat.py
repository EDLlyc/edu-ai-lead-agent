from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AdminWeChatStatusResponse(BaseModel):
    secret_key_configured: bool


class AdminWeChatAccountResponse(BaseModel):
    id: UUID
    name: str
    app_id: str
    secret_hint: str
    topics: list[str]
    enabled: bool
    last_verified_at: datetime | None
    last_verify_error: str | None
    created_by: str
    created_at: datetime


class AdminWeChatAccountListResponse(BaseModel):
    items: list[AdminWeChatAccountResponse]
    count: int


class AdminWeChatAccountOption(BaseModel):
    id: UUID
    name: str
    topics: list[str]


class AdminWeChatAccountOptionsResponse(BaseModel):
    items: list[AdminWeChatAccountOption]


class AdminWeChatAccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    app_id: str = Field(min_length=1, max_length=40)
    app_secret: str = Field(min_length=1, max_length=80)
    topics: list[str] = Field(default_factory=list, max_length=20)


class AdminWeChatAccountUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    topics: list[str] | None = Field(default=None, max_length=20)
    enabled: bool | None = None
    app_secret: str | None = Field(default=None, max_length=80)


class AdminWeChatDraftArticle(BaseModel):
    title: str
    author: str
    digest: str


class AdminWeChatDraft(BaseModel):
    media_id: str
    updated_at: datetime
    articles: list[AdminWeChatDraftArticle]
    open_job_id: UUID | None


class AdminWeChatDraftListResponse(BaseModel):
    total: int
    items: list[AdminWeChatDraft]


class AdminWeChatPublishedArticle(BaseModel):
    title: str
    url: str


class AdminWeChatPublished(BaseModel):
    article_id: str
    updated_at: datetime
    articles: list[AdminWeChatPublishedArticle]


class AdminWeChatPublishedListResponse(BaseModel):
    total: int
    items: list[AdminWeChatPublished]


class AdminWeChatPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    media_id: str = Field(min_length=1, max_length=128)
    title: str = Field(default="", max_length=300)
    scheduled_at: datetime | None = None


class AdminWeChatPublishJob(BaseModel):
    id: UUID
    account_id: UUID
    account_name: str
    media_id: str
    title: str
    scheduled_at: datetime
    status: Literal[
        "scheduled",
        "submitting",
        "publishing",
        "succeeded",
        "failed",
        "outcome_unknown",
        "cancelled",
    ]
    article_url: str | None
    error: str | None
    created_by: str
    cancelled_by: str | None
    created_at: datetime
    completed_at: datetime | None
    updated_at: datetime
    can_recheck: bool
    reconciled_by: str | None
    reconciliation_note: str | None


class AdminWeChatPublishReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: Literal["published", "not_published"]
    note: str = Field(min_length=5, max_length=500)
    confirmed: Literal[True]
    expected_updated_at: datetime


class AdminWeChatPublishJobListResponse(BaseModel):
    items: list[AdminWeChatPublishJob]


class AdminWeChatDailyStats(BaseModel):
    date: date
    read_user: int
    share_user: int
    like_user: int
    zaikan_user: int
    comment_count: int
    collection_user: int


class AdminWeChatArticleStats(BaseModel):
    msgid: str
    title: str
    url: str | None
    publish_date: date
    stat_date: date
    read_user: int
    share_user: int
    collection_user: int
    read_delivery_rate: float | None
    read_finish_rate: float | None
    read_avg_activetime: float | None
    read_sources: dict[str, int]


class AdminWeChatStatsResponse(BaseModel):
    range_start: date
    range_end: date
    # Date coverage only; optional counters retain the provider's sparse-response semantics.
    missing_dates: list[date]
    synced_on: date | None
    sync_error: str | None
    daily: list[AdminWeChatDailyStats]
    articles: list[AdminWeChatArticleStats]


class AdminWeChatSyncResponse(BaseModel):
    articles: int
    days: int


class AdminLayoutTemplate(BaseModel):
    id: str
    name: str
    description: str
    swatches: list[str]
    is_default: bool


class AdminLayoutAccount(BaseModel):
    id: UUID
    name: str
    layout_template_id: str


class AdminLayoutTemplatesResponse(BaseModel):
    templates: list[AdminLayoutTemplate]
    accounts: list[AdminLayoutAccount]


class AdminLayoutPreviewResponse(BaseModel):
    html: str


class AdminLayoutTemplateSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=40)
