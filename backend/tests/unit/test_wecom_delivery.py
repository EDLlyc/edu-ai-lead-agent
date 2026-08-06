from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.application.services.wecom_delivery import (
    WeComDeliveryExecutor,
    _validate_wecom_image_body,
    build_wecom_text,
    enqueue_wecom_delivery,
)
from app.core.config import Settings
from app.core.errors import ConflictError
from app.domain.image_generation import image_checksum, image_content_key
from app.infrastructure.db.models import ImageArtifactModel, MaterialPackageModel
from pydantic import SecretStr
from sqlalchemy.sql import Select


def _package(*, title: str = "机器人如何学会调整动作", copywriting: str = "家长能看懂的正文"):
    return SimpleNamespace(
        topic_snapshot={"title": title},
        copy_snapshot={"copywriting": copywriting},
    )


def _settings(*, require_review: bool) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        wecom_enabled=True,
        wecom_corp_id="corp",
        wecom_agent_id=17,
        wecom_corp_secret=SecretStr("secret"),
        wecom_default_recipient_id="sales-user",
        wecom_require_review_before_send=require_review,
    )


def _delivery_package(
    *, status: str = "awaiting_manual_use", review_status: str = "pending"
) -> tuple[SimpleNamespace, SimpleNamespace]:
    image = SimpleNamespace(
        id=uuid4(),
        status="succeeded",
        bucket="edu-ai-materials",
        object_key=image_content_key("b" * 64, "image/png"),
        media_type="image/png",
        byte_size=1024,
        sha256="b" * 64,
        validation_snapshot={"configured": True, "passed": True},
        audit_snapshot={"configured": False, "passed": None},
        storage_metadata={"access": "private", "immutable": True, "content_addressed": True},
    )
    package = SimpleNamespace(
        id=uuid4(),
        status=status,
        review_status=review_status,
        image_artifact_id=image.id,
        package_version=1,
        request_fingerprint="a" * 64,
        validation_snapshot={"passed": True},
        audit_snapshot={"accepted": True},
    )
    return package, image


class _DeliverySession:
    def __init__(self, package: SimpleNamespace, image: SimpleNamespace) -> None:
        self.package = package
        self.image = image
        self.added: list[object] = []
        self.commits = 0

    async def get(self, model: object, _entity_id: object) -> object:
        if model is MaterialPackageModel:
            return self.package
        if model is ImageArtifactModel:
            return self.image
        raise AssertionError(f"unexpected model: {model!r}")

    async def scalar(self, _statement: object) -> object | None:
        return None

    def add(self, entity: object) -> None:
        self.added.append(entity)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _entity: object) -> None:
        return None


class _AutoQueryResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


class _AutoDeliverySession:
    def __init__(self, packages: list[object]) -> None:
        self.packages = packages
        self.statement: Select[tuple[MaterialPackageModel]] | None = None

    async def __aenter__(self) -> _AutoDeliverySession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def scalars(self, statement: Select[tuple[MaterialPackageModel]]) -> _AutoQueryResult:
        self.statement = statement
        return _AutoQueryResult(self.packages)


class _AutoDeliverySessionFactory:
    def __init__(self, session: _AutoDeliverySession) -> None:
        self.session = session

    def __call__(self) -> _AutoDeliverySession:
        return self.session


def test_build_wecom_text_contains_title_and_test_marker() -> None:
    text = build_wecom_text(_package(), mode="test", max_bytes=2048)

    assert text == "【测试消息】\n【机器人如何学会调整动作】\n\n家长能看懂的正文"


def test_build_wecom_text_rejects_utf8_overflow() -> None:
    with pytest.raises(ConflictError, match="exceeds WeCom text limit"):
        build_wecom_text(_package(copywriting="正文" * 100), mode="formal", max_bytes=20)


@pytest.mark.asyncio
async def test_review_required_mode_rejects_pending_review() -> None:
    settings = _settings(require_review=True)
    package = SimpleNamespace(
        id="package-id",
        status="completed",
        review_status="pending",
    )

    class _Session:
        async def get(self, _model: object, _package_id: object) -> object:
            return package

    with pytest.raises(ConflictError, match="approved"):
        await enqueue_wecom_delivery(
            session=_Session(),  # type: ignore[arg-type]
            package_id="package-id",  # type: ignore[arg-type]
            recipient_id="default",
            mode="formal",
            include_copy=True,
            include_image=False,
            settings=settings,
        )

    assert settings.wecom_enabled is True


