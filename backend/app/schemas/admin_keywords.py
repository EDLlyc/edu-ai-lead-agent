from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AdminKeywordLists(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focus: list[str] = Field(default_factory=list, max_length=400)
    block: list[str] = Field(default_factory=list, max_length=400)
    copy_banned: list[str] = Field(default_factory=list, max_length=400)


class AdminKeywordSaveRequest(AdminKeywordLists):
    note: str | None = Field(default=None, max_length=200)
    confirm_wide_block: bool = False


class AdminKeywordImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focus: list[str] = Field(default_factory=list, max_length=400)
    block: list[str] = Field(default_factory=list, max_length=400)


class AdminKeywordVersionResponse(BaseModel):
    version: int
    focus: list[str]
    block: list[str]
    copy_banned: list[str]
    note: str | None
    created_by: str
    created_at: datetime


class AdminKeywordHistoryItem(BaseModel):
    version: int
    note: str | None
    created_by: str
    created_at: datetime
    focus_count: int
    block_count: int
    copy_banned_count: int


class AdminKeywordsResponse(BaseModel):
    current: AdminKeywordVersionResponse | None
    history: list[AdminKeywordHistoryItem]


class AdminKeywordBlockedItem(BaseModel):
    title: str
    terms: list[str]
    selected: bool


class AdminKeywordFocusedItem(BaseModel):
    title: str
    terms: list[str]


class AdminKeywordTermCount(BaseModel):
    term: str
    count: int


class AdminKeywordImpactResponse(BaseModel):
    days: int
    candidate_count: int
    blocked_count: int
    blocked_selected_count: int
    blocked_share: float
    wide: bool
    blocked: list[AdminKeywordBlockedItem]
    per_block_term: list[AdminKeywordTermCount]
    focused_count: int
    focused: list[AdminKeywordFocusedItem]
