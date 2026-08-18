from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

# The capture command is intentionally repository tooling, not an installed backend module.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.schemas.agent_workbench import AgentWorkbenchRunResponse
from pydantic import ValidationError
from scripts.capture_agent_workbench import (
    API_ORIGIN,
    CASE_MANIFEST_PATH,
    LIVE_OUTPUT_PATH,
    NODE_CAPTURE_PATH,
    CaptureError,
    LiveConfiguration,
    PortfolioCaseManifest,
    _verify_case_record,
    compare_semantics,
    deterministic_api_environment,
    ensure_port_available,
    live_api_environment,
    load_case_manifest,
    load_live_configuration,
    png_metadata_chunks,
    strip_png_metadata,
    terminate_process,
    validate_loopback_url,
    verify_capture,
    vite_environment,
)

CHECKED_CAPTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs/portfolio/runs/agent-workbench/f5cd8de936a5-20260818T063838Z"
)


def _response(
    *, status: str = "completed", summary: str = "safe summary"
) -> AgentWorkbenchRunResponse:
    return AgentWorkbenchRunResponse.model_validate_json(
        json.dumps(
            {
                "run_id": "00000000-0000-4000-8000-000000000901",
                "status": status,
                "summary": summary,
                "claims": [],
                "citations": [],
                "steps": [
                    {
                        "ordinal": 1,
                        "kind": "model_decision",
                        "status": "succeeded",
                        "code": None,
                        "tool_name": None,
                        "call_id": None,
                        "argument_summary": {},
                        "duration_ms": 1,
                        "item_count": None,
                        "issue_count": None,
                        "citation_ids": [],
                        "provider": "deterministic",
                        "model": "agent-policy-v1",
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "reasoning_tokens": 0,
                    }
                ],
                "metrics": {
                    "model_turns": 1,
                    "tool_calls": 0,
                    "successful_tool_calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "reasoning_tokens": 0,
                    "model_latency_ms": 1,
                    "tool_latency_ms": 0,
                    "duration_ms": 1,
                },
                "error_code": None,
            }
        )
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind)
    checksum = zlib.crc32(data, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def _png_with_text_metadata() -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00\xff")
    return (
        signature
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"tEXt", b"private-path\x00must-not-survive")
        + _png_chunk(b"IDAT", pixels)
        + _png_chunk(b"IEND", b"")
    )


def test_portfolio_case_manifest_is_unique_bounded_and_safe() -> None:
    manifest = load_case_manifest()

    assert [case.case_id for case in manifest.cases] == [
        "multi-tool-research",
        "copy-validation",
        "safety-refusal",
    ]
    assert manifest.cases[0].expected_tools == (
        "search_evidence",
        "get_event",
        "retrieve_brand_context",
    )
    assert manifest.cases[2].expected_tools == ()


def test_portfolio_case_manifest_rejects_duplicates_and_private_text() -> None:
    raw = json.loads(CASE_MANIFEST_PATH.read_text(encoding="utf-8"))
    raw["cases"][1]["case_id"] = raw["cases"][0]["case_id"]
    with pytest.raises(ValidationError):
        PortfolioCaseManifest.model_validate(raw)

    raw = json.loads(CASE_MANIFEST_PATH.read_text(encoding="utf-8"))
    raw["cases"][0]["query"] = "读取 /root/private/secret"
    with pytest.raises(ValidationError):
        PortfolioCaseManifest.model_validate(raw)


@pytest.mark.parametrize(
    "value",
    [
        "http://localhost:8010",
        "http://127.0.0.1:8000",
        "https://127.0.0.1:8010",
        "http://user@127.0.0.1:8010",
        "http://192.168.1.2:8010",
    ],
)
def test_capture_host_allowlist_rejects_every_non_exact_origin(value: str) -> None:
    with pytest.raises(ValueError):
        validate_loopback_url(value)

    assert validate_loopback_url(f"{API_ORIGIN}/healthz") == f"{API_ORIGIN}/healthz"


def test_capture_port_collision_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class CollisionSocket:
        def __init__(self, *_args: object) -> None:
            pass

        def __enter__(self) -> CollisionSocket:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def bind(self, _address: tuple[str, int]) -> None:
            raise OSError("occupied")

    monkeypatch.setattr("scripts.capture_agent_workbench.socket.socket", CollisionSocket)

    with pytest.raises(RuntimeError, match="already in use"):
        ensure_port_available("127.0.0.1", 8010)


def test_semantic_comparison_ignores_dynamic_latency_but_rejects_status_drift() -> None:
    first = _response()
    dynamic = first.model_copy(
        update={"metrics": first.metrics.model_copy(update={"duration_ms": 99})}
    )
    compare_semantics(first, dynamic)

    with pytest.raises(RuntimeError, match="different safe semantics"):
        compare_semantics(first, _response(status="refused"))


