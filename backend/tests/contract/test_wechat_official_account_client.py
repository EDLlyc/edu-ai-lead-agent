from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from app.application.ports.wechat_official_account import (
    WECHAT_MP_INVALID_INPUT,
    WECHAT_MP_INVALID_RESPONSE,
    WECHAT_MP_MAX_INLINE_IMAGE_BYTES,
    WECHAT_MP_MAX_THUMB_BYTES,
    WECHAT_MP_OUTCOME_UNKNOWN,
    WECHAT_MP_PROVIDER_REJECTED,
    WECHAT_MP_TOKEN_INVALID,
    WeChatDraftArticleRequest,
    WeChatMpConfigurationError,
    WeChatOfficialAccountError,
)
from app.core.config import Settings
from app.infrastructure.wechat_official_account.client import (
    WeChatOfficialAccountApiClient,
    WeChatOfficialAccountHttpClient,
)
from pydantic import SecretStr, ValidationError

PNG_BYTES = b"\x89PNG\r\n\x1a\n"
JPEG_BYTES = b"\xff\xd8\xff\xd9\x00\x00\x00\x00"
APP_ID = "wx-contract-app-id"
APP_SECRET = "wx-contract-app-secret"
TOKEN = "wx-contract-access-token"


def _adapter(
    transport: httpx.AsyncBaseTransport,
    *,
    clock: Any | None = None,
    max_response_bytes: int = 64 * 1024,
) -> tuple[WeChatOfficialAccountApiClient, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=transport)
    kwargs: dict[str, object] = {}
    if clock is not None:
        kwargs["clock"] = clock
    return (
        WeChatOfficialAccountApiClient(
            client=client,
            app_id=SecretStr(APP_ID),
            app_secret=SecretStr(APP_SECRET),
            timeout_seconds=1,
            max_response_bytes=max_response_bytes,
            **kwargs,  # type: ignore[arg-type]
        ),
        client,
    )


def _token_payload(token: str = TOKEN, *, expires_in: int = 7200) -> dict[str, object]:
    return {"access_token": token, "expires_in": expires_in}


async def test_exact_stable_token_upload_and_single_article_draft_contract() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "POST"
        if request.url.path == "/cgi-bin/stable_token":
            assert request.url.query == b""
            assert json.loads(request.content) == {
                "grant_type": "client_credential",
                "appid": APP_ID,
                "secret": APP_SECRET,
                "force_refresh": False,
            }
            return httpx.Response(200, json=_token_payload())
        assert request.url.params["access_token"] == TOKEN
        if request.url.path == "/cgi-bin/media/uploadimg":
            assert request.headers["content-type"].startswith("multipart/form-data;")
            assert b'name="media"' in request.content
            assert b'filename="body.png"' in request.content
            assert PNG_BYTES in request.content
            return httpx.Response(200, json={"url": "http://mmbiz.qpic.cn/body.png?a=1&b=2"})
        if request.url.path == "/cgi-bin/material/add_material":
            assert request.url.params["type"] == "thumb"
            assert b'filename="cover-thumb.jpg"' in request.content
            assert b"image/jpeg" in request.content
            assert JPEG_BYTES in request.content
            return httpx.Response(200, json={"media_id": "thumb-media-id"})
        assert request.url.path == "/cgi-bin/draft/add"
        payload = json.loads(request.content)
        assert payload == {
            "articles": [
                {
                    "article_type": "news",
                    "title": "每周科创观察",
                    "author": "赛先生",
                    "digest": "一篇经过本地质量门禁的草稿。",
                    "content": '<p><img src="https://mmbiz.qpic.cn/body.png"></p>',
                    "thumb_media_id": "thumb-media-id",
                    "need_open_comment": 0,
                    "only_fans_can_comment": 0,
                    "content_source_url": "https://example.com/source",
                }
            ]
        }
        return httpx.Response(200, json={"media_id": "draft-media-id"})

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        inline = await adapter.upload_inline_image(PNG_BYTES, "image/png", "body.png")
        thumb = await adapter.upload_thumb(JPEG_BYTES, "image/jpeg", "cover-thumb.jpg")
        created = await adapter.add_draft(
            WeChatDraftArticleRequest(
                title="每周科创观察",
                author="赛先生",
                digest="一篇经过本地质量门禁的草稿。",
                content='<p><img src="https://mmbiz.qpic.cn/body.png"></p>',
                content_source_url="https://example.com/source",
                thumb_media_id=thumb.media_id,
                need_open_comment=False,
                only_fans_can_comment=False,
            )
        )

    assert inline.url == "https://mmbiz.qpic.cn/body.png?a=1&b=2"
    assert created.media_id == "draft-media-id"
    assert [request.url.path for request in calls].count("/cgi-bin/stable_token") == 1
    assert [request.url.path for request in calls] == [
        "/cgi-bin/stable_token",
        "/cgi-bin/media/uploadimg",
        "/cgi-bin/material/add_material",
        "/cgi-bin/draft/add",
    ]
    assert all("freepublish" not in request.url.path for request in calls)


