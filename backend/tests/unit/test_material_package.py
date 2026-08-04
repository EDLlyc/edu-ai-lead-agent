from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.api.v1.routes import material_packages as material_package_routes
from app.application.ports.image_generation import ImageGenerationRequest, ImageGenerationResult
from app.application.services.material_package import (
    AcceptedMaterialInput,
    ClaimedMaterialPackage,
    MaterialPackageExecutor,
    MaterialPackageResult,
    enqueue_material_package,
)
from app.core.config import Settings
from app.core.errors import ConflictError, ImageProviderRejectedError
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


def _claimed_material_package(*, eligible: bool = True) -> ClaimedMaterialPackage:
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
    )


class _RecordingImageGenerator:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        self.calls += 1
        return ImageGenerationResult(
            provider="fake",
            model="gpt-image-2",
            request_fingerprint=request.request_fingerprint,
            provider_task_id=None,
            provider_upload_id=None,
            image_bytes=b"generated-image",
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
    ) -> bool:
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
async def test_material_worker_provider_rejection_is_review_required_and_never_accepted(
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
    ) -> None:
        assert value == claimed
        finished.append(
            {
                "error_code": error_code,
                "retryable": retryable,
                "review_required": review_required,
            }
        )

    monkeypatch.setattr(executor, "_claim", fake_claim)
    monkeypatch.setattr(executor, "_finish_attempt", fake_finish)

    assert await executor.execute_next("material-worker") is True
    assert generator.calls == 1
    assert finished == [
        {
            "error_code": "image_provider_rejected",
            "retryable": False,
            "review_required": True,
        }
    ]
