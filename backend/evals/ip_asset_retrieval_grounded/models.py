from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ASSET_SNAPSHOT_SCHEMA_VERSION: Literal["ip-asset-grounded-assets-v1"] = (
    "ip-asset-grounded-assets-v1"
)
QUERY_SCHEMA_VERSION: Literal["ip-asset-grounded-query-v1"] = "ip-asset-grounded-query-v1"
SEED_SCHEMA_VERSION: Literal["ip-asset-grounded-codex-seed-v1"] = "ip-asset-grounded-codex-seed-v1"
RUN_SCHEMA_VERSION: Literal["ip-asset-grounded-run-v1"] = "ip-asset-grounded-run-v1"
RUBRIC_VERSION: Literal["ip-asset-relevance-rubric-v1"] = "ip-asset-relevance-rubric-v1"
EVALUATOR_VERSION: Literal["codex-visual-review-v1"] = "codex-visual-review-v1"
QUERY_V2_SCHEMA_VERSION: Literal["ip-asset-grounded-query-v2"] = "ip-asset-grounded-query-v2"
SEED_V2_SCHEMA_VERSION: Literal["ip-asset-grounded-codex-seed-v2"] = (
    "ip-asset-grounded-codex-seed-v2"
)
REVIEW_V2_SCHEMA_VERSION: Literal["ip-asset-grounded-codex-review-v2"] = (
    "ip-asset-grounded-codex-review-v2"
)
ROBUSTNESS_V2_SCHEMA_VERSION: Literal["ip-asset-grounded-robustness-v2"] = (
    "ip-asset-grounded-robustness-v2"
)
RUN_V2_SCHEMA_VERSION: Literal["ip-asset-grounded-run-v2"] = "ip-asset-grounded-run-v2"
RUBRIC_V2_VERSION: Literal["ip-asset-relevance-rubric-v2"] = "ip-asset-relevance-rubric-v2"
EVALUATOR_V2_VERSION: Literal["codex-visual-review-v2"] = "codex-visual-review-v2"
EXPECTED_ASSET_COUNT = 41
EXPECTED_QUERY_COUNT = 100
EXPECTED_V2_QUERY_COUNT = 124
EXPECTED_V2_NO_ANSWER_COUNT = 30


class GroundedQueryCategory(StrEnum):
    CHARACTER = "character"
    ASSET_TYPE = "asset_type"
    EMOTION = "emotion"
    ACTION = "action"
    SCENE = "scene"
    INTENDED_USE = "intended_use"
    TRANSPARENT_BACKGROUND = "transparent_background"
    COMBINED_CONSTRAINTS = "combined_constraints"
    PARAPHRASE = "paraphrase"
    NOISY_ALIAS = "noisy_alias"
    NO_ANSWER = "no_answer"


class GroundedChallengeKind(StrEnum):
    NONEXISTENT_CHARACTER = "nonexistent_character"
    WRONG_SCENE = "wrong_scene"
    CONTRADICTORY_CONSTRAINTS = "contradictory_constraints"
    UNSUPPORTED_VISIBLE_TEXT = "unsupported_visible_text"
    UNAVAILABLE_ACTION_OR_USE = "unavailable_action_or_use"
    SEMANTIC_NEAR_MISS = "semantic_near_miss"


class GroundedRobustnessRelation(StrEnum):
    PARAPHRASE_NEAR_MISS = "paraphrase_near_miss"
    NOISY_ALIAS_NEAR_MISS = "noisy_alias_near_miss"
    FILTER_MONOTONICITY = "filter_monotonicity"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SafeGroundedAsset(_FrozenModel):
    catalog_ref: str = Field(pattern=r"^[a-f0-9]{16}$")
    display_name: str = Field(min_length=1, max_length=80)
    asset_kind: Literal["identity", "action"]
    characters: tuple[Literal["xiao-sai", "sai-xiansheng"], ...] = Field(min_length=1, max_length=2)
    roles: tuple[str, ...] = Field(min_length=1, max_length=2)
    poses: tuple[str, ...] = Field(max_length=8)
    scene_tags: tuple[str, ...] = Field(max_length=8)
    topics: tuple[str, ...] = Field(max_length=12)
    selection_tags: tuple[str, ...] = Field(max_length=24)
    width: int = Field(ge=256, le=10_000)
    height: int = Field(ge=256, le=10_000)
    has_alpha: bool


