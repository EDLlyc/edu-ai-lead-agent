from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from app.domain.governance_enums import DuplicateRelationKind
from app.domain.governance_normalization import simhash_distance


@dataclass(frozen=True, slots=True)
class SemanticDuplicatePolicy:
    version: str
    minimum_similarity: float = 0.94
    maximum_simhash_distance: int = 12

    def __post_init__(self) -> None:
        if not self.version.strip() or len(self.version) > 80:
            raise ValueError("semantic duplicate policy version must be non-blank and bounded")
        if not 0 <= self.minimum_similarity <= 1:
            raise ValueError("semantic duplicate similarity threshold must be in [0, 1]")
        if not 0 <= self.maximum_simhash_distance <= 64:
            raise ValueError("SimHash threshold must be in [0, 64]")


@dataclass(frozen=True, slots=True)
class SemanticArticle:
    normalized_article_id: UUID
    candidate_id: UUID
    simhash_hex: str
    vector: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class SemanticDuplicateFeatures:
    cosine_similarity: float
    simhash_distance: int

    def as_metadata(self) -> dict[str, float | int]:
        return {
            "cosine_similarity": round(self.cosine_similarity, 8),
            "simhash_distance": self.simhash_distance,
        }


@dataclass(frozen=True, slots=True)
class SemanticDuplicateDecision:
    left_article_id: UUID
    right_article_id: UUID
    relation_kind: DuplicateRelationKind
    matched: bool
    features: SemanticDuplicateFeatures
    threshold: float
    maximum_simhash_distance: int
    policy_version: str


def cosine_similarity(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    if not first or len(first) != len(second):
        raise ValueError("cosine similarity requires equal non-empty vectors")
    dot_product = sum(left * right for left, right in zip(first, second, strict=True))
    first_norm = math.sqrt(sum(value * value for value in first))
    second_norm = math.sqrt(sum(value * value for value in second))
    if first_norm == 0 or second_norm == 0:
        raise ValueError("cosine similarity does not accept zero vectors")
    return max(-1.0, min(1.0, dot_product / (first_norm * second_norm)))


def decide_semantic_duplicate(
    incoming: SemanticArticle,
    candidate: SemanticArticle,
    policy: SemanticDuplicatePolicy,
) -> SemanticDuplicateDecision:
    if incoming.normalized_article_id == candidate.normalized_article_id:
        raise ValueError("semantic duplicate comparison requires different articles")
    similarity = cosine_similarity(incoming.vector, candidate.vector)
    distance = simhash_distance(incoming.simhash_hex, candidate.simhash_hex)
    matched = (
        similarity >= policy.minimum_similarity and distance <= policy.maximum_simhash_distance
    )
    left, right = sorted(
        (incoming.normalized_article_id, candidate.normalized_article_id),
        key=lambda value: value.int,
    )
    return SemanticDuplicateDecision(
        left_article_id=left,
        right_article_id=right,
        relation_kind=DuplicateRelationKind.NEAR_DUPLICATE,
        matched=matched,
        features=SemanticDuplicateFeatures(
            cosine_similarity=similarity,
            simhash_distance=distance,
        ),
        threshold=policy.minimum_similarity,
        maximum_simhash_distance=policy.maximum_simhash_distance,
        policy_version=policy.version,
    )
