"""Build and validate the frozen 48-pair, six-source derived image dataset."""

from __future__ import annotations

import stat
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.domain.image_quality_eval import ImageEvalDimension

from evals.model_panel import (
    ArmDecision,
    ArmVerdict,
    CanonicalChoice,
    canonical_json_bytes,
    evidence_sha256,
)

from .models import (
    IMAGE_PANEL_DATASET_VERSION,
    IMAGE_PANEL_RECIPE_VERSION,
    ISSUE_BY_DIMENSION,
    DatasetSplit,
    GoldKind,
    ImageArm,
    ImageArtifact,
    ImagePanelCase,
    SourceArtifact,
    SourceCatalog,
)
from .sources import REPOSITORY_ROOT, catalog_sha256, load_source_catalog, preflight_sources
from .transforms import render_artifact

CASE_COUNT = 48
OBJECTIVE_CASE_COUNT = 36
SUBJECTIVE_CASE_COUNT = 12
CASES_PER_DIMENSION = 8
CASES_PER_SPLIT = 24
EFFECTIVE_SOURCE_CLUSTER_N = 6
SUBJECTIVE_INDEXES = frozenset({2, 6})
# Repeat every unlabeled subjective case so the repeat metric measures self-stability rather than
# re-scoring objective anchors. There are two subjective cases per dimension, hence 12 repeats.
REPEAT_INDEXES = SUBJECTIVE_INDEXES
_TEXT_AND_IP_FAMILY_BY_SPLIT = {
    DatasetSplit.CALIBRATION: "brain-computer-interface-ai",
    DatasetSplit.HOLDOUT: "science-learning-by-doing",
}

_DEFECT_RECIPE = {
    ImageEvalDimension.SEMANTIC_FAITHFULNESS: "semantic-occlusion",
    ImageEvalDimension.IP_IDENTITY: "identity-corruption",
    ImageEvalDimension.OCR_TEXT: "visible-text-mutation",
    ImageEvalDimension.AESTHETICS_ARTIFACTS: "artifact-degradation",
    ImageEvalDimension.PUBLICATION_LAYOUT: "unsafe-crop",
}


class ImagePanelDatasetError(ValueError):
    """The derived dataset is incomplete, unsafe, or no longer reproducible."""


@dataclass(frozen=True, slots=True)
class LoadedImagePanelDataset:
    cases: tuple[ImagePanelCase, ...]
    artifact_paths: dict[str, Path]
    dataset_version: str
    dataset_sha256: str
    source_catalog_sha256: str
    case_n: int
    effective_source_cluster_n: int


