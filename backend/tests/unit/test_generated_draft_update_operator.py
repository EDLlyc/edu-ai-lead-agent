from __future__ import annotations

import importlib.util
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from app.application.ports.image_generation import ImageGenerationResult
from app.application.ports.image_validation import ImageQualityAuditResult
from app.core.errors import ImageOutputValidationError
from app.domain.official_account_local import fingerprint
from app.domain.official_account_visual_pipeline import STRICT_VISUAL_POLICY
from app.infrastructure.wechat_official_account.manual_journal import LocalManualDraftJournal
from PIL import Image
from pydantic import SecretStr
from test_official_account_strict_visual_worker import _components
from test_official_account_worker import _ApprovedCatalog

PATH = (
    Path(__file__).resolve().parents[3]
    / ".trellis/tasks/09-05-production-recovery-qwen-embedding/research"
    / "visual-recovery-20260916/generated-draft-update.py"
)
SPEC = importlib.util.spec_from_file_location("generated_draft_update_operator", PATH)
operator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(operator)


async def inputs():
    repo, store, generator, _auditor, executor = _components()
    assert await executor.execute_next("prepare-offline-fixture")
    assert repo.failure is None
    candidates = {row.catalog_asset_ref: row for row in await _ApprovedCatalog().load_candidates()}
    plans = tuple(repo.generated[i].plan for i in range(5))
    references = tuple(
        replace(
            candidates[plan.reference_asset_ref],
            ordinal=i,
            assigned_section_index=plan.section_index,
            selection_method=plan.selection_method,
            similarity_band=plan.similarity_band,
        )
        for i, plan in enumerate(plans)
    )
    contents = tuple(request.references[0].image_bytes for request in generator.calls)
    bodies = tuple(store.images[repo.generated[i].sha256] for i in range(5))
    return repo.article, references, contents, plans, bodies


class Generator:
    def __init__(self, bodies, unknown=False):
        self.bodies, self.unknown, self.calls = bodies, unknown, []

    async def generate(self, request):
        ordinal = len(self.calls)
        self.calls.append(request)
        if self.unknown:
            raise TimeoutError("synthetic private transport details")
        return ImageGenerationResult(
            provider="comfly",
            model=STRICT_VISUAL_POLICY.generation_model,
            request_fingerprint=request.request_fingerprint,
            provider_task_id=None,
            provider_upload_id=None,
            image_bytes=self.bodies[ordinal],
            media_type="image/jpeg",
            width=1536,
            height=1024,
            attempts=1,
        )


class Auditor:
    def __init__(self, *, unknown=False, accepted=True):
        self.unknown, self.accepted, self.calls = unknown, accepted, []

    async def audit(self, request):
        self.calls.append(request)
        if self.unknown:
            raise TimeoutError("synthetic private audit details")
        return ImageQualityAuditResult(
            accepted=self.accepted,
            provider="openai-compatible",
            model="glm-5v-turbo",
            request_fingerprint=request.request_fingerprint,
        )


@pytest.mark.asyncio
async def test_five_distinct_new_keys_six_exact_audits_and_resume_without_paid_calls(tmp_path):
    article, refs, sources, plans, bodies = await inputs()
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    generator, auditor = Generator(bodies), Auditor()
    try:
        result = await operator.generate(
            journal,
            {"test_auth": "explicit-new-operation"},
            article,
            refs,
            sources,
            plans,
            generator,
            auditor,
            AsyncMock(return_value=True),
        )
        assert len(generator.calls) == 5 and len(auditor.calls) == 6
        physical = [request.provider_request_fingerprint for request in generator.calls]
        assert len(set(physical)) == 5
        assert not set(physical) & {plan.request_fingerprint for plan in plans}
        assert tuple(request.image_bytes for request in auditor.calls) == (*result[0], result[1])
        assert len(result[1]) < 65536
        fresh_generator, fresh_auditor = Generator(bodies), Auditor()
        assert (
            await operator.generate(
                journal,
                {"test_auth": "explicit-new-operation"},
                article,
                refs,
                sources,
                plans,
                fresh_generator,
                fresh_auditor,
                AsyncMock(return_value=False),
            )
            == result
        )
        assert fresh_generator.calls == [] and fresh_auditor.calls == []
    finally:
        journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["generation", "audit", "rejected"])
