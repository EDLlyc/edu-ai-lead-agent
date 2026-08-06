from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from app.application.ports.wecom import (
    WECOM_DELIVERY_UNKNOWN,
    WECOM_INVALID_RESPONSE,
    WECOM_PROVIDER_REJECTED,
    WECOM_RATE_LIMITED,
    WECOM_TRANSIENT,
    WeComProviderError,
)
from app.core.config import Settings
from app.infrastructure.wecom.client import WeComApiClient, WeComHttpClient
from pydantic import SecretStr

_Sleep = Callable[[float], Awaitable[None]]
IMAGE_BYTES = b"\x89PNG\r\n\x1a\n"


async def _no_sleep(_: float) -> None:
    return None


def _adapter(
    handler: httpx.AsyncBaseTransport,
    *,
    max_attempts: int = 2,
    max_response_bytes: int = 64 * 1024,
    sleep: _Sleep = _no_sleep,
) -> tuple[WeComApiClient, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=handler)
    return (
        WeComApiClient(
            client=client,
            corp_id="corp-contract",
            corp_secret=SecretStr("corp-secret-contract"),
            base_url="https://qyapi.weixin.qq.com",
            timeout_seconds=1,
            max_attempts=max_attempts,
            max_response_bytes=max_response_bytes,
            sleep=sleep,
        ),
        client,
    )


def _token_payload(token: str = "access-token-1") -> dict[str, object]:
    return {"errcode": 0, "errmsg": "ok", "access_token": token, "expires_in": 7_200}


async def test_token_is_cached_and_upload_uses_bounded_official_multipart() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/gettoken"):
            return httpx.Response(200, json=_token_payload())
        assert request.url.path.endswith("/media/upload")
        assert request.url.params["type"] == "image"
        assert request.url.params["access_token"] == "access-token-1"
        assert request.headers["content-type"].startswith("multipart/form-data;")
        assert b'name="media"' in request.content
        assert b'filename="sale.png"' in request.content
        assert b"image/png" in request.content
        assert IMAGE_BYTES in request.content
        return httpx.Response(
            200,
            json={"errcode": 0, "errmsg": "ok", "type": "image", "media_id": "media-1"},
            headers={"x-request-id": "request-upload-1"},
        )

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        first = await adapter.upload_image(IMAGE_BYTES, "image/png", "sale.png")
        second = await adapter.upload_image(IMAGE_BYTES, "image/png", "sale.png")

    assert [request.url.path for request in calls].count("/cgi-bin/gettoken") == 1
    assert first.media_id == "media-1"
    assert first.provider_request_id == "request-upload-1"
    assert first.response_code == 0
    assert first.safe_response_code == "0"
    assert repr(first).find("media-1") == -1
    assert second.media_id == "media-1"


