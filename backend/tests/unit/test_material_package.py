from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from app.api.v1.routes import material_packages as material_package_routes
from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageReference,
)
from app.application.ports.image_validation import (
    ImageQualityAuditRequest,
    ImageQualityAuditResult,
    ImageTextRecognitionRequest,
    ImageTextRecognitionResult,
)
from app.application.services.material_package import (
    AcceptedMaterialInput,
    ClaimedMaterialPackage,
    MaterialPackageExecutor,
    MaterialPackageResult,
    ReservedVisualReference,
    _claim_prompt,
    _expected_visual_text,
    _prepare_image_input,
    _provider_output_recovery_error_code,
    _provider_request_fingerprint,
    _validate_controlled_claim_identity,
    enqueue_material_package,
    retry_material_package_image,
)
from app.core.config import Settings
from app.core.errors import (
    ConflictError,
    ImageOutputValidationError,
    ImageProviderRejectedError,
    ImageProviderTimeoutError,
    InvalidProviderOutputError,
    ProviderRejectedError,
)
from app.domain.content_slots import ContentSlot
from app.domain.image_similarity import ImageSimilarityResult, evaluate_image_similarity
from app.domain.visual_brief import (
    CONTROLLED_VISUAL_BRIEF_VERSION,
    AcceptedVisualContext,
    VisualBrief,
    build_visual_brief,
)
from app.domain.visual_diversity import build_visual_plan_bundle
from app.infrastructure.ai.image_generation import OpenAICompatibleImageGenerator, _solid_png
from app.infrastructure.db.models import ImageArtifactModel, MaterialPackageModel
from app.infrastructure.storage.minio_image_store import ImageObjectDescriptor
from app.schemas.material_package import (
    MaterialPackageCreateRequest,
    MaterialPackageDownloadResponse,
)
from fastapi import Response
from pydantic import SecretStr


def _package_and_image() -> tuple[SimpleNamespace, SimpleNamespace]:
    package_id = uuid4()
    image_id = uuid4()
    package = SimpleNamespace(
        id=package_id,
        run_id=uuid4(),
        image_artifact_id=image_id,
        package_version=1,
        status="queued",
        review_status="pending",
        topic_snapshot={
            "business_date": "2099-01-01",
            "title": "受控选题",
            "score": {"explanation": {"reason": "bounded"}},
        },
        copy_snapshot={"draft_version_id": str(uuid4()), "copywriting": "正文"},
        source_snapshot=[{"source_url": "https://example.test/source", "source_tier": "A"}],
        brand_snapshot=[{"brand_chunk_id": str(uuid4()), "document_title": "品牌规范"}],
        validation_snapshot={"passed": True, "issues": []},
        audit_snapshot={"accepted": True, "issues": []},
        version_snapshot={"package_schema_version": "material-package-v2"},
        review_note=None,
        reviewed_at=None,
        created_at=datetime.now(UTC),
    )
    image = SimpleNamespace(
        id=image_id,
        status="queued",
        provider="fake",
        model="gpt-image-2",
        request_fingerprint="a" * 64,
        width=None,
        height=None,
        media_type=None,
        byte_size=None,
        sha256=None,
        storage_metadata={
            "access": "private",
            "immutable": True,
            "content_addressed": True,
        },
        error_code=None,
    )
    return package, image


class _SequenceSession:
    def __init__(self, scalar_results: list[object | None]) -> None:
        self._scalar_results = scalar_results
        self.added: list[object] = []

    async def __aenter__(self) -> _SequenceSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def scalar(self, _statement: object) -> object | None:
        return self._scalar_results.pop(0)

    def add_all(self, values: tuple[object, ...]) -> None:
        self.added.extend(values)

    async def commit(self) -> None:
        raise AssertionError("conflicting reservations must not commit")


class _SequenceSessionFactory:
    def __init__(self, session: _SequenceSession) -> None:
        self.session = session

    def __call__(self) -> _SequenceSession:
        return self.session


class _ClaimResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _ReadyPackageSession:
    def __init__(self, runs: list[object]) -> None:
        self._runs = runs

    async def __aenter__(self) -> _ReadyPackageSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def scalars(self, _statement: object) -> _ClaimResult:
        return _ClaimResult(self._runs)


class _ClaimSession:
    def __init__(self, *, exhausted: list[object], scalar_results: list[object | None]) -> None:
        self._exhausted = exhausted
        self._scalar_results = scalar_results
        self.commits = 0

    async def __aenter__(self) -> _ClaimSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def scalars(self, _statement: object) -> _ClaimResult:
        return _ClaimResult(self._exhausted)

    async def scalar(self, _statement: object) -> object | None:
        return self._scalar_results.pop(0)

    async def get(self, _model: object, _entity_id: object) -> object | None:
        raise AssertionError("an exhausted material image must not be claimed")

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_enqueue_rejects_a_different_request_for_the_same_accepted_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = SimpleNamespace(id=uuid4())
    draft = SimpleNamespace(id=uuid4())
    accepted = AcceptedMaterialInput(
        run=run,  # type: ignore[arg-type]
        draft=draft,  # type: ignore[arg-type]
        prompt="面向家长的科学探索插画",
        topic_snapshot={},
        copy_snapshot={},
        source_snapshot=[],
        brand_snapshot=[],
        validation_snapshot={},
        audit_snapshot={},
        version_snapshot={},
    )
    session = _SequenceSession([None, None, SimpleNamespace()])
    monkeypatch.setattr(
        "app.application.services.material_package._load_accepted_input",
        lambda _factory, _run_id: _resolved(accepted),
    )

    with pytest.raises(ConflictError, match="different image request"):
        await enqueue_material_package(
            session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
            run_id=run.id,
            reference_asset=None,
            image_provider="fake",
            image_model="gpt-image-2",
        )
    assert session.added == []


@pytest.mark.asyncio
async def test_reconcile_ready_packages_reserves_an_image_for_an_accepted_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    package, image = _package_and_image()
    calls: list[dict[str, object]] = []

    async def fake_enqueue(**kwargs: object) -> MaterialPackageResult:
        calls.append(kwargs)
        return MaterialPackageResult(package=package, image=image)

    monkeypatch.setattr(
        "app.application.services.material_package.enqueue_material_package", fake_enqueue
    )
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(  # type: ignore[arg-type]
            _ReadyPackageSession([SimpleNamespace(id=run_id)])  # type: ignore[arg-type]
        ),
        image_generator=object(),  # type: ignore[arg-type]
        image_store=object(),  # type: ignore[arg-type]
        settings=Settings(image_enabled=True, image_provider_mode="fake"),
        reference_asset="private/reference.png",
    )

    assert await executor.reconcile_ready_packages() == 1
    assert calls[0]["run_id"] == run_id
    assert calls[0]["image_provider"] == "fake"


@pytest.mark.asyncio
async def test_reconcile_ready_packages_tolerates_an_idempotency_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def conflicting_enqueue(**_kwargs: object) -> MaterialPackageResult:
        raise ConflictError("image reservation already exists")

    monkeypatch.setattr(
        "app.application.services.material_package.enqueue_material_package",
        conflicting_enqueue,
    )
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(  # type: ignore[arg-type]
            _ReadyPackageSession([SimpleNamespace(id=uuid4())])  # type: ignore[arg-type]
        ),
        image_generator=object(),  # type: ignore[arg-type]
        image_store=object(),  # type: ignore[arg-type]
        settings=Settings(image_enabled=True, image_provider_mode="fake"),
        reference_asset=None,
    )

    assert await executor.reconcile_ready_packages() == 0


@pytest.mark.asyncio
async def test_material_worker_terminalizes_an_exhausted_expired_lease() -> None:
    image = SimpleNamespace(
        id=uuid4(),
        status="running",
        provider="disabled",
        model="gpt-image-2",
        attempt_count=1,
        available_at=datetime.now(UTC),
        lease_owner="old-worker",
        lease_token=uuid4(),
        lease_expires_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
        error_code=None,
        completed_at=None,
    )
    package = SimpleNamespace(id=uuid4(), image_artifact_id=image.id, status="queued")
    session = _ClaimSession(exhausted=[image], scalar_results=[package, None])
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
        image_generator=object(),  # type: ignore[arg-type]
        image_store=object(),  # type: ignore[arg-type]
        settings=Settings(image_max_attempts=1),
        reference_asset=None,
    )

    claimed = await executor._claim("material-worker")

    assert claimed is None
    assert image.status == "failed"
    assert image.error_code == "lease_expired"
    assert image.lease_token is None
    assert image.completed_at is not None
    assert package.status == "failed"
    assert session.commits == 1


