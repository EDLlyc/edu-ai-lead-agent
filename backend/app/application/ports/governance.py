from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.event_assignment import (
    EventArticleProfile,
    EventAssignmentDecision,
    EventAssignmentPolicy,
)
from app.domain.governance_deduplication import (
    ExactDuplicateArtifact,
    ExactDuplicateDecision,
)
from app.domain.governance_entities import (
    ClaimedGovernanceJob,
    GovernanceJobCompletion,
    GovernanceSourceOccurrence,
    GovernanceVersionBundle,
)
from app.domain.governance_enums import (
    AnalysisValidationCode,
    EmbeddingPurpose,
    GovernanceAttemptResult,
)
from app.domain.governance_normalization import NormalizedDocument
from app.domain.governance_pipeline import (
    AnalysisArtifact,
    EmbeddingArtifact,
    ExactReuseArtifact,
    NormalizedArtifact,
    PersistedEventAssignment,
    RecentEventCandidate,
    SemanticCandidateArtifact,
    StoredGovernanceCandidate,
)
from app.domain.governance_semantic import SemanticDuplicateDecision
from app.domain.value_objects import is_sha256_hex
from app.schemas.governance_analysis import FactualAnalysisOutput


@dataclass(frozen=True, slots=True)
class FactualAnalysisPassage:
    passage_id: UUID
    ordinal: int
    passage_hash: str
    text: str

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("passage ordinal must be non-negative")
        if not is_sha256_hex(self.passage_hash):
            raise ValueError("passage hash must be a lowercase SHA-256 hex digest")
        if not self.text.strip():
            raise ValueError("analysis passage text must not be blank")


@dataclass(frozen=True, slots=True)
class FactualAnalysisRequest:
    candidate_id: UUID
    title: str
    published_at: datetime | None
    language: str
    passages: tuple[FactualAnalysisPassage, ...]
    prompt_version: str
    schema_version: str
    taxonomy_version: str
    max_output_tokens: int
    repair_issue_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.title.strip() or not self.language.strip():
            raise ValueError("analysis title and language must not be blank")
        if not self.passages:
            raise ValueError("factual analysis requires at least one passage")
        passage_ids = [passage.passage_id for passage in self.passages]
        if len(passage_ids) != len(set(passage_ids)):
            raise ValueError("factual-analysis passage IDs must be unique")
        passage_ordinals = [passage.ordinal for passage in self.passages]
        if len(passage_ordinals) != len(set(passage_ordinals)):
            raise ValueError("factual-analysis passage ordinals must be unique")
        if self.max_output_tokens <= 0:
            raise ValueError("maximum output tokens must be positive")
        if self.published_at is not None and self.published_at.tzinfo is None:
            raise ValueError("publication time must be timezone-aware")
        versions = (self.prompt_version, self.schema_version, self.taxonomy_version)
        if any(not version.strip() or len(version) > 80 for version in versions):
            raise ValueError("analysis versions must be non-blank and at most 80 characters")
        approved_issue_codes = {code.value for code in AnalysisValidationCode}
        if any(code not in approved_issue_codes for code in self.repair_issue_codes):
            raise ValueError("repair issue codes must use the approved validation taxonomy")


@dataclass(frozen=True, slots=True)
class FactualAnalysisResult:
    analysis: FactualAnalysisOutput
    provider: str
    model: str
    request_fingerprint: str
    provider_request_id: str | None
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    latency_ms: int
    validation_corrections: int = 0


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    artifact_id: UUID
    purpose: EmbeddingPurpose
    input_hash: str
    text: str
    expected_dimensions: int = 2048

    def __post_init__(self) -> None:
        if not is_sha256_hex(self.input_hash):
            raise ValueError("embedding input hash must be a lowercase SHA-256 hex digest")
        if not self.text.strip():
            raise ValueError("embedding input must not be blank")
        if self.expected_dimensions != 2048:
            raise ValueError("embedding persistence contract requires 2048 dimensions")


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vector: tuple[float, ...]
    provider: str
    model: str
    dimensions: int
    request_fingerprint: str
    provider_request_id: str | None
    prompt_tokens: int
    latency_ms: int


