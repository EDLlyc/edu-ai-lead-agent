"""Strict loader for the frozen, synthetic Reviewer live A/B inputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import DATASET_VERSION, LiveAbCase, canonical_json_bytes
from .privacy import PrivacyScanError, require_privacy_safe

FEATURE_ROOT = Path(__file__).resolve().parent
DEFAULT_CASES_PATH = FEATURE_ROOT / "cases.v1.jsonl"
MAX_DATASET_BYTES = 2_097_152
MAX_RECORD_BYTES = 32_768
MINIMUM_CASE_COUNT = 12

_PROHIBITED_CASE_KEYS = frozenset(
    {
        "answer",
        "expected_decision",
        "gold",
        "human_label",
        "oracle",
        "provider_response",
        "score",
    }
)


class LiveAbDatasetError(ValueError):
    """The paired live A/B dataset is unsafe, incomplete, or non-reproducible."""


@dataclass(frozen=True, slots=True)
class LoadedLiveAbDataset:
    cases: tuple[LiveAbCase, ...]
    dataset_version: str
    dataset_sha256: str
    article_sha256_by_case: dict[str, str]


def load_live_ab_dataset(path: Path = DEFAULT_CASES_PATH) -> LoadedLiveAbDataset:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise LiveAbDatasetError("live A/B dataset could not be read") from exc
    if not payload or len(payload) > MAX_DATASET_BYTES:
        raise LiveAbDatasetError("live A/B dataset has an invalid byte length")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LiveAbDatasetError("live A/B dataset must be UTF-8") from exc
    records: list[LiveAbCase] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise LiveAbDatasetError(f"blank live A/B record at line {line_number}")
        if len(line.encode("utf-8")) > MAX_RECORD_BYTES:
            raise LiveAbDatasetError(f"live A/B record {line_number} exceeds the byte limit")
        try:
            raw = _strict_json_loads(line)
        except ValueError as exc:
            raise LiveAbDatasetError(f"invalid live A/B JSON at line {line_number}") from exc
        if not isinstance(raw, dict):
            raise LiveAbDatasetError(f"live A/B record {line_number} must be an object")
        prohibited = _find_prohibited_keys(raw)
        if prohibited:
            raise LiveAbDatasetError(
                f"live A/B record {line_number} contains label fields: "
                + ",".join(sorted(prohibited))
            )
        try:
            require_privacy_safe(raw)
            records.append(LiveAbCase.model_validate(raw))
        except (PrivacyScanError, ValidationError) as exc:
            raise LiveAbDatasetError(f"unsafe live A/B record at line {line_number}") from exc
    if len(records) < MINIMUM_CASE_COUNT:
        raise LiveAbDatasetError(
            f"live A/B dataset requires at least {MINIMUM_CASE_COUNT} synthetic cases"
        )
    case_ids = tuple(case.case_id for case in records)
    if len(case_ids) != len(set(case_ids)):
        raise LiveAbDatasetError("live A/B case IDs must be unique")
    if {case.split for case in records} != {"calibration", "holdout"}:
        raise LiveAbDatasetError("live A/B dataset requires calibration and holdout cases")
    article_hashes = {
        case.case_id: sha256(canonical_json_bytes(case.initial_article)).hexdigest()
        for case in records
    }
    if len(set(article_hashes.values())) != len(article_hashes):
        raise LiveAbDatasetError("live A/B initial articles must be distinct")
    return LoadedLiveAbDataset(
        cases=tuple(records),
        dataset_version=DATASET_VERSION,
        dataset_sha256=sha256(payload).hexdigest(),
        article_sha256_by_case=article_hashes,
    )


def _strict_json_loads(line: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(line, object_pairs_hook=reject_duplicates)


def _find_prohibited_keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in _PROHIBITED_CASE_KEYS:
                found.add(normalized)
            found.update(_find_prohibited_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_find_prohibited_keys(child))
    return found
