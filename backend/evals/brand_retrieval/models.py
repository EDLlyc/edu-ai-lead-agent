"""Strict contracts for the sanitized brand-text retrieval evaluation dataset."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from app.domain.brand_knowledge import BrandClaimScope, BrandContentType
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

CASE_SCHEMA_VERSION = "brand-retrieval-eval-case-v1"

BoundedIdentifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9._:-]*$"),
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BrandRetrievalEvalCandidate(_FrozenModel):
    """One sanitized candidate observation plus an evaluator-only relevance grade."""

    candidate_id: BoundedIdentifier
    document_key: BoundedIdentifier
    version_key: BoundedIdentifier
    section_key: BoundedIdentifier
    ordinal: int = Field(ge=0, le=10_000)
    content_type: BrandContentType
    claim_scope: BrandClaimScope
    verification_required: bool
    evidence_eligible: bool
    full_text_rank: int | None = Field(default=None, ge=1, le=100)
    vector_rank: int | None = Field(default=None, ge=1, le=100)
    relevance_grade: int = Field(ge=0, le=3)

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if self.full_text_rank is None and self.vector_rank is None:
            raise ValueError("candidate must have at least one observed rank")
        return self


class BrandRetrievalEvalCase(_FrozenModel):
    """One query and its independently graded, pre-selection candidate observation."""

    schema_version: Literal["brand-retrieval-eval-case-v1"]
    case_id: BoundedIdentifier
    category: BrandContentType
    query: str = Field(min_length=1, max_length=300)
    candidates: tuple[BrandRetrievalEvalCandidate, ...] = Field(min_length=7, max_length=12)

    @model_validator(mode="after")
    def validate_case(self) -> Self:
        candidate_ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate IDs must be unique within a case")
        for field_name in ("full_text_rank", "vector_rank"):
            ranks = tuple(
                rank
                for candidate in self.candidates
                if (rank := getattr(candidate, field_name)) is not None
            )
            if len(ranks) != len(set(ranks)):
                raise ValueError(f"{field_name} values must be unique within a case")
        if not any(candidate.relevance_grade > 0 for candidate in self.candidates):
            raise ValueError("each case requires at least one relevant candidate")
        if not any(
            candidate.content_type is self.category and candidate.relevance_grade > 0
            for candidate in self.candidates
        ):
            raise ValueError("each case requires a category-matching relevant candidate")
        return self
