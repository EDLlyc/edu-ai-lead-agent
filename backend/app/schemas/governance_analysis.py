from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.governance_enums import (
    EventTimePrecision,
    FactualCategory,
    FactualEntityType,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvidenceBoundStatement(_StrictModel):
    text: str = Field(min_length=4, max_length=500)
    passage_ids: tuple[UUID, ...] = Field(min_length=1, max_length=5)

    @field_validator("passage_ids")
    @classmethod
    def passage_ids_must_be_unique(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("passage IDs must be unique")
        return value


class FactualClaim(EvidenceBoundStatement):
    event_time_start: AwareDatetime | None = None
    event_time_end: AwareDatetime | None = None
    event_time_precision: EventTimePrecision = EventTimePrecision.UNKNOWN

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.event_time_start is not None and self.event_time_end is not None:
            if self.event_time_end < self.event_time_start:
                raise ValueError("fact event-time end must not precede start")
        if self.event_time_precision is EventTimePrecision.UNKNOWN and (
            self.event_time_start is not None or self.event_time_end is not None
        ):
            raise ValueError("unknown fact event-time precision cannot carry a time")
        if self.event_time_precision is not EventTimePrecision.UNKNOWN:
            if self.event_time_start is None:
                raise ValueError("known fact event-time precision requires a start time")
        return self


class StructuredEntity(_StrictModel):
    entity_type: FactualEntityType
    source_mention: str = Field(min_length=1, max_length=120)
    canonical_name: str = Field(min_length=1, max_length=120)
    passage_id: UUID


class FactualCategoryAssignment(_StrictModel):
    category: FactualCategory
    confidence: float = Field(ge=0, le=1)


class FactualAnalysisOutput(_StrictModel):
    summary: EvidenceBoundStatement
    key_facts: tuple[FactualClaim, ...] = Field(min_length=1, max_length=8)
    entities: tuple[StructuredEntity, ...] = Field(default=(), max_length=20)
    categories: tuple[FactualCategoryAssignment, ...] = Field(min_length=1, max_length=4)
    primary_category: FactualCategory | None = None
    keywords: tuple[str, ...] = Field(min_length=1, max_length=12)
    event_time_start: AwareDatetime | None = None
    event_time_end: AwareDatetime | None = None
    event_time_precision: EventTimePrecision = EventTimePrecision.UNKNOWN
    publication_time: AwareDatetime | None = None

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(len(keyword) < 2 or len(keyword) > 40 for keyword in value):
            raise ValueError("keywords must contain 2 to 40 characters")
        normalized = [keyword.casefold() for keyword in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("keywords must be unique")
        return value

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        categories = [assignment.category for assignment in self.categories]
        if len(categories) != len(set(categories)):
            raise ValueError("categories must be unique")
        if self.primary_category is not None and self.primary_category not in categories:
            raise ValueError("primary category must also appear in categories")
        fact_texts = [fact.text.casefold() for fact in self.key_facts]
        if len(fact_texts) != len(set(fact_texts)):
            raise ValueError("key facts must be unique")
        if self.event_time_start is not None and self.event_time_end is not None:
            if self.event_time_end < self.event_time_start:
                raise ValueError("analysis event-time end must not precede start")
        if self.event_time_precision is EventTimePrecision.UNKNOWN and (
            self.event_time_start is not None or self.event_time_end is not None
        ):
            raise ValueError("unknown analysis event-time precision cannot carry a time")
        if self.event_time_precision is not EventTimePrecision.UNKNOWN:
            if self.event_time_start is None:
                raise ValueError("known analysis event-time precision requires a start time")
        return self
