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
    acquisition_max_retry_after_seconds: int = Field(default=300, ge=0, le=3600)
    acquisition_user_agent: str = (
        "EduAILeadAgent/0.1 (+https://github.com/EDLlyc/edu-ai-lead-agent)"
    )
    acquisition_first_run_item_limit: int = Field(default=20, ge=1, le=100)
    acquisition_daily_item_limit: int = Field(default=10, ge=1, le=50)
    acquisition_first_run_scan_limit: int = Field(default=100, ge=1, le=500)
    acquisition_daily_scan_limit: int = Field(default=50, ge=1, le=200)
    acquisition_freshness_window_days: int = Field(default=10, ge=1, le=365)
    acquisition_version: str = "acquisition-v3-freshness-pacing"

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
    content_freshness_window_days: int = Field(default=10, ge=1, le=365)
    content_scoring_version: str = "scoring-v1-preview.2"
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
    brand_parser_version: str = "brand-parser-v2-glm-ocr"
    brand_chunk_version: str = "brand-chunk-v2-structure-aware"
    brand_embedding_input_version: str = "brand-embedding-input-v1"
    brand_retrieval_version: str = "brand-hybrid-rrf-v2-diverse"
    brand_ocr_model: str = Field(default="glm-ocr", min_length=1, max_length=120)
    brand_ocr_sparse_text_threshold: int = Field(default=40, ge=1, le=10_000)
    brand_ocr_max_request_bytes: int = Field(
        default=40 * 1024 * 1024, ge=64 * 1024, le=64 * 1024 * 1024
    )
    brand_ocr_max_response_bytes: int = Field(
        default=10 * 1024 * 1024, ge=64 * 1024, le=50 * 1024 * 1024
    )
    brand_ocr_timeout_seconds: float = Field(default=180.0, gt=0, le=360)
    brand_ocr_max_pages: int = Field(default=100, ge=1, le=100)
    copy_pipeline_version: str = "copy-pipeline-v8-parent-language"
    copy_generator_prompt_version: str = "moments-generator-v8-parent-language"
    copy_draft_schema_version: str = "moments-draft-schema-v1"
    copy_auditor_prompt_version: str = "moments-auditor-v8-parent-language"
    copy_audit_schema_version: str = "moments-audit-schema-v1"
    copy_rule_version: str = "moments-rules-v3-parent-language"
    copy_preview_policy_version: str = "preview-v2"
    copy_brand_context_limit: int = Field(default=6, ge=1, le=20)
    copy_max_output_tokens: int = Field(default=2_048, ge=512, le=8_192)
    copy_audit_max_output_tokens: int = Field(default=1_024, ge=256, le=4_096)

    image_enabled: bool = False
    image_provider_mode: Literal["disabled", "fake", "toapis", "comfly"] = "disabled"
    toapis_base_url: str = "https://toapis.com"
    toapis_api_key: SecretStr | None = None
    comfly_base_url: str = "https://ai.comfly.org"
    comfly_api_key: SecretStr | None = None
    comfly_output_hosts: str = ""
    image_model: str = "gpt-image-2"
    image_prompt_version: str = "image-prompt-v1"
    image_pipeline_version: str = "image-pipeline-v1"
    image_max_attempts: int = Field(default=3, ge=1, le=6)
    image_poll_initial_seconds: float = Field(default=5.0, ge=0.1, le=30)
    image_poll_interval_seconds: float = Field(default=7.0, ge=0.1, le=30)
    image_provider_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    image_provider_window_seconds: float = Field(default=120.0, gt=1, le=180)
    image_max_download_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    image_max_request_bytes: int = Field(default=8 * 1024 * 1024, ge=64 * 1024, le=50 * 1024 * 1024)
    image_max_provider_response_bytes: int = Field(
        default=32 * 1024 * 1024, ge=16 * 1024, le=50 * 1024 * 1024
    )
    image_reference_asset: str = "private/brand-materials/05-visual-assets/赛先生-显微镜.png"

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
        if self.content_freshness_window_days < 1:
            raise ValueError("content freshness window must be positive")
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
        if self.image_enabled and self.image_provider_mode == "disabled":
            raise ValueError("image provider must be enabled when image generation is enabled")
        if self.image_provider_mode == "toapis":
            key = self.toapis_api_key.get_secret_value().strip() if self.toapis_api_key else ""
            if not key:
                raise ValueError("ToAPIs image mode requires TOAPIS_API_KEY")
            parsed_toapis = urlsplit(self.toapis_base_url)
            if (
                parsed_toapis.scheme != "https"
                or parsed_toapis.hostname != "toapis.com"
                or parsed_toapis.port not in {None, 443}
                or parsed_toapis.path not in {"", "/"}
                or parsed_toapis.username is not None
                or parsed_toapis.password is not None
                or parsed_toapis.query
                or parsed_toapis.fragment
            ):
                raise ValueError("ToAPIs base URL must be exactly https://toapis.com")
        if self.image_provider_mode == "comfly":
            key = self.comfly_api_key.get_secret_value().strip() if self.comfly_api_key else ""
            if not key:
                raise ValueError("Comfly image mode requires COMFLY_API_KEY")
            base_url = self.comfly_base_url.strip()
            parsed_comfly = urlsplit(base_url)
            try:
                port = parsed_comfly.port
            except ValueError as exc:
                raise ValueError("Comfly base URL must be a valid HTTPS origin") from exc
            if (
                parsed_comfly.scheme != "https"
                or not parsed_comfly.hostname
                or port not in {None, 443}
                or parsed_comfly.path not in {"", "/"}
                or parsed_comfly.username is not None
                or parsed_comfly.password is not None
                or parsed_comfly.query
                or parsed_comfly.fragment
                or any(character.isspace() for character in base_url)
            ):
                raise ValueError("Comfly base URL must be an HTTPS origin without credentials")
            for host in self.comfly_output_hosts.split(","):
                normalized_host = host.strip().lower()
                if not normalized_host:
                    continue
                if (
                    len(normalized_host) > 253
                    or any(
                        character not in "abcdefghijklmnopqrstuvwxyz0123456789.-"
                        for character in normalized_host
                    )
                    or normalized_host.startswith(".")
                    or normalized_host.endswith(".")
                    or ".." in normalized_host
                ):
                    raise ValueError("Comfly output hosts must be bare DNS hostnames")
        if not self.image_model.strip() or any(ch.isspace() for ch in self.image_model):
            raise ValueError("image model identifier must be non-blank and contain no whitespace")
        if not self.brand_ocr_model.strip() or any(
            character.isspace() for character in self.brand_ocr_model
        ):
            raise ValueError(
                "brand OCR model identifier must be non-blank and contain no whitespace"
            )
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
            self.acquisition_version,
            self.brand_parser_version,
            self.brand_chunk_version,
            self.brand_embedding_input_version,
            self.brand_retrieval_version,
            self.copy_pipeline_version,
            self.copy_generator_prompt_version,
            self.copy_draft_schema_version,
            self.copy_auditor_prompt_version,
            self.copy_audit_schema_version,
            self.copy_rule_version,
            self.copy_preview_policy_version,
            self.image_prompt_version,
            self.image_pipeline_version,
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
