from __future__ import annotations

from uuid import UUID, uuid5

from app.domain.governance_entities import GovernanceVersionBundle
from app.domain.value_objects import stable_key

GOVERNANCE_NAMESPACE = UUID("fcb20f57-e3dc-4dff-aef8-7ff1f8778104")


def governance_job_idempotency_key(
    candidate_id: UUID, input_content_hash: str, bundle: GovernanceVersionBundle
) -> str:
    return stable_key(candidate_id, input_content_hash, bundle.fingerprint)


def source_occurrence_key(
    candidate_id: UUID, observation_id: UUID, snapshot_id: UUID, source_item_id: str
) -> str:
    return stable_key(candidate_id, observation_id, snapshot_id, source_item_id)


def stable_passage_id(
    candidate_id: UUID,
    normalization_version: str,
    ordinal: int,
    passage_hash: str,
) -> UUID:
    value = stable_key(candidate_id, normalization_version, ordinal, passage_hash)
    return uuid5(GOVERNANCE_NAMESPACE, value)


def stable_governance_artifact_id(kind: str, *parts: object) -> UUID:
    if not kind.strip():
        raise ValueError("governance artifact kind must not be blank")
    return uuid5(GOVERNANCE_NAMESPACE, stable_key(kind, *parts))


def event_assignment_advisory_key(normalized_article_id: UUID, policy_version: str) -> int:
    unsigned = int(stable_key(normalized_article_id, policy_version)[:16], 16)
    return unsigned if unsigned < 2**63 else unsigned - 2**64


def event_assignment_lane_advisory_key(policy_version: str) -> int:
    unsigned = int(stable_key("event-assignment-lane", policy_version)[:16], 16)
    return unsigned if unsigned < 2**63 else unsigned - 2**64


def canonical_candidate_pair(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    if first == second:
        raise ValueError("duplicate relation requires two different candidates")
    if first.int < second.int:
        return first, second
    return second, first
