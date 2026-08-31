from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from .models import IpAssetRetrievalEvalCase

DEFAULT_CASES_PATH = Path(__file__).with_name("cases.v1.jsonl")
PROHIBITED_KEYS = frozenset(
    {
        "asset_id",
        "asset_ref",
        "profile_id",
        "profile_ref",
        "profile_token",
        "session_id",
        "user_id",
        "ip",
        "user_agent",
        "referrer",
        "cookie",
        "filename",
        "object_key",
        "vector",
    }
)


class IpAssetRetrievalEvalDatasetError(ValueError):
    pass


def load_eval_cases(path: Path = DEFAULT_CASES_PATH) -> tuple[IpAssetRetrievalEvalCase, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise IpAssetRetrievalEvalDatasetError("IP retrieval dataset could not be read") from exc
    cases: list[IpAssetRetrievalEvalCase] = []
    seen: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise IpAssetRetrievalEvalDatasetError("blank dataset lines are forbidden")
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IpAssetRetrievalEvalDatasetError(f"invalid JSON on line {line_number}") from exc
        if not isinstance(raw, dict):
            raise IpAssetRetrievalEvalDatasetError("each dataset line must be an object")
        prohibited = _find_prohibited_keys(raw)
        if prohibited:
            raise IpAssetRetrievalEvalDatasetError(
                "dataset contains prohibited identity or payload fields: "
                + ", ".join(sorted(prohibited))
            )
        try:
            case = IpAssetRetrievalEvalCase.model_validate(raw)
        except ValidationError as exc:
            raise IpAssetRetrievalEvalDatasetError(f"invalid case on line {line_number}") from exc
        if case.case_id in seen:
            raise IpAssetRetrievalEvalDatasetError("case IDs must be unique")
        seen.add(case.case_id)
        cases.append(case)
    if len(cases) < 40:
        raise IpAssetRetrievalEvalDatasetError("IP retrieval dataset needs at least 40 cases")
    return tuple(sorted(cases, key=lambda item: item.case_id))


def _find_prohibited_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        found = {str(key).casefold() for key in value if str(key).casefold() in PROHIBITED_KEYS}
        for child in value.values():
            found.update(_find_prohibited_keys(child))
        return found
    if isinstance(value, list):
        list_found: set[str] = set()
        for child in value:
            list_found.update(_find_prohibited_keys(child))
        return list_found
    return set()