async def _resolved(value: AcceptedMaterialInput) -> AcceptedMaterialInput:
    return value


@pytest.mark.asyncio
async def test_post_material_package_only_reserves_and_does_not_call_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, image = _package_and_image()
    calls: list[dict[str, object]] = []

    async def fake_enqueue(**kwargs: object) -> MaterialPackageResult:
        calls.append(kwargs)
        return MaterialPackageResult(package=package, image=image)

    monkeypatch.setattr(material_package_routes, "enqueue_material_package", fake_enqueue)
    settings = SimpleNamespace(
        content_enabled=True,
        image_enabled=True,
        image_provider_mode="fake",
        image_reference_asset=None,
        image_prompt_version="image-prompt-v1",
        image_pipeline_version="image-pipeline-v1",
        image_model="gpt-image-2",
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings, session_factory=object()))
    )
    response = Response()

    projected = await material_package_routes.generate_material_package(
        MaterialPackageCreateRequest(copy_generation_run_id=package.run_id),
        request,
        response,
    )

    assert projected.status == "queued"
    assert image.status == "queued"
    assert len(calls) == 1
    assert "image_generator" not in calls[0]
    assert response.headers["location"] == f"/api/v1/material-packages/{package.id}"


@pytest.mark.asyncio
async def test_material_package_download_is_structured_and_safe() -> None:
    package, image = _package_and_image()

    class FakeSession:
        async def get(self, model: object, entity_id: object) -> object | None:
            if model is MaterialPackageModel and entity_id == package.id:
                return package
            if model is ImageArtifactModel and entity_id == image.id:
                return image
            return None

    response = Response()
    result = await material_package_routes.download_material_package(
        package.id,
        response,
        FakeSession(),  # type: ignore[arg-type]
    )

    assert isinstance(result, MaterialPackageDownloadResponse)
    payload = result.model_dump(mode="json", by_alias=True)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert payload["brand_bindings"]
    assert payload["validation"]["passed"] is True
    assert payload["audit"]["accepted"] is True
    assert payload["image"]["request_fingerprint"] == "a" * 64
    assert payload["image"]["download_url"] is None
    assert payload["download_url"] == f"/api/v1/material-packages/{package.id}/download"
    assert "object_key" not in encoded
    assert "bucket" not in encoded
    assert "signed" not in encoded.lower()
    assert response.headers["content-disposition"].endswith('.json"')


def test_material_package_image_projection_exposes_only_relative_download_url() -> None:
    package, image = _package_and_image()
    image.status = "succeeded"
    image.width = 1024
    image.height = 1024
    image.media_type = "image/png"
    image.byte_size = 15
    image.sha256 = "a" * 64

    result = material_package_routes._detail_response(package, image)
    payload = result.model_dump(mode="json", by_alias=True)

    assert payload["image"]["download_url"] == f"/api/v1/material-packages/{package.id}/image"
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "private-test-bucket" not in encoded
    assert "generated-images/" not in encoded


@pytest.mark.parametrize(
    "initial_error_code",
    ("image_provider_rejected", "image_output_invalid"),
)
def test_material_package_image_projection_defaults_and_redacts_fallback_provenance(
    initial_error_code: str,
) -> None:
    package, image = _package_and_image()
    image.provider_rejection_retry_count = 1
    package.version_snapshot["image"] = {
        "fallback": {
            "version": "image-fallback-v1",
            "state": "brand_catalog",
            "initial_error_code": initial_error_code,
            "primary_provider": "fake",
            "primary_model": "gpt-image-2",
            "asset": {
                "asset_id": "asset-1",
                "filename": "/private/brand/asset.png",
                "sha256": "a" * 64,
                "role": "action_reference",
                "selection_reason": "https://private.example.test/object",
                "fallback": False,
            },
        }
    }

    payload = material_package_routes._detail_response(package, image).model_dump(mode="json")

    assert payload["image"]["fallback"] == {
        "version": "image-fallback-v1",
        "state": "brand_catalog",
        "provider_rejection_retry_count": 1,
        "initial_error_code": initial_error_code,
        "primary_provider": "fake",
        "primary_model": "gpt-image-2",
        "asset": None,
    }
    assert "private.example.test" not in json.dumps(payload)


def test_material_package_projects_safe_second_plan_diversity_warning() -> None:
    package, image = _package_and_image()
    brief = build_visual_brief(
        AcceptedVisualContext(topic_title="人工智能教育"),
        version="visual-brief-v2-controlled-diversity",
    )
    plans = build_visual_plan_bundle(
        category=brief.category,
        business_date=date(2026, 8, 15),
        content_slot=ContentSlot.EVENING,
        stable_seed="api-warning",
    )
    package.version_snapshot = {
        "package_schema_version": "material-package-v2",
        "image": {
            "prompt_version": "image-prompt-v3-controlled-diversity",
            "pipeline_version": "image-pipeline-v3-controlled-diversity",
            "visual_brief_version": "visual-brief-v2-controlled-diversity",
            "diversity_policy_version": "visual-diversity-policy-v1",
            "similarity_policy_version": "image-similarity-policy-v1",
            "perceptual_hash_version": "image-perceptual-hash-v1",
            "catalog_version": "catalog-v1",
            "selector_version": "brand-visual-selector-v2-novelty",
            "history_digest": "private-history-digest",
            "plans": [
                {
                    "attempt_ordinal": ordinal,
                    "plan": plan.as_metadata(),
                    "prompt_fingerprint": f"private-prompt-{ordinal}",
                    "reference_fingerprint": f"private-reference-{ordinal}",
                    "reference_mode": "single_reference",
                    "references": [
                        {
                            "role": "identity_reference",
                            "asset_id": f"approved-{ordinal}",
                            "filename": f"approved-{ordinal}.png",
                            "sha256": f"{ordinal:064x}",
                            "selection_reason": "approved identity coverage",
                            "fallback": False,
                        }
                    ],
                }
                for ordinal, plan in ((1, plans.primary), (2, plans.alternate))
            ],
            "diversity": {
                "near_duplicate": True,
                "exact_duplicate": False,
                "nearest_distance": 3,
                "threshold": 6,
                "candidate_count": 12,
                "decision": "accepted_with_warning",
            },
        },
    }
    image.visual_brief_snapshot = {
        **brief.as_metadata(),
        "controlled_plan": plans.alternate.as_metadata(),
    }
    image.reference_mode = "single_reference"
    image.repair_count = 0
    image.provider_rejection_retry_count = 0
    image.diversity_retry_count = 1
    image.active_plan_ordinal = 2
    image.final_plan_ordinal = 2
    image.diversity_warning = "near_duplicate_after_retry"
    image.validation_snapshot = {}
    image.audit_snapshot = {}

    payload = material_package_routes._detail_response(package, image).model_dump(mode="json")

    assert payload["image"]["diversity"]["plan"]["scene"] == plans.alternate.scene.value
    assert payload["image"]["diversity"]["retry_count"] == 1
    assert payload["image"]["diversity"]["warning"] is True
    assert payload["image"]["diversity"]["decision"] == "accepted_with_warning"
    assert payload["image"]["references"][0]["asset_id"] == "approved-2"
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "private-history-digest" not in encoded
    assert "private-prompt" not in encoded
    assert "private-reference" not in encoded

    package.version_snapshot["image"]["diversity"] = {
        "near_duplicate": False,
        "exact_duplicate": False,
        "nearest_distance": 15,
        "threshold": 6,
        "candidate_count": 12,
        "decision": "accepted",
    }
    image.diversity_retry_count = 0
    image.active_plan_ordinal = 1
    image.final_plan_ordinal = 1
    image.diversity_warning = None
    distinct = material_package_routes._detail_response(package, image).model_dump(mode="json")
    assert distinct["image"]["diversity"]["plan"]["scene"] == plans.primary.scene.value
    assert distinct["image"]["diversity"]["retry_count"] == 0
    assert distinct["image"]["diversity"]["warning"] is False
    assert distinct["image"]["diversity"]["decision"] == "accepted"

    image.diversity_retry_count = 1
    image.active_plan_ordinal = 2
    image.final_plan_ordinal = 2
    repaired = material_package_routes._detail_response(package, image).model_dump(mode="json")
    assert repaired["image"]["diversity"]["plan"]["scene"] == plans.alternate.scene.value
    assert repaired["image"]["diversity"]["retry_count"] == 1
    assert repaired["image"]["diversity"]["warning"] is False


