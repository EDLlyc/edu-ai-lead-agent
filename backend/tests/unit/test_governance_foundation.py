from uuid import uuid4

import pytest
from app.application.services.governance_runtime import build_governance_version_bundle
from app.core.config import Settings
from app.domain.governance_enums import FactualCategory
from app.domain.governance_value_objects import (
    canonical_candidate_pair,
    event_assignment_advisory_key,
    governance_job_idempotency_key,
    stable_passage_id,
)
from app.infrastructure.db.governance_checkpointer import PostgresGovernanceCheckpointer
from app.infrastructure.db.governance_repositories import _validated_safe_metadata
from pydantic import SecretStr, ValidationError


def _settings(**updates: object) -> Settings:
    return Settings(_env_file=None, **updates)  # type: ignore[call-arg]


def test_governance_defaults_are_disabled_and_versioned() -> None:
    settings = _settings()
    bundle = build_governance_version_bundle(settings)

    assert settings.governance_enabled is False
    assert settings.governance_scheduler_enabled is False
    assert settings.governance_worker_enabled is False
    assert bundle.chat_model == "glm-5.2"
    assert bundle.embedding_model == "embedding-3"
    assert bundle.embedding_dimensions == 2048
    assert len(bundle.fingerprint) == 64
    assert "api_key" not in bundle.as_metadata()


def test_governance_settings_enforce_leases_vectors_urls_and_budgets() -> None:
    with pytest.raises(ValidationError, match="governance heartbeat"):
        _settings(governance_lease_seconds=60, governance_heartbeat_seconds=60)
    with pytest.raises(ValidationError, match="processes require governance"):
        _settings(governance_scheduler_enabled=True)
    with pytest.raises(ValidationError, match="2048 dimensions"):
        _settings(ai_embedding_dimensions=1024)
    with pytest.raises(ValidationError, match="psycopg"):
        _settings(
            governance_checkpoint_database_url=SecretStr(
                "postgresql+asyncpg://service:secret@db:5432/service"
            )
        )
    with pytest.raises(ValidationError, match="psycopg"):
        _settings(governance_checkpoint_database_url=SecretStr("postgresql://"))
    with pytest.raises(ValidationError, match="daily token budget"):
        _settings(ai_max_tokens_per_run=20_000, ai_max_tokens_per_day=10_000)
    with pytest.raises(ValidationError, match="daily cost budget"):
        _settings(ai_max_cost_units_per_run=20_000, ai_max_cost_units_per_day=10_000)


def test_zhipu_mode_requires_non_blank_secret_configuration() -> None:
    with pytest.raises(ValidationError, match="non-blank"):
        _settings(
            governance_enabled=True,
            governance_worker_enabled=True,
            ai_provider_mode="zhipu",
            ai_platform_base_url=" ",
            ai_platform_api_key=SecretStr(" "),
        )
    with pytest.raises(ValidationError, match="non-blank API key"):
        _settings(
            governance_enabled=True,
            governance_worker_enabled=True,
            ai_provider_mode="zhipu",
            ai_platform_base_url="https://provider.invalid/v4",
        )
    settings = _settings(
        ai_provider_mode="zhipu",
        ai_platform_base_url="https://provider.invalid/v4",
    )
    assert settings.ai_platform_api_key is None
    worker_settings = _settings(
        governance_enabled=True,
        governance_worker_enabled=True,
        ai_provider_mode="zhipu",
        ai_platform_base_url="https://provider.invalid/v4",
        ai_platform_api_key=SecretStr("local-test-secret"),
    )
    assert str(worker_settings.ai_platform_api_key) == "**********"
    assert "local-test-secret" not in repr(worker_settings)
    with pytest.raises(ValidationError, match="HTTPS"):
        _settings(
            ai_provider_mode="zhipu",
            ai_platform_base_url="http://provider.invalid/v4",
            ai_platform_api_key=SecretStr("local-test-secret"),
        )


def test_version_keys_passages_and_pairs_are_deterministic() -> None:
    candidate_id = uuid4()
    other_candidate_id = uuid4()
    bundle = build_governance_version_bundle(_settings())
    first_key = governance_job_idempotency_key(candidate_id, "a" * 64, bundle)
    second_key = governance_job_idempotency_key(candidate_id, "a" * 64, bundle)
    changed_key = governance_job_idempotency_key(candidate_id, "b" * 64, bundle)

    assert first_key == second_key
    assert first_key != changed_key
    assert stable_passage_id(candidate_id, "normalization-v1", 0, "c" * 64) == (
        stable_passage_id(candidate_id, "normalization-v1", 0, "c" * 64)
    )
    left, right = canonical_candidate_pair(candidate_id, other_candidate_id)
    assert left.int < right.int
    with pytest.raises(ValueError, match="different candidates"):
        canonical_candidate_pair(candidate_id, candidate_id)
    assert event_assignment_advisory_key(candidate_id, "policy-v1") == (
        event_assignment_advisory_key(candidate_id, "policy-v1")
    )


def test_taxonomy_has_the_approved_seven_categories() -> None:
    assert {category.value for category in FactualCategory} == {
        "ai_education_policy",
        "large_generative_models",
        "robotics_embodied_intelligence",
        "ai_compute_chips",
        "youth_science_education",
        "ai_industry_application",
        "ai_governance_safety",
    }


def test_checkpointer_rejects_asyncpg_url_without_exposing_it() -> None:
    with pytest.raises(ValueError, match="psycopg"):
        PostgresGovernanceCheckpointer(
            SecretStr("postgresql+asyncpg://service:do-not-print@db:5432/service")
        )


def test_safe_audit_metadata_rejects_nested_content_and_credentials() -> None:
    safe = {
        "counts": {"facts": 3},
        "provider_request_id": "request-1",
        "response_status": "ok",
        "prompt_tokens": 20,
        "reasoning_tokens": 10,
        "source_text_hash": "a" * 64,
    }
    assert _validated_safe_metadata(safe) == safe
    for unsafe_key in (
        "reasoning_content",
        "raw_response",
        "prompt_text",
        "source_body",
        "authorization_header",
        "apiKey",
        "APIKey",
        "api-key",
        "sourceBodies",
        "checkpoint",
        "provider_output",
        "error_message",
    ):
        with pytest.raises(ValueError, match="forbidden"):
            _validated_safe_metadata({"provider": {unsafe_key: "hidden"}})
    with pytest.raises(ValueError, match="JSON-compatible"):
        _validated_safe_metadata({"unexpected": object()})
