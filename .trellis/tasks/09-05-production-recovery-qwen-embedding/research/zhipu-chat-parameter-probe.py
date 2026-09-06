"""Release-bound zero/one-call nonprivate Zhipu chat parameter diagnostic; no DB or send."""

from __future__ import annotations

# ruff: noqa: RUF001
import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter_ns
from typing import NoReturn

import app
import httpx
import structlog
from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.ai.copy_generation import _ZhipuStructuredCopyClient
from app.infrastructure.ai.zhipu import _read_bounded_response

RELEASE = "5c560da71bcbb61b765d3fe82c742cf2d5e676e1"
SOURCE_SHA256 = "70105e3d9fcbc4db75a879d1e44af357f3d182b2cbdbcebbddcae6bbbe51ec86"
PROMPT = 'Return exactly this JSON object: {"ok":true}'
MAX_RESPONSE_BYTES = 32768
# Reviewed official business codes: https://docs.bigmodel.cn/cn/api/api-code (2026-09-05).
OFFICIAL_ERROR_CODES = frozenset(
    {
        "1000",
        "1001",
        "1003",
        "1005",
        "1113",
        "1200",
        "1210",
        "1211",
        "1212",
        "1213",
        "1214",
        "1215",
        "1220",
        "1221",
        "1222",
        "1230",
        "1234",
        "1261",
        "1301",
        "1302",
        "1305",
        "1308",
        "1309",
        "1310",
        "1311",
        "1313",
        "1314",
        "1315",
        "1316",
        "1317",
        "1318",
        "1319",
        "1320",
        "1321",
    }
)
SAFE_ERRORS = frozenset(
    {
        "arguments_invalid",
        "release_mismatch",
        "source_mismatch",
        "config_mismatch",
        "provider_config_mismatch",
        "provider_endpoint_invalid",
        "live_identity_required",
        "http_call_denied",
        "response_invalid",
        "response_limit",
        "success_shape_invalid",
        "provider_request_rejected",
        "provider_authentication_failed",
        "provider_rate_limited",
        "provider_unavailable",
        "provider_timeout",
        "invalid_provider_output",
        "probe_timeout",
    }
)


class ProbeError(Exception):
    pass


@dataclass(frozen=True)
class Options:
    release: str
    live: bool = False
    max_http_calls: int = 0
    expected_config: str | None = None

    def validate(self) -> None:
        if self.release != RELEASE:
            raise ProbeError("release_mismatch")
        if self.max_http_calls != (1 if self.live else 0):
            raise ProbeError("arguments_invalid")
        if self.expected_config is not None and not re.fullmatch(
            "[0-9a-f]{64}", self.expected_config
        ):
            raise ProbeError("arguments_invalid")
        if self.live and self.expected_config is None:
            raise ProbeError("live_identity_required")


@dataclass
class Report:
    schema: str = "zhipu-chat-parameter-probe-v1"
    release: str = RELEASE
    source_sha256: str | None = None
    config_sha256: str | None = None
    mode: str = "dry_run"
    outcome: str = "not_started"
    error_code: str | None = None
    http_status: int | None = None
    business_error_code: str | None = None
    http_calls: int = 0
    response_bytes: int = 0
    strict_ok: bool | None = None
    latency_ms: int = 0


