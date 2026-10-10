"""Publication uncertainty classifications use only a fake provider transport."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.infrastructure.wechat_official_account.admin_client import (
    WeChatAdminClient,
    WeChatAdminError,
    WeChatAdminOutcomeUnknown,
)


@pytest.mark.parametrize(
    "kind",
    [
        "timeout",
        "disconnect",
        "write_error",
        "5xx",
        "redirect",
        "4xx",
        "bad_json",
        "large",
        "list",
        "empty",
        "bad_code",
        "bool_code",
        "empty_id",
        "bool_id",
        "object_id",
        "long_id",
        "nul_id",
    ],
)
async def test_ambiguous_submit_is_unknown_and_is_not_automatically_resent(kind: str) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("stable_token"):
            return httpx.Response(200, json={"access_token": "mock", "expires_in": 7200})
        errors = {
            "timeout": httpx.ReadTimeout,
            "disconnect": httpx.ReadError,
            "write_error": httpx.WriteError,
        }
        if kind in errors:
            raise errors[kind]("provider body must stay private", request=request)
        if kind in {"5xx", "redirect", "4xx"}:
            return httpx.Response(
                {"5xx": 502, "redirect": 302, "4xx": 400}[kind], json={"errcode": 48001}
            )
        if kind == "bad_json":
            return httpx.Response(200, content=b"not-json-private-provider-body")
        if kind == "large":
            return httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
        bodies: dict[str, Any] = {
            "list": [],
            "empty": {},
            "bad_code": {"errcode": "0", "publish_id": "P1"},
            "bool_code": {"errcode": False, "publish_id": "P1"},
            "empty_id": {"errcode": 0, "publish_id": ""},
            "bool_id": {"errcode": 0, "publish_id": True},
            "object_id": {"errcode": 0, "publish_id": {}},
            "long_id": {"errcode": 0, "publish_id": "x" * 65},
            "nul_id": {"errcode": 0, "publish_id": "publish\x00id"},
        }
        return httpx.Response(200, json=bodies[kind])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = WeChatAdminClient(app_id=uuid4().hex, app_secret="test", client=http)
        with pytest.raises(WeChatAdminOutcomeUnknown) as raised:
            await client.submit("M1")
    assert "private" not in raised.value.message
    assert calls.count("/cgi-bin/freepublish/submit") == 1


async def test_explicit_provider_rejection_remains_a_known_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("stable_token"):
            return httpx.Response(200, json={"access_token": "mock", "expires_in": 7200})
        return httpx.Response(200, json={"errcode": 48001, "errmsg": "private account info"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(WeChatAdminError) as raised:
            await WeChatAdminClient(app_id=uuid4().hex, app_secret="test", client=http).submit("M1")
    assert not isinstance(raised.value, WeChatAdminOutcomeUnknown)
    assert raised.value.code == 48001
    assert "private" not in raised.value.message


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"publish_status": -1},
        {"publish_status": 99},
        {"publish_status": "0"},
        {"publish_status": 0},
        {"publish_status": 0, "article_id": "x" * 129},
        {"publish_status": 0, "article_id": "article\x00id"},
        {"errcode": "0", "publish_status": 0, "article_id": "ART1"},
        {"errcode": False, "publish_status": 0, "article_id": "ART1"},
        {
            "publish_status": 0,
            "article_id": "ART1",
            "article_detail": {"item": [{"article_url": "https://example.org/\x00"}]},
        },
        {
            "publish_status": 0,
            "article_id": "ART1",
            "article_detail": {"item": [{"article_url": {"invalid": "url"}}]},
        },
    ],
)
async def test_unusable_poll_response_never_proves_a_failure(body: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("stable_token"):
            return httpx.Response(200, json={"access_token": "mock", "expires_in": 7200})
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(WeChatAdminError):
            await WeChatAdminClient(
                app_id=uuid4().hex, app_secret="test", client=http
            ).publish_status("P1")
