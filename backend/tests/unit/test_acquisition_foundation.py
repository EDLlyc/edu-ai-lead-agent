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


def test_brand_version_bundles_are_frozen_and_mixed_labels_fail_closed() -> None:
    legacy = Settings(
        _env_file=None,
        brand_parser_version="brand-parser-v2-glm-ocr",
        brand_chunk_version="brand-chunk-v2-structure-aware",
        brand_embedding_input_version="brand-embedding-input-v1",
        brand_retrieval_version="brand-hybrid-rrf-v2-diverse",
    )
    assert legacy.brand_parser_version == "brand-parser-v2-glm-ocr"

    with pytest.raises(ValidationError, match="supported frozen bundle"):
        Settings(_env_file=None, brand_parser_version="brand-parser-v2-glm-ocr")
    with pytest.raises(ValidationError, match="brand retrieval version is unsupported"):
        Settings(_env_file=None, brand_retrieval_version="brand-hybrid-rrf-unknown")


def test_image_ocr_settings_are_bounded_and_separate_from_text_generation() -> None:
    settings = Settings(_env_file=None, ai_chat_model="glm-5.2")

    assert settings.ai_chat_model == "glm-5.2"
    assert settings.image_ocr_model == "glm-ocr"
    assert settings.image_ocr_max_input_bytes == 10 * 1024 * 1024
    assert settings.image_ocr_max_response_bytes == 1024 * 1024
    assert settings.image_ocr_timeout_seconds == 120.0

    with pytest.raises(ValidationError, match="image OCR model identifier"):
        Settings(_env_file=None, image_ocr_model="glm ocr")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, image_ocr_max_input_bytes=10 * 1024 * 1024 + 1)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, image_ocr_max_response_bytes=1024 * 1024 + 1)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, image_ocr_timeout_seconds=361)


def test_image_ocr_numeric_bounds_parse_from_environment_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMAGE_OCR_MAX_INPUT_BYTES", "10485760")
    monkeypatch.setenv("IMAGE_OCR_MAX_RESPONSE_BYTES", "1048576")
    monkeypatch.setenv("IMAGE_OCR_TIMEOUT_SECONDS", "120")

    settings = Settings(_env_file=None)

    assert settings.image_ocr_max_input_bytes == 10 * 1024 * 1024
    assert settings.image_ocr_max_response_bytes == 1024 * 1024
    assert settings.image_ocr_timeout_seconds == 120.0


def test_visual_embedding_defaults_are_provider_free_and_enabled_mode_is_closed() -> None:
    defaults = Settings(_env_file=None)
    assert defaults.visual_semantic_enabled is False
    assert defaults.visual_embedding_provider_mode == "disabled"
    assert defaults.visual_embedding_api_key is None
    assert defaults.visual_embedding_dimensions == 2048
    assert defaults.visual_embedding_input_policy_version == "brand-visual-embedding-input-v2"
    assert (
        defaults.visual_embedding_identity.input_policy_version == "brand-visual-embedding-input-v2"
    )

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            visual_embedding_input_policy_version="brand-visual-embedding-input-v1",
        )

    with pytest.raises(ValidationError, match="requires an embedding provider"):
        Settings(_env_file=None, visual_semantic_enabled=True)

    fake = Settings(
        _env_file=None,
        visual_semantic_enabled=True,
        visual_embedding_provider_mode="fake",
    )
    assert fake.visual_embedding_model == "qwen3-vl-embedding"

    with pytest.raises(ValidationError, match="approved asset selection"):
        Settings(
            _env_file=None,
            visual_semantic_enabled=True,
            visual_embedding_provider_mode="fake",
            image_selector_enabled=False,
        )

    with pytest.raises(ValidationError, match="lease must outlast"):
        Settings(
            _env_file=None,
            visual_embedding_timeout_seconds=60,
            visual_index_lease_seconds=60,
        )

    with pytest.raises(ValidationError, match="endpoint and API key"):
        Settings(
            _env_file=None,
            visual_semantic_enabled=True,
            visual_embedding_provider_mode="alibaba",
        )


def test_visual_embedding_dimensions_parse_exact_env_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VISUAL_EMBEDDING_DIMENSIONS", "2048")
    assert Settings(_env_file=None).visual_embedding_dimensions == 2048

    monkeypatch.setenv("VISUAL_EMBEDDING_DIMENSIONS", "1024")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


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
