from __future__ import annotations

# ruff: noqa: RUF001
import ast
import gzip
import importlib.util
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

import app
import httpx
import pytest
from app.core.config import Settings
from app.core.errors import AppError
from pydantic import SecretStr

SCRIPT = Path(__file__).with_name("zhipu-chat-parameter-probe.py")
spec = importlib.util.spec_from_file_location("chat_parameter_probe", SCRIPT)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)
PRIVATE = "private_sentinel_message_body_key"


def settings():
    return Settings(_env_file=None, ai_provider_mode="fake").model_copy(
        update={
            "app_env": "production",
            "ai_provider_mode": "zhipu",
            "ai_chat_model": "glm-5.2",
            "copy_max_output_tokens": 2048,
            "ai_max_input_characters": 40000,
            "content_copy_provider_required": True,
            "ai_platform_base_url": "https://example.test/api",
            "ai_platform_api_key": SecretStr(PRIVATE),
        }
    )


def options(live=False):
    return probe.Options(
        probe.RELEASE,
        live,
        1 if live else 0,
        probe.config_fingerprint(settings()) if live else None,
    )


def test_default_zero_and_bad_cli_redaction(capsys):
    assert probe.parse_args(["--expected-release", probe.RELEASE]) == options()
    with pytest.raises(probe.ProbeError, match="arguments_invalid"):
        probe.parse_args(["--expected-release", probe.RELEASE, "--api-key", PRIVATE])
    assert PRIVATE not in capsys.readouterr().err


@pytest.mark.parametrize(
    "changes",
    [
        {"release": "0" * 40},
        {"live": True},
        {"max_http_calls": 1},
        {"max_http_calls": 2},
        {"expected_config": PRIVATE},
    ],
)
def test_live_requires_exact_cap_and_config(changes):
    with pytest.raises(probe.ProbeError):
        replace(options(), **changes).validate()


def test_exact_source_and_drift(tmp_path):
    probe.verify_source(Path(app.__file__).parent)
    with pytest.raises(probe.ProbeError, match="source_mismatch"):
        probe.verify_source(tmp_path)


@pytest.mark.parametrize(
    "change",
    [
        {"ai_chat_model": "another-model"},
        {"copy_max_output_tokens": 1},
        {"ai_max_input_characters": 50000},
        {"ai_provider_mode": "fake"},
        {"app_env": "test"},
    ],
)
def test_config_drift_before_http(change):
    with pytest.raises(probe.ProbeError, match="config_mismatch"):
        probe.validate_config(settings().model_copy(update=change), options(True), probe.Report())


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"code": PRIVATE, "message": PRIVATE}},
        {"error": {"code": True, "message": PRIVATE}},
        {"error": {"code": {"nested": PRIVATE}, "message": PRIVATE}},
        {"code": "1210", "message": PRIVATE},
        [PRIVATE],
    ],
)
def test_error_code_untrusted_projection(body):
    assert probe.official_error_code(json.dumps(body).encode()) == "other_code"


def test_official_code_allowlist_and_duplicate_fields():
    assert probe.OFFICIAL_ERROR_CODES
    for code in probe.OFFICIAL_ERROR_CODES:
        assert (
            probe.official_error_code(
                json.dumps({"error": {"code": code, "message": PRIVATE}}).encode()
            )
            == code
        )
        assert (
            probe.official_error_code(json.dumps({"error": {"code": int(code)}}).encode()) == code
        )
    assert probe.official_error_code(b'{"error":{"code":"1210","code":"1234"}}') == "other_code"
    assert probe.official_error_code(b'{"error":{"code":NaN}}') == "other_code"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.test/api",
        "https:///api",
        "https://example.test/api?key=private",
        "https://example.test/api#private",
        "https://user:private@example.test/api",
    ],
)
def test_secure_endpoint_gate_before_constructor(endpoint):
    with pytest.raises(probe.ProbeError, match="provider_endpoint_invalid"):
        probe.validate_config(
            settings().model_copy(update={"ai_platform_base_url": endpoint}),
            options(),
            probe.Report(),
        )


