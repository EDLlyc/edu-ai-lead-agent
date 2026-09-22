from __future__ import annotations

import asyncio
import importlib.util
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.application.ports.image_generation import ImageGenerationRequest
from app.core.errors import ImageGenerationFailure, StrictImageGenerationError
from app.domain.official_account_local import (
    ArticleMediaSelectionItem,
)
from app.infrastructure.ai.image_generation import DeterministicFakeImageGenerator
from app.infrastructure.wechat_official_account.manual_journal import LocalManualDraftJournal
from test_official_account_visual_generation import (
    _article,
    _reference,
    _reference_jpeg,
    _render,
)

PATH = (
    Path(__file__).resolve().parents[3]
    / ".trellis/tasks/09-22-wechat-draft-scheduler-backfill/research"
    / "single_backfill_operator.py"
)
SPEC = importlib.util.spec_from_file_location("single_backfill_operator", PATH)
assert SPEC is not None and SPEC.loader is not None
operator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = operator
SPEC.loader.exec_module(operator)


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[tuple[str, int, str], bytes] = {}

    async def put_immutable(self, body: bytes, *, media_type: str = "image/png") -> object:
        from hashlib import sha256

        key = (media_type, len(body), sha256(body).hexdigest())
        self.values[key] = body
        return object()

    async def get_content_addressed_bytes(
        self, *, media_type: str, byte_size: int, sha256: str
    ) -> bytes:
        return self.values[(media_type, byte_size, sha256)]


class CountingGenerator:
    def __init__(self, *, fail_at: int | None = None, cancel_at: int | None = None) -> None:
        self.delegate = DeterministicFakeImageGenerator(model="gpt-image-2")
        self.fail_at = fail_at
        self.cancel_at = cancel_at
        self.calls: list[str] = []

    async def generate(self, request):
        index = len(self.calls)
        self.calls.append(request.provider_request_fingerprint)
        if index == self.cancel_at:
            raise asyncio.CancelledError
        if index == self.fail_at:
            raise StrictImageGenerationError(
                ImageGenerationFailure(
                    error_code="official_account_generated_visual_result_unknown",
                    disposition="unknown",
                    reason="post_outcome_unknown",
                )
            )
        return await self.delegate.generate(request)


def slots():
    article = _article()
    reference = _reference()
    rendered = _render(article)
    result = []
    for ordinal in range(5):
        plan = operator.plan_generated_body_visual(
            run_id=rendered.id,
            article=article,
            render=rendered,
            ordinal=ordinal,
            reference=reference,
            provider="fake",
            model="gpt-image-2",
            reference_bytes=_reference_jpeg(),
        )
        request = ImageGenerationRequest(
            run_id=plan.run_id,
            draft_version_id=plan.article_version_id,
            prompt=operator.build_generated_visual_prompt(
                article=article,
                section_index=0,
                reference=reference,
                prompt_version=plan.prompt_version,
                block_index=plan.block_index,
            ),
            request_fingerprint=plan.request_fingerprint,
        )
        result.append(operator.BackfillVisualSlot(ordinal, plan, request))
    return tuple(result)


def auth():
    now = datetime.now(UTC)
    return {
        "binding": {"version": operator.POLICY},
        "authorized_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
    }


async def allowed() -> bool:
    return True


def test_visual_plan_rehydrates_frozen_assignment_metadata_from_article():
    reference = _reference()
    assignment = ArticleMediaSelectionItem(
        ordinal=0,
        section_index=0,
        candidate_ref=reference.catalog_asset_ref,
        source_checksum=reference.source_master_sha256,
        publication_checksum=reference.sha256,
        selection_method="deterministic_tag",
        reason_code="stable_fallback",
        similarity_band=None,
    )
    catalog_reference = replace(
        reference,
        ordinal=None,
        assigned_section_index=None,
        selection_reason_code=None,
        selection_method="deterministic_tag",
        similarity_band=None,
    )
    assigned = operator.assigned_reference(
        assignment=assignment,
        catalog_version=reference.catalog_version,
        reference=catalog_reference,
    )
    assert assigned.assigned_section_index == assignment.section_index
    assert assigned.ordinal == assignment.ordinal
    assert assigned.selection_reason_code == assignment.reason_code


