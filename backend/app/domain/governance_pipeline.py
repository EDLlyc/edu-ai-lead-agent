from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.event_assignment import EventCandidateProfile
from app.domain.governance_enums import EmbeddingPurpose, EventAssignmentOutcome
from app.domain.governance_normalization import NormalizedPassage
from app.schemas.governance_analysis import FactualAnalysisOutput


@dataclass(frozen=True, slots=True)
class StoredGovernanceCandidate:
    candidate_id: UUID
    source_id: UUID
    source_item_id: str
    title: str
    clean_text: str
    canonical_url: str
    published_at: datetime | None
    first_fetched_at: datetime
    language: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class NormalizedArtifact:
    normalized_article_id: UUID
    candidate_id: UUID
    input_content_hash: str
    normalization_version: str
    normalized_hash: str
    simhash_hex: str
    normalized_text: str
    passages: tuple[NormalizedPassage, ...]


@dataclass(frozen=True, slots=True)
class AnalysisArtifact:
    analysis_id: UUID
    normalized_article_id: UUID
    candidate_id: UUID
    request_fingerprint: str
    analysis: FactualAnalysisOutput


@dataclass(frozen=True, slots=True)
class EmbeddingArtifact:
    embedding_id: UUID
    normalized_article_id: UUID
    purpose: EmbeddingPurpose
    provider: str
    model: str
    dimensions: int
    input_hash: str
    input_version: str
    vector: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class SemanticCandidateArtifact:
    normalized_article_id: UUID
    candidate_id: UUID
    simhash_hex: str
    vector: tuple[float, ...]
    cosine_distance: float


@dataclass(frozen=True, slots=True)
class ExactReuseArtifact:
    canonical_article_id: UUID
    analysis_id: UUID
    event_id: UUID | None


@dataclass(frozen=True, slots=True)
class PersistedEventAssignment:
    decision_id: UUID
    outcome: EventAssignmentOutcome
    event_id: UUID | None
    event_version_id: UUID | None
    source_diversity: int


@dataclass(frozen=True, slots=True)
class RecentEventCandidate:
    profile: EventCandidateProfile
    cosine_distance: float
