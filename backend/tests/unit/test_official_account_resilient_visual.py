from __future__ import annotations

import pytest
from app.application.ports.official_account_strict_visual import (
    RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS,
    resilient_visual_attempt_ordinal,
    resilient_visual_failure_retries,
    resilient_visual_provider_request_fingerprint,
)
from app.core.errors import ImageGenerationFailure
from app.domain.official_account_visual_pipeline import (
    RESILIENT_VISUAL_PIPELINE_VERSION,
    native_visual_audit_releases,
)
from app.infrastructure.official_account_runtime import official_account_identity_from_settings
from test_official_account_strict_visual_policy import _settings


def _failure(error_code: str) -> ImageGenerationFailure:
    return ImageGenerationFailure(
        error_code=error_code,
        disposition=(
            "unknown"
            if error_code == "official_account_generated_visual_result_unknown"
            else "terminal"
        ),
        reason=(
            "post_outcome_unknown"
            if error_code == "official_account_generated_visual_result_unknown"
            else "image_output_invalid"
            if error_code == "image_output_invalid"
            else "provider_failure"
        ),
    )


def test_resilient_identity_and_three_distinct_physical_keys_are_frozen() -> None:
    settings = _settings(
        official_account_local_visual_pipeline_version=RESILIENT_VISUAL_PIPELINE_VERSION
    )
    identity = official_account_identity_from_settings(settings, provider="zhipu", model="glm-5.2")
    assert identity.visual_pipeline_version == RESILIENT_VISUAL_PIPELINE_VERSION
    logical = "a" * 64
    keys = tuple(
        resilient_visual_provider_request_fingerprint(logical, attempt)
        for attempt in range(1, RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS + 1)
    )
    assert len(set(keys)) == 3
    assert tuple(resilient_visual_attempt_ordinal(4, attempt) for attempt in range(1, 4)) == (
        113,
        114,
        115,
    )
    with pytest.raises(ValueError):
        resilient_visual_provider_request_fingerprint(logical, 4)


@pytest.mark.parametrize(
    ("error_code", "retry"),
    [
        ("provider_request_rejected", True),
        ("image_provider_rejected", True),
        ("image_output_invalid", True),
        ("official_account_generated_visual_result_unknown", True),
        ("provider_authentication_failed", False),
        ("provider_input_limit", False),
        ("image_provider_not_configured", False),
        ("provider_identity_mismatch", False),
    ],
)
def test_resilient_retry_matrix(error_code: str, retry: bool) -> None:
    assert resilient_visual_failure_retries(_failure(error_code)) is retry


def test_resilient_lost_lease_is_not_retryable_provider_ambiguity() -> None:
    diagnostic = ImageGenerationFailure(
        error_code="official_account_generated_visual_result_unknown",
        disposition="unknown",
        reason="lease_authority_lost",
    )
    assert resilient_visual_failure_retries(diagnostic) is False


@pytest.mark.parametrize(
    ("status", "codes", "releases"),
    [
        ("accepted", (), True),
        ("rejected", ("strict_visual_audit_rejected",), True),
        ("unavailable", ("strict_visual_audit_unavailable",), True),
        ("result_unknown", ("strict_visual_audit_result_unknown",), True),
        ("rejected", ("strict_visual_audit_identity_mismatch",), False),
    ],
)
def test_resilient_review_is_advisory_but_identity_is_hard(
    status: str, codes: tuple[str, ...], releases: bool
) -> None:
    assert (
        native_visual_audit_releases(RESILIENT_VISUAL_PIPELINE_VERSION, status, codes) is releases
    )