@pytest.mark.asyncio
async def test_direct_mode_enqueues_pending_manual_use_package_after_quality_checks() -> None:
    package, image = _delivery_package()
    session = _DeliverySession(package, image)

    job = await enqueue_wecom_delivery(
        session=session,  # type: ignore[arg-type]
        package_id=package.id,
        recipient_id="default",
        mode="formal",
        include_copy=True,
        include_image=True,
        settings=_settings(require_review=False),
    )

    assert job.material_package_id == package.id
    assert job.status == "queued"
    assert job.mode == "formal"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_direct_mode_rejects_explicit_review_rejection() -> None:
    package, image = _delivery_package(review_status="rejected")

    with pytest.raises(ConflictError, match="rejected"):
        await enqueue_wecom_delivery(
            session=_DeliverySession(package, image),  # type: ignore[arg-type]
            package_id=package.id,
            recipient_id="default",
            mode="formal",
            include_copy=True,
            include_image=True,
            settings=_settings(require_review=False),
        )


@pytest.mark.asyncio
async def test_direct_mode_rejects_failed_copy_quality() -> None:
    package, image = _delivery_package()
    package.validation_snapshot = {"passed": False}

    with pytest.raises(ConflictError, match="copy validation"):
        await enqueue_wecom_delivery(
            session=_DeliverySession(package, image),  # type: ignore[arg-type]
            package_id=package.id,
            recipient_id="default",
            mode="formal",
            include_copy=True,
            include_image=True,
            settings=_settings(require_review=False),
        )


@pytest.mark.asyncio
async def test_direct_mode_rejects_configured_failed_image_audit() -> None:
    package, image = _delivery_package()
    image.audit_snapshot = {"configured": True, "passed": False}

    with pytest.raises(ConflictError, match="image audit"):
        await enqueue_wecom_delivery(
            session=_DeliverySession(package, image),  # type: ignore[arg-type]
            package_id=package.id,
            recipient_id="default",
            mode="formal",
            include_copy=True,
            include_image=True,
            settings=_settings(require_review=False),
        )


@pytest.mark.asyncio
async def test_direct_mode_rejects_incomplete_image_metadata_before_enqueue() -> None:
    package, image = _delivery_package()
    image.sha256 = None

    with pytest.raises(ConflictError, match="metadata is incomplete"):
        await enqueue_wecom_delivery(
            session=_DeliverySession(package, image),  # type: ignore[arg-type]
            package_id=package.id,
            recipient_id="default",
            mode="formal",
            include_copy=True,
            include_image=True,
            settings=_settings(require_review=False),
        )


@pytest.mark.asyncio
async def test_direct_mode_accepts_storage_metadata_by_value() -> None:
    package, image = _delivery_package()
    image.storage_metadata = {
        "access": "".join(("pri", "vate")),
        "immutable": bool(1),
        "content_addressed": bool(1),
    }

    job = await enqueue_wecom_delivery(
        session=_DeliverySession(package, image),  # type: ignore[arg-type]
        package_id=package.id,
        recipient_id="default",
        mode="formal",
        include_copy=True,
        include_image=True,
        settings=_settings(require_review=False),
    )

    assert job.status == "queued"


@pytest.mark.asyncio
async def test_direct_auto_reconciliation_queries_pending_manual_use_packages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, _image = _delivery_package()
    session = _AutoDeliverySession([package])
    settings = _settings(require_review=False)
    settings.wecom_auto_delivery_enabled = True
    calls: list[object] = []

    async def fake_enqueue(**kwargs: object) -> object:
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(
        "app.application.services.wecom_delivery.enqueue_wecom_delivery", fake_enqueue
    )
    executor = WeComDeliveryExecutor(
        session_factory=_AutoDeliverySessionFactory(session),  # type: ignore[arg-type]
        client=object(),  # type: ignore[arg-type]
        image_store=object(),  # type: ignore[arg-type]
        settings=settings,
    )

    created = await executor.reconcile_auto_deliveries(limit=5)

    assert created == 1
    assert len(calls) == 1
    assert session.statement is not None
    sql = str(session.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "awaiting_manual_use" in sql
    assert "completed" in sql
    assert "rejected" in sql


def test_image_body_validation_checks_metadata_and_signature() -> None:
    body = b"\x89PNG\r\n\x1a\nvalid-payload"

    _validate_wecom_image_body(
        body,
        media_type="image/png",
        expected_size=len(body),
        expected_sha256=image_checksum(body),
        max_bytes=1024,
    )

    with pytest.raises(ConflictError, match="checksum"):
        _validate_wecom_image_body(
            body,
            media_type="image/png",
            expected_size=len(body),
            expected_sha256=image_checksum(b"different"),
            max_bytes=1024,
        )


def test_empty_optional_wecom_environment_values_use_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WECOM_AGENT_ID", "")
    monkeypatch.setenv("WECOM_CORP_SECRET", "")
    monkeypatch.setenv("WECOM_DEFAULT_RECIPIENT_ID", "")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.wecom_agent_id is None
    assert settings.wecom_corp_secret is None
    assert settings.wecom_default_recipient_id == ""


def test_image_body_validation_rejects_wrong_media_signature() -> None:
    body = b"not-a-png"

    with pytest.raises(ConflictError, match="media type"):
        _validate_wecom_image_body(
            body,
            media_type="image/png",
            expected_size=len(body),
            expected_sha256=image_checksum(body),
            max_bytes=1024,
        )
