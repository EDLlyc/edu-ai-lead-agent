"""PostgreSQL planner for one immutable production weekly input."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.official_account_weekly_production import (
    WeeklyProductionInput,
    WeeklyProductionInputItem,
)
from app.domain.editorial_relevance import (
    ScienceTechContentSignal,
    ScienceTechEditorialCohort,
)
from app.domain.official_account_weekly_edition import (
    WeeklyArticleSelection,
    WeeklyEditionSchedule,
    WeeklyGovernedCandidate,
    select_weekly_articles,
)
from app.domain.topic_selection import TopicCandidate, TopicScore, TopicVetoCode
from app.infrastructure.db.models import (
    ContentSlotScoreModel,
    ContentSlotSelectionModel,
    CopyGenerationRunModel,
    EventClusterVersionModel,
    EventMembershipModel,
    EvidenceCandidateModel,
    ImageArtifactModel,
    MaterialPackageModel,
    NormalizedArticleModel,
    SourceModel,
    SourceVersionModel,
    TopicScoreModel,
)


@dataclass(frozen=True, slots=True)
class _MaterialCandidate:
    package: MaterialPackageModel
    run: CopyGenerationRunModel
    event_version: EventClusterVersionModel
    score: TopicScoreModel | ContentSlotScoreModel
    governed: WeeklyGovernedCandidate
    score_fingerprint: str


class PostgresWeeklyProductionInputPlanner:
    """Select real delivered packages through stored scoring and source authority."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def plan(
        self,
        *,
        week_start: date,
        cutoff: datetime,
    ) -> WeeklyProductionInput:
        schedule = WeeklyEditionSchedule()
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("weekly production cutoff must be timezone-aware")
        if week_start.weekday() != 0:
            raise ValueError("weekly production week start must be a Monday")
        async with self._session_factory() as session:
            rows = await self._load_material_rows(session, cutoff=cutoff)
            score_by_package = await self._load_scores(session, rows)
            authority = await self._load_source_authority(
                session,
                {run.selected_event_id for _package, run, _version, _image in rows},
            )

        candidates: dict[UUID, _MaterialCandidate] = {}
        for package, run, event_version, image in rows:
            event_id = run.selected_event_id
            event_version_id = run.selected_event_version_id
            if event_id is None or event_version_id is None:
                continue
            score = score_by_package.get(package.id)
            source_rows = authority.get(event_id, ())
            if score is None or not source_rows or not _material_is_eligible(package, image):
                continue
            governed, score_fingerprint = _governed_candidate(
                run=run,
                event_version=event_version,
                score=score,
                source_rows=source_rows,
            )
            current = candidates.get(event_id)
            if current is None or (package.created_at, str(package.id)) > (
                current.package.created_at,
                str(current.package.id),
            ):
                candidates[event_id] = _MaterialCandidate(
                    package=package,
                    run=run,
                    event_version=event_version,
                    score=score,
                    governed=governed,
                    score_fingerprint=score_fingerprint,
                )
        selection = select_weekly_articles(
            tuple(item.governed for item in candidates.values()),
            week_start=week_start,
            cutoff=cutoff,
            schedule=schedule,
        )
        by_event = {item.governed.candidate.event_id: item for item in candidates.values()}
        items = tuple(
            _production_item(selected, by_event[selected.event_id])
            for selected in selection.selected
        )
        return WeeklyProductionInput(
            week_start=week_start,
            cutoff=cutoff,
            selection=selection,
            items=cast(
                tuple[
                    WeeklyProductionInputItem,
                    WeeklyProductionInputItem,
                    WeeklyProductionInputItem,
                ],
                items,
            ),
        )

    async def _load_material_rows(
        self,
        session: AsyncSession,
        *,
        cutoff: datetime,
    ) -> tuple[
        tuple[
            MaterialPackageModel,
            CopyGenerationRunModel,
            EventClusterVersionModel,
            ImageArtifactModel,
        ],
        ...,
    ]:
        business_floor = (cutoff - timedelta(days=14)).date()
        statement = (
            select(
                MaterialPackageModel,
                CopyGenerationRunModel,
                EventClusterVersionModel,
                ImageArtifactModel,
            )
            .join(CopyGenerationRunModel, CopyGenerationRunModel.id == MaterialPackageModel.run_id)
            .join(
                EventClusterVersionModel,
                EventClusterVersionModel.id == CopyGenerationRunModel.selected_event_version_id,
            )
            .join(
                ImageArtifactModel,
                ImageArtifactModel.id == MaterialPackageModel.image_artifact_id,
            )
            .where(
                CopyGenerationRunModel.business_date >= business_floor,
                CopyGenerationRunModel.business_date <= cutoff.date(),
                MaterialPackageModel.created_at <= cutoff,
            )
            .order_by(MaterialPackageModel.created_at.desc(), MaterialPackageModel.id)
        )
        return tuple((await session.execute(statement)).tuples())

    async def _load_scores(
        self,
        session: AsyncSession,
        rows: tuple[
            tuple[
                MaterialPackageModel,
                CopyGenerationRunModel,
                EventClusterVersionModel,
                ImageArtifactModel,
            ],
            ...,
        ],
    ) -> dict[UUID, TopicScoreModel | ContentSlotScoreModel]:
        daily_run_ids = {
            run.topic_selection_run_id
            for _package, run, _version, _image in rows
            if run.topic_selection_run_id is not None
        }
        slot_selection_ids = {
            run.content_slot_selection_id
            for _package, run, _version, _image in rows
            if run.content_slot_selection_id is not None
        }
        daily_scores = (
            tuple(
                await session.scalars(
                    select(TopicScoreModel).where(TopicScoreModel.run_id.in_(daily_run_ids))
                )
            )
            if daily_run_ids
            else ()
        )
        daily_by_key = {
            (score.run_id, score.event_id, score.event_version_id): score for score in daily_scores
        }
        selections = (
            tuple(
                await session.scalars(
                    select(ContentSlotSelectionModel).where(
                        ContentSlotSelectionModel.id.in_(slot_selection_ids)
                    )
                )
            )
            if slot_selection_ids
            else ()
        )
        slot_score_ids = {selection.score_id for selection in selections}
        slot_scores = (
            tuple(
                await session.scalars(
                    select(ContentSlotScoreModel).where(
                        ContentSlotScoreModel.id.in_(slot_score_ids)
                    )
                )
            )
            if slot_score_ids
            else ()
        )
        slot_by_id = {score.id: score for score in slot_scores}
        selection_score = {
            selection.id: slot_by_id[selection.score_id]
            for selection in selections
            if selection.score_id in slot_by_id
        }
        result: dict[UUID, TopicScoreModel | ContentSlotScoreModel] = {}
        for package, run, _version, _image in rows:
            if run.selected_event_id is None or run.selected_event_version_id is None:
                continue
            score: TopicScoreModel | ContentSlotScoreModel | None = None
            if run.topic_selection_run_id is not None:
                score = daily_by_key.get(
                    (
                        run.topic_selection_run_id,
                        run.selected_event_id,
                        run.selected_event_version_id,
                    )
                )
            elif run.content_slot_selection_id is not None:
                score = selection_score.get(run.content_slot_selection_id)
            if score is not None:
                result[package.id] = score
        return result

    async def _load_source_authority(
        self,
        session: AsyncSession,
        event_ids: set[UUID | None],
    ) -> dict[UUID, tuple[tuple[str, str], ...]]:
        safe_event_ids = {event_id for event_id in event_ids if event_id is not None}
        if not safe_event_ids:
            return {}
        rows = (
            await session.execute(
                select(
                    EventMembershipModel.event_id,
                    SourceModel.organization_type,
                    SourceVersionModel.config_fingerprint,
                )
                .join(
                    NormalizedArticleModel,
                    NormalizedArticleModel.id == EventMembershipModel.normalized_article_id,
                )
                .join(
                    EvidenceCandidateModel,
                    EvidenceCandidateModel.id == NormalizedArticleModel.candidate_id,
                )
                .join(SourceModel, SourceModel.id == EvidenceCandidateModel.source_id)
                .join(
                    SourceVersionModel,
                    SourceVersionModel.id == EvidenceCandidateModel.source_version_id,
                )
                .where(
                    EventMembershipModel.event_id.in_(safe_event_ids),
                    EventMembershipModel.active.is_(True),
                )
            )
        ).tuples()
        grouped: dict[UUID, set[tuple[str, str]]] = {}
        for event_id, organization_type, config_fingerprint in rows:
            grouped.setdefault(event_id, set()).add((organization_type, config_fingerprint))
        return {event_id: tuple(sorted(values)) for event_id, values in grouped.items()}


