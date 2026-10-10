# ruff: noqa: RUF001
"""WeChat Official Account calls the 运营后台 makes: token, drafts, publishing, analytics.

Separate from the strict draft adapter (`client.py`). Every call goes to the fixed host
`api.weixin.qq.com`, reads a bounded response and turns a WeChat `errcode` into
`WeChatAdminError` with a Chinese hint. `stable_token` is called without force_refresh, so the
token is shared with the draft worker instead of invalidating it. An ambiguous response from
`freepublish/submit` raises `WeChatAdminOutcomeUnknown`: the caller must not retry it blindly.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date
from time import monotonic
from typing import Any

import httpx

WECHAT_HOST = "https://api.weixin.qq.com"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_TIMEOUT_SECONDS = 15.0

_HINTS = {
    -1: "微信系统繁忙，请稍后再试",
    40001: "访问凭证无效，请在「账号」里重新验证",
    40013: "AppID 不对",
    40125: "AppSecret 不对",
    40164: "服务器 IP 不在公众号的 IP 白名单里",
    41001: "缺少访问凭证",
    42001: "访问凭证已过期",
    45009: "今天的接口调用次数用完了",
    48001: "公众号没有这个接口的权限（需要认证或开通）",
    53503: "草稿还没准备好，或者原创声明审核中，不能发布",
    53504: "需要先到公众号后台完成相关设置才能发布",
    53505: "文章里有需要手动处理的内容，请到公众号后台发布",
    61501: "日期范围不对",
    89503: "这个 IP 调用需要管理员在公众号后台确认",
    40007: "草稿不存在或已被删除",
}


class WeChatAdminError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WeChatAdminOutcomeUnknown(WeChatAdminError):
    """The request may have reached WeChat; whether it took effect is unknown."""


def describe_error(code: int, raw: str = "") -> str:
    hint = _HINTS.get(code)
    return f"{hint}（微信错误码 {code}）" if hint else f"微信返回错误 {code}"


@dataclass(frozen=True, slots=True)
class DraftArticle:
    title: str
    author: str
    digest: str


@dataclass(frozen=True, slots=True)
class Draft:
    media_id: str
    updated_at: int
    articles: tuple[DraftArticle, ...]


@dataclass(frozen=True, slots=True)
class PublishedArticle:
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class Published:
    article_id: str
    updated_at: int
    articles: tuple[PublishedArticle, ...]


@dataclass(frozen=True, slots=True)
class PublishStatus:
    status: int
    article_id: str | None
    article_url: str | None
    fail_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _Token:
    value: str
    refresh_at: float


# One cache for the process, keyed by AppID.
_TOKENS: dict[str, _Token] = {}
_TOKEN_LOCKS: dict[str, asyncio.Lock] = {}


class WeChatAdminClient:
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        client: httpx.AsyncClient | None = None,
        clock: Any = monotonic,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._client = client
        self._clock = clock

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        uncertain_on_error: bool = False,
    ) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(trust_env=False)
        try:
            async with asyncio.timeout(_TIMEOUT_SECONDS):
                response = await client.request(
                    method,
                    f"{WECHAT_HOST}{path}",
                    params=params,
                    json=payload,
                    follow_redirects=False,
                    timeout=_TIMEOUT_SECONDS,
                )
        except (TimeoutError, httpx.TimeoutException) as error:
            if uncertain_on_error:
                raise WeChatAdminOutcomeUnknown(-2, "微信响应超时，结果未知") from error
            raise WeChatAdminError(-2, "连接微信超时，请稍后再试") from error
        except httpx.RequestError as error:
            if uncertain_on_error:
                raise WeChatAdminOutcomeUnknown(-3, "微信连接中断，发布结果未知") from error
            raise WeChatAdminError(-3, "连不上微信服务器") from error
        finally:
            if self._client is None:
                await client.aclose()
        response_error = WeChatAdminOutcomeUnknown if uncertain_on_error else WeChatAdminError
        if response.status_code != 200 or len(response.content) > _MAX_RESPONSE_BYTES:
            raise response_error(
                -4, "微信响应异常，结果未知" if uncertain_on_error else "微信响应异常"
            )
        try:
            data = json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise response_error(-5, "微信返回的内容无法确认，结果未知") from error
        if not isinstance(data, dict):
            raise response_error(-5, "微信返回的内容无法确认，结果未知")
        code = data.get("errcode")
        if type(code) is int and code != 0:
            raise WeChatAdminError(code, describe_error(code))
        if uncertain_on_error and type(code) is not int:
            raise WeChatAdminOutcomeUnknown(-5, "微信没有返回有效确认，结果未知")
        return data

    async def token(self) -> str:
        cached = _TOKENS.get(self._app_id)
        if cached is not None and cached.refresh_at > self._clock():
            return cached.value
        lock = _TOKEN_LOCKS.setdefault(self._app_id, asyncio.Lock())
        async with lock:
            cached = _TOKENS.get(self._app_id)
            if cached is not None and cached.refresh_at > self._clock():
                return cached.value
            data = await self._send(
                "POST",
                "/cgi-bin/stable_token",
                payload={
                    "grant_type": "client_credential",
                    "appid": self._app_id,
                    "secret": self._app_secret,
                    "force_refresh": False,
                },
            )
            value, expires = data.get("access_token"), data.get("expires_in")
            if not isinstance(value, str) or not isinstance(expires, int) or expires < 60:
                raise WeChatAdminError(-5, "微信没有返回访问凭证")
            _TOKENS[self._app_id] = _Token(value, self._clock() + expires - min(300, expires / 10))
            return value

    async def _authed(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        uncertain_on_error: bool = False,
    ) -> dict[str, Any]:
        token = await self.token()
        try:
            return await self._send(
                method,
                path,
                params={"access_token": token},
                payload=payload,
                uncertain_on_error=uncertain_on_error,
            )
        except WeChatAdminError as error:
            if error.code not in (40001, 42001) or isinstance(error, WeChatAdminOutcomeUnknown):
                raise
            _TOKENS.pop(self._app_id, None)
            return await self._send(
                method,
                path,
                params={"access_token": await self.token()},
                payload=payload,
                uncertain_on_error=uncertain_on_error,
            )

    async def drafts(self, *, offset: int = 0, count: int = 20) -> tuple[int, list[Draft]]:
        data = await self._authed(
            "POST", "/cgi-bin/draft/batchget", {"offset": offset, "count": count, "no_content": 1}
        )
        drafts = []
        for item in data.get("item") or []:
            content = item.get("content") or {}
            articles = tuple(
                DraftArticle(
                    title=str(news.get("title") or ""),
                    author=str(news.get("author") or ""),
                    digest=str(news.get("digest") or ""),
                )
                for news in content.get("news_item") or []
            )
            drafts.append(
                Draft(
                    media_id=str(item.get("media_id") or ""),
                    updated_at=int(item.get("update_time") or content.get("update_time") or 0),
                    articles=articles,
                )
            )
        return int(data.get("total_count") or 0), drafts

    async def published(self, *, offset: int = 0, count: int = 20) -> tuple[int, list[Published]]:
        data = await self._authed(
            "POST",
            "/cgi-bin/freepublish/batchget",
            {"offset": offset, "count": count, "no_content": 1},
        )
        items = []
        for item in data.get("item") or []:
            content = item.get("content") or {}
            items.append(
                Published(
                    article_id=str(item.get("article_id") or ""),
                    updated_at=int(item.get("update_time") or 0),
                    articles=tuple(
                        PublishedArticle(
                            title=str(news.get("title") or ""), url=str(news.get("url") or "")
                        )
                        for news in content.get("news_item") or []
                    ),
                )
            )
        return int(data.get("total_count") or 0), items

    async def submit(self, media_id: str) -> str:
        data = await self._authed(
            "POST", "/cgi-bin/freepublish/submit", {"media_id": media_id}, uncertain_on_error=True
        )
        publish_id = data.get("publish_id")
        if (
            not isinstance(publish_id, (str, int))
            or isinstance(publish_id, bool)
            or not str(publish_id).strip()
            or len(str(publish_id)) > 64
            or "\x00" in str(publish_id)
        ):
            raise WeChatAdminOutcomeUnknown(-5, "微信没有返回有效发布编号，结果未知")
        return str(publish_id)

    async def publish_status(self, publish_id: str) -> PublishStatus:
        data = await self._authed("POST", "/cgi-bin/freepublish/get", {"publish_id": publish_id})
        if "errcode" in data and type(data["errcode"]) is not int:
            raise WeChatAdminError(-5, "微信没有返回有效发布状态")
        status = data.get("publish_status")
        if type(status) is not int or status not in range(7):
            raise WeChatAdminError(-5, "微信没有返回有效发布状态")
        detail = data.get("article_detail") or {}
        if not isinstance(detail, dict):
            raise WeChatAdminError(-5, "微信没有返回有效文章信息")
        items = detail.get("item") or []
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise WeChatAdminError(-5, "微信没有返回有效文章信息")
        urls = [item["article_url"] for item in items if item.get("article_url")]
        if any(not isinstance(url, str) or "\x00" in url for url in urls):
            raise WeChatAdminError(-5, "微信没有返回有效文章信息")
        url = next(iter(urls), None)
        article_id = data.get("article_id")
        # Keep an unusable receipt on the bounded polling-error path. Otherwise PostgreSQL
        # rejects it after the provider call and the job can stay publishing indefinitely.
        if status == 0 and (
            not isinstance(article_id, str)
            or not article_id.strip()
            or len(article_id) > 128
            or "\x00" in article_id
        ):
            raise WeChatAdminError(-5, "微信成功响应缺少有效文章编号，请重新查询")
        fail_indexes = data.get("fail_idx") or []
        if not isinstance(fail_indexes, list):
            raise WeChatAdminError(-5, "微信没有返回有效发布状态")
        return PublishStatus(
            status=status,
            article_id=str(article_id) if article_id else None,
            article_url=url,
            fail_indexes=tuple(index for index in fail_indexes if type(index) is int),
        )

    async def article_day(self, day: date) -> list[dict[str, Any]]:
        data = await self._authed(
            "POST",
            "/datacube/getarticletotaldetail",
            {"begin_date": day.isoformat(), "end_date": day.isoformat()},
        )
        return list(data.get("list") or [])

    async def account_day(self, day: date) -> list[dict[str, Any]]:
        data = await self._authed(
            "POST",
            "/datacube/getbizsummary",
            {"begin_date": day.isoformat(), "end_date": day.isoformat()},
        )
        return list(data.get("list") or [])


def forget_token(app_id: str) -> None:
    _TOKENS.pop(app_id, None)


__all__ = [
    "Draft",
    "DraftArticle",
    "PublishStatus",
    "Published",
    "PublishedArticle",
    "WeChatAdminClient",
    "WeChatAdminError",
    "WeChatAdminOutcomeUnknown",
    "describe_error",
    "forget_token",
]
