from __future__ import annotations

import asyncio
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from random import Random
from uuid import uuid4

import pytest
from app.application.ports.image_generation import ImageGenerationResult
from app.application.ports.image_validation import ImageQualityAuditResult
from app.application.ports.official_account_strict_visual import (
    StoredStrictVisualAudit,
    StrictGeneratedVisualClaim,
    StrictVisualAuditClaim,
    strict_audit_record_fingerprint,
)
from app.application.services.official_account_local import OfficialAccountLocalExecutor
from app.infrastructure.official_account_local import (
    DeterministicFakeOfficialAccountArticleAuditor,
    DeterministicFakeOfficialAccountArticleGenerator,
    LocalOfficialAccountDraftAdapter,
    LocalOfficialAccountMediaAdapter,
)
from app.infrastructure.official_account_runtime import official_account_identity_from_settings
from PIL import Image
from test_official_account_strict_visual_policy import _settings
from test_official_account_worker import _ApprovedCatalog, _GeneratedVisualRepository


class _Repository(_GeneratedVisualRepository):
    def __init__(self):
        super().__init__()
        self.identity = official_account_identity_from_settings(
            _settings(), provider="zhipu", model="glm-5.2"
        )
        self.audits = {}
        self.fail_completion = False
        self.fail_generation_completion = False

    async def persist_generated_visual(self, **kwargs):
        if self.fail_generation_completion:
            raise RuntimeError("synthetic generation completion failure")
        return await super().persist_generated_visual(**kwargs)

    async def load_news_context_candidates(self, claimed):
        return ()

    async def claim_strict_generated_visual(self, *, claimed, plan):
        prior = self.generated.get(plan.ordinal)
        if prior is not None:
            assert prior.plan == plan
            return StrictGeneratedVisualClaim(
                "completed" if prior.status == "ready" else "result_unknown", prior
            )
        return StrictGeneratedVisualClaim(
            "newly_claimed", await self.create_generated_visual_intent(claimed=claimed, plan=plan)
        )

    async def claim_strict_visual_audit(self, *, claimed, subject):
        key = (subject.role, subject.ordinal)
        if key in self.audits:
            prior = self.audits[key]
            assert prior.subject == subject
            return StrictVisualAuditClaim(
                "result_unknown" if prior.status in {"calling", "result_unknown"} else "completed",
                prior,
            )
        row = StoredStrictVisualAudit(uuid4(), subject, "calling", (), None)
        self.audits[key] = row
        return StrictVisualAuditClaim("newly_claimed", row)

    async def complete_strict_visual_audit(
        self, *, claimed, subject, status, issue_codes, result=None
    ):
        if self.fail_completion:
            raise RuntimeError("synthetic DB completion failure")
        key = (subject.role, subject.ordinal)
        current = self.audits[key]
        assert current.status == "calling"
        stored = replace(
            current,
            status=status,
            issue_codes=issue_codes,
            record_fingerprint=strict_audit_record_fingerprint(subject, status, issue_codes),
        )
        self.audits[key] = stored
        return stored


class _Store:
    def __init__(self):
        self.images = {}

    async def put_immutable(self, body, *, media_type):
        self.images[sha256(body).hexdigest()] = body

    async def get_content_addressed_bytes(self, *, media_type, byte_size, sha256):
        body = self.images[sha256]
        assert len(body) == byte_size
        return body


class _TextGenerator(DeterministicFakeOfficialAccountArticleGenerator):
    async def generate(self, request):
        result = await super().generate(request)
        return replace(result, provider=request.identity.provider, model=request.identity.model)


class _TextAuditor(DeterministicFakeOfficialAccountArticleAuditor):
    async def audit(self, request):
        result = await super().audit(request)
        return replace(result, provider=request.identity.provider, model=request.identity.model)


class _Generator:
    def __init__(self, repository):
        self.repository = repository
        self.calls = []

    async def generate(self, request):
        ordinal = len(self.calls)
        assert self.repository.generated[ordinal].status == "generating"
        assert request.output_size == "1536x1024"
        self.calls.append(request)
        rng = Random(ordinal + 13)
        source = Image.new("RGB", (16, 12))
        source.putdata(
            [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(192)]
        )
        body = BytesIO()
        source.resize((1536, 1024)).save(body, format="JPEG", quality=85)
        return ImageGenerationResult(
            provider="comfly",
            model="gpt-image-2",
            request_fingerprint=request.request_fingerprint,
            provider_task_id=None,
            provider_upload_id=None,
            image_bytes=body.getvalue(),
            media_type="image/jpeg",
            width=1536,
            height=1024,
            attempts=1,
        )


class _Auditor:
    def __init__(self, repository, fail_at=None):
        self.repository = repository
        self.calls = []
        self.fail_at = fail_at

    async def audit(self, request):
        assert len(self.repository.generated) == 5
        assert all(item.status == "ready" for item in self.repository.generated.values())
        assert any(
            item.status == "calling"
            and item.subject.request_fingerprint == request.request_fingerprint
            for item in self.repository.audits.values()
        )
        self.calls.append(request)
        if len(self.calls) - 1 == self.fail_at:
            raise TimeoutError("synthetic outcome unknown")
        return ImageQualityAuditResult(
            accepted=True,
            provider="openai-compatible",
            model="glm-5v-turbo",
            request_fingerprint=request.request_fingerprint,
        )


