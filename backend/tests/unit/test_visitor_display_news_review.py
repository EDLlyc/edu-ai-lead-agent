from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
from app.api.v1.routes.visitor_display import router
from app.api.v1.routes.visitor_display_review import OperatorGate
from app.api.v1.routes.visitor_display_review import router as review_router
from app.application.services.visitor_display import (
    VisitorDisplayService,
    news_key,
    project_news_pool,
)
from app.core.errors import AppError
from app.infrastructure.db.visitor_display import (
    NEWS_POOL_BATCH_LIMIT,
    NEWS_POOL_CANDIDATE_LIMIT,
    NEWS_POOL_POLICY_EXTRA_LIMIT,
    PostgresVisitorDisplayRepository,
    VisitorNewsPoolBatch,
    VisitorNewsPoolCandidate,
    load_news_pool,
)
from app.infrastructure.db.visitor_report import VisitorReportDay, report_window
from app.infrastructure.visitor_review_store import NewsReviewSubject, VisitorReviewStore
from app.schemas.visitor_display import VisitorDisplayNewsBatch
from app.visitor_display_main import load_settings
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import SecretStr
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException

SECRET = "visitor-display-test-secret-that-is-32-bytes-long"
PIN = "246810"
NOW = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)


def _candidate(**changes: object) -> VisitorNewsPoolCandidate:
    base = VisitorNewsPoolCandidate(
        event_id=uuid4(),
        title="  教育部部署  人工智能通识教育  ",
        source_name="教育部",
        source_url="https://www.moe.gov.cn/news/1.html",
        trust_tier="A",
        published_at=NOW,
        snippet="  教育部近日印发通知\n 要求中小学开展人工智能通识教育。",
        total=0.71,
        threshold=0.59,
        passes_threshold=True,
        eligible=True,
        veto_codes=(),
        same_day_excluded=False,
        same_day_exclusion_reason=None,
        rank=1,
        selected_ordinal=1,
        normalized_features={
            "science_education_relevance": 0.9,
            "source_trust": 1.0,
            "freshness": 1.7,
            "marketing_risk": 0.1,
            "private_signal": 0.5,
        },
        weights={"science_education_relevance": 0.3, "source_trust": 0.15, "freshness": 0.1},
        penalty_weights={"marketing_risk": 0.15},
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def _batch(*candidates: VisitorNewsPoolCandidate, slot: str = "morning") -> VisitorNewsPoolBatch:
    return VisitorNewsPoolBatch(
        business_date=date(2026, 9, 28),
        content_slot=slot,
        target_at=NOW,
        total_scores=len(candidates),
        eligible_scores=len(candidates),
        selected_count=1,
        unfilled_reason_codes=("below_threshold", "private_code"),
        candidates=candidates,
    )


class _Repository:
    def __init__(self, batches: tuple[VisitorNewsPoolBatch, ...]) -> None:
        self.batches = batches

    async def load_latest(self) -> tuple[()]:
        return ()

    async def load_news_pool(self) -> tuple[VisitorNewsPoolBatch, ...]:
        return self.batches

    async def load_moments(self) -> tuple[()]:
        return ()

    async def load_issue_signals(self, *, today: date) -> tuple[()]:
        return ()

    async def load_report(self, *, today: date) -> tuple[VisitorReportDay, ...]:
        return tuple(VisitorReportDay(day=day) for day in report_window(today))


def test_news_pool_projects_selected_and_rejected_with_plain_reasons() -> None:
    selected = _candidate()
    vetoed = _candidate(
        selected_ordinal=None,
        rank=2,
        veto_codes=("outside_science_ai_education_scope", "private_new_rule"),
        passes_threshold=False,
        eligible=False,
    )
    same_day = _candidate(selected_ordinal=None, rank=3, same_day_excluded=True)
    ranked_out = _candidate(selected_ordinal=None, rank=4)
    not_eligible = _candidate(selected_ordinal=None, rank=5, eligible=False)

    [batch] = project_news_pool([_batch(selected, vetoed, same_day, ranked_out, not_eligible)])

    assert [item.verdict for item in batch.candidates] == ["selected"] + ["rejected"] * 4
    assert batch.selected_count == 1
    assert batch.unfilled_reasons == ["below_threshold"]
    first = batch.candidates[0]
    assert first.title == "教育部部署 人工智能通识教育"
    assert first.snippet == "教育部近日印发通知 要求中小学开展人工智能通识教育。"
    assert first.tier_label == "权威来源"
    assert first.reasons == []
    assert first.key == news_key(selected.event_id)
    assert {(item.key, item.kind, item.value) for item in first.dimensions} == {
        ("science_education_relevance", "positive", 0.9),
        ("source_trust", "positive", 1.0),
        ("freshness", "positive", 1.0),
        ("marketing_risk", "penalty", 0.1),
    }
    assert batch.candidates[1].reasons == [
        "outside_science_ai_education_scope",
        "other_rule",
        "below_threshold",
    ]
    assert batch.candidates[2].reasons == ["same_day_already_selected"]
    assert batch.candidates[3].reasons == ["ranked_out"]
    assert batch.candidates[4].reasons == ["not_eligible"]


def test_news_pool_never_exposes_internal_identity_or_unsafe_links() -> None:
    row = _candidate(source_url="http://example.com/a", selected_ordinal=None)
    [batch] = project_news_pool([_batch(row), _batch(row, slot="midnight")][:1])
    projected = batch.candidates[0]

    assert projected.source_url is None
    text = batch.model_dump_json()
    assert str(row.event_id) not in text
    assert "private_signal" not in text
    assert "private_code" not in text
    assert project_news_pool([_batch(row, slot="midnight")]) == []


def test_news_key_is_stable_opaque_and_distinct() -> None:
    event_id = UUID("11111111-2222-3333-4444-555555555555")
    assert news_key(event_id) == news_key(event_id)
    assert news_key(event_id) != news_key(uuid4())
    assert news_key(event_id).startswith("vn1_")
    assert len(news_key(event_id)) == 28
    assert str(event_id) not in news_key(event_id)


def test_news_batch_schema_admits_the_rank_cut_plus_policy_extras() -> None:
    field = VisitorDisplayNewsBatch.model_fields["candidates"]
    limit = next(item.max_length for item in field.metadata if hasattr(item, "max_length"))

    assert limit == NEWS_POOL_CANDIDATE_LIMIT + NEWS_POOL_POLICY_EXTRA_LIMIT


@pytest.mark.asyncio
async def test_news_pool_reader_is_bounded_select_only_and_keeps_latest_run_per_slot() -> None:
    session = AsyncMock(spec=AsyncSession)
    newest = SimpleNamespace(
        id=uuid4(),
        business_date=date(2026, 9, 28),
        content_slot="morning",
        target_at=NOW,
        total_scores=2,
        eligible_scores=1,
        selected_count=1,
        unfilled_reason_codes=[],
    )
    older_same_slot = SimpleNamespace(**{**vars(newest), "id": uuid4()})
    session.scalars.return_value = [newest, older_same_slot]
    result = MagicMock()
    result.mappings.return_value = [
        {
            "run_id": newest.id,
            "event_id": uuid4(),
            "total": 0.7,
            "threshold": 0.59,
            "passes_threshold": True,
            "eligible": True,
            "veto_codes": ["stale_event", 3],
            "same_day_excluded": False,
            "same_day_exclusion_reason": None,
            "rank": 1,
            "selected_ordinal": None,
            "normalized_features": {"freshness": 0.4},
            "weights": {"freshness": 0.1},
            "penalty_weights": None,
            "representative_title": "新闻标题",
            "canonical_url": "https://example.gov.cn/a",
            "trust_tier": "A",
            "published_at": NOW,
            "clean_text": "  正文\n第二行" + "字" * 400,
            "display_name": "来源",
        }
    ]
    session.execute.return_value = result

    batches = await load_news_pool(session)

    assert len(batches) == 1
    assert batches[0].candidates[0].veto_codes == ("stale_event",)
    assert batches[0].candidates[0].penalty_weights == {}
    runs_sql = str(
        session.scalars.call_args.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    scores_sql = str(
        session.execute.call_args.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert runs_sql.startswith("SELECT") and "status = 'succeeded'" in runs_sql
    assert "content_slot_runs.trigger IN ('scheduled', 'manual')" in runs_sql
    assert scores_sql.startswith("SELECT")
    assert f"rank <= {NEWS_POOL_CANDIDATE_LIMIT}" in scores_sql
    limit = NEWS_POOL_BATCH_LIMIT * (NEWS_POOL_CANDIDATE_LIMIT + NEWS_POOL_POLICY_EXTRA_LIMIT)
    assert f"LIMIT {limit}" in scores_sql
    # Past the cut-off only central policy documents come back, a bounded number per batch.
    assert f"content_slot_scores.rank > {NEWS_POOL_CANDIDATE_LIMIT}" in scores_sql
    assert f"extra_rank <= {NEWS_POOL_POLICY_EXTRA_LIMIT}" in scores_sql
    assert "PARTITION BY content_slot_scores.run_id" in scores_sql
    assert "representative_title ~ '中共中央|党中央|国务院" in scores_sql
    assert "NOT (event_cluster_versions.representative_title ~ '会议|" in scores_sql
    # Whole values only: server-side truncation splits CJK characters in production.
    assert "left(" not in scores_sql and "convert_to" not in scores_sql
    snippet = batches[0].candidates[0].snippet
    assert snippet is not None and snippet.startswith("正文 第二行") and len(snippet) == 160
    assert str(older_same_slot.id) not in scores_sql


@pytest.mark.asyncio
async def test_unreadable_news_pool_keeps_articles_and_is_absent() -> None:
    repository = _Repository(())
    repository.load_news_pool = AsyncMock(  # type: ignore[method-assign]
        side_effect=OperationalError("SELECT", {}, Exception("down"))
    )
    snapshot = await VisitorDisplayService(
        repository=repository,  # type: ignore[arg-type]
        asset_secret=SECRET,
    ).snapshot(now=NOW)

    assert snapshot.state == "empty"
    assert snapshot.news_pool is None


@pytest.mark.asyncio
async def test_review_store_keeps_history_and_returns_latest(tmp_path: Path) -> None:
    store = VisitorReviewStore(tmp_path / "reviews" / "news.sqlite3")
    store.initialize()
    subject = NewsReviewSubject(
        title="新闻",
        source_name=None,
        ai_verdict="rejected",
        business_date=date(2026, 9, 28),
        slot="noon",
    )
    await store.record(key="vn1_" + "a" * 24, decision="include", note="值得写", subject=subject)
    await store.record(key="vn1_" + "a" * 24, decision="agree", note=None, subject=subject)

    latest = await store.latest(["vn1_" + "a" * 24, "vn1_" + "b" * 24])

    assert set(latest) == {"vn1_" + "a" * 24}
    assert latest["vn1_" + "a" * 24].decision == "agree"
    assert latest["vn1_" + "a" * 24].note is None
    with sqlite3.connect(tmp_path / "reviews" / "news.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM news_reviews").fetchone() == (2,)
    assert oct((tmp_path / "reviews" / "news.sqlite3").stat().st_mode & 0o777) == "0o600"


def test_operator_gate_locks_after_repeated_failures() -> None:
    clock = [0.0]
    gate = OperatorGate(PIN, max_failures=3, lockout_seconds=60, clock=lambda: clock[0])
    gate.verify(PIN)
    for _ in range(3):
        with pytest.raises(HTTPException) as denied:
            gate.verify("000000")
        assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as locked:
        gate.verify(PIN)
    assert locked.value.status_code == 429
    clock[0] = 61.0
    gate.verify(PIN)
    with pytest.raises(ValueError):
        OperatorGate("12")


def _review_app(tmp_path: Path, batches: tuple[VisitorNewsPoolBatch, ...]) -> FastAPI:
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    application.include_router(review_router, prefix="/api/v1")
    application.state.settings = SimpleNamespace(
        visitor_display_enabled=True, visitor_display_asset_secret=SecretStr(SECRET)
    )
    application.state.session_factory = object()
    store = VisitorReviewStore(tmp_path / "news.sqlite3")
    store.initialize()
    application.state.review_store = store
    application.state.operator_gate = OperatorGate(PIN)

    @application.exception_handler(AppError)
    async def app_error(_request: Request, error: AppError) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content={})

    return application


@pytest.mark.asyncio
async def test_review_routes_require_pin_and_only_record_locally(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rejected = _candidate(selected_ordinal=None, passes_threshold=False)
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
        PostgresVisitorDisplayRepository,
        "load_news_pool",
        AsyncMock(return_value=(_batch(rejected),)),
    )
    key = news_key(rejected.event_id)
    application = _review_app(tmp_path, ())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        wrong_session = await client.post(
            "/api/v1/visitor-display/operator/session", json={"pin": "999999"}
        )
        session = await client.post("/api/v1/visitor-display/operator/session", json={"pin": PIN})
        body = {"key": key, "decision": "include", "note": "适合家长科普"}
        missing_pin = await client.post("/api/v1/visitor-display/news-reviews", json=body)
        unknown = await client.post(
            "/api/v1/visitor-display/news-reviews",
            json={**body, "key": "vn1_" + "0" * 24},
            headers={"X-Operator-Pin": PIN},
        )
        invalid = await client.post(
            "/api/v1/visitor-display/news-reviews",
            json={**body, "decision": "publish"},
            headers={"X-Operator-Pin": PIN},
        )
        recorded = await client.post(
            "/api/v1/visitor-display/news-reviews", json=body, headers={"X-Operator-Pin": PIN}
        )
        snapshot = await client.get("/api/v1/visitor-display/snapshot")

    assert wrong_session.status_code == 403
    assert session.status_code == 204
    assert missing_pin.status_code == 403
    assert unknown.status_code == 404
    assert invalid.status_code == 422
    assert recorded.status_code == 200
    assert recorded.json()["decision"] == "include"
    pool = snapshot.json()["news_pool"]
    assert pool["review_enabled"] is True
    candidate = pool["batches"][0]["candidates"][0]
    assert candidate["verdict"] == "rejected"
    assert candidate["human_review"]["decision"] == "include"
    assert candidate["human_review"]["note"] == "适合家长科普"
    with sqlite3.connect(tmp_path / "news.sqlite3") as connection:
        assert connection.execute(
            "SELECT news_key, decision, title, ai_verdict, slot FROM news_reviews"
        ).fetchall() == [(key, "include", "教育部部署 人工智能通识教育", "rejected", "morning")]


@pytest.mark.asyncio
async def test_review_store_records_candidate_context_and_upgrades_old_files(
    tmp_path: Path,
) -> None:
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        # A file created before the context columns existed, with one review in it.
        connection.executescript(
            "CREATE TABLE news_reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "news_key TEXT NOT NULL, decision TEXT NOT NULL, note TEXT, title TEXT NOT NULL, "
            "source_name TEXT, ai_verdict TEXT NOT NULL, business_date TEXT NOT NULL, "
            "slot TEXT NOT NULL, reviewed_at TEXT NOT NULL);"
            "INSERT INTO news_reviews (news_key, decision, title, ai_verdict, business_date, "
            "slot, reviewed_at) VALUES ('vn1_old', 'agree', '旧记录', 'selected', '2026-09-28', "
            "'morning', '2026-09-28T01:00:00+00:00');"
        )
    store = VisitorReviewStore(path)
    store.initialize()
    store.initialize()  # idempotent
    await store.record(
        key="vn1_" + "c" * 24,
        decision="include",
        note="家长关心",
        subject=NewsReviewSubject(
            title="高校分类改革",
            source_name="教育部",
            ai_verdict="rejected",
            business_date=date(2026, 9, 29),
            slot="noon",
            source_url="https://www.moe.gov.cn/a.html",
            snippet="教育部发布意见。",
            tier_label="权威来源",
            ai_score=0.41,
            ai_threshold=0.59,
            ai_rank=5,
            ai_reasons=("below_threshold",),
        ),
        now=NOW,
    )
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT news_key, source_url, tier_label, ai_score, ai_rank, ai_reasons "
            "FROM news_reviews ORDER BY id"
        ).fetchall()
    assert rows == [
        ("vn1_old", None, None, None, None, None),
        (
            "vn1_" + "c" * 24,
            "https://www.moe.gov.cn/a.html",
            "权威来源",
            0.41,
            5,
            '["below_threshold"]',
        ),
    ]
    latest = await store.latest(["vn1_old", "vn1_" + "c" * 24])
    assert latest["vn1_" + "c" * 24].decision == "include"


def test_adapter_review_settings_are_all_or_nothing(tmp_path: Path) -> None:
    base = {"VISITOR_DISPLAY_ENABLED": "false"}
    assert load_settings(base).visitor_review_enabled is False
    enabled = load_settings(
        {
            **base,
            "VISITOR_DISPLAY_REVIEW_DB": str(tmp_path / "news.sqlite3"),
            "VISITOR_DISPLAY_OPERATOR_PIN": PIN,
        }
    )
    assert enabled.visitor_review_enabled is True
    for partial in (
        {"VISITOR_DISPLAY_REVIEW_DB": str(tmp_path / "news.sqlite3")},
        {"VISITOR_DISPLAY_OPERATOR_PIN": PIN},
        {"VISITOR_DISPLAY_REVIEW_DB": "relative.sqlite3", "VISITOR_DISPLAY_OPERATOR_PIN": PIN},
        {"VISITOR_DISPLAY_REVIEW_DB": str(tmp_path / "x"), "VISITOR_DISPLAY_OPERATOR_PIN": "12"},
    ):
        with pytest.raises(ValueError):
            load_settings({**base, **partial})
