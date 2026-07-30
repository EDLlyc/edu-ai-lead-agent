from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.application.ports.governance import (
    EmbeddingRequest,
    EmbeddingResult,
    FactualAnalysisRequest,
    FactualAnalysisResult,
)
from app.domain.governance_enums import (
    EventTimePrecision,
    FactualCategory,
    FactualEntityType,
)
from app.domain.value_objects import stable_key
from app.schemas.governance_analysis import (
    EvidenceBoundStatement,
    FactualAnalysisOutput,
    FactualCategoryAssignment,
    FactualClaim,
    StructuredEntity,
)

FIXED_VECTOR = (1.0,) + (0.0,) * 2047


@dataclass(slots=True)
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@dataclass(slots=True)
class FakeFactualAnalysisModel:
    category: FactualCategory
    entity_name: str
    provider: str = "disabled"
    model: str = "glm-5.2"
    calls: list[UUID] = field(default_factory=list)

    async def analyze(self, request: FactualAnalysisRequest) -> FactualAnalysisResult:
        self.calls.append(request.candidate_id)
        passage_id = request.passages[0].passage_id
        event_time = request.published_at
        precision = EventTimePrecision.DAY if event_time is not None else EventTimePrecision.UNKNOWN
        output = FactualAnalysisOutput(
            summary=EvidenceBoundStatement(
                text=f"{self.entity_name}发布人工智能领域的重要进展。",
                passage_ids=(passage_id,),
            ),
            key_facts=(
                FactualClaim(
                    text=f"{self.entity_name}公布了可核验的人工智能进展。",
                    passage_ids=(passage_id,),
                    event_time_start=event_time,
                    event_time_end=event_time,
                    event_time_precision=precision,
                ),
            ),
            entities=(
                StructuredEntity(
                    entity_type=FactualEntityType.ORGANIZATION,
                    source_mention=self.entity_name,
                    canonical_name=self.entity_name,
                    passage_id=passage_id,
                ),
            ),
            categories=(FactualCategoryAssignment(category=self.category, confidence=0.99),),
            primary_category=self.category,
            keywords=("人工智能", "权威进展"),
            event_time_start=event_time,
            event_time_end=event_time,
            event_time_precision=precision,
            publication_time=request.published_at,
        )
        return FactualAnalysisResult(
            analysis=output,
            provider=self.provider,
            model=self.model,
            request_fingerprint=stable_key(
                request.candidate_id,
                request.prompt_version,
                request.schema_version,
                request.taxonomy_version,
                self.provider,
                self.model,
            ),
            provider_request_id="fake-analysis-request",
            prompt_tokens=20,
            completion_tokens=30,
            reasoning_tokens=0,
            latency_ms=1,
        )


@dataclass(slots=True)
class FakeEmbeddingModel:
    provider: str = "disabled"
    model: str = "embedding-3"
    vector: tuple[float, ...] = FIXED_VECTOR
    calls: list[EmbeddingRequest] = field(default_factory=list)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        self.calls.append(request)
        return EmbeddingResult(
            vector=self.vector,
            provider=self.provider,
            model=self.model,
            dimensions=len(self.vector),
            request_fingerprint=stable_key(
                request.artifact_id,
                request.purpose.value,
                request.input_hash,
                self.provider,
                self.model,
            ),
            provider_request_id="fake-embedding-request",
            prompt_tokens=10,
            latency_ms=1,
        )