def _material_is_eligible(package: MaterialPackageModel, image: ImageArtifactModel) -> bool:
    image_audit = image.audit_snapshot if isinstance(image.audit_snapshot, dict) else {}
    return bool(
        package.status in {"ready", "awaiting_manual_use", "completed"}
        and package.review_status != "rejected"
        and package.validation_snapshot.get("passed") is True
        and package.audit_snapshot.get("accepted") is True
        and package.source_snapshot
        and package.brand_snapshot
        and image.status == "succeeded"
        and image.validation_snapshot.get("passed") is True
        and (
            image_audit.get("configured") is not True
            or image_audit.get("status") in {"accepted", "not_applicable"}
        )
        and image.media_type is not None
        and image.byte_size is not None
        and image.sha256 is not None
    )


def _governed_candidate(
    *,
    run: CopyGenerationRunModel,
    event_version: EventClusterVersionModel,
    score: TopicScoreModel | ContentSlotScoreModel,
    source_rows: tuple[tuple[str, str], ...],
) -> tuple[WeeklyGovernedCandidate, str]:
    if run.selected_event_id is None or run.selected_event_version_id is None:
        raise ValueError("weekly production copy run has no selected event")
    if (
        score.event_id != run.selected_event_id
        or score.event_version_id != run.selected_event_version_id
    ):
        raise ValueError("weekly production score lineage changed")
    explanation = score.explanation
    raw = _float_mapping(score.raw_features)
    normalized = _float_mapping(score.normalized_features)
    title = _bounded_string(run_title=event_version.representative_title, maximum=300)
    summary = _bounded_string(
        run_title=str(event_version.summary_projection.get("summary", title)),
        maximum=500,
    )
    cohort_value = explanation.get("science_tech_editorial_cohort")
    cohort = (
        ScienceTechEditorialCohort(str(cohort_value))
        if isinstance(cohort_value, str)
        else ScienceTechEditorialCohort.OUT_OF_SCOPE
    )
    signals = tuple(
        ScienceTechContentSignal(str(value))
        for value in _string_list(explanation.get("science_tech_content_signals"))
    )
    topic_priority_policy = _optional_string(explanation.get("topic_priority_policy"))
    event_time = event_version.event_time_start or event_version.created_at
    candidate = TopicCandidate(
        event_id=run.selected_event_id,
        event_version_id=run.selected_event_version_id,
        event_time=event_time,
        source_trust=_feature(raw, normalized, "source_trust"),
        source_diversity=max(0, round(raw.get("source_diversity", event_version.source_diversity))),
        ai_relevance=_feature(raw, normalized, "ai_relevance"),
        parent_relevance=_feature(raw, normalized, "parent_relevance"),
        communication_potential=_feature(raw, normalized, "communication_potential"),
        science_education_relevance=_feature(raw, normalized, "science_education_relevance"),
        product_matrix_fit=_feature(raw, normalized, "product_matrix_fit"),
        editorial_priority=_feature(raw, normalized, "editorial_priority"),
        science_tech_editorial_cohort=cohort,
        science_tech_education_relevance=_bounded_float(
            explanation.get("science_tech_education_relevance", raw.get("education_relevance", 0.0))
        ),
        frontier_significance=_bounded_float(
            explanation.get("frontier_significance", raw.get("frontier_significance", 0.0))
        ),
        science_tech_editorial_reason_codes=_string_list(
            explanation.get("science_tech_editorial_reason_codes")
        ),
        science_tech_content_signals=signals,
        product_matrix_fit_v2=_feature(raw, normalized, "product_matrix_fit"),
        product_matrix_v2_direction_ids=_string_list(
            explanation.get("product_matrix_direction_ids")
        ),
        topic_priority_policy=topic_priority_policy,
        priority_title=title,
        priority_summary=summary,
        theme_repetition=_feature(raw, normalized, "theme_repetition"),
        controversy_risk=_feature(raw, normalized, "controversy_risk"),
        marketing_risk=_feature(raw, normalized, "marketing_risk"),
    )
    scoring_version = _required_string(explanation.get("scoring_version"), "scoring version")
    scoring_profile = _required_string(explanation.get("scoring_profile"), "scoring profile")
    persisted_score = TopicScore(
        event_id=score.event_id,
        event_version_id=score.event_version_id,
        scoring_version=scoring_version,
        scoring_profile=scoring_profile,
        raw_features=raw,
        normalized_features=normalized,
        weights=_float_mapping(score.weights),
        penalty_weights=_float_mapping(score.penalty_weights),
        positive_components=_float_mapping(score.positive_components),
        penalty_components=_float_mapping(score.penalty_components),
        total=score.total,
        threshold=score.threshold,
        passes_threshold=score.passes_threshold,
        eligible=score.eligible,
        veto_codes=tuple(TopicVetoCode(value) for value in score.veto_codes),
        selection_priority_rule_version=_optional_string(
            explanation.get("selection_priority_rule_version")
        ),
        topic_priority_policy=topic_priority_policy,
        priority_applied=explanation.get("priority_applied") is True,
        priority_reason=str(explanation.get("priority_reason", "not_eligible"))[:80],
        threshold_bypass_applied=explanation.get("threshold_bypass_applied") is True,
        threshold_bypass_reason=_optional_string(explanation.get("threshold_bypass_reason")),
        hard_tech_pool_policy_version=_optional_string(
            explanation.get("hard_tech_pool_policy_version")
        ),
        science_ai_education_rule_version=_optional_string(
            explanation.get("science_ai_education_rule_version")
        ),
        science_tech_editorial_rule_version=_optional_string(
            explanation.get("science_tech_editorial_rule_version")
        ),
        product_matrix_fit_rule_version=_optional_string(
            explanation.get("product_matrix_fit_rule_version")
        ),
        science_ai_education_reason_codes=_string_list(
            explanation.get("science_ai_education_reason_codes")
        ),
        product_matrix_direction_ids=_string_list(explanation.get("product_matrix_direction_ids")),
        science_tech_editorial_cohort=cohort,
        science_tech_education_relevance=candidate.science_tech_education_relevance,
        frontier_significance=candidate.frontier_significance,
        science_tech_editorial_reason_codes=candidate.science_tech_editorial_reason_codes,
        science_tech_content_signals=signals,
        rank=score.rank,
        deterministic_rank=score.deterministic_rank,
        rerank_reason_codes=_string_list(explanation.get("rerank_reason_codes")),
        rerank_explanation=_optional_string(explanation.get("rerank_explanation"), maximum=500),
    )
    organization_types = {organization_type for organization_type, _fingerprint in source_rows}
    organization_type = (
        "government" if "government" in organization_types else sorted(organization_types)[0]
    )
    source_fingerprint = _json_fingerprint(source_rows)
    score_fingerprint = _json_fingerprint(
        {
            "score_id": str(score.id),
            "event_id": str(score.event_id),
            "event_version_id": str(score.event_version_id),
            "raw_features": score.raw_features,
            "normalized_features": score.normalized_features,
            "weights": score.weights,
            "penalty_weights": score.penalty_weights,
            "positive_components": score.positive_components,
            "penalty_components": score.penalty_components,
            "total": score.total,
            "threshold": score.threshold,
            "eligible": score.eligible,
            "veto_codes": score.veto_codes,
            "rank": score.rank,
            "deterministic_rank": score.deterministic_rank,
            "explanation": score.explanation,
        }
    )
    return (
        WeeklyGovernedCandidate(
            candidate=candidate,
            score=persisted_score,
            organization_type=organization_type,
            source_metadata_fingerprint=source_fingerprint,
        ),
        score_fingerprint,
    )


