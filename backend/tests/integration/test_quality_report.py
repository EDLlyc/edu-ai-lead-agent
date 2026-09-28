from __future__ import annotations

from datetime import date

import pytest
from app.application.services.quality_report import assess, render_markdown
from app.infrastructure.db.quality_report import load_quality_snapshot
from sqlalchemy import text
from tests.integration.conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_every_report_query_runs_read_only_against_the_migrated_schema(
    integration_context: IntegrationContext,
) -> None:
    async with integration_context.session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        snapshot = await load_quality_snapshot(
            session,
            business_date=date(1999, 1, 1),
            timezone="Asia/Shanghai",
            lookback_days=7,
        )
        await session.rollback()

    assert snapshot.slot_runs == []
    assert snapshot.copy_status == {}
    assert snapshot.brand_usage == []
    assert snapshot.copy_model_usage.calls == 0
    findings = assess(snapshot)
    assert [finding.code for finding in findings] == ["no_slot_runs"]
    assert "线上质量日报 1999-01-01" in render_markdown(snapshot, findings)
