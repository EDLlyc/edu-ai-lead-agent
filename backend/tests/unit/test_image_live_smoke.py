from __future__ import annotations

from app.core.errors import ImageOutputValidationError, ImageProviderRejectedError
from app.image_live_smoke import _effective_business_run_id, _safe_failure_summary


def test_smoke_generates_a_fresh_business_run_id_when_omitted() -> None:
    first = _effective_business_run_id(None)
    second = _effective_business_run_id("")

    assert first.startswith("live-smoke-")
    assert second.startswith("live-smoke-")
    assert first != second
    assert _effective_business_run_id(" operator-run-1 ") == "operator-run-1"


def test_safe_failure_summary_includes_only_allowlisted_validation_reason() -> None:
    summary = _safe_failure_summary(ImageOutputValidationError("image_dimensions_invalid"))

    assert summary == ("code=image_output_invalid retryable=false reason=image_dimensions_invalid")


def test_safe_failure_summary_includes_only_allowlisted_rejection_metadata() -> None:
    summary = _safe_failure_summary(
        ImageProviderRejectedError(http_status=200, response_kind="other")
    )

    assert summary == (
        "code=image_provider_rejected retryable=false "
        "provider_http_status=200 provider_response_kind=other"
    )
    assert "PRIVATE-COMFLY-RESPONSE" not in summary
