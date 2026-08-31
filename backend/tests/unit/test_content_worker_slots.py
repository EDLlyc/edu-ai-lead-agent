from __future__ import annotations

import asyncio

import pytest
from app.content_worker_main import _brand_ingestion_provider_enabled, _worker_loop
from app.core.config import Settings
from pydantic import SecretStr


class _CopyRepository:
    def __init__(self) -> None:
        self.legacy_reconciliations = 0
        self.slot_reconciliations = 0

    async def reconcile_ready_topics(self, **_values: object) -> int:
        self.legacy_reconciliations += 1
        return 0

    async def reconcile_ready_slot_topics(self, **_values: object) -> int:
        self.slot_reconciliations += 1
        return 0


class _StopExecutor:
    def __init__(self, stop: asyncio.Event) -> None:
        self._stop = stop
        self.calls = 0

    async def execute_next(self, _worker_id: str) -> bool:
        self.calls += 1
        self._stop.set()
        return False


class _IdleExecutor:
    async def execute_next(self, _worker_id: str) -> bool:
        return False


def test_alibaba_brand_ingestion_does_not_require_governance_ai_provider() -> None:
    settings = Settings(
        _env_file=None,
        ai_provider_mode="disabled",
        content_enabled=True,
        content_worker_enabled=True,
        content_llm_rerank_enabled=False,
        brand_embedding_provider_mode="alibaba",
        visual_embedding_endpoint=SecretStr(
            "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/embeddings/"
            "multimodal-embedding/multimodal-embedding"
        ),
        visual_embedding_api_key=SecretStr("test-only-alibaba-key"),
    )

    assert _brand_ingestion_provider_enabled(settings) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("slot_mode", [False, True])
async def test_content_worker_reconciles_only_the_active_copy_origin(slot_mode: bool) -> None:
    stop = asyncio.Event()
    legacy_executor = _StopExecutor(stop)
    slot_executor = _StopExecutor(stop)
    copy_repository = _CopyRepository()
    settings = Settings(
        _env_file=None,
        content_enabled=True,
        content_llm_rerank_enabled=False,
        content_slot_mode_enabled=slot_mode,
    )

    await _worker_loop(
        worker_id="content-worker-test",
        stop=stop,
        executor=legacy_executor,  # type: ignore[arg-type]
        slot_executor=slot_executor,  # type: ignore[arg-type]
        brand_executor=None,
        copy_executor=_IdleExecutor(),  # type: ignore[arg-type]
        material_executor=None,
        copy_repository=copy_repository,  # type: ignore[arg-type]
        settings=settings,
        poll_seconds=0.01,
    )

    assert copy_repository.legacy_reconciliations == int(not slot_mode)
    assert copy_repository.slot_reconciliations == int(slot_mode)
    assert legacy_executor.calls == int(not slot_mode)
    assert slot_executor.calls == int(slot_mode)
