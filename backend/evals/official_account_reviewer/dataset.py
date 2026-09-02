"""Fail-closed loader for physically separated Reviewer cases and oracle labels."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, TypeVar

from app.domain.official_account_reviewer import (
    ReviewDecision,
    ReviewDimension,
    ReviewIssueSource,
    active_review_rubric,
    build_review_issue,
    build_review_request,
    build_review_verdict,
    project_repair_directives,
    reviewer_issue_allowed,
)
from pydantic import BaseModel, ValidationError

from .models import (
    DATASET_VERSION,
    FixtureProviderStatus,
    ReviewEvalCase,
    ReviewEvalOracle,
    ReviewFixtureKind,
)

FEATURE_ROOT = Path(__file__).resolve().parent
DEFAULT_CASES_PATH = FEATURE_ROOT / "cases.v1.jsonl"
DEFAULT_ORACLE_PATH = FEATURE_ROOT / "oracle.v1.jsonl"
DEFAULT_RUBRIC_PATH = FEATURE_ROOT / "rubric.v1.json"

MINIMUM_CASE_COUNT = 48
MINIMUM_CASES_PER_DIMENSION = 8
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
        "expected_decision",
        "expected_issues",
        "expected_repair_issue_codes",
        "gold",
        "answer",
        "raw_prompt",
        "prompt",
        "provider_body",
        "provider_response",
        "chain_of_thought",
        "reasoning",
        "repair_instruction",
        "article_text",
        "source_text",
    }
)


class ReviewEvalDatasetError(ValueError):
    """The Reviewer fixture dataset is unsafe, incomplete, or ambiguous."""


@dataclass(frozen=True, slots=True)
class LoadedReviewEvalDataset:
    cases: tuple[ReviewEvalCase, ...]
    oracles: tuple[ReviewEvalOracle, ...]
    dataset_version: str
    cases_sha256: str
    oracle_sha256: str
    rubric_sha256: str


ModelT = TypeVar("ModelT", bound=BaseModel)


def load_review_eval_dataset(
    *,
    cases_path: Path = DEFAULT_CASES_PATH,
    oracle_path: Path = DEFAULT_ORACLE_PATH,
    rubric_path: Path = DEFAULT_RUBRIC_PATH,
) -> LoadedReviewEvalDataset:
    cases_bytes = _read_bounded(cases_path, MAX_DATASET_BYTES, "case dataset")
    oracle_bytes = _read_bounded(oracle_path, MAX_DATASET_BYTES, "oracle dataset")
    rubric_bytes = _read_bounded(rubric_path, MAX_RUBRIC_BYTES, "rubric")
    cases = _load_jsonl(cases_bytes, ReviewEvalCase, "case", prohibit_oracle=True)
    oracles = _load_jsonl(oracle_bytes, ReviewEvalOracle, "oracle", prohibit_oracle=False)
    _validate_rubric(rubric_bytes)
    _validate_dataset(cases, oracles)
    return LoadedReviewEvalDataset(
        cases=tuple(sorted(cases, key=lambda item: item.case_id)),
        oracles=tuple(sorted(oracles, key=lambda item: item.case_id)),
        dataset_version=DATASET_VERSION,
        cases_sha256=sha256(cases_bytes).hexdigest(),
        oracle_sha256=sha256(oracle_bytes).hexdigest(),
        rubric_sha256=sha256(rubric_bytes).hexdigest(),
    )


def _read_bounded(path: Path, limit: int, label: str) -> bytes:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ReviewEvalDatasetError(f"review eval {label} could not be read") from exc
    if not payload or len(payload) > limit:
        raise ReviewEvalDatasetError(f"review eval {label} has an invalid byte length")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewEvalDatasetError(f"review eval {label} must be UTF-8") from exc
    if _SENSITIVE_TEXT.search(text):
        raise ReviewEvalDatasetError(f"review eval {label} contains a sensitive-data marker")
    return payload


def _load_jsonl(
    payload: bytes,
    model: type[ModelT],
    label: str,
    *,
    prohibit_oracle: bool,
) -> list[ModelT]:
    records: list[ModelT] = []
    for line_number, line in enumerate(payload.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            raise ReviewEvalDatasetError(f"blank {label} JSONL record at line {line_number}")
        if len(line.encode("utf-8")) > MAX_RECORD_BYTES:
            raise ReviewEvalDatasetError(f"{label} record {line_number} exceeds the byte limit")
        try:
            raw: Any = _strict_json_loads(line)
        except ValueError as exc:
            raise ReviewEvalDatasetError(f"invalid {label} JSON at line {line_number}") from exc
        if not isinstance(raw, dict):
            raise ReviewEvalDatasetError(f"{label} record {line_number} must be an object")
        prohibited = _find_prohibited_keys(raw) if prohibit_oracle else set()
        if prohibited:
            raise ReviewEvalDatasetError(
                f"case record {line_number} contains evaluator-only fields: "
                + ",".join(sorted(prohibited))
            )
        try:
            records.append(model.model_validate(raw))
        except ValidationError as exc:
            safe_types = sorted({error["type"] for error in exc.errors(include_input=False)})
            raise ReviewEvalDatasetError(
                f"invalid {label} record at line {line_number}: {','.join(safe_types)}"
            ) from exc
    return records


def _validate_rubric(payload: bytes) -> None:
    try:
        raw: Any = _strict_json_loads(payload.decode("utf-8"))
    except ValueError as exc:
        raise ReviewEvalDatasetError("review eval rubric is invalid JSON") from exc
    if not isinstance(raw, dict):
        raise ReviewEvalDatasetError("review eval rubric must be an object")
    expected = active_review_rubric().model_dump(mode="json")
    if raw != expected:
        raise ReviewEvalDatasetError("review eval rubric drifted from the domain contract")


def _validate_dataset(
    cases: list[ReviewEvalCase],
    oracles: list[ReviewEvalOracle],
) -> None:
    if len(cases) < MINIMUM_CASE_COUNT:
        raise ReviewEvalDatasetError(
            f"review eval dataset requires at least {MINIMUM_CASE_COUNT} cases"
        )
    case_ids = tuple(case.case_id for case in cases)
    oracle_ids = tuple(item.case_id for item in oracles)
    if len(case_ids) != len(set(case_ids)):
        raise ReviewEvalDatasetError("review eval case IDs must be unique")
    if len(oracle_ids) != len(set(oracle_ids)):
        raise ReviewEvalDatasetError("review eval oracle IDs must be unique")
    if set(case_ids) != set(oracle_ids):
        raise ReviewEvalDatasetError("review eval case/oracle coverage mismatch")
    counts = Counter(case.focus_dimension for case in cases)
    sparse = [
        dimension.value
        for dimension in ReviewDimension
        if counts[dimension] < MINIMUM_CASES_PER_DIMENSION
    ]
    if sparse:
        raise ReviewEvalDatasetError(
            "review eval dimensions are under-covered: " + ",".join(sparse)
        )
    for dimension in ReviewDimension:
        dimension_cases = tuple(case for case in cases if case.focus_dimension is dimension)
        if not any(case.fixture_kind is ReviewFixtureKind.POSITIVE for case in dimension_cases):
            raise ReviewEvalDatasetError(
                f"review eval dimension {dimension.value} has no positive fixture"
            )
        if not any(case.signals or case.hard_gate_failures for case in dimension_cases):
            raise ReviewEvalDatasetError(
                f"review eval dimension {dimension.value} has no defect fixture"
            )
        if {case.provider_status for case in dimension_cases} != set(FixtureProviderStatus):
            raise ReviewEvalDatasetError(
                f"review eval dimension {dimension.value} has incomplete provider-status coverage"
            )
    if {case.fixture_kind for case in cases} != set(ReviewFixtureKind):
        raise ReviewEvalDatasetError("review eval fixture-kind coverage is incomplete")

    oracle_by_id = {item.case_id: item for item in oracles}
    for case in cases:
        oracle = oracle_by_id[case.case_id]
        request = build_review_request(
            request_id=f"request:{case.case_id}",
            identity=case.identity,
            reviewer_version="provider-free-reviewer-v1",
            prompt_version="provider-free-review-prompt-v1",
            hard_gate_failures=case.hard_gate_failures,
        )
        expected_issues = tuple(
            build_review_issue(
                code=item.code,
                source=ReviewIssueSource.REVIEWER,
                references=item.references,
            )
            for item in oracle.expected_issues
            if reviewer_issue_allowed(item.code)
        )
        unavailable_reason = None
        if oracle.expected_decision is ReviewDecision.UNAVAILABLE:
            from app.domain.official_account_reviewer import ReviewUnavailableReason

            unavailable_reason = (
                ReviewUnavailableReason.PROVIDER_UNAVAILABLE
                if case.provider_status is FixtureProviderStatus.UNAVAILABLE
                else ReviewUnavailableReason.INVALID_OUTPUT
            )
        try:
            expected_verdict = build_review_verdict(
                request,
                reviewer_issues=expected_issues,
                unavailable_reason=unavailable_reason,
            )
        except ValueError as exc:
            raise ReviewEvalDatasetError(
                f"invalid oracle/reference binding for case {case.case_id}"
            ) from exc
        if expected_verdict.decision is not oracle.expected_decision:
            raise ReviewEvalDatasetError(f"oracle decision is inconsistent for case {case.case_id}")
        if expected_verdict.issues and not any(
            issue.dimension is case.focus_dimension for issue in expected_verdict.issues
        ):
            raise ReviewEvalDatasetError(
                f"oracle does not exercise focus dimension for case {case.case_id}"
            )
        oracle_issue_keys = {
            (item.code, tuple((ref.kind, ref.ref) for ref in item.references))
            for item in oracle.expected_issues
        }
        verdict_issue_keys = {
            (item.code, tuple((ref.kind, ref.ref) for ref in item.references))
            for item in expected_verdict.issues
        }
        if oracle_issue_keys != verdict_issue_keys:
            raise ReviewEvalDatasetError(
                f"invalid oracle/reference binding for case {case.case_id}"
            )
        repair_codes = tuple(
            directive.issue_code
            for directive in project_repair_directives(request, expected_verdict)
        )
        if repair_codes != oracle.expected_repair_issue_codes:
            raise ReviewEvalDatasetError(
                f"oracle repairability is inconsistent for case {case.case_id}"
            )
        override = (
            bool(case.hard_gate_failures)
            and case.provider_status is not FixtureProviderStatus.AVAILABLE
        )
        if oracle.expected_hard_gate_override is not override:
            raise ReviewEvalDatasetError(
                f"oracle hard-gate precedence is inconsistent for case {case.case_id}"
            )


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


def _strict_json_loads(payload: str) -> object:
    def reject_constant(_: str) -> None:
        raise ValueError("non-standard JSON constant")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    return json.loads(
        payload,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_constant,
    )
