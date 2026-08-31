from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

CASE_SCHEMA_VERSION = "ip-asset-retrieval-eval-case-v1"


class IpAssetRetrievalEvalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(pattern=r"^[a-z0-9-]{3,80}$")
    metadata_rank: int | None = Field(default=None, ge=1, le=100)
    semantic_rank: int | None = Field(default=None, ge=1, le=100)
    metadata_score: float | None = Field(default=None, ge=0, le=1)
    semantic_similarity: float | None = Field(default=None, ge=-1, le=1)
    relevance_grade: int = Field(ge=0, le=3)

    @model_validator(mode="after")
    def validate_lanes(self) -> IpAssetRetrievalEvalCandidate:
        if self.metadata_rank is None and self.semantic_rank is None:
            raise ValueError("candidate needs at least one observed rank")
        if (self.metadata_rank is None) != (self.metadata_score is None):
            raise ValueError("metadata rank and score must be observed together")
        if (self.semantic_rank is None) != (self.semantic_similarity is None):
            raise ValueError("semantic rank and similarity must be observed together")
        return self


class IpAssetRetrievalEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^ip-asset-retrieval-eval-case-v1$")
    case_id: str = Field(pattern=r"^[a-z0-9-]{3,80}$")
    category: str = Field(pattern=r"^[a-z_]{3,40}$")
    query: str = Field(min_length=1, max_length=200)
    exact_metadata_priority: bool = False
    allow_no_results: bool = False
    candidates: tuple[IpAssetRetrievalEvalCandidate, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_case(self) -> IpAssetRetrievalEvalCase:
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate IDs must be unique")
        for field_name in ("metadata_rank", "semantic_rank"):
            ranks = [
                value
                for candidate in self.candidates
                if (value := getattr(candidate, field_name)) is not None
            ]
            if len(ranks) != len(set(ranks)):
                raise ValueError(f"{field_name} values must be unique")
        if not self.candidates and not self.allow_no_results:
            raise ValueError("empty candidate cases must explicitly allow no results")
        if (
            self.exact_metadata_priority
            and self.candidates
            and not any(candidate.metadata_rank is not None for candidate in self.candidates)
        ):
            raise ValueError("exact metadata priority needs an observed metadata lane")
        if self.allow_no_results and any(
            candidate.relevance_grade > 0 for candidate in self.candidates
        ):
            raise ValueError("allowed no-result cases cannot hide relevant candidates")
        return self
