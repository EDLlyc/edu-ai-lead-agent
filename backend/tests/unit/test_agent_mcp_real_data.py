from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from app.agent_mcp_real_data_main import (
    build_real_data_mcp_server,
    validate_real_data_mcp_settings,
)
from app.agent_workbench_runtime import (
    build_fixture_tool_registry,
    build_postgres_agent_tool_registry,
)
from app.application.ports.brand_knowledge import BrandEmbeddingModel
from app.core.agent_workbench_config import AgentWorkbenchSettings
from app.core.config import Settings
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def _real_data_workbench_settings(**updates: object) -> AgentWorkbenchSettings:
    values: dict[str, object] = {
        "app_env": "development",
        "agent_mcp_data_mode": "postgres",
        "agent_mcp_real_data_enabled": True,
    }
    values.update(updates)
    return AgentWorkbenchSettings.model_validate(values)


def _application_settings(
    *,
    app_env: str = "development",
    provider_mode: str = "zhipu",
    brand_provider_mode: str = "alibaba",
    zhipu_credentials: bool = True,
) -> Settings:
    return cast(
        Settings,
        SimpleNamespace(
            app_env=app_env,
            ai_provider_mode=provider_mode,
            resolved_brand_embedding_provider_mode=brand_provider_mode,
            ai_platform_base_url=(
                "https://open.bigmodel.invalid/api/paas/v4" if zhipu_credentials else None
            ),
            ai_platform_api_key=(SecretStr("test-only-zhipu-key") if zhipu_credentials else None),
        ),
    )


def test_real_data_mcp_settings_require_development_postgres_opt_in() -> None:
    assert _real_data_workbench_settings().agent_mcp_real_data_enabled is True

    with pytest.raises(ValueError, match="postgres data mode"):
        _real_data_workbench_settings(agent_mcp_data_mode="fixture")
    with pytest.raises(ValueError, match="development-only"):
        _real_data_workbench_settings(app_env="test")
    with pytest.raises(ValueError, match="explicit enablement"):
        AgentWorkbenchSettings(
            _env_file=None,
            app_env="development",
            agent_mcp_data_mode="postgres",
        )


@pytest.mark.parametrize(
    ("workbench_settings", "application_settings", "message"),
    (
        (
            _real_data_workbench_settings(),
            _application_settings(app_env="production"),
            "development-only",
        ),
        (
            _real_data_workbench_settings(),
            _application_settings(provider_mode="fake"),
            "Zhipu planning",
        ),
        (
            _real_data_workbench_settings(),
            _application_settings(brand_provider_mode="disabled"),
            "Alibaba multimodal",
        ),
        (
            _real_data_workbench_settings(),
            _application_settings(zhipu_credentials=False),
            "Zhipu credentials",
        ),
        (
            AgentWorkbenchSettings(_env_file=None),
            _application_settings(),
            "explicit enablement",
        ),
    ),
)
def test_real_data_mcp_runtime_validation_fails_closed(
    workbench_settings: AgentWorkbenchSettings,
    application_settings: Settings,
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message):
        validate_real_data_mcp_settings(workbench_settings, application_settings)


def test_postgres_registry_reuses_exact_fixture_tool_contract() -> None:
    registry = build_postgres_agent_tool_registry(
        cast(async_sessionmaker[AsyncSession], object()),
        brand_embeddings=cast(BrandEmbeddingModel, object()),
        brand_retrieval_version="brand-hybrid-rrf-v3-parent-diverse",
    )

    assert registry.canonical_schema() == build_fixture_tool_registry().canonical_schema()


class _DisposableEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class _DisposableClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_real_data_mcp_lifespan_releases_owned_resources() -> None:
    engine = _DisposableEngine()
    client = _DisposableClient()
    server = build_real_data_mcp_server(
        build_fixture_tool_registry(),
        engine=cast(AsyncEngine, engine),
        embedding_client=cast(httpx.AsyncClient, client),
    )
    lifespan = server.settings.lifespan
    assert lifespan is not None

    async with lifespan(server):
        assert engine.disposed is False
        assert client.closed is False

    assert engine.disposed is True
    assert client.closed is True
