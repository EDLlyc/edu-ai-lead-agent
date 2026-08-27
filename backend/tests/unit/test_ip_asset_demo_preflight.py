from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.ip_asset_demo_preflight import (
    HttpResult,
    PreflightError,
    parse_compose_ps,
    run_preflight,
)


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, "")


def _compose_output(*, workers: int = 1) -> str:
    rows = [
        {"ID": "postgres-id", "Service": "postgres", "State": "running", "Health": "healthy"},
        {"ID": "minio-id", "Service": "minio", "State": "running", "Health": "healthy"},
    ]
    rows.extend(
        {
            "ID": f"worker-{index}",
            "Service": "ip-asset-worker",
            "State": "running",
            "Health": "",
        }
        for index in range(workers)
    )
    return "\n".join(json.dumps(row) for row in rows)


def _runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    if command[:4] == ["docker", "compose", "ps", "--format"]:
        return _completed(_compose_output())
    if command[:2] == ["docker", "inspect"]:
        return _completed("4100\n")
    if command[:3] == ["ps", "-eo", "pid=,ppid=,args="]:
        return _completed("4100 1 python -m app.ip_asset_worker_main\n")
    raise AssertionError(f"unexpected command: {command}")


def test_read_only_preflight_checks_the_complete_demo_path() -> None:
    calls: list[tuple[str, str, bytes | None]] = []

    def requester(method: str, url: str, body: bytes | None) -> HttpResult:
        calls.append((method, url, body))
        if url.endswith("/capabilities"):
            payload = {
                "enabled": True,
                "authentication": "none",
                "deployment_boundary": "company_intranet",
                "semantic_search_available": True,
                "generation_available": True,
                "recognition_available": True,
            }
            return _json_result(payload)
        if url.endswith("?limit=16"):
            return _json_result(
                {
                    "items": [
                        {
                            "asset_ref": "ipa_11111111111111111111",
                            "status": "ready",
                            "thumbnail_url": (
                                "/api/v1/ip-assets/ipa_11111111111111111111/thumbnail?v=1"
                            ),
                        }
                    ],
                    "next_cursor": None,
                }
            )
        if "/thumbnail?v=1" in url:
            return HttpResult(
                status=200,
                headers={
                    "content-type": "image/webp",
                    "cache-control": "private, max-age=604800, immutable",
                    "etag": '"abc"',
                    "vary": "X-IP-Profile-Token",
                },
                body=b"RIFF\x04\x00\x00\x00WEBP",
            )
        if url.endswith("/search/text"):
            return _json_result({"mode": "semantic", "degraded_reason": None, "items": []})
        raise AssertionError(f"unexpected URL: {url}")

    lines = run_preflight(
        api_base="http://127.0.0.1:8000",
        site_url="http://127.0.0.1:5173/ip-assets",
        runner=_runner,
        requester=requester,
    )

    assert lines[-1] == "READY http://127.0.0.1:5173/ip-assets"
    assert [(method, url.rsplit("/", 1)[-1]) for method, url, _body in calls] == [
        ("GET", "capabilities"),
        ("GET", "ip-assets?limit=16"),
        ("GET", "thumbnail?v=1"),
        ("POST", "text"),
    ]
    assert all("generations" not in url and "downloads" not in url for _method, url, _ in calls)
    output = "\n".join(lines)
    assert "小赛开心庆祝" not in output
    assert "object_key" not in output


def test_preflight_rejects_duplicate_effective_workers() -> None:
    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[:4] == ["docker", "compose", "ps", "--format"]:
            return _completed(_compose_output())
        if command[:2] == ["docker", "inspect"]:
            return _completed("4100\n")
        if command[:3] == ["ps", "-eo", "pid=,ppid=,args="]:
            return _completed(
                "4100 1 python -m app.ip_asset_worker_main\n"
                "5200 1 conda run --name edu-ai python -m app.ip_asset_worker_main\n"
                "5201 5200 python -m app.ip_asset_worker_main\n"
            )
        raise AssertionError

    with pytest.raises(PreflightError, match="数量为 2"):
        run_preflight(
            api_base="http://127.0.0.1:8000",
            site_url="http://127.0.0.1:5173/ip-assets",
            runner=runner,
            requester=lambda *_args: (_ for _ in ()).throw(AssertionError),
        )


def test_parse_compose_ps_accepts_array_and_json_lines() -> None:
    rows = [{"Service": "postgres", "State": "running"}]

    assert parse_compose_ps(json.dumps(rows)) == tuple(rows)
    assert parse_compose_ps("\n".join(json.dumps(row) for row in rows)) == tuple(rows)


@pytest.mark.parametrize(
    "site_url",
    [
        "http://demo:secret@127.0.0.1:5173/ip-assets",
        "http://127.0.0.1:5173/ip-assets?token=secret",
        "http://127.0.0.1:5173/other",
    ],
)
def test_preflight_refuses_unsafe_site_urls(site_url: str) -> None:
    with pytest.raises(PreflightError, match="演示站点"):
        run_preflight(
            api_base="http://127.0.0.1:8000",
            site_url=site_url,
            runner=_runner,
            requester=lambda *_args: (_ for _ in ()).throw(AssertionError),
        )


@pytest.mark.parametrize(
    ("body", "cache_control", "etag", "vary"),
    [
        (
            b"not-webp",
            "private, max-age=604800, immutable",
            '"abc"',
            "X-IP-Profile-Token",
        ),
        (
            b"RIFF\x04\x00\x00\x00WEBP",
            "private, max-age=0, immutable",
            '"abc"',
            "X-IP-Profile-Token",
        ),
        (
            b"RIFF\x04\x00\x00\x00WEBP",
            "private, max-age=604800, immutable",
            'W/"abc"',
            "X-IP-Profile-Token",
        ),
        (
            b"RIFF\x04\x00\x00\x00WEBP",
            "private, max-age=604800, immutable",
            '"abc"',
            "Origin",
        ),
    ],
)
def test_preflight_rejects_invalid_thumbnail_contract(
    body: bytes, cache_control: str, etag: str, vary: str
) -> None:
    def requester(method: str, url: str, request_body: bytes | None) -> HttpResult:
        del method, request_body
        if url.endswith("/capabilities"):
            return _json_result(
                {
                    "enabled": True,
                    "authentication": "none",
                    "deployment_boundary": "company_intranet",
                    "semantic_search_available": True,
                    "generation_available": True,
                    "recognition_available": True,
                }
            )
        if url.endswith("?limit=16"):
            return _json_result(
                {
                    "items": [
                        {
                            "asset_ref": "ipa_11111111111111111111",
                            "status": "ready",
                            "thumbnail_url": (
                                "/api/v1/ip-assets/ipa_11111111111111111111/thumbnail?v=1"
                            ),
                        }
                    ]
                }
            )
        if "/thumbnail?v=1" in url:
            return HttpResult(
                status=200,
                headers={
                    "content-type": "image/webp",
                    "cache-control": cache_control,
                    "etag": etag,
                    "vary": vary,
                },
                body=body,
            )
        raise AssertionError(f"unexpected URL: {url}")

    with pytest.raises(PreflightError, match="缩略图"):
        run_preflight(
            api_base="http://127.0.0.1:8000",
            site_url="http://127.0.0.1:5173/ip-assets",
            runner=_runner,
            requester=requester,
        )


def _json_result(payload: object) -> HttpResult:
    return HttpResult(
        status=200,
        headers={"content-type": "application/json"},
        body=json.dumps(payload, ensure_ascii=False).encode(),
    )
