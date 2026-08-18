"""Fail-closed loader for the small versioned digital-IP fixture dataset."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import DigitalIpEvalCase, DigitalIpEvalCategory

DEFAULT_CASES_PATH = Path(__file__).with_name("cases.v1.jsonl")
MAX_DATASET_BYTES = 128 * 1024
_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:postgres(?:ql)?://|minio://|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\b(?:sk|ak)-[A-Za-z0-9_-]{12,}\b|authorization\s*:\s*bearer|private/brand-materials)"
)


class DigitalIpEvalDatasetError(ValueError):
    """The fixture dataset is unsafe, incomplete, or malformed."""


def load_eval_cases(path: Path = DEFAULT_CASES_PATH) -> tuple[DigitalIpEvalCase, ...]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise DigitalIpEvalDatasetError("digital IP eval dataset could not be read") from exc
    if len(payload) > MAX_DATASET_BYTES:
        raise DigitalIpEvalDatasetError("digital IP eval dataset exceeds the byte limit")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DigitalIpEvalDatasetError("digital IP eval dataset must be UTF-8") from exc
    if _SENSITIVE_TEXT.search(text):
        raise DigitalIpEvalDatasetError("digital IP eval dataset contains sensitive markers")

    cases: list[DigitalIpEvalCase] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise DigitalIpEvalDatasetError(f"blank record at line {line_number}")
        try:
            raw: Any = json.loads(line)
            case = DigitalIpEvalCase.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise DigitalIpEvalDatasetError(
                f"invalid digital IP eval case at line {line_number}"
            ) from exc
        cases.append(case)

    if len(cases) < len(DigitalIpEvalCategory):
        raise DigitalIpEvalDatasetError("digital IP eval requires all five categories")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise DigitalIpEvalDatasetError("digital IP eval case IDs must be unique")
    category_counts = Counter(case.category for case in cases)
    if any(category_counts[category] < 1 for category in DigitalIpEvalCategory):
        raise DigitalIpEvalDatasetError("digital IP eval requires one case per category")
    return tuple(sorted(cases, key=lambda case: case.case_id))
