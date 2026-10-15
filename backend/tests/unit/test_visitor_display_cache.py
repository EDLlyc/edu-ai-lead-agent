from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from app.infrastructure.db import visitor_display as repository_module
from app.infrastructure.db.visitor_display import PostgresVisitorDisplayRepository


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_error: object) -> bool:
        return False


class _Factory:
    """A session factory stand-in: no database, only something to key the cache on."""

    def __call__(self) -> _Session:
        return _Session()


class _Reads:
    """Counts reads and lets a test decide how long each one takes."""

    def __init__(self) -> None:
        self.count = 0
        self.gate: asyncio.Event | None = None
        self.fail = False

    async def load(self, _session: Any, **_kwargs: Any) -> tuple[str, ...]:
        self.count += 1
        number = self.count
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError("SELECT secret FROM private")
        return (f"read-{number}",)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [1000.0]
    # Replace the module's view of the clock only: patching time.monotonic itself would also
    # freeze the event loop.
    monkeypatch.setattr(repository_module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> _Reads:
    reads = _Reads()
    monkeypatch.setattr(repository_module, "load_news_pool", reads.load)
    monkeypatch.setattr(repository_module, "load_report_days", reads.load)
    return reads


async def test_fresh_result_is_reused_without_a_read(clock: list[float], reads: _Reads) -> None:
    repository = PostgresVisitorDisplayRepository(_Factory())  # type: ignore[arg-type]

    assert await repository.load_news_pool() == ("read-1",)
    clock[0] += 59
    assert await repository.load_news_pool() == ("read-1",)
    assert reads.count == 1


async def test_expired_result_is_served_while_one_refresh_runs(
    clock: list[float], reads: _Reads
) -> None:
    repository = PostgresVisitorDisplayRepository(_Factory())  # type: ignore[arg-type]
    await repository.load_news_pool()
    clock[0] += 61
    reads.gate = asyncio.Event()

    # The slow production read must not hold up the screens that are polling.
    assert await asyncio.wait_for(repository.load_news_pool(), 0.5) == ("read-1",)
    assert await asyncio.wait_for(repository.load_news_pool(), 0.5) == ("read-1",)
    await asyncio.sleep(0)
    assert reads.count == 2

    reads.gate.set()
    await asyncio.sleep(0.01)
    assert await repository.load_news_pool() == ("read-2",)
    assert reads.count == 2


async def test_failed_refresh_keeps_the_last_result_and_logs_no_detail(
    clock: list[float], reads: _Reads, caplog: pytest.LogCaptureFixture
) -> None:
    repository = PostgresVisitorDisplayRepository(_Factory())  # type: ignore[arg-type]
    await repository.load_news_pool()
    clock[0] += 61
    reads.fail = True

    assert await repository.load_news_pool() == ("read-1",)
    await asyncio.sleep(0.01)

    assert "visitor cache refresh failed: news_pool RuntimeError" in caplog.text
    assert "SELECT" not in caplog.text
    # The next request may try again; the failure is not remembered as a result.
    reads.fail = False
    assert await repository.load_news_pool() == ("read-1",)
    await asyncio.sleep(0.01)
    assert await repository.load_news_pool() == ("read-3",)


async def test_result_too_old_or_from_another_day_is_read_again(
    clock: list[float], reads: _Reads
) -> None:
    repository = PostgresVisitorDisplayRepository(_Factory())  # type: ignore[arg-type]
    await repository.load_report(today=date(2026, 9, 29))

    # A new Beijing day never shows yesterday's numbers as today's.
    assert await repository.load_report(today=date(2026, 9, 30)) == ("read-2",)

    clock[0] += 601
    assert await repository.load_report(today=date(2026, 9, 30)) == ("read-3",)


async def test_first_read_failure_reaches_the_caller(clock: list[float], reads: _Reads) -> None:
    reads.fail = True
    repository = PostgresVisitorDisplayRepository(_Factory())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError):
        await repository.load_news_pool()