def verify_source(root: Path) -> None:
    # Same pure source contract as the prior canary, deliberately without importing its DB code.
    rows: list[str] = []
    for path in sorted(root.rglob("*.py"), key=lambda p: p.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if (
            path.is_symlink()
            or any(p.is_symlink() for p in path.parents)
            or (not re.fullmatch(r"[A-Za-z0-9_./-]+", relative) or path.stat().st_size > 2_000_000)
        ):
            raise ProbeError("source_mismatch")
        rows.append(f"{relative} {hashlib.sha256(path.read_bytes()).hexdigest()}\n")
    if len(rows) != 253 or hashlib.sha256("".join(rows).encode()).hexdigest() != SOURCE_SHA256:
        raise ProbeError("source_mismatch")


def config_fingerprint(settings: Settings) -> str:
    fields = (
        "app_env",
        "ai_provider_mode",
        "ai_chat_model",
        "copy_max_output_tokens",
        "ai_max_input_characters",
        "ai_connect_timeout_seconds",
        "ai_read_timeout_seconds",
        "ai_total_timeout_seconds",
        "ai_provider_concurrency",
        "ai_max_attempts",
        "ai_max_validation_corrections",
        "content_copy_provider_required",
    )
    payload = {name: getattr(settings, name) for name in fields}
    payload["endpoint_sha256"] = hashlib.sha256(
        (settings.ai_platform_base_url or "").encode()
    ).hexdigest()
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate_config(settings: Settings, options: Options, report: Report) -> None:
    report.config_sha256 = config_fingerprint(settings)
    if options.expected_config and options.expected_config != report.config_sha256:
        raise ProbeError("config_mismatch")
    if (
        settings.app_env != "production"
        or settings.ai_provider_mode != "zhipu"
        or settings.ai_chat_model != "glm-5.2"
        or settings.copy_max_output_tokens != 2048
        or settings.ai_max_input_characters != 40000
        or not settings.content_copy_provider_required
        or not settings.ai_platform_base_url
        or not settings.ai_platform_api_key
    ):
        raise ProbeError("provider_config_mismatch")
    try:
        endpoint = httpx.URL(settings.ai_platform_base_url)
    except httpx.InvalidURL:
        raise ProbeError("provider_endpoint_invalid") from None
    if (
        endpoint.scheme != "https"
        or not endpoint.host
        or (endpoint.query or endpoint.fragment or endpoint.userinfo)
    ):
        raise ProbeError("provider_endpoint_invalid")


def strict_json(body: bytes | str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ProbeError("response_invalid")
            result[key] = value
        return result

    def constant(value: str) -> NoReturn:
        raise ProbeError("response_invalid")

    try:
        return json.loads(body, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ProbeError("response_invalid") from None


def official_error_code(body: bytes) -> str:
    try:
        value = strict_json(body)
    except ProbeError:
        return "other_code"
    if not isinstance(value, dict) or not isinstance(value.get("error"), dict):
        return "other_code"
    code = value["error"].get("code")
    if type(code) is int:
        code = str(code)
    return code if isinstance(code, str) and code in OFFICIAL_ERROR_CODES else "other_code"


class OneRequestTransport(httpx.AsyncBaseTransport):
    def __init__(
        self, inner: httpx.AsyncBaseTransport, settings: Settings, options: Options, report: Report
    ) -> None:
        self.inner, self.settings, self.options, self.report = inner, settings, options, report

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        expected_url = httpx.URL(
            f"{(self.settings.ai_platform_base_url or '').rstrip('/')}/chat/completions"
        )
        if (
            not self.options.live
            or self.options.max_http_calls != 1
            or self.report.http_calls
            or (request.method != "POST" or request.url != expected_url)
        ):
            raise ProbeError("http_call_denied")
        expected_payload = {
            "model": self.settings.ai_chat_model,
            "messages": [
                {"role": "system", "content": "只返回严格JSON，不输出Markdown或解释。"},
                {"role": "user", "content": PROMPT},
            ],
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": 2048,
        }
        if strict_json(request.content) != expected_payload:
            raise ProbeError("http_call_denied")
        self.report.http_calls += 1
        response = await self.inner.handle_async_request(request)
        self.report.http_status = response.status_code
        response.request = request
        try:
            # Reuse the deployed gzip/raw bounded reader on all statuses, before the normal
            # copy adapter intentionally discards non-success bodies. No raw body survives output.
            bounded = await _read_bounded_response(response, max_response_bytes=MAX_RESPONSE_BYTES)
        finally:
            await response.aclose()
        self.report.response_bytes = len(bounded.content)
        if not 200 <= response.status_code < 300:
            self.report.business_error_code = official_error_code(bounded.content)
            return httpx.Response(response.status_code, content=b"", request=request)
        return bounded

    async def aclose(self) -> None:
        await self.inner.aclose()


async def exercise(
    settings: Settings, options: Options, report: Report, client: httpx.AsyncClient
) -> None:
    if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
        raise ProbeError("provider_config_mismatch")
    structured = _ZhipuStructuredCopyClient(
        client=client,
        base_url=settings.ai_platform_base_url,
        api_key=settings.ai_platform_api_key,
        model=settings.ai_chat_model,
        connect_timeout_seconds=settings.ai_connect_timeout_seconds,
        read_timeout_seconds=settings.ai_read_timeout_seconds,
        total_timeout_seconds=settings.ai_total_timeout_seconds,
        concurrency=settings.ai_provider_concurrency,
        max_attempts=1,
        max_input_characters=settings.ai_max_input_characters,
        max_output_tokens=settings.copy_max_output_tokens,
        max_validation_corrections=0,
    )
    if not options.live:
        report.outcome = "preflight_passed_live_unverified"
        return
    content, _, _ = await structured.complete(
        prompt=PROMPT, output_tokens=settings.copy_max_output_tokens
    )
    value = strict_json(content)
    if not isinstance(value, dict) or set(value) != {"ok"} or value["ok"] is not True:
        report.strict_ok = False
        raise ProbeError("success_shape_invalid")
    report.strict_ok, report.outcome = True, "fixed_request_passed"


async def run(options: Options) -> Report:
    report, started = Report(), perf_counter_ns()
    try:
        options.validate()
        report.mode = "live_one_call" if options.live else "dry_run"
        verify_source(Path(app.__file__).parent)
        report.source_sha256 = SOURCE_SHA256
        settings = Settings()
        validate_config(settings, options, report)
        transport = OneRequestTransport(
            httpx.AsyncHTTPTransport(retries=0, trust_env=False), settings, options, report
        )
        async with httpx.AsyncClient(
            transport=transport, follow_redirects=False, trust_env=False
        ) as client:
            async with asyncio.timeout(60):
                await exercise(settings, options, report, client)
    except (ProbeError, AppError) as error:
        code = error.code if isinstance(error, AppError) else str(error)
        report.outcome, report.error_code = (
            "failed",
            code if code in SAFE_ERRORS else "probe_internal_error",
        )
    except TimeoutError:
        report.outcome, report.error_code = "failed", "probe_timeout"
    except Exception:
        report.outcome, report.error_code = "failed", "probe_internal_error"
    report.latency_ms = max(0, (perf_counter_ns() - started) // 1_000_000)
    return report


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ProbeError("arguments_invalid")


def parse_args(argv: list[str]) -> Options:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--live-one-call", action="store_true")
    parser.add_argument("--max-http-calls", type=int, default=0)
    parser.add_argument("--expected-config-sha256")
    args = parser.parse_args(argv)
    options = Options(
        args.expected_release, args.live_one_call, args.max_http_calls, args.expected_config_sha256
    )
    options.validate()
    return options


def main(argv: list[str] | None = None) -> int:
    logging.disable(logging.CRITICAL)
    structlog.configure(processors=[lambda *args: (_ for _ in ()).throw(structlog.DropEvent())])
    try:
        report = asyncio.run(run(parse_args(sys.argv[1:] if argv is None else argv)))
    except ProbeError:
        report = Report(outcome="failed", error_code="arguments_invalid")
    print(json.dumps(asdict(report), sort_keys=True))
    return (
        0 if report.outcome in {"preflight_passed_live_unverified", "fixed_request_passed"} else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