def _claimed_material_package(
    *,
    eligible: bool = True,
    repair_count: int = 0,
    provider_rejection_retry_count: int = 0,
    provider_output_recovery_error_code: str | None = None,
    references: tuple[ReservedVisualReference, ...] = (),
    visual_brief: VisualBrief | None = None,
) -> ClaimedMaterialPackage:
    return ClaimedMaterialPackage(
        package_id=uuid4(),
        image_id=uuid4(),
        run_id=uuid4(),
        draft_version_id=uuid4(),
        request_fingerprint="b" * 64,
        provider="fake",
        model="gpt-image-2",
        prompt="面向家长的科学探索插画",
        reference_sha256=references[0].sha256 if references else None,
        lease_token=uuid4(),
        attempt_number=1,
        eligible=eligible,
        references=references,
        repair_count=repair_count,
        provider_rejection_retry_count=provider_rejection_retry_count,
        provider_output_recovery_error_code=provider_output_recovery_error_code,  # type: ignore[arg-type]
        visual_brief=visual_brief,
    )


def test_controlled_alternate_recovery_fingerprints_remain_distinct() -> None:
    plan = build_visual_plan_bundle(
        category=build_visual_brief(
            AcceptedVisualContext(topic_title="机器人教育"),
            version="visual-brief-v2-controlled-diversity",
        ).category,
        business_date=date(2026, 8, 15),
        content_slot=ContentSlot.NOON,
        stable_seed="alternate-recovery",
    ).alternate
    base = _claimed_material_package()
    alternate = replace(
        base,
        prompt="controlled alternate prompt",
        diversity_retry_count=1,
        active_plan_ordinal=2,
        controlled_plan=plan,
        prompt_fingerprint="d" * 64,
    )
    repaired = replace(
        alternate,
        prompt="controlled alternate repair prompt",
        repair_count=1,
    )
    neutralized = replace(
        alternate,
        prompt="controlled alternate neutralized prompt",
        provider_rejection_retry_count=1,
        provider_output_recovery_error_code="image_provider_rejected",
    )
    representation_recovery = replace(
        alternate,
        provider_rejection_retry_count=1,
        provider_output_recovery_error_code="image_output_invalid",
    )

    fingerprints = {
        _provider_request_fingerprint(alternate),
        _provider_request_fingerprint(repaired),
        _provider_request_fingerprint(neutralized),
        _provider_request_fingerprint(representation_recovery),
    }
    assert None not in fingerprints
    assert len(fingerprints) == 4


def test_controlled_alternate_provider_recovery_keeps_reserved_plan() -> None:
    package, image = _package_and_image()
    package.topic_snapshot["title"] = "人工智能教育"
    plan = build_visual_plan_bundle(
        category=build_visual_brief(
            AcceptedVisualContext(topic_title="人工智能教育"),
            version="visual-brief-v2-controlled-diversity",
        ).category,
        business_date=date(2026, 8, 15),
        content_slot=ContentSlot.EVENING,
        stable_seed="alternate-provider-recovery",
    ).alternate
    image.reference_mode = "single_reference"
    image.diversity_policy_version = "visual-diversity-policy-v1"
    image.provider_rejection_retry_count = 1
    image.diversity_retry_count = 1
    image.prompt_version = "image-prompt-v3-controlled-diversity"
    image.pipeline_version = "image-pipeline-v3-controlled-diversity"
    image.visual_brief_snapshot = {"version": "visual-brief-v2-controlled-diversity"}
    draft = SimpleNamespace(
        copywriting="不应进入提示词的家长文案",
        image_prompt="不应复用的原始提示词",
    )

    prompt, snapshot, _brief = _claim_prompt(
        package=package,
        draft=draft,
        image=image,
        references=(),
        controlled_plan=plan,
    )

    assert "Recovery prompt version: image-provider-rejection-retry-v1" in prompt
    assert "Controlled composition:" in prompt
    assert "Controlled camera:" in prompt
    assert "不应进入提示词" not in prompt
    assert "不应复用" not in prompt
    assert snapshot is not None
    assert snapshot["controlled_plan"]["fingerprint"] == plan.fingerprint


def test_representation_recovery_preserves_controlled_prompt_and_plan() -> None:
    package, image = _package_and_image()
    package.topic_snapshot["title"] = "人工智能教育"
    plan = build_visual_plan_bundle(
        category=build_visual_brief(
            AcceptedVisualContext(topic_title="人工智能教育"),
            version="visual-brief-v2-controlled-diversity",
        ).category,
        business_date=date(2026, 8, 17),
        content_slot=ContentSlot.NOON,
        stable_seed="representation-recovery",
    ).primary
    image.reference_mode = "single_reference"
    image.diversity_policy_version = "visual-diversity-policy-v1"
    image.provider_rejection_retry_count = 0
    image.prompt_version = "image-prompt-v3-controlled-diversity"
    image.pipeline_version = "image-pipeline-v3-controlled-diversity"
    image.visual_brief_snapshot = {"version": "visual-brief-v2-controlled-diversity"}
    draft = SimpleNamespace(copywriting="家长文案", image_prompt="受控原始提示词")

    original_prompt, original_snapshot, _ = _claim_prompt(
        package=package,
        draft=draft,
        image=image,
        references=(),
        controlled_plan=plan,
    )
    image.provider_rejection_retry_count = 1
    package.version_snapshot["image"] = {
        "fallback": {
            "state": "neutralized_retry",
            "provider_rejection_retry_count": 1,
            "initial_error_code": "image_output_invalid",
        }
    }
    recovery_prompt, recovery_snapshot, _ = _claim_prompt(
        package=package,
        draft=draft,
        image=image,
        references=(),
        controlled_plan=plan,
    )

    assert recovery_prompt == original_prompt
    assert recovery_snapshot == original_snapshot
    assert recovery_snapshot is not None
    assert recovery_snapshot["controlled_plan"]["fingerprint"] == plan.fingerprint
    assert _provider_output_recovery_error_code(package, image) == "image_output_invalid"


def test_legacy_recovery_snapshot_defaults_to_provider_rejection_neutralization() -> None:
    package, image = _package_and_image()
    image.provider_rejection_retry_count = 1

    assert _provider_output_recovery_error_code(package, image) == "image_provider_rejected"


def test_controlled_visual_ocr_allowlist_is_exactly_signature_title_subtitle() -> None:
    brief = build_visual_brief(
        AcceptedVisualContext(topic_title="人工智能教育"),
        version="visual-brief-v2-controlled-diversity",
    )

    assert _expected_visual_text(brief) == (
        "赛先生科学",
        "人工智能",
        "理解智能如何学习与反馈",
    )


def test_controlled_claim_rejects_snapshot_fingerprint_drift() -> None:
    brief = build_visual_brief(
        AcceptedVisualContext(topic_title="人工智能教育"),
        version="visual-brief-v2-controlled-diversity",
    )
    plan = build_visual_plan_bundle(
        category=brief.category,
        business_date=date(2026, 8, 15),
        content_slot=ContentSlot.NOON,
        stable_seed="claim-integrity",
    ).primary
    image = SimpleNamespace(
        prompt_version="image-prompt-v3-controlled-diversity",
        pipeline_version="image-pipeline-v3-controlled-diversity",
    )
    reservation = SimpleNamespace(
        plan_fingerprint="0" * 64,
        selector_version="brand-visual-selector-v2-novelty",
        reference_fingerprint="0" * 64,
        prompt_fingerprint="0" * 64,
    )

    with pytest.raises(ValueError, match="plan fingerprint"):
        _validate_controlled_claim_identity(
            reservation=reservation,
            image=image,
            plan=plan,
            brief=brief,
            references=(),
        )


class _RecordingImageGenerator:
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[ImageGenerationRequest] = []

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        self.calls += 1
        self.requests.append(request)
        return ImageGenerationResult(
            provider="fake",
            model="gpt-image-2",
            request_fingerprint=request.request_fingerprint,
            provider_task_id=None,
            provider_upload_id=None,
            image_bytes=_solid_png("material-package-worker", "generated-image"),
            media_type="image/png",
            width=1024,
            height=1024,
            attempts=1,
        )


class _RejectingImageGenerator:
    def __init__(self, error: ImageProviderRejectedError | None = None) -> None:
        self.calls = 0
        self._error = error or ImageProviderRejectedError()

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        del request
        self.calls += 1
        raise self._error


class _InvalidOutputImageGenerator:
    def __init__(self, reason: str = "image_download_content_type_invalid") -> None:
        self.calls = 0
        self.reason = reason

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        del request
        self.calls += 1
        raise ImageOutputValidationError(self.reason)


class _RecordingImageStore:
    def __init__(self) -> None:
        self.calls = 0

    async def put_immutable(
        self, body: bytes, *, media_type: str = "image/png"
    ) -> ImageObjectDescriptor:
        self.calls += 1
        return ImageObjectDescriptor(
            bucket="private-test-bucket",
            object_key="generated-images/sha256/aa/" + "a" * 64 + ".png",
            media_type=media_type,
            byte_size=len(body),
            sha256="a" * 64,
        )


