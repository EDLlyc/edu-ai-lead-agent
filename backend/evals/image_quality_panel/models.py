"""Closed contracts for the six-source image model-panel experiment."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from app.domain.image_quality_eval import ImageEvalDimension
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from evals.model_panel import ArmVerdict, CanonicalChoice, PanelIssueCode, evidence_sha256

IMAGE_PANEL_DATASET_VERSION = "image-panel-derived-pairs-v1"
IMAGE_PANEL_RECIPE_VERSION: Final[Literal["image-panel-pillow-recipes-v1"]] = (
    "image-panel-pillow-recipes-v1"
)
IMAGE_PANEL_PROMPT_VERSION = "image-panel-pairwise-judge-v2"
IMAGE_PANEL_RUBRIC_VERSION = "image-panel-six-dimension-rubric-v1"
IMAGE_PANEL_SOURCE_SCHEMA_VERSION = "image-panel-sources-v1"
IMAGE_PANEL_AUTHORIZATION_BASIS = "project_owner_authorized_external_evaluation_2026-09-02"
IMAGE_PANEL_REPORT_DISCLAIMER = (
    "Automated single-model calibration over deterministic derivatives from six public source "
    "families. Objective recipe anchors are the only correctness labels; subjective cases have "
    "external_label_n=0. The 48 derived pairs are not 48 independent real images, and this is "
    "not Human Gold, model consensus, or human agreement evidence."
)

SafeId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=192, pattern=r"^[A-Za-z0-9][A-Za-z0-9:_.\/-]*$"),
]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitBlobOid = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)


class DatasetSplit(StrEnum):
    CALIBRATION = "calibration"
    HOLDOUT = "holdout"


class GoldKind(StrEnum):
    OBJECTIVE_RECIPE = "objective_recipe"
    SUBJECTIVE_UNLABELED = "subjective_unlabeled"


class EvaluatorRole(StrEnum):
    EVALUATOR = "evaluator"


class SourceArtifact(FrozenModel):
    source_family: SafeId
    split: DatasetSplit | None = None
    repository_path: str = Field(min_length=1, max_length=320)
    git_blob_oid: GitBlobOid
    content_sha256: Sha256Hex
    media_type: Literal["image/png", "image/jpeg"]
    byte_size: int = Field(ge=1, le=16 * 1024 * 1024)
    width: int = Field(ge=64, le=16_384)
    height: int = Field(ge=64, le=16_384)
    derivative_of: str | None


class SourceCatalog(FrozenModel):
    schema_version: Literal["image-panel-sources-v1"]
    catalog_version: SafeId
    external_model_use_basis: Literal["project_owner_authorized_external_evaluation_2026-09-02"]
    sources: tuple[SourceArtifact, ...] = Field(min_length=6, max_length=6)
    derivatives: tuple[SourceArtifact, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        all_paths = tuple(item.repository_path for item in (*self.sources, *self.derivatives))
        if len(all_paths) != len(set(all_paths)):
            raise ValueError("source and derivative repository paths must be unique")
        families = tuple(item.source_family for item in self.sources)
        if len(families) != 6 or len(families) != len(set(families)):
            raise ValueError("source catalog requires exactly six independent families")
        source_paths = {item.repository_path: item for item in self.sources}
        if any(item.derivative_of is not None or item.split is None for item in self.sources):
            raise ValueError("independent sources require a split and cannot be derivatives")
        for derivative in self.derivatives:
            parent = source_paths.get(derivative.derivative_of or "")
            if parent is None or parent.source_family != derivative.source_family:
                raise ValueError("every derivative must bind to its source family")
            if derivative.split is not None:
                raise ValueError("derivatives inherit their parent split")
        return self


class ImageArtifact(FrozenModel):
    artifact_ref: SafeId
    media_type: Literal["image/jpeg"]
    byte_size: int = Field(ge=1, le=16 * 1024 * 1024)
    sha256: Sha256Hex


class ImageArm(FrozenModel):
    artifacts: tuple[ImageArtifact, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def unique_artifacts(self) -> Self:
        refs = tuple(item.artifact_ref for item in self.artifacts)
        if len(refs) != len(set(refs)):
            raise ValueError("arm artifact references must be unique")
        return self


class ImagePanelCase(FrozenModel):
    schema_version: Literal["image-panel-case-v1"] = "image-panel-case-v1"
    case_ref: SafeId
    pair_ref: SafeId
    dimension: ImageEvalDimension
    split: DatasetSplit
    source_families: tuple[SafeId, ...] = Field(min_length=1, max_length=2)
    gold_kind: GoldKind
    arm_0: ImageArm
    arm_1: ImageArm
    reference: ImageArtifact | None = None
    gold_choice: CanonicalChoice | None = None
    gold_first_verdict: ArmVerdict | None = None
    gold_second_verdict: ArmVerdict | None = None
    recipe_version: Literal["image-panel-pillow-recipes-v1"] = IMAGE_PANEL_RECIPE_VERSION
    recipe_sha256: Sha256Hex
    case_binding_sha256: Sha256Hex
    capability_gate: bool = False

    @model_validator(mode="after")
    def validate_case(self) -> Self:
        if self.source_families != tuple(sorted(set(self.source_families))):
            raise ValueError("source families must be unique and sorted")
        all_refs = tuple(
            artifact.artifact_ref for artifact in (*self.arm_0.artifacts, *self.arm_1.artifacts)
        )
        if self.reference is not None:
            all_refs += (self.reference.artifact_ref,)
        if len(all_refs) != len(set(all_refs)):
            raise ValueError("case artifact references must be unique")
        if self.dimension is ImageEvalDimension.BATCH_DIVERSITY:
            if len(self.arm_0.artifacts) != 2 or len(self.arm_1.artifacts) != 2:
                raise ValueError("batch diversity requires two images per arm")
            if self.reference is not None:
                raise ValueError("batch diversity cannot include a reference")
        elif len(self.arm_0.artifacts) != 1 or len(self.arm_1.artifacts) != 1:
            raise ValueError("single-image dimensions require one image per arm")
        if self.dimension is ImageEvalDimension.IP_IDENTITY and self.reference is None:
            raise ValueError("IP identity cases require a reference image")
        if self.gold_kind is GoldKind.OBJECTIVE_RECIPE:
            if self.gold_choice not in {CanonicalChoice.FIRST, CanonicalChoice.SECOND}:
                raise ValueError("objective cases require an unambiguous pair winner")
            if self.gold_first_verdict is None or self.gold_second_verdict is None:
                raise ValueError("objective cases require both arm verdicts")
        elif any(
            value is not None
            for value in (
                self.gold_choice,
                self.gold_first_verdict,
                self.gold_second_verdict,
            )
        ):
            raise ValueError("unlabeled subjective cases cannot claim objective gold")
        if self.capability_gate and self.dimension is not ImageEvalDimension.BATCH_DIVERSITY:
            raise ValueError("the capability gate must be a four-image diversity case")
        payload = self.model_dump(mode="json", exclude={"case_binding_sha256"})
        if evidence_sha256(payload) != self.case_binding_sha256:
            raise ValueError("case binding SHA-256 does not match its canonical payload")
        return self


class ImageModelSpec(FrozenModel):
    model_ref: SafeId
    role: EvaluatorRole
    gateway: SafeId
    provider: SafeId
    requested_model: SafeId


IMAGE_EVALUATOR_MODEL_SPEC = ImageModelSpec(
    model_ref="evaluator-glm-5v-turbo",
    role=EvaluatorRole.EVALUATOR,
    gateway="zhipu-direct",
    provider="zhipu",
    requested_model="glm-5v-turbo",
)
ALL_MODEL_SPECS = (IMAGE_EVALUATOR_MODEL_SPEC,)


ISSUE_BY_DIMENSION = {
    ImageEvalDimension.SEMANTIC_FAITHFULNESS: PanelIssueCode.SEMANTIC_MISMATCH,
    ImageEvalDimension.IP_IDENTITY: PanelIssueCode.APPROVED_IDENTITY_MISMATCH,
    ImageEvalDimension.OCR_TEXT: PanelIssueCode.VISIBLE_TEXT_ERROR,
    ImageEvalDimension.AESTHETICS_ARTIFACTS: PanelIssueCode.RENDERING_ARTIFACT,
    ImageEvalDimension.PUBLICATION_LAYOUT: PanelIssueCode.CROP_LAYOUT_ERROR,
    ImageEvalDimension.BATCH_DIVERSITY: PanelIssueCode.BATCH_DUPLICATE,
}