async def test_unknown_or_rejected_never_replayed_and_cannot_complete(tmp_path, phase):
    article, refs, sources, plans, bodies = await inputs()
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    generator = Generator(bodies, unknown=phase == "generation")
    auditor = Auditor(unknown=phase == "audit", accepted=phase != "rejected")
    try:
        with pytest.raises((TimeoutError, ValueError)):
            await operator.generate(
                journal,
                {"test": "bound"},
                article,
                refs,
                sources,
                plans,
                generator,
                auditor,
                AsyncMock(return_value=True),
            )
        fresh_generator, fresh_auditor = Generator(bodies), Auditor()
        with pytest.raises(ValueError, match=r"prior_outcome_unknown|audit_failed"):
            await operator.generate(
                journal,
                {"test": "bound"},
                article,
                refs,
                sources,
                plans,
                fresh_generator,
                fresh_auditor,
                AsyncMock(return_value=True),
            )
        assert fresh_generator.calls == [] and fresh_auditor.calls == []
        assert journal.read(operator.PREFIX + "-image-1-intent.json") is None
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_intent_is_durable_before_paid_dispatch_and_result_prevents_repeat(tmp_path):
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    intent = {"identity": "explicit-paid-operation"}

    async def paid():
        assert journal.read("generated-test-intent.json") == intent
        assert journal.read("generated-test-result.json") is None
        return {"ok": True}

    invoke = AsyncMock(side_effect=paid)
    try:
        first = await operator.once(
            journal, "generated-test", intent, invoke, AsyncMock(return_value=True)
        )
        assert (
            await operator.once(
                journal, "generated-test", intent, invoke, AsyncMock(return_value=False)
            )
            == first
        )
        assert invoke.await_count == 1
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_default_plan_constructs_no_model_or_wechat_client_and_writes_no_authority(
    tmp_path, monkeypatch
):
    manual = SimpleNamespace(
        ACCOUNT="a" * 64, wechat_draft_account_fingerprint=lambda _app: "a" * 64
    )
    settings = SimpleNamespace(
        image_provider_mode="comfly",
        image_model="gpt-image-2.5-sunburst",
        wechat_mp_app_id=None,
        wechat_mp_draft_artifact_root=tmp_path,
        image_asset_manifest="unused-fixture",
    )
    (tmp_path / "manual-v1" / manual.ACCOUNT).mkdir(parents=True)
    engine = SimpleNamespace(dispose=AsyncMock())
    journal = SimpleNamespace(
        write=lambda *_: pytest.fail("plan must not write"), close=lambda: None
    )
    base = SimpleNamespace(title="科学教育", author="程岳", digest="摘要")
    monkeypatch.setattr(operator, "load_manual", lambda: manual)
    monkeypatch.setattr(operator, "get_settings", lambda: settings)
    monkeypatch.setattr(operator, "create_engine", lambda _settings: engine)
    monkeypatch.setattr(operator, "create_session_factory", lambda _engine: object())
    monkeypatch.setattr(operator, "LocalOfficialAccountCatalogMediaProvider", lambda _: object())
    monkeypatch.setattr(operator, "LocalManualDraftJournal", lambda *_: journal)
    monkeypatch.setattr(
        operator, "prepare_inputs", AsyncMock(return_value=(None, None, base, "source", (), (), ()))
    )
    monkeypatch.setattr(
        operator,
        "original_receipt",
        lambda *_: (
            "fixture-media",
            {"title": base.title, "author": base.author, "digest": base.digest},
            "receipt",
        ),
    )
    monkeypatch.setattr(operator, "authorization", lambda *_: {})
    monkeypatch.setattr(
        operator, "BoundedNormalizedGenerator", lambda _: pytest.fail("paid client")
    )
    monkeypatch.setattr(
        operator,
        "LazyStrictOfficialAccountImageQualityAuditor",
        lambda _: pytest.fail("paid client"),
    )
    await operator.main("plan")
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_authority_makes_no_first_paid_call(tmp_path):
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    paid = AsyncMock(return_value={"ok": True})
    try:
        with pytest.raises(ValueError, match="authority_expired"):
            await operator.once(
                journal, "generated-test", {"identity": "safe"}, paid, AsyncMock(return_value=False)
            )
        assert paid.await_count == 0
        assert journal.read("generated-test-intent.json") is None
    finally:
        journal.close()


