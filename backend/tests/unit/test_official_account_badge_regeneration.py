from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
from dataclasses import dataclass, replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageReference,
)
from app.core.errors import ImageGenerationFailure, StrictImageGenerationError
from app.domain.image_provider_input import IMAGE_REFERENCE_INPUT_V2
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION,
    STRICT_VISUAL_POLICY,
)
from PIL import Image
from test_official_account_visual_generation import (
    _article,
    _reference,
    _reference_jpeg,
    _render,
)

PATH = (
    Path(__file__).resolve().parents[3]
    / ".trellis/tasks/09-22-wechat-draft-scheduler-backfill/research"
    / "regenerate_badge_visuals.py"
)
SPEC = importlib.util.spec_from_file_location("regenerate_badge_visuals", PATH)
assert SPEC is not None and SPEC.loader is not None
operator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = operator
SPEC.loader.exec_module(operator)


@dataclass(frozen=True)
class Descriptor:
    media_type: str
    byte_size: int
    sha256: str


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[tuple[str, int, str], bytes] = {}

    async def put_immutable(self, body: bytes, *, media_type: str = "image/png") -> Descriptor:
        digest = sha256(body).hexdigest()
        self.values[(media_type, len(body), digest)] = body
        return Descriptor(media_type, len(body), digest)

    async def get_content_addressed_bytes(
        self, *, media_type: str, byte_size: int, sha256: str
    ) -> bytes:
        return self.values[(media_type, byte_size, sha256)]


class CountingGenerator:
    def __init__(self, *, fail_at: int | None = None, cancel_at: int | None = None) -> None:
        self.fail_at = fail_at
        self.cancel_at = cancel_at
        self.requests: list[ImageGenerationRequest] = []

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        index = len(self.requests)
        self.requests.append(request)
        if index == self.cancel_at:
            raise asyncio.CancelledError
        if index == self.fail_at:
            raise StrictImageGenerationError(
                ImageGenerationFailure(
                    error_code="provider_unavailable",
                    disposition="not_applied_retryable",
                    reason="connect_failed",
                )
            )
        stream = BytesIO()
        Image.new("RGB", (1536, 1024), (30 + index, 80, 120)).save(stream, format="PNG")
        body = stream.getvalue()
        return ImageGenerationResult(
            provider=STRICT_VISUAL_POLICY.generation_provider,
            model=STRICT_VISUAL_POLICY.generation_model,
            request_fingerprint=request.request_fingerprint,
            provider_task_id=f"task-{index}",
            provider_upload_id=None,
            image_bytes=body,
            media_type="image/png",
            width=1536,
            height=1024,
            attempts=1,
        )


def target_and_slots():
    article = _article()
    render = _render(article)
    reference = replace(_reference(), selection_method="deterministic_tag", similarity_band=None)
    reference_bytes = _reference_jpeg()
    target = operator.CorrectionTarget(
        article=article,
        render=render,
        run_id=render.id,
        target_identity="a" * 64,
        plan_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
        prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION,
    )
    slots = []
    for ordinal in range(5):
        plan = operator.plan_generated_body_visual(
            run_id=target.run_id,
            article=article,
            render=render,
            ordinal=ordinal,
            reference=reference,
            provider=STRICT_VISUAL_POLICY.generation_provider,
            model=STRICT_VISUAL_POLICY.generation_model,
            reference_bytes=reference_bytes,
            plan_version=target.plan_version,
            prompt_version=target.prompt_version,
        )
        prompt = operator.build_badge_visual_prompt(
            article=article,
            section_index=plan.section_index,
            reference=reference,
            prompt_version=plan.prompt_version,
            block_index=plan.block_index,
        )
        prompt_digest = sha256(prompt.encode()).hexdigest()
        logical = operator.fingerprint(
            operator.POLICY,
            "logical-corrected-visual-request",
            target.target_identity,
            ordinal,
            plan.request_fingerprint,
            prompt_digest,
        )
        plan = replace(plan, request_fingerprint=logical)
        request = ImageGenerationRequest(
            run_id=target.run_id,
            draft_version_id=article.id,
            prompt=prompt,
            request_fingerprint=logical,
            output_size=STRICT_VISUAL_POLICY.output_size,
            references=(
                ImageReference(
                    role="approved_ip_reference",
                    asset_id=plan.reference_asset_ref,
                    filename="reference.jpg",
                    sha256=reference.sha256,
                    image_bytes=reference_bytes,
                    input_normalization_version=IMAGE_REFERENCE_INPUT_V2,
                    provider_input_sha256=plan.reference_input_checksum,
                ),
            ),
            reference_mode="single_reference",
        )
        slots.append(operator.CorrectionVisualSlot(ordinal, plan, request, prompt_digest))
    return target, tuple(slots)


