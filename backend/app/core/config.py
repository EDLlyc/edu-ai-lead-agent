from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated local configuration with safe development defaults."""

    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    business_timezone: str = "Asia/Shanghai"

    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://edu_ai:edu_ai_local_change_me@127.0.0.1:5432/edu_ai"
    )
    minio_endpoint: str = "http://127.0.0.1:9000"
    minio_bucket: str = "edu-ai-materials"
    minio_secure: bool = False
    minio_access_key: SecretStr = SecretStr("edu_ai_minio")
    minio_secret_key: SecretStr = SecretStr("edu_ai_minio_local_change_me")

    acquisition_schedule_hour: int = Field(default=6, ge=0, le=23)
    acquisition_schedule_minute: int = Field(default=30, ge=0, le=59)
    acquisition_catchup_hours: int = Field(default=12, ge=1, le=24)
    acquisition_poll_seconds: float = Field(default=2.0, ge=0.1, le=60)
    acquisition_worker_concurrency: int = Field(default=4, ge=1, le=32)
    acquisition_lease_seconds: int = Field(default=120, ge=30, le=3600)
    acquisition_heartbeat_seconds: int = Field(default=30, ge=5, le=600)
    acquisition_max_attempts: int = Field(default=3, ge=1, le=10)
    acquisition_max_response_bytes: int = Field(
        default=5 * 1024 * 1024, ge=64 * 1024, le=50 * 1024 * 1024
    )
    acquisition_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    acquisition_read_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    acquisition_total_timeout_seconds: float = Field(default=45.0, gt=0, le=180)
    acquisition_max_redirects: int = Field(default=3, ge=0, le=10)
    acquisition_user_agent: str = (
        "EduAILeadAgent/0.1 (+https://github.com/EDLlyc/edu-ai-lead-agent)"
    )
    acquisition_first_run_item_limit: int = Field(default=20, ge=1, le=100)
    acquisition_daily_item_limit: int = Field(default=10, ge=1, le=50)
    acquisition_first_run_scan_limit: int = Field(default=100, ge=1, le=500)
    acquisition_daily_scan_limit: int = Field(default=50, ge=1, le=200)
    acquisition_version: str = "acquisition-v1"

    governance_enabled: bool = False
    governance_scheduler_enabled: bool = False
    governance_worker_enabled: bool = False
    governance_poll_seconds: float = Field(default=5.0, ge=0.1, le=300)
    governance_worker_concurrency: int = Field(default=2, ge=1, le=16)
    governance_lease_seconds: int = Field(default=300, ge=60, le=3600)
    governance_heartbeat_seconds: int = Field(default=60, ge=5, le=600)
    governance_max_attempts: int = Field(default=3, ge=1, le=10)
    governance_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    governance_pipeline_version: str = "governance-v1"
    governance_normalization_version: str = "normalization-v1"
    governance_passage_schema_version: str = "passage-v1"
    governance_taxonomy_version: str = "ai-factual-taxonomy-v1"
    governance_prompt_version: str = "factual-analysis-v1"
    governance_analysis_schema_version: str = "factual-analysis-schema-v1"
    governance_embedding_input_version: str = "embedding-input-v1"
    governance_similarity_rule_version: str = "semantic-v1"
    governance_event_assignment_version: str = "event-assignment-v1"
    governance_checkpoint_database_url: SecretStr = SecretStr(
        "postgresql://edu_ai:edu_ai_local_change_me@127.0.0.1:5432/edu_ai"
    )

    content_enabled: bool = False
    content_scheduler_enabled: bool = False
    content_worker_enabled: bool = False
    content_schedule_hour: int = Field(default=7, ge=0, le=23)
    content_schedule_minute: int = Field(default=30, ge=0, le=59)
    content_catchup_hours: int = Field(default=12, ge=1, le=24)
    content_poll_seconds: float = Field(default=2.0, ge=0.1, le=300)
    content_worker_concurrency: int = Field(default=1, ge=1, le=8)
    content_lease_seconds: int = Field(default=120, ge=30, le=3600)
    content_heartbeat_seconds: int = Field(default=30, ge=5, le=600)
    content_max_attempts: int = Field(default=3, ge=1, le=10)
    content_scoring_version: str = "scoring-v1-preview.1"
    content_scoring_profile: str = "preview"
    brand_upload_max_bytes: int = Field(
        default=25 * 1024 * 1024,
        ge=64 * 1024,
        le=25 * 1024 * 1024,
    )
    brand_parse_max_pages: int = Field(default=120, ge=1, le=500)
    brand_parse_max_characters: int = Field(default=300_000, ge=1_000, le=1_000_000)
    brand_parse_max_chunks: int = Field(default=600, ge=1, le=2_000)
    brand_chunk_characters: int = Field(default=900, ge=300, le=3_000)
    brand_chunk_overlap_characters: int = Field(default=120, ge=0, le=500)
    brand_parser_version: str = "brand-parser-v1"
    brand_chunk_version: str = "brand-chunk-v1"
    brand_embedding_input_version: str = "brand-embedding-input-v1"
    brand_retrieval_version: str = "brand-hybrid-rrf-v1"

    ai_provider_mode: Literal["disabled", "fake", "zhipu"] = "disabled"
    ai_platform_base_url: str | None = None
    ai_platform_api_key: SecretStr | None = None
    ai_chat_model: str = "glm-5.2"
    ai_embedding_model: str = "embedding-3"
    ai_embedding_dimensions: int = 2048
    ai_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    ai_read_timeout_seconds: float = Field(default=120.0, gt=0, le=300)
    ai_total_timeout_seconds: float = Field(default=150.0, gt=0, le=360)
    ai_provider_concurrency: int = Field(default=2, ge=1, le=16)
    ai_max_attempts: int = Field(default=3, ge=1, le=6)
    ai_max_validation_corrections: int = Field(default=1, ge=0, le=1)
    ai_max_input_characters: int = Field(default=40_000, ge=1_000, le=200_000)
    ai_max_output_tokens: int = Field(default=4_096, ge=256, le=32_768)
    ai_max_tokens_per_run: int = Field(default=200_000, ge=4_096, le=10_000_000)
    ai_max_tokens_per_day: int = Field(default=1_000_000, ge=4_096, le=100_000_000)
    ai_max_cost_units_per_run: int = Field(default=100_000, ge=0, le=100_000_000)
    ai_max_cost_units_per_day: int = Field(default=500_000, ge=0, le=1_000_000_000)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def validate_runtime_invariants(self) -> "Settings":
        if self.acquisition_heartbeat_seconds >= self.acquisition_lease_seconds:
            raise ValueError("acquisition heartbeat must be shorter than the lease")
        if self.governance_heartbeat_seconds >= self.governance_lease_seconds:
            raise ValueError("governance heartbeat must be shorter than the lease")
        if self.content_heartbeat_seconds >= self.content_lease_seconds:
            raise ValueError("content heartbeat must be shorter than the lease")
        if self.brand_chunk_overlap_characters >= self.brand_chunk_characters:
            raise ValueError("brand chunk overlap must be shorter than the chunk")
        if (
            self.governance_scheduler_enabled or self.governance_worker_enabled
        ) and not self.governance_enabled:
            raise ValueError("governance processes require governance to be enabled")
        if (
            self.content_scheduler_enabled or self.content_worker_enabled
        ) and not self.content_enabled:
            raise ValueError("content processes require content to be enabled")
        if self.acquisition_total_timeout_seconds < self.acquisition_read_timeout_seconds:
            raise ValueError("acquisition total timeout must cover the read timeout")
        if (
            "EduAILeadAgent/" not in self.acquisition_user_agent
            or "+" not in self.acquisition_user_agent
        ):
            raise ValueError("acquisition user agent must identify the service and contact URL")
        if self.acquisition_first_run_scan_limit < self.acquisition_first_run_item_limit:
            raise ValueError("first-run scan limit must cover the accepted item limit")
        if self.acquisition_daily_scan_limit < self.acquisition_daily_item_limit:
            raise ValueError("daily scan limit must cover the accepted item limit")
        if self.ai_total_timeout_seconds < self.ai_read_timeout_seconds:
            raise ValueError("AI total timeout must cover the read timeout")
        if self.ai_max_tokens_per_run < self.ai_max_output_tokens:
            raise ValueError("AI run token budget must cover one maximum output")
        if self.ai_max_tokens_per_day < self.ai_max_tokens_per_run:
            raise ValueError("AI daily token budget must cover one run budget")
        if self.ai_max_cost_units_per_day < self.ai_max_cost_units_per_run:
            raise ValueError("AI daily cost budget must cover one run budget")
        if self.ai_embedding_dimensions != 2048:
            raise ValueError("embedding-3 persistence contract requires exactly 2048 dimensions")
        checkpoint_url = self.governance_checkpoint_database_url.get_secret_value()
        parsed_checkpoint_url = urlsplit(checkpoint_url)
        if (
            parsed_checkpoint_url.scheme not in {"postgresql", "postgres"}
            or not parsed_checkpoint_url.hostname
            or not parsed_checkpoint_url.path.strip("/")
            or parsed_checkpoint_url.fragment
        ):
            raise ValueError(
                "governance checkpoint URL must be a psycopg postgresql:// connection URL"
            )
        if self.ai_provider_mode == "zhipu":
            base_url = (self.ai_platform_base_url or "").strip()
            api_key = (
                self.ai_platform_api_key.get_secret_value().strip()
                if self.ai_platform_api_key is not None
                else ""
            )
            if not base_url:
                raise ValueError("Zhipu mode requires a non-blank AI platform base URL")
            if (self.governance_worker_enabled or self.content_worker_enabled) and not api_key:
                raise ValueError("Zhipu model workers require a non-blank API key")
            parsed_base_url = urlsplit(base_url)
            if (
                parsed_base_url.scheme != "https"
                or not parsed_base_url.hostname
                or parsed_base_url.username is not None
                or parsed_base_url.password is not None
                or parsed_base_url.query
                or parsed_base_url.fragment
            ):
                raise ValueError("Zhipu base URL must be an HTTPS origin/path without credentials")
        if not self.ai_chat_model.strip() or not self.ai_embedding_model.strip():
            raise ValueError("AI model identifiers must be non-blank")
        version_values = {
            self.governance_pipeline_version,
            self.governance_normalization_version,
            self.governance_passage_schema_version,
            self.governance_taxonomy_version,
            self.governance_prompt_version,
            self.governance_analysis_schema_version,
            self.governance_embedding_input_version,
            self.governance_similarity_rule_version,
            self.governance_event_assignment_version,
            self.content_scoring_version,
            self.content_scoring_profile,
            self.brand_parser_version,
            self.brand_chunk_version,
            self.brand_embedding_input_version,
            self.brand_retrieval_version,
        }
        if any(not value.strip() or len(value) > 80 for value in version_values):
            raise ValueError(
                "governance version identifiers must be non-empty and at most 80 chars"
            )
        if self.app_env == "production":
            placeholders = {
                "edu_ai_minio",
                "edu_ai_minio_local_change_me",
                "edu_ai_local_change_me",
            }
            database_url = self.database_url.get_secret_value()
            checkpoint_url = self.governance_checkpoint_database_url.get_secret_value()
            if (
                self.minio_access_key.get_secret_value() in placeholders
                or self.minio_secret_key.get_secret_value() in placeholders
                or any(value in database_url for value in placeholders)
                or (
                    self.governance_enabled
                    and any(value in checkpoint_url for value in placeholders)
                )
            ):
                raise ValueError("production credentials must not use development placeholders")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