class SafeGroundedAssetSnapshot(_FrozenModel):
    schema_version: Literal["ip-asset-grounded-assets-v1"]
    catalog_version: str = Field(min_length=1, max_length=120)
    asset_set_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    assets: tuple[SafeGroundedAsset, ...] = Field(
        min_length=EXPECTED_ASSET_COUNT,
        max_length=EXPECTED_ASSET_COUNT,
    )

    @model_validator(mode="after")
    def validate_unique_assets(self) -> SafeGroundedAssetSnapshot:
        refs = [asset.catalog_ref for asset in self.assets]
        if len(refs) != len(set(refs)):
            raise ValueError("grounded asset refs must be unique")
        if refs != sorted(refs):
            raise ValueError("grounded assets must be sorted by catalog ref")
        return self


class GroundedQuery(_FrozenModel):
    schema_version: Literal["ip-asset-grounded-query-v1"]
    query_ref: str = Field(pattern=r"^[a-z0-9-]{3,80}$")
    category: GroundedQueryCategory
    split: Literal["dev", "holdout"]
    query: str = Field(min_length=1, max_length=200)
    expected_answer_kind: Literal["has_relevant", "no_answer"]


class GroundedQueryV2(_FrozenModel):
    schema_version: Literal["ip-asset-grounded-query-v2"]
    query_ref: str = Field(pattern=r"^[a-z0-9-]{3,80}$")
    category: GroundedQueryCategory
    split: Literal["dev", "holdout"]
    query: str = Field(min_length=1, max_length=200)
    expected_answer_kind: Literal["has_relevant", "no_answer"]
    challenge_kind: GroundedChallengeKind | None = None


class GroundedRelevanceGrade(_FrozenModel):
    catalog_ref: str = Field(pattern=r"^[a-f0-9]{16}$")
    grade: int = Field(ge=0, le=3)


class GroundedSeedMatrix(_FrozenModel):
    schema_version: Literal["ip-asset-grounded-codex-seed-v1"]
    query_ref: str = Field(pattern=r"^[a-z0-9-]{3,80}$")
    label_source: Literal["codex_seed"]
    evaluator_version: Literal["codex-visual-review-v1"]
    rubric_version: Literal["ip-asset-relevance-rubric-v1"]
    grades: tuple[GroundedRelevanceGrade, ...] = Field(
        min_length=EXPECTED_ASSET_COUNT,
        max_length=EXPECTED_ASSET_COUNT,
    )

    @model_validator(mode="after")
    def validate_unique_grades(self) -> GroundedSeedMatrix:
        refs = [grade.catalog_ref for grade in self.grades]
        if len(refs) != len(set(refs)):
            raise ValueError("grounded seed asset refs must be unique")
        if refs != sorted(refs):
            raise ValueError("grounded seed grades must be sorted by catalog ref")
        return self


class GroundedSeedMatrixV2(_FrozenModel):
    schema_version: Literal["ip-asset-grounded-codex-seed-v2"]
    query_ref: str = Field(pattern=r"^[a-z0-9-]{3,80}$")
    label_source: Literal["codex_seed_v2"]
    evaluator_version: Literal["codex-visual-review-v2"]
    rubric_version: Literal["ip-asset-relevance-rubric-v2"]
    grades: tuple[GroundedRelevanceGrade, ...] = Field(
        min_length=EXPECTED_ASSET_COUNT,
        max_length=EXPECTED_ASSET_COUNT,
    )

    @model_validator(mode="after")
    def validate_unique_grades(self) -> GroundedSeedMatrixV2:
        refs = [grade.catalog_ref for grade in self.grades]
        if len(refs) != len(set(refs)):
            raise ValueError("grounded Seed V2 asset refs must be unique")
        if refs != sorted(refs):
            raise ValueError("grounded Seed V2 grades must be sorted by catalog ref")
        return self