def build_image_panel_dataset(
    *,
    artifact_directory: Path,
    repository_root: Path = REPOSITORY_ROOT,
    catalog: SourceCatalog | None = None,
) -> LoadedImagePanelDataset:
    """Materialize deterministic JPEG derivatives into a new private directory."""

    source_catalog = catalog or load_source_catalog()
    source_catalog_hash = catalog_sha256() if catalog is None else evidence_sha256(source_catalog)
    preflight_sources(source_catalog, repository_root=repository_root)
    _require_empty_private_directory(artifact_directory)
    sources_by_split = {
        split: tuple(item for item in source_catalog.sources if item.split is split)
        for split in DatasetSplit
    }
    if any(len(items) != 3 for items in sources_by_split.values()):
        raise ImagePanelDatasetError("each split requires exactly three independent families")

    cases: list[ImagePanelCase] = []
    artifact_paths: dict[str, Path] = {}
    objective_ordinal = 0
    for dimension_index, dimension in enumerate(ImageEvalDimension):
        for case_index in range(CASES_PER_DIMENSION):
            split = DatasetSplit.CALIBRATION if case_index < 4 else DatasetSplit.HOLDOUT
            split_sources = sources_by_split[split]
            local_index = case_index if case_index < 4 else case_index - 4
            if dimension in {
                ImageEvalDimension.IP_IDENTITY,
                ImageEvalDimension.OCR_TEXT,
            }:
                primary = next(
                    source
                    for source in split_sources
                    if source.source_family == _TEXT_AND_IP_FAMILY_BY_SPLIT[split]
                )
            else:
                primary = split_sources[local_index % len(split_sources)]
            companion = split_sources[(local_index + 1) % len(split_sources)]
            gold_kind = (
                GoldKind.SUBJECTIVE_UNLABELED
                if case_index in SUBJECTIVE_INDEXES
                else GoldKind.OBJECTIVE_RECIPE
            )
            winner = None
            if gold_kind is GoldKind.OBJECTIVE_RECIPE:
                winner = (
                    CanonicalChoice.FIRST if objective_ordinal % 2 == 0 else CanonicalChoice.SECOND
                )
                objective_ordinal += 1
            case, paths = _build_case(
                repository_root=repository_root,
                artifact_directory=artifact_directory,
                dimension=dimension,
                dimension_index=dimension_index,
                case_index=case_index,
                split=split,
                primary=primary,
                companion=companion,
                gold_kind=gold_kind,
                winner=winner,
            )
            cases.append(case)
            overlap = set(paths).intersection(artifact_paths)
            if overlap:
                raise ImagePanelDatasetError("derived artifact references must be globally unique")
            artifact_paths.update(paths)

    ordered = tuple(
        sorted(
            cases,
            key=lambda case: (
                not case.capability_gate,
                list(ImageEvalDimension).index(case.dimension),
                case.case_ref,
            ),
        )
    )
    _validate_dataset(ordered, source_catalog)
    dataset_hash = evidence_sha256(
        {
            "dataset_version": IMAGE_PANEL_DATASET_VERSION,
            "source_catalog_sha256": source_catalog_hash,
            "cases": [case.model_dump(mode="json") for case in ordered],
        }
    )
    return LoadedImagePanelDataset(
        cases=ordered,
        artifact_paths=artifact_paths,
        dataset_version=IMAGE_PANEL_DATASET_VERSION,
        dataset_sha256=dataset_hash,
        source_catalog_sha256=source_catalog_hash,
        case_n=len(ordered),
        effective_source_cluster_n=len(source_catalog.sources),
    )


def repeat_case_refs(cases: tuple[ImagePanelCase, ...]) -> tuple[str, ...]:
    selected = tuple(
        case.case_ref
        for case in cases
        if int(case.case_ref.rsplit("-", maxsplit=1)[1]) in REPEAT_INDEXES
    )
    if len(selected) != 12:
        raise ImagePanelDatasetError("repeat subset must contain two cases per dimension")
    return selected


