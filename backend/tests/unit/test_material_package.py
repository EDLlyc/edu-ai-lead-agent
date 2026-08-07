from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

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
    _prepare_image_input,
    enqueue_material_package,
    retry_material_package_image,
)
from app.core.config import Settings
from app.core.errors import ConflictError, ImageOutputValidationError, ImageProviderRejectedError
from app.domain.visual_brief import AcceptedVisualContext, VisualBrief, build_visual_brief
from app.infrastructure.ai.image_generation import _solid_png
from app.infrastructure.db.models import ImageArtifactModel, MaterialPackageModel
from app.infrastructure.storage.minio_image_store import ImageObjectDescriptor
from app.schemas.material_package import (
    MaterialPackageCreateRequest,
    MaterialPackageDownloadResponse,
)
from fastapi import Response


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


def test_material_package_image_projection_defaults_and_redacts_fallback_provenance() -> None:
    package, image = _package_and_image()
    image.provider_rejection_retry_count = 1
    package.version_snapshot["image"] = {
        "fallback": {
            "version": "image-fallback-v1",
            "state": "brand_catalog",
            "initial_error_code": "image_provider_rejected",
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
        "initial_error_code": "image_provider_rejected",
        "primary_provider": "fake",
        "primary_model": "gpt-image-2",
        "asset": None,
    }
    assert "private.example.test" not in json.dumps(payload)


def _claimed_material_package(
    *,
    eligible: bool = True,
    repair_count: int = 0,
    provider_rejection_retry_count: int = 0,
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
        reference_sha256=None,
        lease_token=uuid4(),
        attempt_number=1,
        eligible=eligible,
        references=references,
        repair_count=repair_count,
        provider_rejection_retry_count=provider_rejection_retry_count,
        visual_brief=visual_brief,
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
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        del request
        self.calls += 1
        raise ImageProviderRejectedError()


class _InvalidOutputImageGenerator:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        del request
        self.calls += 1
        raise ImageOutputValidationError("image_download_content_type_invalid")


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
    ) -> None:
        assert references == ()
        assert validation_snapshot == {}
        assert audit_snapshot["status"] == "not_configured"
        fallbacks.append(value)

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_persist_catalog_fallback", fake_fallback)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert fallbacks == [claimed]


@pytest.mark.asyncio
async def test_catalog_fallback_stores_a_validated_private_brand_image() -> None:
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
        "initial_error_code": "image_provider_rejected",
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
async def test_material_worker_persists_a_safe_adapter_output_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _InvalidOutputImageGenerator()
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
                "issue_codes": ["image_download_content_type_invalid"],
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
async def test_material_worker_second_quality_failure_requires_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claimed = _claimed_material_package(
        repair_count=1,
        visual_brief=_quality_visual_brief(),
    )
    image, package, session = _quality_attempt_state(claimed)
    generator = _RecordingImageGenerator()
    recognizer = _RecordingImageTextRecognizer(("具身智能", "未经允许的文案"))
    executor = MaterialPackageExecutor(
        session_factory=_SequenceSessionFactory(session),  # type: ignore[arg-type]
        image_generator=generator,
        image_store=object(),  # type: ignore[arg-type]
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
    assert image.status == "review_required"
    assert image.repair_count == 1
    assert image.error_code == "image_text_validation_failed"
    assert image.completed_at is not None
    assert image.lease_token is None
    assert package.status == "failed"
    assert image.validation_snapshot["issue_codes"] == [
        "missing_visual_text",
        "unexpected_visual_text",
    ]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_material_worker_persists_configured_ocr_and_audit_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brief = _quality_visual_brief()
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
    assert recognizer.requests[0].expected_text == (
        brief.text_layer.title,
        brief.text_layer.learning_line,
        *brief.text_layer.keywords,
        *brief.text_layer.brand_values,
    )
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
        ("robotics-identity.png", ["identity_reference", "action_reference"], 90),
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
                "characters": ["xiao-sai", "sai-xiansheng"] if "identity" in filename else [],
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
        "robotics-identity.png",
        "robotics-style.png",
    ]
    assert prepared.visual_brief_snapshot["category"] == "robotics"
    assert "家长能看懂的正文" not in prepared.prompt
