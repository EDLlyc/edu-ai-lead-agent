"""The optional image backlog must not delay scheduled original messages."""

from __future__ import annotations

import asyncio

import pytest
from app.wecom_dispatcher_main import _worker_loop


@pytest.mark.asyncio
async def test_due_base_jobs_are_not_starved_by_ready_infographic_backlog() -> None:
    stop = asyncio.Event()
    order: list[str] = []

    class Base:
        async def reconcile_auto_deliveries(self) -> None:
            order.append("base_reconcile")

        async def execute_next(self, worker_id: str) -> bool:
            order.append("base")
            if order.count("base") == 3:
                stop.set()
            return True

    class Supplements:
        async def reconcile(self) -> None:
            order.append("supplement_reconcile")

        async def execute_next(self, worker_id: str) -> bool:
            order.append("supplement")
            return True  # An unlimited ready backlog exists.

    await _worker_loop(
        worker_id="synthetic-worker",
        stop=stop,
        executor=Base(),  # type: ignore[arg-type]
        supplements=Supplements(),  # type: ignore[arg-type]
        poll_seconds=0.01,
        reconcile_auto=True,
    )
    assert order.count("base") == 3
    assert order.count("supplement") == 3
    assert order.index("base") < order.index("supplement_reconcile")
    assert order.index("base") < order.index("supplement")
    assert order.index("base", order.index("supplement") + 1) < order.index(
        "supplement", order.index("supplement") + 1
    )


@pytest.mark.asyncio
async def test_supplement_failure_does_not_stop_sibling_base_dispatch() -> None:
    stop = asyncio.Event()
    base_count = 0

    class Base:
        async def reconcile_auto_deliveries(self) -> None:
            return None

        async def execute_next(self, worker_id: str) -> bool:
            nonlocal base_count
            base_count += 1
            if base_count == 3:
                stop.set()
            return True

    class BrokenSupplements:
        async def reconcile(self) -> None:
            raise RuntimeError("synthetic supplement-only fault")

        async def execute_next(self, worker_id: str) -> bool:
            raise RuntimeError("synthetic supplement-only fault")

    await _worker_loop(
        worker_id="synthetic-worker",
        stop=stop,
        executor=Base(),  # type: ignore[arg-type]
        supplements=BrokenSupplements(),  # type: ignore[arg-type]
        poll_seconds=0.01,
        reconcile_auto=True,
    )
    assert base_count == 3
