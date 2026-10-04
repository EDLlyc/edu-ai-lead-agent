"""The weekly summary's SQL runs on the migrated schema, read-only."""

from __future__ import annotations

from datetime import date

import pytest
from app.infrastructure.db.weekly_report import load_week
from sqlalchemy import text

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_weekly_queries_run_read_only_on_the_schema(
    integration_context: IntegrationContext,
) -> None:
    async with integration_context.session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        stats = await load_week(
            session, start=date(2097, 1, 1), end=date(2097, 1, 7), timezone="Asia/Shanghai"
        )
        await session.rollback()

    assert (stats.posts_selected, stats.posts_delivered, stats.missed) == (0, 0, 0)
    assert stats.repair is not None and stats.repair.repaired_runs == 0
    assert (stats.action_refs, stats.copy_prompt_tokens) == (0, 0)