class GovernanceRepository(Protocol):
    async def create_run_for_acquisition(
        self,
        *,
        acquisition_run_id: UUID,
        bundle: GovernanceVersionBundle,
        timezone: str,
    ) -> UUID: ...

    async def create_manual_run(
        self,
        *,
        candidate_ids: tuple[UUID, ...],
        idempotency_key: str,
        bundle: GovernanceVersionBundle,
        timezone: str,
    ) -> UUID: ...

    async def reconcile_terminal_acquisition_runs(
        self, *, bundle: GovernanceVersionBundle, timezone: str, limit: int = 20
    ) -> int: ...

    async def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> ClaimedGovernanceJob | None: ...

    async def claim_for_run(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        lease_seconds: int,
    ) -> ClaimedGovernanceJob | None: ...

    async def heartbeat(self, *, claimed: ClaimedGovernanceJob, lease_seconds: int) -> bool: ...

    async def update_stage(self, claimed: ClaimedGovernanceJob, *, stage: str) -> None: ...

    async def create_attempt(self, claimed: ClaimedGovernanceJob, *, stage: str) -> UUID: ...

    async def complete_attempt(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        attempt_id: UUID,
        result: GovernanceAttemptResult,
        stage: str,
        error_code: str | None = None,
        safe_metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def synchronize_occurrences(
        self, claimed: ClaimedGovernanceJob
    ) -> Sequence[GovernanceSourceOccurrence]: ...

    async def complete_job(
        self, *, claimed: ClaimedGovernanceJob, completion: GovernanceJobCompletion
    ) -> bool: ...


class GovernanceArtifactRepository(Protocol):
    async def load_candidate(self, claimed: ClaimedGovernanceJob) -> StoredGovernanceCandidate: ...

    async def persist_normalized(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        document: NormalizedDocument,
        language: str,
    ) -> NormalizedArtifact: ...

    async def find_exact_duplicates(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        article: NormalizedArtifact,
    ) -> tuple[ExactDuplicateArtifact, ...]: ...

    async def persist_exact_duplicate_decision(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        incoming: ExactDuplicateArtifact,
        decision: ExactDuplicateDecision,
        policy_version: str,
    ) -> tuple[UUID, ...]: ...

    async def find_exact_reuse(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        canonical_article_id: UUID,
    ) -> ExactReuseArtifact | None: ...

    async def load_analysis(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        normalized_article_id: UUID,
    ) -> AnalysisArtifact | None: ...

    async def persist_analysis(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        article: NormalizedArtifact,
        result: FactualAnalysisResult,
        prompt_version: str,
        schema_version: str,
        taxonomy_version: str,
    ) -> AnalysisArtifact: ...

    async def load_embedding(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        normalized_article_id: UUID,
        purpose: EmbeddingPurpose,
        input_hash: str,
        input_version: str,
    ) -> EmbeddingArtifact | None: ...

    async def persist_embedding(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        normalized_article_id: UUID,
        purpose: EmbeddingPurpose,
        input_hash: str,
        input_version: str,
        result: EmbeddingResult,
    ) -> EmbeddingArtifact: ...

    async def find_semantic_candidates(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        article: NormalizedArtifact,
        embedding: EmbeddingArtifact,
        limit: int,
    ) -> tuple[SemanticCandidateArtifact, ...]: ...

    async def persist_semantic_decisions(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        decisions: tuple[SemanticDuplicateDecision, ...],
    ) -> tuple[UUID, ...]: ...

    async def find_recent_event_candidates(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        incoming: EventArticleProfile,
        embedding: EmbeddingArtifact,
        policy: EventAssignmentPolicy,
        now: datetime,
    ) -> tuple[RecentEventCandidate, ...]: ...

    async def persist_event_assignment(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        incoming: EventArticleProfile,
        decision: EventAssignmentDecision,
        policy: EventAssignmentPolicy,
        now: datetime,
    ) -> PersistedEventAssignment: ...


class FactualAnalysisModel(Protocol):
    async def analyze(self, request: FactualAnalysisRequest) -> FactualAnalysisResult: ...


class EmbeddingModel(Protocol):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult: ...


class GovernanceCheckpointer(Protocol):
    async def checkpoint_exists(self, *, thread_id: str) -> bool: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new(self) -> UUID: ...
