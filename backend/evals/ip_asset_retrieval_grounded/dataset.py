from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .models import (
    EXPECTED_ASSET_COUNT,
    EXPECTED_QUERY_COUNT,
    GroundedQuery,
    GroundedQueryCategory,
    GroundedSeedMatrix,
    SafeGroundedAssetSnapshot,
)

FEATURE_ROOT = Path(__file__).resolve().parent
DEFAULT_ASSETS_PATH = FEATURE_ROOT / "assets.v1.json"
DEFAULT_QUERIES_PATH = FEATURE_ROOT / "queries.v1.jsonl"
DEFAULT_SEED_PATH = FEATURE_ROOT / "codex-seed.v1.jsonl"
PROHIBITED_KEYS = frozenset(
    {
        "asset_id",
        "asset_uuid",
        "checksum",
        "sha256",
        "source_master_sha256",
        "filename",
        "relative_path",
        "path",
        "object_key",
        "bucket",
        "vector",
        "similarity",
        "score",
        "rank",
        "provider_body",
        "provider_request_id",
        "profile_id",
        "profile_ref",
        "profile_token",
        "user_id",
        "session_id",
        "ip",
        "user_agent",
        "cookie",
    }
)


class GroundedDatasetError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GroundedDatasetBundle:
    assets: SafeGroundedAssetSnapshot
    queries: tuple[GroundedQuery, ...]
    seed: tuple[GroundedSeedMatrix, ...]
    assets_sha256: str
    queries_sha256: str
    seed_sha256: str


ModelT = TypeVar("ModelT", bound=BaseModel)


def load_grounded_bundle(
    *,
    assets_path: Path = DEFAULT_ASSETS_PATH,
    queries_path: Path = DEFAULT_QUERIES_PATH,
    seed_path: Path = DEFAULT_SEED_PATH,
) -> GroundedDatasetBundle:
    assets = _load_json_model(assets_path, SafeGroundedAssetSnapshot)
    queries = _load_jsonl_models(queries_path, GroundedQuery)
    seed = _load_jsonl_models(seed_path, GroundedSeedMatrix)
    _validate_bundle(assets=assets, queries=queries, seed=seed)
    return GroundedDatasetBundle(
        assets=assets,
        queries=queries,
        seed=seed,
        assets_sha256=_sha256_file(assets_path),
        queries_sha256=_sha256_file(queries_path),
        seed_sha256=_sha256_file(seed_path),
    )


def _load_json_model(path: Path, model: type[ModelT]) -> ModelT:
    try:
        body = path.read_bytes()
        raw = json.loads(body)
    except (OSError, json.JSONDecodeError) as error:
        raise GroundedDatasetError("grounded JSON dataset could not be read") from error
    _reject_prohibited_keys(raw)
    try:
        return model.model_validate_json(body, strict=True)
    except ValidationError as error:
        raise GroundedDatasetError("grounded JSON dataset is invalid") from error


def _load_jsonl_models(path: Path, model: type[ModelT]) -> tuple[ModelT, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise GroundedDatasetError("grounded JSONL dataset could not be read") from error
    records: list[ModelT] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise GroundedDatasetError("grounded JSONL contains a blank line")
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as error:
            raise GroundedDatasetError(
                f"grounded JSONL contains invalid JSON on line {line_number}"
            ) from error
        _reject_prohibited_keys(raw)
        try:
            records.append(model.model_validate_json(line, strict=True))
        except ValidationError as error:
            raise GroundedDatasetError(
                f"grounded JSONL contains an invalid record on line {line_number}"
            ) from error
    return tuple(records)


def _validate_bundle(
    *,
    assets: SafeGroundedAssetSnapshot,
    queries: tuple[GroundedQuery, ...],
    seed: tuple[GroundedSeedMatrix, ...],
) -> None:
    if len(assets.assets) != EXPECTED_ASSET_COUNT:
        raise GroundedDatasetError("grounded asset snapshot must contain exactly 41 assets")
    if len(queries) != EXPECTED_QUERY_COUNT:
        raise GroundedDatasetError("grounded query set must contain exactly 100 queries")
    if len(seed) != EXPECTED_QUERY_COUNT:
        raise GroundedDatasetError("grounded seed must contain exactly 100 matrices")
    query_refs = [query.query_ref for query in queries]
    if len(query_refs) != len(set(query_refs)) or query_refs != sorted(query_refs):
        raise GroundedDatasetError("grounded queries must be unique and sorted")
    if sum(query.split == "dev" for query in queries) != 80:
        raise GroundedDatasetError("grounded query set must contain exactly 80 dev queries")
    if sum(query.split == "holdout" for query in queries) != 20:
        raise GroundedDatasetError("grounded query set must contain exactly 20 holdout queries")
    if {query.category for query in queries} != set(GroundedQueryCategory):
        raise GroundedDatasetError("grounded query categories are incomplete")
    if not any(query.query == "小赛和赛先生在空间站" for query in queries):
        raise GroundedDatasetError("grounded query set is missing the fixed space-station query")
    seed_refs = [matrix.query_ref for matrix in seed]
    if seed_refs != query_refs:
        raise GroundedDatasetError("grounded seed query identity/order does not match queries")
    asset_refs = {asset.catalog_ref for asset in assets.assets}
    query_by_ref = {query.query_ref: query for query in queries}
    for matrix in seed:
        grades = {item.catalog_ref: item.grade for item in matrix.grades}
        if set(grades) != asset_refs:
            raise GroundedDatasetError("grounded seed matrix does not cover the exact asset set")
        relevant = sum(grade >= 2 for grade in grades.values())
        expected = query_by_ref[matrix.query_ref].expected_answer_kind
        if expected == "no_answer" and relevant:
            raise GroundedDatasetError("no-answer grounded query contains a usable relevant grade")
        if expected == "has_relevant" and not relevant:
            raise GroundedDatasetError("answerable grounded query has no usable relevant grade")


def _reject_prohibited_keys(value: object) -> None:
    found = _find_prohibited_keys(value)
    if found:
        raise GroundedDatasetError(
            "grounded dataset contains prohibited fields: " + ", ".join(sorted(found))
        )


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


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise GroundedDatasetError("grounded dataset could not be hashed") from error