class _FailingImageStore:
    def __init__(self) -> None:
        self.calls = 0

    async def put_immutable(
        self, body: bytes, *, media_type: str = "image/png"
    ) -> ImageObjectDescriptor:
        del body, media_type
        self.calls += 1
        raise ConflictError("private image storage unavailable")


class _QualityAttemptSession:
    def __init__(self, image: SimpleNamespace, package: SimpleNamespace) -> None:
        self.image = image
        self.package = package
        self.commits = 0

    async def __aenter__(self) -> _QualityAttemptSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def scalar(self, _statement: object) -> SimpleNamespace:
        return self.image

    async def get(self, _model: object, _entity_id: object) -> SimpleNamespace:
        return self.package

    async def commit(self) -> None:
        self.commits += 1


class _RetrySession:
    def __init__(self, package: SimpleNamespace, image: SimpleNamespace) -> None:
        self._results = [package, image]
        self.commits = 0

    async def scalar(self, _statement: object) -> SimpleNamespace | None:
        return self._results.pop(0) if self._results else None

    async def commit(self) -> None:
        self.commits += 1


class _RecordingImageTextRecognizer:
    def __init__(self, recognized_lines: tuple[str, ...] | None = None) -> None:
        self._recognized_lines = recognized_lines
        self.requests: list[ImageTextRecognitionRequest] = []

    async def recognize(self, request: ImageTextRecognitionRequest) -> ImageTextRecognitionResult:
        self.requests.append(request)
        return ImageTextRecognitionResult(
            recognized_lines=self._recognized_lines or request.expected_text,
            provider="fake-ocr",
            model="ocr-v1",
            request_fingerprint=request.request_fingerprint,
        )


class _RejectingImageTextRecognizer:
    def __init__(self) -> None:
        self.requests: list[ImageTextRecognitionRequest] = []

    async def recognize(self, request: ImageTextRecognitionRequest) -> ImageTextRecognitionResult:
        self.requests.append(request)
        raise ProviderRejectedError()


class _InvalidTextImageTextRecognizer:
    def __init__(self, issue_codes: tuple[str, ...]) -> None:
        self._issue_codes = issue_codes
        self.requests: list[ImageTextRecognitionRequest] = []

    async def recognize(self, request: ImageTextRecognitionRequest) -> ImageTextRecognitionResult:
        self.requests.append(request)
        raise InvalidProviderOutputError(self._issue_codes)


class _RecordingImageQualityAuditor:
    def __init__(self) -> None:
        self.requests: list[ImageQualityAuditRequest] = []

    async def audit(self, request: ImageQualityAuditRequest) -> ImageQualityAuditResult:
        self.requests.append(request)
        return ImageQualityAuditResult(
            accepted=True,
            provider="fake-auditor",
            model="quality-v1",
            request_fingerprint=request.request_fingerprint,
        )


def _quality_visual_brief() -> VisualBrief:
    return build_visual_brief(
        AcceptedVisualContext(
            topic_title="机器人如何学会调整动作",
            topic_summary="从尝试中学习",
            copywriting="家长能看懂的正文",
        )
    )


def _quality_attempt_state(
    claimed: ClaimedMaterialPackage,
) -> tuple[SimpleNamespace, SimpleNamespace, _QualityAttemptSession]:
    now = datetime.now(UTC)
    image = SimpleNamespace(
        id=claimed.image_id,
        status="running",
        provider=claimed.provider,
        model=claimed.model,
        repair_count=claimed.repair_count,
        provider_rejection_retry_count=claimed.provider_rejection_retry_count,
        validation_snapshot={},
        audit_snapshot={},
        error_code=None,
        completed_at=None,
        available_at=now,
        lease_owner="material-worker",
        lease_token=claimed.lease_token,
        lease_expires_at=now,
        heartbeat_at=now,
    )
    package = SimpleNamespace(
        id=claimed.package_id,
        status="queued",
        version_snapshot={},
    )
    return image, package, _QualityAttemptSession(image, package)


@pytest.mark.asyncio
async def test_material_worker_skips_provider_for_non_accepted_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _RecordingImageGenerator()
    executor = MaterialPackageExecutor(
        session_factory=object(),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=object(),  # type: ignore[arg-type]
        settings=Settings(),
        reference_asset=None,
    )
    claimed = _claimed_material_package(eligible=False)

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    monkeypatch.setattr(executor, "_claim", fake_claim)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 0


@pytest.mark.asyncio
async def test_material_worker_persists_one_success_with_private_storage_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _RecordingImageGenerator()
    store = _RecordingImageStore()
    executor = MaterialPackageExecutor(
        session_factory=object(),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=store,  # type: ignore[arg-type]
        settings=Settings(),
        reference_asset=None,
    )
    claimed = _claimed_material_package()
    persisted: list[tuple[ImageGenerationResult, ImageObjectDescriptor]] = []

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    async def fake_persist(
        value: ClaimedMaterialPackage,
        result: ImageGenerationResult,
        descriptor: ImageObjectDescriptor,
        *,
        validation_snapshot: dict[str, object] | None = None,
        audit_snapshot: dict[str, object] | None = None,
    ) -> bool:
        del validation_snapshot, audit_snapshot
        assert value == claimed
        persisted.append((result, descriptor))
        return True

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_persist_success", fake_persist)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert store.calls == 1
    assert len(persisted) == 1
    assert persisted[0][0].request_fingerprint == claimed.request_fingerprint
    assert persisted[0][1].sha256 == "a" * 64


@pytest.mark.asyncio
async def test_controlled_material_worker_skips_disabled_ocr_and_keeps_diversity_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brief = build_visual_brief(
        AcceptedVisualContext(topic_title="人工智能教育"),
        version=CONTROLLED_VISUAL_BRIEF_VERSION,
    )
    plan = build_visual_plan_bundle(
        category=brief.category,
        business_date=date(2026, 8, 18),
        content_slot=ContentSlot.NOON,
        stable_seed="controlled-ocr-disabled",
    ).primary
    claimed = replace(
        _claimed_material_package(visual_brief=brief),
        controlled_plan=plan,
        plan_reservation_id=uuid4(),
        prompt_fingerprint="c" * 64,
    )
    generator = _RecordingImageGenerator()
    recognizer = _RecordingImageTextRecognizer()
    auditor = _RecordingImageQualityAuditor()

    class _IntegrityRecordingImageStore:
        def __init__(self) -> None:
            self.calls = 0

        async def put_immutable(
            self, body: bytes, *, media_type: str = "image/png"
        ) -> ImageObjectDescriptor:
            self.calls += 1
            sha256 = hashlib.sha256(body).hexdigest()
            return ImageObjectDescriptor(
                bucket="private-test-bucket",
                object_key=f"generated-images/sha256/{sha256[:2]}/{sha256}.png",
                media_type=media_type,
                byte_size=len(body),
                sha256=sha256,
            )

    store = _IntegrityRecordingImageStore()
    executor = MaterialPackageExecutor(
        session_factory=object(),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=store,  # type: ignore[arg-type]
        settings=Settings(
            _env_file=None,
            image_enabled=True,
            image_provider_mode="fake",
            image_diversity_enabled=True,
            image_ocr_enabled=False,
            image_quality_audit_enabled=True,
        ),
        reference_asset=None,
        image_text_recognizer=recognizer,
        image_quality_auditor=auditor,
    )
    similarity_calls = 0
    persisted: list[dict[str, object]] = []

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    async def fake_similarity(
        value: ClaimedMaterialPackage,
        *,
        image_bytes: bytes,
    ) -> tuple[bool, ImageSimilarityResult]:
        nonlocal similarity_calls
        assert value == claimed
        assert image_bytes
        similarity_calls += 1
        return True, evaluate_image_similarity(image_bytes, references=())

    async def fake_persist(
        value: ClaimedMaterialPackage,
        result: ImageGenerationResult,
        descriptor: ImageObjectDescriptor,
        *,
        validation_snapshot: dict[str, object] | None = None,
        audit_snapshot: dict[str, object] | None = None,
        similarity_result: ImageSimilarityResult | None = None,
    ) -> bool:
        assert value == claimed
        persisted.append(
            {
                "result": result,
                "descriptor": descriptor,
                "validation": validation_snapshot,
                "audit": audit_snapshot,
                "similarity": similarity_result,
            }
        )
        return True

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_assess_image_similarity", fake_similarity)
    monkeypatch.setattr(executor, "_persist_success", fake_persist)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert recognizer.requests == []
    assert len(auditor.requests) == 1
    assert similarity_calls == 1
    assert store.calls == 1
    assert len(persisted) == 1
    validation = persisted[0]["validation"]
    assert isinstance(validation, dict)
    assert validation["passed"] is True
    assert validation["issue_codes"] == []
    assert validation["media_type"] == "image/png"
    assert validation["width"] == 1024
    assert validation["height"] == 1024
    assert "image_ocr_not_configured" not in json.dumps(validation)
    audit = persisted[0]["audit"]
    assert isinstance(audit, dict)
    assert audit["passed"] is True
    similarity = persisted[0]["similarity"]
    assert isinstance(similarity, ImageSimilarityResult)
    assert similarity.candidate_count == 0
    result = persisted[0]["result"]
    descriptor = persisted[0]["descriptor"]
    assert isinstance(result, ImageGenerationResult)
    assert isinstance(descriptor, ImageObjectDescriptor)
    assert descriptor.byte_size == len(result.image_bytes)
    assert descriptor.sha256 == hashlib.sha256(result.image_bytes).hexdigest()