@pytest.mark.asyncio
async def test_five_successes_are_sealed_and_replayed_without_provider_calls(tmp_path):
    store = MemoryStore()
    first = CountingGenerator()
    authorization = auth()
    journal = LocalManualDraftJournal(tmp_path, operator.ACCOUNT)
    try:
        selected = await operator.select_visuals(
            journal=journal,
            auth=authorization,
            slots=slots(),
            generator=first,
            store=store,
            authorize_side_effect=allowed,
        )
        receipt = operator.seal_visual_selection(journal, auth=authorization, selection=selected)
        assert receipt["origin"] == "generated"
        assert len(first.calls) == 5
        second = CountingGenerator()
        replayed = await operator.select_visuals(
            journal=journal,
            auth=authorization,
            slots=slots(),
            generator=second,
            store=store,
            authorize_side_effect=allowed,
        )
        assert replayed.origin == "generated"
        assert second.calls == []
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_first_unknown_stops_remaining_calls_and_permanently_selects_whole_fallback(tmp_path):
    store = MemoryStore()
    authorization = auth()
    journal = LocalManualDraftJournal(tmp_path, operator.ACCOUNT)
    try:
        first = CountingGenerator(fail_at=2)
        selected = await operator.select_visuals(
            journal=journal,
            auth=authorization,
            slots=slots(),
            generator=first,
            store=store,
            authorize_side_effect=allowed,
        )
        assert selected.origin == "approved_catalog_fallback"
        assert len(first.calls) == 3
        operator.seal_visual_selection(journal, auth=authorization, selection=selected)
        second = CountingGenerator()
        replayed = await operator.select_visuals(
            journal=journal,
            auth=authorization,
            slots=slots(),
            generator=second,
            store=store,
            authorize_side_effect=allowed,
        )
        assert replayed.origin == "approved_catalog_fallback"
        assert second.calls == []
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_crash_after_intent_is_unknown_and_never_replayed(tmp_path):
    store = MemoryStore()
    authorization = auth()
    journal = LocalManualDraftJournal(tmp_path, operator.ACCOUNT)
    try:
        with pytest.raises(asyncio.CancelledError):
            await operator.select_visuals(
                journal=journal,
                auth=authorization,
                slots=slots(),
                generator=CountingGenerator(cancel_at=0),
                store=store,
                authorize_side_effect=allowed,
            )
        second = CountingGenerator()
        selected = await operator.select_visuals(
            journal=journal,
            auth=authorization,
            slots=slots(),
            generator=second,
            store=store,
            authorize_side_effect=allowed,
        )
        assert selected.origin == "approved_catalog_fallback"
        assert selected.safe_results[0]["status"] == "outcome_unknown"
        assert second.calls == []
        receipt = operator.seal_visual_selection(journal, auth=authorization, selection=selected)
        assert receipt["origin"] == "approved_catalog_fallback"
    finally:
        journal.close()


def test_readback_accepts_only_narrow_wechat_serialization_differences():
    expected = operator.WeChatDraftArticleRequest(
        "科学教育",
        "程岳",
        "摘要",
        '<section style="color:#123"><span leaf>孩子</span>'
        '<img src="https://mmbiz.qpic.cn/a.jpg/0?x=1"/></section>',
        None,
        "thumb",
        False,
        False,
    )
    observed = operator.replace(
        expected,
        content=(
            '<section style="color:#123"><span leaf="leaf">孩子</span><img '
            'data-src="https://mmbiz.qpic.cn/a.jpg/640?x=1"></section>'
        ),
    )
    assert operator.equivalent_draft(expected, observed)
    assert not operator.equivalent_draft(
        expected, operator.replace(observed, content=observed.content.replace("#123", "#124"))
    )
