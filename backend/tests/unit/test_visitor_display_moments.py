# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional exhibit copy.
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from app.api.v1.routes.visitor_display import router
from app.application.services.visitor_moments import (
    image_signature_matches,
    moment_asset_ref,
    project_moments,
    resolve_moment_asset,
)
from app.core.errors import AppError, NotFoundError
from app.infrastructure.db.visitor_display import PostgresVisitorDisplayRepository
from app.infrastructure.db.visitor_moments import VisitorMomentImage, VisitorMomentRow
from app.schemas.visitor_display import VisitorDisplayMoment
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import SecretStr

SECRET = "visitor-display-test-secret-that-is-32-bytes-long"
SENT = datetime(2026, 9, 29, 0, 30, tzinfo=UTC)
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 60


def _image(kind: str = "generated", **changes: object) -> VisitorMomentImage:
    base = VisitorMomentImage(
        kind=kind,
        row_id=uuid4(),
        media_type="image/jpeg",
        byte_size=len(JPEG),
        sha256="a" * 64,
        width=1024,
        height=1024,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def _row(**changes: object) -> VisitorMomentRow:
    base = VisitorMomentRow(
        job_id=uuid4(),
        event_id=uuid4(),
        human_pick=False,
        topic={
            "content_slot": "morning",
            "ordinal": 1,
            "business_date": "2026-09-29",
            "title": "  教育部部署  人工智能通识教育 ",
            "score": {
                "total": 0.72,
                "threshold": 0.59,
                "explanation": {"education_policy_level": "national"},
            },
        },
        copy={"copywriting": "🔎 小赛洞察\n\n教育部近日部署……\n\n新闻来源：教育部"},
        sources=[
            {"source_url": "http://insecure.example/a"},
            {"source_url": "https://www.moe.gov.cn/a.html"},
        ],
        brand=[
            {"document_title": "7真 · 真动手"},
            {"document_title": "7真 · 真动手"},
            {"document_title": "品牌定位"},
        ],
        validation={"issues": [{"code": "unverified_superlative", "severity": "warning"}]},
        audit={
            "issues": [
                {"code": "something_new", "severity": "warning"},
                {"code": "unbound_external_fact", "severity": "error"},
            ]
        },
        copy_started_at=SENT,
        copy_finished_at=SENT,
        repair_count=1,
        delivery_status="delivered",
        text_sent_at=SENT,
        image_sent_at=SENT,
        delivered_at=SENT,
        image=_image(),
        long_image=_image("long", width=1152, height=2048),
        long_image_status="ready",
        long_image_sent_at=SENT,
        business_date=date(2026, 9, 29),
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def test_moment_projection_explains_each_step_without_internal_ids() -> None:
    row = _row()
    [moment] = project_moments([row], secret=SECRET)

    assert moment.title == "教育部部署 人工智能通识教育"
    assert moment.selection_reason == "国家教育政策风向，最高优先级"
    assert moment.source_url == "https://www.moe.gov.cn/a.html"
    assert moment.source_host == "www.moe.gov.cn"
    assert moment.brand_angles == ["7真 · 真动手", "品牌定位"]
    # Only warnings that were let through; unknown codes get a plain label.
    assert moment.checks == ["新闻里的最高级说法", "其他写作提示"]
    assert moment.copy_text.startswith("🔎 小赛洞察")
    assert (moment.delivery, moment.long_image_state) == ("delivered", "sent")
    assert moment.image is not None and moment.image.ref.startswith("vm1_")
    assert moment.long_image is not None and moment.long_image.height == 2048
    dumped = moment.model_dump_json()
    assert str(row.job_id) not in dumped and str(row.event_id) not in dumped
    assert "a" * 64 not in dumped
    VisitorDisplayMoment.model_validate(moment.model_dump())


def test_human_picks_and_broken_or_pending_rows() -> None:
    [picked] = project_moments([_row(human_pick=True)], secret=SECRET)
    assert picked.selection_reason == "运营在展厅人工审核后加推"

    pending = project_moments(
        [_row(long_image=None, long_image_status="running", long_image_sent_at=None)],
        secret=SECRET,
    )
    assert pending[0].long_image_state == "making"
    assert pending[0].long_image is None

    broken = _row(topic={"content_slot": "midnight", "title": "x"})
    empty_copy = _row(copy={"copywriting": "  "})
    assert project_moments([broken, empty_copy], secret=SECRET) == []


def test_moment_asset_refs_resolve_only_listed_images() -> None:
    row = _row()
    assert row.image is not None
    ref = moment_asset_ref(secret=SECRET, image=row.image)
    assert resolve_moment_asset(secret=SECRET, asset_ref=ref, rows=[row]) == row.image
    with pytest.raises(NotFoundError):
        resolve_moment_asset(
            secret="another-secret-that-is-at-least-32-bytes", asset_ref=ref, rows=[row]
        )
    with pytest.raises(NotFoundError):
        resolve_moment_asset(secret=SECRET, asset_ref=ref, rows=[_row()])
    svg = _row(image=_image(media_type="image/svg+xml"))
    assert svg.image is not None
    with pytest.raises(NotFoundError):
        resolve_moment_asset(
            secret=SECRET,
            asset_ref=moment_asset_ref(secret=SECRET, image=svg.image),
            rows=[svg],
        )
    assert image_signature_matches("image/jpeg", JPEG)
    assert not image_signature_matches("image/png", JPEG)
    assert image_signature_matches("image/webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ")


@asynccontextmanager
async def _no_session() -> AsyncIterator[None]:
    yield None


@pytest.mark.asyncio
async def test_asset_route_serves_verified_moment_image(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row()
    assert row.image is not None
    monkeypatch.setattr(
        PostgresVisitorDisplayRepository, "load_moments", AsyncMock(return_value=(row,))
    )
    store = SimpleNamespace(get_content_addressed_bytes=AsyncMock(return_value=JPEG))
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    application.state.settings = SimpleNamespace(
        visitor_display_enabled=True, visitor_display_asset_secret=SecretStr(SECRET)
    )
    # The route's DB session dependency is opened but never used for 朋友圈 images.
    application.state.session_factory = _no_session
    application.state.image_store = store

    @application.exception_handler(AppError)
    async def app_error(_request: Request, error: AppError) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content={})

    ref = moment_asset_ref(secret=SECRET, image=row.image)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        served = await client.get(f"/api/v1/visitor-display/assets/{ref}")
        unknown = await client.get("/api/v1/visitor-display/assets/vm1_" + "A" * 43)
        store.get_content_addressed_bytes.return_value = b"<svg>"
        tampered = await client.get(f"/api/v1/visitor-display/assets/{ref}")

    assert served.status_code == 200
    assert served.content == JPEG
    assert served.headers["content-type"] == "image/jpeg"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert unknown.status_code == 404
    assert tampered.status_code == 409
    store.get_content_addressed_bytes.assert_any_await(
        media_type="image/jpeg", byte_size=len(JPEG), sha256="a" * 64
    )