@pytest.mark.asyncio
async def test_material_worker_provider_rejection_schedules_one_neutralized_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _RejectingImageGenerator()
    executor = MaterialPackageExecutor(
        session_factory=object(),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=object(),  # type: ignore[arg-type]
        settings=Settings(image_max_attempts=1),
        reference_asset=None,
    )
    claimed = _claimed_material_package()
    scheduled: list[ClaimedMaterialPackage] = []
    events: list[tuple[str, dict[str, object]]] = []

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    async def fake_schedule(value: ClaimedMaterialPackage) -> bool:
        scheduled.append(value)
        return True

    class _SafeLogger:
        def warning(self, event: str, **values: object) -> None:
            events.append((event, values))

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_schedule_provider_rejection_retry", fake_schedule)
    monkeypatch.setattr("app.application.services.material_package.logger", _SafeLogger())

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert scheduled == [claimed]
    assert events == [
        (
            "material_package_image_provider_rejected",
            {
                "package_id": str(claimed.package_id),
                "image_id": str(claimed.image_id),
                "provider": "fake",
                "model": "gpt-image-2",
                "attempt": 1,
                "repair_count": 0,
                "provider_rejection_retry_count": 1,
                "next_action": "neutralized_retry",
            },
        )
    ]


@pytest.mark.asyncio
async def test_representation_failure_persists_exactly_one_durable_output_recovery() -> None:
    claimed = _claimed_material_package()
    image, package, session = _quality_attempt_state(claimed)
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
        image_generator=object(),  # type: ignore[arg-type]
        image_store=object(),  # type: ignore[arg-type]
        settings=Settings(),
        reference_asset=None,
    )

    assert await executor._schedule_provider_rejection_retry(
        claimed,
        initial_error_code="image_output_invalid",
        validation_snapshot={"stage": "provider_output", "issue_codes": ["safe-reason"]},
    )
    assert not await executor._schedule_provider_rejection_retry(
        claimed,
        initial_error_code="image_output_invalid",
    )

    assert session.commits == 1
    assert image.status == "queued"
    assert image.provider_rejection_retry_count == 1
    assert image.error_code == "image_output_invalid"
    assert image.validation_snapshot == {
        "stage": "provider_output",
        "issue_codes": ["safe-reason"],
    }
    assert image.lease_token is None
    assert package.status == "queued"
    assert package.version_snapshot["image"]["fallback"] == {
        "version": "image-fallback-v1",
        "state": "neutralized_retry",
        "provider_rejection_retry_count": 1,
        "initial_error_code": "image_output_invalid",
        "primary_provider": "fake",
        "primary_model": "gpt-image-2",
    }


@pytest.mark.asyncio
async def test_material_worker_representation_failure_schedules_safe_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_marker = "PRIVATE-INVALID-REPRESENTATION"
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(
            200,
            request=request,
            json={"data": [{"b64_json": raw_marker}]},
        )

    claimed = _claimed_material_package()
    scheduled: list[tuple[ClaimedMaterialPackage, str]] = []
    events: list[tuple[str, dict[str, object]]] = []

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    async def fake_schedule(
        value: ClaimedMaterialPackage,
        *,
        initial_error_code: str,
        validation_snapshot: dict[str, object],
    ) -> bool:
        assert validation_snapshot["issue_codes"] == ["image_output_representation_invalid"]
        scheduled.append((value, initial_error_code))
        return True

    class _SafeLogger:
        def warning(self, event: str, **values: object) -> None:
            events.append((event, values))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator = OpenAICompatibleImageGenerator(
            client=client,
            base_url="https://ai.comfly.org",
            api_key=SecretStr("test-key"),
            max_attempts=1,
        )
        executor = MaterialPackageExecutor(
            session_factory=object(),  # type: ignore[arg-type]
            image_generator=generator,
            image_store=object(),  # type: ignore[arg-type]
            settings=Settings(image_max_attempts=1),
            reference_asset=None,
        )
        monkeypatch.setattr(executor, "_claim", fake_claim)
        monkeypatch.setattr(executor, "_schedule_provider_rejection_retry", fake_schedule)
        monkeypatch.setattr("app.application.services.material_package.logger", _SafeLogger())

        assert await executor.execute_next("material-worker") is True

    assert provider_calls == 1
    assert scheduled == [(claimed, "image_output_invalid")]
    assert events == [
        (
            "material_package_image_output_recovery",
            {
                "package_id": str(claimed.package_id),
                "image_id": str(claimed.image_id),
                "provider": "fake",
                "model": "gpt-image-2",
                "attempt": 1,
                "repair_count": 0,
                "provider_rejection_retry_count": 1,
                "error_code": "image_output_invalid",
                "reason": "image_output_representation_invalid",
                "next_action": "neutralized_retry",
            },
        )
    ]
    assert raw_marker not in json.dumps(events)


@pytest.mark.asyncio
async def test_material_worker_representation_recovery_success_uses_distinct_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _RecordingImageGenerator()
    store = _RecordingImageStore()
    executor = MaterialPackageExecutor(
        session_factory=object(),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=store,
        settings=Settings(image_max_attempts=1),
        reference_asset=None,
    )
    claimed = _claimed_material_package(
        provider_rejection_retry_count=1,
        provider_output_recovery_error_code="image_output_invalid",
    )
    persisted: list[ImageGenerationResult] = []

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    async def fake_persist(
        value: ClaimedMaterialPackage,
        result: ImageGenerationResult,
        descriptor: ImageObjectDescriptor,
        **_snapshots: object,
    ) -> bool:
        assert value == claimed
        assert descriptor.sha256 == "a" * 64
        persisted.append(result)
        return True

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_persist_success", fake_persist)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert store.calls == 1
    assert len(persisted) == 1
    assert generator.requests[0].prompt == claimed.prompt
    assert generator.requests[0].provider_request_fingerprint is not None
    assert generator.requests[0].provider_request_fingerprint != claimed.request_fingerprint
    assert generator.requests[0].provider_request_fingerprint == _provider_request_fingerprint(
        claimed
    )


@pytest.mark.asyncio
async def test_material_worker_logs_only_safe_provider_rejection_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _RejectingImageGenerator(
        ImageProviderRejectedError(http_status=422, response_kind="other")
    )
    executor = MaterialPackageExecutor(
        session_factory=object(),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=object(),  # type: ignore[arg-type]
        settings=Settings(image_max_attempts=1),
        reference_asset=None,
    )
    claimed = _claimed_material_package()
    events: list[tuple[str, dict[str, object]]] = []

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    async def fake_schedule(_value: ClaimedMaterialPackage) -> bool:
        return True

    class _SafeLogger:
        def warning(self, event: str, **values: object) -> None:
            events.append((event, values))

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_schedule_provider_rejection_retry", fake_schedule)
    monkeypatch.setattr("app.application.services.material_package.logger", _SafeLogger())

    assert await executor.execute_next("material-worker") is True
    assert events[0][0] == "material_package_image_provider_rejected"
    assert events[0][1]["provider_http_status"] == 422
    assert events[0][1]["provider_response_kind"] == "other"
    assert "PRIVATE-COMFLY-RESPONSE" not in json.dumps(events[0][1])


