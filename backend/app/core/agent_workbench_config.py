from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentWorkbenchSettings(BaseSettings):
    """Isolated local-workbench configuration; production API never imports it."""

    app_env: Literal["development", "test", "production"] = "development"
    agent_workbench_enabled: bool = False
    agent_workbench_data_mode: Literal["fixture"] = "fixture"
    agent_mcp_data_mode: Literal["fixture", "postgres"] = "fixture"
    agent_mcp_real_data_enabled: bool = False
    agent_workbench_model_mode: Literal["deterministic", "openai"] = "deterministic"
    agent_workbench_live_enabled: bool = False
    agent_workbench_openai_base_url: str | None = None
    agent_workbench_openai_api_key: SecretStr | None = None
    agent_workbench_openai_model: str = Field(default="glm-5.2", min_length=1, max_length=120)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,
    )

    @model_validator(mode="after")
    def validate_local_only_contract(self) -> Self:
        if self.agent_workbench_enabled and self.app_env == "production":
            raise ValueError("agent workbench cannot be enabled in production")
        if self.agent_mcp_real_data_enabled:
            if self.app_env != "development":
                raise ValueError("real-data agent MCP is development-only")
            if self.agent_mcp_data_mode != "postgres":
                raise ValueError("real-data agent MCP requires postgres data mode")
        elif self.agent_mcp_data_mode != "fixture":
            raise ValueError("postgres agent MCP data mode requires explicit enablement")
        if self.agent_workbench_model_mode == "openai":
            if not self.agent_workbench_live_enabled:
                raise ValueError("OpenAI-compatible workbench mode requires explicit live opt-in")
            if self.app_env != "development":
                raise ValueError("OpenAI-compatible workbench mode is development-only")
            if not (self.agent_workbench_openai_base_url or "").strip():
                raise ValueError("OpenAI-compatible workbench mode requires a base URL")
        elif self.agent_workbench_live_enabled:
            raise ValueError("live workbench opt-in is valid only for OpenAI-compatible mode")
        return self


@lru_cache
def get_agent_workbench_settings() -> AgentWorkbenchSettings:
    return AgentWorkbenchSettings()