def _production_item(
    selected: WeeklyArticleSelection,
    candidate: _MaterialCandidate,
) -> WeeklyProductionInputItem:
    snapshot_title = candidate.package.topic_snapshot.get("title")
    title = (
        snapshot_title
        if isinstance(snapshot_title, str) and snapshot_title.strip()
        else candidate.event_version.representative_title
    )
    return WeeklyProductionInputItem(
        role=selected.role,
        material_package_id=candidate.package.id,
        event_id=cast(UUID, candidate.run.selected_event_id),
        event_version_id=cast(UUID, candidate.run.selected_event_version_id),
        title=_bounded_string(run_title=title, maximum=300),
        material_request_fingerprint=candidate.package.request_fingerprint,
        score_fingerprint=candidate.score_fingerprint,
        source_metadata_fingerprint=selected.source_metadata_fingerprint,
        organization_type=selected.organization_type,
        official_authority=selected.official_authority,
        selection_reason=selected.selection_reason.value,
        affinity_reasons=selected.affinity_reasons,
        governed_total=selected.governed_total,
        governed_score_version=selected.governed_score_version,
    )


def _json_fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _float_mapping(value: dict[str, Any]) -> dict[str, float]:
    return {str(key): float(item) for key, item in value.items() if isinstance(item, int | float)}


def _feature(raw: dict[str, float], normalized: dict[str, float], key: str) -> float:
    return _bounded_float(normalized.get(key, raw.get(key, 0.0)))


def _bounded_float(value: object) -> float:
    number = float(value) if isinstance(value, int | float) else 0.0
    return min(1.0, max(0.0, number))


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item)[:100] for item in value if isinstance(item, str) and item.strip())


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError(f"weekly production {label} is invalid")
    return value


def _optional_string(value: object, *, maximum: int = 120) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("weekly production optional score metadata is invalid")
    return value


def _bounded_string(*, run_title: str, maximum: int) -> str:
    value = " ".join(run_title.split())
    if not value:
        raise ValueError("weekly production title or summary is empty")
    return value[:maximum]


__all__ = ["PostgresWeeklyProductionInputPlanner"]
