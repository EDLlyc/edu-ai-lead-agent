from __future__ import annotations

import base64
import hashlib
import json
from io import BytesIO

import app.infrastructure.wecom.group_webhook as group_webhook
import httpx
import pytest
from app.application.ports.wecom import WECOM_DELIVERY_UNKNOWN, WeComProviderError
from app.core.config import Settings
from app.infrastructure.wecom.group_webhook import (
    WeComGroupWebhookClient,
    prepare_group_webhook_image,
)
from PIL import Image
from pydantic import SecretStr, ValidationError


def _png_bytes(
    *,
    size: tuple[int, int] = (32, 32),
    color: tuple[int, int, int] = (31, 112, 192),
) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG", optimize=True)
    return output.getvalue()


def _settings(**updates: object) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        wecom_enabled=True,
        wecom_delivery_provider="group_webhook",
        wecom_group_webhook_key=SecretStr("group-webhook-secret"),
        **updates,
    )


@pytest.mark.asyncio
async def test_group_webhook_sends_markdown_without_self_built_app_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/cgi-bin/webhook/send"
        assert request.url.params["key"] == "group-webhook-secret"
        payload = json.loads(request.content)
        assert payload == {
            "msgtype": "markdown",
            "markdown": {"content": "# 今日选题\n\n家长看得懂的正文 😊"},
        }
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    adapter = WeComGroupWebhookClient(_settings(), client=http_client)
    async with http_client:
        result = await adapter.send_text(
            "default", None, "# 今日选题\n\n家长看得懂的正文 😊", "text-fingerprint"
        )

    assert result.response_code == 0
    assert len(requests) == 1
    assert "group-webhook-secret" not in repr(adapter)


@pytest.mark.asyncio
async def test_group_webhook_sends_raw_image_base64_and_md5() -> None:
    image = _png_bytes()
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        payloads.append(payload)
        encoded = payload["image"]["base64"]
        assert isinstance(encoded, str)
        assert base64.b64decode(encoded) == image
        assert payload["image"]["md5"] == hashlib.md5(image).hexdigest()
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = WeComGroupWebhookClient(_settings(), client=http_client)
    async with http_client:
        result = await adapter.send_image_bytes(
            "default",
            None,
            image,
            "image/png",
            "sale.png",
            "image-fingerprint",
        )

    assert result.response_code == 0
    assert len(payloads) == 1


def test_group_webhook_image_preparation_is_bounded_and_does_not_mutate_source() -> None:
    output = BytesIO()
    image = Image.effect_noise((512, 512), 128).convert("RGB")
    image.save(output, format="PNG", compress_level=0)
    source = output.getvalue()

    prepared = prepare_group_webhook_image(source, "image/png", max_bytes=20_000)

    assert source.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(prepared.body) <= 20_000
    assert prepared.media_type in {"image/png", "image/jpeg"}
    if prepared.media_type == "image/jpeg":
        assert prepared.body.startswith(b"\xff\xd8\xff")


@pytest.mark.asyncio
async def test_group_markdown_limit_is_rejected_before_provider_call() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"errcode": 0})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = WeComGroupWebhookClient(_settings(), client=http_client)
    async with http_client:
        with pytest.raises(WeComProviderError) as raised:
            await adapter.send_text("default", None, "汉" * 1366, "too-long")

    assert raised.value.code == "wecom_invalid_input"
    assert calls == 0


@pytest.mark.asyncio
async def test_group_send_timeout_is_unknown_and_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("webhook body must not leak", request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = WeComGroupWebhookClient(_settings(wecom_max_attempts=3), client=http_client)
    async with http_client:
        with pytest.raises(WeComProviderError) as raised:
            await adapter.send_text("default", None, "内容", "timeout")

    assert raised.value.code == WECOM_DELIVERY_UNKNOWN
    assert raised.value.unknown is True
    assert calls == 1
    assert "webhook body must not leak" not in str(raised.value)


@pytest.mark.asyncio
async def test_group_provider_error_is_safe_and_terminal() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"errcode": 93004, "errmsg": "group-webhook-secret must not leak"},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = WeComGroupWebhookClient(_settings(), client=http_client)
    async with http_client:
        with pytest.raises(WeComProviderError) as raised:
            await adapter.send_text("default", None, "内容", "rejected")

    assert raised.value.code == "wecom_provider_rejected"
    assert raised.value.retryable is False
    assert "group-webhook-secret" not in str(raised.value)


def test_group_provider_does_not_require_self_built_app_credentials() -> None:
    settings = _settings()

    assert settings.wecom_corp_id == ""
    assert settings.wecom_agent_id is None
    assert settings.wecom_corp_secret is None


def test_enabled_group_provider_requires_a_key() -> None:
    with pytest.raises(ValidationError, match="webhook key"):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            wecom_enabled=True,
            wecom_delivery_provider="group_webhook",
        )


@pytest.mark.asyncio
async def test_group_rate_limiter_waits_after_twenty_message_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = WeComGroupWebhookClient(_settings(), client=httpx.AsyncClient())
    adapter._message_timestamps.extend([0.0] * 20)  # type: ignore[attr-defined]
    current = 0.0
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return current

    async def fake_sleep(seconds: float) -> None:
        nonlocal current
        sleeps.append(seconds)
        current += seconds

    monkeypatch.setattr(group_webhook, "monotonic", fake_monotonic)
    monkeypatch.setattr(group_webhook.asyncio, "sleep", fake_sleep)
    await adapter._acquire_message_slot()  # type: ignore[attr-defined]
    await adapter._client.aclose()

    assert sleeps == [60.0]