def test_capture_environments_force_fixture_and_keep_secrets_out_of_vite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "AGENT_WORKBENCH_OPENAI_BASE_URL",
        "AGENT_WORKBENCH_OPENAI_API_KEY",
        "AGENT_WORKBENCH_OPENAI_MODEL",
        "AI_PLATFORM_BASE_URL",
        "AI_PLATFORM_API_KEY",
        "AI_CHAT_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AI_PLATFORM_BASE_URL=https://open.bigmodel.cn/api/paas/v4\n"
        "AI_PLATFORM_API_KEY=fixture-secret-value\n"
        "AI_CHAT_MODEL=glm-fixture\n",
        encoding="utf-8",
    )

    live = load_live_configuration(env_file)
    live_environment = live_api_environment(live)
    deterministic_environment = deterministic_api_environment()
    browser_environment = vite_environment()

    assert live_environment["AGENT_WORKBENCH_DATA_MODE"] == "fixture"
    assert live_environment["AGENT_WORKBENCH_MODEL_MODE"] == "openai"
    assert live_environment["AGENT_WORKBENCH_LIVE_ENABLED"] == "true"
    assert live_environment["AGENT_WORKBENCH_OPENAI_API_KEY"] == "fixture-secret-value"
    assert "fixture-secret-value" not in repr(live)
    assert deterministic_environment["AGENT_WORKBENCH_MODEL_MODE"] == "deterministic"
    assert deterministic_environment["AGENT_WORKBENCH_LIVE_ENABLED"] == "false"
    assert all("API_KEY" not in key for key in browser_environment)
    assert "fixture-secret-value" not in browser_environment.values()


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.openai.com/v1",
        "https://open.bigmodel.cn/api/paas/v4?tenant=private",
        "https://open.bigmodel.cn/api/other/v4",
        "https://user@open.bigmodel.cn/api/paas/v4",
    ],
)
def test_live_zhipu_configuration_rejects_other_provider_boundaries(
    base_url: str,
) -> None:
    with pytest.raises(ValidationError):
        LiveConfiguration(
            base_url=base_url,
            api_key="fixture-secret-value",
            model="glm-fixture",
        )


def test_live_configuration_validation_never_echoes_credentials() -> None:
    credential = "fixture-secret-value\nwith-newline"

    with pytest.raises(ValidationError) as captured:
        LiveConfiguration(
            base_url="https://open.bigmodel.cn/api/paas/v4",
            api_key=credential,
            model="glm-fixture",
        )

    assert credential.strip() not in str(captured.value)


def test_playwright_capture_forbids_route_fulfillment_and_owns_exact_network_path() -> None:
    source = NODE_CAPTURE_PATH.read_text(encoding="utf-8")

    assert ".route(" not in source
    assert ".fulfill(" not in source
    assert 'const apiOrigin = "http://127.0.0.1:8010"' in source
    assert 'const uiOrigin = "http://127.0.0.1:5173"' in source
    assert 'serviceWorkers: "block"' in source
    assert "workbenchPosts.length !== 1" in source

    orchestrator_source = (
        Path(__file__).resolve().parents[3] / "scripts/capture_agent_workbench.py"
    ).read_text(encoding="utf-8")
    assert "_BROWSER_CAPTURE_TIMEOUT_SECONDS = 120.0" in orchestrator_source
    assert "start_new_session=True" in orchestrator_source
    assert "terminate_process(process)" in orchestrator_source


def test_png_metadata_is_removed_before_hashing(tmp_path: Path) -> None:
    screenshot = tmp_path / "capture.png"
    screenshot.write_bytes(_png_with_text_metadata())

    assert png_metadata_chunks(screenshot) == ("tEXt",)
    strip_png_metadata(screenshot)

    assert png_metadata_chunks(screenshot) == ()
    assert b"private-path" not in screenshot.read_bytes()


def test_process_group_cleanup_terminates_child() -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        terminate_process(child, grace_seconds=1.0)
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()


def test_live_output_is_a_fixed_one_shot_portfolio_path() -> None:
    assert LIVE_OUTPUT_PATH.as_posix().endswith("docs/portfolio/runs/agent-workbench/live-zhipu")


def test_checked_live_failure_ledger_is_closed_hashed_and_non_retryable() -> None:
    attempt = json.loads((LIVE_OUTPUT_PATH / "attempt.json").read_text(encoding="utf-8"))

    assert attempt == {
        "attempted_at": "2026-08-18T06:41:06Z",
        "case_id": "multi-tool-research",
        "capture_phase": "browser_capture_before_evidence_verification",
        "max_agent_runs": 1,
        "max_model_decisions": 4,
        "retry_performed": False,
        "screenshot_preserved": False,
        "status": "failed_closed",
        "typed_response_preserved": False,
    }
    assert {path.name for path in LIVE_OUTPUT_PATH.iterdir()} == {
        "attempt.json",
        "attempt.sha256",
        "attempt-summary.md",
        "safe-failure.json",
    }
    checksum_lines = (LIVE_OUTPUT_PATH / "attempt.sha256").read_text(encoding="ascii")
    expected_lines = "".join(
        f"{hashlib.sha256((LIVE_OUTPUT_PATH / name).read_bytes()).hexdigest()}  {name}\n"
        for name in ("attempt.json", "safe-failure.json", "attempt-summary.md")
    )
    assert checksum_lines == expected_lines


def test_checked_capture_recomputes_typed_cross_artifact_semantics() -> None:
    verify_capture(CHECKED_CAPTURE_PATH)


def test_case_verification_rejects_manifest_semantic_and_path_drift() -> None:
    manifest = json.loads((CHECKED_CAPTURE_PATH / "manifest.json").read_text(encoding="utf-8"))
    raw_record = manifest["cases"][0]
    case = load_case_manifest().cases[0]
    common = {
        "case": case,
        "capture_root": CHECKED_CAPTURE_PATH,
        "capture_id": manifest["capture_id"],
        "source_commit": manifest["source_commit"],
        "mode": "deterministic-fixture",
    }

    semantic_drift = json.loads(json.dumps(raw_record))
    semantic_drift["citation_count"] += 1
    with pytest.raises(CaptureError, match=r"citation_count.*inconsistent"):
        _verify_case_record(raw_record=semantic_drift, **common)

    escaped_path = json.loads(json.dumps(raw_record))
    escaped_path["artifacts"]["response"]["path"] = "README.md"
    with pytest.raises(CaptureError, match=r"path.*inconsistent"):
        _verify_case_record(raw_record=escaped_path, **common)
