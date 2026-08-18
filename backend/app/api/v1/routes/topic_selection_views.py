from __future__ import annotations

from typing import Literal, cast

from app.infrastructure.db.models import TopicRerankRecordModel, TopicSelectionRunModel
from app.infrastructure.db.topic_selection import TopicScoreProjection
from app.schemas.topic_rerank import TopicRerankSummaryResponse
from app.schemas.topic_selection import TopicScoreResponse, TopicSelectionRunResponse

TopicDecisionKind = Literal["selected", "no_topic"]
TopicRerankOutcomeValue = Literal["not_applied", "applied", "skipped", "fallback"]


def topic_decision_kind(value: str) -> TopicDecisionKind:
    if value == "selected":
        return "selected"
    if value == "no_topic":
        return "no_topic"
    raise RuntimeError("stored daily topic decision kind is invalid")


def topic_rerank_summary(
    *,
    config_snapshot: dict[str, object],
    config_fingerprint: str,
    record: TopicRerankRecordModel | None,
) -> TopicRerankSummaryResponse:
    enabled = config_snapshot.get("enabled") is True
    policy = config_snapshot.get("policy_version")
    provider = config_snapshot.get("provider")
    model = config_snapshot.get("model")
    projected_provider = provider if isinstance(provider, str) else "unknown"
    projected_model = model if isinstance(model, str) else "unknown"
    outcome: TopicRerankOutcomeValue = (
        cast(TopicRerankOutcomeValue, record.outcome) if record is not None else "not_applied"
    )
    return TopicRerankSummaryResponse(
        outcome=outcome,
        enabled=enabled,
        policy_version=policy if isinstance(policy, str) else "unknown",
        config_fingerprint=config_fingerprint,
        provider=record.provider if record is not None else projected_provider,
        model=record.model if record is not None else projected_model,
        candidate_count=record.candidate_count if record is not None else 0,
        failure_code=record.failure_code if record is not None else None,
        request_fingerprint=record.request_fingerprint if record is not None else None,
        prompt_fingerprint=record.prompt_fingerprint if record is not None else None,
        prompt_tokens=record.prompt_tokens if record is not None else 0,
        completion_tokens=record.completion_tokens if record is not None else 0,
        reasoning_tokens=record.reasoning_tokens if record is not None else 0,
        latency_ms=record.latency_ms if record is not None else 0,
    )


def topic_selection_run_response(
    run: TopicSelectionRunModel,
    record: TopicRerankRecordModel | None = None,
) -> TopicSelectionRunResponse:
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
        rerank_config_fingerprint=run.rerank_config_fingerprint,
        rerank_config=run.rerank_config_snapshot,
        rerank=topic_rerank_summary(
            config_snapshot=run.rerank_config_snapshot,
            config_fingerprint=run.rerank_config_fingerprint,
            record=record,
        ),
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
    rerank_explanation = score.explanation.get("rerank_explanation")
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
        explanation=dict(score.explanation),
        rank=score.rank,
        deterministic_rank=score.deterministic_rank,
        final_rank=score.rank,
        rerank_reason_codes=[
            str(code) for code in score.explanation.get("rerank_reason_codes", [])
        ],
        rerank_explanation=(rerank_explanation if isinstance(rerank_explanation, str) else None),
    )
