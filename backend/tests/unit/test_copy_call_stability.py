"""Copy-call stability: shared evidence quotes (v28) and content-filter rejections."""

# ruff: noqa: RUF001 -- Chinese fixture text uses native punctuation.

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.application.ports.copy_generation import DraftGenerationRequest
from app.application.services.copy_generation import (
    LEAN_CONTEXT_GENERATOR_PROMPT_VERSION,
    SHARED_QUOTE_EVIDENCE_CHAR_BUDGET,
    SHARED_QUOTE_GENERATOR_PROMPT_VERSION,
    CopyGenerationExecutor,
    build_copy_version_bundle,
    build_generator_prompt,
)
from app.core.config import Settings
from app.core.errors import ProviderRejectedError
from app.domain.copy_generation import EligibleEvidence
from app.infrastructure.ai.zhipu import _post_json_with_retries
from pydantic import SecretStr
from structlog.testing import capture_logs
from test_copy_generation import (
    FakeBrandRetriever,
    FakeCopyRepository,
    _brand,
    _topic,
)

PASSAGE = "研究团队发布了用于机器人学习的世界模型研究进展，" * 40  # ~1,000 characters


def _evidence(quote: str, statement: str) -> EligibleEvidence:
    return EligibleEvidence(
        evidence_id=uuid4(),
        candidate_id=uuid4(),
        passage_id=uuid4(),
        occurrence_id=uuid4(),
        snapshot_id=uuid4(),
        source_name="科技日报",
        source_url="https://example.test/article",
        source_tier="A",
        published_at=datetime(2026, 7, 30, tzinfo=UTC),
        exact_quote=quote,
        governed_statement=statement,
    )


def _request(version: str, evidence: tuple[EligibleEvidence, ...]) -> DraftGenerationRequest:
    bundle = replace(
        build_copy_version_bundle(Settings(_env_file=None)), generator_prompt_version=version
    )
    return DraftGenerationRequest(
        run_id=uuid4(),
        topic=replace(_topic(), evidence=evidence),
        brand_context=_brand(),
        version_bundle=bundle,
        draft_version=1,
        max_output_tokens=2048,
    )


def _evidence_block(prompt: str) -> list[dict[str, Any]]:
    # The instructions also mention <EVIDENCE>; the data block is the one holding a JSON list.
    start = prompt.index("<EVIDENCE>[") + len("<EVIDENCE>")
    value: list[dict[str, Any]] = json.loads(prompt[start : prompt.index("</EVIDENCE>", start)])
    return value


def test_v28_writes_each_quote_once_and_keeps_every_fact() -> None:
    # Production shape: one binding per governed fact, all quoting the same long passage.
    evidence = tuple(_evidence(PASSAGE, f"第{index}条治理事实。") for index in range(24))
    lean = build_generator_prompt(_request(LEAN_CONTEXT_GENERATOR_PROMPT_VERSION, evidence))
    shared = build_generator_prompt(_request(SHARED_QUOTE_GENERATOR_PROMPT_VERSION, evidence))

    block = _evidence_block(shared)
    assert [item["evidence_id"] for item in block] == [str(e.evidence_id) for e in evidence]
    assert [item["governed_statement"] for item in block] == [
        e.governed_statement for e in evidence
    ]
    assert block[0]["exact_quote"] == PASSAGE
    assert all(item["exact_quote_same_as"] == block[0]["evidence_id"] for item in block[1:])
    assert all("exact_quote" not in item for item in block[1:])
    assert shared.count(PASSAGE) == 1 and lean.count(PASSAGE) == 24
    assert len(lean) > 26_000 and len(shared) < len(lean) - 20_000
    assert "exact_quote_same_as" in shared.split("<EVIDENCE>")[0]


def test_v27_prompt_is_unchanged_and_distinct_quotes_stay_whole() -> None:
    evidence = (
        _evidence("第一段原文。", "事实一。"),
        _evidence("第二段原文。", "事实二。"),
        _evidence("第一段原文。", "事实三。"),
    )
    lean_block = _evidence_block(
        build_generator_prompt(_request(LEAN_CONTEXT_GENERATOR_PROMPT_VERSION, evidence))
    )
    assert [item["exact_quote"] for item in lean_block] == [
        "第一段原文。",
        "第二段原文。",
        "第一段原文。",
    ]
    shared_block = _evidence_block(
        build_generator_prompt(_request(SHARED_QUOTE_GENERATOR_PROMPT_VERSION, evidence))
    )
    assert [item.get("exact_quote") for item in shared_block] == [
        "第一段原文。",
        "第二段原文。",
        None,
    ]
    assert shared_block[2]["exact_quote_same_as"] == str(evidence[0].evidence_id)


