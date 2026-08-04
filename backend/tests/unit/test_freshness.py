from datetime import UTC, datetime, timedelta

import pytest
from app.domain.freshness import evaluate_publication_freshness

EVALUATED_AT = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def test_publication_at_exact_ten_day_boundary_is_fresh() -> None:
    decision = evaluate_publication_freshness(
        EVALUATED_AT - timedelta(days=10),
        evaluated_at=EVALUATED_AT,
        max_age_days=10,
    )

    assert decision.status == "fresh"
    assert decision.reason_code == "fresh_within_window"


def test_publication_one_second_before_boundary_is_stale() -> None:
    decision = evaluate_publication_freshness(
        EVALUATED_AT - timedelta(days=10, seconds=1),
        evaluated_at=EVALUATED_AT,
        max_age_days=10,
    )

    assert decision.status == "stale"
    assert decision.reason_code == "stale_beyond_window"


def test_unknown_publication_time_is_not_eligible() -> None:
    decision = evaluate_publication_freshness(
        None,
        evaluated_at=EVALUATED_AT,
        max_age_days=10,
    )

    assert decision.status == "unknown"
    assert decision.eligible is False
    assert decision.cutoff_at == EVALUATED_AT - timedelta(days=10)


def test_freshness_rejects_naive_instants() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_publication_freshness(
            datetime(2026, 8, 3, 12),
            evaluated_at=EVALUATED_AT,
            max_age_days=10,
        )