@pytest.mark.asyncio
async def test_material_worker_second_provider_rejection_uses_catalog_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _RejectingImageGenerator()
    executor = MaterialPackageExecutor(
        session_factory=object(),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=object(),  # type: ignore[arg-type]
        settings=Settings(image_max_attempts=1),
        reference_asset=None,
    )
    claimed = _claimed_material_package(provider_rejection_retry_count=1)
    fallbacks: list[ClaimedMaterialPackage] = []

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    async def fake_fallback(
        value: ClaimedMaterialPackage,
        *,
        references: tuple[ImageReference, ...],
        validation_snapshot: dict[str, object],
        audit_snapshot: dict[str, object],
        initial_error_code: str,
    ) -> None:
        assert references == ()
        assert validation_snapshot == {}
        assert audit_snapshot["status"] == "not_configured"
        assert initial_error_code == "image_provider_rejected"
        fallbacks.append(value)

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_persist_catalog_fallback", fake_fallback)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert fallbacks == [claimed]


@pytest.mark.asyncio
async def test_second_representation_failure_uses_catalog_without_a_third_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reserved = ReservedVisualReference(
        role="action_reference",
        asset_id="asset-representation-action",
        filename="representation-action.png",
        sha256="e" * 64,
        selection_reason="representation recovery action match",
        fallback=False,
    )
    claimed = _claimed_material_package(
        provider_rejection_retry_count=1,
        provider_output_recovery_error_code="image_output_invalid",
        references=(reserved,),
    )
    image, package, session = _quality_attempt_state(claimed)
    generator = _InvalidOutputImageGenerator("image_output_representation_invalid")
    store = _RecordingImageStore()
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=store,
        settings=Settings(image_max_attempts=1),
        reference_asset=None,
    )
    reference = ImageReference(
        role=reserved.role,
        asset_id=reserved.asset_id,
        filename=reserved.filename,
        sha256=reserved.sha256,
        image_bytes=_solid_png("representation-fallback", "approved"),
        selection_reason=reserved.selection_reason,
    )

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    async def fake_read_references(
        value: ClaimedMaterialPackage,
    ) -> tuple[ImageReference, ...]:
        assert value == claimed
        return (reference,)

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_read_claimed_references", fake_read_references)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert store.calls == 1
    assert image.status == "succeeded"
    assert image.provider == "fake"
    assert image.model == "gpt-image-2"
    assert package.status == "awaiting_manual_use"
    assert package.version_snapshot["image"]["fallback"]["state"] == "brand_catalog"
    assert (
        package.version_snapshot["image"]["fallback"]["initial_error_code"]
        == "image_output_invalid"
    )


@pytest.mark.parametrize(
    "initial_error_code",
    ("image_provider_rejected", "image_output_invalid"),
)
@pytest.mark.asyncio
async def test_catalog_fallback_stores_a_validated_private_brand_image(
    initial_error_code: str,
) -> None:
    reserved = ReservedVisualReference(
        role="action_reference",
        asset_id="asset-robot-action",
        filename="robot-action.png",
        sha256="b" * 64,
        selection_reason="robotics action match",
        fallback=False,
    )
    claimed = _claimed_material_package(
        provider_rejection_retry_count=1,
        references=(reserved,),
    )
    image, package, session = _quality_attempt_state(claimed)
    store = _RecordingImageStore()
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
        image_generator=object(),  # type: ignore[arg-type]
        image_store=store,
        settings=Settings(),
        reference_asset=None,
    )
    reference = ImageReference(
        role="action_reference",
        asset_id=reserved.asset_id,
        filename=reserved.filename,
        sha256=reserved.sha256,
        image_bytes=_solid_png("catalog-fallback", "robot-action"),
        selection_reason=reserved.selection_reason,
    )

    await executor._persist_catalog_fallback(
        claimed,
        references=(reference,),
        validation_snapshot={},
        audit_snapshot={"status": "not_configured"},
        initial_error_code=initial_error_code,
    )

    assert store.calls == 1
    assert image.status == "succeeded"
    assert image.provider == "fake"
    assert image.model == "gpt-image-2"
    assert image.width == 1024
    assert image.height == 1024
    assert image.audit_snapshot["status"] == "not_applicable"
    assert package.status == "awaiting_manual_use"
    assert package.version_snapshot["image"]["fallback"] == {
        "version": "image-fallback-v1",
        "state": "brand_catalog",
        "provider_rejection_retry_count": 1,
        "initial_error_code": initial_error_code,
        "primary_provider": "fake",
        "primary_model": "gpt-image-2",
        "asset": {
            "asset_id": "asset-robot-action",
            "filename": "robot-action.png",
            "sha256": "b" * 64,
            "role": "action_reference",
            "selection_reason": "robotics action match",
            "fallback": False,
        },
    }


@pytest.mark.asyncio
async def test_catalog_fallback_without_a_reserved_asset_stays_reviewable() -> None:
    claimed = _claimed_material_package(provider_rejection_retry_count=1)
    image, package, session = _quality_attempt_state(claimed)
    store = _RecordingImageStore()
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
        image_generator=object(),  # type: ignore[arg-type]
        image_store=store,
        settings=Settings(),
        reference_asset=None,
    )

    await executor._persist_catalog_fallback(
        claimed,
        references=(),
        validation_snapshot={},
        audit_snapshot={"status": "not_configured"},
    )

    assert store.calls == 0
    assert image.status == "review_required"
    assert image.error_code == "brand_asset_fallback_unavailable"
    assert package.status == "failed"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_catalog_fallback_with_corrupt_reserved_asset_stays_reviewable() -> None:
    reserved = ReservedVisualReference(
        role="action_reference",
        asset_id="asset-corrupt-action",
        filename="corrupt-action.png",
        sha256="c" * 64,
        selection_reason="robotics action match",
        fallback=False,
    )
    claimed = _claimed_material_package(
        provider_rejection_retry_count=1,
        provider_output_recovery_error_code="image_output_invalid",
        references=(reserved,),
    )
    image, package, session = _quality_attempt_state(claimed)
    store = _RecordingImageStore()
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
        image_generator=object(),  # type: ignore[arg-type]
        image_store=store,
        settings=Settings(),
        reference_asset=None,
    )
    reference = ImageReference(
        role=reserved.role,
        asset_id=reserved.asset_id,
        filename=reserved.filename,
        sha256=reserved.sha256,
        image_bytes=b"PRIVATE-CORRUPT-CATALOG-ASSET",
        selection_reason=reserved.selection_reason,
    )

    await executor._persist_catalog_fallback(
        claimed,
        references=(reference,),
        validation_snapshot={"issue_codes": ["image_output_representation_invalid"]},
        audit_snapshot={"status": "not_configured"},
        initial_error_code="image_output_invalid",
    )

    assert store.calls == 0
    assert image.status == "review_required"
    assert image.error_code == "brand_asset_fallback_invalid"
    assert package.status == "failed"
    assert "PRIVATE-CORRUPT-CATALOG-ASSET" not in json.dumps(package.version_snapshot)


@pytest.mark.asyncio
async def test_catalog_fallback_storage_failure_stays_reviewable() -> None:
    reserved = ReservedVisualReference(
        role="action_reference",
        asset_id="asset-storage-action",
        filename="storage-action.png",
        sha256="d" * 64,
        selection_reason="robotics action match",
        fallback=False,
    )
    claimed = _claimed_material_package(
        provider_rejection_retry_count=1,
        provider_output_recovery_error_code="image_output_invalid",
        references=(reserved,),
    )
    image, package, session = _quality_attempt_state(claimed)
    store = _FailingImageStore()
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
        image_generator=object(),  # type: ignore[arg-type]
        image_store=store,
        settings=Settings(),
        reference_asset=None,
    )
    reference = ImageReference(
        role=reserved.role,
        asset_id=reserved.asset_id,
        filename=reserved.filename,
        sha256=reserved.sha256,
        image_bytes=_solid_png("catalog-storage-failure", "approved"),
        selection_reason=reserved.selection_reason,
    )

    await executor._persist_catalog_fallback(
        claimed,
        references=(reference,),
        validation_snapshot={"issue_codes": ["image_output_representation_invalid"]},
        audit_snapshot={"status": "not_configured"},
        initial_error_code="image_output_invalid",
    )

    assert store.calls == 1
    assert image.status == "review_required"
    assert image.error_code == "brand_asset_fallback_storage_failed"
    assert package.status == "failed"


