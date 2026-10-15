# ruff: noqa: RUF001
from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.infrastructure.db.visitor_display import (
    _POLICY_DOCUMENT_REGEX,
    _POLICY_EXCLUDED_REGEX,
    _POLICY_ISSUER_REGEX,
    _POLICY_SUBJECT_REGEX,
    load_news_pool,
)
from sqlalchemy import literal, select

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_news_pool_policy_query_runs_on_postgres_and_regex_matches_headlines(
    integration_context: IntegrationContext,
) -> None:
    run = SimpleNamespace(
        id=uuid4(),
        business_date=date(2026, 10, 12),
        content_slot="morning",
        target_at=datetime(2026, 10, 12, 6, 0, tzinfo=UTC),
        total_scores=0,
        eligible_scores=0,
        selected_count=0,
        unfilled_reason_codes=[],
    )

    async with integration_context.session_factory() as session:
        real_scalars = session.scalars

        async def fake_scalars(*_args: object, **_kwargs: object) -> list[SimpleNamespace]:
            return [run]

        session.scalars = fake_scalars  # type: ignore[method-assign,assignment]
        try:
            # The full score query (policy sub-select, window, row-value IN) must plan and run.
            [batch] = await load_news_pool(session)
        finally:
            session.scalars = real_scalars  # type: ignore[method-assign]
        assert batch.candidates == ()

        async def qualifies(title: str) -> bool:
            value = literal(title)
            result = await session.scalar(
                select(
                    value.op("~")(_POLICY_ISSUER_REGEX)
                    & value.op("~")(_POLICY_DOCUMENT_REGEX)
                    & value.op("~")(_POLICY_SUBJECT_REGEX)
                    & ~value.op("~")(_POLICY_EXCLUDED_REGEX)
                )
            )
            return bool(result)

        assert await qualifies("中共中央 国务院关于发展新质生产力的意见")
        assert await qualifies("国务院关于深入实施“人工智能+”行动的意见")
        assert not await qualifies("国务院常务会议研究推进新质生产力发展，听取意见")
        assert not await qualifies("李强考察科技企业并座谈")
        assert not await qualifies("某省关于发展新质生产力的实施意见")
        assert not await qualifies("国务院关于水利建设投资的意见")
