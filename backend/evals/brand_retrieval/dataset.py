"""Fail-closed loader for the sanitized brand-text retrieval JSONL dataset."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.domain.brand_knowledge import BrandContentType
from pydantic import ValidationError

from .models import BrandRetrievalEvalCase

DEFAULT_CASES_PATH = Path(__file__).with_name("cases.v1.jsonl")
EXPECTED_CASE_COUNT = 36
EXPECTED_CASES_PER_CATEGORY = 4
MAX_DATASET_BYTES = 1_048_576
MAX_CASE_BYTES = 32_768

_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:postgres(?:ql)?://|mysql://|mongodb://|minio://|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk|ak)-[A-Za-z0-9_-]{12,}\b|"
    r"authorization\s*:\s*bearer|/root/|/home/|private/brand-materials)"
)


class BrandRetrievalEvalDatasetError(ValueError):
    """The offline dataset is unsafe, ambiguous, or malformed."""


def load_eval_cases(
    path: Path = DEFAULT_CASES_PATH,
) -> tuple[BrandRetrievalEvalCase, ...]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise BrandRetrievalEvalDatasetError(
            "brand retrieval eval dataset could not be read"
        ) from exc
    if len(payload) > MAX_DATASET_BYTES:
        raise BrandRetrievalEvalDatasetError("brand retrieval eval dataset exceeds the byte limit")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BrandRetrievalEvalDatasetError("brand retrieval eval dataset must be UTF-8") from exc
    if _SENSITIVE_TEXT.search(text):
        raise BrandRetrievalEvalDatasetError(
            "brand retrieval eval dataset contains a forbidden sensitive-data marker"
        )

    cases: list[BrandRetrievalEvalCase] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise BrandRetrievalEvalDatasetError(f"blank JSONL record at line {line_number}")
        if len(line.encode("utf-8")) > MAX_CASE_BYTES:
            raise BrandRetrievalEvalDatasetError(
                f"JSONL record {line_number} exceeds the byte limit"
            )
        try:
            raw: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BrandRetrievalEvalDatasetError(f"invalid JSON at line {line_number}") from exc
        if not isinstance(raw, dict):
            raise BrandRetrievalEvalDatasetError(f"JSONL record {line_number} must be an object")
        try:
            cases.append(BrandRetrievalEvalCase.model_validate(raw))
        except ValidationError as exc:
            safe_types = sorted({error["type"] for error in exc.errors(include_input=False)})
            raise BrandRetrievalEvalDatasetError(
                f"invalid eval case at line {line_number}: {','.join(safe_types)}"
            ) from exc

    _validate_dataset(cases)
    return tuple(sorted(cases, key=lambda case: case.case_id))


def _validate_dataset(cases: list[BrandRetrievalEvalCase]) -> None:
    if len(cases) != EXPECTED_CASE_COUNT:
        raise BrandRetrievalEvalDatasetError(
            f"brand retrieval eval dataset requires exactly {EXPECTED_CASE_COUNT} cases"
        )
    case_ids = tuple(case.case_id for case in cases)
    if len(case_ids) != len(set(case_ids)):
        raise BrandRetrievalEvalDatasetError("brand retrieval eval case IDs must be unique")
    category_counts = Counter(case.category for case in cases)
    invalid_categories = tuple(
        category.value
        for category in BrandContentType
        if category_counts[category] != EXPECTED_CASES_PER_CATEGORY
    )
    if invalid_categories:
        raise BrandRetrievalEvalDatasetError(
            "brand retrieval eval categories require exactly "
            f"{EXPECTED_CASES_PER_CATEGORY} cases: {','.join(invalid_categories)}"
        )
