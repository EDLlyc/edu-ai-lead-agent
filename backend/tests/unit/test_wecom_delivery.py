from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.application.services.wecom_delivery import (
    WeComDeliveryExecutor,
    _auto_delivery_candidate_statement,
    _delivery_fingerprint_namespace,
    _validate_wecom_image_body,
    build_wecom_text,
    enqueue_wecom_delivery,
)
from app.core.config import Settings
from app.core.errors import ConflictError
from app.domain.image_generation import image_checksum, image_content_key
from app.infrastructure.db.models import ImageArtifactModel, MaterialPackageModel
from pydantic import SecretStr
from sqlalchemy.dialects import postgresql
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


def test_build_wecom_text_keeps_evidence_bound_news_source_footer() -> None:
    copywriting = (
        "📰今天看到一条新闻\uff1a机器人研究有了新进展。\n"
        "孩子能从真实问题里理解技术。🔎\n\n"
        "🤖科学学习从提问开始。\n"
        "一次次动手验证,让想法更清楚。💡\n\n"
        "✨在赛先生,孩子会把好奇心变成行动。\n"
        "在探索中慢慢学会解决问题。🚀\n\n"
        "新闻来源\uff1a科技日报\n"
        "原文链接\uff1ahttps://example.test/article\n"
        "#赛先生科学 #科学思维"
    )

    text = build_wecom_text(_package(copywriting=copywriting), mode="formal", max_bytes=4096)

    assert "新闻来源\uff1a科技日报" in text
    assert "https://example.test/article" in text
    assert text.endswith("#赛先生科学 #科学思维")


def test_build_wecom_text_rejects_utf8_overflow() -> None:
    with pytest.raises(ConflictError, match="exceeds WeCom text limit"):
        build_wecom_text(_package(copywriting="正文" * 100), mode="formal", max_bytes=20)


def test_group_delivery_fingerprint_namespace_is_distinct_from_legacy_route() -> None:
    legacy = _settings(require_review=False)
    group = Settings(
        _env_file=None,  # type: ignore[call-arg]
        wecom_enabled=True,
        wecom_delivery_provider="group_webhook",
        wecom_group_webhook_key=SecretStr("group-webhook-secret"),
    )

    assert _delivery_fingerprint_namespace(legacy) == "wecom-delivery-v1"
    assert _delivery_fingerprint_namespace(group) == "wecom-delivery-group-v1"


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
        clock=lambda: datetime(2026, 8, 7, 16, 30, tzinfo=UTC),
    )

    created = await executor.reconcile_auto_deliveries(limit=5)

    assert created == 1
    assert len(calls) == 1
    assert session.statement is not None
    compiled = session.statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert ["awaiting_manual_use", "completed"] in compiled.params.values()
    assert "rejected" in compiled.params.values()
    assert "NOT (EXISTS" in sql
    assert "wecom_delivery_jobs.material_package_id" in sql
    assert "copy_generation_runs.business_date" in sql
    assert date(2026, 8, 8) in compiled.params.values()
    assert "image_artifacts.validation_snapshot" in sql
    assert "image_artifacts.audit_snapshot" in sql
    assert "generated-images/sha256/" in compiled.params.values()
    assert "@>" in sql
    assert "CAST(" not in sql
    assert {"passed": True} in compiled.params.values()
    assert {"accepted": True} in compiled.params.values()
    assert {"access": "private", "immutable": True, "content_addressed": True} in (
        compiled.params.values()
    )


def test_auto_delivery_candidate_query_uses_typed_business_date() -> None:
    settings = _settings(require_review=False)

    statement = _auto_delivery_candidate_statement(
        settings=settings,
        business_date=date(2026, 8, 7),
        limit=5,
    )
    compiled = statement.compile(dialect=postgresql.dialect())

    assert "JOIN copy_generation_runs" in str(compiled)
    assert date(2026, 8, 7) in compiled.params.values()


@pytest.mark.asyncio
async def test_direct_auto_reconciliation_skips_historical_incomplete_image_state() -> None:
    historical_package, historical_image = _delivery_package()
    historical_image.validation_snapshot = {}
    historical_image.audit_snapshot = {}
    session = _AutoDeliverySession([])
    settings = _settings(require_review=False)
    settings.wecom_auto_delivery_enabled = True
    executor = WeComDeliveryExecutor(
        session_factory=_AutoDeliverySessionFactory(session),  # type: ignore[arg-type]
        client=object(),  # type: ignore[arg-type]
        image_store=object(),  # type: ignore[arg-type]
        settings=settings,
    )

    assert await executor.reconcile_auto_deliveries(limit=5) == 0
    assert session.statement is not None
    compiled = session.statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "image_artifacts.validation_snapshot @>" in sql
    assert "image_artifacts.audit_snapshot @>" in sql
    assert "CAST(" not in sql
    assert str(historical_package.id) not in sql


@pytest.mark.asyncio
async def test_direct_mode_rejects_non_boolean_image_quality_metadata() -> None:
    package, image = _delivery_package()
    image.audit_snapshot = {"configured": 0, "passed": True}

    with pytest.raises(ConflictError, match="image audit is unavailable"):
        await enqueue_wecom_delivery(
            session=_DeliverySession(package, image),  # type: ignore[arg-type]
            package_id=package.id,
            recipient_id="default",
            mode="formal",
            include_copy=True,
            include_image=True,
            settings=_settings(require_review=False),
        )

    image.audit_snapshot = {"configured": False, "passed": None}
    image.storage_metadata = {"access": "private", "immutable": 1, "content_addressed": True}
    with pytest.raises(ConflictError, match="storage metadata"):
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
async def test_auto_reconciliation_deduplicates_unchanged_race_conflict_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, _image = _delivery_package()
    session = _AutoDeliverySession([package])
    settings = _settings(require_review=False)
    settings.wecom_auto_delivery_enabled = True
    log_events: list[dict[str, object]] = []

    class _Logger:
        def info(self, _event: str, **values: object) -> None:
            log_events.append(values)

    async def fake_enqueue(**_kwargs: object) -> object:
        raise ConflictError("package changed after candidate query")

    monkeypatch.setattr(
        "app.application.services.wecom_delivery.enqueue_wecom_delivery", fake_enqueue
    )
    monkeypatch.setattr("app.application.services.wecom_delivery.logger", _Logger())
    executor = WeComDeliveryExecutor(
        session_factory=_AutoDeliverySessionFactory(session),  # type: ignore[arg-type]
        client=object(),  # type: ignore[arg-type]
        image_store=object(),  # type: ignore[arg-type]
        settings=settings,
    )

    assert await executor.reconcile_auto_deliveries(limit=5) == 0
    assert await executor.reconcile_auto_deliveries(limit=5) == 0
    assert len(log_events) == 1
    assert log_events[0]["package_id"] == str(package.id)
    assert log_events[0]["error_code"] == "conflict"
    assert isinstance(log_events[0]["readiness_state"], str)

    package.validation_snapshot = {"passed": False}
    assert await executor.reconcile_auto_deliveries(limit=5) == 0
    assert len(log_events) == 2


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