async def test_token_cache_expires_early_and_invalid_token_forces_one_refresh() -> None:
    now = [0.0]
    token_calls: list[dict[str, object]] = []
    upload_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal upload_calls
        if request.url.path == "/cgi-bin/stable_token":
            payload = json.loads(request.content)
            token_calls.append(payload)
            return httpx.Response(
                200,
                json=_token_payload(f"token-{len(token_calls)}", expires_in=100),
            )
        upload_calls += 1
        if upload_calls == 3:
            return httpx.Response(200, json={"errcode": 40014, "errmsg": APP_SECRET})
        return httpx.Response(200, json={"url": "https://mmbiz.qpic.cn/body.jpg"})

    adapter, client = _adapter(httpx.MockTransport(handler), clock=lambda: now[0])
    async with client:
        await adapter.upload_inline_image(JPEG_BYTES, "image/jpeg", "body.jpg")
        now[0] = 89
        await adapter.upload_inline_image(JPEG_BYTES, "image/jpeg", "body.jpg")
        now[0] = 90
        await adapter.upload_inline_image(JPEG_BYTES, "image/jpeg", "body.jpg")

    assert [payload["force_refresh"] for payload in token_calls] == [False, False, True]
    assert upload_calls == 4


async def test_second_invalid_token_response_is_terminal_after_one_refresh() -> None:
    token_calls = 0
    upload_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, upload_calls
        if request.url.path == "/cgi-bin/stable_token":
            token_calls += 1
            return httpx.Response(200, json=_token_payload(f"token-{token_calls}"))
        upload_calls += 1
        return httpx.Response(200, json={"errcode": 42001, "errmsg": TOKEN})

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        with pytest.raises(WeChatOfficialAccountError) as raised:
            await adapter.upload_inline_image(PNG_BYTES, "image/png", "body.png")

    assert raised.value.code == WECHAT_MP_TOKEN_INVALID
    assert TOKEN not in str(raised.value)
    assert token_calls == 2
    assert upload_calls == 2


async def test_concurrent_invalid_token_responses_share_one_forced_refresh() -> None:
    token_payloads: list[dict[str, object]] = []
    stale_uploads = 0
    refreshed_uploads = 0
    both_stale_requests_arrived = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal stale_uploads, refreshed_uploads
        if request.url.path == "/cgi-bin/stable_token":
            payload = json.loads(request.content)
            token_payloads.append(payload)
            return httpx.Response(
                200,
                json=_token_payload(f"token-{len(token_payloads)}"),
            )
        if request.url.params["access_token"] == "token-1":
            stale_uploads += 1
            if stale_uploads == 2:
                both_stale_requests_arrived.set()
            await both_stale_requests_arrived.wait()
            return httpx.Response(200, json={"errcode": 40014})
        refreshed_uploads += 1
        return httpx.Response(200, json={"url": "https://mmbiz.qpic.cn/body.jpg"})

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        results = await asyncio.gather(
            adapter.upload_inline_image(JPEG_BYTES, "image/jpeg", "one.jpg"),
            adapter.upload_inline_image(JPEG_BYTES, "image/jpeg", "two.jpg"),
        )

    assert [result.url for result in results] == [
        "https://mmbiz.qpic.cn/body.jpg",
        "https://mmbiz.qpic.cn/body.jpg",
    ]
    assert [payload["force_refresh"] for payload in token_payloads] == [False, True]
    assert stale_uploads == 2
    assert refreshed_uploads == 2


