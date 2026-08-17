#!/usr/bin/env python3
"""Network-free regression harness for controlled-ocr-fixture-runner.py."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx
from PIL import Image
from pydantic import SecretStr

RUNNER_PATH = Path(__file__).with_name("controlled-ocr-fixture-runner.py")
EXPECTED = ("赛先生科学", "人工智能", "理解智能如何学习与反馈")
SENTINELS = (
    "private-api-key-sentinel",
    "private-body-sentinel",
    "private-exception-sentinel",
    "private-provider-id-sentinel",
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("controlled_ocr_fixture_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        ai_provider_mode="zhipu",
        ai_platform_base_url="https://provider.invalid/api/paas/v4",
        ai_platform_api_key=SecretStr("private-api-key-sentinel"),
        image_ocr_model="glm-ocr",
        ai_connect_timeout_seconds=1.0,
        image_ocr_timeout_seconds=2.0,
        image_ocr_max_input_bytes=10 * 1024 * 1024,
        image_ocr_max_response_bytes=1024 * 1024,
    )


def _response(*, invalid: bool = False) -> dict[str, object]:
    labels = (EXPECTED[0], EXPECTED[1], EXPECTED[2])
    boxes = ([102, 102, 922, 205], [102, 410, 922, 512], [102, 716, 922, 819])
    layout = [
        {
            "index": index,
            "label": "unknown-private-body-sentinel" if invalid and index == 1 else "text",
            "bbox_2d": boxes[index],
            "content": labels[index],
            "height": 1024,
            "width": 1024,
        }
        for index in range(3)
    ]
    return {
        "id": "private-provider-id-sentinel",
        "created": 1,
        "model": "glm-ocr",
        "layout_details": [layout],
        "data_info": {"num_pages": 1, "pages": [{"width": 1024, "height": 1024}]},
        "md_results": "private-body-sentinel",
        "layout_visualization": [],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "request_id": "private-provider-id-sentinel",
    }


def _fixture(root: Path) -> Path:
    path = root / "fixture.png"
    Image.new("RGB", (16, 16), (20, 54, 96)).save(path, format="PNG")
    path.chmod(0o600)
    return path


def _invoke(path: Path, handler) -> tuple[int, dict[str, object], str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    argv = ["--fixture", str(path)]
    for line in EXPECTED:
        argv.extend(("--expected-line", line))
    with contextlib.redirect_stderr(stderr):
        code = RUNNER.main(
            argv,
            transport=httpx.MockTransport(handler),
            settings_factory=_settings,
            stdout=stdout,
        )
    raw = stdout.getvalue()
    assert raw.count("\n") == 1 and raw.endswith("\n")
    report = json.loads(raw)
    assert list(report) == [
        "schema_version",
        "stage",
        "http_attempts",
        "outcome",
        "typed_error_code",
        "issue_codes",
        "exact_ordered",
        "accepted_line_count",
    ]
    for sentinel in SENTINELS:
        assert sentinel not in raw and sentinel not in stderr.getvalue()
    return code, report, raw, stderr.getvalue()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="controlled-ocr-runner-test-") as temporary:
        root = Path(temporary)
        fixture = _fixture(root)

        valid_code, valid, _raw, valid_stderr = _invoke(
            fixture, lambda request: httpx.Response(200, request=request, json=_response())
        )
        assert valid_code == 0
        assert valid == {
            "schema_version": 1,
            "stage": "terminal",
            "http_attempts": 1,
            "outcome": "pass",
            "typed_error_code": "",
            "issue_codes": [],
            "exact_ordered": True,
            "accepted_line_count": 3,
        }
        assert valid_stderr == ""

        invalid_code, invalid, *_ = _invoke(
            fixture,
            lambda request: httpx.Response(200, request=request, json=_response(invalid=True)),
        )
        assert invalid_code != 0 and invalid["http_attempts"] == 1
        assert invalid["typed_error_code"] == "invalid_provider_output"
        assert invalid["issue_codes"] == ["image_ocr_contract_label_unknown"]

        missing_code, missing, *_ = _invoke(
            root / "missing.png",
            lambda _request: (_ for _ in ()).throw(AssertionError("HTTP must not start")),
        )
        assert missing_code != 0 and missing["http_attempts"] == 0
        assert missing["stage"] == "before_request"
        assert missing["typed_error_code"] == "fixture_not_found"

        def transport_error(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("private-exception-sentinel", request=request)

        timeout_code, timeout, *_ = _invoke(fixture, transport_error)
        assert timeout_code != 0 and timeout["http_attempts"] == 1
        assert timeout["stage"] == "request_started"
        assert timeout["typed_error_code"] == "provider_timeout"

        def unexpected(_request: httpx.Request) -> httpx.Response:
            raise RuntimeError("private-exception-sentinel")

        unexpected_code, unexpected_report, unexpected_raw, unexpected_stderr = _invoke(
            fixture, unexpected
        )
        assert unexpected_code != 0 and unexpected_report["http_attempts"] == 1
        assert unexpected_report["typed_error_code"] == "unexpected_error"
        assert unexpected_stderr == ""
        assert "private-exception-sentinel" not in unexpected_raw

    print(
        "test_passed cases=official-raw-bbox,typed-invalid,missing-preflight,"
        "transport-error,unexpected-safe,one-json,secret-body-stderr-redaction,max-attempts-one"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
