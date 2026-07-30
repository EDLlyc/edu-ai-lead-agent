from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.governance_enums import DuplicateRelationKind
from app.domain.value_objects import is_sha256_hex


@dataclass(frozen=True, slots=True)
class ExactDuplicateArtifact:
    normalized_article_id: UUID
    candidate_id: UUID
    source_id: UUID
    normalized_hash: str
    input_content_hash: str
    canonical_url: str
    source_item_id: str
    first_fetched_at: datetime
    occurrence_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        if self.first_fetched_at.tzinfo is None:
            raise ValueError("exact-duplicate fetch time must be timezone-aware")
        if not is_sha256_hex(self.normalized_hash) or not is_sha256_hex(self.input_content_hash):
            raise ValueError("exact-duplicate hashes must be lowercase SHA-256 hex digests")
        if not self.canonical_url.strip() or not self.source_item_id.strip():
            raise ValueError("exact-duplicate source identities must not be blank")
        if len(self.occurrence_ids) != len(set(self.occurrence_ids)):
            raise ValueError("occurrence IDs must be unique")
        if not self.occurrence_ids:
            raise ValueError("exact-duplicate artifacts must preserve at least one occurrence ID")


@dataclass(frozen=True, slots=True)
class ExactDuplicateRelation:
    left_article_id: UUID
    right_article_id: UUID
    relation_kind: DuplicateRelationKind


@dataclass(frozen=True, slots=True)
class ExactDuplicateDecision:
    canonical: ExactDuplicateArtifact
    duplicates: tuple[ExactDuplicateArtifact, ...]
    relations: tuple[ExactDuplicateRelation, ...]
    occurrence_ids: tuple[UUID, ...]


def exact_duplicate_reasons(
    first: ExactDuplicateArtifact, second: ExactDuplicateArtifact
) -> tuple[DuplicateRelationKind, ...]:
    reasons: list[DuplicateRelationKind] = []
    if first.normalized_hash == second.normalized_hash:
        reasons.append(DuplicateRelationKind.SAME_CONTENT)
    if (
        first.canonical_url == second.canonical_url
        and first.input_content_hash == second.input_content_hash
    ):
        reasons.append(DuplicateRelationKind.SAME_URL)
    if (
        first.source_id == second.source_id
        and first.source_item_id == second.source_item_id
        and first.input_content_hash == second.input_content_hash
    ):
        reasons.append(DuplicateRelationKind.SAME_SOURCE_ITEM)
    return tuple(reasons)


def select_exact_duplicate_canonical(
    incoming: ExactDuplicateArtifact,
    existing: tuple[ExactDuplicateArtifact, ...],
) -> ExactDuplicateDecision | None:
    matches = tuple(
        artifact for artifact in existing if exact_duplicate_reasons(incoming, artifact)
    )
    if not matches:
        return None
    by_article_id = {artifact.normalized_article_id: artifact for artifact in (*matches, incoming)}
    pool = tuple(by_article_id.values())
    canonical = min(
        pool,
        key=lambda artifact: (
            artifact.first_fetched_at,
            artifact.candidate_id.int,
            artifact.normalized_article_id.int,
        ),
    )
    duplicates = tuple(
        sorted(
            (artifact for artifact in pool if artifact != canonical),
            key=lambda artifact: (artifact.first_fetched_at, artifact.candidate_id.int),
        )
    )
    relations: list[ExactDuplicateRelation] = []
    ordered_pool = sorted(pool, key=lambda artifact: artifact.normalized_article_id.int)
    for index, first in enumerate(ordered_pool):
        for second in ordered_pool[index + 1 :]:
            reasons = exact_duplicate_reasons(first, second)
            if not reasons:
                continue
            relations.extend(
                ExactDuplicateRelation(
                    left_article_id=first.normalized_article_id,
                    right_article_id=second.normalized_article_id,
                    relation_kind=reason,
                )
                for reason in reasons
            )
    occurrence_ids = tuple(
        sorted(
            {occurrence_id for artifact in pool for occurrence_id in artifact.occurrence_ids},
            key=lambda value: value.int,
        )
    )
    return ExactDuplicateDecision(
        canonical=canonical,
        duplicates=duplicates,
        relations=tuple(relations),
        occurrence_ids=occurrence_ids,
    )