def _build_case(
    *,
    repository_root: Path,
    artifact_directory: Path,
    dimension: ImageEvalDimension,
    dimension_index: int,
    case_index: int,
    split: DatasetSplit,
    primary: SourceArtifact,
    companion: SourceArtifact,
    gold_kind: GoldKind,
    winner: CanonicalChoice | None,
) -> tuple[ImagePanelCase, dict[str, Path]]:
    case_ref = f"img-{dimension.value.replace('_', '-')}-{case_index:02d}"
    recipe_payload = {
        "recipe_version": IMAGE_PANEL_RECIPE_VERSION,
        "case_ref": case_ref,
        "dimension": dimension.value,
        "split": split.value,
        "primary_family": primary.source_family,
        "companion_family": companion.source_family,
        "gold_kind": gold_kind.value,
        "winner": None if winner is None else winner.value,
        "seed": evidence_sha256({"dimension": dimension.value, "index": case_index}),
    }
    recipe_sha = evidence_sha256(recipe_payload)
    paths: dict[str, Path] = {}

    def render(
        source: SourceArtifact,
        recipe: str,
        canonical_arm: int | str,
        group_index: int,
    ) -> ImageArtifact:
        opaque = evidence_sha256(
            {
                "case_ref": case_ref,
                "arm": str(canonical_arm),
                "group_index": group_index,
                "recipe_sha256": recipe_sha,
            }
        )
        artifact_ref = f"img-{opaque[:28]}"
        destination = artifact_directory / f"{artifact_ref}.jpg"
        artifact = render_artifact(
            source_path=repository_root / source.repository_path,
            destination=destination,
            artifact_ref=artifact_ref,
            recipe=recipe,
            seed_material=f"{recipe_sha}:{canonical_arm}:{group_index}",
        )
        paths[artifact_ref] = destination
        return artifact

    good_specs: tuple[tuple[SourceArtifact, str], ...]
    bad_specs: tuple[tuple[SourceArtifact, str], ...]
    if dimension is ImageEvalDimension.BATCH_DIVERSITY:
        if gold_kind is GoldKind.OBJECTIVE_RECIPE:
            good_specs = ((primary, "clean"), (companion, "clean"))
            bad_specs = ((primary, "clean"), (primary, "clean"))
        else:
            good_specs = ((primary, "mild-a"), (companion, "mild-a"))
            bad_specs = ((primary, "mild-b"), (companion, "mild-b"))
        first_specs, second_specs = _place_specs(good_specs, bad_specs, winner)
        arm_0 = ImageArm(
            artifacts=tuple(
                render(source, recipe, 0, index)
                for index, (source, recipe) in enumerate(first_specs, 1)
            )
        )
        arm_1 = ImageArm(
            artifacts=tuple(
                render(source, recipe, 1, index)
                for index, (source, recipe) in enumerate(second_specs, 1)
            )
        )
        reference = None
        families = tuple(sorted({primary.source_family, companion.source_family}))
    else:
        if gold_kind is GoldKind.OBJECTIVE_RECIPE:
            good_specs = ((primary, "clean"),)
            bad_specs = ((primary, _DEFECT_RECIPE[dimension]),)
        else:
            good_specs = ((primary, "mild-a"),)
            bad_specs = ((primary, "mild-b"),)
        first_specs, second_specs = _place_specs(good_specs, bad_specs, winner)
        arm_0 = ImageArm(artifacts=(render(first_specs[0][0], first_specs[0][1], 0, 1),))
        arm_1 = ImageArm(artifacts=(render(second_specs[0][0], second_specs[0][1], 1, 1),))
        reference = (
            render(primary, "clean", "reference", 1)
            if dimension is ImageEvalDimension.IP_IDENTITY
            else None
        )
        families = (primary.source_family,)

    first_verdict, second_verdict = _gold_verdicts(dimension, winner)
    pair_ref = f"pair-{evidence_sha256(recipe_payload)[:28]}"
    payload: dict[str, object] = {
        "schema_version": "image-panel-case-v1",
        "case_ref": case_ref,
        "pair_ref": pair_ref,
        "dimension": dimension,
        "split": split,
        "source_families": families,
        "gold_kind": gold_kind,
        "arm_0": arm_0,
        "arm_1": arm_1,
        "reference": reference,
        "gold_choice": winner,
        "gold_first_verdict": first_verdict,
        "gold_second_verdict": second_verdict,
        "recipe_version": IMAGE_PANEL_RECIPE_VERSION,
        "recipe_sha256": recipe_sha,
        "capability_gate": dimension is ImageEvalDimension.BATCH_DIVERSITY and case_index == 0,
    }
    payload["case_binding_sha256"] = evidence_sha256(payload)
    return ImagePanelCase.model_validate_json(canonical_json_bytes(payload)), paths


def _place_specs(
    good_specs: tuple[tuple[SourceArtifact, str], ...],
    other_specs: tuple[tuple[SourceArtifact, str], ...],
    winner: CanonicalChoice | None,
) -> tuple[tuple[tuple[SourceArtifact, str], ...], tuple[tuple[SourceArtifact, str], ...]]:
    if winner is CanonicalChoice.SECOND:
        return other_specs, good_specs
    return good_specs, other_specs


def _gold_verdicts(
    dimension: ImageEvalDimension,
    winner: CanonicalChoice | None,
) -> tuple[ArmVerdict | None, ArmVerdict | None]:
    if winner is None:
        return None, None
    accepted = ArmVerdict(decision=ArmDecision.ACCEPT, critical=False, issue_codes=())
    rejected = ArmVerdict(
        decision=ArmDecision.REJECT,
        critical=True,
        issue_codes=(ISSUE_BY_DIMENSION[dimension],),
    )
    return (accepted, rejected) if winner is CanonicalChoice.FIRST else (rejected, accepted)


