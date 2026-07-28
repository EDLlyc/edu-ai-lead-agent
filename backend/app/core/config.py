from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
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

    ai_platform_base_url: str | None = None
    ai_platform_api_key: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
