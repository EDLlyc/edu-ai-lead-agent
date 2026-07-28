import pytest
from app.api_main import app
from app.core.config import get_settings
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_healthz_reports_environment_shell() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "service": "edu-ai-lead-agent-api",
        "status": "ok",
        "environment": "development",
        "timezone": "Asia/Shanghai",
    }


def test_settings_redact_database_credentials() -> None:
    settings = get_settings()

    assert str(settings.database_url) == "**********"
