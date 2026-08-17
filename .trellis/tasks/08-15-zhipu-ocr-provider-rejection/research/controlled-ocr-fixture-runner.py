#!/usr/bin/env python3
"""One-shot, body-free controlled OCR evidence runner.

The CLI reads provider configuration only through ``Settings`` environment
loading. It always writes exactly one safe JSON line and never logs request or
response content. Test callers may inject an httpx transport and Settings
factory; the CLI has no switch that enables a fake transport.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import httpx

_PROJECT_BACKEND = Path(__file__).resolve().parents[4] / "backend"
if _PROJECT_BACKEND.is_dir():
    sys.path.insert(0, str(_PROJECT_BACKEND))

from app.application.ports.image_validation import ImageTextRecognitionRequest  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.errors import AppError, InvalidProviderOutputError  # noqa: E402
from app.infrastructure.ai.zhipu import ZhipuImageTextRecognizer  # noqa: E402

SCHEMA_VERSION = 1
MAX_ATTEMPTS = 1
_STAGES = frozenset(
    {
        "adapter_construction",
        "before_request",
        "request_started",
        "response_returned",
        "validation",
        "terminal",
    }
)
_SAFE_TYPED_ERROR_CODES = frozenset(
    {
        "",
        "configuration_invalid",
        "fixture_invalid",
        "fixture_not_found",
        "invalid_provider_output",
        "provider_authentication_failed",
        "provider_identity_mismatch",
        "provider_input_limit",
        "provider_rate_limited",
        "provider_request_rejected",
        "provider_timeout",
        "provider_unavailable",
        "runner_input_invalid",
        "unexpected_error",
    }
)
_SAFE_ISSUE_CODES = frozenset(
    {
        "duplicate_visual_text",
        "image_ocr_contract_bbox_range",
        "image_ocr_contract_bbox_scale",
        "image_ocr_contract_bbox_shape",
        "image_ocr_contract_content_limit",
        "image_ocr_contract_content_type",
        "image_ocr_contract_element_extra",
        "image_ocr_contract_formula_unsupported",
        "image_ocr_contract_index_duplicate",
        "image_ocr_contract_index_invalid",
        "image_ocr_contract_label_unknown",
        "image_ocr_contract_line_limit",
        "image_ocr_contract_page_count",
        "image_ocr_contract_page_dimensions",
        "image_ocr_contract_page_dimensions_conflict",
        "image_ocr_contract_schema_invalid",
        "image_ocr_contract_source_conflict",
        "image_ocr_contract_source_invalid",
        "image_ocr_contract_table_unsupported",
        "image_ocr_response_envelope_invalid",
        "invalid_expected_visual_text",
        "misordered_visual_text",
        "missing_visual_text",
        "unclassified_validation_issue",
        "unexpected_visual_text",
    }
)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValueError("runner input invalid")


@dataclass(slots=True)
class _AuditState:
    stage: str = "adapter_construction"
    http_attempts: int = 0
    outcome: str = "fail"
    typed_error_code: str = "unexpected_error"
    issue_codes: tuple[str, ...] = ()
    exact_ordered: bool = False
    accepted_line_count: int = 0

    def safe_report(self) -> dict[str, object]:
        stage = self.stage if self.stage in _STAGES else "terminal"
        typed = (
            self.typed_error_code
            if self.typed_error_code in _SAFE_TYPED_ERROR_CODES
            else "unexpected_error"
        )
        issues = tuple(
            dict.fromkeys(
                code if code in _SAFE_ISSUE_CODES else "unclassified_validation_issue"
                for code in self.issue_codes[:12]
                if isinstance(code, str)
            )
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": stage,
            "http_attempts": max(0, int(self.http_attempts)),
            "outcome": "pass" if self.outcome == "pass" else "fail",
            "typed_error_code": typed,
            "issue_codes": list(issues),
            "exact_ordered": bool(self.exact_ordered),
            "accepted_line_count": max(0, int(self.accepted_line_count)),
        }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = _SafeArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--expected-line", action="append", required=True)
    parsed = parser.parse_args(list(argv))
    if len(parsed.expected_line) != 3:
        raise ValueError("runner input invalid")
    if any(
        not isinstance(line, str)
        or not line.strip()
        or len(line) > 160
        or any(character in line for character in "\x00\r\n")
        for line in parsed.expected_line
    ):
        raise ValueError("runner input invalid")
    return parsed


def _load_fixture(path_value: str, maximum: int) -> tuple[bytes, str]:
    path = Path(path_value)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        raise FileNotFoundError from None
    if not path.is_absolute() or not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise ValueError("fixture invalid")
    if metadata.st_size < 1 or metadata.st_size > maximum:
        raise ValueError("fixture invalid")
    suffix = path.suffix.casefold()
    media_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(
        suffix
    )
    if media_type is None:
        raise ValueError("fixture invalid")
    payload = path.read_bytes()
    if len(payload) != metadata.st_size:
        raise ValueError("fixture invalid")
    return payload, media_type


def _settings_from_environment() -> Settings:
    return Settings(_env_file=None)


async def _run(
    argv: Sequence[str],
    state: _AuditState,
    *,
    transport: httpx.AsyncBaseTransport | None,
    settings_factory: Callable[[], Any],
) -> int:
    try:
        parsed = _parse_args(argv)
    except (TypeError, ValueError):
        state.typed_error_code = "runner_input_invalid"
        return 2

    state.stage = "adapter_construction"
    try:
        settings = settings_factory()
        if (
            settings.ai_provider_mode != "zhipu"
            or not settings.ai_platform_base_url
            or settings.ai_platform_api_key is None
            or settings.image_ocr_model != "glm-ocr"
        ):
            raise ValueError("configuration invalid")

        async def request_started(_request: httpx.Request) -> None:
            state.http_attempts += 1
            state.stage = "request_started"
            if state.http_attempts > MAX_ATTEMPTS:
                raise RuntimeError("attempt limit exceeded")

        async def response_returned(_response: httpx.Response) -> None:
            state.stage = "response_returned"

        client = httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            event_hooks={"request": [request_started], "response": [response_returned]},
        )
        async with client:
            adapter = ZhipuImageTextRecognizer(
                client=client,
                base_url=settings.ai_platform_base_url,
                api_key=settings.ai_platform_api_key,
                model=settings.image_ocr_model,
                connect_timeout_seconds=settings.ai_connect_timeout_seconds,
                read_timeout_seconds=settings.image_ocr_timeout_seconds,
                total_timeout_seconds=settings.image_ocr_timeout_seconds,
                concurrency=1,
                max_attempts=MAX_ATTEMPTS,
                max_input_bytes=settings.image_ocr_max_input_bytes,
                max_response_bytes=settings.image_ocr_max_response_bytes,
            )
            if getattr(adapter, "_max_attempts", None) != MAX_ATTEMPTS:
                raise RuntimeError("attempt contract drift")
            state.stage = "before_request"
            try:
                image_bytes, media_type = _load_fixture(
                    parsed.fixture, settings.image_ocr_max_input_bytes
                )
            except FileNotFoundError:
                state.typed_error_code = "fixture_not_found"
                return 2
            except (OSError, ValueError):
                state.typed_error_code = "fixture_invalid"
                return 2
            request = ImageTextRecognitionRequest(
                image_bytes=image_bytes,
                request_fingerprint="controlled-ocr-fixture-v1",
                expected_text=tuple(parsed.expected_line),
                media_type=media_type,
                require_order=True,
            )
            result = await adapter.recognize(request)
            state.stage = "validation"
            state.accepted_line_count = len(result.recognized_lines)
            state.exact_ordered = result.recognized_lines == tuple(parsed.expected_line)
            if not state.exact_ordered or state.accepted_line_count != 3:
                state.typed_error_code = "invalid_provider_output"
                state.issue_codes = ("unclassified_validation_issue",)
                return 1
    except AppError as error:
        state.typed_error_code = error.code
        if isinstance(error, InvalidProviderOutputError):
            state.issue_codes = tuple(error.issue_codes)
        return 1
    except (OSError, TypeError, ValueError):
        state.typed_error_code = "configuration_invalid"
        return 2
    except Exception:
        state.typed_error_code = "unexpected_error"
        return 1

    state.stage = "terminal"
    state.outcome = "pass"
    state.typed_error_code = ""
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    settings_factory: Callable[[], Any] = _settings_from_environment,
    stdout: Any = None,
) -> int:
    state = _AuditState()
    output = stdout if stdout is not None else sys.stdout
    try:
        exit_code = asyncio.run(
            _run(
                sys.argv[1:] if argv is None else argv,
                state,
                transport=transport,
                settings_factory=settings_factory,
            )
        )
    except Exception:
        state.typed_error_code = "unexpected_error"
        exit_code = 1
    report = state.safe_report()
    output.write(json.dumps(report, ensure_ascii=True, separators=(",", ":")) + "\n")
    output.flush()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