async def test_text_and_image_send_payloads_enable_duplicate_check() -> None:
    payloads: list[dict[str, Any]] = []
    responses = iter(
        (
            _token_payload(),
            {"errcode": 0, "errmsg": "ok", "msgid": 101},
            {"errcode": 0, "errmsg": "ok", "msgid": 102},
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/message/send"):
            body = json.loads(request.content)
            assert isinstance(body, dict)
            payloads.append(body)
        return httpx.Response(200, json=next(responses))

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        text_result = await adapter.send_text(
            "sales-user",
            17,
            "【测试消息】\n今天的选题",
            "fingerprint-text",
        )
        image_result = await adapter.send_image(
            "sales-user",
            17,
            "media-1",
            "fingerprint-image",
        )

    assert payloads == [
        {
            "touser": "sales-user",
            "msgtype": "text",
            "agentid": 17,
            "text": {"content": "【测试消息】\n今天的选题"},
            "enable_duplicate_check": 1,
            "duplicate_check_interval": 1_800,
        },
        {
            "touser": "sales-user",
            "msgtype": "image",
            "agentid": 17,
            "image": {"media_id": "media-1"},
            "enable_duplicate_check": 1,
            "duplicate_check_interval": 1_800,
        },
    ]
    assert text_result.provider_request_id == "101"
    assert image_result.provider_request_id == "102"
    assert text_result.response_code == image_result.response_code == 0


async def test_invalid_token_is_refreshed_once_without_leaking_provider_body() -> None:
    token_requests = 0
    message_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests, message_requests
        if request.url.path.endswith("/gettoken"):
            token_requests += 1
            return httpx.Response(200, json=_token_payload(f"access-token-{token_requests}"))
        message_requests += 1
        if message_requests == 1:
            return httpx.Response(
                200,
                json={"errcode": 40014, "errmsg": "corp-secret-contract access-token leaked"},
            )
        assert request.url.params["access_token"] == "access-token-2"
        return httpx.Response(200, json={"errcode": 0, "msgid": 7})

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        result = await adapter.send_text("sales-user", 17, "content", "fingerprint")

    assert result.provider_request_id == "7"
    assert token_requests == 2
    assert message_requests == 2


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ({"errcode": 45009, "errmsg": "secret response body"}, WECOM_RATE_LIMITED),
        ({"errcode": -1, "errmsg": "secret response body"}, WECOM_TRANSIENT),
        ({"errcode": 81013, "errmsg": "raw recipient body"}, WECOM_PROVIDER_REJECTED),
    ],
)
async def test_provider_error_codes_are_safe_and_typed(
    payload: dict[str, object], expected_code: str
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("/gettoken"):
            return httpx.Response(200, json=_token_payload())
        calls += 1
        return httpx.Response(200, json=payload)

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=2)
    async with client:
        with pytest.raises(WeComProviderError) as raised:
            await adapter.send_text("sales-user", 17, "content", "fingerprint")

    error = raised.value
    assert error.code == expected_code
    assert error.safe_response_code == payload["errcode"]
    assert "secret response body" not in str(error)
    assert "raw recipient body" not in str(error)
    if expected_code == WECOM_RATE_LIMITED:
        assert error.retryable is True
        assert calls == 2
    elif expected_code == WECOM_TRANSIENT:
        assert error.retryable is True
        assert calls == 2
    else:
        assert error.retryable is False
        assert error.unknown is False
        assert calls == 1


async def test_send_timeout_is_unknown_and_never_retried() -> None:
    message_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal message_calls
        if request.url.path.endswith("/gettoken"):
            return httpx.Response(200, json=_token_payload())
        message_calls += 1
        raise httpx.ReadTimeout("response body must not leak", request=request)

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=3)
    async with client:
        with pytest.raises(WeComProviderError) as raised:
            await adapter.send_text("sales-user", 17, "content", "fingerprint")

    assert raised.value.code == WECOM_DELIVERY_UNKNOWN
    assert raised.value.unknown is True
    assert raised.value.retryable is False
    assert message_calls == 1
    assert "response body must not leak" not in str(raised.value)


async def test_success_response_with_invalid_recipient_is_not_marked_delivered() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/gettoken"):
            return httpx.Response(200, json=_token_payload())
        return httpx.Response(
            200,
            json={"errcode": 0, "errmsg": "ok", "invaliduser": "sales-user"},
        )

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(WeComProviderError) as raised:
            await adapter.send_text("sales-user", 17, "content", "fingerprint")

    assert raised.value.code == WECOM_PROVIDER_REJECTED
    assert raised.value.retryable is False
    assert "sales-user" not in str(raised.value)


async def test_oversized_response_and_unsupported_image_are_rejected_before_side_effect() -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(200, json=_token_payload())
        return httpx.Response(200, content=b"x" * 129, headers={"content-length": "129"})

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1, max_response_bytes=128)
    async with client:
        with pytest.raises(WeComProviderError) as oversized:
            await adapter.send_text("sales-user", 17, "content", "fingerprint")
        with pytest.raises(WeComProviderError) as unsupported:
            await adapter.upload_image(IMAGE_BYTES, "image/webp", "sale.webp")
        with pytest.raises(WeComProviderError) as mismatched:
            await adapter.upload_image(b"not-a-png", "image/png", "sale.png")

    assert oversized.value.code == WECOM_INVALID_RESPONSE
    assert unsupported.value.retryable is False
    assert mismatched.value.retryable is False
    assert requests == 2


async def test_http_client_binds_settings_without_exposing_credentials() -> None:
    settings = Settings(
        wecom_enabled=True,
        wecom_corp_id="corp-contract",
        wecom_agent_id=17,
        wecom_corp_secret=SecretStr("corp-secret-contract"),
        wecom_default_recipient_id="sales-user",
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    adapter = WeComHttpClient(settings, client)

    assert isinstance(adapter, WeComApiClient)
    assert "corp-secret-contract" not in repr(adapter)
    assert adapter._max_image_bytes == settings.wecom_max_image_bytes
    await client.aclose()
