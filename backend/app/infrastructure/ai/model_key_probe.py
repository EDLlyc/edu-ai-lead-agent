# ruff: noqa: RUF001
"""One tiny request per provider, to prove a model key works before it replaces the current one.

- 智谱: a chat completion capped at 1 output token (thinking off), on the configured chat model.
- Comfly: `GET /v1/models`, which costs nothing.
- 阿里云百炼: a short text embedding on the pinned multimodal endpoint.

The key is only placed in the Authorization header. Provider messages are shortened and any echo
of the key is removed before they reach the page.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx

from app.core.config import Settings
from app.domain.visual_retrieval import VISUAL_EMBEDDING_DIMENSIONS, VISUAL_EMBEDDING_MODEL

PROBE_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True, slots=True)
class ProbeResult:
    ok: bool
    latency_ms: int
    message: str


def _request(provider_id: str, settings: Settings) -> tuple[str, str, dict[str, Any] | None]:
    if provider_id == "zhipu":
        base = (settings.ai_platform_base_url or "").strip().rstrip("/")
        if not base:
            raise LookupError("服务器没有配置智谱的接口地址")
        return (
            "POST",
            f"{base}/chat/completions",
            {
                "model": settings.ai_chat_model,
                "messages": [{"role": "user", "content": "回复 1"}],
                "thinking": {"type": "disabled"},
                "max_tokens": 1,
                "stream": False,
            },
        )
    if provider_id == "comfly":
        return "GET", f"{settings.comfly_base_url.strip().rstrip('/')}/v1/models", None
    if provider_id == "alibaba-visual":
        endpoint = settings.visual_embedding_endpoint
        if endpoint is None or not endpoint.get_secret_value().strip():
            raise LookupError("服务器没有配置图片向量的接口地址")
        return (
            "POST",
            endpoint.get_secret_value().strip(),
            {
                "model": VISUAL_EMBEDDING_MODEL,
                "input": {"contents": [{"text": "连接测试"}]},
                "parameters": {"dimension": VISUAL_EMBEDDING_DIMENSIONS, "output_type": "dense"},
            },
        )
    raise LookupError("没有这个模型服务")


def _provider_message(response: httpx.Response, api_key: str) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    message: Any = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
        elif isinstance(error, str):
            message = error
        message = message or body.get("message") or body.get("msg")
    if not isinstance(message, str):
        return ""
    return message.replace(api_key, "••••")[:120]


def _status_message(status: int) -> str:
    if status in {401, 403}:
        return "key 不对，或者没有这个模型的权限"
    if status == 429:
        return "请求太多或余额不足"
    return f"服务返回 {status}"


async def probe_model_key(
    provider_id: str,
    api_key: str,
    *,
    settings: Settings,
    http: httpx.AsyncClient | None = None,
) -> ProbeResult:
    try:
        method, url, payload = _request(provider_id, settings)
    except LookupError as error:
        return ProbeResult(ok=False, latency_ms=0, message=str(error))
    client = http or httpx.AsyncClient()
    started = perf_counter()
    try:
        response = await client.request(
            method,
            url,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        return ProbeResult(ok=False, latency_ms=_ms(started), message="连接超时（20 秒）")
    except httpx.HTTPError:
        return ProbeResult(ok=False, latency_ms=_ms(started), message="连不上这个服务")
    finally:
        if http is None:
            await client.aclose()
    latency = _ms(started)
    if 200 <= response.status_code < 300:
        return ProbeResult(ok=True, latency_ms=latency, message="连接成功")
    detail = _provider_message(response, api_key)
    text = _status_message(response.status_code)
    return ProbeResult(
        ok=False, latency_ms=latency, message=f"{text}：{detail}" if detail else text
    )


def _ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


__all__ = ["PROBE_TIMEOUT_SECONDS", "ProbeResult", "probe_model_key"]
