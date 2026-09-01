"""Fail-closed loader for sanitized image-quality cases and frozen observations."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, TypeVar

from app.domain.image_quality_eval import (
    IMAGE_EVAL_RUBRIC_VERSION,
    ImageEvalCase,
    ImageEvalDecisionKind,
    ImageEvalDimension,
    ImageEvalEvaluatorKind,
    ImageEvalFixtureKind,
    ImageEvalObservation,
    ImageEvalRubric,
    ImageEvalSeverity,
    decide_image_eval,
    issue_contract,
)
from pydantic import BaseModel, ValidationError

FEATURE_ROOT = Path(__file__).resolve().parent
DEFAULT_CASES_PATH = FEATURE_ROOT / "cases.v1.jsonl"
DEFAULT_OBSERVATIONS_PATH = FEATURE_ROOT / "observations" / "frozen.v1.jsonl"
DEFAULT_RUBRIC_PATH = FEATURE_ROOT / "rubric.v1.json"

MINIMUM_CASE_COUNT = 40
MINIMUM_CASES_PER_DIMENSION = 6
MAX_DATASET_BYTES = 2_097_152
MAX_RECORD_BYTES = 32_768
MAX_RUBRIC_BYTES = 131_072

_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:postgres(?:ql)?://|mysql://|mongodb://|minio://|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk|ak)-[A-Za-z0-9_-]{12,}\b|"
    r"authorization\s*:\s*bearer|private[/\\]|data:image/|base64[,=:])"
)
_PROHIBITED_KEYS = frozenset(
    {
        "raw_prompt",
        "prompt",
        "provider_body",
        "provider_response",
        "vector",
        "embedding",
        "private_path",
        "object_key",
        "filename",
        "file_path",
        "image_bytes",
        "base64",
    }
)


class ImageEvalDatasetError(ValueError):
    """The fixture dataset is unsafe, incomplete, or ambiguous."""


@dataclass(frozen=True, slots=True)
class LoadedImageEvalDataset:
    cases: tuple[ImageEvalCase, ...]
    observations: tuple[ImageEvalObservation, ...]
    rubric: ImageEvalRubric
    dataset_sha256: str
    rubric_sha256: str


ModelT = TypeVar("ModelT", bound=BaseModel)


def load_image_eval_dataset(
    *,
    cases_path: Path = DEFAULT_CASES_PATH,
    observations_path: Path = DEFAULT_OBSERVATIONS_PATH,
    rubric_path: Path = DEFAULT_RUBRIC_PATH,
) -> LoadedImageEvalDataset:
    """Load all three versioned artifacts and validate their cross-file contract."""

    cases_bytes = _read_bounded(cases_path, MAX_DATASET_BYTES, "case dataset")
    observations_bytes = _read_bounded(observations_path, MAX_DATASET_BYTES, "observation dataset")
    rubric_bytes = _read_bounded(rubric_path, MAX_RUBRIC_BYTES, "rubric")
    cases = _load_jsonl(cases_bytes, ImageEvalCase, "case")
    observations = _load_jsonl(observations_bytes, ImageEvalObservation, "observation")
    rubric = _load_rubric(rubric_bytes)
    _validate_rubric_contract(rubric)
    _validate_dataset(cases, observations, rubric)
    dataset_payload = b"cases\0" + cases_bytes + b"observations\0" + observations_bytes
    return LoadedImageEvalDataset(
        cases=tuple(sorted(cases, key=lambda item: item.case_id)),
        observations=tuple(sorted(observations, key=lambda item: item.subject_ref)),
        rubric=rubric,
        dataset_sha256=sha256(dataset_payload).hexdigest(),
        rubric_sha256=sha256(rubric_bytes).hexdigest(),
    )


def _read_bounded(path: Path, limit: int, label: str) -> bytes:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ImageEvalDatasetError(f"image eval {label} could not be read") from exc
    if not payload or len(payload) > limit:
        raise ImageEvalDatasetError(f"image eval {label} has an invalid byte length")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ImageEvalDatasetError(f"image eval {label} must be UTF-8") from exc
    if _SENSITIVE_TEXT.search(text):
        raise ImageEvalDatasetError(f"image eval {label} contains a sensitive-data marker")
    return payload


def _load_jsonl(
    payload: bytes,
    model: type[ModelT],
    label: str,
) -> list[ModelT]:
    text = payload.decode("utf-8")
    records: list[ModelT] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise ImageEvalDatasetError(f"blank {label} JSONL record at line {line_number}")
        if len(line.encode("utf-8")) > MAX_RECORD_BYTES:
            raise ImageEvalDatasetError(
                f"{label} JSONL record {line_number} exceeds the byte limit"
            )
        try:
            raw: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ImageEvalDatasetError(f"invalid {label} JSON at line {line_number}") from exc
        if not isinstance(raw, dict):
            raise ImageEvalDatasetError(f"{label} JSONL record {line_number} must be an object")
        prohibited = _find_prohibited_keys(raw)
        if prohibited:
            raise ImageEvalDatasetError(
                f"{label} JSONL record {line_number} contains prohibited fields: "
                + ",".join(sorted(prohibited))
            )
        try:
            records.append(model.model_validate(raw))
        except ValidationError as exc:
            safe_types = sorted({error["type"] for error in exc.errors(include_input=False)})
            raise ImageEvalDatasetError(
                f"invalid {label} record at line {line_number}: {','.join(safe_types)}"
            ) from exc
    return records


def _load_rubric(payload: bytes) -> ImageEvalRubric:
    try:
        raw: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ImageEvalDatasetError("image eval rubric is invalid JSON") from exc
    if not isinstance(raw, dict):
        raise ImageEvalDatasetError("image eval rubric must be an object")
    prohibited = _find_prohibited_keys(raw)
    if prohibited:
        raise ImageEvalDatasetError(
            "image eval rubric contains prohibited fields: " + ",".join(sorted(prohibited))
        )
    try:
        return ImageEvalRubric.model_validate(raw)
    except ValidationError as exc:
        safe_types = sorted({error["type"] for error in exc.errors(include_input=False)})
        raise ImageEvalDatasetError(f"invalid image eval rubric: {','.join(safe_types)}") from exc


def _validate_rubric_contract(rubric: ImageEvalRubric) -> None:
    if rubric.rubric_version != IMAGE_EVAL_RUBRIC_VERSION:
        raise ImageEvalDatasetError("image eval rubric version is not supported")
    for definition in rubric.issues:
        dimension, severity = issue_contract(definition.code)
        if definition.dimension is not dimension or definition.severity is not severity:
            raise ImageEvalDatasetError(
                f"rubric issue contract mismatch for {definition.code.value}"
            )


def _validate_dataset(
    cases: list[ImageEvalCase],
    observations: list[ImageEvalObservation],
    rubric: ImageEvalRubric,
) -> None:
    if len(cases) < MINIMUM_CASE_COUNT:
        raise ImageEvalDatasetError(
            f"image eval dataset requires at least {MINIMUM_CASE_COUNT} cases"
        )
    case_ids = tuple(case.case_id for case in cases)
    if len(case_ids) != len(set(case_ids)):
        raise ImageEvalDatasetError("image eval case IDs must be unique")
    observation_ids = tuple(item.observation_id for item in observations)
    if len(observation_ids) != len(set(observation_ids)):
        raise ImageEvalDatasetError("image eval observation IDs must be unique")
    subject_refs = tuple(item.subject_ref for item in observations)
    if len(subject_refs) != len(set(subject_refs)):
        raise ImageEvalDatasetError("one frozen observation per case is required")
    if set(subject_refs) != set(case_ids):
        missing = sorted(set(case_ids).difference(subject_refs))
        unexpected = sorted(set(subject_refs).difference(case_ids))
        raise ImageEvalDatasetError(
            f"case/observation coverage mismatch missing={missing} unexpected={unexpected}"
        )
    dimension_counts = Counter(case.dimension for case in cases)
    sparse = [
        dimension.value
        for dimension in ImageEvalDimension
        if dimension_counts[dimension] < MINIMUM_CASES_PER_DIMENSION
    ]
    if sparse:
        raise ImageEvalDatasetError(
            "image eval dimensions require at least "
            f"{MINIMUM_CASES_PER_DIMENSION} cases: {','.join(sparse)}"
        )
    fixture_kinds = {case.fixture_kind for case in cases}
    if fixture_kinds != set(ImageEvalFixtureKind):
        missing_kinds = sorted(kind.value for kind in set(ImageEvalFixtureKind) - fixture_kinds)
        raise ImageEvalDatasetError(
            "image eval dataset is missing fixture kinds: " + ",".join(missing_kinds)
        )

    observation_by_subject = {item.subject_ref: item for item in observations}
    for case in cases:
        _validate_gold_case(case)
        observation = observation_by_subject[case.case_id]
        if observation.evaluator_kind is not ImageEvalEvaluatorKind.FROZEN_FIXTURE:
            raise ImageEvalDatasetError("offline observations must use frozen_fixture evaluator")
        if observation.provider or observation.model or observation.request_fingerprint:
            raise ImageEvalDatasetError(
                "offline observations cannot claim a live provider identity"
            )
        if observation.dimension is not case.dimension:
            raise ImageEvalDatasetError(f"dimension mismatch for case {case.case_id}")
        if observation.publication_sha256 != case.publication_sha256:
            raise ImageEvalDatasetError(f"publication hash mismatch for case {case.case_id}")
        try:
            decide_image_eval(observation, rubric)
        except ValueError as exc:
            raise ImageEvalDatasetError(
                f"invalid frozen observation contract for case {case.case_id}"
            ) from exc


def _validate_gold_case(case: ImageEvalCase) -> None:
    severities: list[ImageEvalSeverity] = []
    for code in case.gold_issue_codes:
        dimension, severity = issue_contract(code)
        if dimension is not case.dimension:
            raise ImageEvalDatasetError(f"gold issue dimension mismatch for case {case.case_id}")
        severities.append(severity)
    if case.fixture_kind is ImageEvalFixtureKind.POSITIVE:
        valid = not severities and case.expected_decision is ImageEvalDecisionKind.ACCEPTED
    elif case.fixture_kind is ImageEvalFixtureKind.HARD_NEGATIVE:
        valid = (
            ImageEvalSeverity.CRITICAL in severities
            and case.expected_decision is ImageEvalDecisionKind.REJECTED
        )
    elif case.fixture_kind in {ImageEvalFixtureKind.WARNING, ImageEvalFixtureKind.BORDERLINE}:
        valid = (
            bool(severities)
            and ImageEvalSeverity.CRITICAL not in severities
            and case.expected_decision is ImageEvalDecisionKind.MANUAL_REVIEW
        )
    else:
        valid = not severities and case.expected_decision is ImageEvalDecisionKind.UNAVAILABLE
    if not valid:
        raise ImageEvalDatasetError(f"gold label is inconsistent for case {case.case_id}")


def _find_prohibited_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        found = {str(key).casefold() for key in value if str(key).casefold() in _PROHIBITED_KEYS}
        for child in value.values():
            found.update(_find_prohibited_keys(child))
        return found
    if isinstance(value, list):
        found_list: set[str] = set()
        for child in value:
            found_list.update(_find_prohibited_keys(child))
        return found_list
    return set()
