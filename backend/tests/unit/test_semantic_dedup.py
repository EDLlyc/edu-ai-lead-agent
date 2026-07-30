from uuid import UUID

import pytest
from app.domain.governance_enums import DuplicateRelationKind
from app.domain.governance_semantic import (
    SemanticArticle,
    SemanticDuplicatePolicy,
    cosine_similarity,
    decide_semantic_duplicate,
)


def _article(
    article_id: str,
    *,
    vector: tuple[float, ...],
    simhash_hex: str,
) -> SemanticArticle:
    return SemanticArticle(
        normalized_article_id=UUID(article_id),
        candidate_id=UUID(article_id.replace("1", "a").replace("2", "b")),
        simhash_hex=simhash_hex,
        vector=vector,
    )


def test_cosine_similarity_requires_equal_non_zero_vectors() -> None:
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)

    with pytest.raises(ValueError, match="equal non-empty"):
        cosine_similarity((1.0,), (1.0, 0.0))
    with pytest.raises(ValueError, match="zero vectors"):
        cosine_similarity((0.0, 0.0), (1.0, 0.0))


def test_semantic_duplicate_requires_both_embedding_and_simhash_thresholds() -> None:
    incoming = _article(
        "11111111-1111-4111-8111-111111111111",
        vector=(1.0, 0.0),
        simhash_hex="0000000000000000",
    )
    policy = SemanticDuplicatePolicy(
        version="semantic-v1",
        minimum_similarity=0.94,
        maximum_simhash_distance=2,
    )
    matched = decide_semantic_duplicate(
        incoming,
        _article(
            "22222222-2222-4222-8222-222222222222",
            vector=(0.95, 0.3122498999),
            simhash_hex="0000000000000003",
        ),
        policy,
    )
    distant_simhash = decide_semantic_duplicate(
        incoming,
        _article(
            "22222222-2222-4222-8222-222222222222",
            vector=(0.99, 0.1410673598),
            simhash_hex="000000000000000f",
        ),
        policy,
    )
    weak_embedding = decide_semantic_duplicate(
        incoming,
        _article(
            "22222222-2222-4222-8222-222222222222",
            vector=(0.90, 0.4358898944),
            simhash_hex="0000000000000001",
        ),
        policy,
    )

    assert matched.matched is True
    assert matched.relation_kind is DuplicateRelationKind.NEAR_DUPLICATE
    assert matched.threshold == 0.94
    assert matched.maximum_simhash_distance == 2
    assert distant_simhash.matched is False
    assert weak_embedding.matched is False


def test_semantic_decision_uses_stable_article_order_and_rejects_self_comparison() -> None:
    higher = _article(
        "22222222-2222-4222-8222-222222222222",
        vector=(1.0, 0.0),
        simhash_hex="0000000000000000",
    )
    lower = _article(
        "11111111-1111-4111-8111-111111111111",
        vector=(1.0, 0.0),
        simhash_hex="0000000000000000",
    )
    decision = decide_semantic_duplicate(
        higher,
        lower,
        SemanticDuplicatePolicy(version="semantic-v1"),
    )

    assert decision.left_article_id == lower.normalized_article_id
    assert decision.right_article_id == higher.normalized_article_id
    with pytest.raises(ValueError, match="different articles"):
        decide_semantic_duplicate(lower, lower, SemanticDuplicatePolicy(version="semantic-v1"))
