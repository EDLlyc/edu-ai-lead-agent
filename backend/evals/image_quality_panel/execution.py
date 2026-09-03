"""Sequential one-shot execution with a per-model first-call capability stop."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.domain.image_quality_eval import ImageEvalDimension

from evals.model_panel import (
    AttemptStatus,
    JudgeImage,
    JudgeMaterial,
    OneShotExecution,
    PairwiseJudgeRequest,
    PanelAttempt,
    PanelAuthorization,
    validate_authorization_binding,
)

from .dataset import LoadedImagePanelDataset
from .planning import (
    CALLS_PER_MODEL,
    ImageExperimentPlan,
    ImagePanelPlanningError,
    validate_experiment_plan,
)


@dataclass(frozen=True, slots=True)
class ImagePlanExecutionResult:
    attempts: tuple[PanelAttempt, ...]
    stopped_model_refs: tuple[str, ...]
    skipped_attempt_count: int


async def execute_image_plan(
    *,
    plan: ImageExperimentPlan,
    authorization: PanelAuthorization,
    dataset: LoadedImagePanelDataset,
    execution_by_model: dict[str, OneShotExecution],
    now: datetime,
) -> ImagePlanExecutionResult:
    """Execute the immutable plan; never retry, fallback, or continue after capability failure."""

    validate_experiment_plan(plan)
    validate_authorization_binding(plan.manifest, authorization, now=now)
    if (
        plan.manifest.dataset_version != dataset.dataset_version
        or plan.manifest.dataset_sha256 != dataset.dataset_sha256
    ):
        raise ImagePanelPlanningError("plan does not bind the supplied image dataset")
    identities = {item.identity_ref: item for item in plan.manifest.identities}
    if set(execution_by_model) != set(identities):
        raise ImagePanelPlanningError(
            "execution adapters must exactly cover the unique frozen model"
        )
    if any(
        request.authorization_sha256 != authorization.authorization_sha256
        or request.manifest_sha256 != plan.manifest.manifest_sha256
        for request in plan.requests
    ):
        raise ImagePanelPlanningError("requests are not hash-bound to manifest and authorization")
    counts = Counter(request.evaluator_model_ref for request in plan.requests)
    if set(counts.values()) != {CALLS_PER_MODEL}:
        raise ImagePanelPlanningError("selective or partial model plans are forbidden")

    attempts: list[PanelAttempt] = []
    stopped: list[str] = []
    skipped = 0
    for model_ref in sorted(identities):
        requests = tuple(
            request for request in plan.requests if request.evaluator_model_ref == model_ref
        )
        identity = identities[model_ref]
        execution = execution_by_model[model_ref]
        for index, request in enumerate(requests):
            attempt = await execution.execute(
                identity=identity,
                request=request,
                material=material_for_request(dataset, plan, request),
            )
            attempts.append(attempt)
            if index == 0 and attempt.status is not AttemptStatus.COMPLETED:
                stopped.append(model_ref)
                skipped += len(requests) - 1
                break
    return ImagePlanExecutionResult(
        attempts=tuple(attempts),
        stopped_model_refs=tuple(stopped),
        skipped_attempt_count=skipped,
    )


def material_for_request(
    dataset: LoadedImagePanelDataset,
    plan: ImageExperimentPlan,
    request: PairwiseJudgeRequest,
) -> JudgeMaterial:
    try:
        rubric = plan.rubric_by_dimension[ImageEvalDimension(request.dimension)]
    except (KeyError, ValueError) as exc:
        raise ImagePanelPlanningError("request dimension is not in the frozen rubric") from exc
    images: list[JudgeImage] = []
    paths_by_sha256 = _artifact_paths_by_sha256(dataset)
    for reference in request.artifacts:
        try:
            path = paths_by_sha256[reference.sha256]
            content = path.read_bytes()
        except (KeyError, OSError) as exc:
            raise ImagePanelPlanningError("request artifact is unavailable") from exc
        images.append(JudgeImage(reference=reference, content=content))
    return JudgeMaterial(rubric_instruction=rubric, images=tuple(images))


def _artifact_paths_by_sha256(dataset: LoadedImagePanelDataset) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for case in dataset.cases:
        artifacts = (*case.arm_0.artifacts, *case.arm_1.artifacts)
        if case.reference is not None:
            artifacts += (case.reference,)
        for artifact in artifacts:
            paths[artifact.sha256] = dataset.artifact_paths[artifact.artifact_ref]
    return paths
