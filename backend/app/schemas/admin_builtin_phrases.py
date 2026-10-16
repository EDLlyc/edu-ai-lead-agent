from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuiltinPhraseLockedList(_Strict):
    name: str
    terms: list[str]


class BuiltinPhrasesResponse(_Strict):
    """The lists in force. ``version`` is null until someone saves a change."""

    version: int | None
    marketing: list[str]
    anxiety: list[str]
    defaults_marketing: list[str]
    defaults_anxiety: list[str]
    locked: list[BuiltinPhraseLockedList]
    note: str | None = None
    created_by: str | None = None
    created_at: datetime | None = None


class BuiltinPhrasesSaveRequest(_Strict):
    marketing: list[str] = Field(default_factory=list, max_length=200)
    anxiety: list[str] = Field(default_factory=list, max_length=200)
    note: str | None = Field(default=None, max_length=200)
