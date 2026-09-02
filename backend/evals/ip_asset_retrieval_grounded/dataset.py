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
    EXPECTED_V2_NO_ANSWER_COUNT,
    EXPECTED_V2_QUERY_COUNT,
    GroundedQuery,
    GroundedQueryCategory,
    GroundedQueryV2,
    GroundedRobustnessPairV2,
    GroundedSeedMatrix,
    GroundedSeedMatrixV2,
    GroundedSeedReviewLedgerV2,
    SafeGroundedAssetSnapshot,
)

FEATURE_ROOT = Path(__file__).resolve().parent
DEFAULT_ASSETS_PATH = FEATURE_ROOT / "assets.v1.json"
DEFAULT_QUERIES_PATH = FEATURE_ROOT / "queries.v1.jsonl"
DEFAULT_SEED_PATH = FEATURE_ROOT / "codex-seed.v1.jsonl"
DEFAULT_V2_QUERIES_PATH = FEATURE_ROOT / "queries.v2.jsonl"
DEFAULT_V2_SEED_PATH = FEATURE_ROOT / "codex-seed.v2.jsonl"
DEFAULT_V2_REVIEW_PATH = FEATURE_ROOT / "codex-seed-v2-review-ledger.json"
DEFAULT_V2_ROBUSTNESS_PATH = FEATURE_ROOT / "robustness-pairs.v2.jsonl"
EXPECTED_V1_ASSETS_SHA256 = "9399146b747a5028052254cb8f5bf6934b9712dba31a1c48cba58f802640a506"
EXPECTED_V1_QUERIES_SHA256 = "637a4f155beeae969353d6fb7fafb7a555e2bb695eebf91ef1c9cec6644e7e98"
EXPECTED_V1_SEED_SHA256 = "8bf85e957b21658dbb2de28d6c735927605571170a1a05cccf61339a61715165"
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


@dataclass(frozen=True, slots=True)
class GroundedDatasetBundleV2:
    assets: SafeGroundedAssetSnapshot
    queries: tuple[GroundedQueryV2, ...]
    seed: tuple[GroundedSeedMatrixV2, ...]
    review: GroundedSeedReviewLedgerV2
    robustness_pairs: tuple[GroundedRobustnessPairV2, ...]
    assets_sha256: str
    queries_sha256: str
    seed_sha256: str
    review_sha256: str
    robustness_sha256: str
    source_v1_queries_sha256: str
    source_v1_seed_sha256: str


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


def load_grounded_bundle_v2(
    *,
    assets_path: Path = DEFAULT_ASSETS_PATH,
    queries_path: Path = DEFAULT_V2_QUERIES_PATH,
    seed_path: Path = DEFAULT_V2_SEED_PATH,
    review_path: Path = DEFAULT_V2_REVIEW_PATH,
    robustness_path: Path = DEFAULT_V2_ROBUSTNESS_PATH,
    source_v1_queries_path: Path = DEFAULT_QUERIES_PATH,
    source_v1_seed_path: Path = DEFAULT_SEED_PATH,
) -> GroundedDatasetBundleV2:
    assets = _load_json_model(assets_path, SafeGroundedAssetSnapshot)
    queries = _load_jsonl_models(queries_path, GroundedQueryV2)
    seed = _load_jsonl_models(seed_path, GroundedSeedMatrixV2)
    review = _load_json_model(review_path, GroundedSeedReviewLedgerV2)
    robustness_pairs = _load_jsonl_models(robustness_path, GroundedRobustnessPairV2)
    source_v1_queries = _load_jsonl_models(source_v1_queries_path, GroundedQuery)
    source_v1_seed = _load_jsonl_models(source_v1_seed_path, GroundedSeedMatrix)
    source_v1_queries_sha256 = _sha256_file(source_v1_queries_path)
    source_v1_seed_sha256 = _sha256_file(source_v1_seed_path)
    assets_sha256 = _sha256_file(assets_path)
    _validate_v1_identity(
        assets_sha256=assets_sha256,
        queries_sha256=source_v1_queries_sha256,
        seed_sha256=source_v1_seed_sha256,
    )
    _validate_bundle_v2(
        assets=assets,
        queries=queries,
        seed=seed,
        review=review,
        robustness_pairs=robustness_pairs,
        source_v1_queries=source_v1_queries,
        source_v1_seed=source_v1_seed,
        source_v1_seed_sha256=source_v1_seed_sha256,
    )
    return GroundedDatasetBundleV2(
        assets=assets,
        queries=queries,
        seed=seed,
        review=review,
        robustness_pairs=robustness_pairs,
        assets_sha256=assets_sha256,
        queries_sha256=_sha256_file(queries_path),
        seed_sha256=_sha256_file(seed_path),
        review_sha256=_sha256_file(review_path),
        robustness_sha256=_sha256_file(robustness_path),
        source_v1_queries_sha256=source_v1_queries_sha256,
        source_v1_seed_sha256=source_v1_seed_sha256,
    )