@pytest.mark.parametrize(
    "reason",
    (
        "image_download_url_invalid",
        "image_download_address_invalid",
        "image_download_content_type_invalid",
        "image_download_too_large",
        "image_raster_signature_invalid",
        "image_dimensions_invalid",
    ),
)
@pytest.mark.asyncio
async def test_material_worker_keeps_security_and_raster_validation_failures_terminal(
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    generator = _InvalidOutputImageGenerator(reason)
    executor = MaterialPackageExecutor(
        session_factory=object(),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=object(),  # type: ignore[arg-type]
        settings=Settings(image_max_attempts=1),
        reference_asset=None,
    )
    claimed = _claimed_material_package()
    finished: list[dict[str, object]] = []

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    async def fake_finish(
        value: ClaimedMaterialPackage,
        *,
        error_code: str,
        retryable: bool,
        review_required: bool,
        validation_snapshot: dict[str, object] | None = None,
        audit_snapshot: dict[str, object] | None = None,
    ) -> None:
        del audit_snapshot
        assert value == claimed
        finished.append(
            {
                "error_code": error_code,
                "retryable": retryable,
                "review_required": review_required,
                "validation_snapshot": validation_snapshot,
            }
        )

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_finish_attempt", fake_finish)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert finished == [
        {
            "error_code": "image_output_invalid",
            "retryable": False,
            "review_required": True,
            "validation_snapshot": {
                "version": "image-validation-v1",
                "configured": True,
                "passed": False,
                "stage": "provider_output",
                "issue_codes": [reason],
                "provider": "fake",
                "model": "gpt-image-2",
                "media_type": None,
                "width": None,
                "height": None,
                "byte_size": None,
            },
        }
    ]


@pytest.mark.asyncio
async def test_retry_material_package_image_requeues_only_the_existing_terminal_image() -> None:
    package_id = uuid4()
    image_id = uuid4()
    package = SimpleNamespace(id=package_id, image_artifact_id=image_id, status="failed")
    image = SimpleNamespace(
        id=image_id,
        status="review_required",
        attempt_count=1,
        error_code="image_output_invalid",
        available_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        lease_owner="previous-worker",
        lease_token=uuid4(),
        lease_expires_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
    )
    session = _RetrySession(package, image)

    result = await retry_material_package_image(
        session=session,  # type: ignore[arg-type]
        package_id=package_id,
        max_attempts=3,
    )

    assert result.package is package
    assert result.image is image
    assert package.status == "queued"
    assert image.status == "queued"
    assert image.error_code is None
    assert image.completed_at is None
    assert image.lease_owner is None
    assert image.lease_token is None
    assert image.lease_expires_at is None
    assert image.heartbeat_at is None
    assert session.commits == 1


@pytest.mark.asyncio
async def test_material_worker_ocr_missing_and_unexpected_text_queues_one_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claimed = _claimed_material_package(
        visual_brief=_quality_visual_brief(),
    )
    image, package, session = _quality_attempt_state(claimed)
    generator = _RecordingImageGenerator()
    recognizer = _RecordingImageTextRecognizer(("具身智能", "未经允许的文案"))
    store = _RecordingImageStore()
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=store,
        settings=Settings(image_ocr_enabled=True),
        reference_asset=None,
        image_text_recognizer=recognizer,
    )

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    monkeypatch.setattr(executor, "_claim", fake_claim)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert len(recognizer.requests) == 1
    assert store.calls == 0
    assert image.status == "queued"
    assert image.repair_count == 1
    assert image.error_code == "image_text_validation_failed"
    assert image.completed_at is None
    assert package.status == "queued"
    assert image.validation_snapshot["passed"] is False
    assert image.validation_snapshot["issue_codes"] == [
        "missing_visual_text",
        "unexpected_visual_text",
    ]
    assert image.audit_snapshot["status"] == "not_configured"
    assert package.version_snapshot["image"]["validation"] == image.validation_snapshot
    assert package.version_snapshot["image"]["audit"] == image.audit_snapshot
    assert session.commits == 1


@pytest.mark.asyncio
async def test_material_worker_stops_before_similarity_and_storage_on_typed_ocr_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claimed = _claimed_material_package(visual_brief=_quality_visual_brief())
    image, package, session = _quality_attempt_state(claimed)
    generator = _RecordingImageGenerator()
    recognizer = _RejectingImageTextRecognizer()
    store = _RecordingImageStore()
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=store,
        settings=Settings(image_ocr_enabled=True),
        reference_asset=None,
        image_text_recognizer=recognizer,
    )
    similarity_calls = 0

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    async def fake_similarity(
        value: ClaimedMaterialPackage,
        *,
        image_bytes: bytes,
    ) -> tuple[bool, None]:
        nonlocal similarity_calls
        del value, image_bytes
        similarity_calls += 1
        return True, None

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_assess_image_similarity", fake_similarity)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert len(recognizer.requests) == 1
    assert similarity_calls == 0
    assert store.calls == 0
    assert image.error_code == "provider_request_rejected"
    assert package.status == "failed"


@pytest.mark.asyncio
async def test_material_worker_repairs_provider_validated_exact_text_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claimed = _claimed_material_package(visual_brief=_quality_visual_brief())
    image, package, session = _quality_attempt_state(claimed)
    generator = _RecordingImageGenerator()
    recognizer = _InvalidTextImageTextRecognizer(("missing_visual_text", "unexpected_visual_text"))
    store = _RecordingImageStore()
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=store,
        settings=Settings(image_ocr_enabled=True),
        reference_asset=None,
        image_text_recognizer=recognizer,
    )
    similarity_calls = 0

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    async def fake_similarity(
        value: ClaimedMaterialPackage,
        *,
        image_bytes: bytes,
    ) -> tuple[bool, None]:
        nonlocal similarity_calls
        del value, image_bytes
        similarity_calls += 1
        return True, None

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_assess_image_similarity", fake_similarity)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert len(recognizer.requests) == 1
    assert similarity_calls == 0
    assert store.calls == 0
    assert image.status == "queued"
    assert image.repair_count == 1
    assert image.error_code == "image_text_validation_failed"
    assert image.validation_snapshot["issue_codes"] == [
        "missing_visual_text",
        "unexpected_visual_text",
    ]
    assert package.status == "queued"


@pytest.mark.parametrize(
    "issue_codes",
    (
        ("image_ocr_response_envelope_invalid",),
        ("image_ocr_contract_source_invalid",),
        ("image_ocr_contract_source_conflict",),
        ("image_ocr_contract_schema_invalid",),
        ("image_ocr_contract_page_count",),
        ("image_ocr_contract_page_dimensions",),
        ("image_ocr_contract_page_dimensions_conflict",),
        ("image_ocr_contract_index_invalid",),
        ("image_ocr_contract_index_duplicate",),
        ("image_ocr_contract_label_unknown",),
        ("image_ocr_contract_bbox_shape",),
        ("image_ocr_contract_bbox_scale",),
        ("image_ocr_contract_bbox_range",),
        ("image_ocr_contract_content_type",),
        ("image_ocr_contract_content_limit",),
        ("image_ocr_contract_element_extra",),
        ("image_ocr_contract_table_unsupported",),
        ("image_ocr_contract_formula_unsupported",),
        ("image_ocr_contract_line_limit",),
        ("missing_visual_text", "image_ocr_contract_bbox_shape"),
    ),
)
@pytest.mark.asyncio
async def test_material_worker_keeps_malformed_ocr_output_terminal_before_downstream_work(
    monkeypatch: pytest.MonkeyPatch,
    issue_codes: tuple[str, ...],
) -> None:
    claimed = _claimed_material_package(visual_brief=_quality_visual_brief())
    image, package, session = _quality_attempt_state(claimed)
    generator = _RecordingImageGenerator()
    recognizer = _InvalidTextImageTextRecognizer(issue_codes)
    store = _RecordingImageStore()
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=store,
        settings=Settings(image_ocr_enabled=True),
        reference_asset=None,
        image_text_recognizer=recognizer,
    )
    similarity_calls = 0

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    async def fake_similarity(
        value: ClaimedMaterialPackage,
        *,
        image_bytes: bytes,
    ) -> tuple[bool, None]:
        nonlocal similarity_calls
        del value, image_bytes
        similarity_calls += 1
        return True, None

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_assess_image_similarity", fake_similarity)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert len(recognizer.requests) == 1
    assert similarity_calls == 0
    assert store.calls == 0
    assert image.status == "failed"
    assert image.repair_count == 0
    assert image.error_code == "invalid_provider_output"
    assert image.validation_snapshot["passed"] is False
    assert image.validation_snapshot["stage"] == "image_ocr_provider_output"
    assert image.validation_snapshot["issue_codes"] == list(issue_codes)
    assert package.status == "failed"


