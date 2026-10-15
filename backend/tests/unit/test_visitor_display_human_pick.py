# ruff: noqa: RUF001
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from app.api.v1.routes.visitor_display import router
from app.api.v1.routes.visitor_display_human_pick import PRODUCTION_HUMAN_PICK_PATH
from app.api.v1.routes.visitor_display_human_pick import router as human_pick_router
from app.api.v1.routes.visitor_display_review import OperatorGate
from app.application.services.visitor_display import news_key, project_human_pick
from app.core.errors import AppError
from app.infrastructure.db.visitor_display import (
    PostgresVisitorDisplayRepository,
    VisitorHumanPickRow,
    VisitorNewsPoolBatch,
    VisitorNewsPoolCandidate,
)
from app.infrastructure.db.visitor_report import VisitorReportDay, report_window
from app.visitor_display_main import load_settings
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import SecretStr

NOW = datetime(2026, 9, 28, 2, 0, tzinfo=UTC)
SECRET = "visitor-display-test-secret-that-is-32-bytes-long"
PIN = "246810"


def _candidate() -> VisitorNewsPoolCandidate:
    return VisitorNewsPoolCandidate(
        event_id=uuid4(),
        title="高校分类改革新闻",
        source_name="教育部",
        source_url="https://www.moe.gov.cn/news/2.html",
        trust_tier="A",
        published_at=NOW,
        snippet="教育部发布高校分类改革意见。",
        total=0.41,
        threshold=0.59,
        passes_threshold=False,
        eligible=True,
        veto_codes=(),
        same_day_excluded=False,
        same_day_exclusion_reason=None,
        rank=5,
        selected_ordinal=None,
        normalized_features={"science_education_relevance": 0.9},
        weights={"science_education_relevance": 0.3},
        penalty_weights={},
    )


def _batch(candidate: VisitorNewsPoolCandidate) -> VisitorNewsPoolBatch:
    return VisitorNewsPoolBatch(
        business_date=date(2026, 9, 28),
        content_slot="morning",
        target_at=NOW,
        total_scores=1,
        eligible_scores=1,
        selected_count=0,
        unfilled_reason_codes=("below_threshold",),
        candidates=(candidate,),
    )


def _row(**changes: object) -> VisitorHumanPickRow:
    base = VisitorHumanPickRow(event_id=uuid4(), picked_at=NOW, expires_at=NOW + timedelta(hours=3))
    return replace(base, **changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "stage", "failure", "long_image"),
    [
        ({}, "queued", None, None),
        ({"copy_status": "running"}, "writing", None, None),
        (
            {"copy_status": "review_required", "copy_error": "missing_eligible_evidence"},
            "failed",
            "missing_eligible_evidence",
            None,
        ),
        ({"copy_status": "accepted"}, "imaging", None, None),
        ({"copy_status": "accepted", "package_status": "queued"}, "imaging", None, None),
        ({"copy_status": "accepted", "package_status": "failed"}, "failed", "package_failed", None),
        # Ready packages are held until the operator pushes (approves) them.
        (
            {"copy_status": "accepted", "package_status": "awaiting_manual_use"},
            "awaiting_review",
            None,
            None,
        ),
        (
            {
                "copy_status": "accepted",
                "package_status": "completed",
                "package_review_status": "approved",
            },
            "sending",
            None,
            None,
        ),
        (
            {
                "copy_status": "accepted",
                "package_status": "completed",
                "delivery_status": "delivered",
                "infographic_status": "ready",
            },
            "delivered",
            None,
            "making",
        ),
        (
            {
                "copy_status": "accepted",
                "package_status": "completed",
                "delivery_status": "delivered",
                "infographic_status": "ready",
                "supplement_status": "delivered",
            },
            "delivered",
            None,
            "sent",
        ),
        (
            {"delivery_status": "delivery_unknown", "delivery_error": "Provider Timeout!"},
            "unknown",
            "unknown_error",
            None,
        ),
        ({"delivery_status": "delivery_window_expired"}, "expired", None, None),
        ({"infographic_status": "skipped"}, "queued", None, None),
    ],
)
def test_human_pick_progress_collapses_pipeline_stages(
    changes: dict[str, object], stage: str, failure: str | None, long_image: str | None
) -> None:
    projected = project_human_pick(_row(**changes), now=NOW + timedelta(minutes=5))
    assert (projected.stage, projected.failure_code, projected.long_image) == (
        stage,
        failure,
        long_image,
    )


def test_older_production_sends_ready_picks_itself() -> None:
    ready = _row(copy_status="accepted", package_status="awaiting_manual_use")
    assert project_human_pick(ready, now=NOW, held=False).stage == "sending"
    assert project_human_pick(ready, now=NOW, held=True).stage == "awaiting_review"


def test_unfinished_human_pick_becomes_expired_after_its_window() -> None:
    row = _row(copy_status="running")
    assert project_human_pick(row, now=row.expires_at).stage == "expired"
    held = _row(copy_status="accepted", package_status="awaiting_manual_use")
    assert project_human_pick(held, now=held.expires_at).stage == "expired"
    delivered = _row(delivery_status="delivered")
    assert project_human_pick(delivered, now=delivered.expires_at).stage == "delivered"


def _app(upstream: httpx.MockTransport) -> FastAPI:
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    application.include_router(human_pick_router, prefix="/api/v1")
    application.state.settings = SimpleNamespace(
        visitor_display_enabled=True, visitor_display_asset_secret=SecretStr(SECRET)
    )
    application.state.session_factory = object()
    application.state.operator_gate = OperatorGate(PIN)
    application.state.human_pick_client = httpx.AsyncClient(
        transport=upstream, base_url="http://127.0.0.1:18000"
    )

    @application.exception_handler(AppError)
    async def app_error(_request: Request, error: AppError) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content={})

    return application