def journal(tmp_path: Path):
    root = tmp_path / "journal"
    account = root / "manual-v1" / operator.ACCOUNT
    account.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    (root / "manual-v1").chmod(0o700)
    account.chmod(0o700)
    return operator.PrivateJournal(root, operator.ACCOUNT)


async def allowed() -> bool:
    return True


class TargetGuard:
    def __init__(self, *, fail_at: int) -> None:
        self.fail_at = fail_at
        self.calls = 0

    async def __call__(self) -> bool:
        current = self.calls
        self.calls += 1
        return current != self.fail_at


def test_all_five_prompts_require_badge_and_have_distinct_new_identities():
    target, slots = target_and_slots()
    physical = [operator._physical_identity(target.target_identity, slot) for slot in slots]
    assert len(set(physical)) == len(set(slot.plan.request_fingerprint for slot in slots)) == 5
    for slot in slots:
        assert "mandatory small centered blue 'AI' chest panel" in slot.request.prompt
        assert "Text: none except Xiaosai's white 'AI' chest badge" in slot.request.prompt
        assert (
            "No other words, letters, numbers, logos, marks, labels, UI, QR, watermarks"
            in slot.request.prompt
        )
        assert "chest labels" not in slot.request.prompt


def test_old_production_prompt_text_is_upgraded(monkeypatch):
    target, slots = target_and_slots()
    corrected = slots[0].request.prompt
    old = corrected.replace(operator._NEW_IDENTITY, operator._OLD_IDENTITY, 1).replace(
        operator._NEW_TEXT_RULE, operator._OLD_TEXT_RULE, 1
    )
    monkeypatch.setattr(operator, "build_generated_visual_prompt", lambda **_kwargs: old)
    upgraded = operator.build_badge_visual_prompt(
        article=target.article,
        section_index=slots[0].plan.section_index,
        reference=_reference(),
        prompt_version=slots[0].plan.prompt_version,
        block_index=slots[0].plan.block_index,
    )
    assert upgraded == corrected