@pytest.mark.asyncio
async def test_material_worker_second_quality_failure_uses_brand_catalog_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reserved = ReservedVisualReference(
        role="action_reference",
        asset_id="asset-robot-action",
        filename="robot-action.png",
        sha256="b" * 64,
        selection_reason="robotics action match",
        fallback=False,
    )
    claimed = _claimed_material_package(
        repair_count=1,
        visual_brief=_quality_visual_brief(),
        references=(reserved,),
    )
    image, package, session = _quality_attempt_state(claimed)
    generator = _RecordingImageGenerator()
    recognizer = _RecordingImageTextRecognizer(("具身智能", "未经允许的文案"))
    store = _RecordingImageStore()
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=store,
        settings=Settings(image_ocr_enabled=True),
        reference_asset=None,
        image_text_recognizer=recognizer,
    )

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    reference = ImageReference(
        role=reserved.role,
        asset_id=reserved.asset_id,
        filename=reserved.filename,
        sha256=reserved.sha256,
        image_bytes=_solid_png("catalog-fallback", "robot-action"),
        selection_reason=reserved.selection_reason,
    )

    async def fake_read_references(
        value: ClaimedMaterialPackage,
    ) -> tuple[ImageReference, ...]:
        assert value == claimed
        return (reference,)

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_read_claimed_references", fake_read_references)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert len(recognizer.requests) == 1
    assert store.calls == 1
    assert image.status == "succeeded"
    assert image.repair_count == 1
    assert image.error_code is None
    assert image.completed_at is not None
    assert image.lease_token is None
    assert package.status == "awaiting_manual_use"
    assert image.validation_snapshot["passed"] is True
    assert image.validation_snapshot["stage"] == "brand_catalog_fallback"
    assert image.audit_snapshot["status"] == "not_applicable"
    assert session.commits == 1
    assert package.version_snapshot["image"]["fallback"]["state"] == "brand_catalog"
    assert (
        package.version_snapshot["image"]["fallback"]["initial_error_code"]
        == "image_text_validation_failed"
    )


class _TimeoutImageGenerator:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        del request
        self.calls += 1
        raise ImageProviderTimeoutError()


@pytest.mark.asyncio
async def test_material_worker_exhausted_transient_provider_uses_catalog_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reserved = ReservedVisualReference(
        role="action_reference",
        asset_id="asset-robot-action",
        filename="robot-action.png",
        sha256="b" * 64,
        selection_reason="robotics action match",
        fallback=False,
    )
    claimed = _claimed_material_package(references=(reserved,))
    image, package, session = _quality_attempt_state(claimed)
    generator = _TimeoutImageGenerator()
    store = _RecordingImageStore()
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=store,
        settings=Settings(image_max_attempts=1),
        reference_asset=None,
    )

    reference = ImageReference(
        role=reserved.role,
        asset_id=reserved.asset_id,
        filename=reserved.filename,
        sha256=reserved.sha256,
        image_bytes=_solid_png("catalog-fallback", "robot-action"),
        selection_reason=reserved.selection_reason,
    )

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    async def fake_read_references(
        value: ClaimedMaterialPackage,
    ) -> tuple[ImageReference, ...]:
        assert value == claimed
        return (reference,)

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_read_claimed_references", fake_read_references)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert store.calls == 1
    assert image.status == "succeeded"
    assert package.status == "awaiting_manual_use"
    assert (
        package.version_snapshot["image"]["fallback"]["initial_error_code"]
        == "image_provider_timeout"
    )


@pytest.mark.parametrize("controlled", (False, True))
@pytest.mark.asyncio
async def test_material_worker_persists_configured_ocr_and_audit_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    controlled: bool,
) -> None:
    brief = (
        build_visual_brief(
            AcceptedVisualContext(topic_title="机器人如何学会调整动作"),
            version=CONTROLLED_VISUAL_BRIEF_VERSION,
        )
        if controlled
        else _quality_visual_brief()
    )
    claimed = _claimed_material_package(visual_brief=brief)
    generator = _RecordingImageGenerator()
    store = _RecordingImageStore()
    recognizer = _RecordingImageTextRecognizer()
    auditor = _RecordingImageQualityAuditor()
    executor = MaterialPackageExecutor(
        session_factory=object(),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=store,
        settings=Settings(image_ocr_enabled=True, image_quality_audit_enabled=True),
        reference_asset=None,
        image_text_recognizer=recognizer,
        image_quality_auditor=auditor,
    )
    persisted: list[dict[str, object]] = []

    async def fake_claim(worker_id: str) -> ClaimedMaterialPackage:
        del worker_id
        return claimed

    async def fake_persist(
        value: ClaimedMaterialPackage,
        result: ImageGenerationResult,
        descriptor: ImageObjectDescriptor,
        *,
        validation_snapshot: dict[str, object] | None = None,
        audit_snapshot: dict[str, object] | None = None,
    ) -> bool:
        assert value == claimed
        persisted.append(
            {
                "result": result,
                "descriptor": descriptor,
                "validation": validation_snapshot,
                "audit": audit_snapshot,
            }
        )
        return True

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_persist_success", fake_persist)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert store.calls == 1
    assert len(recognizer.requests) == 1
    assert recognizer.requests[0].expected_text == _expected_visual_text(brief)
    assert recognizer.requests[0].require_order is controlled
    assert len(auditor.requests) == 1
    assert auditor.requests[0].visual_brief == brief
    assert len(persisted) == 1

    validation = persisted[0]["validation"]
    assert isinstance(validation, dict)
    assert validation["version"] == "image-validation-v1"
    assert validation["configured"] is True
    assert validation["passed"] is True
    assert validation["issue_codes"] == []
    assert validation["provider"] == "fake-ocr"
    assert validation["model"] == "ocr-v1"

    audit = persisted[0]["audit"]
    assert isinstance(audit, dict)
    assert audit == {
        "version": "image-audit-v1",
        "configured": True,
        "status": "accepted",
        "passed": True,
        "issue_codes": [],
        "provider": "fake-auditor",
        "model": "quality-v1",
    }


def test_content_driven_image_input_persists_ordered_real_reference_metadata(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    asset_root = materials_root / "05-visual-assets"
    asset_root.mkdir(parents=True)
    entries: list[dict[str, object]] = []
    for filename, roles, priority in (
        ("robotics-identity-xiao.png", ["identity_reference"], 90),
        ("robotics-identity-sai.png", ["identity_reference"], 80),
        ("robotics-action.png", ["action_reference"], 70),
        ("robotics-style.png", ["style_reference"], 10),
    ):
        body = _solid_png(filename, "approved")
        path = asset_root / filename
        path.write_bytes(body)
        digest = hashlib.sha256(body).hexdigest()
        entries.append(
            {
                "asset_id": digest,
                "sha256": digest,
                "checksum": digest,
                "relative_path": f"05-visual-assets/{filename}",
                "category": "visual-asset",
                "filename": filename,
                "byte_size": len(body),
                "media_type": "image/png",
                "width": 1024,
                "height": 1024,
                "has_alpha": False,
                "characters": (
                    ["xiao-sai"]
                    if "identity-xiao" in filename
                    else ["sai-xiansheng"]
                    if "identity-sai" in filename
                    else []
                ),
                "roles": roles,
                "topics": ["robotics", "ai", "science"],
                "poses": ["observe"],
                "scene_tags": ["robotics_lab"],
                "priority": priority,
                "approved": True,
            }
        )
    manifest = materials_root / "visual-assets.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "brand-visual-assets-v2",
                "catalog_version": "brand-visual-catalog-test-v1",
                "private": True,
                "text_rag_eligible": False,
                "asset_count": len(entries),
                "assets": entries,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    accepted = AcceptedMaterialInput(
        run=SimpleNamespace(id=uuid4()),  # type: ignore[arg-type]
        draft=SimpleNamespace(id=uuid4()),  # type: ignore[arg-type]
        prompt="legacy prompt",
        topic_snapshot={"title": "机器人如何学会调整动作", "summary": "从尝试中学习"},
        copy_snapshot={"copywriting": "家长能看懂的正文"},
        source_snapshot=[],
        brand_snapshot=[],
        validation_snapshot={},
        audit_snapshot={},
        version_snapshot={},
        visual_brief=build_visual_brief(
            AcceptedVisualContext(
                topic_title="机器人如何学会调整动作",
                topic_summary="从尝试中学习",
                copywriting="家长能看懂的正文",
            )
        ),
    )

    prepared = _prepare_image_input(
        accepted,
        reference_asset=None,
        image_asset_manifest=str(manifest),
        image_provider="comfly",
        image_prompt_version="image-prompt-test-v1",
        image_pipeline_version="image-pipeline-test-v1",
        image_selector_version="visual-asset-selector-test-v1",
        image_selector_enabled=True,
        image_max_reference_images=3,
        image_reference_budget_bytes=1_000_000,
    )

    assert prepared.reference_mode == "budgeted_multi_reference"
    assert [reference.filename for reference in prepared.references] == [
        "robotics-identity-xiao.png",
        "robotics-identity-sai.png",
        "robotics-action.png",
    ]
    assert prepared.visual_brief_snapshot["category"] == "robotics"
    assert "家长能看懂的正文" not in prepared.prompt
