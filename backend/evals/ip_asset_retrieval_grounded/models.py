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
EXPECTED_ASSET_COUNT = 41
EXPECTED_QUERY_COUNT = 100


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