def _components(*, fail_at=None):
    repo = _Repository()
    catalog = _ApprovedCatalog()
    catalog.candidates = catalog.candidates[:3]
    store = _Store()
    generator = _Generator(repo)
    auditor = _Auditor(repo, fail_at)
    executor = OfficialAccountLocalExecutor(
        repository=repo,
        fixture_generator=DeterministicFakeOfficialAccountArticleGenerator(),
        fixture_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
        live_generator=_TextGenerator(),
        live_auditor=_TextAuditor(),
        media_adapter=LocalOfficialAccountMediaAdapter(catalog),
        draft_adapter=LocalOfficialAccountDraftAdapter(),
        lease_seconds=600,
        heartbeat_seconds=30,
        max_attempts=3,
        retry_base_seconds=0,
        generation_max_output_tokens=8192,
        audit_max_output_tokens=1024,
        catalog_media_provider=catalog,
        generated_visual_store=store,
        strict_image_generator=generator,
        strict_image_quality_auditor=auditor,
    )
    return repo, store, generator, auditor, executor


@pytest.mark.asyncio
async def test_real_strict_executor_five_native_scenes_six_final_audits_and_zero_replay():
    repo, store, generator, auditor, executor = _components()
    assert await executor.execute_next("strict-offline")
    assert repo.failure is None
    assert repo.draft is not None
    assert len(generator.calls) == 5 and len(auditor.calls) == 6
    assert len({request.references[0].asset_id for request in generator.calls}) == 3
    assert repo.article.article.media_selection.reference_policy_version is not None
    for request in auditor.calls:
        assert sha256(request.image_bytes).hexdigest() in store.images
    cover = auditor.calls[-1].image_bytes
    with Image.open(BytesIO(cover)) as image:
        assert image.size == (1175, 500)
    assert len(cover) < 65536
    assert await executor.execute_next("strict-repeat") is False
    assert len(generator.calls) == 5 and len(auditor.calls) == 6


@pytest.mark.asyncio
async def test_audit_unknown_preserves_five_paid_siblings_and_never_resubmits():
    repo, _store, generator, auditor, executor = _components(fail_at=2)
    assert await executor.execute_next("strict-offline")
    assert repo.draft is None
    assert len(generator.calls) == 5 and len(auditor.calls) == 3
    assert all(item.status == "ready" for item in repo.generated.values())
    assert [item.status for item in repo.audits.values()] == [
        "accepted",
        "accepted",
        "result_unknown",
    ]
    repo.claimed = False
    assert await executor.execute_next("strict-recovery")
    assert len(generator.calls) == 5 and len(auditor.calls) == 3
    assert repo.draft is None


@pytest.mark.asyncio
async def test_response_then_db_failure_keeps_calling_intent_without_paid_replay():
    repo, _store, generator, auditor, executor = _components()
    repo.fail_completion = True
    assert await executor.execute_next("strict-offline")
    assert len(auditor.calls) == 1 and next(iter(repo.audits.values())).status == "calling"
    assert all(item.status == "ready" for item in repo.generated.values())
    repo.fail_completion = False
    repo.claimed = False
    assert await executor.execute_next("strict-recovery")
    assert len(generator.calls) == 5 and len(auditor.calls) == 1 and repo.draft is None


@pytest.mark.asyncio
async def test_heartbeat_failure_prevents_next_paid_call_and_keeps_first_result():
    repo, _store, generator, auditor, executor = _components()
    started, lost = asyncio.Event(), asyncio.Event()
    original_generate = generator.generate

    async def generate(request):
        result = await original_generate(request)
        started.set()
        await lost.wait()
        return result

    async def heartbeat(**kwargs):
        await started.wait()
        lost.set()
        raise RuntimeError("synthetic heartbeat failure")

    generator.generate = generate
    repo.heartbeat = heartbeat
    executor._heartbeat_seconds = 0.001
    assert await executor.execute_next("strict-heartbeat")
    assert len(generator.calls) == 1 and len(auditor.calls) == 0
    assert repo.generated[0].status == "ready" and repo.draft is None


@pytest.mark.asyncio
async def test_generation_response_then_db_failure_keeps_blob_and_never_replays():
    repo, store, generator, auditor, executor = _components()
    repo.fail_generation_completion = True
    assert await executor.execute_next("strict-completion")
    assert len(generator.calls) == 1 and len(store.images) == 1
    assert repo.generated[0].status == "generating"
    repo.fail_generation_completion = False
    repo.claimed = False
    assert await executor.execute_next("strict-completion-recovery")
    assert len(generator.calls) == 1 and len(auditor.calls) == 0 and repo.draft is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("ordinal", True),
        ("width", 1536.0),
        ("role", "context"),
        ("run_id", "invalid"),
        ("model", "other"),
    ],
)
def test_strict_subject_json_decoder_rejects_coercion_and_unknown_identity(field, value):
    from app.application.ports.official_account_strict_visual import StrictVisualAuditSubject
    from app.infrastructure.db.official_account_strict_visual import (
        _subject_from_payload,
        _subject_payload,
    )

    subject = StrictVisualAuditSubject(
        run_id=uuid4(),
        article_version_id=uuid4(),
        render_version_id=uuid4(),
        role="body",
        ordinal=0,
        generated_visual_id=uuid4(),
        generated_plan_request_fingerprint="a" * 64,
        reference_asset_ref="a" * 16,
        reference_publication_sha256="b" * 64,
        publication_sha256="c" * 64,
        upload_sha256="d" * 64,
        upload_policy_version="official-account-upload-body-v1",
        media_type="image/jpeg",
        byte_size=100,
        width=1536,
        height=1024,
        criteria_fingerprint="e" * 64,
        perceptual_hash="0" * 16,
        catalog_perceptual_hashes=("1" * 16,),
    )
    payload = _subject_payload(subject)
    assert _subject_from_payload(payload) == subject
    payload[field] = value
    with pytest.raises(ValueError):
        _subject_from_payload(payload)
