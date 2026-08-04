from __future__ import annotations

from typing import Literal

from app.infrastructure.db.models import TopicSelectionRunModel
from app.infrastructure.db.topic_selection import TopicScoreProjection
from app.schemas.topic_selection import TopicScoreResponse, TopicSelectionRunResponse

TopicDecisionKind = Literal["selected", "no_topic"]


def topic_decision_kind(value: str) -> TopicDecisionKind:
    if value == "selected":
        return "selected"
    if value == "no_topic":
        return "no_topic"
    raise RuntimeError("stored daily topic decision kind is invalid")


def topic_selection_run_response(run: TopicSelectionRunModel) -> TopicSelectionRunResponse:
    config_version = run.config_snapshot.get("version")
    return TopicSelectionRunResponse(
        id=run.id,
        trigger=run.trigger,
        business_date=run.business_date,
        timezone=run.timezone,
        scoring_version=(config_version if isinstance(config_version, str) else "unknown"),
        scoring_profile=run.scoring_profile,
        revision=run.revision,
        config_fingerprint=run.config_fingerprint,
        config=run.config_snapshot,
        status=run.status,
        considered_count=run.total_scores,
        eligible_count=run.eligible_scores,
        selected_event_id=run.selected_event_id,
        selected_event_version_id=run.selected_event_version_id,
        no_topic_code=run.no_topic_code,
        cutoff_at=run.governed_event_cutoff,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        superseded_at=run.superseded_at,
        superseded_by_run_id=run.superseded_by_run_id,
        is_current=run.superseded_at is None,
        status_url=f"/api/v1/topic-selection-runs/{run.id}",
        scores_url=f"/api/v1/topic-selection-runs/{run.id}/scores",
    )


def topic_score_response(row: TopicScoreProjection) -> TopicScoreResponse:
    score = row.score
    explanation_version = score.explanation.get("scoring_version")
    explanation_profile = score.explanation.get("scoring_profile")
    return TopicScoreResponse(
        id=score.id,
        run_id=score.run_id,
        event_id=score.event_id,
        event_version_id=score.event_version_id,
        event_title=row.event_title,
        event_time=row.event_time,
        scoring_version=(
            explanation_version if isinstance(explanation_version, str) else "unknown"
        ),
        scoring_profile=(
            explanation_profile if isinstance(explanation_profile, str) else "unknown"
        ),
        raw_features={key: float(value) for key, value in score.raw_features.items()},
        normalized_features={key: float(value) for key, value in score.normalized_features.items()},
        weights={key: float(value) for key, value in score.weights.items()},
        penalty_weights={key: float(value) for key, value in score.penalty_weights.items()},
        positive_components={key: float(value) for key, value in score.positive_components.items()},
        penalty_components={key: float(value) for key, value in score.penalty_components.items()},
        total=score.total,
        threshold=score.threshold,
        passes_threshold=score.passes_threshold,
        eligible=score.eligible,
        veto_codes=[str(code) for code in score.veto_codes],
        rank=score.rank,
    )