class GroundedGradeReviewChange(_FrozenModel):
    query_ref: str = Field(pattern=r"^[a-z0-9-]{3,80}$")
    catalog_ref: str = Field(pattern=r"^[a-f0-9]{16}$")
    old_grade: int = Field(ge=0, le=3)
    new_grade: int = Field(ge=0, le=3)
    reason_code: Literal[
        "missing_required_character",
        "missing_required_action",
        "missing_required_scene",
        "missing_required_object",
    ]

    @model_validator(mode="after")
    def validate_changed_grade(self) -> GroundedGradeReviewChange:
        if self.old_grade == self.new_grade:
            raise ValueError("grounded Seed V2 review ledger needs an actual grade change")
        return self


class GroundedSeedReviewLedgerV2(_FrozenModel):
    schema_version: Literal["ip-asset-grounded-codex-review-v2"]
    review_pass_id: Literal["codex-blind-risk-review-v2"]
    evaluator_version: Literal["codex-visual-review-v2"]
    source_seed_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    rank_or_score_observations_opened: Literal[False]
    independent_human_review: Literal[False]
    reviewed_asset_count: Literal[41]
    reviewed_scopes: tuple[
        Literal[
            "v1_no_answer_queries",
            "v1_combined_constraint_queries",
            "v1_grade_1_2_boundaries",
            "fixed_space_station_query",
        ],
        ...,
    ] = Field(min_length=4, max_length=4)
    changes: tuple[GroundedGradeReviewChange, ...] = Field(max_length=64)

    @model_validator(mode="after")
    def validate_unique_changes(self) -> GroundedSeedReviewLedgerV2:
        if self.reviewed_scopes != (
            "v1_no_answer_queries",
            "v1_combined_constraint_queries",
            "v1_grade_1_2_boundaries",
            "fixed_space_station_query",
        ):
            raise ValueError("grounded Seed V2 review scopes are incomplete or unordered")
        identities = [(item.query_ref, item.catalog_ref) for item in self.changes]
        if len(identities) != len(set(identities)):
            raise ValueError("grounded Seed V2 review changes must be unique")
        if identities != sorted(identities):
            raise ValueError("grounded Seed V2 review changes must be sorted")
        return self


class GroundedRobustnessPairV2(_FrozenModel):
    schema_version: Literal["ip-asset-grounded-robustness-v2"]
    challenge_query_ref: str = Field(pattern=r"^[a-z0-9-]{3,80}$")
    anchor_query_ref: str = Field(pattern=r"^[a-z0-9-]{3,80}$")
    relation: GroundedRobustnessRelation
    constraint_dimension: Literal[
        "character",
        "scene",
        "action",
        "visible_text",
        "background",
        "object",
    ]
    expected_relation: Literal["anchor_answers_challenge_abstains"]


class GroundedQueryObservation(_FrozenModel):
    query_ref: str = Field(pattern=r"^[a-z0-9-]{3,80}$")
    mode: Literal["semantic", "degraded_metadata"] | None
    degraded_reason: str | None = Field(default=None, pattern=r"^[a-z0-9_]{3,80}$")
    selected_catalog_refs: tuple[str, ...] = Field(max_length=8)
    failure_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]{3,80}$")

    @model_validator(mode="after")
    def validate_outcome(self) -> GroundedQueryObservation:
        if len(self.selected_catalog_refs) != len(set(self.selected_catalog_refs)):
            raise ValueError("grounded run selected refs must be unique")
        if any(
            len(ref) != 16 or any(character not in "0123456789abcdef" for character in ref)
            for ref in self.selected_catalog_refs
        ):
            raise ValueError("grounded run selected ref is invalid")
        if self.failure_code is None and self.mode is None:
            raise ValueError("successful grounded observation needs a search mode")
        if self.failure_code is not None and (
            self.mode is not None or self.degraded_reason is not None or self.selected_catalog_refs
        ):
            raise ValueError("failed grounded observation cannot contain search output")
        if self.mode == "semantic" and self.degraded_reason is not None:
            raise ValueError("semantic grounded observation cannot contain a degraded reason")
        if self.mode == "degraded_metadata" and self.degraded_reason is None:
            raise ValueError("degraded grounded observation needs a reason")
        return self


