from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.api.v1.routes.content_slots import (
    _edition_slot_state,
    _safe_source_links,
    _selection_state,
)
from app.core.config import Settings


def test_content_edition_source_links_reject_authenticated_or_unsafe_urls() -> None:
    links = _safe_source_links(
        [
            {"source_url": "https://news.example.test/story?id=1"},
            {"source_url": "https://news.example.test:443/story?id=1"},
            {"source_url": "https://user:secret@news.example.test/private"},
            {"source_url": "http://news.example.test/insecure"},
            {"source_url": "https://127.0.0.1/internal"},
            {"source_url": "https://[invalid/source"},
        ]
    )

    assert [item.url for item in links] == ["https://news.example.test/story?id=1"]


def test_content_edition_selection_projects_expired_without_a_delivery_job() -> None:
    assert (
        _selection_state(
            copy_status=None,
            package_status=None,
            delivery_status=None,
            window_expired=True,
        )
        == "expired"
    )
    assert (
        _selection_state(
            copy_status="accepted",
            package_status="ready",
            delivery_status=None,
            window_expired=True,
        )
        == "expired"
    )
    assert (
        _selection_state(
            copy_status="accepted",
            package_status="completed",
            delivery_status="queued",
            window_expired=True,
        )
        == "expired"
    )


def test_content_edition_selection_preserves_terminal_and_started_delivery_states() -> None:
    assert (
        _selection_state(
            copy_status="accepted",
            package_status="completed",
            delivery_status="running",
            window_expired=True,
        )
        == "ready"
    )
    assert (
        _selection_state(
            copy_status="failed",
            package_status=None,
            delivery_status=None,
            window_expired=True,
        )
        == "failed"
    )
    assert (
        _selection_state(
            copy_status="accepted",
            package_status="completed",
            delivery_status="delivery_unknown",
            window_expired=True,
        )
        == "delivery_unknown"
    )


def test_content_edition_run_stops_projecting_preparing_after_its_window() -> None:
    now = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
    settings = Settings(
        _env_file=None,
        content_enabled=True,
        content_llm_rerank_enabled=False,
        content_slot_mode_enabled=True,
    )
    projection = SimpleNamespace(
        run=SimpleNamespace(status="queued", expires_at=now - timedelta(seconds=1))
    )

    assert (
        _edition_slot_state(
            settings=settings,
            enabled=True,
            projection=projection,  # type: ignore[arg-type]
            selection_states=(),
            expires_at=projection.run.expires_at,
            now=now,
        )
        == "expired"
    )
