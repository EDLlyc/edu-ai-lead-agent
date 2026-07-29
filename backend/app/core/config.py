from functools import lru_cache
from typing import Literal

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

    ai_platform_base_url: str | None = None
    ai_platform_api_key: SecretStr | None = None

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
        if self.app_env == "production":
            placeholders = {
                "edu_ai_minio",
                "edu_ai_minio_local_change_me",
                "edu_ai_local_change_me",
            }
            database_url = self.database_url.get_secret_value()
            if (
                self.minio_access_key.get_secret_value() in placeholders
                or self.minio_secret_key.get_secret_value() in placeholders
                or any(value in database_url for value in placeholders)
            ):
                raise ValueError("production credentials must not use development placeholders")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