class GroundedDecisionEvidence(_FrozenModel):
    top_semantic_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)
    semantic_margin: float | None = Field(default=None, ge=0.0, le=2.0)
    metadata_match_score: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata_match_count: int = Field(ge=0, le=64)
    evidence_lane_count: int = Field(ge=0, le=2)

    @model_validator(mode="after")
    def validate_semantic_evidence(self) -> GroundedDecisionEvidence:
        if self.semantic_margin is not None and self.top_semantic_similarity is None:
            raise ValueError("semantic margin needs a top semantic similarity")
        return self


class GroundedQueryObservationV2(_FrozenModel):
    query_ref: str = Field(pattern=r"^[a-z0-9-]{3,80}$")
    mode: Literal["semantic", "degraded_metadata"] | None
    degraded_reason: str | None = Field(default=None, pattern=r"^[a-z0-9_]{3,80}$")
    selected_catalog_refs: tuple[str, ...] = Field(max_length=8)
    decision_evidence: GroundedDecisionEvidence | None
    failure_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]{3,80}$")

    @model_validator(mode="after")
    def validate_outcome(self) -> GroundedQueryObservationV2:
        if len(self.selected_catalog_refs) != len(set(self.selected_catalog_refs)):
            raise ValueError("grounded Seed V2 run selected refs must be unique")
        if any(
            len(ref) != 16 or any(character not in "0123456789abcdef" for character in ref)
            for ref in self.selected_catalog_refs
        ):
            raise ValueError("grounded Seed V2 run selected ref is invalid")
        if self.failure_code is None and (self.mode is None or self.decision_evidence is None):
            raise ValueError("successful grounded Seed V2 observation needs mode and evidence")
        if self.failure_code is not None and (
            self.mode is not None
            or self.degraded_reason is not None
            or self.selected_catalog_refs
            or self.decision_evidence is not None
        ):
            raise ValueError("failed grounded Seed V2 observation cannot contain search output")
        if self.mode == "semantic" and self.degraded_reason is not None:
            raise ValueError("semantic grounded Seed V2 observation cannot be degraded")
        if self.mode == "degraded_metadata" and self.degraded_reason is None:
            raise ValueError("degraded grounded Seed V2 observation needs a reason")
        return self


class GroundedRetrievalRun(_FrozenModel):
    schema_version: Literal["ip-asset-grounded-run-v1"]
    run_ref: str = Field(pattern=r"^igr_[a-f0-9]{20}$")
    created_at: str = Field(min_length=20, max_length=40)
    maturity: Literal["seed"]
    search_version: str = Field(pattern=r"^ip-asset-hybrid-v[0-9]+(?:-[a-z0-9-]+)?$")
    embedding_execution_mode: Literal["fake", "alibaba"]
    embedding_provider: str = Field(min_length=1, max_length=80)
    embedding_model: str = Field(min_length=1, max_length=120)
    embedding_dimensions: int = Field(ge=1, le=10_000)
    embedding_input_policy_version: str = Field(min_length=1, max_length=120)
    asset_set_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    query_dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    seed_dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    observations: tuple[GroundedQueryObservation, ...] = Field(
        min_length=EXPECTED_QUERY_COUNT,
        max_length=EXPECTED_QUERY_COUNT,
    )

    @model_validator(mode="after")
    def validate_unique_queries(self) -> GroundedRetrievalRun:
        refs = [observation.query_ref for observation in self.observations]
        if len(refs) != len(set(refs)):
            raise ValueError("grounded run query refs must be unique")
        if refs != sorted(refs):
            raise ValueError("grounded run observations must be sorted by query ref")
        return self


