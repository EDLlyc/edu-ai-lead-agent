
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from app.application.services.ops_tools import DayTraceResult, PostTrace, StageSpan, UsageRow
from app.ops_trace_report_main import render_trace_html

START = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)


def _stage(stage: str, minutes: int, seconds: int, tokens: int = 0) -> StageSpan:
    return StageSpan(
        stage=stage,
        model="glm-5.2" if tokens else None,
        calls=1,
        failures=0,
        prompt_tokens=tokens,
        completion_tokens=tokens // 10,
        latency_ms=seconds * 1000,
        started_at=START + timedelta(minutes=minutes),
        ended_at=START + timedelta(minutes=minutes, seconds=seconds),
        status="succeeded",
    )


def _day() -> DayTraceResult:
    return DayTraceResult(
        business_date=date(2026, 9, 30),
        posts=(
            PostTrace(
                content_slot="evening",
                ordinal=1,
                title="<script>alert(1)</script>教育部新闻",
                copy_run_id=uuid4(),
                prepared_at=START,
                target_at=START + timedelta(minutes=30),
                delivered_at=START + timedelta(minutes=31),
                stages=(
                    _stage("generation", 1, 20, tokens=6000),
                    _stage("audit", 2, 8, tokens=2000),
                    _stage("delivery", 30, 3),
                ),
            ),
        ),
        usage=(
            UsageRow(
                stage="generation",
                model="glm-5.2",
                calls=1,
                failures=0,
                prompt_tokens=6000,
                completion_tokens=600,
                p50_latency_ms=20000,
                p95_latency_ms=20000,
            ),
        ),
    )


def test_trace_page_escapes_titles_and_draws_each_stage() -> None:
    page = render_trace_html([_day()], prices={}, generated_at=START)

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    assert page.count('class="lane"') == 3
    assert "未配置单价" in page
    assert "1/1" in page  # delivered / selected


def test_trace_page_prices_only_models_with_a_configured_price() -> None:
    page = render_trace_html(
        [_day()], prices={"glm-5.2": {"input": 4.0, "output": 16.0}}, generated_at=START
    )

    # 6000 * 4 / 1e6 + 600 * 16 / 1e6 = 0.0336
    assert "¥0.034" in page
