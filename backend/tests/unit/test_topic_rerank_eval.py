from __future__ import annotations

import pytest
from evals.topic_rerank.runner import _evaluate_case, load_cases


@pytest.mark.asyncio
async def test_priority_fixture_exercises_two_groups_and_preserves_barrier() -> None:
    case = next(case for case in load_cases()[0] if case.case_id == "priority-barrier")

    result = await _evaluate_case(case)

    assert result["priority_groups"] == [0, 1]
    assert result["final_priority_groups"] == [0, 1]
    assert result["final_order_suffixes"] == [1, 2]
    checks = result["checks"]
    assert isinstance(checks, dict)
    assert checks["priority_fixture_groups_are_distinct"] is True
    assert checks["priority_barrier"] is True
    assert result["passed"] is True