@pytest.mark.parametrize(
    ("operation", "body", "media_type", "expected_code"),
    [
        (
            "inline",
            b"\xff\xd8\xff" + b"x" * (WECHAT_MP_MAX_INLINE_IMAGE_BYTES - 2),
            "image/jpeg",
            WECHAT_MP_INVALID_INPUT,
        ),
        (
            "thumb",
            b"\xff\xd8\xff" + b"x" * (WECHAT_MP_MAX_THUMB_BYTES - 2),
            "image/jpeg",
            WECHAT_MP_INVALID_INPUT,
        ),
        ("thumb", PNG_BYTES, "image/png", WECHAT_MP_INVALID_INPUT),
    ],
)
async def test_operation_specific_image_limits_fail_before_token_request(
    operation: str,
    body: bytes,
    media_type: str,
    expected_code: str,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        with pytest.raises(WeChatOfficialAccountError) as raised:
            if operation == "inline":
                await adapter.upload_inline_image(body, media_type, "body.jpg")
            else:
                await adapter.upload_thumb(body, media_type, "cover.jpg")

    assert raised.value.code == expected_code
    assert calls == 0


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (httpx.Response(200, content=b'{"url":"one","url":"two"}'), WECHAT_MP_INVALID_RESPONSE),
        (
            httpx.Response(
                200,
                content=b'{"url":"https://mmbiz.qpic.cn/body.jpg","extra":NaN}',
            ),
            WECHAT_MP_INVALID_RESPONSE,
        ),
        (
            httpx.Response(200, json={"errcode": 48001, "errmsg": APP_SECRET}),
            WECHAT_MP_PROVIDER_REJECTED,
        ),
    ],
)
async def test_bad_responses_are_typed_and_never_leak_credentials_or_urls(
    response: httpx.Response,
    expected_code: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/stable_token":
            return httpx.Response(200, json=_token_payload())
        return response

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        with pytest.raises(WeChatOfficialAccountError) as raised:
            await adapter.upload_inline_image(PNG_BYTES, "image/png", "body.png")

    rendered = f"{raised.value!r} {raised.value}"
    assert raised.value.code == expected_code
    assert APP_ID not in rendered
    assert APP_SECRET not in rendered
    assert TOKEN not in rendered
    assert "api.weixin.qq.com" not in rendered


async def test_http_401_does_not_refresh_without_an_explicit_token_errcode() -> None:
    token_calls = 0
    upload_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, upload_calls
        if request.url.path == "/cgi-bin/stable_token":
            token_calls += 1
            return httpx.Response(200, json=_token_payload())
        upload_calls += 1
        return httpx.Response(401, content=b"must-not-be-projected")

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        with pytest.raises(WeChatOfficialAccountError) as raised:
            await adapter.upload_inline_image(PNG_BYTES, "image/png", "body.png")

    assert raised.value.code == WECHAT_MP_PROVIDER_REJECTED
    assert raised.value.provider_code == 401
    assert token_calls == 1
    assert upload_calls == 1


@pytest.mark.parametrize(
    "article",
    [
        WeChatDraftArticleRequest(
            title="题" * 33,
            author="赛先生",
            digest="摘要",
            content="<p>正文</p>",
            content_source_url=None,
            thumb_media_id="thumb",
            need_open_comment=False,
            only_fans_can_comment=False,
        ),
        WeChatDraftArticleRequest(
            title="标题",
            author="作" * 17,
            digest="摘要",
            content="<p>正文</p>",
            content_source_url=None,
            thumb_media_id="thumb",
            need_open_comment=False,
            only_fans_can_comment=False,
        ),
        WeChatDraftArticleRequest(
            title="标题",
            author="赛先生",
            digest="摘要",
            content="字" * 20_000,
            content_source_url=None,
            thumb_media_id="thumb",
            need_open_comment=False,
            only_fans_can_comment=False,
        ),
        WeChatDraftArticleRequest(
            title="标题",
            author="赛先生",
            digest="摘要",
            content="<p>正文</p>",
            content_source_url="https://example.com/" + "a" * 1024,
            thumb_media_id="thumb",
            need_open_comment=False,
            only_fans_can_comment=False,
        ),
    ],
)
async def test_documented_draft_field_limits_fail_before_token_request(
    article: WeChatDraftArticleRequest,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        with pytest.raises(WeChatOfficialAccountError) as raised:
            await adapter.add_draft(article)

    assert raised.value.code == WECHAT_MP_INVALID_INPUT
    assert calls == 0


async def test_write_timeout_is_unknown_without_automatic_retry_or_raw_detail() -> None:
    upload_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal upload_calls
        if request.url.path == "/cgi-bin/stable_token":
            return httpx.Response(200, json=_token_payload())
        upload_calls += 1
        raise httpx.ReadTimeout(
            f"must not leak {TOKEN}",
            request=request,
        )

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        with pytest.raises(WeChatOfficialAccountError) as raised:
            await adapter.upload_inline_image(PNG_BYTES, "image/png", "body.png")

    assert raised.value.code == WECHAT_MP_OUTCOME_UNKNOWN
    assert raised.value.unknown is True
    assert TOKEN not in str(raised.value)
    assert upload_calls == 1


@pytest.mark.parametrize("host", ["mmbiz.qpic.cn", "mmecoa.qpic.cn"])
async def test_inline_image_response_accepts_exact_wechat_cdn_hosts(host: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/stable_token":
            return httpx.Response(200, json=_token_payload())
        return httpx.Response(200, json={"url": f"http://{host}/body.png?a=1&b=2"})

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        uploaded = await adapter.upload_inline_image(PNG_BYTES, "image/png", "body.png")

    assert uploaded.url == f"https://{host}/body.png?a=1&b=2"


@pytest.mark.parametrize(
    "provider_url",
    [
        "https://evil.example/body.png",
        "https://arbitrary.qpic.cn/body.png",
        "https://mmbiz.qpic.cn.evil.example/body.png",
        "https://user@mmbiz.qpic.cn/body.png",
        "https://mmbiz.qpic.cn:443/body.png",
        "https://mmbiz.qpic.cn/body.png#fragment",
        "https://mmbiz.qpic.cn/body\x7f.png",
    ],
)
async def test_inline_image_response_rejects_non_exact_or_unsafe_urls(
    provider_url: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/stable_token":
            return httpx.Response(200, json=_token_payload())
        return httpx.Response(200, json={"url": provider_url})

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        with pytest.raises(WeChatOfficialAccountError) as raised:
            await adapter.upload_inline_image(PNG_BYTES, "image/png", "body.png")

    assert raised.value.code == WECHAT_MP_INVALID_RESPONSE
    assert provider_url not in str(raised.value)


async def test_response_size_and_settings_are_fail_closed() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if request.url.path == "/cgi-bin/stable_token":
            return httpx.Response(200, json=_token_payload())
        return httpx.Response(200, content=b"x" * 1025, headers={"content-length": "1025"})

    adapter, client = _adapter(httpx.MockTransport(handler), max_response_bytes=1024)
    async with client:
        with pytest.raises(WeChatOfficialAccountError) as oversized:
            await adapter.upload_inline_image(PNG_BYTES, "image/png", "body.png")
    assert oversized.value.code == WECHAT_MP_INVALID_RESPONSE
    assert requests == 2

    disabled = Settings(_env_file=None)  # type: ignore[call-arg]
    bound_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(WeChatMpConfigurationError):
        WeChatOfficialAccountHttpClient(disabled, bound_client)
    await bound_client.aclose()

    enabled = Settings(
        _env_file=None,  # type: ignore[call-arg]
        wechat_mp_enabled=True,
        wechat_mp_app_id=SecretStr(APP_ID),
        wechat_mp_app_secret=SecretStr(APP_SECRET),
    )
    assert "wx-contract" not in repr(enabled)
    with pytest.raises(ValidationError, match="development-only"):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            app_env="production",
            wechat_mp_enabled=True,
            wechat_mp_app_id=SecretStr(APP_ID),
            wechat_mp_app_secret=SecretStr(APP_SECRET),
        )