def _validate_v1_identity(
    *,
    assets_sha256: str,
    queries_sha256: str,
    seed_sha256: str,
) -> None:
    drifted = [
        name
        for name, actual, expected in (
            ("assets.v1.json", assets_sha256, EXPECTED_V1_ASSETS_SHA256),
            ("queries.v1.jsonl", queries_sha256, EXPECTED_V1_QUERIES_SHA256),
            ("codex-seed.v1.jsonl", seed_sha256, EXPECTED_V1_SEED_SHA256),
        )
        if actual != expected
    ]
    if drifted:
        raise GroundedDatasetError("grounded Seed V1 identity drifted: " + ", ".join(drifted))


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


def _validate_bundle_v2(
    *,
    assets: SafeGroundedAssetSnapshot,
    queries: tuple[GroundedQueryV2, ...],
    seed: tuple[GroundedSeedMatrixV2, ...],
    review: GroundedSeedReviewLedgerV2,
    robustness_pairs: tuple[GroundedRobustnessPairV2, ...],
    source_v1_queries: tuple[GroundedQuery, ...],
    source_v1_seed: tuple[GroundedSeedMatrix, ...],
    source_v1_seed_sha256: str,
) -> None:
    if len(assets.assets) != EXPECTED_ASSET_COUNT:
        raise GroundedDatasetError("grounded Seed V2 needs exactly 41 assets")
    if len(queries) != EXPECTED_V2_QUERY_COUNT or len(seed) != EXPECTED_V2_QUERY_COUNT:
        raise GroundedDatasetError("grounded Seed V2 needs exactly 124 queries and matrices")
    query_refs = [query.query_ref for query in queries]
    if len(query_refs) != len(set(query_refs)) or query_refs != sorted(query_refs):
        raise GroundedDatasetError("grounded Seed V2 queries must be unique and sorted")
    if sum(query.split == "dev" for query in queries) != 98:
        raise GroundedDatasetError("grounded Seed V2 needs exactly 98 dev queries")
    if sum(query.split == "holdout" for query in queries) != 26:
        raise GroundedDatasetError("grounded Seed V2 needs exactly 26 holdout queries")
    if (
        sum(query.expected_answer_kind == "no_answer" for query in queries)
        != EXPECTED_V2_NO_ANSWER_COUNT
    ):
        raise GroundedDatasetError("grounded Seed V2 needs exactly 30 no-answer queries")
    source_query_by_ref = {query.query_ref: query for query in source_v1_queries}
    v2_query_by_ref = {query.query_ref: query for query in queries}
    if len(source_query_by_ref) != EXPECTED_QUERY_COUNT:
        raise GroundedDatasetError("grounded Seed V1 query identity is incomplete")
    for ref, source in source_query_by_ref.items():
        candidate = v2_query_by_ref.get(ref)
        if candidate is None or (
            candidate.category != source.category
            or candidate.split != source.split
            or candidate.query != source.query
            or candidate.expected_answer_kind != source.expected_answer_kind
            or candidate.challenge_kind is not None
        ):
            raise GroundedDatasetError("grounded Seed V2 changed a Seed V1 query")
    new_queries = tuple(query for query in queries if query.query_ref not in source_query_by_ref)
    if len(new_queries) != 24:
        raise GroundedDatasetError("grounded Seed V2 must add exactly 24 queries")
    if (
        sum(query.split == "dev" for query in new_queries) != 18
        or sum(query.split == "holdout" for query in new_queries) != 6
    ):
        raise GroundedDatasetError("grounded Seed V2 additions must be 18 dev and 6 holdout")
    if any(
        query.category is not GroundedQueryCategory.NO_ANSWER
        or query.expected_answer_kind != "no_answer"
        or query.challenge_kind is None
        for query in new_queries
    ):
        raise GroundedDatasetError("grounded Seed V2 additions must be typed no-answer challenges")
    seed_refs = [matrix.query_ref for matrix in seed]
    if seed_refs != query_refs:
        raise GroundedDatasetError("grounded Seed V2 matrix order does not match queries")
    asset_refs = {asset.catalog_ref for asset in assets.assets}
    grades_by_query: dict[str, dict[str, int]] = {}
    for matrix in seed:
        grades = {item.catalog_ref: item.grade for item in matrix.grades}
        if set(grades) != asset_refs:
            raise GroundedDatasetError("grounded Seed V2 matrix does not cover the asset set")
        grades_by_query[matrix.query_ref] = grades
        relevant = sum(grade >= 2 for grade in grades.values())
        expected = v2_query_by_ref[matrix.query_ref].expected_answer_kind
        if expected == "no_answer" and relevant:
            raise GroundedDatasetError("grounded Seed V2 no-answer query has usable relevance")
        if expected == "has_relevant" and not relevant:
            raise GroundedDatasetError("grounded Seed V2 answerable query has no usable relevance")
    if review.source_seed_sha256 != source_v1_seed_sha256:
        raise GroundedDatasetError("grounded Seed V2 review source hash is not Seed V1")
    source_grades = {
        matrix.query_ref: {grade.catalog_ref: grade.grade for grade in matrix.grades}
        for matrix in source_v1_seed
    }
    changes = {(item.query_ref, item.catalog_ref): item for item in review.changes}
    for ref in source_query_by_ref:
        for catalog_ref in asset_refs:
            source_grade = source_grades[ref][catalog_ref]
            candidate_grade = grades_by_query[ref][catalog_ref]
            change = changes.get((ref, catalog_ref))
            if candidate_grade == source_grade and change is not None:
                raise GroundedDatasetError("grounded Seed V2 review ledger has a false change")
            if candidate_grade != source_grade and (
                change is None
                or change.old_grade != source_grade
                or change.new_grade != candidate_grade
            ):
                raise GroundedDatasetError("grounded Seed V2 grade change is missing from ledger")
    challenge_refs = {query.query_ref for query in new_queries}
    if (
        len(robustness_pairs) != 24
        or {pair.challenge_query_ref for pair in robustness_pairs} != challenge_refs
    ):
        raise GroundedDatasetError("grounded Seed V2 robustness metadata is incomplete")
    if [pair.challenge_query_ref for pair in robustness_pairs] != sorted(challenge_refs):
        raise GroundedDatasetError("grounded Seed V2 robustness pairs must be sorted")
    for pair in robustness_pairs:
        challenge = v2_query_by_ref[pair.challenge_query_ref]
        anchor = v2_query_by_ref.get(pair.anchor_query_ref)
        if anchor is None or anchor.expected_answer_kind != "has_relevant":
            raise GroundedDatasetError("grounded Seed V2 robustness anchor must be answerable")
        if anchor.split != challenge.split:
            raise GroundedDatasetError("grounded Seed V2 robustness pair must stay in one split")


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
