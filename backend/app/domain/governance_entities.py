from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.enums import SourceTier
from app.domain.governance_enums import GovernanceJobStatus
from app.domain.value_objects import stable_key


@dataclass(frozen=True, slots=True)
class GovernanceVersionBundle:
    pipeline_version: str
    normalization_version: str
    passage_schema_version: str
    taxonomy_version: str
    prompt_version: str
    analysis_schema_version: str
    chat_provider: str
    chat_model: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    embedding_input_version: str
    similarity_rule_version: str
    event_assignment_version: str

    def __post_init__(self) -> None:
        if self.embedding_dimensions != 2048:
            raise ValueError("governance embedding contract requires 2048 dimensions")
        string_values = [value for value in asdict(self).values() if isinstance(value, str)]
        if any(not value.strip() or len(value) > 80 for value in string_values):
            raise ValueError("governance version values must be non-empty and at most 80 chars")

    def as_metadata(self) -> dict[str, str | int]:
        return asdict(self)

    @classmethod
    def from_metadata(cls, value: dict[str, Any]) -> GovernanceVersionBundle:
        return cls(
            pipeline_version=str(value["pipeline_version"]),
            normalization_version=str(value["normalization_version"]),
            passage_schema_version=str(value["passage_schema_version"]),
            taxonomy_version=str(value["taxonomy_version"]),
            prompt_version=str(value["prompt_version"]),
            analysis_schema_version=str(value["analysis_schema_version"]),
            chat_provider=str(value["chat_provider"]),
            chat_model=str(value["chat_model"]),
            embedding_provider=str(value["embedding_provider"]),
            embedding_model=str(value["embedding_model"]),
            embedding_dimensions=int(value["embedding_dimensions"]),
            embedding_input_version=str(value["embedding_input_version"]),
            similarity_rule_version=str(value["similarity_rule_version"]),
            event_assignment_version=str(value["event_assignment_version"]),
        )

    @property
    def fingerprint(self) -> str:
        values = self.as_metadata()
        return stable_key(*(f"{key}={values[key]}" for key in sorted(values)))


@dataclass(frozen=True, slots=True)
class ClaimedGovernanceJob:
    job_id: UUID
    run_id: UUID
    candidate_id: UUID
    attempt_number: int
    lease_token: UUID
    input_content_hash: str
    idempotency_key: str
    version_bundle: GovernanceVersionBundle


@dataclass(frozen=True, slots=True)
class GovernanceSourceOccurrence:
    occurrence_id: UUID
    candidate_id: UUID
    observation_id: UUID
    snapshot_id: UUID
    source_id: UUID
    source_version_id: UUID
    source_item_id: str
    source_slug: str
    source_display_name: str
    trust_tier: SourceTier
    original_url: str
    final_url: str
    # NULL means acquisition did not retain a source-specific publication time for
    # this occurrence (notably when a cross-source exact duplicate reused a candidate).
    published_at: datetime | None
    fetched_at: datetime
    parser_version: str
    relevance_rule_version: str | None


@dataclass(frozen=True, slots=True)
class GovernanceJobCompletion:
    status: GovernanceJobStatus
    outcome: str
    error_code: str | None = None
    retry_at: datetime | None = None
    safe_metadata: dict[str, Any] | None = None