async def execute_fixture(monkeypatch, *, live=True, status=200, body=None, timed_out=False):
    report, calls = probe.Report(), []
    body = (
        body
        if body is not None
        else json.dumps({"choices": [{"message": {"content": '{"ok":true}'}}]}).encode()
    )
    s, chosen = settings(), options(live)

    async def handler(req):
        calls.append(req)
        if timed_out:
            raise httpx.ReadTimeout(PRIVATE)
        return httpx.Response(status, content=body)

    transport = probe.OneRequestTransport(httpx.MockTransport(handler), s, chosen, report)
    async with httpx.AsyncClient(transport=transport) as client:
        try:
            await probe.exercise(s, chosen, report, client)
        except (probe.ProbeError, AppError) as error:
            report.error_code = error.code if isinstance(error, AppError) else str(error)
            report.outcome = "failed"
    return report, calls


@pytest.mark.asyncio
async def test_default_constructs_real_copy_client_without_http(monkeypatch):
    report, calls = await execute_fixture(monkeypatch, live=False)
    assert calls == [] and report.http_calls == 0
    assert report.outcome == "preflight_passed_live_unverified"


@pytest.mark.asyncio
async def test_one_fixed_request_reuses_exact_deployed_payload(monkeypatch):
    report, calls = await execute_fixture(monkeypatch)
    assert len(calls) == report.http_calls == 1 and report.strict_ok is True
    payload = json.loads(calls[0].content)
    assert payload == {
        "model": "glm-5.2",
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": "只返回严格JSON，不输出Markdown或解释。"},
            {"role": "user", "content": probe.PROMPT},
        ],
    }
    assert PRIVATE not in json.dumps(asdict(report))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503, 307])
async def test_non_success_bounded_safe_code_and_no_retries(monkeypatch, status):
    body = json.dumps(
        {"error": {"code": "1210", "message": PRIVATE}, "request_id": PRIVATE}
    ).encode()
    report, calls = await execute_fixture(monkeypatch, status=status, body=body)
    assert len(calls) == report.http_calls == 1 and report.http_status == status
    assert report.business_error_code == "1210" and report.outcome == "failed"
    assert PRIVATE not in json.dumps(asdict(report))


@pytest.mark.asyncio
async def test_timeout_counted_once(monkeypatch):
    report, calls = await execute_fixture(monkeypatch, timed_out=True)
    assert len(calls) == report.http_calls == 1 and report.error_code == "provider_timeout"
    assert PRIVATE not in json.dumps(asdict(report))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 400])
async def test_oversized_bodies_are_never_projected(monkeypatch, status):
    report, calls = await execute_fixture(monkeypatch, status=status, body=PRIVATE.encode() * 2000)
    assert len(calls) == report.http_calls == 1
    assert report.error_code == "invalid_provider_output" and report.business_error_code is None
    assert PRIVATE not in json.dumps(asdict(report))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        PRIVATE,
        '{"ok":"true"}',
        '{"ok":1}',
        '{"ok":false}',
        '{"ok":true,"other":"private_sentinel_message_body_key"}',
        '{"ok":true,"ok":true}',
    ],
)
async def test_success_content_is_strict_and_never_emitted(monkeypatch, content):
    body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    report, calls = await execute_fixture(monkeypatch, body=body)
    assert len(calls) == 1 and report.outcome == "failed"
    assert PRIVATE not in json.dumps(asdict(report))


