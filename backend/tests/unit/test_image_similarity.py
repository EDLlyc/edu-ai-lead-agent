from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from app.domain.image_similarity import (
    ImageSimilarityReference,
    evaluate_image_similarity,
    perceptual_dhash,
    perceptual_hash_distance,
)

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "visual_diversity"


def _body(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def test_perceptual_fixture_matrix_calibrates_near_and_different_images() -> None:
    base = perceptual_dhash(_body("base.pgm"))
    near = perceptual_dhash(_body("near.pgm"))
    different = perceptual_dhash(_body("different.pgm"))

    assert base == "ffffffffffffffff"
    assert perceptual_hash_distance(base, near) == 1
    assert perceptual_hash_distance(base, different) == 64


def test_similarity_detects_exact_sha_even_without_historical_perceptual_hash() -> None:
    body = _body("base.pgm")
    result = evaluate_image_similarity(
        body,
        references=(
            ImageSimilarityReference(
                artifact_id="historical-v1",
                sha256=hashlib.sha256(body).hexdigest(),
                perceptual_hash=None,
            ),
        ),
        threshold=0,
    )

    assert result.exact_duplicate is True
    assert result.near_duplicate is True
    assert result.nearest_artifact_id == "historical-v1"
    assert result.nearest_distance == 0


def test_similarity_threshold_boundary_is_inclusive() -> None:
    base_body = _body("base.pgm")
    near_body = _body("near.pgm")
    reference = ImageSimilarityReference(
        artifact_id="base",
        sha256=hashlib.sha256(base_body).hexdigest(),
        perceptual_hash=perceptual_dhash(base_body),
    )

    at_boundary = evaluate_image_similarity(near_body, references=(reference,), threshold=1)
    below_boundary = evaluate_image_similarity(near_body, references=(reference,), threshold=0)

    assert at_boundary.near_duplicate is True
    assert at_boundary.nearest_distance == 1
    assert below_boundary.near_duplicate is False


def test_similarity_marks_clearly_different_fixture_as_distinct() -> None:
    base_body = _body("base.pgm")
    result = evaluate_image_similarity(
        _body("different.pgm"),
        references=(
            ImageSimilarityReference(
                artifact_id="base",
                sha256=hashlib.sha256(base_body).hexdigest(),
                perceptual_hash=perceptual_dhash(base_body),
            ),
        ),
        threshold=6,
    )

    assert result.near_duplicate is False
    assert result.nearest_distance == 64


def test_similarity_rejects_invalid_hashes_and_bounds() -> None:
    with pytest.raises(ValueError, match="16 hexadecimal"):
        perceptual_hash_distance("0", "f" * 16)
    with pytest.raises(ValueError, match=r"\[0, 64\]"):
        evaluate_image_similarity(_body("base.pgm"), references=(), threshold=65)
    with pytest.raises(ValueError, match="supported raster"):
        perceptual_dhash(b"not-an-image")
