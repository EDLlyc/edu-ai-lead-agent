from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.application.services.wecom_delivery import (
    _validate_wecom_image_body,
    build_wecom_text,
    enqueue_wecom_delivery,
)
from app.core.config import Settings
from app.core.errors import ConflictError
from app.domain.image_generation import image_checksum
from pydantic import SecretStr


def _package(*, title: str = "机器人如何学会调整动作", copywriting: str = "家长能看懂的正文"):
    return SimpleNamespace(
        topic_snapshot={"title": title},
        copy_snapshot={"copywriting": copywriting},
    )


def test_build_wecom_text_contains_title_and_test_marker() -> None:
    text = build_wecom_text(_package(), mode="test", max_bytes=2048)

    assert text == "【测试消息】\n【机器人如何学会调整动作】\n\n家长能看懂的正文"


def test_build_wecom_text_rejects_utf8_overflow() -> None:
    with pytest.raises(ConflictError, match="exceeds WeCom text limit"):
        build_wecom_text(_package(copywriting="正文" * 100), mode="formal", max_bytes=20)


@pytest.mark.asyncio
async def test_formal_delivery_requires_approval_even_when_review_switch_is_disabled() -> None:
    settings = Settings(
        _env_file=None,
        wecom_enabled=True,
        wecom_corp_id="corp",
        wecom_agent_id=17,
        wecom_corp_secret=SecretStr("secret"),
        wecom_default_recipient_id="sales-user",
        wecom_require_review_before_send=False,
    )
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

    settings = Settings(_env_file=None)

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