def raster(fmt="PNG", *, size=(768, 1024), orientation=1):
    stream = BytesIO()
    image = Image.new("RGB", size, (32, 112, 180))
    exif = Image.Exif()
    exif[274] = orientation
    image.save(stream, format=fmt, exif=exif)
    return stream.getvalue()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_bounded_normalizer_decodes_single_frame_exif_rgb_fits_deterministically(fmt):
    adapter = operator.NormalizedComflyGenerator(
        client=None,
        base_url="https://example.com",
        api_key=SecretStr("test"),
        max_download_bytes=12 * 1024 * 1024,
    )
    raw = raster(fmt, orientation=6)
    first = adapter._normalize_image_bytes(raw, expected_dimensions=(1536, 1024))
    assert first == adapter._normalize_image_bytes(raw, expected_dimensions=(1536, 1024))
    body, media_type, width, height = first
    assert (media_type, width, height) == ("image/jpeg", 1536, 1024)
    with Image.open(BytesIO(body)) as image:
        assert image.mode == "RGB" and image.size == (1536, 1024)
        assert image.getexif().get(274, 1) == 1
    assert adapter.last_normalization["source_sha256"] == sha256(raw).hexdigest()
    assert adapter.last_normalization["version"] == operator.NORMALIZATION_VERSION


@pytest.mark.parametrize("invalid", ["non-image", "too-large", "mismatch", "animated", "tiny"])
def test_bounded_normalizer_still_rejects_invalid_raster(invalid):
    adapter = operator.NormalizedComflyGenerator(
        client=None,
        base_url="https://example.com",
        api_key=SecretStr("test"),
        max_download_bytes=12 * 1024 * 1024,
    )
    body, declared = raster(), None
    if invalid == "non-image":
        body = b"<html>upstream error</html>"
    elif invalid == "too-large":
        adapter._max_download_bytes = len(body) - 1
    elif invalid == "mismatch":
        declared = "image/jpeg"
    elif invalid == "tiny":
        body = raster(size=(10, 10))
    else:
        stream = BytesIO()
        Image.new("RGB", (256, 256), "blue").save(
            stream,
            format="WEBP",
            save_all=True,
            append_images=[Image.new("RGB", (256, 256), "red")],
            duration=100,
        )
        body = stream.getvalue()
    with pytest.raises(ImageOutputValidationError):
        adapter._normalize_image_bytes(
            body, expected_dimensions=(1536, 1024), declared_media_type=declared
        )


def recovery_fixture(journal, monkeypatch):
    now = datetime(2026, 9, 16, 10, tzinfo=UTC)
    auth = {"expires_at": (now + timedelta(hours=1)).isoformat(), "binding": "fixture"}
    intent = {
        "authorization_fingerprint": fingerprint(auth),
        "ordinal": 0,
        "provider_request_fingerprint": "old-physical-key",
        "model": "gpt-image-2.5-sunburst",
    }
    journal.write(operator.PREFIX + "-image-0-intent.json", intent)
    monkeypatch.setattr(operator, "ORIGINAL_TERMINAL_INTENT", fingerprint(intent))
    return now, auth, intent