class GroundedRetrievalRunV2(_FrozenModel):
    schema_version: Literal["ip-asset-grounded-run-v2"]
    run_ref: str = Field(pattern=r"^igr_[a-f0-9]{20}$")
    created_at: str = Field(min_length=20, max_length=40)
    maturity: Literal["seed"]
    search_version: str = Field(pattern=r"^ip-asset-hybrid-v[0-9]+(?:-[a-z0-9-]+)?$")
    embedding_execution_mode: Literal["fake", "alibaba"]
    embedding_provider: str = Field(min_length=1, max_length=80)
    embedding_model: str = Field(min_length=1, max_length=120)
    embedding_dimensions: int = Field(ge=1, le=10_000)
    embedding_input_policy_version: str = Field(min_length=1, max_length=120)
    asset_set_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    query_dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    seed_dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    robustness_dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_ledger_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duration_ms: int = Field(ge=0)
    provider_request_count: int = Field(ge=0, le=EXPECTED_V2_QUERY_COUNT)
    input_token_count: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0.0)
    observations: tuple[GroundedQueryObservationV2, ...] = Field(
        min_length=EXPECTED_V2_QUERY_COUNT,
        max_length=EXPECTED_V2_QUERY_COUNT,
    )

    @model_validator(mode="after")
    def validate_unique_queries(self) -> GroundedRetrievalRunV2:
        refs = [observation.query_ref for observation in self.observations]
        if len(refs) != len(set(refs)):
            raise ValueError("grounded Seed V2 run query refs must be unique")
        if refs != sorted(refs):
            raise ValueError("grounded Seed V2 run observations must be sorted")
        return self


class GroundedSafeArtifactHash(_FrozenModel):
    artifact_ref: Literal["grounded_run_v2", "selective_report_v2"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class GroundedSafeManifestMetrics(_FrozenModel):
    dev_coverage: float = Field(ge=0.0, le=1.0)
    dev_selective_risk: float | None = Field(default=None, ge=0.0, le=1.0)
    dev_no_answer_false_positive_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    dev_answerable_false_abstention_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    holdout_coverage: float = Field(ge=0.0, le=1.0)
    holdout_selective_risk: float | None = Field(default=None, ge=0.0, le=1.0)
    holdout_no_answer_false_positive_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    holdout_answerable_false_abstention_rate: float | None = Field(default=None, ge=0.0, le=1.0)


class GroundedSafeRunManifestV2(_FrozenModel):
    schema_version: Literal["ip-asset-grounded-safe-manifest-v2"]
    run_ref: str = Field(pattern=r"^igr_[a-f0-9]{20}$")
    git_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    evidence_tier: Literal["model_corpus_quality"]
    maturity: Literal["seed"]
    evaluator_version: Literal["codex-visual-review-v2"]
    rubric_version: Literal["ip-asset-relevance-rubric-v2"]
    search_version: str = Field(pattern=r"^ip-asset-hybrid-v[0-9]+(?:-[a-z0-9-]+)?$")
    embedding_execution_mode: Literal["fake", "alibaba"]
    embedding_provider: str = Field(min_length=1, max_length=80)
    embedding_model: str = Field(min_length=1, max_length=120)
    embedding_input_policy_version: str = Field(min_length=1, max_length=120)
    asset_set_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    query_dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    seed_dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    robustness_dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_ledger_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_policy_ref: str = Field(pattern=r"^selective-v1-[a-z0-9-]+$")
    bootstrap_samples: int = Field(ge=1_000)
    bootstrap_seed: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    provider_request_count: int = Field(ge=0)
    input_token_count: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0.0)
    metrics: GroundedSafeManifestMetrics
    artifacts: tuple[GroundedSafeArtifactHash, GroundedSafeArtifactHash] = Field(
        min_length=2, max_length=2
    )
    validity_notes: tuple[
        Literal[
            "codex_seed_not_human_gold",
            "no_human_agreement",
            "holdout_not_used_for_policy_selection",
            "no_online_effectiveness_claim",
            "cost_unavailable_when_null",
            "harness_bound_to_run_and_artifact_hashes",
            "contamination_not_independently_audited",
            "ambiguous_or_broken_cases_not_independently_adjudicated",
            "corpus_drift_requires_new_asset_set_fingerprint",
        ],
        ...,
    ] = Field(min_length=9, max_length=9)

    @model_validator(mode="after")
    def validate_artifact_identity(self) -> GroundedSafeRunManifestV2:
        refs = [artifact.artifact_ref for artifact in self.artifacts]
        if refs != ["grounded_run_v2", "selective_report_v2"]:
            raise ValueError("grounded safe manifest artifact refs are incomplete or unordered")
        if len(self.validity_notes) != len(set(self.validity_notes)):
            raise ValueError("grounded safe manifest validity notes must be unique")
        return self