@pytest.mark.asyncio
async def test_second_request_and_nonfixed_payload_denied_before_transport():
    report, calls, s = probe.Report(), [], settings()
    transport = probe.OneRequestTransport(
        httpx.MockTransport(lambda req: calls.append(req) or httpx.Response(200)),
        s,
        options(True),
        report,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(probe.ProbeError, match="http_call_denied"):
            await client.post(
                f"{s.ai_platform_base_url}/chat/completions", json={"model": "another"}
            )
        report.http_calls = 1
        with pytest.raises(probe.ProbeError, match="http_call_denied"):
            await client.post(f"{s.ai_platform_base_url}/chat/completions", json={})
    assert calls == []


@pytest.mark.asyncio
async def test_actual_second_completion_is_denied_after_one_success():
    report, calls, s = probe.Report(), [], settings()

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    transport = probe.OneRequestTransport(httpx.MockTransport(handler), s, options(True), report)
    async with httpx.AsyncClient(transport=transport) as client:
        await probe.exercise(s, options(True), report, client)
        with pytest.raises(probe.ProbeError, match="http_call_denied"):
            await probe.exercise(s, options(True), report, client)
    assert len(calls) == report.http_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [None, "999999999"])
async def test_streaming_error_body_bound_and_close(declared):
    class Body(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield PRIVATE.encode() * 2000

        async def aclose(self):
            self.closed = True

    body, report, s = Body(), probe.Report(), settings()

    def handler(req):
        headers = {"content-length": declared} if declared is not None else {}
        return httpx.Response(400, stream=body, headers=headers)

    transport = probe.OneRequestTransport(httpx.MockTransport(handler), s, options(True), report)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(AppError):
            await probe.exercise(s, options(True), report, client)
    assert report.http_calls == 1 and report.business_error_code is None and body.closed
    assert PRIVATE not in json.dumps(asdict(report))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["gzip_expansion", "gzip_truncated", "gzip_valid", "chunked_large"]
)
async def test_real_stream_decoding_is_bounded_and_always_closed(kind):
    normal = json.dumps({"error": {"code": "1210", "message": PRIVATE}}).encode()
    raw = gzip.compress(normal)
    if kind == "gzip_expansion":
        raw = gzip.compress(PRIVATE.encode() * 2000)
    elif kind == "gzip_truncated":
        raw = raw[:-5]
    elif kind == "chunked_large":
        raw = PRIVATE.encode() * 2000

    class Body(httpx.AsyncByteStream):
        closed = False
        yielded_bytes = 0

        async def __aiter__(self):
            for offset in range(0, len(raw), 4096):
                chunk = raw[offset : offset + 4096]
                self.yielded_bytes += len(chunk)
                yield chunk

        async def aclose(self):
            self.closed = True

    body, report, s = Body(), probe.Report(), settings()

    def handler(req):
        headers = {"content-encoding": "gzip"} if kind.startswith("gzip") else {}
        return httpx.Response(400, stream=body, headers=headers)

    transport = probe.OneRequestTransport(httpx.MockTransport(handler), s, options(True), report)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(AppError) as caught:
            await probe.exercise(s, options(True), report, client)
    assert report.http_calls == 1 and body.closed
    if kind == "gzip_valid":
        assert report.business_error_code == "1210"
        assert caught.value.code == "provider_request_rejected"
    else:
        assert report.business_error_code is None
        assert caught.value.code == "invalid_provider_output"
    assert body.yielded_bytes <= probe.MAX_RESPONSE_BYTES + 4096
    assert PRIVATE not in json.dumps(asdict(report))


@pytest.mark.asyncio
async def test_top_level_arbitrary_exception_redaction(monkeypatch):
    def fail(root):
        raise probe.ProbeError(PRIVATE)

    monkeypatch.setattr(probe, "verify_source", fail)
    report = await probe.run(options())
    assert report.error_code == "probe_internal_error" and PRIVATE not in json.dumps(asdict(report))


def test_no_business_side_effect_constructors_or_secret_cli():
    tree = ast.parse(SCRIPT.read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        any(
            word in module
            for word in (".db", "wecom", "image_generation", "brand_knowledge", "material_packages")
        )
        for module in imports
    )
    assert not any(
        node.attr in {"commit", "create_engine", "create_brand_embedding_model"}
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    )