@pytest.mark.asyncio
async def test_explicit_terminal_recovery_preserves_original_and_allows_one_new_key_only(
    tmp_path, monkeypatch
):
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    try:
        now, auth, intent = recovery_fixture(journal, monkeypatch)
        assert operator.select_generation_attempt(journal, auth, 0, intent) == (
            operator.PREFIX + "-image-0",
            intent,
        )
        with pytest.raises(ValueError, match="terminal_evidence_required"):
            operator.authorize_terminal_recovery(
                journal, auth, 0, now=now, observed_intent="wrong", persist=True
            )
        plan = operator.authorize_terminal_recovery(
            journal, auth, 0, now=now, observed_intent=fingerprint(intent)
        )
        assert journal.read(operator.PREFIX + "-image-0-attempt2-authorization.json") is None
        assert plan == operator.authorize_terminal_recovery(
            journal, auth, 0, now=now, observed_intent=fingerprint(intent), persist=True
        )
        assert plan == operator.authorize_terminal_recovery(
            journal,
            auth,
            0,
            now=now + timedelta(minutes=5),
            observed_intent=fingerprint(intent),
            persist=True,
        )
        name, successor = operator.select_generation_attempt(journal, auth, 0, intent)
        assert successor["provider_request_fingerprint"] != intent["provider_request_fingerprint"]
        assert successor["prior_intent_fingerprint"] == fingerprint(intent)
        paid = AsyncMock(side_effect=TimeoutError("unknown"))
        with pytest.raises(TimeoutError):
            await operator.generated_once(
                journal, name, successor, paid, AsyncMock(return_value=True)
            )
        with pytest.raises(ValueError, match="prior_outcome_unknown"):
            await operator.generated_once(
                journal, name, successor, paid, AsyncMock(return_value=True)
            )
        assert paid.await_count == 1
        assert journal.read(operator.PREFIX + "-image-0-intent.json") == intent
        assert journal.read(name + "-terminal-invalid.json") is None
        assert journal.read(operator.PREFIX + "-image-0-result.json") is None
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_new_terminal_invalid_records_evidence_but_does_not_automatically_retry(tmp_path):
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    now = datetime(2026, 9, 16, 10, tzinfo=UTC)
    auth = {"expires_at": (now + timedelta(hours=1)).isoformat()}
    name = operator.PREFIX + "-image-1"
    intent = {
        "authorization_fingerprint": fingerprint(auth),
        "ordinal": 1,
        "provider_request_fingerprint": "key1",
    }
    paid = AsyncMock(side_effect=ImageOutputValidationError())
    try:
        with pytest.raises(ImageOutputValidationError):
            await operator.generated_once(journal, name, intent, paid, AsyncMock(return_value=True))
        marker = journal.read(name + "-terminal-invalid.json")
        assert (
            marker["intent_fingerprint"] == fingerprint(intent)
            and marker["cause_detail_known"] is False
        )
        with pytest.raises(ValueError, match="prior_outcome_unknown"):
            await operator.generated_once(journal, name, intent, paid, AsyncMock(return_value=True))
        assert paid.await_count == 1
        assert journal.read(name + "-attempt2-authorization.json") is None
        with pytest.raises(ValueError, match="recovery_ordinal_not_authorized"):
            operator.authorize_terminal_recovery(journal, auth, 1, now=now, persist=True)
        assert journal.read(name + "-attempt2-authorization.json") is None
    finally:
        journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe",
    [
        pytest.param(
            False,
            marks=pytest.mark.xfail(
                strict=True,
                raises=TypeError,
                reason=(
                    "the 09-16 recovery operator is frozen (its code hash is pinned) and predates "
                    "the image generator's output_geometry_policy argument; kept for provenance"
                ),
            ),
        ),
        True,
    ],
)
async def test_normalized_adapter_preserves_single_post_key_and_rejects_unsafe_download(unsafe):
    repo, _store, old_generator, _auditor, executor = _components()
    assert await executor.execute_next("fixture-request") and repo.failure is None
    request = replace(old_generator.calls[0], provider_request_fingerprint="a" * 64)
    calls = []

    async def handler(http_request):
        calls.append(http_request)
        if unsafe:
            return httpx.Response(200, json={"data": [{"url": "https://127.0.0.1/private"}]})
        return httpx.Response(200, content=raster(), headers={"content-type": "image/png"})

    settings = SimpleNamespace(
        image_provider_mode="comfly",
        image_model=STRICT_VISUAL_POLICY.generation_model,
        comfly_api_key=SecretStr("fixture"),
        comfly_base_url="https://example.com",
        image_poll_initial_seconds=0.01,
        image_poll_interval_seconds=0.01,
        image_provider_window_seconds=60,
        image_provider_timeout_seconds=30,
        image_max_download_bytes=12 * 1024 * 1024,
        image_max_request_bytes=8 * 1024 * 1024,
        image_max_provider_response_bytes=32 * 1024 * 1024,
        image_max_reference_images=3,
    )
    adapter = operator.BoundedNormalizedGenerator(
        settings, transport_factory=lambda: httpx.MockTransport(handler)
    )
    if unsafe:
        with pytest.raises(ImageOutputValidationError):
            await adapter.generate(request)
    else:
        result = await adapter.generate(request)
        assert result.width == 1536 and result.height == 1024 and result.attempts == 1
        assert result.request_fingerprint == request.request_fingerprint
        assert adapter.last_normalization["source_width"] == 768
    assert len(calls) == 1 and calls[0].method == "POST"
    assert calls[0].headers["Idempotency-Key"] == "a" * 64


