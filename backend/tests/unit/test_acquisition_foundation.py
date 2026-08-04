from datetime import UTC, date, datetime

import pytest
from app.core.config import Settings
from app.core.logging import redact_mapping, safe_url
from app.domain.enums import JobStatus, RunStatus
from app.domain.state import validate_job_transition, validate_run_transition
from app.domain.value_objects import due_business_date, sha256_bytes, stable_key
from pydantic import SecretStr, ValidationError


def test_settings_enforce_lease_and_heartbeat_invariant() -> None:
    with pytest.raises(ValidationError, match="heartbeat must be shorter"):
        Settings(acquisition_lease_seconds=30, acquisition_heartbeat_seconds=30)


def test_settings_require_scan_limits_to_cover_accepted_item_limits() -> None:
    with pytest.raises(ValidationError, match="first-run scan limit"):
        Settings(acquisition_first_run_item_limit=20, acquisition_first_run_scan_limit=19)
    with pytest.raises(ValidationError, match="daily scan limit"):
        Settings(acquisition_daily_item_limit=10, acquisition_daily_scan_limit=9)


def test_production_settings_reject_placeholder_credentials() -> None:
    with pytest.raises(ValidationError, match="production credentials"):
        Settings(_env_file=None, app_env="production")

    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url=SecretStr("postgresql+asyncpg://service:strong-password@db:5432/service"),
        minio_endpoint="https://minio.internal",
        minio_secure=True,
        minio_access_key=SecretStr("production-access"),
        minio_secret_key=SecretStr("production-secret-value"),
    )
    assert str(settings.minio_secret_key) == "**********"


def test_brand_ocr_model_is_a_bounded_identifier() -> None:
    with pytest.raises(ValidationError, match="brand OCR model identifier"):
        Settings(_env_file=None, brand_ocr_model="glm ocr")
    with pytest.raises(ValidationError, match="brand OCR model identifier"):
        Settings(_env_file=None, brand_ocr_model=" ")


def test_state_transitions_are_explicit() -> None:
    validate_run_transition(RunStatus.QUEUED, RunStatus.RUNNING)
    validate_job_transition(JobStatus.RUNNING, JobStatus.RETRY_SCHEDULED)
    with pytest.raises(ValueError, match="invalid run transition"):
        validate_run_transition(RunStatus.SUCCEEDED, RunStatus.RUNNING)
    with pytest.raises(ValueError, match="invalid job transition"):
        validate_job_transition(JobStatus.QUEUED, JobStatus.SUCCEEDED)


def test_hash_and_idempotency_helpers_are_deterministic() -> None:
    assert sha256_bytes(b"evidence") == sha256_bytes(b"evidence")
    assert stable_key("run", 1, date(2026, 7, 28)) == stable_key("run", 1, date(2026, 7, 28))
    assert stable_key("run", 1) != stable_key("run", 2)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 7, 27, 22, 29, tzinfo=UTC), None),
        (datetime(2026, 7, 27, 22, 30, tzinfo=UTC), date(2026, 7, 28)),
        (datetime(2026, 7, 28, 9, 0, tzinfo=UTC), date(2026, 7, 28)),
        (datetime(2026, 7, 28, 11, 0, 1, tzinfo=UTC), None),
    ],
)
def test_daily_schedule_and_bounded_catchup(now: datetime, expected: date | None) -> None:
    assert (
        due_business_date(
            now,
            timezone="Asia/Shanghai",
            hour=6,
            minute=30,
            catchup_hours=12,
        )
        == expected
    )


def test_log_projection_removes_sensitive_values() -> None:
    assert safe_url("https://example.com/path?token=secret") == "https://example.com/path"
    assert redact_mapping(
        {
            "authorization": "Bearer secret",
            "headers": {"Set-Cookie": "session=secret", "etag": "safe"},
            "raw_html": "<html>secret</html>",
        }
    ) == {
        "authorization": "[REDACTED]",
        "headers": {"Set-Cookie": "[REDACTED]", "etag": "safe"},
        "raw_html": "[REDACTED]",
    }
