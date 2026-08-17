"""Fail-closed loader for the versioned, sanitized workbench JSONL dataset."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import AgentEvalCase, EvalCategory

DEFAULT_CASES_PATH = Path(__file__).with_name("cases.v1.jsonl")
MINIMUM_CASE_COUNT = 40
MINIMUM_CASES_PER_CATEGORY = 6
MAX_DATASET_BYTES = 1_048_576
MAX_CASE_BYTES = 16_384

_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:postgres(?:ql)?://|mysql://|mongodb://|minio://|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\b(?:sk|ak)-[A-Za-z0-9_-]{12,}\b|authorization\s*:\s*bearer)"
)


class EvalDatasetError(ValueError):
    """The offline oracle dataset is unsafe, ambiguous, or malformed."""


def load_eval_cases(path: Path = DEFAULT_CASES_PATH) -> tuple[AgentEvalCase, ...]:
    """Load, validate, and deterministically order all evaluation cases."""

    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise EvalDatasetError("agent eval dataset could not be read") from exc
    if len(payload) > MAX_DATASET_BYTES:
        raise EvalDatasetError("agent eval dataset exceeds the byte limit")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvalDatasetError("agent eval dataset must be UTF-8") from exc
    if _SENSITIVE_TEXT.search(text):
        raise EvalDatasetError("agent eval dataset contains a forbidden sensitive-data marker")

    cases: list[AgentEvalCase] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise EvalDatasetError(f"blank JSONL record at line {line_number}")
        if len(line.encode("utf-8")) > MAX_CASE_BYTES:
            raise EvalDatasetError(f"JSONL record {line_number} exceeds the byte limit")
        try:
            raw: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalDatasetError(f"invalid JSON at line {line_number}") from exc
        if not isinstance(raw, dict):
            raise EvalDatasetError(f"JSONL record {line_number} must be an object")
        try:
            case = AgentEvalCase.model_validate(raw)
        except ValidationError as exc:
            safe_types = sorted({error["type"] for error in exc.errors(include_input=False)})
            raise EvalDatasetError(
                f"invalid eval case at line {line_number}: {','.join(safe_types)}"
            ) from exc
        cases.append(case)

    _validate_dataset(cases)
    return tuple(sorted(cases, key=lambda case: case.case_id))


def _validate_dataset(cases: list[AgentEvalCase]) -> None:
    if len(cases) < MINIMUM_CASE_COUNT:
        raise EvalDatasetError(f"agent eval dataset requires at least {MINIMUM_CASE_COUNT} cases")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise EvalDatasetError("agent eval case IDs must be unique")
    category_counts = Counter(case.category for case in cases)
    missing = [
        category.value
        for category in EvalCategory
        if category_counts[category] < MINIMUM_CASES_PER_CATEGORY
    ]
    if missing:
        raise EvalDatasetError(
            "agent eval categories require at least "
            f"{MINIMUM_CASES_PER_CATEGORY} cases: {','.join(missing)}"
        )