@pytest.mark.asyncio
async def test_authorized_first_image_replacement_continues_rest_and_resumes_exact_receipts(
    tmp_path, monkeypatch
):
    article, refs, sources, plans, bodies = await inputs()
    journal = LocalManualDraftJournal(tmp_path, "a" * 64)
    now = datetime(2026, 9, 16, 10, tzinfo=UTC)
    auth = {"expires_at": (now + timedelta(hours=1)).isoformat()}
    failing = SimpleNamespace(generate=AsyncMock(side_effect=ImageOutputValidationError()))
    allowed = AsyncMock(return_value=True)
    try:
        with pytest.raises(ImageOutputValidationError):
            await operator.generate(
                journal, auth, article, refs, sources, plans, failing, Auditor(), allowed
            )
        old_name = operator.PREFIX + "-image-0"
        old_intent = journal.read(old_name + "-intent.json")
        monkeypatch.setattr(operator, "ORIGINAL_TERMINAL_INTENT", fingerprint(old_intent))
        operator.authorize_terminal_recovery(journal, auth, 0, now=now, persist=True)
        generator, auditor = Generator(bodies), Auditor()
        ready = await operator.generate(
            journal, auth, article, refs, sources, plans, generator, auditor, allowed
        )
        assert len(generator.calls) == 5 and len(auditor.calls) == 6
        assert (
            generator.calls[0].provider_request_fingerprint
            != old_intent["provider_request_fingerprint"]
        )
        assert journal.read(old_name + "-intent.json") == old_intent
        assert journal.read(old_name + "-result.json") is None
        assert journal.read(old_name + "-attempt2-result.json") is not None
        for i in range(1, 5):
            record = journal.read(operator.PREFIX + f"-image-{i}-intent.json")
            assert record["normalization_version"] == operator.NORMALIZATION_VERSION
            assert journal.read(operator.PREFIX + f"-image-{i}-result.json") is not None
        forbidden = SimpleNamespace(generate=AsyncMock(side_effect=AssertionError("paid replay")))
        audit_forbidden = SimpleNamespace(
            audit=AsyncMock(side_effect=AssertionError("audit replay"))
        )
        assert ready == await operator.generate(
            journal,
            auth,
            article,
            refs,
            sources,
            plans,
            forbidden,
            audit_forbidden,
            AsyncMock(return_value=False),
        )
        forbidden.generate.assert_not_awaited()
        audit_forbidden.audit.assert_not_awaited()
    finally:
        journal.close()