@pytest.mark.asyncio
async def test_five_calls_are_content_addressed_and_replay_makes_no_calls(tmp_path):
    target, slots = target_and_slots()
    store = MemoryStore()
    first = CountingGenerator()
    ledger = journal(tmp_path)
    try:
        result = await operator.generate_badge_visuals(
            journal=ledger,
            target=target,
            slots=slots,
            generator=first,
            store=store,
            target_still_current=allowed,
        )
        assert result["status"] == "ready_for_visual_inspection"
        assert result["provider_calls"] == len(first.requests) == 5
        selection = ledger.read(operator.SELECTION_NAME)
        assert selection is not None
        assert len(selection["objects"]) == 5
        for ordinal, media_type, byte_size, digest, width, height in selection["objects"]:
            assert ordinal in range(5)
            assert (media_type, byte_size, digest) in store.values
            assert (width, height) == (1536, 1024)
        replay = CountingGenerator()
        repeated = await operator.generate_badge_visuals(
            journal=ledger,
            target=target,
            slots=slots,
            generator=replay,
            store=store,
            target_still_current=allowed,
        )
        assert repeated["status"] == "ready_for_visual_inspection"
        assert repeated["provider_calls"] == 0
        assert replay.requests == []
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_failure_stops_later_slots_and_never_retries(tmp_path):
    target, slots = target_and_slots()
    store = MemoryStore()
    first = CountingGenerator(fail_at=2)
    ledger = journal(tmp_path)
    try:
        result = await operator.generate_badge_visuals(
            journal=ledger,
            target=target,
            slots=slots,
            generator=first,
            store=store,
            target_still_current=allowed,
        )
        assert result["status"] == "stopped"
        assert result["provider_calls"] == len(first.requests) == 3
        assert ledger.read(operator._intent_name(3)) is None
        replay = CountingGenerator()
        repeated = await operator.generate_badge_visuals(
            journal=ledger,
            target=target,
            slots=slots,
            generator=replay,
            store=store,
            target_still_current=allowed,
        )
        assert repeated["status"] == "stopped"
        assert repeated["provider_calls"] == 0
        assert replay.requests == []
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_orphan_intent_becomes_unknown_without_replay(tmp_path):
    target, slots = target_and_slots()
    store = MemoryStore()
    ledger = journal(tmp_path)
    try:
        with pytest.raises(asyncio.CancelledError):
            await operator.generate_badge_visuals(
                journal=ledger,
                target=target,
                slots=slots,
                generator=CountingGenerator(cancel_at=0),
                store=store,
                target_still_current=allowed,
            )
    finally:
        ledger.close()
    ledger = operator.PrivateJournal(tmp_path / "journal", operator.ACCOUNT)
    try:
        replay = CountingGenerator()
        result = await operator.generate_badge_visuals(
            journal=ledger,
            target=target,
            slots=slots,
            generator=replay,
            store=store,
            target_still_current=allowed,
        )
        assert result["status"] == "stopped"
        assert result["error_code"] == "badge_regeneration_outcome_unknown"
        assert result["provider_calls"] == 0
        assert replay.requests == []
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_target_drift_after_a_completed_call_stops_before_the_next_call(tmp_path):
    target, slots = target_and_slots()
    store = MemoryStore()
    generator = CountingGenerator()
    ledger = journal(tmp_path)
    try:
        with pytest.raises(operator.OperatorError) as captured:
            await operator.generate_badge_visuals(
                journal=ledger,
                target=target,
                slots=slots,
                generator=generator,
                store=store,
                target_still_current=TargetGuard(fail_at=1),
            )
        assert captured.value.code == "badge_regeneration_target_changed"
        assert len(generator.requests) == 1
        assert ledger.read(operator._result_name(0))["status"] == "ready"
        assert ledger.read(operator._intent_name(1)) is None
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_ready_receipt_is_bound_to_slot_and_physical_identity(tmp_path):
    target, slots = target_and_slots()
    store = MemoryStore()
    ledger = journal(tmp_path)
    try:
        await operator.generate_badge_visuals(
            journal=ledger,
            target=target,
            slots=slots,
            generator=CountingGenerator(),
            store=store,
            target_still_current=allowed,
        )
        result = ledger.read(operator._result_name(0))
        assert result is not None
        tampered = {**result, "provider_request_fingerprint": "b" * 64}
        with pytest.raises(operator.OperatorError) as captured:
            await operator._verify_ready_object(
                store,
                tampered,
                intent_sha256=result["intent_sha256"],
                ordinal=0,
                provider_request_fingerprint=operator._physical_identity(
                    target.target_identity, slots[0]
                ),
            )
        assert captured.value.code == "badge_regeneration_result_changed"
    finally:
        ledger.close()


def test_operator_has_no_social_client_import_or_database_write_primitive():
    source = PATH.read_text()
    tree = ast.parse(source)
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any("wechat" in module.casefold() for module in modules)
    assert not any("wechat" in name.casefold() for name in imported)
    assert "WeChatOfficialAccount" not in source
    assert "session.commit" not in source
    assert "session.begin" not in source
    assert "insert(" not in source
    assert "update(" not in source
    assert "delete(" not in source
