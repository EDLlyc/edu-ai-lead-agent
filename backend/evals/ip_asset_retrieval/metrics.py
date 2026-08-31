from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    recall_at_5: float
    mrr_at_5: float
    ndcg_at_5: float
    zero_result: bool


def score_ranking(
    *, selected_ids: tuple[str, ...], relevance_by_id: dict[str, int]
) -> RetrievalMetrics:
    relevant = {candidate_id for candidate_id, grade in relevance_by_id.items() if grade > 0}
    selected = selected_ids[:5]
    recalled = len(relevant.intersection(selected))
    recall = recalled / len(relevant) if relevant else 1.0
    first_relevant = next(
        (rank for rank, candidate_id in enumerate(selected, start=1) if candidate_id in relevant),
        None,
    )
    mrr = 1.0 / first_relevant if first_relevant is not None else (1.0 if not relevant else 0.0)
    gains = [relevance_by_id[candidate_id] for candidate_id in selected]
    dcg = _dcg(gains)
    ideal = _dcg(sorted(relevance_by_id.values(), reverse=True)[:5])
    ndcg = dcg / ideal if ideal else 1.0
    return RetrievalMetrics(
        recall_at_5=recall,
        mrr_at_5=mrr,
        ndcg_at_5=ndcg,
        zero_result=not selected,
    )


def _dcg(grades: list[int]) -> float:
    return float(
        sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1))
    )