def test_v28_budget_drops_trailing_evidence_but_keeps_one() -> None:
    evidence = tuple(_evidence(f"{index}{PASSAGE}", "事实。") for index in range(40))
    block = _evidence_block(
        build_generator_prompt(_request(SHARED_QUOTE_GENERATOR_PROMPT_VERSION, evidence))
    )
    assert 1 <= len(block) < 40
    assert [item["evidence_id"] for item in block] == [
        str(e.evidence_id) for e in evidence[: len(block)]
    ]
    assert len(json.dumps(block, ensure_ascii=False, separators=(",", ":"))) <= (
        SHARED_QUOTE_EVIDENCE_CHAR_BUDGET
    )
    single = (_evidence(PASSAGE * 30, "事实。"),)
    assert (
        len(
            _evidence_block(
                build_generator_prompt(_request(SHARED_QUOTE_GENERATOR_PROMPT_VERSION, single))
            )
        )
        == 1
    )


def test_default_generator_is_v28() -> None:
    bundle = build_copy_version_bundle(Settings(_env_file=None))
    assert bundle.generator_prompt_version == SHARED_QUOTE_GENERATOR_PROMPT_VERSION


def _post(handler: Any, *, attempts: int = 3) -> httpx.Response:
    async def run() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _post_json_with_retries(
                client=client,
                url="https://open.example.test/api/paas/v4/chat/completions",
                api_key=SecretStr("synthetic-key"),
                http_timeout=httpx.Timeout(5.0),
                total_timeout_seconds=5.0,
                semaphore=asyncio.Semaphore(1),
                max_attempts=attempts,
                sleep=lambda _seconds: asyncio.sleep(0),
                payload={"model": "glm-test"},
                max_response_bytes=65_536,
            )

    return asyncio.run(run())


def _rejection(code: str) -> httpx.Response:
    return httpx.Response(400, json={"error": {"code": code, "message": "blocked"}})


def test_content_filter_rejection_is_retried_and_can_succeed() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _rejection("1301") if len(calls) == 1 else httpx.Response(200, json={"ok": True})

    assert _post(handler).json() == {"ok": True}
    assert len(calls) == 2


def test_persistent_content_filter_is_retried_once_and_keeps_the_code() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _rejection("1301")

    with capture_logs() as logs, pytest.raises(ProviderRejectedError) as raised:
        _post(handler, attempts=3)
    assert raised.value.provider_code == "1301"
    assert raised.value.code == "provider_request_rejected" and not raised.value.retryable
    assert len(calls) == 2  # one identical retry, not the whole attempt budget
    assert [entry["event"] for entry in logs] == ["provider_content_filter_retry"]
    calls.clear()
    with pytest.raises(ProviderRejectedError):
        _post(handler, attempts=1)
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (_rejection("1210"), "1210"),  # a parameter error is not retried
        (httpx.Response(400, content=b"not json"), None),
        (httpx.Response(400, json={"error": {"code": "a code with spaces"}}), None),
        (httpx.Response(422, json={"error": {"code": "1301"}}), None),  # body only read for 400
    ],
)
def test_other_rejections_fail_at_once(response: httpx.Response, expected_code: str | None) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response

    with pytest.raises(ProviderRejectedError) as raised:
        _post(handler)
    assert raised.value.provider_code == expected_code
    assert len(calls) == 1


class _RejectingGenerator:
    calls = 0

    async def generate(self, _request: DraftGenerationRequest) -> Any:
        self.calls += 1
        raise ProviderRejectedError("1301")


def test_failed_copy_attempt_records_the_provider_code() -> None:
    repository = FakeCopyRepository(_topic())
    recorded: dict[str, object] = {}
    original = repository.fail_job

    async def fail_job(**kwargs: Any) -> bool:
        recorded.update(kwargs)
        return await original(**kwargs)

    repository.fail_job = fail_job  # type: ignore[method-assign]
    executor = CopyGenerationExecutor(
        repository=repository,
        brand_retriever=FakeBrandRetriever(),
        generator=_RejectingGenerator(),
        auditor=None,
        settings=Settings(_env_file=None),
    )
    executor._auditor = object()  # type: ignore[assignment]  # generation fails first
    assert asyncio.run(executor.execute_next("copy-rejection-worker")) is True
    assert recorded["error_code"] == "provider_request_rejected"
    assert recorded["provider_error_code"] == "1301"
