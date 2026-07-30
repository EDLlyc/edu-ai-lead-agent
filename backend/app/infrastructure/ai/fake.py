from __future__ import annotations

import math
from hashlib import sha256

from app.application.ports.governance import (
    EmbeddingRequest,
    EmbeddingResult,
    FactualAnalysisRequest,
    FactualAnalysisResult,
)
from app.domain.governance_enums import (
    EventTimePrecision,
    FactualCategory,
)
from app.domain.value_objects import stable_key
from app.schemas.governance_analysis import (
    EvidenceBoundStatement,
    FactualAnalysisOutput,
    FactualCategoryAssignment,
    FactualClaim,
)


class DeterministicFakeFactualAnalysisModel:
    """Offline development provider; never used when AI_PROVIDER_MODE=zhipu."""

    def __init__(self, *, model: str) -> None:
        self._model = model

    async def analyze(self, request: FactualAnalysisRequest) -> FactualAnalysisResult:
        passage_id = request.passages[0].passage_id
        event_time = request.published_at
        precision = EventTimePrecision.DAY if event_time is not None else EventTimePrecision.UNKNOWN
        bounded_title = request.title.strip()[:100]
        analysis = FactualAnalysisOutput(
            summary=EvidenceBoundStatement(
                text=f"受控假模型记录: {bounded_title}",
                passage_ids=(passage_id,),
            ),
            key_facts=(
                FactualClaim(
                    text="该记录来自已存储资料, 仅用于离线治理流程验收。",
                    passage_ids=(passage_id,),
                    event_time_start=event_time,
                    event_time_end=event_time,
                    event_time_precision=precision,
                ),
            ),
            categories=(
                FactualCategoryAssignment(
                    category=FactualCategory.AI_INDUSTRY_APPLICATION,
                    confidence=1.0,
                ),
            ),
            primary_category=FactualCategory.AI_INDUSTRY_APPLICATION,
            keywords=("人工智能", "离线验收"),
            event_time_start=event_time,
            event_time_end=event_time,
            event_time_precision=precision,
            publication_time=request.published_at,
        )
        fingerprint = stable_key(
            "fake-factual-analysis",
            request.candidate_id,
            request.prompt_version,
            request.schema_version,
            request.taxonomy_version,
        )
        return FactualAnalysisResult(
            analysis=analysis,
            provider="fake",
            model=self._model,
            request_fingerprint=fingerprint,
            provider_request_id=None,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            latency_ms=0,
        )


class DeterministicFakeEmbeddingModel:
    def __init__(self, *, model: str, dimensions: int = 2048) -> None:
        if dimensions != 2048:
            raise ValueError("fake embedding must honor the 2048-dimensional contract")
        self._model = model
        self._dimensions = dimensions

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        digest = sha256(
            f"{request.purpose.value}\x1e{request.input_hash}\x1e{request.text}".encode()
        ).digest()
        raw = tuple(
            (digest[index % len(digest)] - 127.5) / 127.5 for index in range(self._dimensions)
        )
        norm = math.sqrt(sum(value * value for value in raw))
        vector = tuple(value / norm for value in raw)
        return EmbeddingResult(
            vector=vector,
            provider="fake",
            model=self._model,
            dimensions=self._dimensions,
            request_fingerprint=stable_key(
                "fake-embedding",
                request.artifact_id,
                request.purpose.value,
                request.input_hash,
                self._model,
            ),
            provider_request_id=None,
            prompt_tokens=0,
            latency_ms=0,
        )