@pytest.mark.asyncio
async def test_human_pick_route_forwards_resolved_source_and_maps_refusals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejected = _candidate()
    run_id = uuid4()
    batch = replace(_batch(rejected), run_id=run_id)
    monkeypatch.setattr(PostgresVisitorDisplayRepository, "load_latest", AsyncMock(return_value=()))
    monkeypatch.setattr(
        PostgresVisitorDisplayRepository, "load_moments", AsyncMock(return_value=())
    )
    monkeypatch.setattr(
        PostgresVisitorDisplayRepository, "load_issue_signals", AsyncMock(return_value=())
    )
    monkeypatch.setattr(
        PostgresVisitorDisplayRepository,
        "load_report",
        AsyncMock(return_value=tuple(VisitorReportDay(day=d) for d in report_window(date.today()))),
    )
    monkeypatch.setattr(
        PostgresVisitorDisplayRepository, "load_news_pool", AsyncMock(return_value=(batch,))
    )
    picks = AsyncMock(
        return_value=(
            _row(
                event_id=rejected.event_id,
                copy_status="running",
                expires_at=datetime.now(UTC) + timedelta(hours=3),
            ),
        )
    )
    monkeypatch.setattr(PostgresVisitorDisplayRepository, "load_human_picks", picks)
    seen: list[dict[str, object]] = []
    replies = iter(
        [
            httpx.Response(201, json={"target_at": NOW.isoformat()}),
            httpx.Response(409, json={"error": {"code": "human_pick_already_delivered"}}),
            httpx.Response(409, json={"error": {"code": "conflict", "message": "secret sql"}}),
        ]
    )

    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.url.path == PRODUCTION_HUMAN_PICK_PATH
        seen.append(json.loads(request.content))
        return next(replies)

    application = _app(httpx.MockTransport(upstream))
    key = news_key(rejected.event_id)
    body = {"key": key, "note": "运营推荐"}
    # The real adapter's outer boundary turns unexpected errors into a safe 503.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        missing_pin = await client.post("/api/v1/visitor-display/human-picks", json=body)
        unknown = await client.post(
            "/api/v1/visitor-display/human-picks",
            json={**body, "key": "vn1_" + "0" * 24},
            headers={"X-Operator-Pin": PIN},
        )
        created = await client.post(
            "/api/v1/visitor-display/human-picks", json=body, headers={"X-Operator-Pin": PIN}
        )
        refused = await client.post(
            "/api/v1/visitor-display/human-picks", json=body, headers={"X-Operator-Pin": PIN}
        )
        opaque = await client.post(
            "/api/v1/visitor-display/human-picks", json=body, headers={"X-Operator-Pin": PIN}
        )
        snapshot = await client.get("/api/v1/visitor-display/snapshot")

    assert missing_pin.status_code == 403
    assert unknown.status_code == 404
    assert created.status_code == 200
    assert created.json()["stage"] == "queued"
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "human_pick_already_delivered"
    # Unknown upstream errors never leak their message; the adapter boundary maps them to 503.
    assert opaque.status_code != 200
    assert "secret" not in opaque.text
    assert seen[0] == {
        "source_run_id": str(run_id),
        "event_id": str(rejected.event_id),
        "note": "运营推荐",
    }
    pool = snapshot.json()["news_pool"]
    assert pool["human_pick_enabled"] is True
    assert pool["batches"][0]["candidates"][0]["human_pick"]["stage"] == "writing"
    assert "run_id" not in snapshot.text
    assert str(run_id) not in snapshot.text


def test_adapter_human_pick_needs_pin_and_loopback_production_api(tmp_path: Path) -> None:
    review = {
        "VISITOR_DISPLAY_ENABLED": "false",
        "VISITOR_DISPLAY_REVIEW_DB": str(tmp_path / "news.sqlite3"),
        "VISITOR_DISPLAY_OPERATOR_PIN": PIN,
    }
    assert load_settings(review).visitor_human_pick_enabled is False
    enabled = load_settings(
        {**review, "VISITOR_DISPLAY_PRODUCTION_API_URL": "http://127.0.0.1:18000"}
    )
    assert enabled.visitor_human_pick_enabled is True
    for bad in (
        {"VISITOR_DISPLAY_PRODUCTION_API_URL": "http://127.0.0.1:18000"},  # no PIN/review store
        {**review, "VISITOR_DISPLAY_PRODUCTION_API_URL": "https://127.0.0.1:18000"},
        {**review, "VISITOR_DISPLAY_PRODUCTION_API_URL": "http://10.0.0.5:8000"},
        {**review, "VISITOR_DISPLAY_PRODUCTION_API_URL": "http://127.0.0.1:18000/api"},
        {**review, "VISITOR_DISPLAY_PRODUCTION_API_URL": "http://u:p@127.0.0.1:18000"},
    ):
        with pytest.raises(ValueError):
            load_settings({"VISITOR_DISPLAY_ENABLED": "false", **bad})


HELD_COPY = (
    "🔎【小赛洞察】\n世界技能大赛标准引领职教课堂\n「技能人才培养提质进行时」\n"
    "当职业教育的标准走进课堂，正好和孩子聊聊学东西到底该追求什么✨\n"
    "新闻来源：光明网教育\n原文链接：https://edu.gmw.cn/a.htm\n#赛先生科学 #科学思维"
)
