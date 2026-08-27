#!/usr/bin/env python3
"""Read-only preflight for the local IP asset demo stack."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

_DEFAULT_API_BASE = "http://127.0.0.1:8000"
_DEFAULT_SITE_URL = "http://127.0.0.1:5173/ip-assets"
_SEARCH_BODY = {
    "message": "小赛开心庆祝，适合社群推送",
    "prior_turns": [],
    "limit": 8,
}
_MIN_THUMBNAIL_CACHE_SECONDS = 7 * 24 * 60 * 60
_MAX_GALLERY_PAGE_SIZE = 16


class PreflightError(RuntimeError):
    """A bounded operator-facing preflight failure."""


@dataclass(frozen=True, slots=True)
class HttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]
Requester = Callable[[str, str, bytes | None], HttpResult]


def run_preflight(
    *,
    api_base: str,
    site_url: str,
    runner: Runner,
    requester: Requester,
) -> tuple[str, ...]:
    api_base = _loopback_base(api_base)
    site_url = _loopback_site(site_url)
    compose_rows = _compose_rows(runner)
    _require_compose_service(compose_rows, "postgres", "PostgreSQL")
    _require_compose_service(compose_rows, "minio", "MinIO")
    worker_count = _worker_count(compose_rows, runner)
    if worker_count != 1:
        raise PreflightError(
            f"IP worker 数量为 {worker_count}，需要恰好 1 个；请只启动一次 make ip-asset-worker"
        )

    capabilities = _json_request(
        requester, "GET", f"{api_base}/api/v1/ip-assets/capabilities"
    )
    required_capabilities = {
        "enabled": True,
        "semantic_search_available": True,
        "generation_available": True,
        "recognition_available": True,
    }
    if any(
        capabilities.get(key) is not value
        for key, value in required_capabilities.items()
    ):
        raise PreflightError(
            "API 演示能力未全部就绪；请检查图库、语义检索、识别和生图开关及 provider 配置"
        )
    if (
        capabilities.get("authentication") != "none"
        or capabilities.get("deployment_boundary") != "company_intranet"
    ):
        raise PreflightError("API 安全边界与公司内网无鉴权演示合同不一致")

    gallery = _json_request(
        requester,
        "GET",
        f"{api_base}/api/v1/ip-assets?limit={_MAX_GALLERY_PAGE_SIZE}",
    )
    items = gallery.get("items")
    if (
        not isinstance(items, list)
        or not items
        or len(items) > _MAX_GALLERY_PAGE_SIZE
        or not all(isinstance(item, dict) for item in items)
    ):
        raise PreflightError("共享图库首个分页不是 1–16 项的有效资产列表")
    ready_item = next(
        (item for item in items if item.get("status") == "ready"),
        None,
    )
    if ready_item is None:
        raise PreflightError("共享图库没有可用于演示的 ready 资产")
    thumbnail_path = ready_item.get("thumbnail_url")
    thumbnail_url = _same_origin_thumbnail(api_base, thumbnail_path)
    thumbnail = requester("GET", thumbnail_url, None)
    content_type = (
        thumbnail.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    cache_control = thumbnail.headers.get("cache-control", "").lower()
    etag = thumbnail.headers.get("etag", "")
    vary = {
        item.strip().casefold()
        for item in thumbnail.headers.get("vary", "").split(",")
        if item.strip()
    }
    if (
        thumbnail.status != 200
        or content_type != "image/webp"
        or not _has_webp_signature(thumbnail.body)
    ):
        raise PreflightError("图库缩略图未返回有效 WebP")
    if (
        "private" not in cache_control
        or _cache_max_age(cache_control) < _MIN_THUMBNAIL_CACHE_SECONDS
        or "immutable" not in cache_control
        or not _is_strong_etag(etag)
        or "x-ip-profile-token" not in vary
    ):
        raise PreflightError("缩略图私有缓存隔离、长期缓存或强 ETag 合同未生效")

    search = _json_request(
        requester,
        "POST",
        f"{api_base}/api/v1/ip-assets/search/text",
        payload=_SEARCH_BODY,
    )
    search_items = search.get("items")
    if search.get("mode") != "semantic" or not isinstance(search_items, list):
        raise PreflightError("只读文本检索未返回语义 + 元数据结果")
    if len(search_items) > 8:
        raise PreflightError("只读文本检索返回数量超过演示上限 8")

    return (
        "PASS API：图库、语义检索、识别与生图能力已配置",
        "PASS PostgreSQL：运行中",
        "PASS MinIO：运行中",
        "PASS IP worker：恰好 1 个运行实例",
        f"PASS 图库：首个分页可读（本页 {len(items)} 项）",
        "PASS 缩略图：WebP、强 ETag、长期私有缓存有效",
        f"PASS 只读检索：semantic（{len(search_items)} 项）",
        f"READY {site_url}",
    )


def _json_request(
    requester: Requester,
    method: str,
    url: str,
    *,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    result = requester(method, url, body)
    if result.status != 200:
        raise PreflightError("API 只读检查未返回成功状态")
    try:
        decoded = json.loads(result.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PreflightError("API 只读检查返回了无效 JSON") from error
    if not isinstance(decoded, dict):
        raise PreflightError("API 只读检查返回结构不正确")
    return decoded


def _compose_rows(runner: Runner) -> tuple[dict[str, Any], ...]:
    completed = runner(["docker", "compose", "ps", "--format", "json"])
    if completed.returncode != 0:
        raise PreflightError("无法读取 Compose 状态；请先启动 PostgreSQL 与 MinIO")
    try:
        return parse_compose_ps(completed.stdout)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise PreflightError("Compose 状态格式无法识别") from error


def parse_compose_ps(output: str) -> tuple[dict[str, Any], ...]:
    stripped = output.strip()
    if not stripped:
        return ()
    if stripped.startswith("["):
        parsed = json.loads(stripped)
        if not isinstance(parsed, list) or not all(
            isinstance(item, dict) for item in parsed
        ):
            raise ValueError("compose JSON is not a row list")
        return tuple(parsed)
    rows = tuple(json.loads(line) for line in stripped.splitlines() if line.strip())
    if not all(isinstance(item, dict) for item in rows):
        raise ValueError("compose JSON line is not an object")
    return rows


def _require_compose_service(
    rows: tuple[dict[str, Any], ...], service: str, label: str
) -> None:
    matches = [row for row in rows if row.get("Service") == service]
    if len(matches) != 1 or str(matches[0].get("State", "")).lower() != "running":
        raise PreflightError(f"{label} 未运行；请执行 make infra-up")
    health = str(matches[0].get("Health", "")).lower()
    if health and health != "healthy":
        raise PreflightError(f"{label} 健康检查未通过")


def _worker_count(rows: tuple[dict[str, Any], ...], runner: Runner) -> int:
    compose_workers = [
        row
        for row in rows
        if row.get("Service") == "ip-asset-worker"
        and str(row.get("State", "")).lower() == "running"
    ]
    container_pids: set[int] = set()
    for row in compose_workers:
        container_id = row.get("ID")
        if not isinstance(container_id, str) or not container_id:
            continue
        inspected = runner(
            ["docker", "inspect", "--format", "{{.State.Pid}}", container_id]
        )
        if inspected.returncode == 0 and inspected.stdout.strip().isdigit():
            container_pids.add(int(inspected.stdout.strip()))

    process_rows = _worker_process_rows(runner)
    matching_pids = {pid for pid, _parent, _command in process_rows}
    host_roots = {
        pid
        for pid, parent, _command in process_rows
        if parent not in matching_pids and pid not in container_pids
    }
    return len(compose_workers) + len(host_roots)


def _worker_process_rows(runner: Runner) -> tuple[tuple[int, int, str], ...]:
    completed = runner(["ps", "-eo", "pid=,ppid=,args="])
    if completed.returncode != 0:
        raise PreflightError("无法确认 IP worker 进程数量")
    rows: list[tuple[int, int, str]] = []
    for line in completed.stdout.splitlines():
        parts = line.strip().split(maxsplit=2)
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        command = parts[2]
        if "app.ip_asset_worker_main" not in command:
            continue
        if "ip_asset_demo_preflight.py" in command:
            continue
        rows.append((int(parts[0]), int(parts[1]), command))
    return tuple(rows)


def _same_origin_thumbnail(api_base: str, value: object) -> str:
    if not isinstance(value, str) or not value.startswith("/api/v1/ip-assets/"):
        raise PreflightError("图库没有返回安全的版本化缩略图地址")
    resolved = urljoin(f"{api_base}/", value)
    if (
        urlsplit(resolved).netloc != urlsplit(api_base).netloc
        or "/thumbnail" not in value
    ):
        raise PreflightError("缩略图地址不在本地 API 同源边界内")
    return resolved


def _has_webp_signature(body: bytes) -> bool:
    return len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP"


def _cache_max_age(cache_control: str) -> int:
    match = re.search(r"(?:^|,)\s*max-age\s*=\s*(\d+)\s*(?:,|$)", cache_control)
    return int(match.group(1)) if match is not None else -1


def _is_strong_etag(value: str) -> bool:
    return (
        len(value) >= 2
        and value.startswith('"')
        and value.endswith('"')
        and not value.startswith("W/")
    )


def _loopback_base(value: str) -> str:
    parsed = urlsplit(value.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise PreflightError("演示预检只允许访问 loopback API")
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path
    ):
        raise PreflightError(
            "演示 API 地址必须是不含凭据、路径或参数的 loopback origin"
        )
    return value.rstrip("/")


def _loopback_site(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise PreflightError("演示站点必须是 loopback 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise PreflightError("演示站点地址不得包含凭据、参数或片段")
    if parsed.path.rstrip("/") != "/ip-assets":
        raise PreflightError("演示站点地址必须指向 /ip-assets")
    return value


def _request(method: str, url: str, body: bytes | None) -> HttpResult:
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            response_body = response.read(32 * 1024 * 1024 + 1)
            if len(response_body) > 32 * 1024 * 1024:
                raise PreflightError("本地 API 检查响应超过安全上限")
            return HttpResult(
                status=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=response_body,
            )
    except (HTTPError, URLError, TimeoutError) as error:
        raise PreflightError("无法连接本地 IP 资产 API") from error


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def main() -> int:
    try:
        lines = run_preflight(
            api_base=os.environ.get("IP_ASSET_DEMO_API_BASE_URL", _DEFAULT_API_BASE),
            site_url=os.environ.get("IP_ASSET_DEMO_SITE_URL", _DEFAULT_SITE_URL),
            runner=_run,
            requester=_request,
        )
    except (PreflightError, subprocess.TimeoutExpired):
        error = sys.exception()
        message = (
            str(error) if isinstance(error, PreflightError) else "本地进程检查超时"
        )
        print(f"FAIL {message}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