def _validate_dataset(cases: tuple[ImagePanelCase, ...], catalog: SourceCatalog) -> None:
    if len(cases) != CASE_COUNT or len({case.case_ref for case in cases}) != CASE_COUNT:
        raise ImagePanelDatasetError("dataset requires exactly 48 unique cases")
    dimensions = Counter(case.dimension for case in cases)
    if any(dimensions[dimension] != CASES_PER_DIMENSION for dimension in ImageEvalDimension):
        raise ImagePanelDatasetError("every image dimension requires exactly eight cases")
    kinds = Counter(case.gold_kind for case in cases)
    if kinds != Counter(
        {
            GoldKind.OBJECTIVE_RECIPE: OBJECTIVE_CASE_COUNT,
            GoldKind.SUBJECTIVE_UNLABELED: SUBJECTIVE_CASE_COUNT,
        }
    ):
        raise ImagePanelDatasetError("dataset requires 36 objective and 12 subjective cases")
    splits = Counter(case.split for case in cases)
    if splits != Counter({DatasetSplit.CALIBRATION: 24, DatasetSplit.HOLDOUT: 24}):
        raise ImagePanelDatasetError("dataset requires a balanced 24/24 grouped split")
    family_split = {item.source_family: item.split for item in catalog.sources}
    if len(family_split) != EFFECTIVE_SOURCE_CLUSTER_N:
        raise ImagePanelDatasetError("effective source cluster count must remain six")
    for case in cases:
        if any(family_split[family] is not case.split for family in case.source_families):
            raise ImagePanelDatasetError("source families cannot cross calibration/holdout")
    objective = tuple(case for case in cases if case.gold_kind is GoldKind.OBJECTIVE_RECIPE)
    positions = Counter(case.gold_choice for case in objective)
    if positions != Counter({CanonicalChoice.FIRST: 18, CanonicalChoice.SECOND: 18}):
        raise ImagePanelDatasetError("objective winners must be balanced across canonical arms")
    for case in objective:
        if case.gold_choice is CanonicalChoice.FIRST:
            accepted_arm, rejected_arm = case.arm_0, case.arm_1
            accepted_verdict, rejected_verdict = (
                case.gold_first_verdict,
                case.gold_second_verdict,
            )
        else:
            accepted_arm, rejected_arm = case.arm_1, case.arm_0
            accepted_verdict, rejected_verdict = (
                case.gold_second_verdict,
                case.gold_first_verdict,
            )
        if (
            accepted_verdict is None
            or rejected_verdict is None
            or accepted_verdict.decision is not ArmDecision.ACCEPT
            or accepted_verdict.critical
            or rejected_verdict.decision is not ArmDecision.REJECT
            or rejected_verdict.critical is not True
            or rejected_verdict.issue_codes != (ISSUE_BY_DIMENSION[case.dimension],)
        ):
            raise ImagePanelDatasetError("objective arm labels do not match the recipe gold")
        accepted_hashes = tuple(item.sha256 for item in accepted_arm.artifacts)
        rejected_hashes = tuple(item.sha256 for item in rejected_arm.artifacts)
        if case.dimension is ImageEvalDimension.BATCH_DIVERSITY:
            if len(set(accepted_hashes)) != 2 or len(set(rejected_hashes)) != 1:
                raise ImagePanelDatasetError(
                    "batch-diversity gold must compare a diverse pair with exact duplicates"
                )
        elif accepted_hashes == rejected_hashes:
            raise ImagePanelDatasetError("objective clean and defect artifacts must differ")
        if case.dimension is ImageEvalDimension.IP_IDENTITY and (
            case.reference is None
            or case.reference.sha256 != accepted_hashes[0]
            or case.reference.sha256 == rejected_hashes[0]
        ):
            raise ImagePanelDatasetError(
                "identity gold must bind the clean arm to the trusted reference"
            )
    gates = tuple(case for case in cases if case.capability_gate)
    if len(gates) != 1 or cases[0] is not gates[0]:
        raise ImagePanelDatasetError("the four-image diversity capability case must be first")
    if len(repeat_case_refs(cases)) != 12:
        raise ImagePanelDatasetError("repeat subset is incomplete")


def _require_empty_private_directory(path: Path) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
        children = tuple(path.iterdir())
    except OSError as exc:
        raise ImagePanelDatasetError("artifact directory is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ImagePanelDatasetError("artifact directory must have mode 0700")
    if children:
        raise ImagePanelDatasetError(
            "artifact directory must be empty and immutable-by-construction"
        )
